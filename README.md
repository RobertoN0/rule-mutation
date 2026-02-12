# Evidence and Experiment Index

The main experiment is performed with [experiment_02.ipynb](experiment_02.ipynb). The notebook sets up an experiment to use a simple langgraph agent to complete a task from Meta's CyberSecEval dataset.
Current configuration and results are done for the CWE 89 (SQL Injection) examples in the dataset. Mutation of the rule are performed in two ways:
- Addition of fluff information
- Weakening of the existing rule (replace "MUST" with ""should ideally" and "Ensure" with "Try to ensure")

Experiments were executed with both mutations in place as well as each mutation taken singularly. The results of the experiments are shown here:

- [`evidence_CWE_89_1.txt`](evidence_CWE_89_1.txt) — Experiment 1: comparison between original rule usage and mutated rule with prefix and suffix enabled (fluff present) and rule weakening enabled.
- [`evidence_CWE_89_2.txt`](evidence_CWE_89_2.txt) — Experiment 2: comparison between original rule usage and mutated rule with prefix and suffix set to empty strings and rule weakening enabled.
- [`evidence_CWE_89_3.txt`](evidence_CWE_89_3.txt) — Experiment 3: comparison between original rule usage and mutated rule with prefix and suffix enabled (fluff present) and rule weakening disabled.
- [`evidence_CWE_89_baseline.txt`](evidence_CWE_89_baseline.txt) — Baseline evidence: final experiment version created. Reports three-way comparison including a no-rule baseline, original rule usage and mutated rule with fluff and weakening enabled.