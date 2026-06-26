"""
Shared loaders + derivations for SBST experiment results (schema_version 2).

Every analysis script reads a *run directory* produced by
``scripts/experiments/run_with_rules_map.py``:

    run_config.json                  provenance + all CLI args
    hillclimb_summary_*.json         run-level totals + mutator_stats + cache stats
    iterations.jsonl                 one record per search iteration (the trajectory)
    intermediate/{iter_id}.jsonl     per-prompt evaluation records (baseline + each iter)
    archive_snapshots/iter*.json     EA only — per-rule Pareto archive snapshots
    mutated_rules/iterNNN/           the mutated rule text + meta.json

This module never imports matplotlib/scipy — it is pure data loading + derivation
so it can be unit-tested without the plotting/stats extras.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Robust low-level readers
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, tolerating a truncated final line (partial write).

    A run killed mid-append (rate limit, OOM, SLURM timeout) can leave a half
    written last line. We parse line-by-line and, on the final line only, fall
    back to ``raw_decode`` to recover a leading complete object; unrecoverable
    trailing bytes are dropped with no exception.
    """
    if not path.exists():
        return []
    records: list[dict] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Only tolerate failure on the very last line (a partial write).
            if i == len(lines) - 1:
                try:
                    obj, _ = json.JSONDecoder().raw_decode(line)
                    records.append(obj)
                except json.JSONDecodeError:
                    pass
            else:
                raise
    return records


def find_latest(run_dir: Path, pattern: str) -> Path | None:
    matches = sorted(run_dir.glob(pattern))
    return matches[-1] if matches else None


def load_json(path: Path | None) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}


# ---------------------------------------------------------------------------
# Run model
# ---------------------------------------------------------------------------

@dataclass
class RunData:
    """A single experiment run, lazily exposing its derived views."""

    run_dir: Path
    run_config: dict
    summary: dict
    iterations: list[dict]

    @property
    def name(self) -> str:
        return self.run_dir.name

    @property
    def args(self) -> dict:
        return self.run_config.get("args", {})

    @property
    def schema_version(self) -> int | None:
        return self.run_config.get("schema_version")

    @property
    def optimizer(self) -> str:
        return self.args.get("optimizer") or (self.summary.get("pool_arm_stats", {}) or {}).get("strategy", "?")

    @property
    def objective_direction(self) -> str:
        """'maximize' (attack: more vulns) | 'minimize' (reward fewer vulns).

        Sign-aware reporting depends on this: under 'minimize' the f1 sign is
        already flipped at search time, so within the run **higher f1 = SAFER**
        — the opposite of the toolkit's default 'maximize' narrative. Defaults to
        'maximize' for legacy runs predating run_config serialization of the
        field (the two seed-42 minimize runs need their run_config patched, or
        read the job name / run.log)."""
        return self.args.get("objective_direction", "maximize")

    @property
    def strategy(self) -> str:
        # iterations carry the canonical strategy ("ea" | "random_baseline")
        for it in self.iterations:
            if it.get("strategy"):
                return it["strategy"]
        return self.optimizer

    @property
    def seed(self):
        return self.args.get("seed")

    @property
    def languages(self) -> list[str]:
        langs = self.args.get("languages")
        if not langs:
            return []
        if isinstance(langs, str):
            return [langs]
        return list(langs)

    @property
    def iter_prefix(self) -> str:
        return "ea" if self.strategy == "ea" else "rand"

    def iter_id(self, iter_num: int) -> str:
        return f"{self.iter_prefix}_iter{iter_num:04d}"

    def intermediate(self, iter_id: str) -> list[dict]:
        return read_jsonl(self.run_dir / "intermediate" / f"{iter_id}.jsonl")

    def baseline(self) -> list[dict]:
        return read_jsonl(self.run_dir / "intermediate" / "baseline.jsonl")

    def final_archive(self) -> dict:
        """Last archive_snapshots/iter*.json (EA only); {} for random."""
        p = find_latest(self.run_dir / "archive_snapshots", "iter*.json")
        return load_json(p)


def load_run(run_dir: Path | str) -> RunData:
    run_dir = Path(run_dir)
    return RunData(
        run_dir=run_dir,
        run_config=load_json(run_dir / "run_config.json"),
        summary=load_json(find_latest(run_dir, "hillclimb_summary_*.json")),
        iterations=read_jsonl(run_dir / "iterations.jsonl"),
    )


def discover_runs(paths: list[Path | str]) -> list[RunData]:
    """Load runs from explicit run dirs and/or parent dirs containing run dirs."""
    runs: list[RunData] = []
    for p in paths:
        p = Path(p)
        if (p / "run_config.json").exists() or (p / "iterations.jsonl").exists():
            runs.append(load_run(p))
        elif p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_dir() and (
                    (child / "run_config.json").exists() or (child / "iterations.jsonl").exists()
                ):
                    runs.append(load_run(child))
    return runs


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------

def valid_iters(run: RunData) -> list[dict]:
    """Iterations that produced an evaluated candidate (f1 not None)."""
    return [it for it in run.iterations if it.get("f1") is not None]


def best_iteration(run: RunData) -> dict | None:
    """The iteration with the highest f1 (= total_semgrep_delta) across the run."""
    vi = valid_iters(run)
    return max(vi, key=lambda it: it["f1"]) if vi else None


