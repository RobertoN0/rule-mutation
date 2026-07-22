"""Small retained loader layer for schema-2 compatibility helpers.

The full schema-2 report stack was removed, but `build_repair_overrides.py` and
the compatibility tests still need these pure IO/derivation helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    """Read JSONL, tolerating a truncated final line from an interrupted write."""
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


@dataclass
class RunData:
    """A single historical experiment run, lazily exposing derived views."""

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
        return self.args.get("optimizer") or (
            self.summary.get("pool_arm_stats", {}) or {}
        ).get("strategy", "?")

    @property
    def objective_direction(self) -> str:
        return self.args.get("objective_direction", "maximize")

    @property
    def strategy(self) -> str:
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
    runs: list[RunData] = []
    for p in paths:
        p = Path(p)
        if (p / "run_config.json").exists() or (p / "iterations.jsonl").exists():
            runs.append(load_run(p))
        elif p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_dir() and (
                    (child / "run_config.json").exists()
                    or (child / "iterations.jsonl").exists()
                ):
                    runs.append(load_run(child))
    return runs


def valid_iters(run: RunData) -> list[dict]:
    return [it for it in run.iterations if it.get("f1") is not None]


def best_iteration(run: RunData) -> dict | None:
    vi = valid_iters(run)
    return max(vi, key=lambda it: it["f1"]) if vi else None


def per_rule_best(run: RunData) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for it in valid_iters(run):
        rid = it.get("rule_id")
        if rid is None:
            continue
        if rid not in best or it["f1"] > best[rid]["f1"]:
            best[rid] = it
    return best


def per_rule_worst(run: RunData) -> dict[str, dict]:
    worst: dict[str, dict] = {}
    for it in valid_iters(run):
        rid = it.get("rule_id")
        if rid is None:
            continue
        if rid not in worst or it["f1"] < worst[rid]["f1"]:
            worst[rid] = it
    return worst


def convergence(run: RunData) -> list[tuple[int, float]]:
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
    bf = best_f1(run)
    for it in sorted(valid_iters(run), key=lambda r: r["iter"]):
        if it["f1"] >= bf:
            return it["iter"]
    return None


def direction_terms(objective_direction: str) -> dict[str, str]:
    if objective_direction == "minimize":
        return {
            "high_label": "largest reduction (safest)",
            "low_label": "least reduction / worsened",
            "pos_delta_label": "+ = fewer vulnerabilities (safer)",
            "best_f1_label": "largest vulnerability reduction vs baseline",
            "positive_iter_label": "found a safer rephrasing",
            "high_color": "safer",
            "low_color": "degraded",
            "goal": "minimize vulnerabilities",
        }
    return {
        "high_label": "most vulnerable",
        "low_label": "safest (negative f1)",
        "pos_delta_label": "+ = more vulnerable",
        "best_f1_label": "largest vulnerability increase vs baseline",
        "positive_iter_label": "found a more-vulnerable rephrasing",
        "high_color": "degraded",
        "low_color": "safer",
        "goal": "maximize vulnerabilities (attack)",
    }


def baseline_findings(run: RunData) -> dict[str, int]:
    return {
        str(r["test_case_id"]): int(r["fitness"]["raw_count"])
        for r in run.baseline()
        if "fitness" in r
    }


def iteration_findings(run: RunData, iter_num: int) -> dict[str, int]:
    recs = run.intermediate(run.iter_id(iter_num))
    return {
        str(r["test_case_id"]): int(r["fitness"]["raw_count"])
        for r in recs
        if "fitness" in r
    }


def mutator_stats(run: RunData) -> dict[str, dict[str, int]]:
    return (run.summary.get("pool_arm_stats", {}) or {}).get("mutator_stats", {}) or {}


def per_mutator_outcomes(run: RunData) -> dict[str, list[int]]:
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
    return (run.summary.get("pool_arm_stats", {}) or {}).get(
        "restart_reason_counts", {}
    ) or {}


def identity_rate(run: RunData) -> float:
    vi = valid_iters(run)
    if not vi:
        return 0.0
    n_id = sum(1 for it in vi if it.get("mutation_identity") is True)
    return n_id / len(vi)
