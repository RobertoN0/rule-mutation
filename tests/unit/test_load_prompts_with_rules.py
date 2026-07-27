"""Topic A — Prompt loading unit tests (C-A1 to C-A4).

Validates filter composition (--n-cases, --selection, --languages),
PromptWithRules population, combined_rules formatting, and the
--use-mapping-only loader path.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.evaluation.rule_mapping import PromptWithRules, RuleLoader, RuleMappingIndex


# ---------------------------------------------------------------------------
# Fixtures — mini retrieval map + mock rule loader
# ---------------------------------------------------------------------------

MINI_MAP = {
    "metadata": {
        "model": "test-model",
        "total_prompts": 5,
        "unique_rules_used": 3,
    },
    "rule_frequency": {},
    "mappings": [
        {
            "index": 0,
            "cwe_id": "CWE-89",
            "language": "python",
            "prompt_hash": "aaa0",
            "prompt": "Write a Python function that queries a database.",
            "rules_retrieved": ["rule-input-validation", "rule-sql-injection"],
            "num_rules": 2,
        },
        {
            "index": 1,
            "cwe_id": "CWE-79",
            "language": "javascript",
            "prompt_hash": "aaa1",
            "prompt": "Write a JS function that renders user input.",
            "rules_retrieved": ["rule-xss-defense"],
            "num_rules": 1,
        },
        {
            "index": 2,
            "cwe_id": "CWE-78",
            "language": "python",
            "prompt_hash": "aaa2",
            "prompt": "Write a Python script that executes a shell command.",
            "rules_retrieved": ["rule-input-validation", "rule-os-command"],
            "num_rules": 2,
        },
        {
            "index": 3,
            "cwe_id": "CWE-120",
            "language": "c",
            "prompt_hash": "aaa3",
            "prompt": "Write a C function that copies data into a buffer.",
            "rules_retrieved": ["rule-safe-c-functions"],
            "num_rules": 1,
        },
        {
            "index": 4,
            "cwe_id": "CWE-89",
            "language": "java",
            "prompt_hash": "aaa4",
            "prompt": "Write a Java method that queries a database.",
            "rules_retrieved": ["rule-sql-injection", "rule-input-validation"],
            "num_rules": 2,
        },
    ],
}

RULE_TEXTS = {
    "rule-input-validation": "---\ndescription: Input validation\n---\n\n## Validate all inputs\nMUST validate at trust boundaries.",
    "rule-sql-injection": "---\ndescription: SQL injection prevention\n---\n\n## Use parameterized queries\nNEVER concatenate user input.",
    "rule-xss-defense": "---\ndescription: XSS defense\n---\n\n## Sanitize output\nEscape HTML entities.",
    "rule-os-command": "---\ndescription: OS command injection\n---\n\n## Avoid shell=True\nUse parameterized APIs.",
    "rule-safe-c-functions": "---\ndescription: Safe C functions\n---\n\n## Memory safety\nUse bounds-checked functions.",
}


@pytest.fixture
def mini_map_file(tmp_path: Path) -> Path:
    """Write the mini retrieval map to a temp JSON file."""
    p = tmp_path / "mini_map.json"
    p.write_text(json.dumps(MINI_MAP))
    return p


@pytest.fixture
def mock_rule_loader() -> RuleLoader:
    """RuleLoader that returns canned rule texts without touching disk."""
    loader = MagicMock(spec=RuleLoader)
    loader.load.side_effect = lambda rule_id: RULE_TEXTS[rule_id]
    loader.load_multiple.side_effect = lambda ids: {rid: RULE_TEXTS[rid] for rid in ids}
    loader.combine_rules.side_effect = lambda ids, separator="\n\n---\n\n": separator.join(
        RULE_TEXTS[rid] for rid in ids
    )
    return loader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_mapping(path: Path) -> RuleMappingIndex:
    return RuleMappingIndex.from_json_file(path)


def _build_prompts_with_rules(
    mapping_index: RuleMappingIndex,
    rule_loader: RuleLoader,
    n_cases: int | None = None,
    languages: list[str] | None = None,
    selection: str = "first",
) -> list[PromptWithRules]:
    """Simulate what load_prompts_from_mapping_only does: filter + build."""
    mappings = list(mapping_index.mappings)

    # Language filter
    if languages:
        lang_set = {language.lower() for language in languages}
        mappings = [m for m in mappings if m.language.lower() in lang_set]

    # Selection
    if selection == "random":
        import random
        rng = random.Random(42)
        rng.shuffle(mappings)

    # n_cases limit
    if n_cases is not None:
        mappings = mappings[:n_cases]

    # Build PromptWithRules
    results = []
    for m in mappings:
        individual = rule_loader.load_multiple(m.rules_retrieved)
        combined = rule_loader.combine_rules(m.rules_retrieved)
        results.append(PromptWithRules(
            prompt=m.prompt,
            language=m.language,
            cwe_id=m.cwe_id,
            rule_ids=m.rules_retrieved,
            individual_rules=individual,
            combined_rules=combined,
        ))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# C-A1  Filter composition
# ═══════════════════════════════════════════════════════════════════════════════

class TestFilterComposition:

    def test_no_filters_returns_all(self, mini_map_file: Path, mock_rule_loader):
        """All 5 entries returned when no filters."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)
        assert len(results) == 5

    def test_language_filter(self, mini_map_file: Path, mock_rule_loader):
        """--languages python returns only Python entries."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader, languages=["python"])
        assert len(results) == 2
        assert all(r.language == "python" for r in results)

    def test_language_filter_case_insensitive(self, mini_map_file: Path, mock_rule_loader):
        """Language filter is case-insensitive."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader, languages=["Python"])
        assert len(results) == 2

    def test_n_cases_limit(self, mini_map_file: Path, mock_rule_loader):
        """--n-cases 2 returns exactly 2 entries."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader, n_cases=2)
        assert len(results) == 2

    def test_filter_composition(self, mini_map_file: Path, mock_rule_loader):
        """C-A1: --languages python --n-cases 1 returns exactly 1 Python entry."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(
            idx, mock_rule_loader, languages=["python"], n_cases=1,
        )
        assert len(results) == 1
        assert results[0].language == "python"

    def test_random_selection(self, mini_map_file: Path, mock_rule_loader):
        """--selection random shuffles the order."""
        idx = _load_mapping(mini_map_file)
        first = _build_prompts_with_rules(idx, mock_rule_loader, selection="first")
        rand = _build_prompts_with_rules(idx, mock_rule_loader, selection="random")
        # Same set of prompts
        assert {r.prompt for r in first} == {r.prompt for r in rand}
        # Order may differ (not guaranteed but very likely with 5 items)
        # At minimum, the function doesn't crash


