"""
Rule-aware outcome states (schema_version 2) — the bd-7kr metric core. Builds
the per-prompt and per-(rule,prompt) collapsed outcome states; the CSV/Markdown
row builders that consume these live in ``metrics.outcome_rows``.

Unit of analysis (scopes):
  - prompt:            one state per test case (collapse over all rephrasings).
  - applicable:        one state per (rule, prompt) where the rule was retrieved.
  - all_prompt_rules:  every mutated rule crossed with every prompt (conservative,
                       memo-compatible denominator).

Pure compute: no file IO, no plotting.
"""

from __future__ import annotations

from dataclasses import dataclass

import loaders as L
import records as R


OUTCOMES = ("degraded", "unchanged", "safer")
SCOPES = ("prompt", "applicable", "all_prompt_rules")


@dataclass
class UnitState:
    """Collapsed outcome for one prompt or one rule-prompt exposure."""

    key: tuple[str, ...]
    baseline_score: float
    baseline_raw: int
    baseline_error: int
    baseline_warning: int
    language: str
    cwe_id: str
    rule_id: str = ""
    test_case_id: str = ""
    rules_used_count: int = 0
    observations: int = 0
    ever_up: bool = False
    ever_down: bool = False
    code_changed: bool = False
    min_score: float | None = None
    max_score: float | None = None
    min_raw: int | None = None
    max_raw: int | None = None
    min_error: int | None = None
    max_error: int | None = None
    min_warning: int | None = None
    max_warning: int | None = None

    def __post_init__(self) -> None:
        self.min_score = self.baseline_score
        self.max_score = self.baseline_score
        self.min_raw = self.baseline_raw
        self.max_raw = self.baseline_raw
        self.min_error = self.baseline_error
        self.max_error = self.baseline_error
        self.min_warning = self.baseline_warning
        self.max_warning = self.baseline_warning

    @property
    def outcome(self) -> str:
        if self.ever_up:
            return "degraded"
        if self.ever_down:
            return "safer"
        return "unchanged"

    def observe(self, rec: dict, code_divergence_threshold: float) -> None:
        score = R.weighted_score(rec)
        raw = R.raw_count(rec)
        err = R.error_count(rec)
        warn = R.warning_count(rec)

        self.observations += 1
        if score > self.baseline_score:
            self.ever_up = True
        elif score < self.baseline_score:
            self.ever_down = True
        if R.code_divergence(rec) > code_divergence_threshold:
            self.code_changed = True

        if self.max_score is None or score > self.max_score:
            self.max_score = score
            self.max_raw = raw
            self.max_error = err
            self.max_warning = warn
        if self.min_score is None or score < self.min_score:
            self.min_score = score
            self.min_raw = raw
            self.min_error = err
            self.min_warning = warn


@dataclass
class RunOutcome:
    run: L.RunData
    prompt_states: dict[str, UnitState]
    applicable_states: dict[tuple[str, str], UnitState]
    all_prompt_rule_states: dict[tuple[str, str], UnitState]


def lang_key(run: L.RunData) -> str:
    return ",".join(run.languages) if run.languages else "all"


def run_label(run: L.RunData) -> str:
    """Stable human/output label, including parent name for migrated schema2 dirs."""
    if run.run_dir.name == "schema2" and run.run_dir.parent.name:
        return f"{run.run_dir.parent.name}__schema2"
    return run.name


def _new_state_from_baseline(
    key: tuple[str, ...],
    base_rec: dict,
    *,
    rule_id: str = "",
) -> UnitState:
    raw, err, warn = R.fitness_counts(base_rec)
    tc = str(base_rec["test_case_id"])
    return UnitState(
        key=key,
        baseline_score=R.weighted_score(base_rec),
        baseline_raw=raw,
        baseline_error=err,
        baseline_warning=warn,
        language=str(base_rec.get("language", "?")),
        cwe_id=str(base_rec.get("cwe_id", "?")),
        rule_id=rule_id,
        test_case_id=tc,
        rules_used_count=len(R.original_rule_ids(base_rec)),
    )


def build_run_outcome(run: L.RunData, code_divergence_threshold: float) -> RunOutcome:
    base_by_prompt = {str(rec["test_case_id"]): rec for rec in run.baseline()}
    mutated_rules = sorted({str(it.get("rule_id")) for it in L.valid_iters(run) if it.get("rule_id")})

    prompt_states = {
        tc: _new_state_from_baseline((tc,), rec)
        for tc, rec in base_by_prompt.items()
    }

    applicable_states: dict[tuple[str, str], UnitState] = {}
    for tc, rec in base_by_prompt.items():
        for rule_id in R.original_rule_ids(rec):
            if rule_id in mutated_rules:
                applicable_states[(rule_id, tc)] = _new_state_from_baseline(
                    (rule_id, tc),
                    rec,
                    rule_id=rule_id,
                )

    all_prompt_rule_states = {
        (rule_id, tc): _new_state_from_baseline((rule_id, tc), rec, rule_id=rule_id)
        for rule_id in mutated_rules
        for tc, rec in base_by_prompt.items()
    }

    for it in L.valid_iters(run):
        rule_id = str(it.get("rule_id"))
        iter_id = run.iter_id(int(it["iter"]))
        for rec in run.intermediate(iter_id):
            tc = str(rec.get("test_case_id"))
            if tc not in base_by_prompt:
                continue
            if not R.is_applicable(rec, rule_id):
                continue
            prompt_states[tc].observe(rec, code_divergence_threshold)
            applicable = applicable_states.get((rule_id, tc))
            if applicable is not None:
                applicable.observe(rec, code_divergence_threshold)
            all_scope = all_prompt_rule_states.get((rule_id, tc))
            if all_scope is not None:
                all_scope.observe(rec, code_divergence_threshold)

    return RunOutcome(
        run=run,
        prompt_states=prompt_states,
        applicable_states=applicable_states,
        all_prompt_rule_states=all_prompt_rule_states,
    )


def states_for_scope(outcome: RunOutcome, scope: str) -> list[UnitState]:
    if scope == "prompt":
        return list(outcome.prompt_states.values())
    if scope == "applicable":
        return list(outcome.applicable_states.values())
    if scope == "all_prompt_rules":
        return list(outcome.all_prompt_rule_states.values())
    raise ValueError(f"unknown scope: {scope}")


def distribution(states: list[UnitState]) -> dict[str, int]:
    counts = {name: 0 for name in OUTCOMES}
    for state in states:
        counts[state.outcome] += 1
    return counts
