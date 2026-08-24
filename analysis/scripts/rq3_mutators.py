#!/usr/bin/env python
"""RQ3 - which text mutations and ordering moves are associated with gains?

Three levels of evidence, from cleanest/narrowest to broadest/most confounded.
All three are reported together so the reader can see whether they agree.

LEVEL 1 - clean one-move parent/child contrasts  (the anchor)
    EA main-loop moves with move_type=mutate, chain_length=1 and
    n_effective_changes=1 changed EXACTLY ONE rule by EXACTLY ONE operator
    relative to their parent. Whole-rule order moves are included as a ninth
    move family when exactly one priority change was effective. The fitness change
        delta = f1 - selection_meta.parent_f1
    is a direct local parent/child contrast for that move. Reported per family:
    sampling share, acceptance rate, mean/median delta, and P(delta > 0).
    Move-level quantities are descriptive because moves within a run are
    dependent; run-aggregated rates and deltas are the primary summaries.

LEVEL 2 - rule-instance marginal  (broader, mildly confounded)
    Every rule inside every evaluated chromosome carries its full cumulative
    operator history in mutated_rules/<eval>/meta.json -> gene_paths. For each
    rule instance we compute the mean per-task finding delta over the tasks that
    were actually shown that rule, relative to the run's own origin baseline,
    then group rule instances by "history contains operator M".
    Confounding: a rule with several stacked operators contributes to each of
    them. Level 3 quantifies how much that matters.

    NOTE ON ATTRIBUTION: Semgrep `check_ids` are DETECTOR ids, a different
    namespace from CodeGuard rule ids, so a finding cannot be traced to the
    CodeGuard rule that failed to prevent it. The attribution unit is therefore
    the TASK (which sees ~3 rules), never the finding.

LEVEL 3 - exploratory covariate adjustment
    (a) co-occurrence matrix: how often each operator pair appears in the same
        rule's history, so the reader can see which effects are entangled;
    (b) least-squares regression of per-task delta on operator-presence
        indicators, which estimates each operator's marginal contribution
        holding the others fixed.
    Exploratory, reported as such.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict
from pathlib import Path

from common import MUTATORS, OUT, gated_pairs, load_runs, write

POS = "delta > 0 means FEWER findings than the reference (an improvement)"
WHOLE_RULE_REORDER = "whole_rule_reorder"
MOVE_FAMILIES = tuple(MUTATORS) + (WHOLE_RULE_REORDER,)


def safe_zone_invalid_by_run():
    """Resolved run directory -> evaluation indices violating the contract."""
    audit = json.loads((OUT / "search_safe_zone_audit.json").read_text())
    return {
        str(Path(row["run_dir"]).resolve()): set(row["invalid_evaluation_indices"])
        for row in audit["runs"]
    }


# --------------------------------------------------------------------------- #
def solve(mat, vec):
    """Gaussian elimination with partial pivoting. Returns None if singular."""
    n = len(vec)
    a = [row[:] + [vec[i]] for i, row in enumerate(mat)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[piv][c]) < 1e-12:
            return None
        a[c], a[piv] = a[piv], a[c]
        for r in range(n):
            if r == c:
                continue
            f = a[r][c] / a[c][c]
            for k in range(c, n + 1):
                a[r][k] -= f * a[c][k]
    return [a[i][n] / a[i][i] for i in range(n)]


def ols(rows, y):
    """rows: list of indicator lists (no intercept). Returns coeffs incl. intercept."""
    if not rows:
        return None
    k = len(rows[0]) + 1
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for r, yi in zip(rows, y):
        x = [1.0] + list(r)
        for i in range(k):
            xty[i] += x[i] * yi
            for j in range(k):
                xtx[i][j] += x[i] * x[j]
    return solve(xtx, xty)


def summarise(vals):
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    pos = [v for v in s if v > 0]
    neg = [v for v in s if v < 0]

    def quantile(p):
        if n == 1:
            return s[0]
        position = (n - 1) * p
        lower = int(position)
        upper = min(lower + 1, n - 1)
        weight = position - lower
        return s[lower] * (1 - weight) + s[upper] * weight

    return dict(
        n=n,
        mean=sum(s) / n,
        median=med,
        minimum=s[0],
        q25=quantile(0.25),
        q75=quantile(0.75),
        maximum=s[-1],
        p_positive=len(pos) / n,
        p_zero=sum(1 for v in s if v == 0) / n,
        p_negative=len(neg) / n,
        mean_when_positive=sum(pos) / len(pos) if pos else 0.0,
        mean_when_negative=sum(neg) / len(neg) if neg else 0.0,
    )


def wilson(k, n, z=1.96):
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


# --------------------------------------------------------------------------- #
def level1(ea_dirs):
    """Clean one-move parent/child contrasts, including whole-rule order.

    CRITICAL DISTINCTION. Two different success signals are recorded, and they
    are NOT the same thing:

      * `accepted`    - the archive kept the child. The archive is MULTI-OBJECTIVE
                        (f1 reduction, f2 textual similarity, f3 parsimony), so a child can
                        be accepted on non-dominance while f1 gets WORSE.
      * actual delta  - ``f1 - parent_f1``; strictly positive means improvement.

    The stored ``f1_advance`` field is retained only as a discrepancy audit: in
    the search implementation it was conditioned on archive acceptance and is
    therefore not the requested P(delta > 0) outcome.
    """
    per_stratum = defaultdict(lambda: defaultdict(list))
    per_run = defaultdict(lambda: defaultdict(list))
    accepted = defaultdict(lambda: defaultdict(int))
    actual_positive = defaultdict(lambda: defaultdict(int))
    recorded_advanced = defaultdict(lambda: defaultdict(int))
    mismatches = defaultdict(lambda: defaultdict(int))
    sampled = defaultdict(lambda: defaultdict(int))
    total_moves = defaultdict(int)
    total_text_moves = defaultdict(int)
    excluded_invalid_child = defaultdict(int)
    excluded_invalid_parent = defaultdict(int)
    excluded_unknown_parent = defaultdict(int)
    invalid_by_run = safe_zone_invalid_by_run()

    for key, run_dir in ea_dirs:
        resolved_run = str(Path(run_dir).resolve())
        if resolved_run not in invalid_by_run:
            raise ValueError(f"safe-zone audit has no row for {resolved_run}")
        invalid_indices = invalid_by_run[resolved_run]
        records = list(_iter_evals(run_dir))
        chromosome_validity = defaultdict(set)
        for record in records:
            if record.get("f1") is None or not record.get("chromosome_id"):
                continue
            chromosome_validity[record["chromosome_id"]].add(
                int(record["evaluation_index"]) not in invalid_indices
            )

        for rec in records:
            move_type = rec.get("move_type")
            if move_type == "mutate":
                if rec.get("chain_length") != 1 or rec.get("n_effective_changes") != 1:
                    continue
                muts = rec.get("attempted_mutators") or []
                if len(muts) != 1:
                    continue
                family = muts[0]
                if family not in MUTATORS:
                    continue
            elif move_type == "order":
                if rec.get("n_effective_changes") != 1:
                    continue
                family = WHOLE_RULE_REORDER
            else:
                continue
            parent = (rec.get("selection_meta") or {}).get("parent_f1")
            if parent is None or rec.get("f1") is None:
                continue
            evaluation_index = int(rec["evaluation_index"])
            if evaluation_index in invalid_indices:
                excluded_invalid_child[key] += 1
                continue
            parent_id = rec.get("parent_chromosome_id")
            parent_states = chromosome_validity.get(parent_id, set())
            if parent_states == {False}:
                excluded_invalid_parent[key] += 1
                continue
            if parent_states != {True}:
                # An unseen parent with f1=0 is the structurally valid origin.
                if not parent_states and float(parent) == 0.0:
                    pass
                else:
                    excluded_unknown_parent[key] += 1
                    continue
            if family in MUTATORS:
                total_text_moves[key] += 1
            delta = float(rec["f1"]) - float(parent)
            per_stratum[key][family].append(delta)
            per_run[(key, run_dir)][family].append(delta)
            sampled[key][family] += 1
            total_moves[key] += 1
            if rec.get("accepted"):
                accepted[key][family] += 1
            if delta > 0:
                actual_positive[key][family] += 1
            if rec.get("f1_advance"):
                recorded_advanced[key][family] += 1
            if bool(rec.get("f1_advance")) != (delta > 0):
                mismatches[key][family] += 1

    out = {}
    for key in sorted(per_stratum):
        rows = {}
        tot = total_moves[key]
        tot_acc = sum(accepted[key].values())
        tot_positive = sum(actual_positive[key].values())
        for m in MOVE_FAMILIES:
            d = per_stratum[key].get(m, [])
            s = summarise(d)
            if s is None:
                continue
            n_acc = accepted[key][m]
            n_positive = actual_positive[key][m]
            n_recorded = recorded_advanced[key][m]
            n = s["n"]
            run_summaries = [
                summarise(families[m])
                for (run_key, _), families in per_run.items()
                if run_key == key and families.get(m)
            ]
            run_mean_delta = summarise([r["mean"] for r in run_summaries])
            run_positive_rate = summarise([r["p_positive"] for r in run_summaries])
            sampling_denominator = (
                total_text_moves[key] if m in MUTATORS else total_moves[key]
            )
            rows[m] = dict(
                **s,
                n_accepted=n_acc,
                n_positive_delta=n_positive,
                n_recorded_f1_advance=n_recorded,
                archive_acceptance_rate=n_acc / n,
                positive_delta_rate=n_positive / n,
                # Compatibility field for pre-existing figure consumers; this
                # is now recomputed from delta rather than read from the log.
                f1_advance_rate=n_positive / n,
                recorded_f1_advance_rate=n_recorded / n,
                stored_actual_mismatches=mismatches[key][m],
                sampling_share=(
                    sampled[key][m] / sampling_denominator
                    if sampling_denominator else 0.0
                ),
                sampling_share_scope=(
                    "text_moves" if m in MUTATORS else "all_clean_moves"
                ),
                acceptance_share=n_acc / tot_acc if tot_acc else 0.0,
                positive_delta_share=(
                    n_positive / tot_positive if tot_positive else 0.0
                ),
                n_runs=len(run_summaries),
                run_mean_delta=run_mean_delta,
                run_positive_rate=run_positive_rate,
            )
        out[key] = dict(
            total_clean_moves=tot,
            total_clean_text_moves=total_text_moves[key],
            safe_zone_excluded=dict(
                invalid_child=excluded_invalid_child[key],
                invalid_parent=excluded_invalid_parent[key],
                unknown_or_conflicting_parent=excluded_unknown_parent[key],
            ),
            total_accepted=tot_acc,
            total_positive_delta=tot_positive,
            move_families=rows,
            # Compatibility alias. Includes the whole-rule reorder family.
            operators=rows,
        )
    return out


def _iter_evals(run_dir):
    with open(f"{run_dir}/evaluations.jsonl") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# --------------------------------------------------------------------------- #
def level2_and_3(ea_dirs, max_evals=None):
    """Rule-instance marginal + co-occurrence + indicator regression."""
    rule_inst = defaultdict(lambda: defaultdict(list))   # stratum -> mutator -> deltas
    rule_inst_none = defaultdict(list)                    # stratum -> deltas (op absent)
    cooc = defaultdict(lambda: defaultdict(int))          # mutator -> mutator -> count
    solo = defaultdict(int)
    hist_len = defaultdict(int)
    reg_rows = defaultdict(list)
    reg_y = defaultdict(list)
    invalid_by_run = safe_zone_invalid_by_run()

    for key, run_dir in ea_dirs:
        resolved_run = str(Path(run_dir).resolve())
        if resolved_run not in invalid_by_run:
            raise ValueError(f"safe-zone audit has no row for {resolved_run}")
        invalid_indices = invalid_by_run[resolved_run]
        base_path = f"{run_dir}/intermediate/baseline.jsonl"
        if not os.path.exists(base_path):
            continue
        base = {}
        with open(base_path) as fh:
            for line in fh:
                r = json.loads(line)
                if (r.get("fitness") or {}).get("analysis_status") == "valid":
                    base[r["index"]] = r["fitness"]["raw_count"]
        files = sorted(glob.glob(f"{run_dir}/intermediate/evaluation_*.jsonl"))
        if max_evals:
            files = files[:max_evals]
        for f in files:
            ev = int(os.path.basename(f).split("_")[1].split(".")[0])
            if ev in invalid_indices:
                continue
            # load this evaluation's gene_paths on demand -- loading all 243
            # meta.json files up front costs ~8k small reads per run on BeeGFS
            meta = f"{run_dir}/mutated_rules/evaluation_{ev:04d}/meta.json"
            try:
                gp = (json.load(open(meta)).get("gene_paths")) or {}
            except (OSError, json.JSONDecodeError):
                continue
            if not gp:
                continue
            # per rule instance: collect the deltas of the tasks that saw it
            per_rule = defaultdict(list)
            with open(f) as fh:
                for line in fh:
                    r = json.loads(line)
                    fit = r.get("fitness") or {}
                    if fit.get("analysis_status") != "valid":
                        continue
                    idx = r.get("index")
                    if idx not in base:
                        continue
                    delta = base[idx] - fit["raw_count"]
                    ru = r.get("rules_used") or {}
                    shown = ru.get("original_rule_ids") or []
                    mutated_here = [rid for rid in shown if rid in gp]
                    if not mutated_here:
                        continue
                    present = set()
                    for rid in mutated_here:
                        per_rule[rid].append(delta)
                        present.update(gp[rid])
                    reg_rows[key].append([1 if m in present else 0 for m in MUTATORS])
                    reg_y[key].append(delta)

            for rid, deltas in per_rule.items():
                if not deltas:
                    continue
                mean_delta = sum(deltas) / len(deltas)
                path = gp.get(rid) or []
                uniq = sorted(set(path))
                hist_len[len(uniq)] += 1
                if len(uniq) == 1:
                    solo[uniq[0]] += 1
                for i, m in enumerate(uniq):
                    rule_inst[key][m].append(mean_delta)
                    for m2 in uniq[i + 1:]:
                        cooc[m][m2] += 1
                        cooc[m2][m] += 1
                for m in MUTATORS:
                    if m not in uniq:
                        rule_inst_none[(key, m)].append(mean_delta)

    lvl2 = {}
    for key in sorted(rule_inst):
        rows = {}
        for m in MUTATORS:
            with_m = summarise(rule_inst[key].get(m, []))
            without_m = summarise(rule_inst_none.get((key, m), []))
            if with_m is None:
                continue
            rows[m] = dict(
                with_operator=with_m,
                without_operator=without_m,
                contrast=(
                    with_m["mean"] - without_m["mean"] if without_m else None
                ),
            )
        lvl2[key] = rows

    lvl3 = dict(
        cooccurrence={m: dict(cooc[m]) for m in sorted(cooc)},
        solo_rule_instances=dict(solo),
        history_length_distribution=dict(sorted(hist_len.items())),
        regression={},
    )
    for key in sorted(reg_rows):
        coef = ols(reg_rows[key], reg_y[key])
        if coef is None:
            continue
        lvl3["regression"][key] = dict(
            n_observations=len(reg_y[key]),
            intercept=coef[0],
            coefficients={m: coef[i + 1] for i, m in enumerate(MUTATORS)},
        )
    return lvl2, lvl3


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-evals", type=int, default=None,
                    help="cap evaluations per run for a fast smoke pass")
    ap.add_argument("--skip-level23", action="store_true")
    ap.add_argument(
        "--reuse-level23",
        action="store_true",
        help="reuse existing Level 2/3 JSON while recomputing Level 1 and Markdown",
    )
    a = ap.parse_args()
    if a.skip_level23 and a.reuse_level23:
        ap.error("--skip-level23 and --reuse-level23 are mutually exclusive")

    strata = load_runs()
    kept, excluded = gated_pairs(strata)
    ea_dirs = [(key, e["dir"]) for key, pairs in kept.items() for _, e, _ in pairs]
    print(f"EA runs in scope: {len(ea_dirs)}")

    rep = {"excluded": excluded, "n_ea_runs": len(ea_dirs), "sign_convention": POS}
    rep["level1_single_operator"] = level1(ea_dirs)
    if a.reuse_level23:
        existing = json.loads((OUT / "rq3_mutators.json").read_text())
        for name in ("level2_rule_instance", "level3_deconfounding"):
            if name not in existing:
                raise SystemExit(f"existing rq3_mutators.json has no {name}")
            rep[name] = existing[name]
    elif not a.skip_level23:
        lvl2, lvl3 = level2_and_3(ea_dirs, a.max_evals)
        rep["level2_rule_instance"] = lvl2
        rep["level3_deconfounding"] = lvl3

    write("rq3_mutators.json", json.dumps(rep, indent=2))

    L = [
        "# RQ3 - which text mutations and ordering moves are associated with gains?",
        "",
        f"Sign convention: **{POS}**.",
        f"EA runs in scope: {rep['n_ea_runs']}.",
        "",
        "**These are associations, not causal effects.** Moves were selected by the",
        "search rather than randomised, and successive moves within a run are",
        "dependent, so a high positive-delta rate for an operator does not establish",
        "that the operator caused the reduction.",
        "",
        "## Level 1 - clean one-move parent/child contrasts (the anchor)",
        "",
        "Text moves changed one rule by one operator; whole-rule reorder moves changed",
        "one priority entry. Both the child and its archived parent passed the exact",
        "safe-zone contract. Move-level values are descriptive because successive moves",
        "within a run are dependent. Run-aggregated summaries are the primary evidence.",
        "",
    ]
    L += [
        "**Read the two success columns separately.** `positive delta` is computed",
        "directly as f1 > parent_f1. `archive accept` is",
        "multi-objective — the archive also rewards textual similarity (f2) and parsimony (f3),",
        "so a move can be kept while f1 gets worse. An operator with a high accept",
        "rate but a low advance rate is surviving on textual similarity, not on the finding-count effect.",
        "",
    ]
    for key in sorted(rep["level1_single_operator"]):
        blk = rep["level1_single_operator"][key]
        L += [
            f"### {key} — {blk['total_clean_moves']} clean moves, "
            f"{blk['total_positive_delta']} positive-delta, {blk['total_accepted']} archive-accepted",
            "",
            "Safe-zone exclusions (otherwise-clean moves): "
            f"{blk['safe_zone_excluded']['invalid_child']} invalid child, "
            f"{blk['safe_zone_excluded']['invalid_parent']} invalid parent, "
            f"{blk['safe_zone_excluded']['unknown_or_conflicting_parent']} unknown/conflicting parent.",
            "",
            "| move family | moves | runs | **P(Δ>0), moves** | median run P(Δ>0) | archive accept | mean Δf1 | median run mean Δf1 | stored/actual mismatches |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        ops = sorted(
            blk["operators"].items(),
            key=lambda kv: kv[1]["positive_delta_rate"],
            reverse=True,
        )
        for m, r in ops:
            run_pos = r["run_positive_rate"]
            run_delta = r["run_mean_delta"]
            L.append(
                f"| {m} | {r['n']} | {r['n_runs']} | **{r['positive_delta_rate']:.3f}** | "
                f"{run_pos['median']:.3f} | {r['archive_acceptance_rate']:.3f} | "
                f"{r['mean']:+.3f} | {run_delta['median']:+.3f} | "
                f"{r['stored_actual_mismatches']} |"
            )
        L.append("")

    L += [
        "The `whole_rule_reorder` row is the inter-rule priority operator. The",
        "`section_reorder_shuffle` and `section_reorder_degrade` rows are separate",
        "intra-rule section transformations. Their sampling shares have different",
        "denominators and are not interpreted as randomized treatment probabilities.",
        "",
    ]

    if "level2_rule_instance" in rep:
        L += [
            "## Level 2 - rule-instance marginal (all rules, any history length)",
            "",
            "Unit: one mutated rule inside one evaluated chromosome. Its value is the",
            "mean per-task finding delta over the tasks that were shown that rule,",
            "against the run's own origin baseline. Grouped by whether the rule's",
            "cumulative history contains the operator. Structurally invalid evaluated",
            "chromosomes are excluded. Repeated states/tasks and adaptive selection make",
            "this evidence descriptive and dependent, not an independent-sample test.",
            "",
        ]
        for key in sorted(rep["level2_rule_instance"]):
            L += [
                f"### {key}",
                "",
                "| operator | rule instances with | mean Δ with | mean Δ without | contrast | P(Δ>0) with |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            rows = sorted(
                rep["level2_rule_instance"][key].items(),
                key=lambda kv: kv[1]["contrast"] if kv[1]["contrast"] is not None else -9,
                reverse=True,
            )
            for m, r in rows:
                w = r["with_operator"]
                wo = r["without_operator"]
                L.append(
                    f"| {m} | {w['n']} | {w['mean']:+.4f} | "
                    f"{wo['mean']:+.4f} | {r['contrast']:+.4f} | {w['p_positive']:.3f} |"
                    if wo else
                    f"| {m} | {w['n']} | {w['mean']:+.4f} | n/a | n/a | {w['p_positive']:.3f} |"
                )
            L.append("")

    if "level3_deconfounding" in rep:
        l3 = rep["level3_deconfounding"]
        L += [
            "## Level 3 - exploratory covariate adjustment",
            "",
            "### Rule-history length (how much stacking actually happens)",
            "",
            "| distinct operators in a rule's history | rule instances |",
            "|---:|---:|",
        ]
        for k, v in l3["history_length_distribution"].items():
            L.append(f"| {k} | {v} |")
        L += [
            "",
            "A mass concentrated at 1 limits operator co-occurrence, but Level 2 remains",
            "dependent because states and tasks recur along adaptively selected runs.",
            "",
            "### Operator co-occurrence within a single rule's history",
            "",
            "| operator | " + " | ".join(m[:12] for m in MUTATORS) + " |",
            "|---|" + "---:|" * len(MUTATORS),
        ]
        for m in MUTATORS:
            cells = [str(l3["cooccurrence"].get(m, {}).get(m2, 0)) for m2 in MUTATORS]
            L.append(f"| {m} | " + " | ".join(cells) + " |")
        L += [
            "",
            "### Indicator regression (per-task delta on operator presence)",
            "",
            "Exploratory. Coefficient = marginal change in a task's finding delta when",
            "the task is shown at least one rule carrying that operator, holding the",
            "other operators fixed.",
            "",
        ]
        for key in sorted(l3["regression"]):
            r = l3["regression"][key]
            L += [
                f"#### {key} (n={r['n_observations']} task observations, "
                f"intercept {r['intercept']:+.4f})",
                "",
                "| operator | coefficient |",
                "|---|---:|",
            ]
            for m, c in sorted(r["coefficients"].items(), key=lambda kv: kv[1], reverse=True):
                L.append(f"| {m} | {c:+.4f} |")
            L.append("")

    write("rq3_mutators.md", "\n".join(L) + "\n")
    print("\n".join(L[:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
