# Source package guide

The source tree implements rule retrieval support, rule-set mutation, code
generation, evaluation, and the final search procedures.

```text
src/
├── llm_backends/       model-provider adapters and response accounting
├── mutation/           local controlled transformations of mapped rules
├── evaluation/         output validation, Semgrep execution, fitness, mapping
└── optimizer/          chromosomes, archive, initialization, search, engine
```

## Search architecture

`optimizer/engine.py` orchestrates a run. `optimizer/search.py` contains the
supervisor-approved EA and matched random search. Both begin with the same five
origin-based random candidates, restored from an identity-checked
initialization bundle in final paired runs. The EA then samples parents from
its bounded nondominated front; random search continues sampling from the
origin. The origin remains the no-change evaluation reference but is not an EA
parent or archive-admission threshold.

Each search evaluation operates only on rules mapped to at least one selected
task. Mutations are one local transformation at a time; reorder moves change a
single rule priority.

## Running the entrypoint

```bash
.venv/bin/python scripts/experiments/run_experiment.py \
  --backend claude \
  --dry-run \
  --optimizer ea \
  --enable-validation \
  --rules-map rule_maps/qualified/final_search_map_qwen_python.json \
  --n-cases 2 \
  --main-loop-budget 5 \
  --languages python \
  --mutators synonym_replacement verb_weakening \
  --output-dir experiments/results/library_guide_smoke
```

The final DelftBlue launchers use the approved common wall-time limit and a
deliberately high main-loop safety ceiling. Final paired runs additionally pass
`--initialization-bundle`.

## Public data structures

- `LLMResponse`: generated text, usage, and latency.
- `MutationResult`: one controlled rule transformation and its metadata.
- `FitnessResult`: raw finding count plus diagnostic severity and validity
  information.
- `TestPrompt`: one security-code-generation task.
- `RuleSetChromosome`: complete mapped-rule genotype and rule priorities.
- `ChromosomeArchive`: bounded nondominated EA front.
- `SearchResult`: final incumbent, evaluation records, completion state, and
  resource accounting.

See [optimizer/README.md](optimizer/README.md) for the exact algorithm and
[../WORKFLOW.md](../WORKFLOW.md) for the end-to-end execution procedure.
