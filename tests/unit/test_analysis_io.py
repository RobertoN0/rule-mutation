"""Unit tests for the analysis foundation: loaders.py + stats.py.

These guard the analysis layer against output-schema drift. They exercise only
the pure data-loading/derivation code and the scipy/numpy stat helpers — no
matplotlib (so they run without the [analysis] extra installed... except numpy,
which is a core dep).
"""

import json
import sys
from pathlib import Path

import pytest

_ANALYZE = Path(__file__).resolve().parents[2] / "scripts" / "analyze"
sys.path.insert(0, str(_ANALYZE))

import loaders as L  # noqa: E402
import stats as S    # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic run-dir fixture
# ---------------------------------------------------------------------------

def _write_run(tmp: Path, strategy: str, iters: list[dict],
               baseline: list[dict], summary: dict, args: dict) -> Path:
    (tmp / "intermediate").mkdir(parents=True, exist_ok=True)
    (tmp / "iterations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in iters) + "\n", encoding="utf-8")
    (tmp / "intermediate" / "baseline.jsonl").write_text(
        "\n".join(json.dumps(r) for r in baseline) + "\n", encoding="utf-8")
    (tmp / "run_config.json").write_text(json.dumps({"schema_version": 2, "args": args}))
    (tmp / "hillclimb_summary_x.json").write_text(json.dumps(summary))
    return tmp


def _iter(n, strategy, rule, chain, f1, advance):
    return {"iter": n, "strategy": strategy, "rule_id": rule, "mutation_chain": chain,
            "chain_length": len(chain), "mutation_identity": False, "f1": f1, "f2": 0.0,
            "f3": 0.0, "f1_advance": advance, "accepted": True, "validation_metadata": {},
            "selection_meta": {}}


def _prompt(tc, rule, count, lang="python"):
    return {"iter_id": "baseline", "index": 0, "test_case_id": tc, "language": lang,
            "cwe_id": "x", "rules_used": {"original_rule_ids": [rule], "target_rule_id": rule},
            "fitness": {"raw_count": count}, "generated_code": "x"}


# ---------------------------------------------------------------------------
# Robust JSONL
# ---------------------------------------------------------------------------

class TestReadJsonl:
    def test_reads_clean(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text('{"a":1}\n{"a":2}\n')
        assert [r["a"] for r in L.read_jsonl(p)] == [1, 2]

    def test_complete_last_line_without_newline(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text('{"a":1}\n{"a":2}\n{"a":3}')  # last line complete, just no trailing \n
        assert [r["a"] for r in L.read_jsonl(p)] == [1, 2, 3]

    def test_raw_decode_recovers_leading_object(self, tmp_path):
        p = tmp_path / "a.jsonl"
        # crash left a complete object followed by garbage on the final line
        p.write_text('{"a":1}\n{"a":2}{"a":3' )
        assert [r["a"] for r in L.read_jsonl(p)] == [1, 2]  # leading {"a":2} recovered

    def test_incomplete_last_object_is_dropped(self, tmp_path):
        p = tmp_path / "a.jsonl"
        p.write_text('{"a":1}\n{"a":2}\n{"a":3')  # truncated mid-object → unrecoverable
        assert [r["a"] for r in L.read_jsonl(p)] == [1, 2]

    def test_missing_file_is_empty(self, tmp_path):
        assert L.read_jsonl(tmp_path / "nope.jsonl") == []


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------

class TestDerivations:
    def test_ea_last_mutator_credit(self, tmp_path):
        iters = [
            _iter(1, "ea", "codeguard-0-r", ["m0"], 1.0, True),
            _iter(2, "ea", "codeguard-0-r", ["m0", "m1"], 0.0, False),
        ]
        run = L.load_run(_write_run(tmp_path, "ea", iters, [], {"pool_arm_stats": {"strategy": "ea"}}, {"optimizer": "ea"}))
        outc = L.per_mutator_outcomes(run)
        # EA credits only the LAST mutator of each chain.
        assert outc["m0"] == [1]      # iter1 chain=[m0] advancing
        assert outc["m1"] == [0]      # iter2 chain=[..,m1] not advancing; m0 NOT credited here
        assert L.best_f1(run) == 1.0
        assert L.iter_to_first_best(run) == 1

    def test_random_whole_chain_credit(self, tmp_path):
        iters = [_iter(1, "random_baseline", "codeguard-0-r", ["m0", "m1", "m2"], 2.0, True)]
        run = L.load_run(_write_run(tmp_path, "random_baseline", iters, [],
                                    {"pool_arm_stats": {"strategy": "random_baseline"}}, {"optimizer": "random_baseline"}))
        outc = L.per_mutator_outcomes(run)
        # Whole-chain: every mutator credited the iteration's advance flag.
        assert outc["m0"] == [1] and outc["m1"] == [1] and outc["m2"] == [1]

    def test_per_rule_best_and_baseline_findings(self, tmp_path):
        iters = [
            _iter(1, "ea", "codeguard-0-a", ["m0"], 1.0, True),
            _iter(2, "ea", "codeguard-0-a", ["m0", "m1"], 3.0, True),
            _iter(3, "ea", "codeguard-0-b", ["m0"], 2.0, True),
        ]
        baseline = [_prompt("10", "codeguard-0-a", 0), _prompt("11", "codeguard-0-b", 1)]
        run = L.load_run(_write_run(tmp_path, "ea", iters, baseline,
                                    {"pool_arm_stats": {"strategy": "ea"}}, {"optimizer": "ea"}))
        prb = L.per_rule_best(run)
        assert prb["codeguard-0-a"]["iter"] == 2 and prb["codeguard-0-a"]["f1"] == 3.0
        assert prb["codeguard-0-b"]["iter"] == 3
        assert L.baseline_findings(run) == {"10": 0, "11": 1}
        assert [y for _, y in L.convergence(run)] == [1.0, 3.0, 3.0]

    def test_strategy_detected_from_iterations(self, tmp_path):
        iters = [_iter(1, "random_baseline", "codeguard-0-r", ["m0"], 0.0, False)]
        run = L.load_run(_write_run(tmp_path, "random_baseline", iters, [], {}, {}))
        assert run.strategy == "random_baseline"
        assert run.iter_id(42) == "rand_iter0042"


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

class TestStats:
    def test_wilcoxon_no_change_is_none(self):
        r = S.wilcoxon_paired([0, 0, 0], [0, 0, 0])
        assert r.p is None and "no non-zero" in r.note

    def test_wilcoxon_change(self):
        r = S.wilcoxon_paired([0, 0, 0, 0], [1, 2, 3, 4])
        assert r.p is not None and r.n == 4

    def test_mcnemar_no_discordant(self):
        r = S.mcnemar_binary([True, True], [True, True])
        assert r.p is None

    def test_mcnemar_discordant(self):
        r = S.mcnemar_binary([False, False, False], [True, True, True])
        assert r.p is not None

    def test_sign_test_tie(self):
        assert S.sign_test([0, 0, 0]).p is None

    def test_sign_test(self):
        assert S.sign_test([1, 1, 1, -1]).p is not None

    def test_bootstrap_ci_bounds(self):
        pt, lo, hi = S.bootstrap_ci([0, 1, 0, 1, 1], seed=1)
        assert lo <= pt <= hi and 0.0 <= lo and hi <= 1.0

    def test_bootstrap_ci_singleton(self):
        assert S.bootstrap_ci([1]) == (1.0, 1.0, 1.0)

    def test_bootstrap_ci_empty(self):
        import math
        pt, lo, hi = S.bootstrap_ci([])
        assert math.isnan(pt)
