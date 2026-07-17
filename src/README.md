# src/ Developer Guide

This directory contains the core SBST framework modules for mutation-based security testing.

## Module Structure

```
src/
├── __init__.py
├── llm_backends/           # Claude, OpenAI, and DelftBlue-local providers
│   ├── base.py             # LLMBackend ABC, LLMConfig, LLMResponse
│   ├── claude_backend.py   # Anthropic API implementation
│   ├── openai_backend.py   # OpenAI API implementation
│   └── delftblue_local_backend.py  # Local HF inference (FP16 / 4-bit)
├── mutation/               # Rule mutation strategies
│   ├── base.py             # Mutator ABC, MutationResult
│   └── rule_based.py       # VerbWeakening, SynonymReplacement, SectionReorder, etc.
├── evaluation/             # Code security analysis
│   ├── semgrep_runner.py   # Semgrep integration
│   ├── fitness.py          # Fitness calculation
│   └── rule_mapping.py     # Per-prompt rule retrieval
└── optimizer/              # Search over whole rule-set chromosomes
    ├── chromosome.py       # RuleSetChromosome/Space + ChromosomeArchive (Pareto)
    ├── search.py           # run_ea (1+1 EA) + run_random_search
    └── engine.py           # ExperimentEngine + SearchConfig (drives a run)
```

## Using as a Library

### Set Up LLM Backend

```python
from src.llm_backends import create_claude_backend

# Reads ANTHROPIC_API_KEY from the environment.
backend = create_claude_backend(model="claude-haiku-4-5")

# DelftBlue local model (A100) - FP16 default
from src.llm_backends import create_delftblue_local_backend

local_backend = create_delftblue_local_backend(
    model="Qwen/Qwen2.5-Coder-32B-Instruct",
    quantization="fp16",  # or "4bit"
)
```

### Create and Use a Mutator

```python
from src.mutation import SynonymReplacementMutator

mutator = SynonymReplacementMutator(seed=42)
result = mutator.mutate(rule_text="NEVER use MD5 for hashing...")
print(result.mutated)
print(result.changes)  # List of mutations applied
```

### Run a Search Experiment

```bash
# The CLI constructs ExperimentEngine, loads the rule map, and persists the
# schema-version-4 run artifacts. Validation is required because it feeds f2.
python scripts/experiments/run_experiment.py \
  --backend claude --optimizer ea --enable-validation \
  --rules-map rule_maps/map_qwen32b_python_java.json \
  --n-cases 2 --iterations 5 --languages python \
  --mutators synonym_replacement verb_weakening \
  --output-dir experiments/results/library_guide_smoke
```

For programmatic use, the public optimizer types are `ExperimentEngine` and
`SearchConfig`; both strategies are dispatched by `ExperimentEngine.run_search()`.
See [`optimizer/README.md`](optimizer/README.md) for their algorithm contract.

## Per-Prompt Rule Mapping

For production use, leverage automatic rule retrieval:

```python
from src.evaluation import RuleMappingIndex, enrich_prompts_with_rules

# Load pre-computed rule mapping
mapping_index = RuleMappingIndex.load("path/to/rule_mapping.json")

# Enrich test prompts with relevant rules
enriched = enrich_prompts_with_rules(
    test_prompts,
    mapping_index,
)

# enriched[i].rules contains rules specifically for prompt[i]
```

## Key Data Structures

- **`LLMResponse`**: Code generation output with latency tracking
- **`MutationResult`**: Mutated rule text + list of changes applied
- **`FitnessResult`**: Vulnerability counts (raw_count, weighted_score, error_count, warning_count)
- **`TestPrompt`**: Security task (prompt, language, CWE)
- **`RuleSetChromosome`**: Whole rule-set genotype (mutated rule alleles + order priorities)
- **`ChromosomeArchive`**: Bounded Pareto front over f1/f2/f3 (EA only)
- **`SearchResult`**: Best chromosome, fitness trajectory, and run totals

## Configuration

See [ARCHITECTURE.md](../ARCHITECTURE.md) for detailed config hierarchy and extension points.

## Full Documentation

For complete details on:
- **Project overview & research question**: [../README.md](../README.md)
- **Architecture & system design**: [../ARCHITECTURE.md](../ARCHITECTURE.md)
- **Running experiments & troubleshooting**: [../WORKFLOW.md](../WORKFLOW.md)
| `verb_weakening` | MUST→should, NEVER→avoid |
| `structural` | Shuffle sections, remove headers |
| `composite` | Combine multiple strategies |
