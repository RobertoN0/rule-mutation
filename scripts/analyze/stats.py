"""
Statistical-test helpers for the SBST result analysis (reporting-plan §5).

Thin wrappers over scipy/numpy that degrade gracefully on the small / degenerate
samples typical of these experiments (all-zero deltas, single seed, etc.): they
return a result object with ``p`` = None and a ``note`` rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence

import numpy as np


@dataclass
class TestResult:
    name: str
    statistic: float | None
    p: float | None
    n: int
    note: str = ""

    def __str__(self) -> str:
        if self.p is None:
            return f"{self.name}: n={self.n} — {self.note or 'not computable'}"
        return f"{self.name}: stat={self.statistic:.4g}, p={self.p:.4g}, n={self.n}"


def wilcoxon_paired(baseline: Sequence[float], treatment: Sequence[float]) -> TestResult:
    """Wilcoxon signed-rank on paired observations (RQ1 per-prompt findings)."""
    from scipy import stats

    a, b = np.asarray(baseline, float), np.asarray(treatment, float)
    n = len(a)
    diffs = b - a
    nz = int(np.count_nonzero(diffs))
    if n == 0 or nz == 0:
        return TestResult("Wilcoxon signed-rank", None, None, n,
                          note="no non-zero differences (no change between baseline and treatment)")
    try:
        res = stats.wilcoxon(a, b)
        return TestResult("Wilcoxon signed-rank", float(res.statistic), float(res.pvalue), n)
    except ValueError as e:
        return TestResult("Wilcoxon signed-rank", None, None, n, note=str(e))


def mcnemar_binary(baseline_pos: Sequence[bool], treatment_pos: Sequence[bool]) -> TestResult:
    """McNemar exact test on the paired binary 'has >=1 finding' outcome (RQ1)."""
    from scipy import stats

    a = np.asarray(baseline_pos, bool)
    b = np.asarray(treatment_pos, bool)
    n = len(a)
    b01 = int(np.sum(~a & b))   # baseline negative → treatment positive (newly vulnerable)
    b10 = int(np.sum(a & ~b))   # baseline positive → treatment negative
    discordant = b01 + b10
    if discordant == 0:
        return TestResult("McNemar exact", None, None, n,
                          note=f"no discordant pairs (b01={b01}, b10={b10})")
    # Exact McNemar = two-sided binomial on the discordant pairs.
    res = stats.binomtest(b01, discordant, 0.5, alternative="two-sided")
    return TestResult("McNemar exact", float(b01 - b10), float(res.pvalue), n,
                      note=f"newly_vuln={b01}, lost_vuln={b10}")


def sign_test(deltas: Sequence[float]) -> TestResult:
    """Exact paired sign test on non-zero within-pair deltas."""
    from scipy import stats

    d = np.asarray(deltas, float)
    n = len(d)
    pos = int(np.sum(d > 0))
    neg = int(np.sum(d < 0))
    nz = pos + neg
    if nz == 0:
        return TestResult("Sign test", None, None, n, note="all deltas zero (tie)")
    res = stats.binomtest(pos, nz, 0.5, alternative="two-sided")
    return TestResult("Sign test", float(pos - neg), float(res.pvalue), n,
                      note=f"pos={pos}, neg={neg}")


def ttest_paired(baseline: Sequence[float], treatment: Sequence[float]) -> TestResult:
    """Paired t-test on paired observations (e.g. per-seed totals, norules vs withrules).

    Parametric counterpart to the sign / Wilcoxon tests: uses the magnitude of each
    paired difference and assumes the differences are roughly normal. Degrades
    gracefully on <2 pairs or zero-variance differences (returns p=None + note).
    Statistic sign follows ``treatment - baseline`` (negative → treatment lower).
    """
    from scipy import stats

    a, b = np.asarray(baseline, float), np.asarray(treatment, float)
    n = len(a)
    if n < 2:
        return TestResult("Paired t-test", None, None, n, note="need >=2 pairs")
    diffs = b - a
    if np.allclose(diffs, diffs[0]):
        return TestResult("Paired t-test", None, None, n,
                          note="zero variance in differences (all pairs identical delta)")
    res = stats.ttest_rel(b, a)
    return TestResult("Paired t-test", float(res.statistic), float(res.pvalue), n)


def friedman_test(*conditions: Sequence[float]) -> TestResult:
    """Friedman test — non-parametric repeated-measures ANOVA across >=3 related
    conditions measured on the same blocks (RQ1/RQ3 aggregate across coding tasks).

    Each ``conditions[i]`` is one condition's value per block (e.g. per coding
    task), so all conditions must share the same length (the blocks are matched
    rows). With exactly 2 conditions Friedman is undefined and reduces to the
    Wilcoxon/sign test — use those instead. Degrades gracefully (p=None + note)
    on <3 conditions, mismatched lengths, <2 blocks, or zero within-block variance
    (all conditions identical on every block).
    """
    from scipy import stats

    k = len(conditions)
    arrs = [np.asarray(c, float) for c in conditions]
    n = arrs[0].size if arrs else 0
    if k < 3:
        return TestResult("Friedman", None, None, n,
                          note=f"need >=3 conditions (got {k}); 2 conditions -> use Wilcoxon/sign")
    if any(a.size != n for a in arrs):
        return TestResult("Friedman", None, None, n, note="conditions have mismatched lengths")
    if n < 2:
        return TestResult("Friedman", None, None, n, note="need >=2 blocks (tasks)")
    stacked = np.vstack(arrs)               # k x n
    if np.allclose(stacked.max(axis=0), stacked.min(axis=0)):
        return TestResult("Friedman", None, None, n,
                          note="no within-block variance (all conditions identical on every task)")
    try:
        res = stats.friedmanchisquare(*arrs)
        return TestResult("Friedman", float(res.statistic), float(res.pvalue), n,
                          note=f"k={k} conditions, n={n} blocks")
    except ValueError as e:
        return TestResult("Friedman", None, None, n, note=str(e))


def mann_whitney_u(a: Sequence[float], b: Sequence[float],
                   alternative: str = "two-sided") -> TestResult:
    """Mann-Whitney U for two genuinely independent samples.

    Do not use this helper when arms share a seed-specific initialization bundle
    or otherwise form matched pairs; preserve that pairing with a paired test.
    """
    from scipy import stats

    x, y = np.asarray(a, float), np.asarray(b, float)
    n = len(x) + len(y)
    if len(x) == 0 or len(y) == 0:
        return TestResult("Mann-Whitney U", None, None, n, note="empty sample")
    try:
        res = stats.mannwhitneyu(x, y, alternative=alternative)
        return TestResult("Mann-Whitney U", float(res.statistic), float(res.pvalue), n,
                          note=f"n_a={len(x)}, n_b={len(y)}, alt={alternative}")
    except ValueError as e:
        return TestResult("Mann-Whitney U", None, None, n, note=str(e))


def vargha_delaney_a12(a: Sequence[float], b: Sequence[float]) -> tuple[float, str]:
    """Unpaired Vargha-Delaney Â₁₂ effect size.

    Â₁₂ = P(a > b) + 0.5·P(a == b): the probability a randomly chosen run from
    ``a`` beats one from ``b``. 0.5 = no difference; >0.5 = ``a`` tends larger.
    Magnitude (distance from 0.5): <0.06 negligible, <0.14 small, <0.21 medium,
    else large. Returns (a12, magnitude). It discards matching and therefore
    must not be substituted for a paired common-language effect.
    """
    from scipy import stats

    x, y = np.asarray(a, float), np.asarray(b, float)
    m, k = len(x), len(y)
    if m == 0 or k == 0:
        return (float("nan"), "n/a")
    ranks = stats.rankdata(np.concatenate([x, y]))
    r1 = float(ranks[:m].sum())
    a12 = (r1 / m - (m + 1) / 2) / k
    d = abs(a12 - 0.5)
    mag = ("negligible" if d < 0.06 else "small" if d < 0.14
           else "medium" if d < 0.21 else "large")
    return (float(a12), mag)


def cliffs_delta(treatment: Sequence[float], baseline: Sequence[float]) -> tuple[float, str]:
    """Unpaired Cliff's delta. δ = P(t>b) − P(t<b) ∈ [−1, 1]; equals
    2·Â₁₂ − 1. |δ| thresholds (Romano 2006): <0.147 negligible, <0.33 small,
    <0.474 medium, else large. Returns (delta, magnitude).
    """
    t, b = np.asarray(treatment, float), np.asarray(baseline, float)
    if t.size == 0 or b.size == 0:
        return (float("nan"), "n/a")
    gt = int((t[:, None] > b[None, :]).sum())
    lt = int((t[:, None] < b[None, :]).sum())
    delta = (gt - lt) / (t.size * b.size)
    ad = abs(delta)
    mag = ("negligible" if ad < 0.147 else "small" if ad < 0.33
           else "medium" if ad < 0.474 else "large")
    return (float(delta), mag)


def bootstrap_ci(outcomes: Sequence[float], n_boot: int = 10000, ci: float = 0.95,
                 seed: int = 0) -> tuple[float, float, float]:
    """Bootstrap CI for the mean of a sample (e.g. per-mutator effective rate).

    Returns (point_estimate, lo, hi). Degenerate samples return (mean, mean, mean).
    """
    x = np.asarray(outcomes, float)
    if x.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    point = float(x.mean())
    if x.size == 1:
        return (point, point, point)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n_boot, x.size))
    means = x[idx].mean(axis=1)
    lo = float(np.quantile(means, (1 - ci) / 2))
    hi = float(np.quantile(means, 1 - (1 - ci) / 2))
    return (point, lo, hi)


def wilson_ci(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (point_estimate, lo, hi). Empty samples return NaN values.
    """
    if n <= 0:
        return (float("nan"), float("nan"), float("nan"))
    phat = successes / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return (phat, lo, hi)
