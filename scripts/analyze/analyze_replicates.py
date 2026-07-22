#!/usr/bin/env python3
"""Analyse temp>0 replicate runs produced by ``baseline_harness.py``.

These runs are NOT search trajectories (no mutation/iteration sweep), so the
old EA-oriented trajectory analyzer does not apply. Instead this reports, per
condition, the mean +/- bootstrap-CI of each replicate-level metric across seeds,
and — when a baseline condition is present — the paired effect of the rules
(treatment minus baseline) reusing ``stats.py``.

Pools replicate records across one or more run dirs, so a wall-time-truncated run
and its seed top-up combine into one sample.

    python scripts/analyze/analyze_replicates.py <run_dir> [<run_dir2> ...] \
        [--baseline-ref <dir>] [--baseline-condition norules] [--out <dir>]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stats as S  # noqa: E402

METRICS = ("raw_findings", "vulnerable_cases", "weighted_fitness")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _fmt_p(p: float | None) -> str:
    """Compact p-value formatting; '—' when the test was not computable."""
    if p is None:
        return "—"
    return f"{p:.2g}" if p >= 1e-4 else f"{p:.1e}"


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _replicates_path(run_dir: Path) -> Path:
    new = run_dir / "replicates.jsonl"
    if new.exists():
        return new
    legacy = run_dir / "baseline_replicates.jsonl"
    return legacy if legacy.exists() else new


def read_replicates(run_dir: Path) -> list[dict]:
    """Replicate records from a run dir, each tagged with its source dir."""
    path = _replicates_path(run_dir)
    if not path.exists():
        return []
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            r["_run_dir"] = str(run_dir)
            recs.append(r)
    return recs


def pool(run_dirs: list[Path]) -> dict[str, list[dict]]:
    """Group deduped (condition, seed) records by condition across dirs."""
    seen: set[tuple] = set()
    by_cond: dict[str, list[dict]] = {}
    for d in run_dirs:
        for r in read_replicates(d):
            key = (r.get("condition"), r.get("seed"))
            if key in seen:
                continue
            seen.add(key)
            by_cond.setdefault(r.get("condition"), []).append(r) # type: ignore
    return by_cond


def per_prompt_raw(run_dir: Path, intermediate_file: str | None) -> dict[str, int]:
    if not intermediate_file:
        return {}
    path = run_dir / intermediate_file
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if "fitness" in r:
                out[str(r["test_case_id"])] = int(r["fitness"]["raw_count"])
    return out


def summarise(records: list[dict]) -> dict:
    recs = sorted(records, key=lambda r: r["seed"])
    out = {"n": len(recs), "seeds": [r["seed"] for r in recs]}
    for m in METRICS:
        vals = [float(r[m]) for r in recs]
        point, lo, hi = S.bootstrap_ci(vals) if vals else (float("nan"),) * 3
        out[m] = {"mean": point, "lo": lo, "hi": hi,
                  "min": min(vals) if vals else None, "max": max(vals) if vals else None}
    return out


def effect(treat: list[dict], base: list[dict]) -> dict:
    tb = {r["seed"]: r for r in treat}
    bb = {r["seed"]: r for r in base}
    common = sorted(set(tb) & set(bb))
    eff = {"common_seeds": common, "n": len(common), "metrics": {}}
    if not common:
        eff["note"] = "no common seeds"
        return eff
    for m in METRICS:
        bvals = [bb[s][m] for s in common]
        tvals = [tb[s][m] for s in common]
        deltas = [t - b for t, b in zip(tvals, bvals)]
        point, lo, hi = S.bootstrap_ci(deltas)
        st = S.sign_test(deltas)
        wil = S.wilcoxon_paired(bvals, tvals)   # replicate-level, magnitude-aware
        tt = S.ttest_paired(bvals, tvals)       # replicate-level parametric
        eff["metrics"][m] = {"delta_mean": point, "lo": lo, "hi": hi,
                             "ttest_p": tt.p, "wilcoxon_p": wil.p,
                             "sign_p": st.p, "note": st.note}
    # Per-prompt RQ1 tests on the lowest common seed.
    s0 = common[0]
    tdir = Path(tb[s0]["_run_dir"]); bdir = Path(bb[s0]["_run_dir"])
    tpp = per_prompt_raw(tdir, tb[s0].get("intermediate_file"))
    bpp = per_prompt_raw(bdir, bb[s0].get("intermediate_file"))
    if tpp and bpp:
        ids = sorted(set(tpp) & set(bpp))
        b = [bpp[i] for i in ids]; t = [tpp[i] for i in ids]
        eff["per_prompt_seed"] = s0
        eff["wilcoxon"] = str(S.wilcoxon_paired(b, t))
        eff["mcnemar"] = str(S.mcnemar_binary([x > 0 for x in b], [x > 0 for x in t]))
    else:
        eff["per_prompt_note"] = f"per-prompt tests skipped (no intermediate files for seed {s0})"
    return eff


def main() -> int:
    ap = argparse.ArgumentParser(description="Replicate-run analysis (mean±CI + effect of rules)")
    ap.add_argument("run_dirs", type=Path, nargs="+",
                    help="One or more replicate run dirs (pooled by condition).")
    ap.add_argument("--baseline-ref", type=Path, default=None,
                    help="Extra run dir whose --baseline-condition is the comparison baseline.")
    ap.add_argument("--baseline-condition", default="norules")
    ap.add_argument("--out", type=Path, default=None, help="Output dir (default: <first run_dir>/analysis)")
    args = ap.parse_args()

    by_cond = pool(args.run_dirs)
    base_recs: list[dict] = []
    if args.baseline_ref is not None:
        base_recs = [r for r in read_replicates(args.baseline_ref)
                     if r.get("condition") == args.baseline_condition]
    elif args.baseline_condition in by_cond:
        base_recs = by_cond[args.baseline_condition]

    out = args.out or (args.run_dirs[0] / "analysis")
    out.mkdir(parents=True, exist_ok=True)

    lines = [f"# Replicate analysis — {', '.join(d.name for d in args.run_dirs)}\n"]
    header = ["condition", "n", "metric", "mean", "95% CI", "min", "max"]
    rows: list[list] = []
    summaries = {}
    for cond, recs in sorted(by_cond.items()):
        s = summarise(recs); summaries[cond] = s
        for m in METRICS:
            d = s[m]
            rows.append([cond, s["n"], m, f"{d['mean']:.2f}",
                         f"[{d['lo']:.2f}, {d['hi']:.2f}]", d["min"], d["max"]])
    write_csv(out / "replicate_means.csv", header, rows)
    lines.append("## Per-condition replicate metrics")
    lines.append(md_table(header, rows))

    # Effect of rules vs baseline.
    base_label = args.baseline_condition
    eff_out = {}
    for cond, recs in sorted(by_cond.items()):
        if cond == base_label or not base_recs:
            continue
        eff = effect(recs, base_recs)
        eff_out[cond] = eff
        lines.append(f"\n## Effect: {cond} − {base_label} (paired, {eff['n']} common seeds)")
        if eff.get("note"):
            lines.append(f"_{eff['note']}_")
            continue
        eh = ["metric", "Δ mean", "95% CI", "paired-t p", "Wilcoxon p", "sign p"]
        erows = [[m, f"{eff['metrics'][m]['delta_mean']:+.2f}",
                  f"[{eff['metrics'][m]['lo']:+.2f}, {eff['metrics'][m]['hi']:+.2f}]",
                  _fmt_p(eff['metrics'][m]['ttest_p']),
                  _fmt_p(eff['metrics'][m]['wilcoxon_p']),
                  _fmt_p(eff['metrics'][m]['sign_p'])] for m in METRICS]
        lines.append(md_table(eh, erows))
        if "wilcoxon" in eff:
            lines.append(f"\nPer-prompt (seed {eff['per_prompt_seed']}): "
                         f"{eff['wilcoxon']}; {eff['mcnemar']}")
        elif eff.get("per_prompt_note"):
            lines.append(f"\n_{eff['per_prompt_note']}_")

    text = "\n".join(lines) + "\n"
    (out / "replicate_summary.md").write_text(text, encoding="utf-8")
    (out / "replicate_stats.json").write_text(
        json.dumps({"summaries": summaries, "effects": eff_out}, indent=2))
    print(text)
    print(f"\n📁 Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
