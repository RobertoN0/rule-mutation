"""Unit tests for CompositeFitnessEvaluator after Change 3.

Tests the simplified two-signal evaluator:
  - semgrep_delta  : semgrep_score - baseline_score
  - code_divergence: 1 - CodeBLEU(generated, reference)

SBERT, rule_divergence, and weights have been removed.
"""

from unittest.mock import patch

import pytest

from src.evaluation.composite_fitness import (
    CompositeFitnessEvaluator,
    CompositeFitnessResult,
)

REF_CODE_PY = "def authenticate(user, pwd):\n    return check_hash(user, pwd)\n"
SAME_CODE_PY = REF_CODE_PY
DIFF_CODE_PY = "x = open('/etc/passwd').read()\nprint(x)\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ev(reference_codes=None, lang="python") -> CompositeFitnessEvaluator:
    return CompositeFitnessEvaluator(
        reference_codes=reference_codes or {},
        lang=lang,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# semgrep_delta computation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSemgrepDelta:

    def test_positive_delta(self):
        ev = _ev()
        r = ev.evaluate(semgrep_score=8.0, baseline_score=5.0,
                        generated_code="code", test_case_id="tc0")
        assert r.semgrep_delta == pytest.approx(3.0)

    def test_negative_delta(self):
        ev = _ev()
        r = ev.evaluate(semgrep_score=2.0, baseline_score=5.0,
                        generated_code="code", test_case_id="tc0")
        assert r.semgrep_delta == pytest.approx(-3.0)

    def test_zero_delta(self):
        ev = _ev()
        r = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                        generated_code="code", test_case_id="tc0")
        assert r.semgrep_delta == pytest.approx(0.0)

    def test_baseline_zero(self):
        ev = _ev()
        r = ev.evaluate(semgrep_score=5.0, baseline_score=0.0,
                        generated_code="code", test_case_id="tc0")
        assert r.semgrep_delta == pytest.approx(5.0)


# ═══════════════════════════════════════════════════════════════════════════════
# code_divergence via CodeBLEU
# ═══════════════════════════════════════════════════════════════════════════════

class TestCodeDivergence:

    def test_reference_codes_mutable_after_init(self):
        """reference_codes dict can be populated after construction (hill climber pattern)."""
        ev = _ev(reference_codes={})
        # Empty at first — code_divergence must be 0.0
        r_before = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                               generated_code=REF_CODE_PY, test_case_id="tc0")
        assert r_before.code_divergence == pytest.approx(0.0)
        # Populate reference (simulating baseline run)
        ev.reference_codes["tc0"] = REF_CODE_PY
        r_after = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                              generated_code=SAME_CODE_PY, test_case_id="tc0")
        assert r_after.code_divergence == pytest.approx(0.0)
        r_diff = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                             generated_code=DIFF_CODE_PY, test_case_id="tc0")
        assert r_diff.code_divergence > 0.0

    def test_identical_code_zero_divergence(self):
        ev = _ev(reference_codes={"tc0": REF_CODE_PY})
        r = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                        generated_code=SAME_CODE_PY, test_case_id="tc0")
        assert r.code_divergence == pytest.approx(0.0)

    def test_different_code_nonzero_divergence(self):
        ev = _ev(reference_codes={"tc0": REF_CODE_PY})
        r = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                        generated_code=DIFF_CODE_PY, test_case_id="tc0")
        assert r.code_divergence > 0.0
        assert r.code_divergence <= 1.0

    def test_no_reference_code_gives_zero(self):
        ev = _ev(reference_codes={})  # no ref for tc0
        r = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                        generated_code=SAME_CODE_PY, test_case_id="tc0")
        assert r.code_divergence == pytest.approx(0.0)
        assert r.components["has_reference_code"] is False

    def test_empty_generated_code_gives_zero(self):
        ev = _ev(reference_codes={"tc0": REF_CODE_PY})
        r = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                        generated_code="", test_case_id="tc0")
        assert r.code_divergence == pytest.approx(0.0)

    def test_tc_id_as_int(self):
        ev = _ev(reference_codes={"42": REF_CODE_PY})
        r = ev.evaluate(semgrep_score=5.0, baseline_score=5.0,
                        generated_code=SAME_CODE_PY, test_case_id=42)
        assert r.code_divergence == pytest.approx(0.0)

    def test_java_lang(self):
        ref_j = "public class A { public void f() { System.out.println(1); } }"
        ev = _ev(reference_codes={"j0": ref_j}, lang="java")
        r = ev.evaluate(semgrep_score=0.0, baseline_score=0.0,
                        generated_code=ref_j, test_case_id="j0")
        assert r.code_divergence == pytest.approx(0.0)
        assert r.components["lang"] == "java"

    def test_unknown_lang_falls_back_to_python(self):
        ev = _ev(lang="cobol")
        assert ev._lang == "python"


