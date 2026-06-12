# Implementation Reference

Module-by-module reference, the on-disk output schema, extension points, and
dependencies. For the high-level design (the pipeline, the two strategies, the
fitness model) see [ARCHITECTURE.md](ARCHITECTURE.md).

## Module reference

### `src/mutation/` — mutation pipeline

#### `rule_parser.py` — safe-zone-aware document parser

CodeGuard rules are Markdown with YAML frontmatter, fenced code blocks, and
prose. Only prose may be mutated. `ParsedRule` enforces this:

| Member | Description |
|---|---|
| `ParsedRule.parse(text)` | Split a rule into frontmatter + ordered `Block` list |
| `Block(type="prose"\|"code")` | Prose blocks are mutable; code blocks are never touched |
| `Section` | Top-level (`##`) section, used by `SectionReorderMutator` |
| `get_mutable_prose()` | `(block_id, text)` pairs that are safe mutation targets |
| `reconstruct(mutations)` | Reassemble the document; frontmatter first, code unchanged |
| `mask_inline_code` / `unmask_inline_code` | Replace `` `code` `` spans with `__IC_N__` placeholders and restore them |

**Safe-zone contract:** frontmatter, fenced code blocks, and inline code are
never modified by any mutator.

#### `base.py` — abstract interfaces

- **`Mutator`** — `mutate(text) → MutationResult`, `mutate_batch`, `reset_seed`; every mutator takes a `seed` for deterministic output.
- **`MutationResult`** — `original`, `mutated`, `mutation_type`, `changes: list[str]`, `metadata: dict` (populated by the validator), `changed: bool`, `change_ratio: float` (word-level dissimilarity).

#### `rule_based.py` — function-based mutators (5)

Deterministic, no LLM call. Same output for a given input + seed.

| Mutator | Key behaviour |
|---|---|
| `VerbWeakeningMutator` | Replaces high-urgency security verbs with weaker synonyms (`Ensure → Try to ensure`, `Prevent → Consider preventing`). Fixed replacement map. |
| `SynonymReplacementMutator` | Substitutes nouns/verbs with WordNet synonyms (`nlpaug`). Masks inline code first; word count may grow ≤ 50%. |
| `AddRandomWordMutator` | Inserts security-domain adjectives/adverbs before nouns/verbs from a curated list. |
| `SectionReorderMutator(mode="shuffle")` | Randomly permutes `##`/`###` sections (preamble pinned first). **Paragraph fallback** when < 2 headers: reorders `\n\n`-separated prose paragraphs; headers and code fences pinned. |
| `SectionReorderMutator(mode="degrade")` | Moves the highest security-keyword section to last position (LLM recency bias). Same fallback. |

#### `llm_based.py` — LLM-based mutators (3)

Call the same `LLMBackend` already used for code generation — one extra request
per mutation.

| Mutator | Temperature | Behaviour |
|---|---|---|
| `NegationInjectionMutator` | 0.0 | Inserts contradictory qualifiers before imperative directives (`"MUST validate all input"` → `"While not required in all scenarios, you MUST validate all input"`). Source: LLMORPH MR-48/76. |
| `VoiceChangeMutator` | 0.0 | Active imperative → passive advisory (`"Always sanitize user input"` → `"User input should always be sanitized"`). Source: AUGMENT voice-change. |
| `ParaphraseMutator` | 0.6 | Rewrites prose with weaker vocabulary. Inline code is masked with `ICODE_N` placeholders before the LLM call and restored after, guaranteeing `inline_code_retention == 1.0`. Source: LLMORPH MR-51 + AUGMENT. |

All LLM mutators strip frontmatter before the call and reattach it unchanged.
Each mutation is applied **once** (no retry). If a mutation returns text
identical to its parent, the EA marks that mutator tried for the parent and
selects a different mutator within the same iteration — so no code generation
is spent on a no-op (`ea_optimizer.py`).

#### `pool.py` — `MutatorPool`

A thin container for the mutator list + the shared RNG seed (`mutators`,
`mutator_names`). Both search strategies do their own constrained selection over
this set.

#### `quality.py` — `MutationQualityValidator` (informational, post-hoc)

Implements the AUGMENT three-criteria framework plus a security-domain
criterion (four criteria total). Enabled with `--enable-validation`.
**Informational:** every candidate's metadata is recorded; nothing is ever
rejected on quality grounds (the validator never gates the search). The
post-hoc audit in `scripts/analyze/validation_audit.py` reports per-criterion
fail rates and a "what if we had gated" simulation.

| # | Criterion | How measured | Default threshold |
|---|---|---|---|
| 1 | Instruction adherence | per-mutator check function | pass/fail |
| 2 | Semantic similarity | cosine of `all-mpnet-base-v2` embeddings | ≥ 0.75 |
| 3 | Perplexity ratio | perplexity(mutated)/perplexity(original) | ≤ 2.5 (off by default) |
| 4 | Security-domain preservation | inline-code retention (= 1.0) + keyword retention | keyword ≥ 0.70 |

