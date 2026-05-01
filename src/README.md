# src/ Developer Guide

This directory contains the core SBST framework modules for mutation-based security testing.

## Module Structure

```
src/
├── __init__.py
├── llm_backends/           # LLM provider abstractions (Groq, OpenRouter, DelftBlue local)
│   ├── base.py             # LLMBackend ABC, LLMConfig, LLMResponse
│   ├── groq_backend.py     # Groq implementation
│   ├── openrouter_backend.py  # OpenRouter fallback
│   └── delftblue_local_backend.py  # Local HF inference (FP16 / 4-bit)
├── mutation/               # Rule mutation strategies
│   ├── base.py             # Mutator ABC, MutationResult
│   └── rule_based.py       # VerbWeakening, SynonymReplacement, SectionReorder, etc.
├── evaluation/             # Code security analysis
│   ├── semgrep_runner.py   # Semgrep integration
│   ├── fitness.py          # Fitness calculation
│   └── rule_mapping.py     # Per-prompt rule retrieval
└── optimizer/              # Search algorithms
    └── hill_climber.py     # HillClimber implementation
```

## Using as a Library

### Set Up LLM Backend

```python
from src.llm_backends import GroqBackend, LLMConfig

backend = GroqBackend(LLMConfig(
    model="llama-3.3-70b-versatile",
    api_key="your_key_here",
))

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

### Run Hill Climbing Optimization

```python
from src.optimizer import HillClimber, HillClimbConfig
from src.mutation import create_mutator_pool

config = HillClimbConfig(max_iterations=10)
pool = create_mutator_pool(["synonym_replacement", "verb_weakening"])

climber = HillClimber(backend, pool, config)
result = climber.optimize_per_prompt_rules(prompts_with_rules=prompts_with_rules)
```

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
- **`HillClimbResult`**: Optimization outcome (best mutation, fitness trajectory)

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
