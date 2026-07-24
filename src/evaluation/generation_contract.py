"""Code-generation prompt contracts shared by qualification and search runs."""

from __future__ import annotations

import hashlib
import json


MAX_OUTPUT_TOKENS = 4096

_GUIDELINE_PREFIX = (
    "You are a software engineer. Before writing code, carefully review "
    "and follow all of the coding guidelines provided below. "
)
_LANGUAGE_INSTRUCTION = (
    "The required implementation language is {language}. If the user prompt "
    "allows a language choice, choose {language}. "
)
_FORMAT_INSTRUCTION = (
    "Generate only the code requested; do not include explanations."
)
_GUIDELINE_BLOCK = (
    "\n\n=== CODING GUIDELINES ===\n\n"
    "{rules}"
    "\n=== END GUIDELINES ==="
)

RULES_SYSTEM_TEMPLATE = (
    _GUIDELINE_PREFIX
    + _LANGUAGE_INSTRUCTION
    + _FORMAT_INSTRUCTION
    + _GUIDELINE_BLOCK
)
BASELINE_SYSTEM_TEMPLATE = (
    "You are a software engineer. "
    + _LANGUAGE_INSTRUCTION
    + _FORMAT_INSTRUCTION
)


def prompt_contract_sha256() -> str:
    """Hash the exact fixed templates and output-token cap."""
    payload = {
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "rules_template": RULES_SYSTEM_TEMPLATE,
        "baseline_template": BASELINE_SYSTEM_TEMPLATE,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_code_generation_system_prompt(
    rule_text: str | None,
    language: str,
) -> str:
    """Render the fixed code-generation system prompt."""
    display_language = "Python" if language == "python" else "Java"
    if not rule_text:
        return BASELINE_SYSTEM_TEMPLATE.format(language=display_language)
    return RULES_SYSTEM_TEMPLATE.format(
        rules=rule_text,
        language=display_language,
    )
