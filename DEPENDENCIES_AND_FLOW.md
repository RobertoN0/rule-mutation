# Dependencies and Pipeline Flow

This file is the authoritative answer to four questions:

1. What does `uv` actually install for this project?
2. Which packages are needed for **local API-based** execution vs **DelftBlue (GPU)** execution?
3. Where does each package come into play during a single hill-climbing iteration?
4. How does the pipeline's runtime behaviour differ between those two execution modes?

Use it as a checklist when modifying [`pyproject.toml`](pyproject.toml) or when porting
the workspace to a new machine (your local box, a supervisor's laptop, DelftBlue).

---

## 1. Direct dependencies (what `uv` resolves from `pyproject.toml`)

`uv` resolves these 17 direct dependencies (and ~140 transitive packages they pull
in) into [`uv.lock`](uv.lock). Numbers in parentheses are the version constraints
from [`pyproject.toml`](pyproject.toml); they exist either to express a known-good
range or to work around an upstream packaging issue.

### Core (always installed via `uv sync`)

| Package | Constraint | Used for | Why this constraint |
|---|---|---|---|
| `openai` | `>=1.50,<2` | OpenAI Chat Completions backend; also the LangChain/LangGraph retrieval scripts | `>=1.50` for the modern client (`OpenAI()` not `openai.ChatCompletion`); `<2` so a breaking 2.x release doesn't auto-upgrade |
| `anthropic` | `>=0.40,<1` | Claude Messages backend (the cheap replication path) | `>=0.40` for stable Messages API; `<1` to lock the SDK shape we coded against |
| `semgrep` | `>=1.85,<2` | All static-analysis runs | `>=1.85` for batch JSON output stability; `<2` insulates against a major rule-format change |
| `datasets` | `>=3.0,<5` | Loading CyberSecEval prompts and HF dataset interfaces | `>=3.0` is the modern arrow-backed API; `<5` is a soft upper bound |
| `pandas` | `>=2.0,<3` | Dataset wrangling, analysis helpers | `>=2.0` for `pd.DataFrame.convert_dtypes()`; `<3` for safety |
| `pyyaml` | `>=6.0,<7` | Parsing CodeGuard rule frontmatter, `metadata.json`, SLURM configs | Stable API; `<7` only because PyYAML 7 doesn't exist yet (defensive) |
| `python-dotenv` | `>=1.0,<2` | Loading `.env` so `ANTHROPIC_API_KEY` etc. flow into `os.environ` at startup | The `load_dotenv()` import path we use |
| `pydantic` | `>=2.0,<3` | Schema validation (mostly transitive — pulled by `mcp` and `anthropic`, but we depend on it directly so it's pinned) | Pydantic 1→2 is a hard ABI break; the codebase uses v2 only |
| `torch` | `>=2.0,<3` | Backbone of `sentence-transformers` (SBERT) and the DelftBlue HF backend | **Explicit direct dep** even though it's also transitive — `[tool.uv.sources]` only applies to direct deps. Without this line, `sentence-transformers` would pull the default CUDA wheel from PyPI (~8 GB) on Linux. With it, we get the ~3 GB CPU wheel by default. DelftBlue swaps to CUDA after `uv sync` (see §5.4) |
| `sentence-transformers` | `>=2.2` | SBERT semantic-similarity gate in [`MutationQualityValidator`](src/mutation/quality.py); model is `all-mpnet-base-v2` | `>=2.2` for the modern `SentenceTransformer` constructor; no upper bound — pinning would force lockfile churn on every release |
| `textstat` | `>=0.7` | Flesch-Kincaid readability (Criterion 5 of the quality validator, informational only) | Stable API; no upper bound |
| `nlpaug` | `>=1.1.11` | `SynonymReplacementMutator`, `AddRandomWordMutator` | `>=1.1.11` ships the modern `nlpaug.augmenter.word.*` modules |
| `nltk` | `>=3.8` | WordNet corpus that `nlpaug.SynonymAug` reads; we pre-fetch the corpora at script start to silence the noisy defensive `nltk.download()` calls during runs | `>=3.8` for `quiet=True` on `download()` |
| `codebleu` | `==0.7.0` | `code_divergence` secondary fitness signal (CodeBLEU between baseline code and mutated-rule-generated code) | Hard pin — codebleu 0.7 bundles a specific tree-sitter version internally and bumping it has historically broken the per-language adapters. **DO NOT** upgrade without re-running CodeBLEU smoke tests |
| `tree-sitter-c` | `<0.22` | C grammar that codebleu uses to extract AST for the AST-match score | **Correctness pin** — codebleu 0.7 itself wants `tree-sitter<0.23` (transitively), and its per-language grammar adapters fail with a misleading "codebleu not installed" message when the grammar version doesn't match the underlying tree-sitter. `<0.22` keeps everything compatible with the 0.22.x line codebleu pulls in |
| `tree-sitter-python` | `<0.22` | Same as above, Python grammar | Same reason |
| `tree-sitter-java` | `<0.22` | Same as above, Java grammar | Same reason |

### Optional extras

| Extra | Packages | Used for | Required for what |
|---|---|---|---|
| `gpu` | `accelerate>=0.34,<2`, `bitsandbytes>=0.43,<1` | 4-bit / fp16 quantization in `DelftBlueLocalBackend` | DelftBlue (and any other CUDA host running the local HF backend). Skip on CPU-only machines. |
| `retrieval` | `langchain>=0.3,<0.4`, `langchain-openai>=0.3,<0.4`, `langgraph>=0.2,<0.4`, `mcp>=1.0,<2`, `nest-asyncio>=1.6,<2` | The Anthropic / local-HF rule-retrieval scripts that build `retrieval_map_*.json` from raw CodeGuard rules | Only needed when **re-building** the retrieval map. Replicators using a pre-computed map skip this entirely. |
| `dev` | `pytest>=8`, `ruff>=0.6` | Test runner, linter | Development only. CI and DelftBlue runs don't need it. |

### Transitive packages (not pinned by us)

`uv` pulls ~140 transitive packages (`numpy`, `huggingface-hub`, `tokenizers`,
`safetensors`, `httpx`, `ruamel.yaml`, `tqdm`, `cryptography`, etc.). They are
fully captured in [`uv.lock`](uv.lock) which is the bit-exact reproducibility source.
Run `uv export --format requirements-txt` if you need a flat `pip`-compatible view.

---

## 2. Dependency matrix — API-based vs DelftBlue execution

The same project supports two end-to-end paths. The table below says, for each
direct dep, whether it's **required**, **recommended**, **optional**, or **not used**.

| Dep | API (Claude/OpenAI) on a CPU laptop | DelftBlue (Qwen-32B on A100) | Comment |
|---|:-:|:-:|---|
| `openai` | ✓ required | ⚠️ recommended | API path: backend SDK. DelftBlue: retrieval helpers and ad-hoc smoke tests |
| `anthropic` | ✓ required | ⚠️ recommended | Same logic |
| `semgrep` | ✓ required | ✓ required | Core static-analysis step in every iteration |
| `datasets`, `pandas` | ✓ required | ✓ required | Prompt/dataset loading is identical |
| `pyyaml`, `python-dotenv`, `pydantic` | ✓ required | ✓ required | Config/IO |
| `torch` (CPU) | ✓ required | ✗ replaced | API path uses the CPU wheel pinned in `[tool.uv.sources]`. DelftBlue reinstalls torch from the CUDA index after `uv sync --extra gpu` |
| `torch` (CUDA) | ✗ not used | ✓ required | Installed via the manual `uv pip install --reinstall` step on DelftBlue |
| `sentence-transformers` | ✓ required | ✓ required | SBERT validator gate runs in both paths |
| `textstat` | ✓ required | ✓ required | Quality criterion |
| `nlpaug`, `nltk` | ⚠️ required *if* using function-based mutators | ⚠️ required *if* using function-based mutators | Only `synonym_replacement` and `add_random_word` need them. If you exclusively use LLM mutators (`paraphrase`, `voice_change`, `negation_injection`) you could in principle skip them — but they're cheap and stay in core |
| `codebleu`, `tree-sitter-*` | ✓ required | ✓ required | Code-divergence fitness signal in every iteration |
| `accelerate`, `bitsandbytes` (`gpu` extra) | ✗ not used | ✓ required | GPU quantization only |
| `langchain*`, `mcp`, `nest-asyncio` (`retrieval` extra) | ⚠️ optional | ⚠️ optional | Only required when **building** a new `retrieval_map_*.json`. Pre-computed maps in [`pipeline_breakdown/rule_retrieval_output/`](pipeline_breakdown/rule_retrieval_output/) let you skip this |
| `pytest`, `ruff` (`dev` extra) | ⚠️ optional | ⚠️ optional | Local dev / CI |

**Minimum install per scenario:**

```bash
# Scenario A: pure API-based replication (supervisor on a laptop)
uv sync                              # 1.8 GB; can run --backend claude/openai end-to-end
                                     # with a pre-computed retrieval map

# Scenario B: API replication + you want to rebuild the retrieval map
uv sync --extra retrieval            # adds langchain*/langgraph/mcp

# Scenario C: local development (you, with tests)
uv sync --extra retrieval --extra dev

# Scenario D: DelftBlue
uv sync --extra gpu --extra retrieval --extra dev
uv pip install --reinstall \
    --index-url https://download.pytorch.org/whl/cu126 torch
# (the reinstall step swaps the CPU torch we just pinned for the matching CUDA wheel)
```

---

## 3. Pipeline workflow — where each dependency activates

Below is one full iteration of `scripts/experiments/run_with_rules_map.py`,
annotated with the dep that powers each step.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 0  — Process startup                                                   │
│    • argparse                                              [stdlib]          │
│    • warnings.filterwarnings("ignore", SyntaxWarning, nlpaug)  [stdlib]      │
│    • nltk.download(quiet=True)                              [nltk]           │
│    • load_dotenv(".env")                                   [python-dotenv]   │
│    • Install stdout/stderr tee → run.log                    [stdlib]         │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 1  — Load CodeGuard rules + retrieval map                              │
│    • Read rule files from project-codeguard/skills/.../rules/  [pyyaml]      │
│    • Parse YAML frontmatter, prose body                     [pyyaml]         │
│    • Load retrieval_map_*.json                             [stdlib json]     │
│    • Build PromptWithRules objects                          [pydantic]       │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 2  — Initialize LLM backend                                            │
│    --backend claude       → ClaudeBackend(LLMConfig)        [anthropic]      │
│    --backend openai       → OpenAIBackend(LLMConfig)        [openai]         │
│    --backend delftblue    → DelftBlueLocalBackend(LLMConfig) [torch, sentence│
│                              loads Qwen-32B from HF cache    -transformers,  │
│                              quantizes to fp16 or 4-bit       accelerate,    │
│                                                                bitsandbytes] │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 3  — Build mutator pool                                                │
│    • SynonymReplacementMutator                              [nlpaug, nltk]   │
│    • AddRandomWordMutator                                   [nlpaug, nltk]   │
│    • VerbWeakeningMutator, SectionReorderMutator           [pure python]    │
│    • NegationInjection / VoiceChange / Paraphrase           [the LLM backend │
│                                                              chosen in S2]   │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼ (Optional, only if `--enable-validation`)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 4  — Quality validator setup                                           │
│    • Load all-mpnet-base-v2 SBERT model    [sentence-transformers, torch]    │
│    • Set up Flesch-Kincaid scorer           [textstat]                       │
│    • (Optional, delftblue only) perplexity gate using the loaded Qwen-32B    │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  STEP 5  — Iteration loop (HillClimber.optimize_per_prompt_rules)            ║
║                                                                              ║
║  Per iteration, per rule, per prompt:                                        ║
║                                                                              ║
║  5a. Apply mutation                                                          ║
║      • function-based            [nlpaug, nltk]                              ║
║      • LLM-based                  [the active backend]                       ║
║                                                                              ║
║  5b. Validate mutation quality                                               ║
║      • SBERT cosine ≥ 0.75       [sentence-transformers, torch]              ║
║      • Inline-code retention      [stdlib re]                                 ║
║      • Keyword retention ≥ 0.70   [stdlib]                                    ║
║      • (Optional) perplexity gate [torch + the Qwen model on delftblue only] ║
║                                                                              ║
║  5c. Generate code on baseline + mutated rule text                           ║
║      • API path                   [anthropic or openai]                      ║
║      • DelftBlue path              [torch + transformers + Qwen weights]     ║
║                                                                              ║
║  5d. Semgrep batch scan on every generated code sample                       ║
║      • semgrep --config p/security-audit  [semgrep]                          ║
║      • (DelftBlue: --config /scratch/$USER/semgrep-rules/security-audit)     ║
║                                                                              ║
║  5e. Compute fitness                                                         ║
║      • SEVERITY_WEIGHTED Semgrep score       [stdlib]                        ║
║      • CodeBLEU(baseline_code, mutated_code) [codebleu + tree-sitter-{c,    ║
║                                                python,java}]                  ║
║                                                                              ║
║  5f. Accept/reject + update Pareto archive    [stdlib dataclasses]           ║
║      Restart triggers, depth tracker, mutator pool stats — all pure Python.  ║
║                                                                              ║
║  5g. Persist intermediate result               [stdlib json]                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 6  — Summary writers                                                   │
│    • hillclimb_summary_*.json     [stdlib json]                              │
│    • hillclimb_per_rule_*.json     [stdlib json]                              │
│    • per_prompt_rules_results_*.json [stdlib json]                            │
│    • rerun.sh                      [stdlib]                                  │
│    • run.log finalised by atexit hook  [stdlib]                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Where the `retrieval` extra fits

The `retrieval` extra (`langchain`, `langchain-openai`, `langgraph`, `mcp`,
`nest-asyncio`) is used only by these scripts, which produce the JSONs consumed
in **STEP 1**:

- [`pipeline_breakdown/rule_retrieval_mapping_local.py`](pipeline_breakdown/rule_retrieval_mapping_local.py) — local-HF variant
- [`pipeline_breakdown/rule_retrieval_mapping_anthropic.py`](pipeline_breakdown/rule_retrieval_mapping_anthropic.py) — Anthropic API variant

If you reuse a pre-computed `retrieval_map_*.json` you never invoke either script
and the `retrieval` extra is dead weight.

---

## 4. Behavioural diff — API mode vs DelftBlue mode

The same pipeline runs in both modes. The differences are operational (where
files come from, where compute happens) rather than algorithmic.

| Aspect | API mode (local laptop / cloud VM) | DelftBlue mode (HPC) |
|---|---|---|
| **Internet on the compute box** | YES | NO on compute nodes; YES on login node |
| **LLM inference** | Anthropic / OpenAI HTTPS calls per LLM step | Local Qwen-2.5-Coder-32B-Instruct via `DelftBlueLocalBackend`, weights resident on `/scratch/$USER/models/` |
| **HF model cache** | `~/.cache/huggingface/` populated on demand at first SBERT/tokenizer use | `HF_HOME=/scratch/$USER/models` set in SLURM scripts; **`HF_HUB_OFFLINE=1` forced** so no network calls leak |
| **Semgrep rules** | Default to `p/security-audit` (semgrep.dev online registry) when `SEMGREP_RULESET` is unset | SLURM scripts override with `SEMGREP_RULESET=/scratch/$USER/semgrep-rules/security-audit` (offline copy) |
| **`torch` wheel** | CPU wheel from `https://download.pytorch.org/whl/cpu` (pinned via `[tool.uv.sources]`) | CUDA wheel from `https://download.pytorch.org/whl/cu126` (manually installed after `uv sync --extra gpu`) |
| **GPU quantization** | not used (no CUDA) | fp16 default; optionally 4-bit via `bitsandbytes` |
| **`accelerate`, `bitsandbytes`** | not installed (skip `--extra gpu`) | installed (`uv sync --extra gpu`) |
| **Perplexity gate** | unavailable (the validator's `enable_perplexity` flag becomes a no-op because API providers don't expose token-level logprobs over arbitrary input) | available on `delftblue` backend |
| **Where the run is launched** | `uv run python scripts/experiments/run_with_rules_map.py …` directly | `sbatch scripts/slurm/slurm_*.sh` (or `srun` for an interactive smoke) |
| **Logs** | `<output_dir>/run.log` via the in-process stdout tee | SLURM `%j.out` / `%j.err` in `logs/`; analysis report later in the output dir |
| **Output dir convention** | user-chosen; defaults to `experiments/results/` | `experiments/results/job{SLURM_JOB_ID}_{tag}_{MMDD}/` |
| **Submission cost model** | Paid API per call (Anthropic / OpenAI) | DelftBlue compute hours (institutional allocation) |
| **Reproducibility artefact** | `run_config.json` + `rerun.sh` + `uv.lock` + `.env.example` + `Dockerfile` | Same plus the SLURM script that launched it |

### Things that the API mode could in principle skip but currently doesn't

These are simplifications worth keeping on the radar but **not** worth coding
right now (they save no real time or correctness):

- **HF model fetching.** API mode still loads SBERT and the tokenizers for
  CodeBLEU; both download from HF Hub at first use. We could in principle wire
  an "API-only fitness" mode that uses a cloud embedding API for SBERT, but
  CodeBLEU's tree-sitter step is fully local anyway, and SBERT is a one-off
  ~400 MB download.
- **Semgrep rules.** API mode uses the online registry by default; DelftBlue
  uses the offline copy. The Python code is already portable; no change needed.
- **Perplexity gate.** API providers don't expose the logprob channel we need.
  `--enable-perplexity` is gated to `delftblue` only and the rest of the
  validator still runs in API mode (SBERT, inline-code, keyword retention).

### Things you should *not* do in API mode

- Don't try to use `--backend delftblue` on a CPU box. The backend's
  `is_available()` returns `False` immediately when CUDA is absent and the
  pipeline exits with a clear error.
- Don't set `HF_HUB_OFFLINE=1` locally. Several stages download artefacts on
  first run; forcing offline breaks them with a misleading "model not found"
  message.
- Don't run a long sweep at full `--n-cases`/`--iterations` with paid
  backends without first sanity-checking a 2×2 smoke. The
  [`scripts/validation/validate_claude.py`](scripts/validation/validate_claude.py)
  helper does this in ~1.5 s.

### Things you should *not* do in DelftBlue mode

- Don't run heavy compute on the login node — every Qwen-32B run goes through
  `sbatch`. The login node is for `uv sync`, retrieval-map generation, and the
  Claude-on-DelftBlue analysis prompt (which is read-only file processing).
- Don't expect outbound HTTPS on compute nodes. If you need a model that isn't
  in `/scratch/$USER/models/`, download it on the login node first.
- Don't forget the manual CUDA-torch reinstall after `uv sync --extra gpu` —
  uv's lockfile pins to CPU torch by design and the swap is the one step that
  can't be encoded in `pyproject.toml` without forcing a specific CUDA toolkit
  version on every replicator.

---

## 5. Maintenance checklist

When you change a dep, ask:

- Is this required for both API and DelftBlue paths, or only one? If only one,
  it belongs in an extra (`gpu`, `retrieval`).
- Does it transitively pull `torch`? If yes, decide which torch wheel it should
  ride on (CPU by default, CUDA via the manual reinstall on DelftBlue).
- Will the new constraint trip codebleu's silent tree-sitter fallback? Verify
  with `uv run python -c "from codebleu import calc_codebleu; print(calc_codebleu([...], [...], lang='python', weights=(0.25,)*4))"` — the `dataflow_match_score` must be non-zero on inputs that have any dataflow.
- After changing a constraint, `rm uv.lock && uv lock && uv sync --extra retrieval --extra dev` then `uv run pytest tests/unit/ -q` — must stay at 176/176.

When porting to a new host:

- **Scenario A (anyone replicating)**: clone → `uv sync` → set `.env` → run.
- **Scenario D (DelftBlue post-push)**: clone → `uv sync --extra gpu --extra retrieval --extra dev` → manual CUDA torch reinstall → smoke `--backend delftblue --n-cases 2 --iterations 2 --dry-run` first.
