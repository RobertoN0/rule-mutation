# Phase-3 selected candidates

The twenty rule sets that Phase 3 evaluated under temperature-0.6 resampling,
plus the retrieval maps that carry their rule ordering.

Five candidates were selected per model-language stratum, ranked by fitness and
drawn from five different search seeds, with each search run used at most once.

## Layout

```
artifacts/phase3_selected/
├── index.json      one record per candidate: stratum, rank, search seed, chromosome id, provenance
├── raw/            the 20 selected rule sets exactly as the search produced them
├── sanitized/      the 12 structurally repaired rule sets + manifest.json
└── maps/           the 20 derived retrieval maps + manifest.json
```

Directories are named `{model}_{language}_r{rank}_s{search_seed}_{chromosome_id}`,
so a raw candidate and its sanitised counterpart share a name.

## Raw versus sanitised

Phase 2 did not enforce the structural contract fail-closed, so some archived
candidates had changed fenced or inline code relative to the authored CodeGuard
rules.

- **Eight** candidates already satisfied the contract. They appear only in
  `raw/` and were resampled unchanged.
- **Twelve** did not. For those, `scripts/analyze/sanitize_phase3_candidates.py`
  restored the frontmatter, fenced blocks, and inline-code spans from the
  authored originals while keeping the candidate's prose and rule ordering, and
  wrote a separate artifact in `sanitized/`. The raw artifact was never edited.
  All twelve remained positive after repair, with score changes from -4 to +1.

**Raw and sanitised results are never mixed.** `sanitized/manifest.json` links
each repaired artifact to its raw source by hash, and
`../../analysis/results/rq5_three_way_baseline_comparison.json` records which
kind each candidate is under `candidate_kind`. The older
`rq4_phase3_safe_comparison.json` is retained for provenance and the
temperature-zero selection gain only.

Two artifacts additionally needed deterministic repairs for the tokens
`<input type="password">` and `--cap-drop all`; the linking prose is stored with
the sanitised outputs.

## Maps

A candidate's rule ordering is a gene of its chromosome, and an override
directory of rule files alone cannot encode it. Each candidate therefore has a
derived retrieval map in `maps/` that materialises its stable rule order over
the mapped tasks. `../../analysis/results/phase3_order_priority_check.json`
records the verification of those orderings.

## Provenance paths

`index.json`, `maps/manifest.json`, and `sanitized/manifest.json` contain
absolute paths from the research worktree the artifacts were copied out of, for
example `/home/rnegro/thesis/rule-mutation/experiments/03_search_runs/...`.
Those paths are **provenance records, not paths in this repository**. They point
into the archived experiment tree described in
[EVIDENCE_MAP.md](../../EVIDENCE_MAP.md) §4, and they are preserved rather than
rewritten so that each artifact can be traced back to the exact evaluation that
produced it.
