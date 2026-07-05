"""End-to-end integration smoke for the chromosome pipeline.

Drives HillClimber.optimize_per_prompt_rules with a deterministic fake backend +
patched Semgrep (no real LLM/Semgrep) and inspects the schema-3 artifacts:
iterations.jsonl, archive_snapshots/ (EA), mutated_rules/, intermediate/.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.evaluation.composite_fitness import CompositeFitnessEvaluator
from src.evaluation.rule_mapping import PromptWithRules
from src.evaluation.semgrep_runner import SemgrepResult, SemgrepFinding
from src.mutation.base import Mutator, MutationResult
from src.mutation.pool import MutatorPool
from src.optimizer.hill_climber import HillClimber, HillClimbConfig


class _FakeBackend:
    provider_name = "fake"
    model_name = "fake-model"

    def generate(self, system, messages, **kwargs):
        n_bad = (system or "").count("BAD")
        return SimpleNamespace(content=f"# bad={n_bad}\n" + "x\n" * n_bad,
                               input_tokens=10, output_tokens=5, latency_ms=1.0)


def _semgrep_stub(code_samples, rule_config=None, strip_fences=True):
    out = []
    for code, _lang in code_samples:
        n = code.count("x\n")
        out.append(SemgrepResult(
            findings=[SemgrepFinding(check_id="d", message="x", severity="ERROR", line=i + 1)
                      for i in range(n)],
            error=None,
        ))
    return out


class _BadMutator(Mutator):
    """Appends a ' BAD' marker → deterministically raises the finding count."""

    def __init__(self, name: str, seed=None):
        super().__init__(seed)
        self._n = name

    @property
    def name(self) -> str:
        return self._n

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(text, f"{text} BAD", self._n, [f"+{self._n}"])


def _prompts():
    def mk(i, rids):
        return PromptWithRules(prompt=f"write {i}", language="python", cwe_id="CWE-79",
                               rule_ids=rids, combined_rules="",
                               individual_rules={r: f"rule {r}" for r in rids},
                               metadata={"test_case_id": f"tc{i}"})
    return [mk(0, ["r1", "r2"]), mk(1, ["r1"]), mk(2, ["r2"])]


def _climber(tmp_path, optimizer, iters):
    pool = MutatorPool([_BadMutator("m0", 0), _BadMutator("m1", 0), _BadMutator("m2", 0)], seed=42)
    cfg = HillClimbConfig(max_iterations=iters, output_dir=tmp_path, verbose=False,
                          optimizer=optimizer, objective_direction="maximize",
                          archive_cap=4, restart_h=6, max_depth_ea=4)
    return HillClimber(_FakeBackend(), pool, cfg,
                       composite_evaluator=CompositeFitnessEvaluator(reference_codes={}, lang="python"))


def test_ea_end_to_end_writes_schema3(tmp_path: Path):
    hc = _climber(tmp_path, "ea", iters=10)
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        result = hc.optimize_per_prompt_rules(_prompts())

    # more BAD markers ⇒ more findings ⇒ positive f1 under maximize
    assert result.best_fitness.total_semgrep_delta > 0

    iters = [json.loads(l) for l in (tmp_path / "iterations.jsonl").read_text().splitlines() if l]
    assert iters and all(it["strategy"] == "ea" for it in iters)
    real = [it for it in iters if not it["mutation_identity"]]
    assert real and all({"chromosome_id", "mutated_rule_ids", "move_type", "gene_depth"} <= it.keys() for it in real)

    snaps = sorted((tmp_path / "archive_snapshots").glob("iter*.json"))
    assert snaps
    snap = json.loads(snaps[-1].read_text())
    assert snap["schema_version"] == 3 and "chromosomes" in snap
    # a surviving entry references its gene texts under mutated_rules/
    if snap["chromosomes"]:
        entry = snap["chromosomes"][0]
        for rid, g in entry["genes"].items():
            ref = tmp_path / g["text_ref"]
            assert ref.exists(), ref

    assert (tmp_path / "mutated_rules").is_dir()
    assert list((tmp_path / "mutated_rules").glob("iter*/meta.json"))
    # compounding_state carries the single chromosome archive
    assert "entries" in result.compounding_state


class _SometimesIdentityMutator(Mutator):
    """Identity when told to — exercises both the evaluated and identity paths."""

    def __init__(self, name: str, ident: bool = False, seed=None):
        super().__init__(seed)
        self._n, self._id = name, ident

    @property
    def name(self) -> str:
        return self._n

    def mutate(self, text: str) -> MutationResult:
        return (MutationResult(text, text, self._n, []) if self._id
                else MutationResult(text, f"{text} BAD", self._n, [f"+{self._n}"]))


def test_ea_saves_every_evaluated_iter_and_identity_keeps_cid(tmp_path: Path):
    pool = MutatorPool([_SometimesIdentityMutator("good"),
                        _SometimesIdentityMutator("noop", ident=True)], seed=1)
    cfg = HillClimbConfig(max_iterations=10, output_dir=tmp_path, verbose=False,
                          optimizer="ea", objective_direction="maximize", archive_cap=2,
                          restart_h=8, max_depth_ea=4)
    hc = HillClimber(_FakeBackend(), pool, cfg,
                     composite_evaluator=CompositeFitnessEvaluator({}, "python"))
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc.optimize_per_prompt_rules(_prompts())

    iters = [json.loads(l) for l in (tmp_path / "iterations.jsonl").read_text().splitlines() if l]
    evaluated = [it for it in iters if not it["mutation_identity"]]
    identity = [it for it in iters if it["mutation_identity"]]
    saved = {int(m.parent.name.replace("iter", "")) for m in (tmp_path / "mutated_rules").glob("iter*/meta.json")}

    # FIX 1: every evaluated iteration is persisted — including rejected ones.
    assert evaluated and all(it["iter"] in saved for it in evaluated)
    assert {it["iter"] for it in evaluated if not it["accepted"]} <= saved
    metas = [json.loads(m.read_text()) for m in (tmp_path / "mutated_rules").glob("iter*/meta.json")]
    assert all("accepted" in m for m in metas)
    # FIX 2: identity iterations keep a (parent) chromosome_id — never null.
    assert identity and all(it["chromosome_id"] is not None for it in identity)


class _StubValidator:
    """Minimal MutationQualityValidator stand-in (no SBERT model load)."""
    sbert_threshold = 0.75
    perplexity_threshold = 2.5
    keyword_threshold = 0.9

    def validate(self, mr):
        mr.metadata["quality"] = {
            "instruction_adherent": True, "sbert_step": 0.88, "perplexity_ratio": None,
            "inline_code_retention": 1.0, "keyword_retention": 1.0, "passes_all": True,
        }
        return mr

    def _extract_prose_text(self, t):
        return t

    def _compute_sbert_similarity(self, a, b):
        return 0.80


def test_validation_metadata_flows_when_enabled(tmp_path: Path):
    pool = MutatorPool([_BadMutator("m0", 0), _BadMutator("m1", 0)], seed=7)
    cfg = HillClimbConfig(max_iterations=8, output_dir=tmp_path, verbose=False,
                          optimizer="ea", objective_direction="maximize", archive_cap=4,
                          restart_h=6, max_depth_ea=4, enable_validation=True)
    hc = HillClimber(_FakeBackend(), pool, cfg, validator=_StubValidator(),
                     composite_evaluator=CompositeFitnessEvaluator({}, "python"))
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc.optimize_per_prompt_rules(_prompts())

    iters = [json.loads(l) for l in (tmp_path / "iterations.jsonl").read_text().splitlines() if l]
    real = [it for it in iters if not it["mutation_identity"]]
    assert real and all(it["validation_metadata"].get("passes_all") is True for it in real)
    assert all("sbert_cum" in it["validation_metadata"] for it in real)
    # mutated_rules meta.json also carries it
    metas = list((tmp_path / "mutated_rules").glob("iter*/meta.json"))
    assert metas
    assert any(json.loads(m.read_text()).get("validation_metadata", {}).get("passes_all") is True
               for m in metas)


def test_validation_absent_when_disabled(tmp_path: Path):
    hc = _climber(tmp_path, "ea", iters=6)  # enable_validation defaults False, validator None
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        hc.optimize_per_prompt_rules(_prompts())
    iters = [json.loads(l) for l in (tmp_path / "iterations.jsonl").read_text().splitlines() if l]
    assert all(it["validation_metadata"] == {} for it in iters)


def test_random_end_to_end_writes_schema3(tmp_path: Path):
    hc = _climber(tmp_path, "random_baseline", iters=8)
    with patch("src.optimizer.hill_climber.run_semgrep_batch_dir", side_effect=_semgrep_stub):
        result = hc.optimize_per_prompt_rules(_prompts())

    iters = [json.loads(l) for l in (tmp_path / "iterations.jsonl").read_text().splitlines() if l]
    assert iters and all(it["strategy"] == "random_baseline" for it in iters)
    # random keeps no archive
    assert result.compounding_state == {}
    assert not (tmp_path / "archive_snapshots").exists()
    assert (tmp_path / "mutated_rules").is_dir()
    # baseline intermediate written through the same seam
    assert (tmp_path / "intermediate" / "baseline.jsonl").exists()
