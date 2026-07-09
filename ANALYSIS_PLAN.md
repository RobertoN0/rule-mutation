# Analysis Plan — Chromosome-restructured SBST / LLM rule-repair

_Prepared 2026-07-08. Purpose: one document to review and decide, once and for all, what
we analyse, how, and on what evidence. Covers (A) an audit of the existing analysis stack,
(B) the headline research questions re-framed for the chromosome design, (C) the proposed
analyses — each with source, a realistic worked example on our own data, its meaning, and a
plain-words version — (D) cross-cutting methodology, (E) the literature basis, and (F)
priorities + the decisions I need from you._

---

## 0. TL;DR

Three-layer verdict from the code audit:

1. **The statistics toolkit (`stats.py`) is mature and reusable as-is.** It already implements
   exactly the tests the SBSE methodology literature prescribes (Mann–Whitney U, Vargha–Delaney
   Â₁₂, Wilcoxon, McNemar, sign, Friedman, Cliff's δ, bootstrap/Wilson CIs). No rework.
2. **RQ3 (EA-vs-random search behaviour) is ~80% schema-3 ready.** `best_f1`, convergence, and
   the Pareto front already have chromosome-aware code. Needs: relabelling + the multi-objective
   comparison built out properly.
3. **RQ1 (repair) and RQ2 (mutators) need real rework, and four genuinely new dimensions have
   _zero_ coverage** — move-type contribution, rule **reordering**, rule **interactions**, and
   **saturated-ablation**. These new dimensions are where the chromosome redesign actually earns
   its keep, so they should be first-class, not afterthoughts.

The single biggest framing opportunity: recent surveys of LLMs-in-code-security find that
**vulnerability _repair_ is heavily underexplored (~11% of studies) versus detection**, and that
LLMs "generate insecure code even when explicitly instructed to be secure." Our work is squarely
in that gap — rule-level repair of LLM security behaviour — which is a strong thesis hook.

---

## Part A — Audit of the current analysis stack

### A.1 Component map

| Layer | Modules | Role | Schema-3 status |
|---|---|---|---|
| Loaders | `loaders.py`, `records.py` | Load runs, iterate iterations, best_f1, convergence, baseline findings | Mostly ready; `per_rule_best/worst` semantics shift (see A.3) |
| Stats | `stats.py` | All statistical tests + effect sizes + CIs | **Reusable as-is** |
| Labels | `labels.py` | Canonical class tokens + display map | New, done |
| RQ1 repair | `metrics/repair.py`, `metrics/outcomes.py`, `metrics/outcome_rows.py`, `viz/repair.py`, `report/outcomes.py`, `analyze_repair.py` | Per-task before/after, subsets, outcome envelope | Needs vulnerable-denominator headline + best-chromosome per-prompt read |
| RQ2 mutators | `metrics/mutators.py`, `viz/mutators.py`, `report/mutators.py`, `analyze_mutators.py` | Per-mutator effect, lineage, combinations, per-rule paths | Entry declares **schema-2**; per-rule/combination semantics shift |
| RQ3 search | `metrics/search.py`, `viz/search.py`, `report/search.py`, `analyze_search.py`, `fitness_trajectories.py`, `metrics/series.py` | Efficiency, convergence, Pareto front, EA-vs-random | `final_front_rows` has schema-3 branch; entry declares schema-2 |
| Security | `metrics/security.py`, `viz/security.py`, `analyze_security.py` | Per-CWE outcome rates | Reusable; feed from best chromosome |
| Cost | `metrics/cost.py`, `analyze_cost.py` | Wall time, LLM calls, cache hygiene | Reusable |
| Baseline | `per_prompt_baseline.py` | Classifies tasks from 40-rep baseline | Done (label rename applied) |
| Orchestration | `analyze_run.py`, `analyze_replicates.py`, `collect_reports.py` | Single-run + multi-seed drivers | **All declare schema-2 in the header** |
| Migration | `migrate_legacy_run.py` | schema-2 → 3 (lossy) | For old runs only |

**Bottom line:** the *metric primitives* are largely fine; the *entrypoints* still announce
"schema_version 2" and the *interpretation* of several per-rule tables changes under a
whole-chromosome archive. This is re-theming + targeted rewrites, not a rebuild.

### A.2 The three objectives — what they mean, which is the headline

The Pareto archive maximises **(f1, f2, f3)** on the whole chromosome:

| Obj | Code field | Definition | Role |
|---|---|---|---|
| **f1** | `total_semgrep_delta` | Change in Semgrep findings vs baseline (findings removed, under minimize) | **Headline — the repair signal** |
| f2 | `proportion_divergent` | Fraction of *affected* prompts whose generated code diverges from the reference | Secondary — breadth of behavioural change |
| f3 | `conditional_mean_divergence` | Mean code divergence over the affected-and-divergent subset | Secondary — depth of behavioural change |

**Decision flag #1:** f2/f3 measure *how much the model's output moved* when the rules changed.
For the repair story, f1 is the number that matters. We need to decide whether f2/f3 are (a) a
reported secondary axis ("repairs come with measurable behavioural change / side-effects"),
(b) a constraint we mention, or (c) appendix-only. My recommendation: keep them as the
multi-objective *context* (they justify why an *archive* and not a scalar hill-climb), report
f1 as the headline, and show the f1×(f2/f3) trade-off once (Part C3).

### A.3 What breaks / needs rework for schema-3

1. **Entrypoints declare schema-2.** `analyze_run/search/mutators/security/cost.py` headers say
   "schema_version 2". Even where the underlying metric is chromosome-aware, the drivers and
   captions must be updated (or thin schema-3 drivers added).
2. **"Per-rule" tables change meaning.** Under the old per-rule archive, a row was *one rule's
   isolated effect*. Now the archive holds *whole chromosomes*, so `loaders.per_rule_best/worst`
   and `per_rule_fitness.png` become "the best chromosome whose *changed gene* was rule R" — a
   marginal-in-context reading, not an isolated one. Every such caption/label needs rewriting.
3. **RQ1 denominator.** The supervisor explicitly asked for reductions reported over the
   *initially-vulnerable* tasks (excluding always-safe), as counts, not yes/no. The subset logic
   exists (`metrics/repair.py` via `labels`), but the *headline* must become "of N initially-
   vulnerable tasks, the best rule set fixes M" — and must account for tasks made *worse*.
4. **RQ2 archive-based functions.** `combination_counts`, `per_rule_best_path/safest_path` were
   written against per-rule archives; they must read the single `chromosomes[]` list.

### A.4 Coverage gaps — new dimensions with **no** analysis today

These are new *because the chromosome design is new*, and they are the scientifically interesting
part:

- **Move-type contribution** (mutate vs order vs reverse). Nothing analyses `move_type`.
- **Rule reordering** — does the *order* rules are presented in change adherence? (Our sanity
  data already says yes.) No analysis.
- **Rule interactions** — which rules must change *together* to fix a task. This is the entire
  motivation for going per-rule → chromosome, and there is no analysis of it.
- **Saturated-ablation** — how often are stacked mutations reverted as no-longer-useful, and does
  that help? Brand new operator, no analysis.
- **Stacking depth vs semantic drift** — we have the SBERT-vs-depth curve ad hoc; it should be a
  first-class figure that justifies `max_depth`.

---

## Part B — The headlines (RQs) for the chromosome design

**RQ1 — Repair.** _Can a search over rule-set edits reduce the vulnerabilities an LLM emits, and
by how much, on the tasks that are actually vulnerable to begin with?_
Headline claim shape: "On the initially-vulnerable Python set (185 tasks), the best repaired rule
set removes X% of baseline Semgrep findings and fixes M/ N tasks; on Java, Y%." (Our runs so far:
Python −13–16% of all findings; Java −2–4%.)

