# Experiment 02 — MCP-Based Metamorphic Testing

## Purpose

Evaluate whether an AI agent that **autonomously retrieves** Project CodeGuard security rules via an MCP server produces equally secure code as one that receives the rule through direct injection, and whether weakened ("mutated") rules cause measurable security regressions.

## Architecture

```
┌───────────────────────────────────────────┐
│         experiment_02.ipynb               │
│                                           │
│  Baseline Agent (no rules)                │
│  Control Agent  (MCP retrieval)           │──── MCP stdio ───▶ mcp_codeguard_server.py
│  Mutant Agent   (MCP retrieval weakened)  │                        │
└──────────────┬────────────────────────────┘                        │
               │                                            project-codeguard/
               ▼                                            skills/software-security/
         Semgrep Analysis                                   rules/*.md  (23 rules)
```

| Agent      | How it gets the rule            | Purpose                        |
|------------|---------------------------------|--------------------------------|
| Baseline   | No rule at all                  | Establish LLM's default        |
| Control    | Calls MCP tool → retrieves rule | Realistic autonomous retrieval |
| Mutant     | Calls MCP tool → retrieves rule → weakens it | Metamorphic test oracle        |

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create a .env file with your OpenAI key
echo 'OPENAI_API_KEY=sk-...' > .env

# 3. Open experiment_02.ipynb and run cells 1 → 5D in order.
```

## Notebook Cells

| Cell | Name                   | What it does                                      |
|------|------------------------|---------------------------------------------------|
| 1    | Setup                  | Loads API key, defines rule paths                 |
| 2    | Dataset                | Loads CyberSecEval, helper `get_test_cases()`     |
| 3    | Mutation Logic         | `create_mutant_rule()` — fluff / rephrase         |
| 4    | Agent Definition       | Builds MCP-based agent + baseline (LangGraph)     |
| 5    | Semgrep                | `run_semgrep()` static analysis helper            |
| 5A   | Code Generation        | Runs 3 agents, saves results to JSON              |
| 5B   | Analysis Only          | Loads saved JSON, runs Semgrep on saved code      |
| 5C   | Results Summary        | Summary stats + findings breakdown                |
| 5D   | Code Comparison        | Side-by-side for cases with security differences  |

## MCP Server

`mcp_codeguard_server.py` exposes two tools over stdio:

- **`list_available_guidelines()`** — lists rule IDs and descriptions.
- **`get_guideline_by_id`** — returns full rule in MARKDOWN format by its ID

The notebook's Cell 4 launches this server as a subprocess each time the agent calls a tool. No long-running process or network port is needed.

## Key Difference from `static_analysis.ipynb`

`static_analysis.ipynb` uses a deterministic `consult_guidelines()` tool that returns a pre-loaded global variable. The agent always gets the exact rule the experimenter chose.

`experiment_02.ipynb` instead connects to the MCP server. The agent must formulate a search query; the server decides which rule matches best. This tests whether the agent can **autonomously identify** the right security guideline.

## Updated Mutant Agent Workflow

The mutant agent now retrieves the security rule via the MCP server, applies the `create_mutant_rule()` function to weaken the rule, and uses this mutated rule for code generation. This ensures that the mutant agent's behavior aligns with the MCP-based retrieval process while introducing controlled weaknesses for metamorphic testing.
