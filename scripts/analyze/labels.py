"""Canonical baseline-classification labels — single source of truth.

Per-task baseline behaviour classes (model-specific, from the 40-seed baseline).
The runtime search never uses these; they are an analysis/report-only vocabulary.

* Canonical tokens (``ALWAYS_SAFE`` …) are the machine values written to CSVs and
  compared in code — clean UPPER_SNAKE, safe as dict keys / CSV cells.
* ``DISPLAY`` maps each token to the human label used in figures, tables, and
  report prose. Use ``display()`` at the presentation boundary only.
* ``LEGACY_ALIASES`` normalises the pre-rename tokens so an old CSV still loads.

Rename (2026-07): NEVER→ALWAYS_SAFE, PERSISTENT→ALWAYS_VULNERABLE,
VARIABLE→SOMETIMES_VULNERABLE, RULE_FIXED→FIXED_BY_RULES.
"""
from __future__ import annotations

ALWAYS_SAFE = "ALWAYS_SAFE"
ALWAYS_VULNERABLE = "ALWAYS_VULNERABLE"
SOMETIMES_VULNERABLE = "SOMETIMES_VULNERABLE"
FIXED_BY_RULES = "FIXED_BY_RULES"

# Stable order for report tables / bucket printing.
ALL = (ALWAYS_SAFE, ALWAYS_VULNERABLE, SOMETIMES_VULNERABLE, FIXED_BY_RULES)

DISPLAY = {
    ALWAYS_SAFE:          "Always Safe",
    ALWAYS_VULNERABLE:    "Always Vulnerable",
    SOMETIMES_VULNERABLE: "Sometimes Vulnerable",
    FIXED_BY_RULES:       "Fixed by Rules",
}

# Pre-rename tokens → canonical, so a stray old CSV still normalises on read.
LEGACY_ALIASES = {
    "NEVER":      ALWAYS_SAFE,
    "PERSISTENT": ALWAYS_VULNERABLE,
    "VARIABLE":   SOMETIMES_VULNERABLE,
    "RULE_FIXED": FIXED_BY_RULES,
}


def normalize(value: str) -> str:
    """Map a raw class cell (new or legacy token) to the canonical token.

    Unknown/blank values pass through unchanged (callers treat '' as unknown)."""
    v = (value or "").strip()
    return LEGACY_ALIASES.get(v, v)


def display(value: str) -> str:
    """Human label for a class token (accepts canonical or legacy tokens)."""
    return DISPLAY.get(normalize(value), value)