**RQ2 — Mechanism.** _What edits drive the repair — which mutators, which move types, and which
rule combinations?_ Headline: text mutation is the workhorse; **reordering contributes
independently**; the best rule sets are **multi-rule** (5–6 interacting genes), which the old
per-rule design could not discover.

**RQ3 — Guidance.** _Does guided evolutionary search beat an unguided random baseline, under a
matched operator?_ Headline: with the aligned 1–4 operator, EA ≥ random on best-f1 across seeds
(Mann–Whitney U + Â₁₂), and reaches good solutions faster (anytime curves), and dominates in the
multi-objective sense (attainment surfaces). This is the corrected comparison the supervisor
asked for.

---

## Part C — The proposed analyses

Format per analysis: **What & how (source) · Example (our data) · Meaning · In plain words.**

### Group 1 — RQ3: does guidance beat randomness?

#### C1. Best-fitness comparison, EA vs random (primary RQ3 test)
- **What & how.** Per (language, seed) take each arm's best f1 (findings removed). Compare the two
  independent samples of 5 seeds with **Mann–Whitney U** and report **Vargha–Delaney Â₁₂** as the
  standardised effect size, plus median ± IQR. This is the exact protocol the SBSE methodology
  literature prescribes for comparing randomised algorithms _(Arcuri & Briand 2014; Vargha &
  Delaney 2000)_. Already coded (`stats.mann_whitney_u`, `vargha_delaney_a12`); the code's own
  note documents the small-n floor (n=5 vs 5 can reach p≈0.008) — which is exactly why the effect
  size is reported alongside.