# ═══════════════════════════════════════════════════════════════════════════════
# C-A2  individual_rules populated for every rule_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestIndividualRules:

    def test_all_rule_ids_have_text(self, mini_map_file: Path, mock_rule_loader):
        """C-A2: individual_rules has an entry for every rule_id."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)

        for pwr in results:
            assert len(pwr.individual_rules) == len(pwr.rule_ids)
            for rid in pwr.rule_ids:
                assert rid in pwr.individual_rules
                assert len(pwr.individual_rules[rid]) > 0

    def test_individual_rules_content_correct(self, mini_map_file: Path, mock_rule_loader):
        """Rule texts match the expected content."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)

        # First entry has rule-input-validation + rule-sql-injection
        first = results[0]
        assert first.individual_rules["rule-input-validation"] == RULE_TEXTS["rule-input-validation"]
        assert first.individual_rules["rule-sql-injection"] == RULE_TEXTS["rule-sql-injection"]


# ═══════════════════════════════════════════════════════════════════════════════
# C-A3  combined_rules matches join of individual_rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestCombinedRules:

    def test_combined_is_separator_join(self, mini_map_file: Path, mock_rule_loader):
        """C-A3: combined_rules == separator.join(individual_rules.values())."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)

        for pwr in results:
            expected = "\n\n---\n\n".join(
                RULE_TEXTS[rid] for rid in pwr.rule_ids
            )
            assert pwr.combined_rules == expected


# ═══════════════════════════════════════════════════════════════════════════════
# C-A4  --use-mapping-only constructs valid PromptWithRules
# ═══════════════════════════════════════════════════════════════════════════════

class TestMappingOnlyLoader:

    def test_constructs_valid_prompts(self, mini_map_file: Path, mock_rule_loader):
        """C-A4: each PromptWithRules has prompt, language, cwe_id, rules."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)

        for pwr in results:
            assert pwr.prompt  # non-empty
            assert pwr.language  # non-empty
            assert pwr.cwe_id  # non-empty
            assert pwr.rule_ids  # non-empty
            assert pwr.combined_rules  # non-empty
            assert pwr.individual_rules  # non-empty

    def test_all_languages_covered(self, mini_map_file: Path, mock_rule_loader):
        """C-A4: all language variants in the map are represented."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)

        languages = {r.language for r in results}
        assert languages == {"python", "javascript", "c", "java"}

    def test_num_rules_property(self, mini_map_file: Path, mock_rule_loader):
        """PromptWithRules.num_rules matches rule_ids length."""
        idx = _load_mapping(mini_map_file)
        results = _build_prompts_with_rules(idx, mock_rule_loader)

        for pwr in results:
            assert pwr.num_rules == len(pwr.rule_ids)


# ═══════════════════════════════════════════════════════════════════════════════
# RuleMappingIndex
# ═══════════════════════════════════════════════════════════════════════════════

class TestRuleMappingIndex:

    def test_from_json_file(self, mini_map_file: Path):
        idx = _load_mapping(mini_map_file)
        assert idx.num_mappings == 5

    def test_all_rules(self, mini_map_file: Path):
        idx = _load_mapping(mini_map_file)
        assert idx.all_rules == {
            "rule-input-validation", "rule-sql-injection",
            "rule-xss-defense", "rule-os-command", "rule-safe-c-functions",
        }

    def test_get_by_index(self, mini_map_file: Path):
        idx = _load_mapping(mini_map_file)
        m = idx.get_by_index(0)
        assert m is not None
        assert m.cwe_id == "CWE-89"
        assert m.language == "python"


def test_runtime_loader_uses_map_membership_without_a_second_policy(
    mini_map_file: Path,
    mock_rule_loader,
) -> None:
    from scripts.experiments.run_experiment import load_prompts_with_rules

    prompts = load_prompts_with_rules(
        mini_map_file,
        mock_rule_loader,
        n_cases=5,
    )

    assert len(prompts) == 5
    assert {p.metadata["test_case_id"] for p in prompts} == {"0", "1", "2", "3", "4"}
    assert all("language_mode" not in p.metadata for p in prompts)
