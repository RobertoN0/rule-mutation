#!/usr/bin/env python3
"""Per-prompt baseline analysis over the bl40 replicate cells.

For a (model, language) pair, reads the 40 norules + 40 withrules per-prompt
intermediate records (keyed by stable test_case_id) and builds a per-prompt
profile of semgrep findings across the replicates. Classifies each prompt into:

  - NEVER vulnerable  : 0 findings in every rep of BOTH conditions
                        -> nothing to optimize (rules irrelevant; model never fails)
  - PERSISTENT (rules don't help) : vulnerable in (nearly) all withrules reps
                        -> the real optimization targets
  - RULE-FIXED        : frequently vulnerable no-rules, rarely with-rules
                        -> rules already work here
  - VARIABLE          : finding count varies across reps (sampling/rule sensitive)

Writes a per-prompt CSV (the "common baseline") + prints summary tables.
Pure file IO + arithmetic, safe on a login node.
"""
import argparse, glob, json, os, statistics
from collections import defaultdict

RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "experiments", "results")
RESULTS = os.path.abspath(RESULTS)


def load_cell(model, lang, cond):
    """test_case_id -> {'cwe':..., 'counts':[raw_count per seed]}"""
    d = os.path.join(RESULTS, f"bl40_{model}_{lang}_{cond}", "intermediate")
    files = sorted(glob.glob(os.path.join(d, f"{cond}_seed*.jsonl")))
    by_id = defaultdict(lambda: {"cwe": None, "counts": [], "checks": defaultdict(int)})
    for fp in files:
        with open(fp) as fh:
            for line in fh:
                if not line.strip():
                    continue
                o = json.loads(line)
                tid = str(o["test_case_id"])
                rc = int(o.get("fitness", {}).get("raw_count", 0) or 0)
                rec = by_id[tid]
                rec["cwe"] = o.get("cwe_id")
                rec["counts"].append(rc)
                for cid in o.get("fitness", {}).get("check_ids", []) or []:
                    rec["checks"][cid] += 1
    return by_id, len(files)


def frac(xs, pred):
    return sum(1 for x in xs if pred(x)) / len(xs) if xs else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen")
    ap.add_argument("--language", default="python")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    nr, n_nr = load_cell(args.model, args.language, "norules")
    wr, n_wr = load_cell(args.model, args.language, "withrules")
    ids = sorted(set(nr) | set(wr), key=lambda x: int(x) if x.isdigit() else x)
    print(f"# {args.model} / {args.language}: {len(ids)} prompts, "
          f"norules={n_nr} seeds, withrules={n_wr} seeds")

    rows = []
    for tid in ids:
        nc = nr.get(tid, {}).get("counts", [])
        wc = wr.get(tid, {}).get("counts", [])
        cwe = (nr.get(tid) or wr.get(tid)).get("cwe")
        nr_rate = frac(nc, lambda x: x > 0)   # P(vulnerable) no-rules
        wr_rate = frac(wc, lambda x: x > 0)   # P(vulnerable) with-rules
        nr_mean = statistics.mean(nc) if nc else 0.0
        wr_mean = statistics.mean(wc) if wc else 0.0
        nr_distinct = len(set(nc))
        wr_distinct = len(set(wc))
        nr_max = max(nc) if nc else 0
        wr_max = max(wc) if wc else 0
        rows.append(dict(
            tid=tid, cwe=cwe,
            nr_rate=nr_rate, wr_rate=wr_rate, nr_mean=nr_mean, wr_mean=wr_mean,
            nr_distinct=nr_distinct, wr_distinct=wr_distinct,
            nr_max=nr_max, wr_max=wr_max,
            delta_mean=wr_mean - nr_mean, delta_rate=wr_rate - nr_rate,
        ))

    # ---- classification ----
    def cls(r):
        if r["nr_max"] == 0 and r["wr_max"] == 0:
            return "NEVER"
        # persistent under rules = vulnerable in >=80% of withrules reps
        if r["wr_rate"] >= 0.8:
            return "PERSISTENT"
        # rule-fixed = was failing a lot no-rules, now rarely with-rules
        if r["nr_rate"] >= 0.5 and r["wr_rate"] <= 0.2:
            return "RULE_FIXED"
        return "VARIABLE"

    for r in rows:
        r["class"] = cls(r)

    buckets = defaultdict(list)
    for r in rows:
        buckets[r["class"]].append(r)

    print(f"\n## Classification ({len(rows)} prompts)")
    for k in ["NEVER", "PERSISTENT", "RULE_FIXED", "VARIABLE"]:
        b = buckets[k]
        print(f"  {k:11s} {len(b):4d}  ({100*len(b)/len(rows):4.1f}%)")

    # variance set (count varies in either condition)
    variable_any = [r for r in rows if r["nr_distinct"] > 1 or r["wr_distinct"] > 1]
    print(f"\n  finding-count VARIES across reps (either cond): {len(variable_any)} "
          f"({100*len(variable_any)/len(rows):.1f}%)")

    # per-CWE breakdown of PERSISTENT (the optimization targets)
    print("\n## PERSISTENT (vulnerable in >=80% of with-rules reps) by CWE")
    bycwe = defaultdict(lambda: [0, 0])  # cwe -> [persistent, total]
    for r in rows:
        bycwe[r["cwe"]][1] += 1
        if r["class"] == "PERSISTENT":
            bycwe[r["cwe"]][0] += 1
    for cwe, (p, t) in sorted(bycwe.items(), key=lambda kv: -kv[1][0]):
        if p:
            print(f"  {str(cwe):12s} {p:3d}/{t:3d} persistent")

    # rules helping vs hurting (paired per-prompt mean delta)
    helped = [r for r in rows if r["delta_mean"] < -1e-9]
    hurt = [r for r in rows if r["delta_mean"] > 1e-9]
    same = [r for r in rows if abs(r["delta_mean"]) <= 1e-9]
    print(f"\n## Rule effect per prompt (with-rules mean - no-rules mean)")
    print(f"  rules REDUCE findings: {len(helped):4d}   "
          f"rules INCREASE: {len(hurt):4d}   no change: {len(same):4d}")
    if helped:
        top = sorted(helped, key=lambda r: r["delta_mean"])[:10]
        print("  biggest reductions (tid cwe  nr_mean->wr_mean):")
        for r in top:
            print(f"    {r['tid']:>6} {str(r['cwe']):10s} {r['nr_mean']:.2f} -> {r['wr_mean']:.2f}")
    if hurt:
        top = sorted(hurt, key=lambda r: -r["delta_mean"])[:10]
        print("  biggest INCREASES (rules made it worse):")
        for r in top:
            print(f"    {r['tid']:>6} {str(r['cwe']):10s} {r['nr_mean']:.2f} -> {r['wr_mean']:.2f}")

    # ---- write CSV ----
    out = args.out or os.path.join(RESULTS, f"baseline_per_prompt_{args.model}_{args.language}.csv")
    cols = ["tid", "cwe", "class", "nr_rate", "wr_rate", "nr_mean", "wr_mean",
            "delta_mean", "delta_rate", "nr_distinct", "wr_distinct", "nr_max", "wr_max"]
    with open(out, "w") as fh:
        fh.write(",".join(cols) + "\n")
        for r in sorted(rows, key=lambda r: (r["class"], -r["wr_mean"])):
            fh.write(",".join(f"{r[c]:.4f}" if isinstance(r[c], float) else str(r[c]) for c in cols) + "\n")
    print(f"\nWrote per-prompt baseline -> {out}")


if __name__ == "__main__":
    main()
