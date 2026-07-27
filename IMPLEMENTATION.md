# Implementation Reference

This document describes the active modules and on-disk artifacts. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the study design and
[WORKFLOW.md](WORKFLOW.md) for commands.

## Mutation

### `src/mutation/rule_parser.py`

CodeGuard rules contain YAML frontmatter, prose, inline code, and fenced code
blocks. `ParsedRule` separates these regions and reconstructs the document after
a mutation. Frontmatter and fenced code are immutable. Mutators that operate on
tokens mask inline code before transformation and restore it afterward.

### `src/mutation/base.py` and `pool.py`

`Mutator.mutate(text)` returns a `MutationResult` containing original text,
mutated text, the operator name, human-readable changes, and metadata.
`MutatorPool` holds the selected mutators and the seed shared with the search
runner.

### Rule-based mutators

`src/mutation/rule_based.py` provides:

| Operator | Transformation |
|---|---|
| `verb_weakening` | Replaces high-urgency security verbs with weaker synonyms (`Ensure → Try to ensure`, `Prevent → Consider preventing`). Fixed replacement map. |
| `synonym_replacement` | Replace eligible nouns and verbs with WordNet synonyms (`nlpaug`) |
| `add_random_word` | Insert security-domain adjectives or adverbs |
| `section_reorder_shuffle` | Shuffle sections, with a paragraph fallback |
| `section_reorder_degrade` | Moves the highest security-keyword section to last position |

### LLM-based mutators

`src/mutation/llm_based.py` reuses the code-generation backend:

| Operator | Temperature | Transformation |
|---|---:|---|
| `negation_injection` | 0.0 | Add qualifying contradictions before directives |
| `voice_change` | 0.0 | Convert active directives to passive advice |
| `paraphrase` | 0.6 | Rephrase and weaken prose while masking inline code |

Each object records LLM call attempts, completed calls, tokens, and latency.
These counts are separated from code-generation usage in `search_summary.json`.

### `src/mutation/quality.py`

`MutationQualityValidator` records:

- operator-specific instruction adherence;
- SBERT similarity to the parent and to the original rule;
- optional perplexity ratio;
- inline-code and security-keyword retention.

The measurements do not reject a candidate. SBERT similarity supplies f2, so
validation is required on real search runs.

## Search

### `src/optimizer/chromosome.py`

`RuleSetChromosome` contains mutated `GeneState` objects and rule-order priority
offsets. `RuleSetSpace` owns original texts, renders each task’s mapped subset,
and computes prompt signatures and chromosome IDs.

`ChromosomeArchive` stores the current non-dominated front. The origin is held
only as the reporting baseline. `try_add` rejects duplicate or dominated
candidates, removes members dominated by the child, and applies the bounded
overflow policy. The archive has no reset or restart operation.

### `src/optimizer/search.py`

`run_ea` and `run_random_search` share:

- five origin-based initialization candidates;
- `build_random_chromosome`, which applies between one and K changes;
- the rule/mutator pool, depth cap, order operator, and evaluation callback;
- identity retry accounting;
- candidate and prompt-level persistence callbacks.

EA main-loop behavior:

1. Inject an origin-based random candidate every
   `ea_injection_every` evaluations.
2. Otherwise sample a front member uniformly and deep-copy it.
3. Draw mutate/reorder using weights 0.9/0.1.
4. Apply exactly one local mutation, reorder one rule, or revert a saturated
   mutated rule.
5. If the move cannot change the rendering, retry another rule on the same
   parent, another parent, then an origin-based random sample.

Random search independently samples from the origin after the shared prefix.

`main_loop_budget` is a maximum number of completed post-initialization
evaluations. Total logical evaluations are `5 + main_loop_budget`. A high value
is used as a safety ceiling for final wall-time runs.

### `src/optimizer/initialization.py`

Initialization bundles make the common five-candidate prefix reusable. The
module:

- extracts a strict identity from `run_config.json`;
- serializes complete chromosomes and aggregate fitness;
- retains prompt-level initialization evidence;
- captures and restores search, mutator, and Torch RNG states;
- restores the evaluation cache;
- verifies canonical content and file hashes.

`scripts/setup/materialize_initialization_bundle.py` accepts only a validated
run with `main_loop_budget=0`.

### `src/optimizer/engine.py`

`ExperimentEngine` owns the evaluation seam:

1. Evaluate the original-rule baseline.
2. Build the full chromosome space from the mapped rules.
3. Load and verify an initialization bundle when supplied.
4. Dispatch to the selected search runner.
5. Render each candidate per task, use the temperature-zero signature cache,
   generate missing outputs, validate them, run Semgrep, and aggregate fitness.
