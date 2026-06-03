#!/usr/bin/env python3
"""
Post-hoc quality-validation audit (schema_version 2).

Validation is observational (soft gate) — every candidate is recorded but never
rejected. This script summarises the recorded ``validation_metadata`` so we can
defend the soft-gate choice in the Discussion:

  - per-criterion fail rate (instruction adherence, SBERT, perplexity,
    inline-code retention, keyword retention, overall passes_all)
  - per-mutator passes_all rate
  - "what if we'd gated" simulation: under full-gate (passes_all),
    partial-gate (security_intent_preserved), and no-gate — how many candidates
    each rejects, and the best f1 still reachable among accepted candidates.

Thresholds for the continuous criteria are NOT stored in the metadata (they are
run invariants); pass/fail uses the documented validator defaults, overridable
via flags. Only meaningful for runs launched with --enable-validation; otherwise
``validation_metadata`` is empty and the script says so.

Usage:
    python scripts/analyze/validation_audit.py <run_dir> [--out <dir>]
      [--sbert-threshold 0.75] [--perplexity-threshold 2.0] [--keyword-threshold 0.70]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loaders as L


def write_csv(path: Path, header, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)


def md_table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _criterion_fails(vm: dict, sbert_t: float, ppl_t: float, kw_t: float) -> dict[str, bool]:
    """Per-criterion fail flags from one validation_metadata dict.

    A criterion only counts when its value is present (None → not evaluated,
    e.g. perplexity when the gate was off)."""
    fails: dict[str, bool] = {}
    if "instruction_adherent" in vm and vm["instruction_adherent"] is not None:
        fails["instruction_adherent"] = (vm["instruction_adherent"] is False)
    if vm.get("sbert_step") is not None:
        fails["sbert_step"] = (vm["sbert_step"] < sbert_t)
    if vm.get("perplexity_ratio") is not None:
        fails["perplexity_ratio"] = (vm["perplexity_ratio"] > ppl_t)
    if vm.get("inline_code_retention") is not None:
        fails["inline_code_retention"] = (vm["inline_code_retention"] < 1.0)
    if vm.get("keyword_retention") is not None:
        fails["keyword_retention"] = (vm["keyword_retention"] < kw_t)
    if "passes_all" in vm and vm["passes_all"] is not None:
        fails["passes_all"] = (vm["passes_all"] is False)
    return fails


def audit(run: L.RunData, out: Path, sbert_t: float, ppl_t: float, kw_t: float) -> str:
    out.mkdir(parents=True, exist_ok=True)
    iters = [it for it in run.iterations if it.get("validation_metadata")]
    lines = [f"# Validation audit — {run.name}\n",
             f"thresholds: SBERT≥{sbert_t}, perplexity≤{ppl_t}, keyword≥{kw_t}\n"]

    if not iters:
        lines.append("**No validation_metadata recorded** — this run was launched "
                     "without `--enable-validation`. Re-run with the flag to populate "
                     "the observational quality criteria.")
        text = "\n".join(lines) + "\n"
        (out / "validation_audit.md").write_text(text, encoding="utf-8")
        return text

    # ---- per-criterion fail rate ----
    fail_counts: dict[str, int] = defaultdict(int)
    eval_counts: dict[str, int] = defaultdict(int)
    for it in iters:
        for crit, failed in _criterion_fails(it["validation_metadata"], sbert_t, ppl_t, kw_t).items():
            eval_counts[crit] += 1
            fail_counts[crit] += int(failed)
    lines.append(f"## Per-criterion fail rate (n={len(iters)} validated candidates)")
    crit_rows = []
    for crit in sorted(eval_counts):
        n = eval_counts[crit]; fr = fail_counts[crit] / n if n else 0.0
        crit_rows.append([crit, n, fail_counts[crit], f"{fr:.1%}"])
    write_csv(out / "validation_per_criterion.csv", ["criterion", "n", "fails", "fail_rate"], crit_rows)
    lines.append(md_table(["criterion", "n", "fails", "fail_rate"], crit_rows))

    # ---- per-mutator passes_all rate (last mutator in chain) ----
    per_mut_total: dict[str, int] = defaultdict(int)
    per_mut_pass: dict[str, int] = defaultdict(int)
    for it in iters:
        chain = it.get("mutation_chain") or []
        if not chain:
            continue
        m = chain[-1]
        vm = it["validation_metadata"]
        if vm.get("passes_all") is None:
            continue
        per_mut_total[m] += 1
        per_mut_pass[m] += int(vm["passes_all"] is True)
    lines.append("\n## Per-mutator passes_all rate (last mutator in chain)")
    mut_rows = [[m, per_mut_total[m], per_mut_pass[m],
                 f"{per_mut_pass[m]/per_mut_total[m]:.1%}" if per_mut_total[m] else "—"]
                for m in sorted(per_mut_total)]
    write_csv(out / "validation_per_mutator.csv", ["mutator", "n", "passes", "pass_rate"], mut_rows)
    lines.append(md_table(["mutator", "n", "passes", "pass_rate"], mut_rows) if mut_rows else "(no passes_all data)")

    # ---- what-if-gated ----
    lines.append("\n## What-if-gated simulation")
    def accepted_best(pred) -> tuple[int, float]:
        kept = [it for it in iters if pred(it["validation_metadata"])]
        f1s = [it["f1"] for it in kept if it.get("f1") is not None]
        return len(kept), (max(f1s) if f1s else 0.0)
    gates = {
        "no-gate (current)": lambda vm: True,
        "partial-gate (security_intent_preserved)": lambda vm: vm.get("security_intent_preserved") is not False,
        "full-gate (passes_all)": lambda vm: vm.get("passes_all") is not False,
    }
    g_rows = []
    n_total = len(iters)
    for name, pred in gates.items():
        kept, best = accepted_best(pred)
        g_rows.append([name, kept, n_total - kept, f"{best:+.2f}"])
    write_csv(out / "validation_what_if_gated.csv", ["gate", "accepted", "rejected", "best_f1_kept"], g_rows)
    lines.append(md_table(["gate", "accepted", "rejected", "best_f1_kept"], g_rows))

    # ---- figure ----
    if crit_rows:
        fig, ax = plt.subplots(figsize=(8, 4))
        names = [r[0] for r in crit_rows]
        rates = [fail_counts[c] / eval_counts[c] for c in names]
        ax.bar(range(len(names)), rates)
        ax.set_xticks(range(len(names))); ax.set_xticklabels([n.replace("_", "\n") for n in names], fontsize=8)
        ax.set_ylabel("fail rate"); ax.set_title(f"Per-criterion validation fail rate — {run.name}")
        p = out / "validation_per_criterion.png"
        fig.tight_layout(); fig.savefig(p, dpi=120); plt.close(fig)
        lines.append(f"\n![criteria]({p.name})")

    text = "\n".join(lines) + "\n"
    (out / "validation_audit.md").write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description="Post-hoc validation audit")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--sbert-threshold", type=float, default=0.75)  # matches MutationQualityValidator default
    ap.add_argument("--perplexity-threshold", type=float, default=2.0)
    ap.add_argument("--keyword-threshold", type=float, default=0.70)
    args = ap.parse_args()
    run = L.load_run(args.run_dir)
    out = args.out or (args.run_dir / "analysis")
    print(audit(run, out, args.sbert_threshold, args.perplexity_threshold, args.keyword_threshold))
    print(f"\n📁 Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
