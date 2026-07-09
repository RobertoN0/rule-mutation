"""
Composite fitness evaluator for the SBST hill-climbing optimizer.

Computes two signals per test case, which the (1+1) EA aggregates into the
three objectives of the full-chromosome Pareto archive (see ``ea_optimizer`` /
``chromosome``):

    semgrep_delta   : float   — semgrep_score - baseline_score (effectiveness)
    code_divergence : float   — 1 - CodeBLEU(generated, reference)  [0, 1]

``semgrep_delta`` is the effectiveness signal; ``code_divergence`` measures how
much the mutation changed the LLM's actual code output.  The EA aggregates these
across a rule's test cases into f1 = total semgrep delta, f2 = proportion of
divergent cases, f3 = conditional mean divergence, and admits a candidate to the
archive iff it is **not Pareto-dominated** on (f1, f2, f3). 

Reference code
--------------
``reference_codes`` maps ``str(test_case_id)`` to the code the LLM produced
when given the *original* unmodified rule (captured at iteration 0).  Cases
not in this dict get ``code_divergence = 0.0``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


# CodeBLEU emits a bare ``logging.warning`` on the root logger for every
# evaluation whose *reference* code yields no tree-sitter data-flow edges
# ("...no reference data-flows extracted ... the data-flow match score
# degenerates to 0..."). This is a known CodeBLEU/DFG_python limitation: its
# Python data-flow extractor raises a KeyError on attribute-target assignments
# to bare string literals (e.g. ``self.api_key = 'X'``), which the library
# swallows into an empty DFG. It is harmless here — data-flow is one of four
# CodeBLEU sub-scores and only floors to 0 for that one sample — but at scale it
# floods run logs (one line per affected prompt per iteration). Drop just that
# message, leaving every other warning untouched.
class _DropCodeBleuDataflowWarning(logging.Filter):
    _NEEDLE = "no reference data-flows extracted"

    def filter(self, record: logging.LogRecord) -> bool:
        return self._NEEDLE not in record.getMessage()


def _install_codebleu_warning_filter() -> None:
    """Attach the data-flow-warning filter to the root logger exactly once."""
    root = logging.getLogger()
    if not any(isinstance(f, _DropCodeBleuDataflowWarning) for f in root.filters):
        root.addFilter(_DropCodeBleuDataflowWarning())


_install_codebleu_warning_filter()


# CodeBLEU language aliases — map our internal language names to codebleu lang strings
_LANG_MAP: dict[str, str] = {
    "python": "python",
    "java": "java",
    "c": "c",
    "javascript": "javascript",
    "js": "javascript",
}
_DEFAULT_LANG = "python"


@dataclass
class CompositeFitnessResult:
    """Fitness signals for one test-case sample."""

    semgrep_delta: float
    """Raw Semgrep score change: semgrep_score - baseline_score."""

    code_divergence: float
    """1 - CodeBLEU(generated_code, reference_code).  0.0 when reference absent."""

    components: dict[str, Any] = field(default_factory=dict)
    """Raw component values for logging and analysis."""


class CompositeFitnessEvaluator:
    """Computes per-test-case fitness signals for the hill climber.

    Parameters
    ----------
    reference_codes : dict[str, str]
        Maps ``str(test_case_id)`` to reference code captured at iter-0.
        Cases not present get ``code_divergence = 0.0``.
    lang : str
        Programming language of the generated code (e.g. ``"python"``,
        ``"java"``, ``"c"``).  Forwarded to CodeBLEU.  Defaults to
        ``"python"`` when the language is unknown or unsupported.
    """

    def __init__(
        self,
        reference_codes: dict[str, str],
        lang: str = _DEFAULT_LANG,
    ) -> None:
        self.reference_codes = reference_codes
        self._lang = _LANG_MAP.get(lang.lower(), _DEFAULT_LANG)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_reference(self, test_case_id: str | int, code: str) -> None:
        """Register the iter-0 reference code for a test case.

        Used instead of writing ``self.reference_codes[...]`` from outside, so
        the evaluator owns its own state (loose coupling — see D15 in
        CHROMOSOME_RESTRUCTURE_PLAN.md)."""
        self.reference_codes[str(test_case_id)] = code

    def evaluate(
        self,
        semgrep_score: float,
        baseline_score: float,
        generated_code: str,
        test_case_id: str | int,
        lang: str | None = None,
    ) -> CompositeFitnessResult:
        """Compute fitness signals for one generated code sample.

        Parameters
        ----------
        semgrep_score : float
            Severity-weighted Semgrep score for the candidate (mutated rule).
        baseline_score : float
            Severity-weighted Semgrep score for the same case at baseline.
        generated_code : str
            LLM-generated code for this test case under the mutated rule.
        test_case_id : str | int
            Used to look up reference code in ``self.reference_codes``.
        lang : str | None
            Per-call language override. When set, CodeBLEU uses this
            case's language instead of the constructor default — required for
            mixed-language runs where one evaluator scores both Python and Java
            cases. Unknown values fall back to the constructor default.
        """
        raw_semgrep_delta = semgrep_score - baseline_score

        effective_lang = (
            _LANG_MAP.get(lang.lower(), self._lang) if lang else self._lang
        )

        ref_code = self.reference_codes.get(str(test_case_id))
        if ref_code and generated_code:
            raw_code_divergence = self._code_divergence(
                generated_code, ref_code, lang=effective_lang
            )
        else:
            raw_code_divergence = 0.0

        return CompositeFitnessResult(
            semgrep_delta=raw_semgrep_delta,
            code_divergence=raw_code_divergence,
            components={
                "raw_semgrep_delta": raw_semgrep_delta,
                "raw_code_divergence": raw_code_divergence,
                "has_reference_code": ref_code is not None,
                "lang": effective_lang,
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _code_divergence(
        self, generated: str, reference: str, lang: str | None = None
    ) -> float:
        """1 - CodeBLEU(generated, reference); falls back to token-BLEU.

        ``lang`` overrides the constructor default for this call.
        """
        codebleu_lang = lang or self._lang
        try:
            from codebleu import calc_codebleu  # type: ignore

            result = calc_codebleu(
                [reference], [generated], lang=codebleu_lang
            )
            score = float(result["codebleu"])
            return round(max(0.0, 1.0 - score), 4)
        except ImportError:
            log.warning("codebleu not installed; falling back to token-BLEU")
            return self._token_bleu_divergence(generated, reference)
        except Exception as exc:
            log.warning("CodeBLEU computation failed (%s); falling back to token-BLEU", exc)
            return self._token_bleu_divergence(generated, reference)

    @staticmethod
    def _token_bleu_divergence(generated: str, reference: str) -> float:
        """1 - sentence_BLEU on whitespace tokens (nltk fallback)."""
        try:
            from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction  # type: ignore

            ref_tokens = reference.split()
            hyp_tokens = generated.split()
            if not ref_tokens or not hyp_tokens:
                return 0.0
            score = sentence_bleu(
                [ref_tokens],
                hyp_tokens,
                smoothing_function=SmoothingFunction().method1,
            )
            return round(max(0.0, 1.0 - score), 4)
        except Exception as exc:
            log.warning("Token-BLEU fallback also failed: %s", exc)
            return 0.0
