# Task-to-rule maps

This directory contains the population audit and the maps used by the final
experiments.

- `source_population.json` is the 351-Python/229-Java task carrier.
- `population_eligibility_manifest.json` records the prospective removal of
  one exact duplicate and 30 prompts that explicitly request an output
  language incompatible with their dataset split.
- `qualified/` contains the final model-specific authored-rules maps, matching
  no-rules maps, and the evidence summaries used to verify them. Historical
  filenames and condition fields may use the internal label `withrules`.

The final population requires two independent properties:

1. at least one Semgrep finding was observed over the 20-seed
   temperature-0.6 screening across both code models and both no-rules and
   authored-rules conditions; and
2. the authored-rule temperature-zero output was valid for both code models.

The resulting frozen population contains 203 Python and 126 Java tasks. A
zero-finding task with incomplete screening observations is excluded for lack
of positive Semgrep-finding evidence; it is not described as proven safe or
never capable of producing a finding.

## Integrity fields

- A map SHA-256 hashes the exact JSON file bytes and binds a run to that exact
  rule assignment and metadata.
- A population fingerprint hashes the ordered
  `(task ID, analysis language, prompt hash)` identities. It proves that two
  model maps evaluate the same task population even though their retrieved
  rules may differ.
- The prompt-contract SHA-256 binds the system/user prompt templates and
  language instruction.
- The Semgrep source commit identifies the upstream rules revision; the
  Semgrep rules SHA-256 binds the installed YAML rule contents.

Materialization checks these values against the screening and qualification
artifacts. Search and replicate validators compare the current map bytes and
population fingerprint with the values recorded before model inference.

Validate all nine maps, their ordered task fingerprints, and supporting
artifact hashes with:

```bash
.venv/bin/python scripts/analyze/validate_qualified_maps.py rule_maps/qualified
```
