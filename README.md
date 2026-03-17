# CodeGuard SBST Framework

**Search-Based Software Testing for Security Coding Guidelines**

A research framework for adversarially testing LLM security instruction adherence through mutation-based optimization.

---

## Overview

This project implements a Search-Based Software Testing (SBST) approach to evaluate the robustness of security coding guidelines when used as system prompts for code-generating LLMs.

### Research Question

**How resilient are security instructions to adversarial modifications?**

We investigate whether weakening, obfuscating, or adding noise to security guidelines causes LLMs to generate more vulnerable code. This helps identify fragile instruction patterns and improve guideline robustness.

### Approach

1. **Select** test prompts from security benchmark datasets (CyberSecEval)
2. **Map** relevant security rules to each prompt using AI-based retrieval
3. **Mutate** rules with adversarial transformations (noise injection, verb weakening)
4. **Generate** code using LLM with original vs. mutated rules
5. **Analyze** vulnerabilities using static analysis (Semgrep)
6. **Optimize** through hill climbing to find worst-case mutations

The framework tracks fitness scores (vulnerability counts) to quantify instruction robustness.

---

## Quick Start

### Installation

```bash
# Clone repository
git clone <repo-url>
cd Thesis-rules-codeguard

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set API key
export GROQ_API_KEY="your_key_here"
```

### Running an Experiment

```bash
python scripts/experiments/run_with_rules_map.py \
    --interesting-cases data/interesting_cases.json \
    --rules-map data/rule_mapping.json \
    --n-cases 10 \
    --model llama-3.3-70b-versatile \
    --iterations 5 \
    --output-dir results/experiment_001 \
    --seed 42
```

**Key Parameters:**
- `--n-cases`: Number of test prompts to evaluate
- `--iterations`: Hill climbing iterations (more = deeper search)
- `--model`: LLM model identifier
- `--seed`: Random seed for reproducibility

See [WORKFLOW.md](WORKFLOW.md) for detailed experiment patterns and troubleshooting.

---

## Architecture

### Core Components

| Component | Purpose |
|-----------|---------|
| **Rule Mapping** | Links test prompts to relevant security rules |
| **Hill Climber** | Optimization algorithm to find worst-case mutations |
| **Mutators** | Apply adversarial transformations to rules |
| **LLM Backend** | Code generation API (Groq, OpenAI) |
| **Vulnerability Scanner** | Static analysis via Semgrep |

### Data Flow

```
Test Prompts → Rule Mapping → Rule Loading → Mutation 
    ↓
LLM Code Generation → Semgrep Analysis → Fitness Calculation
    ↓
Hill Climbing (iterate if fitness improves)
```

For detailed architecture and extension points, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Project Structure

```
├── src/                      # Core framework code
│   ├── evaluation/           # Rule mapping, fitness, Semgrep
│   ├── llm_backends/         # API integrations
│   ├── mutation/             # Mutation operators
│   └── optimizer/            # Hill climbing algorithm
├── scripts/                  # Experiment entry points
├── project-codeguard/        # Security rule library (23 rules)
├── results/                  # Experiment outputs
├── ARCHITECTURE.md           # Technical details
├── WORKFLOW.md               # How to run experiments
└── README.md                 # This file
```

---

## Key Features

### Per-Prompt Rule Mapping

Instead of using a single rule for all tests, the system:
- Uses AI agent to select relevant rules for each prompt
- Loads and combines multiple rules per test case
- Tracks exact rule usage for traceability

### Incremental Result Saving

Experiments save results after each prompt evaluation:
- Survives API rate limits mid-experiment
- Each result includes generated code, fitness score, and rule references
- Mutated rules saved to files for reproducibility

### Rate Limit Handling

Graceful handling of API quota limits:
- Detects rate limit errors (429/413 codes)
- Saves all progress before stopping
- Provides resume guidance

---

## Dataset & Rules

### CyberSecEval

- **Source**: Meta AI (via HuggingFace)
- **Content**: 12,000+ code generation prompts with known vulnerability patterns
- **Languages**: Python, C, JavaScript, PHP, SQL
- **Coverage**: 75+ CWE types (injection, memory safety, crypto, etc.)

### CodeGuard Rules

23 security guidelines covering:
- Input validation & injection prevention
- Memory safety (C/C++)
- Cryptography & authentication
- API security & logging
- Supply chain & DevOps practices

Located in [`project-codeguard/skills/software-security/rules/`](project-codeguard/skills/software-security/rules)

---

## Mutation Strategies

### Current Implementation

**FluffMutator:**
- Adds bureaucratic prefix/suffix (de-prioritizes security)
- Weakens imperative verbs: MUST → "should ideally", NEVER → "try to avoid"
- Injects distracting administrative notes

**Effect:** Tests whether LLMs can extract security requirements from noisy instructions.

### Future Strategies

- Section reordering (critical content at end)
- Contradictory instructions
- Misleading code examples
- Complexity injection

---

## Results & Analysis

### Fitness Metric

```
fitness = Σ (severity_weight × finding_count)
  where severity_weight = { ERROR: 3, WARNING: 1, INFO: 0 }
```

Higher fitness = more vulnerabilities = weaker rule effectiveness

### Output Structure

```
results/experiment_001/
├── mutated_rules/            # Saved mutated rule files
├── intermediate_results/     # Per-prompt evaluation JSONs
├── hillclimb_summary_*.json  # Experiment summary
└── per_prompt_rules_results_*.json
```

Each intermediate result includes:
- Test case metadata (language, CWE)
- Original rule IDs and mutated rule file reference
- Generated code
- Fitness scores and Semgrep findings

---

## Development

### Task Management

This project uses [beads](https://github.com/BeadsLand/beads) for issue tracking:

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd list               # List all issues
```
---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design, components, extension points
- **[WORKFLOW.md](WORKFLOW.md)** - How to run experiments, interpret results
- **[AGENTS.md](AGENTS.md)** - AI agent development instructions

