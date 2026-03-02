# Architecture

## System Components

### Core Framework (`src/`)

#### 1. Evaluation Module (`src/evaluation/`)

**Rule Mapping System**
- `rule_mapping.py`: Per-prompt rule retrieval and management
  - `RuleMappingIndex`: Hash-based O(1) prompt→rules lookup
  - `RuleLoader`: Caches and combines multiple rule files
  - `PromptWithRules`: Test prompts enriched with their specific rules

**Vulnerability Analysis**
- `semgrep_runner.py`: Static analysis wrapper for Semgrep
- `fitness.py`: Fitness calculation from vulnerability findings
  - Strategies: RAW_COUNT, SEVERITY_WEIGHTED, UNIQUE_RULES

**Dataset Integration**
- `dataset_config.py`: CyberSecEval dataset loader and selector
- Supports filtering by language, CWE, test case ID

#### 2. Optimization Module (`src/optimizer/`)

**Hill Climbing Algorithm** (`hill_climber.py`)
- `HillClimber`: Main optimization loop
  - `optimize()`: Single-rule optimization
  - `optimize_per_prompt_rules()`: Per-prompt rule optimization
- Tracks fitness across iterations
- Early stopping when no improvement
- Rate limit error handling with graceful recovery

#### 3. Mutation Module (`src/mutation/`)

**Mutation Operators** (`rule_based.py`)
- `FluffMutator`: Adds bureaucratic noise and weakens imperatives
  - Random prefix/suffix injection
  - Verb weakening (MUST → "should ideally")
- `VerbWeakeningMutator`: Standalone verb weakening
- `StructuralMutator`: Document restructuring (experimental)

**Base Classes** (`base.py`)
- `Mutator`: Abstract base with RNG seeding
- `MutationResult`: Tracks original, mutated text, and changes

#### 4. LLM Backend Module (`src/llm_backends/`)

**API Integrations**
- `groq_backend.py`: Groq API (Llama models)
- `base.py`: Abstract `LLMBackend` interface
- Rate limit detection and error propagation

---

## Data Flow

```
┌──────────────────┐
│  Test Prompts    │ (CyberSecEval Dataset)
│  + CWE Labels    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Rule Mapping    │ (AI agent selects relevant rules)
│  prompt → rules  │ 
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Rule Loader     │ (Load and combine rule files)
│  Combine Rules   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Mutator        │ (Apply adversarial transformations)
│   - Fluff        │
│   - Weakening    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  LLM Backend     │ (Generate code with mutated rules)
│  System Prompt   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Semgrep         │ (Static analysis for vulnerabilities)
│  Security Rules  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Fitness Calc    │ (Weighted vulnerability count)
│  Higher = Worse  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Hill Climber    │ (Keep mutation if fitness increased)
│  Iterate         │
└──────────────────┘
```

---

## Configuration System

### Hierarchy

1. **Dataset Config** (`DatasetConfig`)
   - Which dataset backend to use
   - Default language and CWE filters

2. **Selection Criteria** (`SelectionCriteria`)
   - Test case IDs or JSON file
   - Language/CWE filters
   - Limit and shuffling

3. **Hill Climb Config** (`HillClimbConfig`)
   - Max iterations
   - Fitness strategy
   - Early stopping threshold
   - Output directory

4. **LLM Config** (implicit in backend)
   - Model selection
   - Temperature, max tokens
   - API credentials

### Example Configuration

```python
from src.optimizer import HillClimber, HillClimbConfig
from src.mutation import FluffMutator
from src.llm_backends import GroqBackend, LLMConfig
from src.evaluation import FitnessStrategy

# Configure optimization
config = HillClimbConfig(
    max_iterations=10,
    fitness_strategy=FitnessStrategy.SEVERITY_WEIGHTED,
    early_stop_no_improvement=3,
    output_dir="results/experiment_001",
)

# Initialize components
llm = GroqBackend(LLMConfig(model="llama-3.3-70b-versatile"))
mutator = FluffMutator(seed=42, weaken_verbs=True)
climber = HillClimber(llm, mutator, config)
```

---

## Output Structure

### Directory Layout

```
output_dir/
├── mutated_rules/
│   └── iter{N}_tc{ID}_rules{COUNT}.md
├── intermediate_results/
│   └── intermediate_{phase}_{idx}_{timestamp}.json
├── per_prompt_rules_results_{timestamp}.json
└── hillclimb_summary_{timestamp}.json
```

### File Naming Convention

**Mutated Rules:**
- `iter1_tc3_rules2.md` = Iteration 1, Test Case 3, 2 rules combined

**Intermediate Results:**
- `intermediate_baseline_000_20260302_115315.json` = Baseline phase, index 0
- `intermediate_mutation_001_20260302_115442.json` = Mutation phase, index 1

---

## Extension Points

### Adding New Mutation Strategies

1. Inherit from `Mutator` base class
2. Implement `mutate(text: str) -> MutationResult`
3. Return detailed `changes` list for traceability

```python
from src.mutation import Mutator, MutationResult

class MyMutator(Mutator):
    @property
    def name(self) -> str:
        return "my_mutation"
    
    def mutate(self, text: str) -> MutationResult:
        # Apply transformation
        mutated = transform(text)
        return MutationResult(
            original=text,
            mutated=mutated,
            mutation_type=self.name,
            changes=["Applied X transformation"],
        )
```

### Adding New LLM Backends

1. Inherit from `LLMBackend`
2. Implement `generate()` and `validate_connection()`
3. Handle rate limits consistently

```python
from src.llm_backends import LLMBackend, LLMResponse

class MyBackend(LLMBackend):
    def generate(self, system: str, messages: list) -> LLMResponse:
        # API call logic
        return LLMResponse(
            content=result,
            latency_ms=elapsed,
        )
```

### Custom Fitness Functions

Fitness strategies are defined in `src/evaluation/fitness.py`:

```python
class FitnessStrategy(Enum):
    RAW_COUNT = auto()           # Total finding count
    SEVERITY_WEIGHTED = auto()    # ERROR=3, WARNING=1
    UNIQUE_RULES = auto()         # Distinct check_ids triggered
```

Add new strategies by extending the enum and updating `calculate_fitness()`.

---

## Dependencies

### Core Requirements
- Python 3.10+
- Semgrep (static analysis)
- HuggingFace Datasets (CyberSecEval)

### API Keys
- Groq API: `GROQ_API_KEY` environment variable
- (Optional) OpenAI or Anthropic API for rule mapping generation

### Python Packages
See `requirements.txt` for full list. Key dependencies:
- `datasets`: HuggingFace dataset loading
- `semgrep`: Security analysis
- `groq`: LLM API client
- `pydantic`: Config validation
