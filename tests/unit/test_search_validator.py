from __future__ import annotations

import pytest

from scripts.analyze.validate_search_run import (
    _code_call_accounting,
    _completion_state,
)


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


def test_budget_complete_run_still_requires_exact_call_accounting() -> None:
    issue, warning = _code_call_accounting(
        code_calls=2718,
        fresh_prompt_rows=2718,
        termination_reason="evaluation_budget_complete",
        population_size=210,
    )
    assert issue is None
    assert warning is None


@pytest.mark.parametrize("surplus", [1, -1, 17])
def test_budget_complete_run_rejects_any_call_surplus(surplus: int) -> None:
    issue, warning = _code_call_accounting(
        code_calls=2718 + surplus,
        fresh_prompt_rows=2718,
        termination_reason="evaluation_budget_complete",
        population_size=210,
    )
    assert issue is not None
    assert "differs from fresh" in issue
    assert warning is None


@pytest.mark.parametrize("termination", ["wall_time_limit", "rate_limit"])
def test_aborted_run_tolerates_the_discarded_in_flight_evaluation(
    termination: str,
) -> None:
    # A time-bounded run stopped mid-evaluation: the 17 calls it had already
    # issued for the discarded candidate are real, but that candidate's rows
    # were never consumed. This must not fail the run.
    issue, warning = _code_call_accounting(
        code_calls=2735,
        fresh_prompt_rows=2718,
        termination_reason=termination,
        population_size=210,
    )
    assert issue is None
    assert warning == (
        "17 code-generation call(s) belong to the discarded in-flight evaluation"
    )


def test_aborted_run_with_no_surplus_is_silent() -> None:
    issue, warning = _code_call_accounting(
        code_calls=2718,
        fresh_prompt_rows=2718,
        termination_reason="wall_time_limit",
        population_size=210,
    )
    assert issue is None
    assert warning is None


def test_aborted_run_surplus_may_not_exceed_one_full_evaluation() -> None:
    # More than one population's worth of unexplained calls cannot come from a
    # single in-flight candidate — that is a genuine accounting defect.
    issue, warning = _code_call_accounting(
        code_calls=2718 + 211,
        fresh_prompt_rows=2718,
        termination_reason="wall_time_limit",
        population_size=210,
    )
    assert issue is not None
    assert "more than the discarded in-flight evaluation" in issue
    assert warning is None


def test_aborted_run_rejects_fewer_calls_than_consumed_rows() -> None:
    # Fewer calls than consumed fresh rows is impossible in either direction.
    issue, warning = _code_call_accounting(
        code_calls=2700,
        fresh_prompt_rows=2718,
        termination_reason="wall_time_limit",
        population_size=210,
    )
    assert issue is not None
    assert warning is None


def test_aborted_run_accepts_surplus_of_exactly_one_population() -> None:
    issue, warning = _code_call_accounting(
        code_calls=2718 + 210,
        fresh_prompt_rows=2718,
        termination_reason="wall_time_limit",
        population_size=210,
    )
    assert issue is None
    assert warning is not None