`passes_all = instruction_adherent AND keyword_retention ≥ 0.70 AND (sbert is
None OR sbert ≥ 0.75) AND (perplexity is None OR perplexity ≤ 2.5)`.

`validation_metadata` recorded per iteration (in `iterations.jsonl`):
`instruction_adherent`, `sbert_step`, `sbert_cum` (drift vs the on-disk
original), `perplexity_ratio`, `inline_code_retention`, `keyword_retention`,
`security_intent_preserved`, `passes_all`, `changed`. When validation is off,
`validation_metadata` is `{}`.

---

### `src/optimizer/` — search

#### `hill_climber.py` — `HillClimber` orchestration

Owns the evaluation seam shared by both strategies. `optimize_per_prompt_rules()`:

1. **Baseline pass** — generate code for every prompt under the original rules, run a single batched Semgrep, record per-case baseline findings and reference code (for CodeBLEU).
2. **Dispatch** — to `run_ea` or `run_random_baseline` (`ea_optimizer.py`) based on `config.optimizer`. Both call back into the same per-prompt evaluation closure.
3. **Persist** — `iterations.jsonl` (per iteration, atomic append), `intermediate/{iter_id}.jsonl` (per prompt), `archive_snapshots/` (EA, every 20 iters), `mutated_rules/iterNNN/`, and the run summary.

`HillClimbConfig` key fields: `max_iterations`, `optimizer` (`"ea"` default |
`"random_baseline"`), `archive_cap` (6), `restart_h` (8), `max_depth_ea` (4),
`max_mutations_per_iter` (4), `enable_validation`, `enable_eval_cache` (True),
`fitness_strategy` (SEVERITY_WEIGHTED). (`mutation_max_retries` is retained as a
deprecated no-op for CLI/config back-compat.)

**Eval cache:** per prompt, keyed by `(test_case_id, sha256(assembled_rule_text))`.
A hit skips both code generation and Semgrep — safe under `temperature=0` greedy
decoding. Reported in `hillclimb_summary` as `eval_cache_stats`.

#### `ea_optimizer.py` — the two runners

- `run_ea(...)` — the (1+1) EA over per-rule Pareto archives. Records `mutation_chain` = the parent's lineage + this iteration's mutator (last element); `mutator_stats` use **last-mutator credit** `{attempts, archive_adds, archive_adds_f1}`.
- `run_random_baseline(...)` — the stateless sampler. Records `mutation_chain` = the `n` sampled mutators; `mutator_stats` use **whole-chain credit** `{applications, applications_f1_advancing}` (every mutator in a chain whose final candidate beat baseline is credited).
- `_ChainMutator` — applies an ordered list of mutators as one cumulative mutation (used by the random baseline).

#### `pareto_archive.py` — `ParetoArchive` (EA only)

Per-rule archive over the three maximised objectives. Each `ArchiveEntry` carries
its `rule_text`, the three objective values, `depth` (mutations from the
original), `attempted_children` (mutators already tried on it), and
`mutation_path` (the lineage). `try_add` rejects dominated candidates and
identity candidates (byte-identical to an existing entry), evicting the
lowest-sum entry on cap overflow. Restart triggers (each snapshots the prior
state into `restart_history` before reseeding from the original): `stagnation`
(`restart_h` non-inserting attempts), `depth_saturated` (all entries at
`max_depth`), `mutator_exhausted` (all entries tried every mutator),
`fully_exhausted` (mixed).

---

### `src/evaluation/` — scoring

| File | Role |
|---|---|
| `semgrep_runner.py` | Runs Semgrep per batch in one subprocess; resolves the `semgrep` executable via PATH then the running interpreter's `bin/` dir; writes a `semgrep_debug.jsonl` record on **every** path so a failed scan (`error != null`) is distinguishable from a clean scan with zero findings. |
| `composite_fitness.py` | `CompositeFitnessEvaluator` — per prompt, `semgrep_delta = score(mutated) − score(baseline)` and `code_divergence = 1 − CodeBLEU(generated, reference)`. Takes a per-call `lang` override so a mixed Python+Java run uses the correct tree-sitter grammar per case. |
| `fitness.py` | `FitnessStrategy` (per-prompt Semgrep scoring; `SEVERITY_WEIGHTED` = ERROR×3 + WARNING×1) and `AggregatedFitness`, which exposes the three search objectives (f1/f2/f3). |

---

### `src/llm_backends/` — backends

| Backend (`--backend`) | Description |
|---|---|
| `claude` (`ClaudeBackend`) | Anthropic Messages API. Default model `claude-haiku-4-5`. The replication path. |
| `openai` (`OpenAIBackend`) | OpenAI Chat Completions API. Default model `gpt-4o-mini`. |
| `delftblue` (`DelftBlueLocalBackend`) | HuggingFace model from local cache (`HF_HUB_OFFLINE=1`), Qwen2.5-Coder-32B-Instruct on A100; fp16 or 4-bit. Lazy-imported so the API path needs no torch. |