- **Example.** EA best-f1 = {47, 57, 51, 49, 55}, random = {40, 46, 44, 43, 41} → Â₁₂ ≈ 0.9
  ("large"), U-test p ≈ 0.016. Report: "EA removed more findings than random in ~90% of head-to-
  head seed pairings (Â₁₂=0.90, large; MWU p=0.016)."
- **Meaning.** The corrected, apples-to-apples test of whether *guidance* (archive + selection),
  not just the operator, is what wins. It is the sentence the supervisor will look for.
- **In plain words.** "If you pick one guided run and one random run at random, how often does the
  guided one fix more bugs? If it's almost always, guidance clearly helps."

#### C2. Anytime convergence + target-hitting curves (RTD/ECDF)
- **What & how.** Plot best-f1-so-far vs iteration (median + IQR band across seeds), one line per
  arm. Add a **target-based ECDF / run-time distribution**: for each quality target t (e.g. "≥30
  findings removed"), the fraction of runs that have reached t by iteration i. Run-time
  distributions are the standard tool for characterising *anytime* behaviour of stochastic search
  _(Hoos & Stützle 2004)_; the target-ECDF is the single-objective specialisation of the
  attainment view _(López-Ibáñez et al. 2024, arXiv:2404.02031)_. Convergence plotting exists
  (`fitness_trajectories.py`, `metrics/series.py`); the ECDF is a small add.
- **Example.** "EA reaches −30 findings by a median of 42 iterations; random reaches it in only
  2/5 seeds within the budget." The curve visually separates "climbs steadily" (EA) from "lucky-
  or-not" (random) — exactly the dynamic seen in the sanity runs.
- **Meaning.** Effectiveness *and efficiency*: even where end-points are close, EA getting there
  sooner and more reliably is a real result, and it directly answers the meeting's "random gets
  lucky, search compounds" intuition.
- **In plain words.** "Not just who wins, but how fast and how reliably each method gets to a good
  answer over time."

#### C3. Multi-objective comparison — attainment surfaces + hypervolume
- **What & how.** Because the archive is genuinely multi-objective (f1, f2, f3), compare arms with
  the **Empirical Attainment Function (EAF)** and its summary **attainment surfaces**, plus the
  **hypervolume** indicator per run (median ± IQR, tested with MWU + Â₁₂). The EAF is *the*
  method designed for comparing stochastic multi-objective optimisers and visualising *where in
  objective space* one algorithm reliably beats another _(López-Ibáñez, Paquete & Stützle 2010;
  eaf R package)_. Hypervolume is the standard Pareto-quality scalarisation _(Zitzler & Thiele
  1999)_. New code (or the eaf R package offline on your laptop).
- **Example.** A 2-D EAF-difference plot over (f1 = findings removed, f2 = breadth of change)
  showing EA's attainment surface dominating random's across the front; hypervolume EA 0.71 vs
  random 0.55 (Â₁₂=0.84).
- **Meaning.** Defends the *archive* design (not just a scalar objective): guidance yields a
  better *frontier* of repair-vs-behavioural-change trade-offs, not merely a better single point.
  If we decide f2/f3 are appendix-only, this collapses into C1 and we drop it.
- **In plain words.** "We care about two or three things at once (bugs removed, how much the
  code changed). This shows which method gives the better *set* of trade-off options, and in which
  region."

