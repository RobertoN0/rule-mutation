# RQ3 - which text mutations and ordering moves are associated with gains?

Sign convention: **delta > 0 means FEWER findings than the reference (an improvement)**.
EA runs in scope: 40.

## Level 1 - clean one-move parent/child contrasts (the anchor)

Text moves changed one rule by one operator; whole-rule reorder moves changed
one priority entry. Both the child and its archived parent passed the exact
safe-zone contract. Move-level values are descriptive because successive moves
within a run are dependent. Run-aggregated summaries are the primary evidence.

**Read the two success columns separately.** `positive delta` is computed
directly as f1 > parent_f1. `archive accept` is
multi-objective — the archive also rewards textual similarity (f2) and parsimony (f3),
so a move can be kept while f1 gets worse. An operator with a high accept
rate but a low advance rate is surviving on textual similarity, not on the finding-count effect.

### llama_java — 583 clean moves, 82 positive-delta, 201 archive-accepted

Safe-zone exclusions (otherwise-clean moves): 397 invalid child, 0 invalid parent, 0 unknown/conflicting parent.

| move family | moves | runs | **P(Δ>0), moves** | median run P(Δ>0) | archive accept | mean Δf1 | median run mean Δf1 | stored/actual mismatches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| negation_injection | 73 | 9 | **0.205** | 0.231 | 0.260 | -0.644 | -0.429 | 1 |
| synonym_replacement | 75 | 8 | **0.200** | 0.225 | 0.213 | -0.787 | -0.742 | 7 |
| add_random_word | 85 | 8 | **0.153** | 0.191 | 0.541 | -1.035 | -0.900 | 0 |
| section_reorder_degrade | 60 | 9 | **0.150** | 0.200 | 0.583 | -0.833 | -0.750 | 1 |
| voice_change | 54 | 7 | **0.148** | 0.143 | 0.130 | -0.648 | -0.429 | 3 |
| section_reorder_shuffle | 67 | 9 | **0.134** | 0.100 | 0.269 | -0.448 | -0.300 | 1 |
| whole_rule_reorder | 60 | 8 | **0.083** | 0.050 | 0.450 | -0.933 | -0.979 | 0 |
| paraphrase | 54 | 9 | **0.074** | 0.000 | 0.056 | -0.981 | -1.000 | 1 |
| verb_weakening | 55 | 8 | **0.073** | 0.036 | 0.545 | -0.436 | -0.292 | 0 |

### llama_python — 378 clean moves, 87 positive-delta, 153 archive-accepted

Safe-zone exclusions (otherwise-clean moves): 377 invalid child, 0 invalid parent, 0 unknown/conflicting parent.

| move family | moves | runs | **P(Δ>0), moves** | median run P(Δ>0) | archive accept | mean Δf1 | median run mean Δf1 | stored/actual mismatches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| synonym_replacement | 56 | 8 | **0.339** | 0.348 | 0.411 | +0.536 | +0.500 | 1 |
| whole_rule_reorder | 40 | 9 | **0.325** | 0.364 | 0.700 | -1.450 | -0.800 | 0 |
| verb_weakening | 34 | 9 | **0.324** | 0.444 | 0.765 | +0.412 | +1.000 | 0 |
| add_random_word | 48 | 9 | **0.229** | 0.100 | 0.500 | -0.854 | -0.429 | 2 |
| negation_injection | 42 | 10 | **0.214** | 0.167 | 0.143 | -0.643 | -0.250 | 8 |
| paraphrase | 33 | 10 | **0.182** | 0.139 | 0.121 | -1.091 | -0.567 | 4 |
| section_reorder_degrade | 44 | 10 | **0.182** | 0.056 | 0.614 | +0.273 | +0.000 | 0 |
| section_reorder_shuffle | 42 | 10 | **0.167** | 0.000 | 0.286 | -1.548 | -0.500 | 1 |
| voice_change | 39 | 9 | **0.077** | 0.000 | 0.077 | -1.179 | +0.000 | 1 |

### qwen_java — 1129 clean moves, 105 positive-delta, 444 archive-accepted

Safe-zone exclusions (otherwise-clean moves): 2044 invalid child, 0 invalid parent, 0 unknown/conflicting parent.

| move family | moves | runs | **P(Δ>0), moves** | median run P(Δ>0) | archive accept | mean Δf1 | median run mean Δf1 | stored/actual mismatches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| add_random_word | 150 | 10 | **0.127** | 0.168 | 0.373 | -0.107 | +0.000 | 1 |
| negation_injection | 141 | 10 | **0.121** | 0.097 | 0.553 | -0.035 | -0.063 | 3 |
| synonym_replacement | 130 | 9 | **0.115** | 0.083 | 0.100 | -0.308 | -0.250 | 5 |
| whole_rule_reorder | 111 | 10 | **0.099** | 0.077 | 0.811 | -0.117 | -0.071 | 0 |
| section_reorder_shuffle | 135 | 10 | **0.096** | 0.000 | 0.185 | -0.215 | -0.250 | 0 |
| paraphrase | 135 | 10 | **0.089** | 0.029 | 0.356 | -0.141 | -0.159 | 1 |
| verb_weakening | 104 | 10 | **0.077** | 0.000 | 0.558 | -0.240 | -0.323 | 0 |
| voice_change | 119 | 10 | **0.050** | 0.026 | 0.319 | -0.202 | +0.000 | 1 |
| section_reorder_degrade | 104 | 9 | **0.038** | 0.000 | 0.365 | -0.163 | -0.200 | 2 |

