"""Canonical baseline-classification labels.

These labels are retained because the frozen schema-4 analyzer still imports
them. Runtime search never uses them.
"""
from __future__ import annotations

ALWAYS_SAFE = "ALWAYS_SAFE"
ALWAYS_VULNERABLE = "ALWAYS_VULNERABLE"
SOMETIMES_VULNERABLE = "SOMETIMES_VULNERABLE"
FIXED_BY_RULES = "FIXED_BY_RULES"

ALL = (ALWAYS_SAFE, ALWAYS_VULNERABLE, SOMETIMES_VULNERABLE, FIXED_BY_RULES)

DISPLAY = {
    ALWAYS_SAFE: "Always Safe",
    ALWAYS_VULNERABLE: "Always Vulnerable",
    SOMETIMES_VULNERABLE: "Sometimes Vulnerable",
    FIXED_BY_RULES: "Fixed by Rules",
}

LEGACY_ALIASES = {
    "NEVER": ALWAYS_SAFE,
    "PERSISTENT": ALWAYS_VULNERABLE,
    "VARIABLE": SOMETIMES_VULNERABLE,
    "RULE_FIXED": FIXED_BY_RULES,
}


def normalize(value: str) -> str:
    """Map a raw class cell to the canonical token."""
    v = (value or "").strip()
    return LEGACY_ALIASES.get(v, v)


def display(value: str) -> str:
    """Human label for a class token."""
    return DISPLAY.get(normalize(value), value)
