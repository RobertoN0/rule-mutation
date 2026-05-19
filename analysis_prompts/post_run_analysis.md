# Post-run analysis prompt — DelftBlue Claude

**How to use this file.** On DelftBlue, open a fresh Claude Code session in
`~/thesis/rule-mutation/`. Replace the placeholders below, then paste the
whole prompt (from "You are picking up..." down) into the chat as a single
message. Claude will read it, invoke the `analyze-results` skill, and emit
one `analysis_report_<date>.md` at the repo root that you `scp` back to the
local workstation.

---

## Placeholders to fill

| Placeholder | Value to substitute | Notes |
|---|---|---|
| `{{JOB_IDS}}` | Comma-separated SLURM job IDs, e.g. `9900723,9905012` | Required. |
| `{{TOPIC}}` | One of: `B-drift`, `C-validation-gate`, `D-pool-comparison`, `E-fitness-comparison`, `F-end-to-end`, or `general` | Selects the focus the skill applies. |
| `{{NOTES}}` | Free text — anything you want flagged (e.g. "expected fitness drop on Java", "watch for eval_cache_hit_rate > 0.95") | Optional. Leave empty if none. |
| `{{DATE}}` | `YYYY-MM-DD` of the analysis run | Used in the output filename. |

---

## The prompt (copy from here down)

You are picking up after a SLURM experiment burst on DelftBlue. Your single
deliverable is a structured analysis report at the repo root that the user
will `scp` back to their local workstation. Do not run new experiments,
commit anything, or close any beads issues.

### Inputs

- **Job IDs:** `{{JOB_IDS}}`
- **Result directories:** `experiments/results/job{ID}_*/` (one per job ID)
- **Validation topic:** `{{TOPIC}}`
- **User notes:** `{{NOTES}}`
- **Analysis date:** `{{DATE}}`

### What to do

1. **Confirm presence.** For each job ID, list `experiments/results/job{ID}_*/`
   and verify the directory exists. If any are missing or empty, report and stop.
2. **Invoke the `analyze-results` skill.** Point it at the job directories with
   `--topic={{TOPIC}}`. The skill reads `run_config.json`,
   `hillclimb_summary_*.json`, `hillclimb_per_rule_*.json`, `mutated_rules/`,
   and the SLURM `.out` files; it knows the schema.
3. **Per-job extraction.** For each job, capture:
   - `run_config`: optimizer, n_cases, iterations, languages, mutators, seed,
     git_sha, slurm_job_id
   - From `hillclimb_summary_*.json`: wall time, baseline vs best fitness,
     improvement, num_iterations_run, total_llm_calls, eval_cache hit rate,
     pool_arm_stats (if D-UCB: per-mutator pulls + mean_reward; if EA: archive
     size + restart_reason_counts)
   - From `hillclimb_per_rule_*.json`: per-rule best_fitness_delta and
     best_mean_code_divergence; flag the top 5 most impactful rules
   - From `mutated_rules/`: count of accepted mutations, max depth reached
   - From SLURM `.out`: any warnings, retries, GPU OOMs, or rate-limit blips
4. **Cross-job comparison** (only if multiple job IDs).
   Build a markdown table keyed on `(language, optimizer, seed)` with columns:
   baseline_fitness, best_fitness, improvement, num_iterations_run, wall_time,
   top_mutator, accepted_mutations. Add 2-3 paragraphs of commentary on what
   varies across rows.
5. **Topic-specific deep dive** based on `{{TOPIC}}`:
   - `B-drift`: per-case fitness trajectory vs the baseline coverage in
     `experiments/analysis/baseline_coverage.json` — call out any case whose
     drift > 1.5× median.
   - `C-validation-gate`: passes_all rate, SBERT/keyword/inline-code retention
     distributions, rejection reasons histogram.
   - `D-pool-comparison`: per-mutator pulls + mean_reward across optimizers;
     identify dominated and dominating arms.
   - `E-fitness-comparison`: lex vs Pareto archive results; cite the
     archive-corner-trap analogy from the project memory.
   - `F-end-to-end`: smoke-test sanity (was it 200 iters? 25 cases? expected
     wall time? no silent failures?).
   - `general`: include all of the above as appropriate.
6. **Anomalies.** Flag any of: eval_cache_hit_rate > 0.95 (LLM is generating
   identical mutated rule text), fitness flatline for > 30 iterations on a
   single rule (premature local optimum), restart_reason_counts dominated by
   `fully_exhausted` (search space too narrow), wall time > 1.5× the expected
   12 h budget per language.
7. **Recommended next iteration.** End with concrete CLI flags for the next
   run, with one-sentence justifications each. Examples: "bump `--archive-cap`
   from 5 to 10 because two rules hit `depth_saturated` early", or "swap
   `voice_change` for `paraphrase` because mean_reward is 3× higher".

### Output

Write the report to `analysis_report_{{DATE}}.md` at the repo root. Use this
exact section structure (omit empty sections rather than leaving them blank):

```markdown
# Analysis Report — {{JOB_IDS}} — {{DATE}}

## TL;DR
- (main finding, one line)
- (surprise, one line)
- (recommended next step, one line)

## Per-job summary
### Job {{ID_1}}
| Metric | Value |
| ...

### Job {{ID_2}}
...

## Cross-job comparison
(table + commentary; omit section if only one job)

## Topic-specific findings ({{TOPIC}})
(paragraphs + tables; what changed vs prior runs)

## Anomalies
- (each item: what + where + suggested follow-up)

## Recommended next iteration
```bash
# concrete CLI invocation
```
- Rationale for each flag change.

## Appendix: raw metrics
(big tables; can be skipped on read)
```

When the file is written, print only:
- The absolute path to the report
- The TL;DR section
- Any anomalies that need urgent attention

so the user has the gist in chat without re-reading the file.

### What NOT to do

- Don't commit or `git push`.
- Don't run `bd close` on any issue.
- Don't move or archive `experiments/results/job*/` directories.
- Don't sbatch new jobs.
- Don't `pip install` or `uv add` anything new — if a dep is missing, report and stop.

### Hard rules carried over from project memory

- Beads workflow: use `bd ready` to know context. Do not autonomously close anything.
- Git policy: user handles all git operations. You may read state, never write.
- HPC: no heavy compute on login nodes — analysis is read-only file processing, which is fine on login.
