#!/usr/bin/env python3
"""
analyze_prompt_rule_maps.py — analyse retrieval maps and build a consensus "final" map.

A retrieval map is one seed's pass over a fixed prompt set: JSON with
``{metadata, rule_frequency, mappings}`` where each mapping has ``prompt_hash``,
``cwe_id``, ``language`` and ``rules_retrieved``. A temperature sweep produces
N such maps (one per seed) for a config (model × language × framing).

Because temp>0 sampling makes the per-prompt rule *selection* vary seed to seed,
no single seed is "the" map. This tool aggregates the N seeds into one consensus
map by per-prompt majority vote, and reports the stability stats that justify it.

Four modes (stdlib only — safe/fast on a login node):

  single   <map.json>
      Key stats for ONE map: parse-method breakdown, rules/prompt, unique rules,
      empty prompts, top rule frequencies.

  across   "<glob>"  [--k K] [--build OUT.json]
      Stability ACROSS the seed maps of one config, a consensus table over a few
      K thresholds, and — with --build — writes the K-consensus map.

  compare  "<glob_A>" "<glob_B>"  [--k K] [--label-a A --label-b B]
      Before/after (old vs reframed), cross-model, or a single map vs a consensus:
      builds each side's consensus over the shared prompts and reports within-set
      stability, the cross Jaccard, and the largest per-rule prevalence shifts.

  all      [--sweep-dir D] [--out-dir D] [--k K]
      The whole pipeline: build every reframed config's consensus map, then
      cross-model and vs-experiment-map comparisons, and write REPORT.md.
      Skips configs whose maps are not on disk yet, so it runs on a partial sweep.

Examples
────────
  python scripts/mapping/analyze_prompt_rule_maps.py single \\
      rule_maps/temp_sweep_reframed/java/retrieval_map_qwen2.5_coder_32b_instruct_qwen32b_vulnerable_java_t0p6_seed1.json

  python scripts/mapping/analyze_prompt_rule_maps.py across \\
      "rule_maps/temp_sweep_reframed/java/retrieval_map_qwen2.5_coder_32b_instruct_*.json" --k 11

  python scripts/mapping/analyze_prompt_rule_maps.py all
"""

from __future__ import annotations

import argparse
import glob as globmod
import json
import math
import re
import statistics as st
import sys
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── Project layout for `all` mode ────────────────────────────────────────────
MODELS = [  # (label, filename prefix, pretty name)
    ("qwen", "retrieval_map_qwen2.5_coder_32b_instruct", "Qwen2.5-Coder-32B"),
    ("llama", "retrieval_map_llama_3.3_70b_instruct", "Llama-3.3-70B"),
]
LANGS = [  # (subdir, file-tag, prompt-source map used as --from-map / consensus template)
    ("python", "py", "rule_maps/old_maps/map_qwen32b_vulnerable_py.json"),
    ("java", "java", "rule_maps/old_maps/map_qwen32b_vulnerable_java.json"),
]
# Old-framing (v1) sweep maps, for the reframing before/after (Qwen only). The old
# python sweep is race-contaminated except seed1 -> compare seed1 only; the old java
# sweep's 20 seeds are all clean.
OLD_SWEEP = {
    "python": ("rule_maps/temp_sweep/python/**/retrieval_map_qwen2.5_coder_32b_instruct_*_seed1.json",
               "old py sweep race-contaminated except seed1 -> seed1 only"),
    "java": ("rule_maps/temp_sweep/java/**/retrieval_map_qwen2.5_coder_32b_instruct_*.json",
             "old java sweep, 20 clean seeds"),
}


# ── Loading ──────────────────────────────────────────────────────────────────