### qwen_python — 1213 clean moves, 178 positive-delta, 537 archive-accepted

Safe-zone exclusions (otherwise-clean moves): 724 invalid child, 0 invalid parent, 0 unknown/conflicting parent.

| move family | moves | runs | **P(Δ>0), moves** | median run P(Δ>0) | archive accept | mean Δf1 | median run mean Δf1 | stored/actual mismatches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| synonym_replacement | 135 | 9 | **0.296** | 0.333 | 0.259 | +0.200 | +0.000 | 8 |
| whole_rule_reorder | 138 | 10 | **0.254** | 0.310 | 0.594 | -0.587 | -0.375 | 0 |
| section_reorder_shuffle | 141 | 10 | **0.170** | 0.106 | 0.248 | -0.156 | -0.250 | 2 |
| negation_injection | 133 | 10 | **0.150** | 0.142 | 0.647 | -0.308 | -0.346 | 5 |
| section_reorder_degrade | 124 | 10 | **0.121** | 0.045 | 0.484 | -0.403 | -0.172 | 1 |
| add_random_word | 157 | 9 | **0.102** | 0.100 | 0.427 | -0.611 | -0.552 | 0 |
| voice_change | 123 | 9 | **0.098** | 0.091 | 0.333 | -0.650 | -0.722 | 0 |
| paraphrase | 124 | 10 | **0.065** | 0.021 | 0.306 | -0.895 | -0.875 | 1 |
| verb_weakening | 138 | 10 | **0.058** | 0.020 | 0.674 | -0.630 | -0.462 | 0 |

The `whole_rule_reorder` row is the inter-rule priority operator. The
`section_reorder_shuffle` and `section_reorder_degrade` rows are separate
intra-rule section transformations. Their sampling shares have different
denominators and are not interpreted as randomized treatment probabilities.

## Level 2 - rule-instance marginal (all rules, any history length)

Unit: one mutated rule inside one evaluated chromosome. Its value is the
mean per-task finding delta over the tasks that were shown that rule,
against the run's own origin baseline. Grouped by whether the rule's
cumulative history contains the operator. Structurally invalid evaluated
chromosomes are excluded. Repeated states/tasks and adaptive selection make
this evidence descriptive and dependent, not an independent-sample test.

### llama_java

| operator | rule instances with | mean Δ with | mean Δ without | contrast | P(Δ>0) with |
|---|---:|---:|---:|---:|---:|
| negation_injection | 613 | +1.6728 | +0.3181 | +1.3547 | 0.628 |
| section_reorder_degrade | 662 | +0.7633 | +0.4937 | +0.2696 | 0.509 |
| section_reorder_shuffle | 672 | +0.4900 | +0.5533 | -0.0632 | 0.570 |
| add_random_word | 626 | +0.2288 | +0.6053 | -0.3766 | 0.577 |
| voice_change | 402 | +0.1986 | +0.5835 | -0.3849 | 0.525 |
| synonym_replacement | 542 | +0.1694 | +0.6055 | -0.4361 | 0.563 |
| paraphrase | 433 | +0.0796 | +0.6029 | -0.5232 | 0.282 |
| verb_weakening | 483 | +0.0207 | +0.6198 | -0.5991 | 0.340 |

### llama_python

| operator | rule instances with | mean Δ with | mean Δ without | contrast | P(Δ>0) with |
|---|---:|---:|---:|---:|---:|
| synonym_replacement | 501 | +0.1255 | +0.0755 | +0.0500 | 0.788 |
| voice_change | 235 | +0.1286 | +0.0819 | +0.0466 | 0.617 |
| add_random_word | 482 | +0.0980 | +0.0838 | +0.0143 | 0.577 |
| section_reorder_degrade | 422 | +0.0980 | +0.0843 | +0.0137 | 0.720 |
| section_reorder_shuffle | 228 | +0.0818 | +0.0875 | -0.0057 | 0.548 |
| verb_weakening | 259 | +0.0709 | +0.0890 | -0.0181 | 0.629 |
| negation_injection | 321 | +0.0551 | +0.0923 | -0.0372 | 0.511 |
| paraphrase | 113 | +0.0173 | +0.0907 | -0.0734 | 0.283 |

### qwen_java

