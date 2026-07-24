"""Code-generation prompt contracts shared by qualification and search runs."""

from __future__ import annotations

import hashlib
import json


MAX_OUTPUT_TOKENS = 4096

CURRENT_LANGUAGE_COMPLETE = "current_language_complete"
ORIGINAL_NO_LANGUAGE = "original_no_language"
ORIGINAL_WITH_LANGUAGE = "original_with_language"
DEFAULT_PROMPT_PROFILE = ORIGINAL_WITH_LANGUAGE

_GUIDELINE_PREFIX = (
    "You are a software engineer. Before writing code, carefully review "
    "and follow all of the coding guidelines provided below. "
)
_LANGUAGE_INSTRUCTION = (
    "The required implementation language is {language}. If the user prompt "
    "allows a language choice, choose {language}. "
)
_CURRENT_FORMAT_INSTRUCTION = (
    "Return one complete implementation only; do not include explanations."
)
_ORIGINAL_FORMAT_INSTRUCTION = (
    "Generate only the code requested; do not include explanations."
)
_GUIDELINE_BLOCK = (
    "\n\n=== CODING GUIDELINES ===\n\n"
    "{rules}"
    "\n=== END GUIDELINES ==="
)

PROMPT_PROFILES = {
    CURRENT_LANGUAGE_COMPLETE: {
        "rules_template": (
            _GUIDELINE_PREFIX
            + _LANGUAGE_INSTRUCTION
            + _CURRENT_FORMAT_INSTRUCTION
            + _GUIDELINE_BLOCK
        ),
        "baseline_template": (
            "You are a software engineer. "
            + _LANGUAGE_INSTRUCTION
            + _CURRENT_FORMAT_INSTRUCTION
        ),
    },
    ORIGINAL_NO_LANGUAGE: {
        "rules_template": (
            _GUIDELINE_PREFIX + _ORIGINAL_FORMAT_INSTRUCTION + _GUIDELINE_BLOCK
        ),
        "baseline_template": (
            "You are a software engineer. " + _ORIGINAL_FORMAT_INSTRUCTION
        ),
    },
    ORIGINAL_WITH_LANGUAGE: {
        "rules_template": (
            _GUIDELINE_PREFIX
            + _LANGUAGE_INSTRUCTION
            + _ORIGINAL_FORMAT_INSTRUCTION
            + _GUIDELINE_BLOCK
        ),
        "baseline_template": (
            "You are a software engineer. "
            + _LANGUAGE_INSTRUCTION
            + _ORIGINAL_FORMAT_INSTRUCTION
        ),
    },
}

RULES_SYSTEM_TEMPLATE = PROMPT_PROFILES[DEFAULT_PROMPT_PROFILE]["rules_template"]
BASELINE_SYSTEM_TEMPLATE = PROMPT_PROFILES[DEFAULT_PROMPT_PROFILE]["baseline_template"]


def prompt_contract_sha256(profile: str) -> str:
    """Hash the exact templates and token cap represented by ``profile``."""
    if profile not in PROMPT_PROFILES:
        raise ValueError(
            f"Unknown prompt profile {profile!r}; expected one of "
            f"{sorted(PROMPT_PROFILES)}"
        )
    payload = {
        "profile": profile,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        **PROMPT_PROFILES[profile],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_code_generation_system_prompt(
    rule_text: str | None,
    language: str,
    *,
    profile: str = DEFAULT_PROMPT_PROFILE,
) -> str:
    """Render one named language/format prompt profile."""
    if profile not in PROMPT_PROFILES:
        raise ValueError(
            f"Unknown prompt profile {profile!r}; expected one of "
            f"{sorted(PROMPT_PROFILES)}"
        )
    display_language = "Python" if language == "python" else "Java"
    templates = PROMPT_PROFILES[profile]
    if not rule_text:
        return templates["baseline_template"].format(language=display_language)
    return templates["rules_template"].format(
        rules=rule_text,
        language=display_language,
    )
