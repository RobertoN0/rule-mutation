"""Regression tests: rule text must reach the final model system prompt.

Guards the invariant the supervisor cares about — that the prompt going into the
model genuinely contains the rule text, and that no-rules prompts use the clean
baseline. Exercises the real pipeline components shared by both the main pipeline
and the replicate harness:

  * ``RuleLoader``                          — load + combine rule files
  * ``ExperimentEngine._build_system_prompt``    — the exact system prompt sent to the LLM

The companion ``scripts/validation/check_rules_in_prompt.py`` runs the same checks
against the real CodeGuard rules + retrieval maps; these tests use small fixtures
so they run fast in CI without the project-codeguard submodule.
"""
from __future__ import annotations

import pytest

from src.evaluation.rule_mapping import RuleLoader
from src.mutation.base import Mutator, MutationResult
from src.optimizer.engine import ExperimentEngine, SearchConfig

SEP = "\n\n---\n\n"
RULE_A = "RULE-ALPHA: always validate and parameterize SQL queries."
RULE_B = "RULE-BETA: never call os.system with untrusted input."


class _Noop(Mutator):
    @property
    def name(self) -> str:
        return "noop"

    def mutate(self, text: str) -> MutationResult:
        return MutationResult(original=text, mutated=text, mutation_type="noop", changes=[])


@pytest.fixture
def hc() -> ExperimentEngine:
    # llm_backend=None is safe: __init__ only stores it; we never call generate().
    return ExperimentEngine(llm_backend=None, mutator=_Noop(), config=SearchConfig())


@pytest.fixture
def rules_dir(tmp_path):
    (tmp_path / "rule-a.md").write_text(RULE_A, encoding="utf-8")
    (tmp_path / "rule-b.md").write_text(RULE_B, encoding="utf-8")
    return tmp_path


def test_rule_text_reaches_system_prompt(hc, rules_dir):
    """Every combined rule's text appears verbatim in the final system prompt."""
    loader = RuleLoader(rules_dir)
    combined = loader.combine_rules(["rule-a", "rule-b"])
    sysp = hc._build_system_prompt(combined)

    assert sysp != hc.BASELINE_SYSTEM            # rules were injected
    assert "=== CODING GUIDELINES ===" in sysp   # template used
    assert RULE_A in sysp                         # rule A text present
    assert RULE_B in sysp                         # rule B text present
    assert combined == SEP.join([RULE_A, RULE_B]) # faithful assembly


def test_norules_uses_clean_baseline(hc):
    """Empty combined_rules → baseline prompt, with no rule text or guideline markers."""
    sysp = hc._build_system_prompt("")
    assert sysp == hc.BASELINE_SYSTEM
    assert "=== CODING GUIDELINES ===" not in sysp
    assert RULE_A not in sysp and RULE_B not in sysp


def test_override_injects_mutated_text(hc, rules_dir):
    """Harness override path: mutated rule text replaces the original in the prompt.

    Mirrors baseline_harness._apply_overrides (swap individual_rules text, rebuild
    combined_rules with the same separator), then checks the prompt.
    """
    loader = RuleLoader(rules_dir)
    rule_ids = ["rule-a", "rule-b"]
    individual = loader.load_multiple(rule_ids)

    mutated_a = "RULE-ALPHA-MUTATED: maybe validate SQL when convenient."
    individual["rule-a"] = mutated_a  # the override swap
    combined = SEP.join(individual[r] for r in rule_ids)
    sysp = hc._build_system_prompt(combined)

    assert mutated_a in sysp        # mutated text injected
    assert RULE_A not in sysp       # original text gone
    assert RULE_B in sysp           # untouched rule still present


def test_missing_rule_file_raises(rules_dir):
    """A mapped rule_id with no file fails loudly (no silent empty-rule prompt)."""
    loader = RuleLoader(rules_dir)
    with pytest.raises(FileNotFoundError):
        loader.load("rule-does-not-exist")