### Group 2 — RQ1: does the repaired rule set actually reduce vulnerabilities?

#### C4. Aggregate reduction over initially-vulnerable tasks (the supervisor's ask)
- **What & how.** Denominator = tasks that were vulnerable at baseline (`ALWAYS_VULNERABLE` +
  `SOMETIMES_VULNERABLE` + `FIXED_BY_RULES`; exclude `ALWAYS_SAFE`). Report (i) total findings
  removed as a **count** and % of baseline, and (ii) the paired per-task before/after finding
  counts tested with **Wilcoxon signed-rank** + **Cliff's δ** effect size _(Arcuri & Briand
  2014)_. Reporting as counts over the vulnerable denominator (not yes/no over all tasks) is the
  explicit meeting instruction. `metrics/repair.py` has the subset machinery; the headline number
  is the addition.
- **Example.** "Python: 185 initially-vulnerable tasks, 367 baseline findings → 320 with the best
  rule set = **47 findings removed (12.8%)**; per-task Wilcoxon p<0.001, Cliff's δ=0.31 (small-
  medium)."
- **Meaning.** The primary repair result, framed the way the committee wants — impact where impact
  is possible, not diluted by always-safe tasks.
- **In plain words.** "Out of the tasks that were actually buggy, how many bugs did our best rules
  remove? And is that a real drop, not noise?"

#### C5. Per-task fixed-rate + per-CWE breakdown
- **What & how.** Binary "has ≥1 finding" before vs after per task → **McNemar exact test** on the
  discordant pairs (tasks that flipped) _(coded: `stats.mcnemar_binary`)_. Break the fixed/broken
  counts down **by CWE** to show *which vulnerability classes* the rules fix vs can't touch
  (`metrics/security.py`, `per_prompt_baseline.py` already do per-CWE).
- **Example.** "34 tasks fixed, 6 newly-broken (McNemar p<0.001). By CWE: CWE-89 (SQLi) 12/15
  fixed; CWE-79 (XSS) 3/20 — the residual hard class."
- **Meaning.** Complements the count metric with a task-level and a security-domain view; the
  per-CWE table is where the "Java is harder / which bugs resist rules" story lives.
- **In plain words.** "How many buggy tasks became clean, how many got worse, and which *kinds*
  of bugs our rules are good or bad at."

#### C6. Baseline framing — sampling-based vulnerability probability (pass@k logic)
- **What & how.** The temp=0.6, 40-rep baseline classification estimates *P(a task is vulnerable)*
  from samples. Frame it explicitly with the **unbiased pass@k estimator** logic — from n samples
  with c vulnerable, estimate the probability rather than the naive fraction _(Chen et al. 2021,
  HumanEval)_. This legitimises the `ALWAYS/SOMETIMES/…` cut-offs as a principled probability
  estimate, not arbitrary thresholds.
- **Example.** "A task vulnerable in 39/40 reps → P̂(vuln)≈0.98 → `ALWAYS_VULNERABLE`; 8/40 →
  0.20 → `SOMETIMES_VULNERABLE`." (Same idea as pass@k, applied to 'fail@sample'.)
- **Meaning.** Grounds the whole task-classification scheme in an accepted estimator, pre-empting
  "why these buckets?" at the defence.
- **In plain words.** "Because the model is random at temperature 0.6, we sample each task many
  times to estimate how likely it is to be buggy — the standard trick used for code benchmarks."

### Group 3 — RQ2: what drives the repair (mechanism)?

#### C7. Per-mutator marginal effect (lineage delta)
- **What & how.** For every accepted text move, credit the *last* mutator in the chain with the
  chromosome's f1 change vs its parent (`metrics/mutators.py::lineage_steps`, using
  `selection_meta.parent_f1` + `mutation_chain[-1]`). Aggregate to a per-mutator mean effect with
  a **bootstrap 95% CI** _(coded: `stats.bootstrap_ci`)_. **Relabel** the semantics: under the
  chromosome archive this is now "the marginal whole-rule-set effect of applying mutator m *in the
  context of the current best solution*" — which is more meaningful than an isolated per-rule
  effect, not less.
