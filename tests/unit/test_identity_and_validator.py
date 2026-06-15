"""Regression tests for the commit-09115f1 correctness fixes.

These exercise the code paths that the real-model temp=0 smokes did NOT trigger
(no identity mutation happened to occur, and every validation happened to pass):

  1. Identity DETECTION in HillClimber._evaluate_with_per_prompt_rules:
     a mutation that produces no rule-text change returns a None mutated-text
     and skips code-gen + Semgrep entirely (no LLM call wasted).
  2. The EA runner's reaction to identity: mark the mutator tried, retry a
     different mutator for the same parent, and restart cleanly with
     ``mutator_exhausted`` when every mutator is identity.
  3. The random_baseline identity-chain guard: a None-fitness identity chain
     is skipped without the old AttributeError crash.
  4. The validator is informational/post-hoc only: a mutation that FAILS
     validation is still generated (the validator never gates acceptance).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evaluation.fitness import AggregatedFitness
from src.evaluation.rule_mapping import PromptWithRules
from src.evaluation.semgrep_runner import SemgrepResult
from src.mutation.base import Mutator, MutationResult
from src.optimizer.ea_optimizer import run_ea, run_random_baseline
from src.optimizer.hill_climber import IterationResult, PerRuleResult


# ───────────────────────── stubs ──────────────────────────────────────────

class IdentityMutator(Mutator):
    """Mutator that always returns its input unchanged (an identity no-op)."""

    def __init__(self, name: str = "identity", seed: int | None = None):
        super().__init__(seed)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(
            original=text, mutated=text,  # identical → identity
            mutation_type=self._name, changes=["no change"],
        )


class ChangingMutator(Mutator):
    """Mutator that appends its name — always a real (non-identity) change."""

    def __init__(self, name: str, seed: int | None = None):
        super().__init__(seed)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(
            original=text, mutated=f"{text}|{self._name}",
            mutation_type=self._name, changes=[f"applied {self._name}"],
        )


class _FakeLLMBackend:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def generate(self, system, messages, **kwargs):
        user = messages[-1].get("content", "") if messages else ""
        self.calls.append((system or "", user))
        return SimpleNamespace(content="# code", input_tokens=10, output_tokens=5, latency_ms=1.0)


class _FailingValidator:
    """Informational validator double that ALWAYS reports failure.

    The point of the test is that this failure must NOT prevent code generation
    (the validator is post-hoc and never gates).
    """
    sbert_threshold = 0.75
    perplexity_threshold = 2.5
    keyword_threshold = 0.80

    def validate(self, mr: MutationResult):
        mr.metadata["quality"] = {
            "passes_all": False,
            "instruction_adherent": True,
            "sbert_step": 0.50,
            "perplexity_ratio": None,
            "inline_code_retention": 1.0,
            "keyword_retention": 1.0,
        }
        return mr.metadata["quality"]

    def _extract_prose_text(self, t: str) -> str:
        return t

    def _compute_sbert_similarity(self, a: str, b: str) -> float:
        return 0.50


def _semgrep_stub(code_samples, rule_config=None, strip_fences=True):
    return [SemgrepResult(findings=[], error=None) for _ in code_samples]


def _fit(f1: float = 0.0) -> AggregatedFitness:
    return AggregatedFitness(
        total_fitness=f1, mean_fitness=f1, max_fitness=f1,
        num_prompts=1, num_vulnerable=int(f1 > 0), individual_results=[],
        total_semgrep_delta=f1, proportion_divergent=0.0,
        conditional_mean_divergence=0.0,
    )


def _pwr(rule_id: str, rule_text: str) -> PromptWithRules:
    return PromptWithRules(
        prompt="write code", language="python", cwe_id="CWE-79",
        rule_ids=[rule_id], combined_rules=rule_text,
        individual_rules={rule_id: rule_text}, metadata={"test_case_id": "0"},
    )


def _silent(_: str) -> None:
    pass


# ───────────── 1. identity DETECTION: no code-gen, returns None ────────────

def test_identity_detection_skips_codegen(tmp_path: Path):
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig
    backend = _FakeLLMBackend()
    pwr = _pwr("rule_A", "ORIGINAL RULE")
    config = HillClimbConfig(max_iterations=0, output_dir=tmp_path,
                             verbose=False, save_intermediate=False)
    hc = HillClimber(backend, IdentityMutator(), config=config)

    out = hc._evaluate_with_per_prompt_rules(
        [pwr], target_rule_id="rule_A", mutator_fn=lambda _t: _t,
        selected_mutator=IdentityMutator(),
        iteration=1, phase="ea_iter0001", parent_text_override="ORIGINAL RULE",
    )
    # Identity signal: aggregated fitness None and mutated-text None.
    assert out[0] is None, "identity must return None aggregated fitness"
    assert out[4] is None, "identity must return None mutated-text"
    # The crucial guarantee: NO LLM call was made.
    assert backend.calls == [], "identity must not call the LLM backend"


def test_nonidentity_does_generate(tmp_path: Path):
    """Control: a real change DOES reach code generation."""
    from unittest.mock import patch
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig
    backend = _FakeLLMBackend()
    pwr = _pwr("rule_A", "ORIGINAL RULE")
    config = HillClimbConfig(max_iterations=0, output_dir=tmp_path,
                             verbose=False, save_intermediate=False)
    hc = HillClimber(backend, ChangingMutator("m"), config=config)
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        out = hc._evaluate_with_per_prompt_rules(
            [pwr], target_rule_id="rule_A", mutator_fn=lambda _t: _t,
            selected_mutator=ChangingMutator("m"),
            iteration=1, phase="ea_iter0001", parent_text_override="ORIGINAL RULE",
        )
    assert out[4] is not None, "non-identity must produce mutated text"
    assert len(backend.calls) == 1, "non-identity must call the LLM exactly once"


# ───────────── 2. validator never gates (post-hoc / informational) ─────────

def test_failing_validation_still_generates(tmp_path: Path):
    from unittest.mock import patch
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig
    backend = _FakeLLMBackend()
    pwr = _pwr("rule_A", "ORIGINAL RULE")
    config = HillClimbConfig(max_iterations=0, output_dir=tmp_path,
                             verbose=False, save_intermediate=False,
                             enable_validation=True)
    hc = HillClimber(backend, ChangingMutator("m"), config=config,
                     validator=_FailingValidator())
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        out = hc._evaluate_with_per_prompt_rules(
            [pwr], target_rule_id="rule_A", mutator_fn=lambda _t: _t,
            selected_mutator=ChangingMutator("m"),
            iteration=1, phase="ea_iter0001", parent_text_override="ORIGINAL RULE",
        )
    # Even though validation reported passes_all=False, the mutation was used.
    assert out[4] is not None, "validator must not suppress the mutated text"
    assert len(backend.calls) == 1, "validator must NEVER gate code generation"


# ───────────── 3. EA runner reaction to identity ───────────────────────────

def _ea_kwargs(mutators, evaluate_fn, records, max_iterations=6):
    return dict(
        prompts_with_rules=[_pwr("r1", "ORIGINAL[r1]")],
        all_rule_ids=["r1"], rule_originals={"r1": "ORIGINAL[r1]"},
        baseline_fitness=_fit(0), mutators=mutators, evaluate_fn=evaluate_fn,
        iteration_result_factory=IterationResult, per_rule_result_factory=PerRuleResult,
        max_iterations=max_iterations, archive_cap=3, restart_h=8, max_depth=4,
        seed=42, log=_silent, iter_record_fn=records.append,
    )


def test_ea_all_identity_restarts_cleanly():
    """Every mutator is identity → mutator_exhausted restarts, no insert, no crash."""
    records: list[dict] = []
    def ev(rid, parent, mutator, it, phase, chain):
        return (None, [], ["no change"], {}, None)   # always identity
    result = run_ea(**_ea_kwargs([IdentityMutator("a"), IdentityMutator("b")], ev, records))
    snap = result.archives_snapshot["r1"]
    assert snap["n_inserts"] == 0, "identity-only run must insert nothing"
    assert result.restart_reason_counts["mutator_exhausted"] >= 1
    # Identity attempts are recorded as such.
    assert any(r.get("mutation_identity") is True for r in records)


def test_ea_partial_identity_inserts_real_change():
    """Identity mutators are skipped; the one real mutator still advances."""
    records: list[dict] = []
    counter = {"i": 0}
    def ev(rid, parent, mutator, it, phase, chain):
        if mutator.name == "real":
            counter["i"] += 1
            f = float(counter["i"])
            return (_fit(f1=f), [], ["change"], {}, f"{parent}|real")
        return (None, [], ["no change"], {}, None)   # identity for the rest
    result = run_ea(**_ea_kwargs(
        [IdentityMutator("a"), IdentityMutator("b"), ChangingMutator("real")], ev, records))
    assert result.archives_snapshot["r1"]["n_inserts"] >= 1
    assert result.best_fitness is not None and result.best_fitness.total_semgrep_delta > 0


# ───────────── 4. random_baseline identity-chain guard ─────────────────────

def test_random_baseline_identity_chain_no_crash():
    """A None-fitness identity chain must be skipped, not crash (old bug)."""
    records: list[dict] = []
    def ev(rid, original, chain_mutator, it, phase, chain_names):
        return (None, [], ["no change"], {}, None)   # identity chain every time
    result = run_random_baseline(
        prompts_with_rules=[_pwr("r1", "ORIGINAL[r1]")],
        all_rule_ids=["r1"], rule_originals={"r1": "ORIGINAL[r1]"},
        mutators=[ChangingMutator("m0"), ChangingMutator("m1"), ChangingMutator("m2")],
        evaluate_fn=ev, iteration_result_factory=IterationResult,
        per_rule_result_factory=PerRuleResult, max_iterations=5,
        max_mutations_per_iter=3, seed=42, log=_silent, iter_record_fn=records.append,
    )
    # Completed without raising; every iteration recorded as an identity skip.
    assert len(records) == 5
    assert all(r.get("mutation_identity") is True for r in records)
