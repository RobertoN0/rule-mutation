#!/usr/bin/env python3
"""Analyse temperature>0 runs produced by ``run_replicates.py``.

These runs are not search trajectories. This reports, per
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analyze import stats as S  # noqa: E402
from scripts.analyze.validate_replicate_run import validate_replicate_run  # noqa: E402

METRICS = (
    "raw_findings_per_valid_prompt",
    "vulnerable_rate_valid",
    "weighted_score_per_valid_prompt",
    "invalid_outputs",
)

COMPARISON_CONTRACT_FIELDS = (
    "model",
    "model_revision",
    "torch_version",
    "transformers_version",
    "quantization",
    "bnb_compute_dtype",
    "languages",
    "temperature",
    "prompt_profile",
    "prompt_contract_sha256",
    "n_cases",
    "selection",
    "evaluated_population_fingerprint",
    "population_policy",
    "full_frozen_population",
    "max_output_tokens",
    "invalid_output_policy",
    "semgrep_version",
    "semgrep_rules_source_commit",
    "semgrep_rules_sha256",
    "semgrep_timeout_seconds",
)


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


def read_replicates(run_dir: Path) -> list[dict]:
    """Replicate records from a run dir, each tagged with its source dir."""
    path = run_dir / "replicates.jsonl"
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
    """Group records by condition; duplicate condition/seed evidence is ambiguous."""
    seen: dict[tuple, str] = {}
    by_cond: dict[str, list[dict]] = {}
    for d in run_dirs:
        for r in read_replicates(d):
            key = (r.get("condition"), r.get("seed"))
            if key in seen:
                raise ValueError(
                    f"duplicate condition/seed {key} in {seen[key]} and {d}"
                )
            seen[key] = str(d)
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
            if (
                isinstance(r.get("fitness"), dict)
                and r.get("qualification_status", "valid") == "valid"
            ):
                out[str(r["test_case_id"])] = int(r["fitness"]["raw_count"])
    return out


def _assert_comparable(run_dirs: list[Path]) -> None:
    contracts = []
    for run_dir in run_dirs:
        config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
        args = config.get("args", {})
        contract = {field: args.get(field) for field in COMPARISON_CONTRACT_FIELDS}
        contract["git_commit_sha"] = config.get("git_commit_sha")
        contracts.append((run_dir, contract))
    if not contracts:
        return
    reference_dir, reference = contracts[0]
    for run_dir, contract in contracts[1:]:
        mismatches = {
            field: (reference.get(field), contract.get(field))
            for field in reference
            if reference.get(field) != contract.get(field)
        }
        if mismatches:
            raise ValueError(
                f"incompatible replicate contracts in {reference_dir} and {run_dir}: "
                f"{mismatches}"
            )


def summarise(records: list[dict]) -> dict:
    recs = sorted(records, key=lambda r: r["seed"])
    out = {"n": len(recs), "seeds": [r["seed"] for r in recs]}
    for m in METRICS:
        available = [r for r in recs if r.get(m) is not None]
        vals = [float(r[m]) for r in available]
        point, lo, hi = S.bootstrap_ci(vals) if vals else (float("nan"),) * 3
        out[m] = {
            "n": len(vals),
            "mean": point,
            "lo": lo,
            "hi": hi,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        }
    out["observed_raw_findings"] = {
        "per_seed": {
            r["seed"]: {
                "raw_findings": r.get("raw_findings"),
                "valid_outputs": r.get("n_valid_outputs"),
                "total_outputs": r.get("n_cases"),
                "scope": r.get("raw_findings_scope"),
            }
            for r in recs
        }
    }
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
        metric_seeds = [
            seed
            for seed in common
            if tb[seed].get(m) is not None and bb[seed].get(m) is not None
        ]
        bvals = [bb[s][m] for s in metric_seeds]
        tvals = [tb[s][m] for s in metric_seeds]
        if not metric_seeds:
            eff["metrics"][m] = {"n": 0, "note": "no paired non-missing values"}
            continue
        deltas = [t - b for t, b in zip(tvals, bvals)]
        point, lo, hi = S.bootstrap_ci(deltas)
        st = S.sign_test(deltas)
        wil = S.wilcoxon_paired(bvals, tvals)   # replicate-level, magnitude-aware
        tt = S.ttest_paired(bvals, tvals)       # replicate-level parametric
        eff["metrics"][m] = {
            "n": len(metric_seeds),
            "paired_seeds": metric_seeds,
            "delta_mean": point,
            "lo": lo,
            "hi": hi,
            "ttest_p": tt.p,
            "wilcoxon_p": wil.p,
            "sign_p": st.p,
            "note": st.note,
        }

    paired_seed_rows = []
    for seed in common:
        tdir = Path(tb[seed]["_run_dir"])
        bdir = Path(bb[seed]["_run_dir"])
        tpp = per_prompt_raw(tdir, tb[seed].get("intermediate_file"))
        bpp = per_prompt_raw(bdir, bb[seed].get("intermediate_file"))
        ids = sorted(set(tpp) & set(bpp))
        if not ids:
            continue
        raw_delta = sum(tpp[task_id] - bpp[task_id] for task_id in ids) / len(ids)
        vulnerable_delta = sum(
            int(tpp[task_id] > 0) - int(bpp[task_id] > 0) for task_id in ids
        ) / len(ids)
        paired_seed_rows.append(
            {
                "seed": seed,
                "paired_valid_prompts": len(ids),
                "raw_findings_per_prompt_delta": raw_delta,
                "has_finding_rate_delta": vulnerable_delta,
            }
        )
    paired_effect: dict = {
        "analysis_unit": "seed",
        "within_seed_policy": "intersection_of_prompts_valid_in_both_conditions",
        "n_seeds": len(paired_seed_rows),
        "total_prompt_pairs_descriptive": sum(
            row["paired_valid_prompts"] for row in paired_seed_rows
        ),
        "per_seed": paired_seed_rows,
        "note": "Repeated task rows are not pooled as independent observations.",
    }
    for metric in ("raw_findings_per_prompt_delta", "has_finding_rate_delta"):
        deltas = [row[metric] for row in paired_seed_rows]
        if not deltas:
            paired_effect[metric] = {"note": "no paired-valid seed effects"}
            continue
        point, lo, hi = S.bootstrap_ci(deltas)
        sign = S.sign_test(deltas)
        paired_effect[metric] = {
            "delta_mean": point,
            "lo": lo,
            "hi": hi,
            "sign_p": sign.p,
            "sign_note": sign.note,
        }
    eff["paired_valid_prompt_effect"] = paired_effect
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

    validation_dirs = [*args.run_dirs]
    if args.baseline_ref is not None:
        validation_dirs.append(args.baseline_ref)
    invalid = [
        result
        for result in map(validate_replicate_run, validation_dirs)
        if result["status"] != "VALID"
    ]
    if invalid:
        for result in invalid:
            print(json.dumps(result, indent=2), file=sys.stderr)
        raise SystemExit("Refusing to analyze invalid replicate-run artifacts")
    _assert_comparable(validation_dirs)

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
    header = ["condition", "n available", "metric", "mean", "95% CI", "min", "max"]
    rows: list[list] = []
    summaries = {}
    for cond, recs in sorted(by_cond.items()):
        s = summarise(recs)
        summaries[cond] = s
        for m in METRICS:
            d = s[m]
            rows.append([cond, d["n"], m, f"{d['mean']:.3f}",
                         f"[{d['lo']:.2f}, {d['hi']:.2f}]", d["min"], d["max"]])
    write_csv(out / "replicate_means.csv", header, rows)
    lines.append("## Per-condition replicate metrics")
    lines.append(md_table(header, rows))

    observed_header = [
        "condition",
        "seed",
        "observed raw findings",
        "valid / total prompts",
        "scope",
    ]
    observed_rows = [
        [
            condition,
            record["seed"],
            record.get("raw_findings"),
            f"{record.get('n_valid_outputs')} / {record.get('n_cases')}",
            record.get("raw_findings_scope"),
        ]
        for condition, records in sorted(by_cond.items())
        for record in sorted(records, key=lambda row: row["seed"])
    ]
    write_csv(out / "observed_raw_findings.csv", observed_header, observed_rows)
    lines.append("\n## Observed raw vulnerability counts and denominators")
    lines.append(
        "Raw counts are primary but are not compared as full-population totals when "
        "a replicate has invalid outputs."
    )
    lines.append(md_table(observed_header, observed_rows))

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
        erows = []
        for m in METRICS:
            metric = eff["metrics"][m]
            if metric.get("n", 0) == 0:
                erows.append([m, "—", "—", "—", "—", "—"])
                continue
            erows.append([
                m,
                f"{metric['delta_mean']:+.3f}",
                f"[{metric['lo']:+.3f}, {metric['hi']:+.3f}]",
                _fmt_p(metric["ttest_p"]),
                _fmt_p(metric["wilcoxon_p"]),
                _fmt_p(metric["sign_p"]),
            ])
        lines.append(md_table(eh, erows))
        paired = eff["paired_valid_prompt_effect"]
        lines.append(
            "\nPaired-valid prompt effect uses seed as the analysis unit: "
            f"{paired['n_seeds']} seeds, "
            f"{paired['total_prompt_pairs_descriptive']} prompt pairs descriptively."
        )

    text = "\n".join(lines) + "\n"
    (out / "replicate_summary.md").write_text(text, encoding="utf-8")
    (out / "replicate_analysis.json").write_text(
        json.dumps(
            {
                "artifact_type": "replicate_analysis",
                "summaries": summaries,
                "effects": eff_out,
            },
            indent=2,
        )
    )
    print(text)
    print(f"\n📁 Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
