#!/usr/bin/env python
"""Shared loaders and statistics for the v2 analysis suite.

READ-ONLY with respect to the frozen repo: every path under REPO is opened for
reading and nothing is ever written there. All output goes to OUT.

Frozen commit: 09b6b963d47abbf1348f8dab10b5dbc97813c5ce
"""
from __future__ import annotations

import glob
import itertools
import json
import math
import os
from pathlib import Path

# A fresh checkout defaults to itself and its published results. Override the
# two environment variables when running against an unpacked copy of the raw
# DelftBlue archive or writing a separate result set.
DEFAULT_REPO = Path(__file__).resolve().parents[2]
REPO = os.environ.get("RULE_MUTATION_REPO", str(DEFAULT_REPO))
OUT = Path(os.environ.get("ANALYSIS_OUT", str(DEFAULT_REPO / "analysis/results")))
SAFE_ZONE_AUDIT = OUT / "search_safe_zone_audit.json"

# All 80 finished search runs live under one directory per model. The old
# wave1/wave2 split carried no meaning and was removed 2026-08-04; Llama seed 10
# was folded into 03_search_runs/llama/arms once its jobs finished.
ARM_ROOTS = [
    f"{REPO}/experiments/03_search_runs/qwen/arms",
    f"{REPO}/experiments/03_search_runs/llama/arms",
]

MUTATORS = [
    "add_random_word",
    "negation_injection",
    "paraphrase",
    "section_reorder_degrade",
    "section_reorder_shuffle",
    "synonym_replacement",
    "verb_weakening",
    "voice_change",
]


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def perm_test_paired(d, max_n=22):
    """Exact two-sided sign-flip permutation test on paired differences."""
    n = len(d)
    if n == 0:
        return 1.0, "empty"
    if n > max_n:
        raise ValueError(f"n={n} too large to enumerate")
    obs = abs(sum(d) / n)
    cnt = sum(
        1
        for signs in itertools.product((1, -1), repeat=n)
        if abs(sum(s * x for s, x in zip(signs, d)) / n) >= obs - 1e-12
    )
    return cnt / 2 ** n, f"exact, {2 ** n} sign assignments"


def sign_test(d):
    pos = sum(1 for x in d if x > 0)
    neg = sum(1 for x in d if x < 0)
    n = pos + neg
    if n == 0:
        return 1.0, pos, neg
    p = sum(math.comb(n, k) for k in range(min(pos, neg) + 1)) / 2 ** n * 2
    return min(1.0, p), pos, neg


def _walsh(d):
    return sorted((d[i] + d[j]) / 2 for i in range(len(d)) for j in range(i, len(d)))


