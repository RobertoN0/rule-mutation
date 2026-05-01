"""
Composite fitness evaluator for the SBST hill-climbing optimizer.

Tracks two signals per test case, used by the lexicographic acceptance
criterion in the hill climber:

    semgrep_delta   : float   — semgrep_score - baseline_score (primary axis)
    code_divergence : float   — 1 - CodeBLEU(generated, reference)  [0, 1]

``semgrep_delta`` is the primary fitness signal.  ``code_divergence`` is the
secondary axis: it measures how much the mutation changed the LLM's actual
code output, and is used to break ties and avoid semantics-preserving identity
mutations being accepted.

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

    def evaluate(
        self,
        semgrep_score: float,
        baseline_score: float,
        generated_code: str,
        test_case_id: str | int,
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
        """
        raw_semgrep_delta = semgrep_score - baseline_score

        ref_code = self.reference_codes.get(str(test_case_id))
        if ref_code and generated_code:
            raw_code_divergence = self._code_divergence(generated_code, ref_code)
        else:
            raw_code_divergence = 0.0

        return CompositeFitnessResult(
            semgrep_delta=raw_semgrep_delta,
            code_divergence=raw_code_divergence,
            components={
                "raw_semgrep_delta": raw_semgrep_delta,
                "raw_code_divergence": raw_code_divergence,
                "has_reference_code": ref_code is not None,
                "lang": self._lang,
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _code_divergence(self, generated: str, reference: str) -> float:
        """1 - CodeBLEU(generated, reference); falls back to token-BLEU."""
        try:
            from codebleu import calc_codebleu  # type: ignore

            result = calc_codebleu(
                [reference], [generated], lang=self._lang
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