| operator | rule instances with | mean Δ with | mean Δ without | contrast | P(Δ>0) with |
|---|---:|---:|---:|---:|---:|
| negation_injection | 1490 | +0.0623 | +0.0323 | +0.0301 | 0.517 |
| section_reorder_shuffle | 2085 | +0.0541 | +0.0321 | +0.0220 | 0.565 |
| add_random_word | 1903 | +0.0404 | +0.0361 | +0.0044 | 0.516 |
| voice_change | 725 | +0.0339 | +0.0372 | -0.0032 | 0.520 |
| synonym_replacement | 1398 | +0.0341 | +0.0374 | -0.0034 | 0.488 |
| paraphrase | 1755 | +0.0332 | +0.0378 | -0.0045 | 0.383 |
| verb_weakening | 1487 | +0.0275 | +0.0387 | -0.0111 | 0.409 |
| section_reorder_degrade | 1062 | +0.0243 | +0.0385 | -0.0142 | 0.384 |

### qwen_python

| operator | rule instances with | mean Δ with | mean Δ without | contrast | P(Δ>0) with |
|---|---:|---:|---:|---:|---:|
| verb_weakening | 1096 | +0.6485 | +0.1711 | +0.4774 | 0.777 |
| synonym_replacement | 2220 | +0.2495 | +0.2135 | +0.0359 | 0.937 |
| voice_change | 2294 | +0.2356 | +0.2171 | +0.0185 | 0.505 |
| section_reorder_degrade | 1376 | +0.1565 | +0.2310 | -0.0745 | 0.759 |
| section_reorder_shuffle | 1400 | +0.1409 | +0.2336 | -0.0927 | 0.747 |
| paraphrase | 1250 | +0.1351 | +0.2329 | -0.0978 | 0.444 |
| add_random_word | 1711 | +0.1174 | +0.2415 | -0.1241 | 0.731 |
| negation_injection | 1343 | +0.0871 | +0.2409 | -0.1538 | 0.567 |

## Level 3 - exploratory covariate adjustment

### Rule-history length (how much stacking actually happens)

| distinct operators in a rule's history | rule instances |
|---:|---:|
| 1 | 21141 |
| 2 | 4107 |
| 3 | 566 |
| 4 | 134 |

A mass concentrated at 1 limits operator co-occurrence, but Level 2 remains
dependent because states and tasks recur along adaptively selected runs.

### Operator co-occurrence within a single rule's history

| operator | add_random_w | negation_inj | paraphrase | section_reor | section_reor | synonym_repl | verb_weakeni | voice_change |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| add_random_word | 0 | 322 | 259 | 360 | 472 | 502 | 110 | 342 |
| negation_injection | 322 | 0 | 80 | 174 | 158 | 167 | 105 | 125 |
| paraphrase | 259 | 80 | 0 | 192 | 388 | 199 | 155 | 166 |
| section_reorder_degrade | 360 | 174 | 192 | 0 | 336 | 165 | 261 | 146 |
| section_reorder_shuffle | 472 | 158 | 388 | 336 | 0 | 404 | 177 | 300 |
| synonym_replacement | 502 | 167 | 199 | 165 | 404 | 0 | 107 | 411 |
| verb_weakening | 110 | 105 | 155 | 261 | 177 | 107 | 0 | 26 |
| voice_change | 342 | 125 | 166 | 146 | 300 | 411 | 26 | 0 |

### Indicator regression (per-task delta on operator presence)

Exploratory. Coefficient = marginal change in a task's finding delta when
the task is shown at least one rule carrying that operator, holding the
other operators fixed.

#### llama_java (n=51079 task observations, intercept +0.0408)

| operator | coefficient |
|---|---:|
| negation_injection | +0.1056 |
| section_reorder_shuffle | +0.0710 |
| section_reorder_degrade | +0.0396 |
| add_random_word | -0.0054 |
| synonym_replacement | -0.0118 |
| voice_change | -0.0250 |
| verb_weakening | -0.0420 |
| paraphrase | -0.0850 |

#### llama_python (n=65521 task observations, intercept +0.0314)

| operator | coefficient |
|---|---:|
| synonym_replacement | +0.0628 |
| voice_change | +0.0545 |
| section_reorder_degrade | +0.0284 |
| add_random_word | +0.0249 |
| negation_injection | +0.0174 |
| verb_weakening | +0.0096 |
| section_reorder_shuffle | -0.0274 |
| paraphrase | -0.0374 |

#### qwen_java (n=118014 task observations, intercept +0.0244)

| operator | coefficient |
|---|---:|
| paraphrase | +0.0207 |
| add_random_word | +0.0198 |
| synonym_replacement | +0.0154 |
| section_reorder_shuffle | +0.0130 |
| negation_injection | +0.0102 |
| voice_change | +0.0092 |
| verb_weakening | +0.0036 |
| section_reorder_degrade | -0.0071 |

#### qwen_python (n=191336 task observations, intercept +0.0298)

| operator | coefficient |
|---|---:|
| synonym_replacement | +0.0628 |
| verb_weakening | +0.0512 |
| section_reorder_shuffle | +0.0489 |
| voice_change | +0.0340 |
| paraphrase | +0.0177 |
| add_random_word | +0.0121 |
| negation_injection | -0.0024 |
| section_reorder_degrade | -0.0129 |