def load_map(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _seed_of(f: str) -> int:
    m = re.search(r"seed(\d+)", Path(f).name)
    return int(m.group(1)) if m else -1


def iglob(pattern: str) -> list[str]:
    """Recursive glob (so `**` matches nested model subdirs), de-duplicated + sorted."""
    return sorted(set(globmod.glob(pattern, recursive=True)))


def load_seed_set(pattern: str) -> list[dict]:
    """Load every map matching a glob (a single file path is a valid glob), by seed."""
    files = sorted(iglob(pattern), key=_seed_of)
    if not files:
        sys.exit(f"ERROR: no maps match {pattern!r}")
    return [{"path": f, "seed": _seed_of(f), "data": load_map(f)} for f in files]


def selections(data: dict) -> dict[str, set[str]]:
    """prompt_hash -> set(rules_retrieved) for one map."""
    return {e["prompt_hash"]: set(e["rules_retrieved"]) for e in data["mappings"]}


def prompt_meta(data: dict) -> dict[str, dict]:
    """prompt_hash -> {cwe_id, language, prompt_hash, prompt} (identical across seeds).

    The full ``prompt`` text is carried so the consensus map is directly usable as
    a rules-map by the experiment pipeline (RuleMapping requires cwe_id, language,
    prompt_hash, prompt, rules_retrieved).
    """
    out: dict[str, dict] = {}
    for e in data["mappings"]:
        h = e["prompt_hash"]
        if h not in out:  # keep first occurrence (stable index for duplicate prompts)
            out[h] = {
                "index": e.get("index"),
                "cwe_id": e.get("cwe_id"),
                "language": e.get("language"),
                "prompt_hash": h,
                "prompt": e.get("prompt", ""),
            }
    return out


# ── Shared metrics ───────────────────────────────────────────────────────────

def jaccard(a: set, b: set) -> float:
    u = a | b
    return len(a & b) / len(u) if u else 1.0  # two empty sets == identical


def mean_pairwise_jaccard(sels: list[dict[str, set]], hashes: list[str]) -> float:
    pair_means = []
    for A, B in combinations(sels, 2):
        pair_means.append(st.mean(jaccard(A.get(h, set()), B.get(h, set())) for h in hashes))
    return st.mean(pair_means) if pair_means else float("nan")


def frequency_table(sels: list[dict[str, set]], hashes: list[str]) -> dict[str, Counter]:
    """prompt_hash -> Counter(rule -> #seeds that selected it)."""
    freq = {h: Counter() for h in hashes}
    for s in sels:
        for h in hashes:
            for r in s.get(h, set()):
                freq[h][r] += 1
    return freq


def resolve_k(k_arg: float | None, n_seeds: int) -> int:
    """K as absolute seed count. None -> strict majority; <=1.0 -> fraction."""
    if k_arg is None:
        return n_seeds // 2 + 1
    if k_arg <= 1.0:
        return max(1, math.ceil(k_arg * n_seeds))
    return int(k_arg)


def build_consensus(freq: dict[str, Counter], k: int) -> dict[str, list[str]]:
    """prompt_hash -> [rules selected by >= k seeds], ordered by freq desc."""
    return {h: [r for r, cnt in c.most_common() if cnt >= k] for h, c in freq.items()}


# ── Core computations (return dicts; printers/report consume them) ───────────

def across_core(seeds: list[dict], k_arg: float | None) -> dict:
    sels = [selections(s["data"]) for s in seeds]
    metas = prompt_meta(seeds[0]["data"])
    hashes = sorted(set().union(*[set(s.keys()) for s in sels]))
    n_seeds = len(seeds)
    rpp = [st.mean(len(s.get(h, set())) for h in hashes) for s in sels]
    uniq = [len(set().union(*s.values())) if s else 0 for s in sels]
    freq = frequency_table(sels, hashes)
    k = resolve_k(k_arg, n_seeds)
    cons = build_consensus(freq, k)
    return {
        "seeds": seeds, "sels": sels, "metas": metas, "hashes": hashes, "n_seeds": n_seeds,
        "rpp": rpp, "uniq": uniq, "freq": freq, "k": k, "cons": cons,
        "mean_jac": mean_pairwise_jaccard(sels, hashes),
        "unanimous": sum(1 for h in hashes if len({frozenset(s.get(h, set())) for s in sels}) == 1),
        "cons_rpp": st.mean(len(cons[h]) for h in hashes) if hashes else 0.0,
        "cons_uniq": len({r for v in cons.values() for r in v}),
        "cons_empty": sum(1 for h in hashes if not cons[h]),
    }


def compare_core(A: list[dict], B: list[dict], k_arg: float | None) -> dict:
    selsA = [selections(s["data"]) for s in A]
    selsB = [selections(s["data"]) for s in B]
    hA = set().union(*[set(s.keys()) for s in selsA])
    hB = set().union(*[set(s.keys()) for s in selsB])
    shared = sorted(hA & hB)
    if not shared:
        sys.exit("ERROR: the two sets share no prompt_hashes.")
    freqA, freqB = frequency_table(selsA, shared), frequency_table(selsB, shared)
    kA, kB = resolve_k(k_arg, len(A)), resolve_k(k_arg, len(B))
    consA, consB = build_consensus(freqA, kA), build_consensus(freqB, kB)

    def prevalence(cons):
        c = Counter(r for h in shared for r in cons[h])
        return {r: c[r] / len(shared) for r in c}

    pA, pB = prevalence(consA), prevalence(consB)
    deltas = sorted(((pB.get(r, 0) - pA.get(r, 0), r) for r in set(pA) | set(pB)),
                    key=lambda x: -abs(x[0]))
    return {
        "nA": len(A), "nB": len(B), "shared": shared, "only_a": len(hA - hB), "only_b": len(hB - hA),
        "jacA": mean_pairwise_jaccard(selsA, shared) if len(A) > 1 else float("nan"),
        "jacB": mean_pairwise_jaccard(selsB, shared) if len(B) > 1 else float("nan"),
        "rppA": st.mean(len(consA[h]) for h in shared),
        "rppB": st.mean(len(consB[h]) for h in shared),
        "kA": kA, "kB": kB,
        "cross": st.mean(jaccard(set(consA[h]), set(consB[h])) for h in shared),
        "identical": sum(1 for h in shared if set(consA[h]) == set(consB[h])),
        "deltas": deltas, "pA": pA, "pB": pB,
    }


# ── Consensus map writer ─────────────────────────────────────────────────────

def write_consensus_map(out, core: dict, template_path: str | Path | None = None) -> dict:
    """Write a K-consensus map in the standard {metadata, rule_frequency, mappings} schema.

    If ``template_path`` (the source --from-map the sweep ran over) is given, the
    output MIRRORS that map entry-for-entry — keeping each entry's ``index`` (=
    the pipeline's ``test_case_id``), cwe_id, language, prompt_hash and prompt
    verbatim, and only substituting ``rules_retrieved`` with the consensus rules.
    This makes the consensus map a drop-in rules-map whose per-prompt identity
    (and duplicate rows) match the source, so a baseline run over it aligns
    prompt-for-prompt with the old baseline. Without a template, the map is the
    de-duplicated per-prompt-hash consensus (carrying each seed's own ``index``).
    """
    seeds, metas, hashes, freq, cons, k = (
        core["seeds"], core["metas"], core["hashes"], core["freq"], core["cons"], core["k"])
    src_md = seeds[0]["data"].get("metadata", {})

    def _entry(index, cwe, lang, h, prompt):
        rules = cons.get(h, [])
        return {
            "index": index, "cwe_id": cwe, "language": lang, "prompt_hash": h,
            "prompt": prompt, "rules_retrieved": rules, "num_rules": len(rules),
            "seed_frequency": dict(freq.get(h, Counter()).most_common()),
        }

    if template_path is not None:
        # Mirror the source map, keeping each entry's index/test_case_id + cwe/lang/
        # prompt verbatim (so a baseline over this map aligns with the old baseline).
        # De-duplicate by prompt_hash keeping the FIRST occurrence: a duplicated
        # prompt is byte-identical output at temp=0 (verified), so the extra row is
        # redundant -- the final set is the distinct prompts (e.g. java 114 -> 113).
        template = load_map(template_path)["mappings"]
        mappings, seen = [], set()
        for e in template:
            h = e["prompt_hash"]
            if h in seen:
                continue
            seen.add(h)
            mappings.append(_entry(e["index"], e.get("cwe_id"), e.get("language"), h, e.get("prompt", "")))
    else:
        # De-duplicated by prompt_hash; carry the seed map's own index.
        mappings = [
            _entry(metas[h].get("index"), metas[h].get("cwe_id"), metas[h].get("language"),
                   h, metas[h].get("prompt", ""))
            for h in sorted(hashes, key=lambda x: metas[x].get("cwe_id") or "")
        ]
    rule_freq = Counter(r for e in mappings for r in e["rules_retrieved"])
    doc = {
        "metadata": {
            "kind": "consensus_map",
            "built": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "model": src_md.get("model"),
            "framing": src_md.get("prompt_template_version", "(unversioned)"),
            "temperature": src_md.get("temperature"),
            "n_seeds": core["n_seeds"],
            "seeds": [s["seed"] for s in seeds],
            "consensus_k": k,
            "consensus_rule": f"rule kept iff selected by >= {k}/{core['n_seeds']} seeds",
            "total_prompts": len(mappings),
            "distinct_prompts": len(hashes),
            "avg_rules_per_prompt": round(st.mean(e["num_rules"] for e in mappings), 3),
            "unique_rules_used": len(rule_freq),
            "empty_prompts": sum(1 for e in mappings if e["num_rules"] == 0),
            "mean_pairwise_jaccard": round(core["mean_jac"], 4),
            "avg_rules_per_seed_prompt": round(st.mean(core["rpp"]), 3),
            "source_template": Path(template_path).name if template_path else None,
            "source_maps": [Path(s["path"]).name for s in seeds],
        },
        "rule_frequency": dict(rule_freq.most_common()),
        "mappings": mappings,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc


# ── Mode: single ─────────────────────────────────────────────────────────────

def cmd_single(args: argparse.Namespace) -> None:
    data = load_map(args.map)
    md = data.get("metadata", {})
    maps = data["mappings"]
    n = len(maps)
    rules_per = [len(e["rules_retrieved"]) for e in maps]
    parse = Counter(e.get("parse_method", "?") for e in maps)
    freq = Counter(r for e in maps for r in e["rules_retrieved"])
    print(f"MAP  {Path(args.map).name}")
    print(f"  model            : {md.get('model')}")
    print(f"  framing          : {md.get('prompt_template_version', '(unversioned)')}")
    print(f"  seed / temp      : {md.get('seed')} / {md.get('temperature')}")
    print(f"  prompts          : {n}")
    print(f"  parse_method     : {dict(parse)}")
    print(f"  rules/prompt     : mean={st.mean(rules_per):.2f}  range=[{min(rules_per)},{max(rules_per)}]")
    print(f"  unique rules     : {len(freq)}")
    print(f"  empty prompts    : {sum(1 for r in rules_per if r == 0)}/{n}")
    print("  top rules        :")
    for r, c in freq.most_common(args.top):
        print(f"      {c:>4}  {r}")


# ── Mode: across ─────────────────────────────────────────────────────────────

def _print_across(core: dict, glob: str) -> None:
    n = len(core["hashes"])
    seeds = core["seeds"]
    print(f"ACROSS  {glob}")
    print(f"  seeds            : {core['n_seeds']}  (seed {seeds[0]['seed']}..{seeds[-1]['seed']})")
    print(f"  prompts          : {n}")
    print(f"  rules/prompt     : mean={st.mean(core['rpp']):.2f} sd={st.pstdev(core['rpp']):.2f}  "
          f"range=[{min(core['rpp']):.2f},{max(core['rpp']):.2f}]")
    print(f"  unique rules/seed: mean={st.mean(core['uniq']):.1f}  range=[{min(core['uniq'])},{max(core['uniq'])}]")
    print(f"  mean pairwise Jaccard (selection stability): {core['mean_jac']:.3f}")
    print(f"  unanimous prompts (identical across all seeds): {core['unanimous']}/{n} "
          f"({100*core['unanimous']/n:.0f}%)")
    print("  consensus thresholds:")
    n_seeds, k = core["n_seeds"], core["k"]
    for kk in sorted({n_seeds, math.ceil(0.75 * n_seeds), n_seeds // 2 + 1, k}, reverse=True):
        cons = build_consensus(core["freq"], kk)
        empty = sum(1 for h in core["hashes"] if not cons[h])
        avg = st.mean(len(cons[h]) for h in core["hashes"])
        uniq = len({r for v in cons.values() for r in v})
        star = "  <-- chosen K" if kk == k else ""
        print(f"      K>={kk:>2}/{n_seeds}: avg={avg:.2f} r/p, {uniq} unique rules, empty={empty}/{n}{star}")


def cmd_across(args: argparse.Namespace) -> None:
    core = across_core(load_seed_set(args.glob), args.k)
    _print_across(core, args.glob)
    if args.build:
        write_consensus_map(args.build, core, template_path=args.source_map)
        print(f"\n  consensus map (K>={core['k']}/{core['n_seeds']}) written: {args.build}")
        print(f"      {core['cons_rpp']:.2f} rules/prompt, {core['cons_uniq']} unique rules, "
              f"{core['cons_empty']} empty prompts")


# ── Mode: compare ────────────────────────────────────────────────────────────

def _fmt_jac(j, n):
    return f"{j:.3f}" if n > 1 else "n/a (single map)"


def _print_compare(c: dict, la: str, lb: str, top: int) -> None:
    print(f"COMPARE  A={la} ({c['nA']} maps)  vs  B={lb} ({c['nB']} maps)")
    print(f"  shared prompts   : {len(c['shared'])}  (A-only {c['only_a']}, B-only {c['only_b']})")
    print("  within-set stability (mean pairwise Jaccard):")
    print(f"      A {la:<16}: {_fmt_jac(c['jacA'], c['nA'])}")
    print(f"      B {lb:<16}: {_fmt_jac(c['jacB'], c['nB'])}")
    print("  consensus rules/prompt:")
    print(f"      A {la:<16}: {c['rppA']:.2f}   (K={c['kA']}/{c['nA']})")
    print(f"      B {lb:<16}: {c['rppB']:.2f}   (K={c['kB']}/{c['nB']})")
    print(f"  cross consensus agreement A vs B (mean per-prompt Jaccard): {c['cross']:.3f}")
    print(f"  prompts with identical consensus selection: {c['identical']}/{len(c['shared'])} "
          f"({100*c['identical']/len(c['shared']):.0f}%)")
    print("  largest rule prevalence shifts (B - A, share of prompts):")
    for d, r in c["deltas"][:top]:
        if abs(d) < 1e-9:
            continue
        arrow = "↑" if d > 0 else "↓"
        print(f"      {arrow} {d:+.2f}   {r}   [{la} {c['pA'].get(r,0):.2f} -> {lb} {c['pB'].get(r,0):.2f}]")


def cmd_compare(args: argparse.Namespace) -> None:
    A, B = load_seed_set(args.glob_a), load_seed_set(args.glob_b)
    _print_compare(compare_core(A, B, args.k), args.label_a, args.label_b, args.top)


# ── Mode: all (the wired-in cross-config pipeline) ──────────────────────────

def _config_glob(sweep_dir: Path, model_prefix: str, subdir: str) -> str:
    # Recursive: matches both the flat layout ({lang}/{prefix}_*.json) and the
    # model-nested layout ({lang}/{model}/{prefix}_*.json). The prefix already
    # disambiguates qwen vs llama, so the extra depth is safe.
    return str(sweep_dir / subdir / "**" / f"{model_prefix}_*.json")


def cmd_all(args: argparse.Namespace) -> None:
    sweep_dir = Path(args.sweep_dir)
    out_dir = Path(args.out_dir)
    lines: list[str] = []  # REPORT.md body

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("# Final consensus prompt→rule maps")
    emit(f"_Per-prompt rule sets for CyberSecEval, aggregated over 20 temp=0.6 seeds per config by "
         f"majority vote (K = strict majority, {'K=11/20' if True else ''}). Built "
         f"{datetime.now():%Y-%m-%d}._")
    emit()

    # 1) Per-config consensus build ------------------------------------------
    built: dict[tuple[str, str], dict] = {}  # (model_label, subdir) -> core
    emit("## 1. Per-config consensus (one final map per model × language)")
    emit()
    emit("| model | lang | seeds | prompts | r/p (per-seed) | stability | K | consensus r/p | empty | map |")
    emit("|---|---|--:|--:|--:|--:|--:|--:|--:|---|")
    for mlabel, mprefix, mname in MODELS:
        for subdir, tag, _src in LANGS:
            g = _config_glob(sweep_dir, mprefix, subdir)
            files = iglob(g)
            if not files:
                emit(f"| {mname} | {subdir} | — | — | — | — | — | — | — | _(no maps yet)_ |")
                continue
            core = across_core(load_seed_set(g), args.k)
            out = out_dir / f"final_consensus_map_{mlabel}_{subdir}.json"
            # Mirror the source --from-map (LANGS[..][2]) so index/test_case_id +
            # duplicate rows align with the experiment/old-baseline maps.
            template = PROJECT_ROOT / _src
            write_consensus_map(out, core, template_path=template if template.exists() else None)
            built[(mlabel, subdir)] = core
            emit(f"| {mname} | {subdir} | {core['n_seeds']} | {len(core['hashes'])} | "
                 f"{st.mean(core['rpp']):.2f} | {core['mean_jac']:.3f} | {core['k']} | "
                 f"{core['cons_rpp']:.2f} | {core['cons_empty']} | `{out.relative_to(PROJECT_ROOT)}` |")
    emit()

    # 2) Cross-model (same framing, shared prompts) --------------------------
    emit("## 2. Cross-model agreement (reframed consensus, Qwen vs Llama)")
    emit()
    for subdir, tag, _src in LANGS:
        gq = _config_glob(sweep_dir, MODELS[0][1], subdir)
        gl = _config_glob(sweep_dir, MODELS[1][1], subdir)
        if not (iglob(gq) and iglob(gl)):
            emit(f"- **{subdir}**: skipped (need both models present).")
            continue
        c = compare_core(load_seed_set(gq), load_seed_set(gl), args.k)
        emit(f"- **{subdir}** ({len(c['shared'])} prompts): consensus agreement "
             f"Jaccard **{c['cross']:.3f}**, identical on {c['identical']}/{len(c['shared'])} "
             f"({100*c['identical']/len(c['shared']):.0f}%); rules/prompt Qwen {c['rppA']:.2f} vs "
             f"Llama {c['rppB']:.2f}.")
        for d, r in c["deltas"][:5]:
            if abs(d) < 1e-9:
                continue
            emit(f"    - {'Llama+' if d>0 else 'Qwen+'} {abs(d):.2f}  `{r}` "
                 f"(Qwen {c['pA'].get(r,0):.2f} / Llama {c['pB'].get(r,0):.2f})")
    emit()

    status = "COMPLETE" if len(built) == len(MODELS) * len(LANGS) else "PARTIAL (some configs missing)"
    emit(f"_Status: {status} — {len(built)}/{len(MODELS)*len(LANGS)} configs built._")

    report = out_dir / "final_consensus_maps_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport written: {report}")
    print(f"Consensus maps + report in: {out_dir}/")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("single", help="key stats for one map")
    s.add_argument("map")
    s.add_argument("--top", type=int, default=8)
    s.set_defaults(func=cmd_single)

    a = sub.add_parser("across", help="stability + consensus across a config's seed maps")
    a.add_argument("glob")
    a.add_argument("--k", type=float, default=None,
                   help="consensus threshold: absolute seed count, or <=1.0 as a fraction "
                        "(default: strict majority = n//2+1)")
    a.add_argument("--build", metavar="OUT.json", default=None, help="write the K-consensus map")
    a.add_argument("--source-map", default=None,
                   help="the --from-map the sweep ran over; when given, the built map mirrors it "
                        "row-for-row (preserves index/test_case_id + duplicate rows) so a baseline "
                        "over it aligns with the experiment/old-baseline maps")
    a.set_defaults(func=cmd_across)

    c = sub.add_parser("compare", help="before/after, cross-model, or map-vs-consensus")
    c.add_argument("glob_a")
    c.add_argument("glob_b")
    c.add_argument("--k", type=float, default=None)
    c.add_argument("--label-a", default="A")
    c.add_argument("--label-b", default="B")
    c.add_argument("--top", type=int, default=10)
    c.set_defaults(func=cmd_compare)

    al = sub.add_parser("all", help="build every config's consensus + comparisons + REPORT.md")
    al.add_argument("--sweep-dir", default=str(PROJECT_ROOT / "rule_maps/temp_sweep_reframed"))
    al.add_argument("--out-dir", default=str(PROJECT_ROOT / "rule_maps"))
    al.add_argument("--k", type=float, default=None, help="consensus threshold (default: majority)")
    al.set_defaults(func=cmd_all)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