6. Persist all artifacts and termination metadata.

The cache key is `(test_case_id, prompt_signature)`, where the signature hashes
the ordered `(rule_id, rule_text_hash)` sequence. A hit reuses generated code,
validation, Semgrep fitness, and latency evidence. Bundle reuse restores the
same entries present after the original five evaluations.

## Code-generation prompt contract

`src/evaluation/generation_contract.py` defines one fixed code-generation
contract. It uses the original concise generation instruction, explicitly
states the required Python or Java implementation language, and appends the
mapped coding guidelines when rules are present.

Every run records the exact template hash and fixed 4096-token output cap.
Search and replicate runs require the same contract hash recorded in the
qualified map.

## Output validation and Semgrep

`src/evaluation/output_validation.py` fixes the analysis language from the map,
selects one target-language artifact, rejects incomplete, vacuous, ambiguous,
or syntactically invalid output, and constructs deterministic Java wrappers
when a member or statement is not a full compilation unit.

`src/evaluation/semgrep_runner.py` batches samples into one Semgrep process,
maps findings back through wrapper line maps, filters wrapper-only findings,
and distinguishes failures affecting one generated task from scanner or
infrastructure failures.

`src/evaluation/fitness.py` computes raw findings, severity-weighted
diagnostics, per-task reductions, and whole-chromosome aggregation.

Failure policy:

- an invalid candidate output receives that task’s baseline score;
- an invalid baseline stops the search before any candidate is admitted;
- scanner configuration, process, malformed-result, or other infrastructure
  errors abort instead of being interpreted as zero findings.

## Output schema

### Search run directory

A search directory contains:

```text
run_config.json
search_summary.json
evaluations.jsonl
evaluation_manifest.json
intermediate/
  baseline.jsonl
  evaluation_NNNN.jsonl
mutated_rules/
  evaluation_NNNN/
    meta.json
    <mutated-rule>.md
archive_snapshots/                 # EA only
semgrep_debug/
  semgrep_debug.jsonl
evaluation_failures.jsonl         # only when failures were recorded
initialization_random_state.json  # only for a five-candidate bundle source
search_validation.json            # when validator --write is used
run.log
```

### `run_config.json`

Top-level `artifact_type` is `search_run_config`. The file records:

- CLI arguments and original `argv`;
- Git commit, hostname, and SLURM job ID;
- model ID, resolved local-model revision, Torch and Transformers versions;
- code-generation template hash;
- rules-map hash, selected-population fingerprint, rule-corpus hash, and
  qualification policy;
- initialization, main-loop, and total evaluation budgets;
- declared scheduler wall time and pre-timeout lead;
- mutators, archive/search parameters, seed, and objective direction;
- Semgrep version, local rules hash, file count, and upstream rules commit;
- initialization-bundle path and content hash when reused.

`git_commit_sha` identifies the checked-out commit. It does not attempt to infer
or police uncommitted files; submission readiness is checked before a run.

### `search_summary.json`

Top-level `artifact_type` is `search_summary`. It records:

- termination reason: `evaluation_budget_complete`, `wall_time_limit`, or
  `rate_limit`;
- completed initialization and main-loop evaluations;
- initialization, main-loop, and total elapsed time;
- original and best raw/weighted findings and invalid-output counts;
- actual code-generation LLM calls and tokens;
- actual mutation-LLM usage;
- logical usage contributed by a precomputed initialization;
- best chromosome, mutator statistics, and evaluation-cache statistics.

### `evaluations.jsonl`

Each line is one proposal attempt. Important fields:

| Field | Meaning |
|---|---|
| `evaluation_index` | Candidate index; unchanged across identity retries |
| `main_loop_iteration` | `null` for initialization, otherwise 1..B |
| `elapsed_main_loop_seconds` | Completion time of a main-loop evaluation |
| `attempt_index`, `attempt_in_evaluation` | Proposal accounting |
| `evaluation_consumed` | False for an identity/no-op retry |
| `strategy` | `ea` or `random_search` |
| `phase` | `initialization`, `ea`, `injection`, `origin_fallback`, or `random` |
| `initialization_source` | `precomputed_bundle` for reused initial candidates |
| `chromosome_id`, `parent_chromosome_id` | Content and lineage identifiers |
| `move_type`, `rule_id`, `mutation_chain` | Applied operator |
| `n_requested_changes`, `n_attempted_changes`, `n_effective_changes` | Sampler accounting |
| `f1`, `f2`, `f3` | Whole-chromosome objectives |
| `total_raw_findings`, `total_weighted_score` | Primary count and diagnostic |
| `num_invalid_prompts`, `failure_counts` | Conservative failure accounting |
| `accepted` | Archive result for EA; true for evaluated random samples |
| `n_prompts_rerun`, `n_prompts_reused` | Evaluation-cache accounting |
| `validation_metadata` | Per-rule quality measurements |