- **Example.** "`negation_injection`: mean Δf1 = +2.1 [0.8, 3.4] over 46 applications; `verb_
  weakening`: +0.3 [−0.4, 1.1] (CI crosses 0 → not distinguishable from noise)."
- **Meaning.** Which *kinds* of rule edits (weaken directives, inject negation, reorder sections…)
  actually move security behaviour — the operator-effectiveness story.
- **In plain words.** "Which types of wording change to a rule tend to help, once you account for
  everything else already changed."

#### C8. Move-type / operator ablation (mutate vs order vs reverse)
- **What & how.** New. Tabulate, per move type, the count, acceptance rate, and **f1-advance
  rate** (share of moves that strictly improved f1). This is an *ablation-style* contribution
  analysis — the standard way to attribute an effect to a component. Optionally strengthen it with
  dedicated **ablation arms** in a later sweep (EA-without-order, EA-without-ablation) compared by
  MWU + Â₁₂.
- **Example (already computed on the sanity runs).** mutate 10.1% f1-advance, **order 9.1%**,
  reverse 2.2%. Reading: reordering pulls its weight; the *separate* reverse move barely moves f1
  (which is why we integrated ablation instead).
- **Meaning.** Justifies the operator set empirically and feeds the supervisor questions (keep
  order? how to treat reverting?). Directly defensible design evidence.
- **In plain words.** "Each 'kind of move' the search can make — reword a rule, reorder rules, or
  undo a rule — how often does it actually help? Keep the ones that pay off."

#### C9. Rule-interaction / combination analysis (the key new one)
- **What & how.** New, and central. From the best chromosomes: (i) the **distribution of how many
  rules are mutated** in good solutions; (ii) **co-occurrence** — which rule pairs/sets appear
  together in high-f1 chromosomes (`metrics/mutators.py::combination_counts`, rewritten over
  `chromosomes[]`); (iii) **marginal vs joint effect** — using the saturated-ablation reverts as
  natural leave-one-out probes (reverting rule R from a good chromosome and re-scoring estimates
  R's marginal contribution *in context*). Interaction/epistasis analysis of which genes must
  co-vary is standard in EA analysis; framing it via leave-one-out marginal effects is the
  cleanest defensible version here.
- **Example.** "Best Python chromosomes mutate a median of 5–6 rules; the pair (input-validation,
  output-encoding) co-occurs in 4/5 best solutions; reverting output-encoding alone costs +9
  findings, but reverting it when input-validation is *original* costs only +2 → evidence of a
  rule interaction the per-rule search could not see."
- **Meaning.** This is the scientific payoff of the whole restructure: demonstrating that some
  repairs *require* changing multiple rules together. It's the strongest novelty claim.
- **In plain words.** "Some bugs only get fixed when you change two or three rules *at the same
  time* — no single rule change does it. We show which rules team up."

### Group 4 — New chromosome-design dimensions

#### C10. Reordering effect — does the order of rules matter?
- **What & how.** New. (i) Move-type view from C8 (order-move f1-advance rate). (ii) A focused
  view: among accepted order moves, the f1 change from *only* re-ranking rules (no text change).
  (iii) Optional: hold the best text alleles fixed and sweep orderings. This connects directly to
  the LLM literature on **prompt-order / format sensitivity** — models are demonstrably sensitive
  to the order and formatting of prompt content _(Sclar et al. 2023, FormatSpread; "The Order
  Effect" 2025, arXiv:2502.04134; Mizrahi et al. 2024)_.
- **Example.** "Pure-reorder moves removed up to 4 findings with no wording change; promoting the
  input-validation rule to the top of the prompt fixed 3 tasks." Tie to FormatSpread's finding
  that semantically-equivalent presentation changes shift model behaviour substantially.
- **Meaning.** A clean, citable secondary contribution: *rule ordering is a lever for LLM security
  adherence*, independent of wording. Novel and cheap to report.
- **In plain words.** "Even without changing a single word, just re-ordering the security rules in
  the prompt can make the model write safer code."

#### C11. Stacking depth vs semantic drift (justifies max_depth)
- **What & how.** New. Pool all mutated genes; plot **SBERT cumulative similarity to the original
  rule vs stacking depth** (min / median / % below the 0.75 adherence threshold). This is the
  evidence for the `max_depth = 4` choice and a semantics-preservation check. Data already
  emitted in `validation_metadata` (`sbert_cum`).
- **Example (already computed).** depth 1–2: ~0% below 0.75; depth 3: 3.7%; **depth 4: 12.2%**;
  depth 5+: 28%. Reading: past depth 4 a non-trivial tail of rules stops meaning what they did →
  cap at 4.
- **Meaning.** Turns an arbitrary hyperparameter into a justified, measured choice — and is itself
  a small result about how far these rules can be perturbed before they cease to be "the rule."
- **In plain words.** "The more we rewrite a rule, the further its meaning drifts. We measured
  where it starts drifting too far and capped edits there."

#### C12. Saturated-ablation dynamics
- **What & how.** New. Frequency of saturated-gene reverts, their acceptance rate, and whether a
  revert improved or preserved f1 (i.e. were those stacked mutations dead weight?). Uses
  `move_type=="reverse"` records with the `(saturated)` tag.
- **Example.** "18% of late-run moves were saturated reverts; 61% were accepted (the dropped
  mutations weren't earning their place) — evidence the ablation prunes dead edits."
- **Meaning.** Validates the new operator and supports the supervisor conversation on reverting
  strategy; also a mild parsimony story ("the search removes edits that stop helping").
- **In plain words.** "When a rule has been rewritten as much as allowed, we test whether undoing
  it helps — often it does, meaning some earlier edits had gone stale."

---

## Part D — Cross-cutting methodology (applies to all of the above)

- **Multiple runs + report the distribution.** Never a single seed. Median + IQR across the 5
  seeds; independent-sample tests, not paired — at a fixed prompt set the per-seed runs are
  independent draws (the code's `mann_whitney_u` docstring makes exactly this argument). _(Arcuri
  & Briand 2014.)_
- **Always pair a test with an effect size.** p-values are unreliable at n=5; Â₁₂ / Cliff's δ are
  informative at any n and are what SBSE reviewers expect. _(Vargha & Delaney 2000.)_
- **Correct for multiplicity where we run families of tests** (per-CWE, per-mutator): Holm–
  Bonferroni on the family, reported as adjusted p. _(Standard; Holm 1979.)_ For the >2-condition
  comparisons (e.g. subsets, or ablation arms) the code already has **Friedman**; if we ever
  compare ≥3 arms across many tasks, add a Nemenyi/critical-difference post-hoc _(Demšar 2006)_ —
  but with only EA vs random this is not needed.
- **Reproducibility.** Fixed seeds, `run_config.json` provenance, and the byte-exact eval-cache
  (already validated) mean every number is regenerable.
- **Honesty about n.** 5 seeds is enough for a credible effect size and a directional test, not
  for a tight p. Say so; lean on Â₁₂ and the anytime curves.

---

## Part E — Literature basis (why each source, with links)

**Statistical methodology for randomised algorithms**
- Arcuri & Briand, _A Hitchhiker's Guide to Statistical Tests for Assessing Randomized Algorithms
  in Software Engineering_, STVR 2014 — the protocol we follow (multiple runs, Mann–Whitney U,
  Â₁₂). https://dl.acm.org/doi/10.1002/stvr.1486
- Vargha & Delaney, _A Critique and Improvement of the CL Common Language Effect Size Statistics_,
  JEBS 2000 — the Â₁₂ effect size. (In `stats.py` already.)
- Demšar, _Statistical Comparisons of Classifiers over Multiple Data Sets_, JMLR 2006 — Friedman +
  Nemenyi/critical-difference, *if* we go to ≥3 arms over many tasks.

**Stochastic optimiser analysis (anytime + multi-objective)**
- Hoos & Stützle, _Stochastic Local Search: Foundations and Applications_, 2004 — run-time
  distributions / anytime characterisation (C2).
- López-Ibáñez, Paquete & Stützle, _Exploratory Analysis of Stochastic Local Search Algorithms in
  Biobjective Optimization_, in _Experimental Methods for the Analysis of Optimization
  Algorithms_, Springer 2010 — the Empirical Attainment Function (C3).
  https://link.springer.com/chapter/10.1007/978-3-642-02538-9_9 · package: https://mlopez-ibanez.github.io/eaf/
- López-Ibáñez et al., _Using the Empirical Attainment Function for Analyzing Single-objective
  Black-box Optimization Algorithms_, arXiv:2404.02031 (2024) — target-ECDF ≈ EAF; grounds C2/C3.
  https://arxiv.org/abs/2404.02031
- Zitzler & Thiele, hypervolume indicator, IEEE TEVC 1999 — Pareto-quality scalar (C3).

**LLM code security (domain + framing)**
- Pearce et al., _Asleep at the Keyboard? Assessing the Security of GitHub Copilot's Code
  Contributions_, IEEE S&P 2022 — foundational: counting vulnerabilities in LLM code via static
  analysis (our exact measurement paradigm).
- _From Vulnerabilities to Remediation: A Systematic Literature Review of LLMs in Code Security_,
  arXiv:2412.15004 (2024) — repair is ~11% of studies (our gap/hook). https://arxiv.org/abs/2412.15004
- _Can You Really Trust Code Copilots? Evaluating LLMs from a Code Security Perspective_,
  arXiv:2505.10494 (2025) — recent security-eval framing. https://arxiv.org/abs/2505.10494

**LLM prompt sensitivity (reordering / wording — C10)**
- Sclar et al., _Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design_
  (FormatSpread), arXiv:2310.11324 (2023). https://arxiv.org/abs/2310.11324
- _The Order Effect: Investigating Prompt Sensitivity to Input Order in LLMs_, arXiv:2502.04134
  (2025) — directly on ordering. https://arxiv.org/abs/2502.04134
- Mizrahi et al., _State of What Art? A Call for Multi-Prompt LLM Evaluation_, TACL 2024 — why
  robustness across semantically-equivalent prompts matters.

**Sampling-based measurement (baseline classification — C6)**
- Chen et al., _Evaluating Large Language Models Trained on Code_ (HumanEval / pass@k unbiased
  estimator), arXiv:2107.03374 (2021). https://arxiv.org/abs/2107.03374

_Note: venues/years above are from a July-2026 web check for the methodology + domain works and
from standing knowledge for the classics (Vargha–Delaney, Demšar, Hoos–Stützle, Zitzler–Thiele,
Pearce). Verify the exact citation string before it goes in the thesis; I can pull BibTeX for any
of these on request._

---

## Part F — Priorities, build order, and decisions for you

**Build order (most leverage first):**
1. **Schema-3 driver + RQ1 headline (C4/C5)** — the number the committee wants; unblocks the
   results section.
2. **RQ3 primary (C1) + anytime curves (C2)** — the EA-vs-random verdict; mostly wired already.
3. **Rule interactions (C9)** — the novelty; needs the best-chromosome + leave-one-out reads.
4. **Move-type ablation (C8) + reordering (C10)** — cheap, already partly computed, strong
   secondary results.
5. **Depth-vs-drift (C11) + saturated-ablation (C12)** — design-justification figures.
6. **Multi-objective EAF/hypervolume (C3)** — only if we keep f2/f3 as headline (see decision #1).
7. Per-mutator (C7), cost/hygiene, validation audit — supporting/appendix.

**Reused as-is:** all of `stats.py`; convergence plotting; per-CWE security metric; cost/cache.
**Runs on your laptop, not DelftBlue:** anything with matplotlib / the `eaf` R package.

**Decisions I need from you:**
1. **Role of f2/f3.** Headline multi-objective (build C3) or supporting/appendix (drop C3, report
   f1 only)? This is the biggest scoping fork.
2. **Interaction evidence depth (C9).** Is co-occurrence + leave-one-out enough, or do you want a
   dedicated controlled experiment (e.g. best-multi-rule vs best-single-rule head-to-head)?
3. **Ablation arms.** Do we add EA-without-order / EA-without-ablation arms to a *later* sweep to
   make C8 a controlled comparison, or keep C8 observational from the main runs?
4. **Java.** Report as an honest "harder domain" result, or invest in a Java-specific analysis
   (different case set / more iterations) to understand *why*?
5. **Scope for the defence.** Which of C1–C12 are headline (in the main results) vs appendix?
