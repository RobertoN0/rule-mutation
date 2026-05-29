#!/usr/bin/env python3
"""
Migrate a PRE-schema-2 run directory so the new analysis scripts can read it.

Old runs (before the bd-3wa / Phase-2 output redesign) have no iterations.jsonl,
no intermediate/, and no archive_snapshots/ — but their legacy
``intermediate_results/*.json`` files DO carry per-prompt ``raw_count`` +
``composite_score`` + ``code_divergence``, keyed by a ``phase`` string that
encodes the iteration and target rule. This script reconstructs, additively
(old files are left untouched):

    iterations.jsonl              one record per iteration (f1/f2/f3 derived from
                                  composite_score / code_divergence)
    intermediate/{iter_id}.jsonl  per-prompt records in the new shape

SCOPE / LOSSY — supports RQ1 (per-prompt baseline vs best) and RQ3 (best f1,
convergence, multi-seed, cost). It does NOT recover:
  - mutation_chain (old meta.json stores only descriptive change strings, no
    mutator names) → RQ2 per-mutator analysis is unavailable on migrated data.
  - archive_snapshots → EA archive-size hygiene is unavailable.
Records are written with mutation_chain=[] and a "migrated_from_schema_1" marker.

Only ea / random_baseline runs are supported (lex/D-UCB phases are skipped).

Usage:
    python scripts/analyze/migrate_legacy_run.py <old_run_dir> [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_ITER_RE = re.compile(r"^(ea|rand|mutation)_iter(\d+)", re.IGNORECASE)


def _new_intermediate_record(old: dict, iter_id: str) -> dict:
    """Reshape one legacy intermediate_results record into the new per-prompt shape."""
    return {
        "iter_id": iter_id,
        "index": old.get("index"),
        "test_case_id": old.get("test_case_id"),
        "language": old.get("language"),
        "cwe_id": old.get("cwe_id"),
        "rules_used": old.get("rules_used", {}),
        "fitness": old.get("fitness", {}),
        "generation_latency_ms": old.get("generation_latency_ms"),
        "analysis_latency_ms": old.get("analysis_latency_ms"),
        "input_tokens": old.get("input_tokens"),
        "output_tokens": old.get("output_tokens"),
        "eval_cache_hit": old.get("eval_cache_hit"),
        "llm_calls_so_far": old.get("llm_calls_so_far"),
        "input_tokens_so_far": old.get("input_tokens_so_far"),
        "output_tokens_so_far": old.get("output_tokens_so_far"),
        "generated_code": old.get("generated_code", ""),
    }


def _derive_iter_record(iter_num: int, strategy: str, records: list[dict]) -> dict:
    """Build one iterations.jsonl record from a phase's per-prompt records."""
    target = None
    affected = []
    for r in records:
        ru = r.get("rules_used", {}) or {}
        target = target or ru.get("target_rule_id")
        if ru.get("rule_was_applicable") or (target and target in (ru.get("original_rule_ids") or [])):
            affected.append(r)

    def comp(r):
        return (r.get("fitness", {}) or {}).get("composite_score") or 0.0

    def div(r):
        return (r.get("fitness", {}) or {}).get("code_divergence") or 0.0

    f1 = sum(comp(r) for r in records)            # total_semgrep_delta
    aff = affected or records
    divergent = [r for r in aff if div(r) > 0]
    f2 = len(divergent) / len(aff) if aff else 0.0
    f3 = (sum(div(r) for r in divergent) / len(divergent)) if divergent else 0.0

    last = records[-1]
    return {
        "iter": iter_num,
        "timestamp": last.get("timestamp"),
        "strategy": strategy,
        "rule_id": target,
        "mutation_chain": [],                      # NOT recoverable (lossy)
        "chain_length": 0,
        "mutation_identity": None,
        "validation_passed": True,
        "f1": round(f1, 6), "f2": round(f2, 6), "f3": round(f3, 6),
        "f1_advance": f1 > 0,
        "accepted": True,
        "num_prompts_affected": len(affected),
        "llm_calls_total": last.get("llm_calls_so_far"),
        "input_tokens_total": last.get("input_tokens_so_far"),
        "output_tokens_total": last.get("output_tokens_so_far"),
        "validation_metadata": {},
        "selection_meta": {},
        "migrated_from_schema_1": True,
    }


def migrate(old_dir: Path, out_dir: Path) -> dict:
    ir_dir = old_dir / "intermediate_results"
    if not ir_dir.is_dir():
        raise SystemExit(f"❌ {old_dir} has no intermediate_results/ — cannot migrate.")

    # Strategy from run_config, else from the dir name.
    rc = old_dir / "run_config.json"
    strategy = None
    if rc.exists():
        opt = (json.loads(rc.read_text()).get("args", {}) or {}).get("optimizer")
        strategy = {"ea": "ea", "random_baseline": "random_baseline"}.get(opt)

    by_phase: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(ir_dir.glob("*.json")):
        rec = json.loads(p.read_text())
        by_phase[rec.get("phase", "baseline")].append(rec)

    inter_out = out_dir / "intermediate"
    inter_out.mkdir(parents=True, exist_ok=True)
    iter_records: list[dict] = []
    skipped_phases: set[str] = set()

    for phase, recs in by_phase.items():
        recs.sort(key=lambda r: r.get("index", 0))
        if phase == "baseline":
            (inter_out / "baseline.jsonl").write_text(
                "\n".join(json.dumps(_new_intermediate_record(r, "baseline")) for r in recs) + "\n",
                encoding="utf-8")
            continue
        m = _ITER_RE.match(phase)
        if not m or m.group(1).lower() == "mutation":
            skipped_phases.add(phase)       # lex / unrecognised → skip
            continue
        prefix, n = m.group(1).lower(), int(m.group(2))
        strat = strategy or ("ea" if prefix == "ea" else "random_baseline")
        iter_id = f"{'ea' if strat == 'ea' else 'rand'}_iter{n:04d}"
        (inter_out / f"{iter_id}.jsonl").write_text(
            "\n".join(json.dumps(_new_intermediate_record(r, iter_id)) for r in recs) + "\n",
            encoding="utf-8")
        iter_records.append(_derive_iter_record(n, strat, recs))

    iter_records.sort(key=lambda r: r["iter"])
    (out_dir / "iterations.jsonl").write_text(
        "\n".join(json.dumps(r) for r in iter_records) + "\n", encoding="utf-8")

    # When writing to a separate dir, copy the provenance/summary files the
    # analysis scripts also read, so the migrated dir is self-contained.
    if out_dir.resolve() != old_dir.resolve():
        import shutil
        if rc.exists():
            shutil.copy2(rc, out_dir / "run_config.json")
        for s in old_dir.glob("hillclimb_summary_*.json"):
            shutil.copy2(s, out_dir / s.name)

    return {"iterations": len(iter_records), "phases": len(by_phase),
            "skipped_phases": sorted(skipped_phases)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate a pre-schema-2 run for the new analysis scripts")
    ap.add_argument("old_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="Where to write iterations.jsonl + intermediate/ (default: in place, additive)")
    args = ap.parse_args()
    out = args.out or args.old_dir
    info = migrate(args.old_dir, out)
    print(f"✅ migrated {args.old_dir} → {out}")
    print(f"   iterations: {info['iterations']}  (from {info['phases']} phases)")
    if info["skipped_phases"]:
        print(f"   ⚠️ skipped {len(info['skipped_phases'])} non-ea/rand phases (lex/unrecognised)")
    print("   NOTE: RQ2 (mutation_chain) + archive hygiene are NOT available on migrated data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