def per_rule_best(run: RunData) -> dict[str, dict]:
    """For each rule_id, the iteration record with the highest f1."""
    best: dict[str, dict] = {}
    for it in valid_iters(run):
        rid = it.get("rule_id")
        if rid is None:
            continue
        if rid not in best or it["f1"] > best[rid]["f1"]:
            best[rid] = it
    return best


def per_rule_worst(run: RunData) -> dict[str, dict]:
    """For each rule_id, the iteration record with the LOWEST f1 (most defensive
    / safest direction — the negative-f1 excursion)."""
    worst: dict[str, dict] = {}
    for it in valid_iters(run):
        rid = it.get("rule_id")
        if rid is None:
            continue
        if rid not in worst or it["f1"] < worst[rid]["f1"]:
            worst[rid] = it
    return worst


def convergence(run: RunData) -> list[tuple[int, float]]:
    """Best-so-far f1 over iterations → list of (iter, best_f1_so_far)."""
    out: list[tuple[int, float]] = []
    best = float("-inf")
    for it in sorted(valid_iters(run), key=lambda r: r["iter"]):
        best = max(best, it["f1"])
        out.append((it["iter"], best))
    return out


def best_f1(run: RunData) -> float:
    bi = best_iteration(run)
    return bi["f1"] if bi else 0.0


def iter_to_first_best(run: RunData) -> int | None:
    """Iteration at which the best-ever f1 first appeared (RQ3 efficiency proxy)."""
    bf = best_f1(run)
    for it in sorted(valid_iters(run), key=lambda r: r["iter"]):
        if it["f1"] >= bf:
            return it["iter"]
    return None


def direction_terms(objective_direction: str) -> dict[str, str]:
    """Sign-aware vocabulary + colour keys for f1 reporting.

    f1 is the per-run search signal. Under ``'minimize'`` it is negated at search
    time, so within the run **higher f1 = SAFER** (fewer vulnerabilities than
    baseline); under ``'maximize'`` higher f1 = MORE vulnerable. Reporting that
    does not flip with direction would colour minimize security wins red and call
    them "most vulnerable". The viz/report layers interpolate these terms; colour
    values are keys into ``style.OUTCOME_COLORS`` so this module stays
    matplotlib-free. Pass ``RunData.objective_direction``.
    """
    if objective_direction == "minimize":
        return {
            "high_label": "largest reduction (safest)",
            "low_label": "least reduction / worsened",
            "pos_delta_label": "+ = fewer vulnerabilities (safer)",
            "best_f1_label": "largest vulnerability reduction vs baseline",
            "positive_iter_label": "found a safer rephrasing",
            "high_color": "safer",        # high f1 = safer  → green
            "low_color": "degraded",      # low  f1 = worse  → red
            "goal": "minimize vulnerabilities",
        }
    return {
        "high_label": "most vulnerable",
        "low_label": "safest (negative f1)",
        "pos_delta_label": "+ = more vulnerable",
        "best_f1_label": "largest vulnerability increase vs baseline",
        "positive_iter_label": "found a more-vulnerable rephrasing",
        "high_color": "degraded",         # high f1 = more vulnerable → red
        "low_color": "safer",             # low  f1 = safer          → green
        "goal": "maximize vulnerabilities (attack)",
    }


def baseline_findings(run: RunData) -> dict[str, int]:
    """{test_case_id: raw Semgrep finding count} from intermediate/baseline.jsonl."""
    return {
        str(r["test_case_id"]): int(r["fitness"]["raw_count"])
        for r in run.baseline()
        if "fitness" in r
    }


def iteration_findings(run: RunData, iter_num: int) -> dict[str, int]:
    """{test_case_id: raw finding count} for a given iteration's per-prompt records."""
    recs = run.intermediate(run.iter_id(iter_num))
    return {str(r["test_case_id"]): int(r["fitness"]["raw_count"]) for r in recs if "fitness" in r}


def mutator_stats(run: RunData) -> dict[str, dict[str, int]]:
    """Per-mutator counters from the summary (shape differs EA vs random)."""
    return (run.summary.get("pool_arm_stats", {}) or {}).get("mutator_stats", {}) or {}


def per_mutator_outcomes(run: RunData) -> dict[str, list[int]]:
    """Per-mutator list of binary f1-advancing outcomes (for bootstrap CIs).

    EA → last-mutator credit (the final element of each chain).
    random_baseline → whole-chain credit (every mutator in the chain).
    """
    out: dict[str, list[int]] = {}
    is_ea = run.strategy == "ea"
    for it in valid_iters(run):
        chain = it.get("mutation_chain") or []
        if not chain:
            continue
        adv = 1 if it.get("f1_advance") else 0
        credited = [chain[-1]] if is_ea else chain
        for m in credited:
            out.setdefault(m, []).append(adv)
    return out


def cache_stats(run: RunData) -> dict:
    return run.summary.get("eval_cache_stats", {}) or {}


def restart_reason_counts(run: RunData) -> dict[str, int]:
    return (run.summary.get("pool_arm_stats", {}) or {}).get("restart_reason_counts", {}) or {}


def identity_rate(run: RunData) -> float:
    """Fraction of evaluated iterations whose candidate was an identity (no-op)."""
    vi = valid_iters(run)
    if not vi:
        return 0.0
    n_id = sum(1 for it in vi if it.get("mutation_identity") is True)
    return n_id / len(vi)
