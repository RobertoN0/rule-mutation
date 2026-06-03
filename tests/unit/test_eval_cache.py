"""Prompt-skip evaluation cache tests.

Validates that when ``HillClimbConfig.enable_eval_cache=True``, the hill climber
reuses cached (code, semgrep_result) for prompts whose assembled rule text
is byte-identical to a previously evaluated input.

Correctness relies on ``temperature=0`` greedy decoding: same input → same
output. Tests mock the LLM backend and Semgrep runner to count calls and
verify the cache short-circuits the work on the second visit.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.fitness import AggregatedFitness, FitnessResult
from src.evaluation.semgrep_runner import SemgrepResult


class _FakeLLMBackend:
    """Minimal LLM backend double that records every call and returns canned code."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []  # (system, user)

    def generate(self, system, messages, **kwargs):
        user = messages[-1].get("content", "") if messages else ""
        self.calls.append((system or "", user))
        return SimpleNamespace(
            content="# generated code",
            input_tokens=10,
            output_tokens=5,
            latency_ms=1.0,
        )


def _semgrep_stub(code_samples, rule_config=None, strip_fences=True):
    """Stand-in for run_semgrep_batch_dir: one empty SemgrepResult per sample."""
    _semgrep_stub.call_count += 1
    _semgrep_stub.last_batch_size = len(code_samples)
    return [SemgrepResult(findings=[], error=None) for _ in code_samples]


_semgrep_stub.call_count = 0
_semgrep_stub.last_batch_size = 0


@pytest.fixture(autouse=True)
def _reset_semgrep_counter():
    _semgrep_stub.call_count = 0
    _semgrep_stub.last_batch_size = 0
    yield


def _make_prompt_with_rules(tc_id: str, rule_text: str, rule_id: str):
    from src.evaluation.rule_mapping import PromptWithRules
    return PromptWithRules(
        prompt=f"Write code for TC#{tc_id}",
        language="python",
        cwe_id="CWE-79",
        rule_ids=[rule_id],
        combined_rules=rule_text,
        individual_rules={rule_id: rule_text},
        metadata={"test_case_id": tc_id},
    )


def test_cache_hit_skips_generation_and_semgrep(tmp_path: Path):
    """Second evaluation of an identical (tc_id, rule_text) reuses the cache."""
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig

    backend = _FakeLLMBackend()
    pwr = _make_prompt_with_rules("0", "RULE TEXT v1", "rule_A")
    mutator = MagicMock()
    mutator.name = "noop"
    mutator.seed = 0

    config = HillClimbConfig(
        max_iterations=0,
        output_dir=tmp_path,
        verbose=False,
        save_intermediate=False,
        enable_eval_cache=True,
    )
    hc = HillClimber(backend, mutator, config=config)

    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        # First call — cache miss: generate + semgrep
        agg1, res1, _, _, _ = hc._evaluate_with_per_prompt_rules(
            [pwr], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        assert len(backend.calls) == 1, "first call must generate"
        assert _semgrep_stub.call_count == 1, "first call must invoke Semgrep"
        assert hc._eval_cache_hits == 0
        assert hc._eval_cache_misses == 1

        # Second call with byte-identical rule_text — cache hit: skip both
        agg2, res2, _, _, _ = hc._evaluate_with_per_prompt_rules(
            [pwr], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        assert len(backend.calls) == 1, "second call must not generate (cache hit)"
        assert _semgrep_stub.call_count == 1, "second call must not invoke Semgrep (cache hit)"
        assert hc._eval_cache_hits == 1
        assert hc._eval_cache_misses == 1


def test_cache_miss_on_different_rule_text(tmp_path: Path):
    """Changing the rule text forces re-generation (different cache key)."""
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig

    backend = _FakeLLMBackend()
    pwr_v1 = _make_prompt_with_rules("0", "RULE TEXT v1", "rule_A")
    pwr_v2 = _make_prompt_with_rules("0", "RULE TEXT v2", "rule_A")
    mutator = MagicMock()
    mutator.name = "noop"
    mutator.seed = 0

    config = HillClimbConfig(
        max_iterations=0,
        output_dir=tmp_path,
        verbose=False,
        save_intermediate=False,
        enable_eval_cache=True,
    )
    hc = HillClimber(backend, mutator, config=config)

    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc._evaluate_with_per_prompt_rules(
            [pwr_v1], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        hc._evaluate_with_per_prompt_rules(
            [pwr_v2], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        assert len(backend.calls) == 2, "different rule_text must trigger fresh generation"
        assert _semgrep_stub.call_count == 2


def test_cache_disabled_regenerates_every_time(tmp_path: Path):
    """With enable_eval_cache=False, every call regenerates — safe escape hatch."""
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig

    backend = _FakeLLMBackend()
    pwr = _make_prompt_with_rules("0", "RULE TEXT v1", "rule_A")
    mutator = MagicMock()
    mutator.name = "noop"
    mutator.seed = 0

    config = HillClimbConfig(
        max_iterations=0,
        output_dir=tmp_path,
        verbose=False,
        save_intermediate=False,
        enable_eval_cache=False,
    )
    hc = HillClimber(backend, mutator, config=config)

    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc._evaluate_with_per_prompt_rules(
            [pwr], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        hc._evaluate_with_per_prompt_rules(
            [pwr], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        assert len(backend.calls) == 2, "cache disabled must always regenerate"
        assert _semgrep_stub.call_count == 2


def test_partial_cache_hit_batches_only_fresh_samples(tmp_path: Path):
    """In a mixed batch, Semgrep runs only on cache-missed samples."""
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig

    backend = _FakeLLMBackend()
    # Two prompts: same tc_id="0" is already cached, tc_id="1" is new.
    pwr_0 = _make_prompt_with_rules("0", "RULE TEXT v1", "rule_A")
    pwr_1 = _make_prompt_with_rules("1", "RULE TEXT v1", "rule_A")
    mutator = MagicMock()
    mutator.name = "noop"
    mutator.seed = 0

    config = HillClimbConfig(
        max_iterations=0,
        output_dir=tmp_path,
        verbose=False,
        save_intermediate=False,
        enable_eval_cache=True,
    )
    hc = HillClimber(backend, mutator, config=config)

    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        # Prime cache with pwr_0
        hc._evaluate_with_per_prompt_rules(
            [pwr_0], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        assert _semgrep_stub.last_batch_size == 1

        # Now run with both prompts — only pwr_1 should be fresh
        hc._evaluate_with_per_prompt_rules(
            [pwr_0, pwr_1], mutator_fn=None, iteration=None, phase="baseline",
            target_rule_id=None, selected_mutator=None,
        )
        assert _semgrep_stub.last_batch_size == 1, "mixed batch must invoke Semgrep only on fresh samples"
        # Total LLM calls: 1 for priming + 1 for pwr_1 only
        assert len(backend.calls) == 2
