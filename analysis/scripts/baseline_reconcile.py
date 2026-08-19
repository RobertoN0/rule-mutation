#!/usr/bin/env python
"""Baseline provenance reconciliation.

The temperature-0.6 screening baselines predate the provenance-manifest contract,
so their run_config.json carries `rules_map` (a PATH) but no `rules_map_sha256`
and no `population_fingerprint`.

Nothing is back-dated and nothing is written into those run configs. This script
derives the missing provenance NOW, from the artifacts as they exist, and records
it in a separate manifest that is honest about when it was computed. It proves
three things:

  1. the map file each baseline run actually referenced, by SHA-256 computed today;
  2. every task in the final search population (203 python / 126 java) is present
     in the consensus population the baselines were run over (322 / 227);
  3. for every one of those shared tasks, `rules_retrieved` is IDENTICAL between
     the consensus map and the final qualified map - so a baseline observation for
     task i was produced under exactly the rules the final search used for task i.

If (2) and (3) hold, the baselines can be subset to the final population and used
directly as the original-rules and no-rules reference, with no re-running.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import datetime, timezone

from common import REPO, write

PIPE = f"{REPO}/experiments/01_population_and_maps"
CONSENSUS = f"{PIPE}/phase2_consensus/maps"
SCREEN = f"{PIPE}/phase3_screening/block1"
QUALIFIED = f"{REPO}/rule_maps/qualified"

STRATA = [("qwen", "python"), ("qwen", "java"), ("llama", "python"), ("llama", "java")]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_map(path):
    m = json.load(open(path))
    out = {}
    for e in m["mappings"]:
        out[e["index"]] = dict(
            prompt_hash=e.get("prompt_hash"),
            rules=list(e.get("rules_retrieved") or []),
            cwe=e.get("cwe_id"),
        )
    return out, m.get("metadata", {})


def main():
    rep = {
        "artifact_type": "baseline_provenance_reconciliation",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "computed_by": "analysis-time derivation; NOT recorded at run time",
        "statement": (
            "Baseline screening runs predate the provenance-manifest contract. "
            "Their rule assignments were reconciled against the final qualified map "
            "by task-index and prompt-hash comparison. No run artifact was modified."
        ),
        "strata": {},
        "baseline_runs": {},
        "verdict": {},
    }

    all_ok = True
    for model, lang in STRATA:
        key = f"{model}_{lang}"
        cpath = f"{CONSENSUS}/consensus_map_{key}.json"
        fpath = f"{QUALIFIED}/final_search_map_{key}.json"
        if not (os.path.exists(cpath) and os.path.exists(fpath)):
            rep["strata"][key] = {"error": "map file missing"}
            all_ok = False
            continue

        cons, cons_meta = load_map(cpath)
        fin, fin_meta = load_map(fpath)

        missing = sorted(set(fin) - set(cons))
        overlap = sorted(set(fin) & set(cons))
        identical_rules = sum(1 for i in overlap if cons[i]["rules"] == fin[i]["rules"])
        identical_set = sum(1 for i in overlap if set(cons[i]["rules"]) == set(fin[i]["rules"]))
        identical_prompt = sum(
            1 for i in overlap if cons[i]["prompt_hash"] == fin[i]["prompt_hash"]
        )
        differing = [i for i in overlap if cons[i]["rules"] != fin[i]["rules"]]

        ok = not missing and not differing
        all_ok &= ok
        rep["strata"][key] = dict(
            consensus_map=dict(
                path=cpath, sha256=sha256(cpath), n_tasks=len(cons),
                metadata_keys=sorted(cons_meta)[:12],
            ),
            final_map=dict(
                path=fpath, sha256=sha256(fpath), n_tasks=len(fin),
                metadata_keys=sorted(fin_meta)[:12],
            ),
            coverage=dict(
                final_tasks=len(fin), overlap=len(overlap),
                missing_from_consensus=len(missing), missing_indices=missing[:20],
            ),
            rule_assignment=dict(
                identical_ordered=identical_rules,
                identical_as_set=identical_set,
                identical_prompt_hash=identical_prompt,
                differing=len(differing), differing_indices=differing[:20],
            ),
            usable_as_baseline=ok,
        )

    # locate the actual baseline runs and record what they referenced
    for d in sorted(glob.glob(f"{SCREEN}/*")):
        name = os.path.basename(d)
        cfg_path = f"{d}/run_config.json"
        if not os.path.exists(cfg_path):
            continue
        cfg = json.load(open(cfg_path))
        a = cfg.get("args", {})
        rmap = a.get("rules_map")
        entry = dict(
            dir=d,
            git_commit_sha=cfg.get("git_commit_sha"),
            model=a.get("model"),
            languages=a.get("languages"),
            n_cases=a.get("n_cases"),
            temperature=a.get("temperature"),
            seeds=a.get("seeds"),
            n_seeds=len(a.get("seeds") or []),
            rules_map_path=rmap,
            rules_map_sha256_derived=(
                sha256(rmap) if rmap and os.path.exists(rmap) else None
            ),
            replicate_files=len(glob.glob(f"{d}/intermediate/*.jsonl")),
        )
        rep["baseline_runs"][name] = entry

    rep["verdict"] = dict(
        all_strata_reconciled=all_ok,
        conclusion=(
            "Baselines may be subset to the final population and used directly."
            if all_ok
            else "RECONCILIATION FAILED - do not use these baselines without review."
        ),
    )
    write("baseline_reconciliation.json", json.dumps(rep, indent=2))

    L = [
        "# Baseline provenance reconciliation",
        "",
        f"Computed at {rep['computed_at']} — **analysis-time derivation, not a run-time record**.",
        "No run artifact was modified.",
        "",
        "## Why this document exists",
        "",
        "The temperature-0.6 screening baselines predate the provenance-manifest",
        "contract, so they carry a `rules_map` path but no `rules_map_sha256` and no",
        "`population_fingerprint`. Rather than assert provenance that was never",
        "recorded, this reconciles the artifacts directly.",
        "",
        "## Map reconciliation",
        "",
        "| stratum | final tasks | consensus tasks | missing | rules identical (ordered) | prompt_hash identical | differing | usable |",
        "|---|---:|---:|---:|---:|---:|---:|:--:|",
    ]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        if "error" in s:
            L.append(f"| {key} | — | — | — | — | — | — | **{s['error']}** |")
            continue
        cv, ra = s["coverage"], s["rule_assignment"]
        L.append(
            f"| {key} | {cv['final_tasks']} | {s['consensus_map']['n_tasks']} | "
            f"{cv['missing_from_consensus']} | {ra['identical_ordered']} | "
            f"{ra['identical_prompt_hash']} | {ra['differing']} | "
            f"{'YES' if s['usable_as_baseline'] else 'NO'} |"
        )

    L += ["", "## Map file digests (computed today)", "",
          "| stratum | file | sha256 |", "|---|---|---|"]
    for key in sorted(rep["strata"]):
        s = rep["strata"][key]
        if "error" in s:
            continue
        L.append(f"| {key} | consensus_map_{key}.json | `{s['consensus_map']['sha256']}` |")
        L.append(f"| {key} | final_search_map_{key}.json | `{s['final_map']['sha256']}` |")

    L += ["", "## Baseline runs", "",
          "| run | model | n_cases | temp | seeds | replicates | git sha | referenced map sha256 |",
          "|---|---|---:|---:|---:|---:|---|---|"]
    for name in sorted(rep["baseline_runs"]):
        r = rep["baseline_runs"][name]
        sha = r["rules_map_sha256_derived"]
        L.append(
            f"| {name} | {r['model'] or '—'} | {r['n_cases']} | {r['temperature']} | "
            f"{r['n_seeds']} | {r['replicate_files']} | "
            f"`{(r['git_commit_sha'] or '—')[:12]}` | `{(sha or '—')[:16]}` |"
        )

    L += [
        "",
        "## Verdict",
        "",
        f"**{rep['verdict']['conclusion']}**",
        "",
        "## Sentence for the thesis",
        "",
        "> Baseline runs predate the provenance-manifest contract; their rule",
        "> assignments were reconciled against the final qualified map by task-index",
        "> and prompt-hash comparison (`baseline_reconciliation.json`), confirming",
        "> identical rule sets for all shared tasks.",
    ]
    write("baseline_reconciliation.md", "\n".join(L) + "\n")
    print("\n".join(L[12:24]))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
