"""Regression tests for post-hoc Phase-3 structural sanitisation."""

from scripts.analyze.sanitize_phase3_candidates import (
    is_valid,
    sanitize_rule,
    signature_delta,
)


ORIGINAL = """\
---
description: fixture
---

## Container
- Capabilities: use `--cap-drop all` and add only what is needed.
- Use postMessage carefully.

```c
// Bad - unsafe
strcpy(dest, src);
```

## Final
Keep this prose.
"""


def test_sanitizer_restores_missing_and_changed_safe_zones():
    candidate = """\
---
description: fixture
---

## Container
- Capabilities should be limited and only what is needed added.
- Use `postMessage` carefully.

```c
// Not Advisable - unsafe
strcpy(dest, src);
```## Final
Keep this rewritten prose.
"""
    assert not is_valid(signature_delta(ORIGINAL, candidate))

    sanitized, notes = sanitize_rule(ORIGINAL, candidate, "codeguard-fixture")

    assert is_valid(signature_delta(ORIGINAL, sanitized))
    assert "`--cap-drop all`" in sanitized
    assert "Use postMessage carefully" in sanitized
    assert "// Bad - unsafe" in sanitized
    assert "## Final" in sanitized
    assert "rewritten prose" in sanitized
    assert any("reinserted_inline" in note for note in notes)
    assert any("unwrapped_added_inline" in note for note in notes)


def test_valid_candidate_is_unchanged_by_sanitizer():
    sanitized, notes = sanitize_rule(ORIGINAL, ORIGINAL, "codeguard-fixture")
    assert sanitized == ORIGINAL
    assert notes == []
