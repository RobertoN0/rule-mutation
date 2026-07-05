"""Tests for HillClimber._evaluate_chromosome — the pure render/score seam.

Uses a deterministic fake backend + Semgrep stub (mirrors test_eval_cache.py) so
we can count LLM/Semgrep calls and prove:
  * every prompt is rendered from the chromosome's alleles in chromosome order;
  * unaffected prompts (no mutated gene) reuse the cache across a one-gene move;
  * whole-chromosome findings reflect ALL mutated genes, not just the last;
  * cache ON and cache OFF produce identical scores (the parity guarantee);
  * a rule-less prompt uses the baseline system prompt.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.evaluation.semgrep_runner import SemgrepResult, SemgrepFinding
from src.optimizer.chromosome import RuleSetSpace


class _FakeBackend:
    """Deterministic backend: findings scale with 'BAD' markers in the system prompt.

    Determinism proxy for temperature=0 (identical system prompt ⇒ identical
    output). A mutated allele carries 'BAD' markers; originals do not — so a
    mutation deterministically changes the finding count.
    """

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self):
        self.calls: list[str] = []  # system prompts seen

    def generate(self, system, messages, **kwargs):
        self.calls.append(system or "")
        n_bad = (system or "").count("BAD")
        return SimpleNamespace(
            content=f"# bad={n_bad}\n" + "x\n" * n_bad,
            input_tokens=10, output_tokens=5, latency_ms=1.0,
        )


def _semgrep_stub(code_samples, rule_config=None, strip_fences=True):
    """One ERROR finding per 'x' line in the generated code."""
    _semgrep_stub.calls += 1
    out = []
    for code, _lang in code_samples:
        n = code.count("x\n")
        findings = [SemgrepFinding(check_id="demo", message="x", severity="ERROR", line=i + 1)
                    for i in range(n)]
        out.append(SemgrepResult(findings=findings, error=None))
    return out


_semgrep_stub.calls = 0


@pytest.fixture(autouse=True)
def _reset():
    _semgrep_stub.calls = 0
    yield


def _prompts():
    from src.evaluation.rule_mapping import PromptWithRules
    # p0 uses {a,b}; p1 uses {a}; p2 uses {c}; p3 uses {} (no rules)
    specs = [(["a", "b"], "tc0"), (["a"], "tc1"), (["c"], "tc2"), ([], "tc3")]
    return [
        PromptWithRules(prompt=f"write {tc}", language="python", cwe_id="CWE-79",
                        rule_ids=rids, combined_rules="", individual_rules={},
                        metadata={"test_case_id": tc})
        for rids, tc in specs
    ]


def _climber(backend, out_dir, cache=True):
    from src.optimizer.hill_climber import HillClimber, HillClimbConfig
    from src.evaluation.composite_fitness import CompositeFitnessEvaluator
    mutator = MagicMock(); mutator.name = "noop"; mutator.seed = 0
    cfg = HillClimbConfig(max_iterations=0, output_dir=out_dir, verbose=False,
                          save_intermediate=False, enable_eval_cache=cache)
    return HillClimber(backend, mutator, config=cfg,
                       composite_evaluator=CompositeFitnessEvaluator(reference_codes={}, lang="python"))


def _space():
    return RuleSetSpace(all_rule_ids=["a", "b", "c"],
                        originals={"a": "RULE A", "b": "RULE B", "c": "RULE C"})


def test_renders_from_chromosome_and_reuses_unaffected(tmp_path: Path):
    backend = _FakeBackend()
    hc = _climber(backend, tmp_path, cache=True)
    space, prompts = _space(), _prompts()

    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        origin = space.origin()
        _agg, _res, reused0, rerun0 = hc._evaluate_chromosome(origin, space, prompts, iter_id="baseline")
        assert (rerun0, reused0) == (4, 0)
        base_calls = len(backend.calls)

        # Mutate gene 'a' → affects p0 and p1 only; p2 (c) and p3 (none) reuse cache.
        child = space.stamp(origin.with_gene("a", "RULE A BAD BAD", "m"))
        _agg, _res, reused1, rerun1 = hc._evaluate_chromosome(child, space, prompts, iter_id="ea_iter0001")
        assert (rerun1, reused1) == (2, 2)
        assert len(backend.calls) == base_calls + 2


def test_whole_chromosome_reflects_all_mutated_genes(tmp_path: Path):
    backend = _FakeBackend()
    hc = _climber(backend, tmp_path, cache=True)
    space, prompts = _space(), _prompts()
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc._evaluate_chromosome(space.origin(), space, prompts, iter_id="baseline")
        # Mutate BOTH a (1 BAD) and c (2 BAD): p0=a→1, p1=a→1, p2=c→2, p3=0 ⇒ total 4
        child = space.stamp(
            space.origin().with_gene("a", "A BAD", "m").with_gene("c", "C BAD BAD", "m")
        )
        _agg, res, _reused, _rerun = hc._evaluate_chromosome(child, space, prompts, iter_id="ea_iter0002")
        assert sum(r.fitness.raw_count for r in res) == 4


def test_cache_parity_on_vs_off(tmp_path: Path):
    """Same chromosome sequence with cache ON and OFF ⇒ identical scores."""
    space, prompts = _space(), _prompts()
    seq = [
        space.origin(),
        space.stamp(space.origin().with_gene("a", "A BAD", "m")),
        space.stamp(space.origin().with_gene("a", "A BAD", "m").with_gene("c", "C BAD BAD", "m")),
    ]

    def run(cache):
        backend = _FakeBackend()
        hc = _climber(backend, tmp_path / f"cache_{cache}", cache=cache)
        scores = []
        with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
            for i, ch in enumerate(seq):
                agg, res, *_ = hc._evaluate_chromosome(ch, space, prompts, iter_id=f"it{i}")
                scores.append((
                    round(agg.total_semgrep_delta, 6),
                    round(agg.proportion_divergent, 6),
                    round(agg.conditional_mean_divergence, 6),
                    tuple(r.fitness.raw_count for r in res),
                ))
        return scores

    assert run(cache=True) == run(cache=False)


def test_cache_disabled_regenerates(tmp_path: Path):
    backend = _FakeBackend()
    hc = _climber(backend, tmp_path, cache=False)
    space, prompts = _space(), _prompts()
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc._evaluate_chromosome(space.origin(), space, prompts, iter_id="baseline")
        n = len(backend.calls)
        # same chromosome again — cache OFF ⇒ regenerate all rule-carrying prompts
        hc._evaluate_chromosome(space.origin(), space, prompts, iter_id="it1")
        assert len(backend.calls) == 2 * n


def test_semgrep_batches_only_fresh(tmp_path: Path):
    backend = _FakeBackend()
    hc = _climber(backend, tmp_path, cache=True)
    space, prompts = _space(), _prompts()
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub) as m:
        hc._evaluate_chromosome(space.origin(), space, prompts, iter_id="baseline")
        first_batch = m.call_args[0][0]
        assert len(first_batch) == 4   # all 4 prompts fresh at baseline (incl. the rule-less one)
        child = space.stamp(space.origin().with_gene("a", "A BAD", "m"))
        hc._evaluate_chromosome(child, space, prompts, iter_id="it1")
        second_batch = m.call_args[0][0]
        assert len(second_batch) == 2  # only p0,p1 (contain 'a') rerun


def test_empty_prompt_uses_baseline_system(tmp_path: Path):
    backend = _FakeBackend()
    hc = _climber(backend, tmp_path, cache=True)
    space = _space()
    from src.evaluation.rule_mapping import PromptWithRules
    p = PromptWithRules(prompt="x", language="python", cwe_id=None,
                        rule_ids=[], combined_rules="", individual_rules={},
                        metadata={"test_case_id": "tc"})
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        _agg, res, _reused, _rerun = hc._evaluate_chromosome(space.origin(), space, [p], iter_id="baseline")
        assert res[0].fitness.raw_count == 0
        assert "=== CODING GUIDELINES ===" not in backend.calls[0]
