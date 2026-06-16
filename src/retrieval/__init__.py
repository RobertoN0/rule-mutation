"""
Rule-retrieval map builders.

Discover which CodeGuard rules are relevant to each CyberSecEval prompt and emit
the prompt -> rule-IDs maps consumed by the experiment pipeline. Two CLI variants:

- rule_retrieval_mapping_local.py    — locally-hosted model (DelftBlue / GPU).
- rule_retrieval_mapping_anthropic.py — Claude via the Anthropic API.

Pre-computed maps are committed under rule_maps/,
so running these is optional (see the [retrieval] extra in pyproject.toml).
"""