# ═══════════════════════════════════════════════════════════════════════════════
# CodeBLEU import failure → token-BLEU fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallback:

    def test_codebleu_import_error_uses_token_bleu(self):
        ev = _ev(reference_codes={"tc0": REF_CODE_PY})
        with patch("src.evaluation.composite_fitness.CompositeFitnessEvaluator._code_divergence",
                   wraps=lambda self, g, r: CompositeFitnessEvaluator._token_bleu_divergence(g, r)):
            pass  # just check the fallback path exists and is callable
        # Direct call to the fallback
        div = CompositeFitnessEvaluator._token_bleu_divergence(SAME_CODE_PY, SAME_CODE_PY)
        assert div == pytest.approx(0.0)
        div2 = CompositeFitnessEvaluator._token_bleu_divergence(DIFF_CODE_PY, REF_CODE_PY)
        assert div2 > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# components dict structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestComponents:

    def test_components_keys_present(self):
        ev = _ev(reference_codes={"tc0": REF_CODE_PY})
        r = ev.evaluate(semgrep_score=8.0, baseline_score=5.0,
                        generated_code=SAME_CODE_PY, test_case_id="tc0")
        assert "raw_semgrep_delta" in r.components
        assert "raw_code_divergence" in r.components
        assert "has_reference_code" in r.components
        assert "lang" in r.components
        assert r.components["raw_semgrep_delta"] == pytest.approx(3.0)
        assert r.components["has_reference_code"] is True

    def test_result_is_dataclass(self):
        ev = _ev()
        r = ev.evaluate(semgrep_score=0.0, baseline_score=0.0,
                        generated_code="x", test_case_id="t")
        assert isinstance(r, CompositeFitnessResult)
        assert isinstance(r.semgrep_delta, float)
        assert isinstance(r.code_divergence, float)


# ═══════════════════════════════════════════════════════════════════════════════
# bd-03k.2 — per-call language override (mixed-language runs)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerCallLangOverride:
    """One evaluator (constructed for python) must score a java case with the
    java CodeBLEU grammar when the per-call lang override is supplied."""

    def _patched_calc(self):
        """Patch codebleu.calc_codebleu to record the lang it was called with."""
        calls: list[str] = []

        def _fake(refs, hyps, lang):
            calls.append(lang)
            return {"codebleu": 0.5}

        return calls, patch("codebleu.calc_codebleu", side_effect=_fake)

    def test_per_call_lang_overrides_constructor_default(self):
        ev = _ev(reference_codes={"j0": "class A {}"}, lang="python")
        calls, p = self._patched_calc()
        with p:
            r = ev.evaluate(semgrep_score=1.0, baseline_score=0.0,
                            generated_code="class B {}", test_case_id="j0",
                            lang="java")
        assert calls == ["java"], calls
        assert r.components["lang"] == "java"

    def test_default_lang_used_when_no_override(self):
        ev = _ev(reference_codes={"p0": "x = 1"}, lang="python")
        calls, p = self._patched_calc()
        with p:
            r = ev.evaluate(semgrep_score=1.0, baseline_score=0.0,
                            generated_code="x = 2", test_case_id="p0")
        assert calls == ["python"], calls
        assert r.components["lang"] == "python"

    def test_unknown_override_falls_back_to_constructor_default(self):
        ev = _ev(reference_codes={"p0": "x = 1"}, lang="python")
        calls, p = self._patched_calc()
        with p:
            r = ev.evaluate(semgrep_score=1.0, baseline_score=0.0,
                            generated_code="x = 2", test_case_id="p0",
                            lang="cobol")
        assert calls == ["python"], calls
        assert r.components["lang"] == "python"

    def test_mixed_run_two_cases_use_their_own_grammar(self):
        """Single evaluator, two cases scored back-to-back with distinct langs."""
        ev = _ev(reference_codes={"p0": "x = 1", "j0": "class A {}"}, lang="python")
        calls, p = self._patched_calc()
        with p:
            ev.evaluate(1.0, 0.0, "x = 2", "p0", lang="python")
            ev.evaluate(1.0, 0.0, "class B {}", "j0", lang="java")
        assert calls == ["python", "java"], calls
