"""Fail-closed safe-zone tests for live LLM rule mutators."""

from src.llm_backends.base import LLMResponse
from src.mutation.llm_based import (
    NegationInjectionMutator,
    ParaphraseMutator,
    VoiceChangeMutator,
)


RULE = """\
---
description: Safe-zone fixture
alwaysApply: false
---

## Guidance

MUST retain `--cap-drop all` while changing this prose.

```c
// MUST remain byte-for-byte identical
char *value = "NEVER rewrite";
```

Ensure the final prose is rewritten.
"""


class RecordingBackend:
    def __init__(self, transform):
        self.transform = transform
        self.seen = None

    def generate(self, *, system, messages, **kwargs):
        self.seen = messages[0]["content"]
        return LLMResponse(
            content=self.transform(self.seen),
            model="test-backend",
            input_tokens=10,
            output_tokens=10,
            latency_ms=1.0,
        )


def _mutators(backend):
    return (
        NegationInjectionMutator(backend),
        VoiceChangeMutator(backend),
        ParaphraseMutator(backend),
    )


def test_all_llm_mutators_hide_and_restore_protected_content():
    for mutator_type in (
        NegationInjectionMutator,
        VoiceChangeMutator,
        ParaphraseMutator,
    ):
        backend = RecordingBackend(
            lambda text: text.replace("MUST retain", "Please retain")
        )
        result = mutator_type(backend).mutate(RULE)

        assert result.changed
        assert "`--cap-drop all`" in result.mutated
        assert "// MUST remain byte-for-byte identical" in result.mutated
        assert "--cap-drop all" not in backend.seen
        assert "char *value" not in backend.seen
        assert "__SAFE_ZONE_INLINE_0000__" in backend.seen
        assert "__SAFE_ZONE_FENCE_0000__" in backend.seen


def test_dropped_placeholder_returns_identity():
    backend = RecordingBackend(
        lambda text: text.replace("__SAFE_ZONE_INLINE_0000__", "")
    )
    result = ParaphraseMutator(backend).mutate(RULE)
    assert not result.changed
    assert "violated safe-zone placeholders" in result.changes[0]


def test_duplicated_or_reordered_placeholder_returns_identity():
    def duplicate(text):
        return text.replace(
            "__SAFE_ZONE_INLINE_0000__",
            "__SAFE_ZONE_INLINE_0000__ __SAFE_ZONE_INLINE_0000__",
        )

    result = VoiceChangeMutator(RecordingBackend(duplicate)).mutate(RULE)
    assert not result.changed


def test_new_inline_span_returns_identity():
    backend = RecordingBackend(
        lambda text: text.replace("final prose", "`new inline span`")
    )
    result = NegationInjectionMutator(backend).mutate(RULE)
    assert not result.changed
    assert "failed safe-zone validation" in result.changes[0]
