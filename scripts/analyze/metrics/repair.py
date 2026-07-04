"""
Vulnerability-repair metrics (minimize direction) — RQ1 per-task before/after and
RQ3 aggregate global-repair, built on the validated outcome envelope.

For one finished run, a coding task's
  BEFORE = baseline (original rules, temp-0 deterministic), and
  AFTER  = the safest (minimum weighted_score / raw_count) observed across every
           iteration that mutated a rule attached to that task.
Both are sign-unambiguous finding COUNTS (lower = safer), so a repair is
``delta = before - after >= 0``. This sidesteps the f1 negation entirely.

Caveat (temp-0): AFTER is the best repair the SEARCH FOUND in the explored
rephrasing space (existence), not a temp>0 generalization claim — per-task
significance across replicates is Stage-2 (bd-011). Multi-rule prompts are
repaired by mutating ONE of their rules at a time (rules are never jointly
mutated), so AFTER is the best single-rule rephrasing for that task.

Pure compute: no plotting, minimal IO (only the per-model baseline-class CSV).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import loaders as L
from metrics import outcomes as O

# --- per-model baseline subset membership -----------------------------------
# Green-light is Qwen-only: subsets come from Qwen's own 40-seed baseline
# (`qwen_class` in baseline_common_<lang>.csv), NOT the Qwen-Llama intersection.
# Each model is paired with its own baseline; the column is switchable so a later
# Llama run can key on `llama_class` without touching callers.
#   NEVER      — never vulnerable across the 40 baseline runs (the floor)
#   PERSISTENT — vulnerable in >=80% of runs even with the rule present
#   VARIABLE   — the finding comes and goes across seeds (the borderline band)
#   RULE_FIXED — vulnerable without the rule but rarely with it

_LANG_ALIASES = {"python": "python", "py": "python", "java": "java", "ja": "java"}
DEFAULT_SUBSET_DIR = Path("experiments/analysis/bl40_final_full_analysis")
CLASS_COL = "qwen_class"  # switch to "llama_class" for a Llama repair run
SUBSETS = ("full", "movable", "persistent", "variable", "never")


def load_subset_classes(language: str, subset_dir: Path = DEFAULT_SUBSET_DIR,
                        class_col: str = CLASS_COL) -> dict[str, str]:
    """tid -> per-model baseline class from baseline_common_<lang>.csv.

    ``class_col`` selects the model column (default ``qwen_class``). Values are
    'NEVER' | 'PERSISTENT' | 'VARIABLE' | 'RULE_FIXED'.
    """
    lang = _LANG_ALIASES.get(language.lower(), language.lower())
    path = Path(subset_dir) / f"baseline_common_{lang}.csv"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out[str(row["tid"])] = row.get(class_col, "")
    return out


# --- per-task before/after rows -------------------------------------------------


@dataclass
class TaskRow:
    run: str
    strategy: str  # 'ea' | 'rand'
    seed: object
    language: str
    tid: str
    cwe: str
    klass: str  # model-robust common_class, or '' if unknown
    before_raw: int
    after_raw: int
    before_score: float
    after_score: float
    observations: int
    ever_down: bool

    @property
    def delta_raw(self) -> int:
        return self.before_raw - self.after_raw

    @property
    def delta_score(self) -> float:
        return self.before_score - self.after_score

    @property
    def movable(self) -> bool:
        return self.before_raw > 0

    @property
    def repaired(self) -> bool:
        """Driven from >=1 finding to zero findings."""
        return self.before_raw > 0 and self.after_raw == 0


def task_rows(run: L.RunData, code_divergence_threshold: float = 0.0,
              subset_dir: Path = DEFAULT_SUBSET_DIR) -> list[TaskRow]:
    """One row per coding task (prompt) with baseline vs safest-observed findings."""
    ro = O.build_run_outcome(run, code_divergence_threshold)
    states = O.states_for_scope(ro, "prompt")
    lang = run.languages[0] if run.languages else "?"
    classes = load_subset_classes(lang, subset_dir)
    tag = "ea" if run.strategy == "ea" else "rand"
    rows: list[TaskRow] = []
    for s in states:
        after_raw = s.min_raw if s.min_raw is not None else s.baseline_raw
        after_score = s.min_score if s.min_score is not None else s.baseline_score
        rows.append(TaskRow(
            run=run.name, strategy=tag, seed=run.seed, language=lang,
            tid=s.test_case_id, cwe=s.cwe_id, klass=classes.get(s.test_case_id, ""),
            before_raw=s.baseline_raw, after_raw=after_raw,
            before_score=s.baseline_score, after_score=after_score,
            observations=s.observations, ever_down=s.ever_down,
        ))
    return rows


def pool_best_across_seeds(rows_by_seed: list[list[TaskRow]]) -> list[TaskRow]:
    """Collapse N per-seed runs into one row per task, keeping the safest after."""
    best: dict[str, TaskRow] = {}
    for rows in rows_by_seed:
        for r in rows:
            cur = best.get(r.tid)
            if cur is None or r.after_score < cur.after_score:
                best[r.tid] = TaskRow(
                    run=f"{r.strategy}_pooled", strategy=r.strategy, seed="pooled",
                    language=r.language, tid=r.tid, cwe=r.cwe, klass=r.klass,
                    before_raw=r.before_raw, after_raw=r.after_raw,
                    before_score=r.before_score, after_score=r.after_score,
                    observations=r.observations, ever_down=r.ever_down or (cur.ever_down if cur else False),
                )
            elif r.ever_down:
                best[r.tid].ever_down = True
    return list(best.values())


def in_subset(row: TaskRow, subset: str) -> bool:
    if subset == "full":
        return True
    if subset == "movable":
        return row.before_raw > 0
    if subset == "persistent":
        return row.klass == "PERSISTENT"
    if subset == "variable":
        return row.klass in ("VARIABLE", "RULE_FIXED")
    if subset == "never":
        return row.klass == "NEVER"
    raise ValueError(f"unknown subset {subset!r}")


# --- run-level aggregate repair (RQ1 headline counts + RQ3 aggregate) -----------


def aggregate_repair(rows: list[TaskRow], subset: str = "full") -> dict:
    """Run-level repair summary over a task subset."""
    sel = [r for r in rows if in_subset(r, subset)]
    movable = [r for r in sel if r.movable]
    repaired = [r for r in movable if r.repaired]
    partial = [r for r in movable if not r.repaired and r.delta_raw > 0]
    deltas = [r.delta_score for r in movable]
    return {
        "subset": subset,
        "n_tasks": len(sel),
        "n_movable": len(movable),
        "n_repaired": len(repaired),
        "n_partial": len(partial),
        "pct_repaired_of_movable": (len(repaired) / len(movable)) if movable else None,
        "total_delta_score": sum(r.delta_score for r in movable),
        "total_delta_raw": sum(r.delta_raw for r in movable),
        "mean_delta_score_movable": (sum(deltas) / len(deltas)) if deltas else 0.0,
        "median_delta_score_movable": median(deltas) if deltas else 0.0,
    }


# --- RQ3 confound: did EA and random sample the search space comparably? --------


def confound(run: L.RunData) -> dict:
    """Sampling-breadth diagnostics for the best_f1 vs aggregate-repair reconciliation."""
    iters = L.valid_iters(run)
    rules = {str(it.get("rule_id")) for it in iters if it.get("rule_id")}
    affected = [int(it.get("num_prompts_affected", 0) or 0) for it in iters]
    return {
        "run": run.name,
        "strategy": "ea" if run.strategy == "ea" else "rand",
        "seed": run.seed,
        "language": run.languages[0] if run.languages else "?",
        "n_iterations": len(iters),
        "n_distinct_rules": len(rules),
        "mean_prompts_affected": (sum(affected) / len(affected)) if affected else 0.0,
        "total_prompt_evals": sum(affected),
    }


# --- cross-seed consistency (RQ1: how reproducible is a repair?) -----------------


def cross_seed_consistency(rows_by_seed: list[list[TaskRow]], subset: str = "movable") -> list[dict]:
    """Per movable task: in how many of the N seeds was it repaired / reduced."""
    agg: dict[str, dict] = defaultdict(
        lambda: {"cwe": "", "klass": "", "before_raw": None, "n_seeds": 0,
                 "n_repaired": 0, "n_reduced": 0, "deltas": []})
    for rows in rows_by_seed:
        for r in rows:
            if not in_subset(r, subset) or not r.movable:
                continue
            a = agg[r.tid]
            a["cwe"], a["klass"], a["before_raw"] = r.cwe, r.klass, r.before_raw
            a["n_seeds"] += 1
            a["n_repaired"] += int(r.repaired)
            a["n_reduced"] += int(r.delta_raw > 0)
            a["deltas"].append(r.delta_raw)
    out = []
    for tid, a in agg.items():
        ns = a["n_seeds"]
        out.append({
            "tid": tid, "cwe": a["cwe"], "klass": a["klass"], "before_raw": a["before_raw"],
            "n_seeds": ns, "n_repaired_seeds": a["n_repaired"], "n_reduced_seeds": a["n_reduced"],
            "always_repaired": ns > 0 and a["n_repaired"] == ns,
            "always_reduced": ns > 0 and a["n_reduced"] == ns,
            "mean_delta_raw": (sum(a["deltas"]) / ns) if ns else 0.0,
        })
    return sorted(out, key=lambda d: (-d["n_repaired_seeds"], -d["mean_delta_raw"]))


# --- 3-condition vectors for the Friedman aggregate test ------------------------


def _best_after_by_task(rows_by_seed: list[list[TaskRow]], subset: str,
                        field: str) -> dict[str, tuple[float, float]]:
    """tid -> (before, best/safest after over the strategy's seeds) on field."""
    before: dict[str, float] = {}
    best: dict[str, float] = {}
    for rows in rows_by_seed:
        for r in rows:
            if not in_subset(r, subset) or not r.movable:
                continue
            after_v = getattr(r, field)
            before_v = r.before_score if field == "after_score" else r.before_raw
            before[r.tid] = before_v
            if r.tid not in best or after_v < best[r.tid]:
                best[r.tid] = after_v
    return {t: (before[t], best[t]) for t in best}


def three_condition_vectors(ea_by_seed: list[list[TaskRow]], rand_by_seed: list[list[TaskRow]],
                            subset: str = "movable", field: str = "after_score"):
    """Aligned (tids, baseline, ea_best_after, rand_best_after) over tasks movable in BOTH arms.

    Friedman blocks = tasks; conditions = {baseline, EA-best, random-best}.
    """
    ea = _best_after_by_task(ea_by_seed, subset, field)
    rd = _best_after_by_task(rand_by_seed, subset, field)
    tids = sorted(set(ea) & set(rd), key=lambda t: int(t) if str(t).isdigit() else t)
    baseline = [ea[t][0] for t in tids]
    ea_after = [ea[t][1] for t in tids]
    rd_after = [rd[t][1] for t in tids]
    return tids, baseline, ea_after, rd_after
