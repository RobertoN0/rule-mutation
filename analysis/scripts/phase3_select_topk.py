#!/usr/bin/env python
"""Final Phase-3 chromosome selection: top-K candidates from K distinct seeds.

Why this replaces the old rule. The previous selection took ranks 1 and 2 from a
single run's archive. Those two turn out to be near-duplicates -- 9 to 11 of
their genes byte-identical, usually the same rule ordering -- so two jobs tested
essentially one candidate. Taking the best chromosome from each of the top-K seeds
instead yields genuinely different rule sets (pairwise gene-set Jaccard 0.25 to
0.52) at almost no cost in f1, which turns RQ4 from "did this one repair hold?"
into "how many of K distinct selected candidates retained their effect?".

Rule: pool every chromosome in every eligible EA run's FINAL archive snapshot,
rank by f1 desc, f2 desc, f3 desc, cid asc, then walk the ranking and keep a
chromosome only if its seed has not been used yet. Stop at K. Ties on f1 are
therefore broken toward higher textual similarity, and never toward a second chromosome
from a run already represented.

Read-only. Stdlib only.

    python3 phase3_select_topk.py [-k 5] [--models qwen,llama]
"""
from __future__ import annotations

import argparse
import glob
import json
import os

from common import OUT, gated_pairs, load_runs, write


def final_archive(run_dir: str) -> list[dict]:
    snaps = sorted(glob.glob(f"{run_dir}/archive_snapshots/evaluation_*.json"))
    if not snaps:
        return []
    return json.load(open(snaps[-1])).get("chromosomes", [])


def rank_key(c: dict):
    return (-float(c.get("f1", 0)), -float(c.get("f2", 0)),
            -float(c.get("f3", 0)), str(c.get("cid", "")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--models", default="qwen,llama")
    args = ap.parse_args()
    models = args.models.split(",")

    kept, excluded = gated_pairs(load_runs())
    out = {
        "artifact_type": "phase3_chromosome_selection_topk",
        "k": args.k,
        "selection_rule": (
            "pool all chromosomes from every eligible EA run's final archive; "
            "rank by f1 desc, f2 desc, f3 desc, cid asc; walk the ranking and "
            "keep a chromosome only if its seed is not already represented; "
            "stop at K. At most ONE chromosome per run."
        ),
        "f2_definition": (
            "mean SBERT textual similarity to the authored originals; the stored "
            "rule_fidelity field name does not establish semantic equivalence"
        ),
        "strata": {},
        "problems": [],
    }
    md = [
        f"# Phase 3 candidate selection - top {args.k} from {args.k} distinct seeds",
        "",
        out["selection_rule"],
        "",
        "`f2` is mean SBERT textual similarity to the authored originals; it does not",
        "establish semantic equivalence.",
        "",
    ]

    for stratum in sorted(kept):
        if stratum.split("_")[0] not in models:
            continue
        pool = []
        for seed, ea, rand in kept[stratum]:
            for c in final_archive(ea["dir"]):
                pool.append((seed, ea["dir"], c))
        pool.sort(key=lambda t: rank_key(t[2]))

        chosen, used_seeds = [], set()
        for seed, run_dir, c in pool:
            if seed in used_seeds:
                continue
            genes = {}
            ok = True
            for rid, g in (c.get("genes") or {}).items():
                p = os.path.join(run_dir, g["text_ref"])
                if not os.path.exists(p):
                    out["problems"].append(f"{stratum} s{seed} {c['cid']}: missing {p}")
                    ok = False
                genes[rid] = dict(g, text_abs=p, text_exists=os.path.exists(p))
            if not ok:
                continue
            # every gene of one chromosome must come from ONE evaluation dir,
            # which is what lets RULES_OVERRIDE_DIR point at a single folder
            dirs = {os.path.dirname(g["text_abs"]) for g in genes.values()}
            if len(dirs) != 1:
                out["problems"].append(
                    f"{stratum} s{seed} {c['cid']}: genes span {len(dirs)} dirs"
                )
                continue
            chosen.append(dict(
                rank=len(chosen) + 1,
                seed=seed,
                run_dir=run_dir,
                cid=c["cid"],
                f1=c["f1"], f2=c["f2"], f3=c["f3"],
                evaluation_index=c.get("evaluation_index"),
                order_priority={k: int(v) for k, v in (c.get("order_priority") or {}).items()},
                n_rules_mutated=len(genes),
                override_dir=dirs.pop(),
                genes=genes,
            ))
            used_seeds.add(seed)
            if len(chosen) == args.k:
                break

        out["strata"][stratum] = {"n_seeds_available": len(kept[stratum]), "selected": chosen}
        md += [f"## {stratum}", "",
               "| rank | seed | cid | f1 | f2 | rules | order-priority genes |",
               "|---:|---:|---|---:|---:|---:|---:|"]
        for c in chosen:
            md.append(
                f"| {c['rank']} | {c['seed']} | `{c['cid']}` | {c['f1']:.0f} | "
                f"{c['f2']:.4f} | {c['n_rules_mutated']} | {len(c['order_priority'])} |"
            )
        md.append("")

    write("phase3_selection_topk.json", json.dumps(out, indent=2))
    (OUT / "phase3_selection_topk.md").write_text("\n".join(md))
    print("\n".join(md))
    if out["problems"]:
        print("PROBLEMS:")
        for p in out["problems"]:
            print("  ", p)
    else:
        print("no problems; every gene resolves and each chromosome maps to one dir")


if __name__ == "__main__":
    main()
