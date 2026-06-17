"""
Typed accessors for the three saved granularities of a schema-2 run.

The raw artifacts are nested dicts; reading them with
``rec.get("fitness", {}).get("weighted_score", 0.0) or 0.0`` everywhere is
fragile and noisy. This module centralises that access so every metric module
speaks the same vocabulary and a schema change is fixed in one place.

Granularities:
  - prompt record   -> intermediate/{iter}.jsonl + baseline.jsonl rows
  - iteration record-> iterations.jsonl rows
  - archive entry   -> archive_snapshots/iter*.json -> archives[rule].current_entries

No IO, no matplotlib — pure dict access so it is trivially unit-testable.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Generic dotted-path access (the field-agnostic series engine relies on this)
# ---------------------------------------------------------------------------

def get_path(rec: dict, path: str, default: Any = None) -> Any:
    """Read ``a.b.c`` out of a nested dict, returning ``default`` if any hop is
    missing or None. ``get_path(it, "selection_meta.parent_f1")`` etc."""
    cur: Any = rec
    for key in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def get_number(rec: dict, path: str, default: float = 0.0) -> float:
    val = get_path(rec, path, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Prompt records (intermediate/*.jsonl, baseline.jsonl)
# ---------------------------------------------------------------------------

def fitness(rec: dict) -> dict:
    return rec.get("fitness", {}) or {}


def weighted_score(rec: dict) -> float:
    return float(fitness(rec).get("weighted_score", 0.0) or 0.0)


def raw_count(rec: dict) -> int:
    return int(fitness(rec).get("raw_count", 0) or 0)


def error_count(rec: dict) -> int:
    return int(fitness(rec).get("error_count", 0) or 0)


def warning_count(rec: dict) -> int:
    return int(fitness(rec).get("warning_count", 0) or 0)


def fitness_counts(rec: dict) -> tuple[int, int, int]:
    """(raw_count, error_count, warning_count)."""
    return raw_count(rec), error_count(rec), warning_count(rec)


def code_divergence(rec: dict) -> float:
    return float(fitness(rec).get("code_divergence", 0.0) or 0.0)


def composite_score(rec: dict) -> float:
    return float(fitness(rec).get("composite_score", 0.0) or 0.0)


def check_ids(rec: dict) -> list[str]:
    return list(fitness(rec).get("check_ids", []) or [])


def test_case_id(rec: dict) -> str:
    return str(rec.get("test_case_id", "?"))


def language(rec: dict) -> str:
    return str(rec.get("language", "?"))


def cwe_id(rec: dict) -> str:
    return str(rec.get("cwe_id", "?"))


def _rules_used(rec: dict) -> dict:
    return rec.get("rules_used", {}) or {}


def original_rule_ids(rec: dict) -> list[str]:
    return list(_rules_used(rec).get("original_rule_ids") or [])


def target_rule_id(rec: dict) -> str | None:
    return _rules_used(rec).get("target_rule_id")


def is_applicable(rec: dict, fallback_rule_id: str | None = None) -> bool:
    """Was the targeted rule actually retrieved for this prompt?

    Prefers the explicit ``rule_was_applicable`` flag; falls back to membership
    of the target (or ``fallback_rule_id``) in the prompt's original rule set.
    """
    rules_used = _rules_used(rec)
    flag = rules_used.get("rule_was_applicable")
    if flag is True:
        return True
    if flag is False:
        return False
    target = rules_used.get("target_rule_id") or fallback_rule_id
    return bool(target and target in (rules_used.get("original_rule_ids") or []))


# ---------------------------------------------------------------------------
# Iteration records (iterations.jsonl)
# ---------------------------------------------------------------------------

def iter_num(it: dict) -> int:
    return int(it.get("iter", 0))


def rule_id(it: dict) -> str | None:
    return it.get("rule_id")


def mutation_chain(it: dict) -> list[str]:
    return list(it.get("mutation_chain") or [])


def objectives(it: dict) -> tuple[float, float, float]:
    """(f1, f2, f3) for an iteration, with None coerced to 0.0."""
    return (
        float(it.get("f1") or 0.0),
        float(it.get("f2") or 0.0),
        float(it.get("f3") or 0.0),
    )


# ---------------------------------------------------------------------------
# Archive entries (archive_snapshots/iter*.json -> archives[rule].current_entries)
# ---------------------------------------------------------------------------

def entry_objectives(entry: dict) -> tuple[float, float, float]:
    return (
        float(entry.get("f1") or 0.0),
        float(entry.get("f2") or 0.0),
        float(entry.get("f3") or 0.0),
    )


def short_rule(rule_id: str) -> str:
    """Compact label: codeguard-0-foo -> cg-0-foo."""
    return (rule_id or "").replace("codeguard-", "cg-")