### Prompt-level evidence

`intermediate/baseline.jsonl` and `intermediate/evaluation_NNNN.jsonl` contain
one row per task:

- task, language, CWE, chromosome, mapped rules, and render order;
- raw and weighted findings, reductions, score source, and analysis status;
- output-validation decision and Java normalization/line map;
- generated code, finish reason, tokens, and latencies;
- source and analyzed-code hashes;
- evaluation-cache or initialization-bundle reuse markers.

### Archive snapshots and mutated rules

An archive snapshot has `artifact_type: pareto_archive_snapshot`, evaluation
index, capacity, origin, insertion/rejection counts, and full front
chromosomes. Each gene points to the exact Markdown allele under
`mutated_rules/evaluation_NNNN/`.

`meta.json` in each evaluated candidate directory records the chromosome,
parent, move, affected rule, mutation path, order priorities, changes,
acceptance, and validation metadata.

## Qualification and map artifacts

`scripts/experiments/run_qualification.py` performs only temperature-zero
search-population qualification. It writes:

- `run_config.json` with `artifact_type: qualification_run_config`;
- `qualification_manifest.json` with `artifact_type: qualification_manifest`;
- `qualification_generations.jsonl`, containing typed generation records;
- `intermediate/qualification_tasks.jsonl`, containing typed per-task results;
- scanner debug and explicit failure records;
- `qualification_validation.json` with
  `artifact_type: qualification_validation`.

`scripts/setup/materialize_retrieval_consensus.py` validates every retrieval
draw against its exact carrier and frozen retrieval contract, applies the
11-of-20 rule, and materializes deterministic model/language consensus maps.
`scripts/setup/materialize_eligible_population.py` validates and applies the
prospective task-eligibility manifest. `analyze_population_screening.py`
reconciles one complete 20-seed stochastic screening block across both models
and both no-rules/original-rules conditions. It records observed-finding,
all-valid-zero, and incomplete-zero tasks separately and materializes the
conservative qualification-input population.

`scripts/setup/materialize_qualified_search_maps.py` then verifies the four
model×language qualification runs and intersects their valid task IDs with the
tasks that had at least one observed stochastic Semgrep finding. It writes
model-specific search maps, language-specific no-rules maps, their supporting
provenance summaries, and a `qualified_population_manifest`. The resulting
population contains 203 Python and 126 Java tasks. Search and replicate runners
reject a map whose prompt contract, population policy, or fingerprint differs
from the requested run.

## Replicate artifacts

`scripts/experiments/run_replicates.py` evaluates one condition over multiple
seeds and writes:

- `run_config.json` with `artifact_type: replicate_run_config`;
- `replicates.jsonl`, one `replicate_evaluation` aggregate row per seed;
- `intermediate/<condition>_seedNNNN.jsonl`, one
  `replicate_task_evaluation` row per task;
- `replicate_summary.json` with `artifact_type: replicate_summary`;
- `replicate_validation.json` after validation.

Invalid outputs are missing rather than zero. Effects against a baseline are
computed per seed over the common valid-task subset. The run contract records
the exact Git commit, cached model revision, Torch/Transformers versions, prompt
contract, population, map, scanner, and any selected-rule override hash.

## Analysis

- `validate_search_run.py`: per-run search reconciliation and final-eligibility
  decision.
- `analyze_search_runs.py`: common wall-time endpoint, matched-seed EA/random
  inference stratified by model and language, plus secondary evaluation/time
  curves. Cross-model/language pooling is descriptive only.
- `validate_replicate_run.py`: per-run temperature>0 reconciliation.
- `analyze_replicates.py`: pooled per-seed effects and confidence intervals,
  written as reviewer-readable tables plus `replicate_analysis.json`.

## Extension points

To add a mutator, subclass `Mutator`, register it in
`src/mutation/__init__.py`, and add an adherence check in `quality.py`.

To add an objective, extend `AggregatedFitness`, the objective mapping in
`search.py`, archive dominance, persistence, validation, and analysis together.

To add a backend, implement `LLMBackend.generate`, register it in
`src/llm_backends/__init__.py`, and add the backend/model provenance fields
needed for exact reruns.
