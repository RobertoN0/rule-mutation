"""Unit tests for the statistical helpers used by active analyzers."""

from __future__ import annotations

import math

from scripts.analyze import stats


class TestStats:
    def test_wilcoxon_no_change_is_none(self):
        result = stats.wilcoxon_paired([0, 0, 0], [0, 0, 0])
        assert result.p is None and "no non-zero" in result.note

    def test_wilcoxon_change(self):
        result = stats.wilcoxon_paired([0, 0, 0, 0], [1, 2, 3, 4])
        assert result.p is not None and result.n == 4

    def test_mcnemar_no_discordant(self):
        assert stats.mcnemar_binary([True, True], [True, True]).p is None

    def test_mcnemar_discordant(self):
        result = stats.mcnemar_binary(
            [False, False, False],
            [True, True, True],
        )
        assert result.p is not None

    def test_sign_test_tie(self):
        assert stats.sign_test([0, 0, 0]).p is None

    def test_sign_test(self):
        assert stats.sign_test([1, 1, 1, -1]).p is not None

    def test_bootstrap_ci_bounds(self):
        point, low, high = stats.bootstrap_ci([0, 1, 0, 1, 1], seed=1)
        assert low <= point <= high
        assert 0.0 <= low and high <= 1.0

    def test_bootstrap_ci_singleton(self):
        assert stats.bootstrap_ci([1]) == (1.0, 1.0, 1.0)

    def test_bootstrap_ci_empty(self):
        point, low, high = stats.bootstrap_ci([])
        assert math.isnan(point)
        assert math.isnan(low)
        assert math.isnan(high)
