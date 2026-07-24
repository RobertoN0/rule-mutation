from __future__ import annotations

import pytest

from scripts.analyze.validate_search_run import _completion_state


@pytest.mark.parametrize(
    ("requested", "completed", "expected"),
    [
        (0, 0, "complete"),
        (20, 20, "complete"),
        (20, 13, "partial"),
        (20, 21, "overrun"),
        (None, 0, "unknown"),
        (True, 1, "unknown"),
        (-1, 0, "unknown"),
    ],
)
def test_completion_state_separates_health_from_budget_completion(
    requested: object,
    completed: int,
    expected: str,
) -> None:
    assert _completion_state(requested, completed) == expected