def hodges_lehmann(d):
    w = _walsh(d)
    m = len(w)
    return w[m // 2] if m % 2 else (w[m // 2 - 1] + w[m // 2]) / 2


def hl_ci(d, alpha=0.05):
    """Distribution-free CI for the one-sample / paired HL estimator."""
    w = _walsh(d)
    n = len(d)
    counts = {}
    for signs in itertools.product((0, 1), repeat=n):
        k = sum(r for r, s in zip(range(1, n + 1), signs) if s)
        counts[k] = counts.get(k, 0) + 1
    tot = 2 ** n
    cum = 0
    kq = 0
    for key in sorted(counts):
        cum += counts[key]
        if cum / tot > alpha / 2:
            kq = key
            break
    lo = w[kq] if kq < len(w) else w[0]
    hi = w[len(w) - 1 - kq] if kq < len(w) else w[-1]
    return lo, hi


def a12(x, y):
    """Vargha-Delaney A12: P(x > y) + 0.5 P(x == y)."""
    gt = sum(1 for a in x for b in y if a > b)
    eq = sum(1 for a in x for b in y if a == b)
    return (gt + 0.5 * eq) / (len(x) * len(y))


def a12_label(v):
    d = abs(v - 0.5)
    if d < 0.06:
        return "negligible"
    if d < 0.14:
        return "small"
    if d < 0.21:
        return "medium"
    return "large"


def holm(pv, alpha=0.05):
    """Holm-Bonferroni step-down. Returns name -> (p, threshold, reject)."""
    items = sorted(pv.items(), key=lambda kv: kv[1])
    m = len(items)
    out = {}
    prev = True
    for i, (name, p) in enumerate(items):
        thr = alpha / (m - i)
        rej = prev and p <= thr
        prev = rej
        out[name] = (p, thr, rej)
    return out


def bootstrap_ci(d, n_boot=20000, seed=12345):
    import random

    rng = random.Random(seed)
    n = len(d)
    means = sorted(sum(rng.choice(d) for _ in range(n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


def bootstrap_median_ci(d, n_boot=20000, seed=12345):
    """Deterministic percentile-bootstrap CI for a sample median.

    This is an estimation interval, not an exact small-sample confidence
    interval.  Callers must label it as a percentile-bootstrap interval.
    """
    import random
    import statistics

    rng = random.Random(seed)
    n = len(d)
    medians = sorted(
        statistics.median(rng.choice(d) for _ in range(n))
        for _ in range(n_boot)
    )
    return medians[int(0.025 * n_boot)], medians[int(0.975 * n_boot)]


def paired_superiority(d):
    """Paired common-language effect: P(delta>0) + 0.5*P(delta=0)."""
    if not d:
        return float("nan")
    return (
        sum(1 for value in d if value > 0)
        + 0.5 * sum(1 for value in d if value == 0)
    ) / len(d)


def mannwhitney_p(x, y, n_perm=20000, seed=7):
    """Two-sided permutation p for an unpaired difference in means."""
    import random

    rng = random.Random(seed)
    obs = abs(sum(x) / len(x) - sum(y) / len(y))
    pool = list(x) + list(y)
    nx = len(x)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(pool)
        if abs(sum(pool[:nx]) / nx - sum(pool[nx:]) / (len(pool) - nx)) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)


# --------------------------------------------------------------------------- #
# run discovery
# --------------------------------------------------------------------------- #
def load_runs():
    """strata[<model>_<lang>][seed][ea|rand] -> dict of run-level facts."""
    strata: dict = {}
    for root in ARM_ROOTS:
        for cell_dir in sorted(glob.glob(f"{root}/*/")):
            cell = Path(cell_dir).name
            jobs = glob.glob(f"{cell_dir}/job*")
            if not jobs:
                continue
            d = jobs[0]
            try:
                v = json.load(open(f"{d}/search_validation.json"))
                s = json.load(open(f"{d}/search_summary.json"))
                c = json.load(open(f"{d}/run_config.json"))
            except FileNotFoundError:
                continue
            # model comes from the CELL NAME, never the directory root, so a Llama
            # run living under a wave dir cannot be mislabelled as Qwen
            parts = cell.split("_")  # <model>_<lang>_s<seed>_<tag>
            if len(parts) < 4:
                continue
            model, lang, tag = parts[0], parts[1], parts[3]
            if model not in ("qwen", "llama") or lang not in ("python", "java"):
                continue
            seed = int(parts[2][1:])
            strata.setdefault(f"{model}_{lang}", {}).setdefault(seed, {})[tag] = dict(
                cell=cell,
                dir=d,
                status=v["status"],
                fse=v["final_search_eligible"],
                term=v["completion"]["termination_reason"],
                E=s["num_evaluations_completed"],
                f1=float(s["raw_findings_reduction"]),
                wred=float(s["weighted_score_reduction"]),
                orig=s["original_raw_findings"],
                best=s["best_raw_findings"],
                orig_w=s.get("original_weighted_score"),
                invalid=s.get("best_num_invalid_prompts"),
                bundle=c["args"].get("initialization_bundle_content_sha256"),
                n_cases=c["args"].get("n_cases"),
            )
    return strata


def gated_pairs(strata):
    """Yield (stratum, seed, ea, rand) for pairs passing every eligibility gate."""
    excluded = []
    kept = {}
    for key in sorted(strata):
        for seed in sorted(strata[key]):
            p = strata[key][seed]
            if "ea" not in p or "rand" not in p:
                excluded.append(f"{key} s{seed}: incomplete pair")
                continue
            e, r = p["ea"], p["rand"]
            bad = [
                lbl
                for lbl, x in (("ea", e), ("rand", r))
                if x["status"] != "VALID"
                or not x["fse"]
                or x["term"] != "wall_time_limit"
            ]
            if bad:
                excluded.append(f"{key} s{seed}: {bad} failed gates")
                continue
            if e["bundle"] != r["bundle"]:
                excluded.append(f"{key} s{seed}: bundle mismatch")
                continue
            kept.setdefault(key, []).append((seed, e, r))
    return kept, excluded


def safe_zone_gated_pairs(strata, audit_path=SAFE_ZONE_AUDIT):
    """Return eligible pairs with each arm's best *structurally valid* result.

    This is deliberately a separate loader: the original summaries remain the
    record of what the unconstrained searches reported.  Replacing ``f1`` here
    implements a post-hoc sensitivity filter only; it does not reconstruct the
    trajectory of a search whose archive had rejected invalid candidates.
    """
    kept, excluded = gated_pairs(strata)
    audit = json.loads(Path(audit_path).read_text())
    rows = {
        (row["stratum"], int(row["seed"]), row["optimizer"]): row
        for row in audit["runs"]
    }
    strict = {}
    for key, pairs in kept.items():
        for seed, ea, rand in pairs:
            converted = []
            for optimizer, source in (("ea", ea), ("rand", rand)):
                row = rows.get((key, seed, optimizer))
                if row is None:
                    excluded.append(f"{key} s{seed} {optimizer}: missing safe-zone audit")
                    converted = []
                    break
                if Path(row["run_dir"]).resolve() != Path(source["dir"]).resolve():
                    excluded.append(f"{key} s{seed} {optimizer}: audit path mismatch")
                    converted = []
                    break
                if abs(float(row["reported_best_f1"]) - float(source["f1"])) > 1e-9:
                    excluded.append(f"{key} s{seed} {optimizer}: audit score mismatch")
                    converted = []
                    break
                target = dict(source)
                target.update(
                    reported_f1=float(source["f1"]),
                    reported_wred=float(source["wred"]),
                    f1=float(row["strict_best_f1"]),
                    strict_best_evaluation_index=int(
                        row["strict_best_evaluation_index"]
                    ),
                    strict_best_chromosome_id=row["strict_best_chromosome_id"],
                    safe_zone_invalid_fraction=row["invalid_fraction"],
                    safe_zone_invalid_evaluations=row["n_structurally_invalid"],
                    reported_minus_strict=float(row["reported_minus_strict"]),
                )
                strict_weighted = row.get("strict_best_weighted_reduction")
                if strict_weighted is None:
                    strict_weighted = _evaluation_weighted_reduction(
                        source["dir"], target["strict_best_evaluation_index"]
                    )
                target["wred"] = float(strict_weighted)
                converted.append(target)
            if converted:
                strict.setdefault(key, []).append((seed, converted[0], converted[1]))
    return strict, excluded


def _evaluation_weighted_reduction(run_dir, evaluation_index):
    if evaluation_index == 0:
        return 0.0
    for record in iter_evaluations(run_dir):
        if int(record["evaluation_index"]) == evaluation_index:
            value = record.get("weighted_reduction")
            if value is None:
                raise ValueError(
                    f"evaluation {evaluation_index} in {run_dir} has no weighted_reduction"
                )
            return float(value)
    raise ValueError(f"evaluation {evaluation_index} not found in {run_dir}")


def iter_evaluations(run_dir):
    """Yield parsed records from evaluations.jsonl."""
    with open(f"{run_dir}/evaluations.jsonl") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_gene_paths(run_dir):
    """evaluation_index -> {rule_id: [mutator, ...]} from mutated_rules/*/meta.json."""
    out = {}
    for meta in sorted(glob.glob(f"{run_dir}/mutated_rules/evaluation_*/meta.json")):
        try:
            m = json.load(open(meta))
        except (json.JSONDecodeError, OSError):
            continue
        out[int(m["evaluation_index"])] = m.get("gene_paths") or {}
    return out


def write(name, text):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text)
    print(f"wrote {OUT / name}")