`LLMBackend.generate(system, messages, …) → LLMResponse` with `content`,
`latency_ms`, `input_tokens`, `output_tokens`.

---

## Output schema

`run_config.json` carries `schema_version: 2`. A run directory:

```
{output_dir}/
├── run_config.json                  # schema_version, all CLI args, argv, git_sha, slurm_job_id, hostname
├── hillclimb_summary_*.json         # run-level: provider/model, totals, pool_arm_stats, eval_cache_stats, run_config_ref
├── iterations.jsonl                 # one record per iteration (see below)
├── archive_snapshots/iterNNNN.json  # EA only — {iter, config, archives{rule_id: {...}}} every 20 iters + final
├── intermediate/{iter_id}.jsonl     # per-prompt evaluation records; iter_id ∈ {baseline, ea_iter0001, rand_iter0042}
├── mutated_rules/iterNNN/           # <rule>.md (mutated text) + meta.json
├── semgrep_debug/semgrep_debug.jsonl
└── run.log
```

**`iterations.jsonl`** (one JSON object per line):

```jsonc
{
  "iter": 7, "timestamp": "…Z",
  "strategy": "ea",                        // "ea" | "random_baseline"
  "rule_id": "codeguard-0-…",
  "mutation_chain": ["verb_weakening"],    // list[str]; EA: lineage; random: the n sampled mutators
  "chain_length": 1,
  "mutation_identity": false,              // candidate byte-identical to its source
  "validation_passed": true,
  "f1": 0.0, "f2": 0.0, "f3": 0.0,         // the three objectives (null if no candidate)
  "f1_advance": false,
  "accepted": true,                        // EA: try_add result; random: always true
  "num_prompts_affected": 3,
  "llm_calls_total": 31, "input_tokens_total": 105521, "output_tokens_total": 28119,
  "validation_metadata": { … },            // {} unless --enable-validation
  "selection_meta": { … }                  // EA: parent_iter/parent_depth/archive sizes/…; random: {}
}
```

**`archive_snapshots/iterNNNN.json`** — top-level `{iter, config, archives}`; the
per-rule `config` (cap/restart_h/max_depth/n_mutators) is hoisted out once.
Each archive entry carries `f1/f2/f3`, `depth`, `mutation_chain`,
`iteration_added`, and a `rule_text_ref` pointing at the corresponding
`mutated_rules/` file (null for the depth-0 seed = the original rule).

**`intermediate/{iter_id}.jsonl`** — per prompt: `test_case_id`, `language`,
`cwe_id`, `rules_used`, `fitness{raw_count, weighted_score, check_ids,
composite_score, code_divergence, …}`, latencies, tokens, and `generated_code`
(last). The prompt text is *not* stored — it is recoverable from the rules map
keyed by `test_case_id`.

**`mutated_rules/iterNNN/meta.json`** — `{iteration, mutation_chain (list),
target_rule_id, mutation_identity, mutation_changes}`.

---

## Extension points

**New mutator** — subclass `Mutator`, implement `name` + `mutate()`; register an
adherence check in `quality.py`; add it to the `--mutators` choices in
`scripts/experiments/run_with_rules_map.py`.

```python
from src.mutation.base import Mutator, MutationResult
from src.mutation.rule_parser import ParsedRule

class MyMutator(Mutator):
    @property
    def name(self) -> str:
        return "my_mutation"

    def mutate(self, text: str) -> MutationResult:
        parsed = ParsedRule.parse(text)
        new_body = transform(parsed.body_raw)
        return MutationResult(
            original=text,
            mutated=parsed.frontmatter_raw + new_body,
            mutation_type=self.name,
            changes=["applied X"],
        )
```

**New objective / fitness component** — extend `AggregatedFitness` in
`src/evaluation/fitness.py` and the archive's dominance check in
`pareto_archive.py`.

**New backend** — implement `LLMBackend`, register it in
`src/llm_backends/__init__.py`, and add a `--backend` choice.

---

## Dependencies

Managed by `uv` (Python ≥ 3.11), pinned in `uv.lock`.

- **Code generation:** `anthropic`, `openai` (API path); `torch`, `transformers`, `accelerate`, `bitsandbytes` (`--extra gpu`, DelftBlue only).
- **Scoring:** `semgrep` (pinned 1.85.0 for DelftBlue glibc 2.28), `codebleu` + `tree-sitter-{python,java,c}` grammars.
- **Validation:** `sentence-transformers` (`all-mpnet-base-v2`), `textstat`.
- **Mutation:** `nlpaug`, `nltk`, `pyyaml`.
- **Analysis (`--extra analysis`):** `matplotlib`, `scipy`, `pandas`.
- **Dev (`--extra dev`):** `pytest`, `ruff`.

**DelftBlue infrastructure:** A100 80GB (`gpu-a100`), HF cache at
`/scratch/$USER/models/hub` (offline), Semgrep rules at
`/scratch/$USER/semgrep-rules/security-audit`.
