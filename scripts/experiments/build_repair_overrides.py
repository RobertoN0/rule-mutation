#!/usr/bin/env python3
"""
Stage-2 helper: assemble the best discovered repair mutation per rule into an
override dir for ``baseline_harness.py --rules-override-dir`` (temp>0 validation).

For each rule, pick the iteration with the highest fitness (safest, largest
vulnerability reduction) ACROSS the given EA runs, keep only rules whose best
fitness > 0 (a genuine repair), and copy that iteration's mutated ``cg-*.md`` into
the output dir. Also reports the union of affected prompts (what
``--only-overridden-prompts`` will run) so runtime can be estimated.

Usage:
    python scripts/experiments/build_repair_overrides.py \
        experiments/final/job*_ea_qwen32b_py_s* --out experiments/final/overrides/python
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analyze"))

import loaders as L  # noqa: E402
import records as R  # noqa: E402


def _mutated_dir_for_iter(run: L.RunData, iter_num: int) -> Path | None:
    base = run.run_dir / "mutated_rules"
    for cand in (f"iter{iter_num:03d}", f"iter{iter_num}", f"iter{iter_num:04d}"):
        if (base / cand).is_dir():
            return base / cand
    # fall back: match by numeric suffix
    for d in base.glob("iter*"):
        digits = "".join(ch for ch in d.name if ch.isdigit())
        if digits and int(digits) == iter_num:
            return d
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path, help="EA run dirs (one language)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-fitness", type=float, default=0.0001,
                    help="keep only rules whose best fitness exceeds this (genuine repair)")
    args = ap.parse_args()

    runs = L.discover_runs(args.paths)
    if not runs:
        print("No runs found.", file=sys.stderr)
        return 1

    # per rule_id -> (best_f1, run, iter_num)
    best: dict[str, tuple[float, L.RunData, int]] = {}
    for run in runs:
        for it in L.valid_iters(run):
            rid = str(it.get("rule_id") or "")
            f1 = float(it.get("f1") or 0.0)
            if not rid:
                continue
            if rid not in best or f1 > best[rid][0]:
                best[rid] = (f1, run, int(it["iter"]))

    repairs = {rid: v for rid, v in best.items() if v[0] > args.min_fitness}
    args.out.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for rid, (f1, run, itn) in sorted(repairs.items(), key=lambda kv: -kv[1][0]):
        mdir = _mutated_dir_for_iter(run, itn)
        if mdir is None:
            print(f"  ⚠️  no mutated_rules dir for {rid} iter{itn} in {run.run_dir.name}")
            continue
        mds = list(mdir.glob("cg-*.md"))
        if not mds:
            print(f"  ⚠️  no cg-*.md in {mdir}")
            continue
        for src in mds:
            shutil.copy2(src, args.out / src.name)
            copied.append(f"{src.stem}  (fitness +{f1:.1f}, {run.run_dir.name} iter{itn})")

    # union of affected prompts under these rules (what --only-overridden runs)
    included = set(repairs)
    any_run = runs[0]
    affected = sum(
        1 for rec in any_run.baseline()
        if set(R.original_rule_ids(rec)) & included
    )
    total = sum(1 for _ in any_run.baseline())

    print(f"\nWrote {len(copied)} override rule file(s) to {args.out}:")
    for c in copied:
        print(f"  - {c}")
    print(f"\nRules with a genuine repair (fitness>0): {len(repairs)} of {len(best)} mutated")
    print(f"Affected prompts (--only-overridden-prompts will run): {affected} / {total}")
    print(f"Est. generations at 20 replicates: {affected * 20}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
