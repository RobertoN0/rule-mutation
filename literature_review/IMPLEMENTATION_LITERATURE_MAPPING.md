# Implementation ↔ Literature Mapping

*Generated 2026-04-15. Last updated 2026-04-24 (Perplexity deep-research pass: Papers 26–40 added; §1.6, §4.5, §4.11, §5.6, §5.7, §5.9, §6.4–6.7, §8.3, §8.5 resolved or eliminated).*

The 40 papers referenced below are the ones analysed in `LITERATURE_REVIEW_ANALYSIS.md` / `THESIS_RELEVANCE.md`. Paper numbers match those files.

This document is a **mapping**, not a new literature search. Anything marked **GAP** is an action item: something we rely on but currently justify only by engineering judgment.

---

## How to read this document

Each implementation choice is categorised into one of three tiers:

- **✅ Validated** — an explicit, named citation from our 25-paper set directly supports this choice (not just the general area).
- **🟡 Partial** — literature supports the general approach but not the specific parameter/threshold/variant we chose.
- **❌ GAP** — no reviewed paper justifies this. We rely on engineering judgment, ad-hoc empirical tuning, or convention.

Inside each tier, choices are grouped by subsystem (search, mutation, validation, fitness, generation, evaluation).

---

## Summary dashboard

*(Revised 2026-04-17 after supervisor-prep pass; revised again 2026-04-24 after Perplexity deep-research pass: lexicographic acceptance replaces weighted sum; CodeBLEU replaces NL-SBERT for code_div; DYTS/D-UCB added; mutator-only bandit factorization; CWE reporting stratification eliminated; CyberSecEval v2 citation corrected.)*

| Subsystem | ✅ Validated | 🟡 Partial | ❌ GAP |
|---|---|---|---|
| Search algorithm | 4 | 1 | 1 |
| Mutation operators | 6 | 2 | 4 |
| Safe-zone / parsing | 1 | 1 | 1 |
| Quality validator | 8 | 2 | 1 |
| Fitness function | 4 | 2 | 1 |
| Pool / bandit | 6 | 1 | 0 |
| Generation setup | 2 | 1 | 3 |
| Evaluation protocol | 3 | 1 | 2 |
| **Totals** | **34** | **11** | **13** |

Gaps down from 22 to **13** after Perplexity deep-research pass. Remaining concentrations: (a) mutator hyperparameters (aug_p fractions, filler-word lists — §2.11, §2.12), (b) generation sampling parameters (top_p, max_new_tokens — §7.4, §7.5, §7.6), (c) N_CASES and N_ITERATIONS power analysis (§8.6, §8.7), (d) readability-delta criterion (§4.12), (e) two-phase retrieval pipeline (§9). These are engineering details expected to remain uncited; see §12 for the deliberate out-of-scope list.

---

## 1. Search algorithm

### ✅ Validated

**1.1 Hill climbing as the base SBST loop**
- *Choice:* Single-objective stochastic hill climb over mutated rule text; accept on improvement.
- *Citation:* Paper 3 (Hyun et al. 2025) — uses SBST over MR selection; shows search-based selection outperforms random. Paper 19 (SPRIG) — directly analogous hill-climb over system prompts.
- *Confidence:* Strong. Two papers in the reviewed set use the same structural algorithm on closely related problems.

**1.2 Iterative accept-on-improvement semantics**
- *Choice:* Adopt candidate if fitness strictly improves, else discard.
- *Citation:* Paper 3 (Hyun et al. 2025) — standard SBST acceptance; Paper 19 (SPRIG) — fitness-guided selection step.

**1.3 Mutations compound on current best (not original)**
- *Choice:* `CurrentBestTracker` keeps the accepted text per rule so later mutations stack on earlier accepted ones.
- *Citation:* Paper 3 (Hyun et al. 2025, Table 1) — "1 to 4 perturbation functions in Cmb_MR" explicitly defines combinatorial chaining on the parent candidate.

### 🟡 Partial

**1.5 Random restarts from HillClimbConfig**
- *Choice:* `random_restarts` knob to escape local optima.
- *Support:* Standard SBST technique. No specific paper in our set validates it for this task; user flagged it as a "deeper-experiments" item, not current-run.

### ❌ GAP

**1.4 Early-stop after N iterations without improvement**
- *Choice:* `early_stop_no_improvement` parameter on HillClimbConfig.
- *Status:* **Not actively used in current experiments** (user-confirmed 2026-04-17). Likely dead parameter; candidate for removal.
- *Gap:* No paper in our set validates the specific threshold (5). Since it's not used, low-priority gap.

**1.6 Lexicographic acceptance (primary: semgrep_delta; secondary: code_divergence)** ✅ RESOLVED 2026-04-24
- *Choice:* Accept if `delta_s > 0`; accept secondary if `delta_s == 0 AND delta_c > 0`; else reject. No weighted composite, no Pareto front.
- *Citation:* **Paper 26 (Chen & Li, TOSEM 2022)** — empirically shows weighted sums miss Pareto-optimal solutions in 77% of SE benchmarks; provides the empirical case for abandoning α/β/γ weights. **Paper 28 (Miettinen 1999)** — textbook chapter 3.7 formalizes lexicographic ordering as the theoretically correct scalarization when objectives have strict asymmetric priority. **Paper 21 (ATheNA)** — `f_AT` (Semgrep) primary / `f_MAN` (code_div) secondary is the formal hybrid-fitness analogue. **Paper 19 (SPRIG)** — confirms fitness-guided selection over a system-prompt search space.
- *Rule_div status:* demoted to quality gate constraint (SBERT ≥ 0.75); no longer a fitness term — see §4.8.
- *Code_div status:* secondary fitness signal, computed via CodeBLEU — see §5.3, §5.9.

---

## 2. Mutation operators

### ✅ Validated

**2.1 SynonymReplacementMutator (WordNet-backed via nlpaug)**
- *Citation:* Paper 3 (Hyun et al. 2025) — identified as a silver-bullet MR. Paper 4 (AUGMENT) — used as a paraphrase primitive. Paper 9 (METAL) — word-level MR.

**2.2 AddRandomWordMutator**
- *Citation:* Paper 3 (Hyun et al. 2025) — silver-bullet MR. Paper 9 (METAL) — insertion MR.

**2.3 SectionReorderMutator (shuffle mode)**
- *Citation:* Paper 2 (LLMORPH) MR-19 / MR-107 — reorder MRs. Paper 9 (METAL) — sentence-level reordering.

**2.4 NegationInjectionMutator**
- *Citation:* Paper 2 (LLMORPH) MR-48 / MR-76 — negation-injection MRs.

**2.5 VoiceChangeMutator (active → passive)**
- *Citation:* Paper 4 (AUGMENT) — voice-change is one of AUGMENT's listed paraphrase types. Paper 2 (LLMORPH) — MR-equivalent transformations.

**2.6 ParaphraseMutator (LLM few-shot with linguistic constraints)**
- *Citation:* Paper 2 (LLMORPH) MR-51. Paper 4 (AUGMENT) — synonym-constraint paraphrase prompting. Paper 18 (Artemis) validates LLM-ensemble mutation over random mutation.

### 🟡 Partial

**2.7 SectionReorderMutator (degrade mode — move security-critical section to end)**
- *Support:* Paper 2 (LLMORPH) documents recency bias as an architectural property; Paper 5 (Heo et al.) supports the phrasing-dimension-dominance theory. Neither paper names or evaluates a "move to end to exploit recency bias" mutator specifically — we are extrapolating from observed LLM behaviour.

**2.8 LLM-based mutators reuse the generation backbone (Qwen2.5-Coder-32B)**
- *Support:* Paper 18 (Artemis) uses LLM-ensemble mutation. Paper 25 (zkCraft) uses LLM as zero-shot mutation oracle. Neither specifically validates reusing the *same model under test* as the mutator — we do so for VRAM efficiency, not because a paper recommends it.

### ❌ GAP

**2.9 FluffMutator (bureaucratic preamble/postamble + verb weakening)** — *scheduled for removal*
- *Gap:* Thesis original. Closest analogue is Paper 10 (Tone and Politeness) at a pragmatic level, but Paper 10 does not define a mutator of this form.
- *Status (2026-04-17):* User-confirmed to be retired. Will not survive the next round of mutator refinement. Keeping in the mapping only so the decision trail is visible; should not require a literature citation going forward.

**2.10 VerbWeakeningMutator (MUST → should ideally, NEVER → try to avoid, etc.)** — *scheduled for removal / reshape*
- *Gap:* Thesis original. Paper 10 (Tone) and Paper 4 (AUGMENT) touch on register shifting but do not prescribe this specific mapping table.
- *Status (2026-04-17):* User-confirmed to be retired or reshaped in favour of cited mutators. The hardcoded `VERB_WEAKENING_MAP` is explicitly targeted for removal per the user's "less hardcoding is better" rule.

**2.11 Specific hyper-parameters inside rule-based mutators**
- *Gap:*
  - `SynonymReplacement.aug_p = 0.3` — no literature justification for this fraction.
  - `AddRandomWord.aug_p = 0.1` — no literature justification.
  - Negation stopword list (~16 entries) for AddRandomWord — curated by the author; Paper 2 (LLMORPH) defines *negation injection* as a distinct MR, which is the reason we exclude these words, but the exact list is ours.
  - `_SimpleWordInserter` filler-word list (20 adverbs/connectors) — chosen by the author; no paper enumerates this list.

**2.12 `FLUFF_PREFIXES` / `FLUFF_SUFFIXES` template contents**
- *Gap:* The four preamble templates and four postamble templates are hand-authored. No paper prescribes bureaucratic-register templates of this form.

---

## 3. Safe-zone contract and rule parsing

### ✅ Validated

**3.1 Concept of mutation-immutable zones (frontmatter + fenced code + inline code)**
- *Citation:* Paper 20 (SCAFFOLD-CEGIS) — "semantic anchoring" of regions that must not be perturbed. Our `ParsedRule.get_mutable_prose()` is explicitly a lightweight form of that principle.

### 🟡 Partial

**3.2 Frontmatter = immutable, fenced code = immutable, inline code = immutable, prose = mutable**
- *Support:* The general principle comes from Paper 20, but the specific three-way split (frontmatter / fenced / inline) is driven by the Markdown format of CodeGuard rules, not by a paper.

### ❌ GAP

**3.3 `mask_inline_code` / `unmask_inline_code` placeholder protocol**
- *Gap:* Implementation detail — how we mask `` `code` `` spans before running nlpaug and restore afterwards. Engineering choice, no citation.

---

## 4. Quality validator (`MutationQualityValidator`)

### ✅ Validated

**4.1 Three-criteria quality-gating framework (adherence + semantic similarity + fluency)**
- *Citation:* Paper 4 (AUGMENT) — direct source. The validator is an implementation of AUGMENT's framework.

**4.2 SBERT cosine similarity as the semantic-similarity gate**
- *Citation:* Paper 4 (AUGMENT) — uses SBERT. Paper 1 (191-MR Catalog) — validates SBERT for MR oracle purposes.

**4.3 Perplexity ratio as the fluency gate**
- *Citation:* Paper 4 (AUGMENT) — perplexity ratio. Paper 6 (LAP) — provides calibration (ratio ≤ 2.0 ↔ SBERT ≥ 0.80 in >90 % of cases).

**4.4 Per-mutator adherence function (each mutator gets its own check)**
- *Citation:* Paper 4 (AUGMENT) — describes per-mutator adherence tests; our `_adherence_*` functions are that pattern.

### 🟡 Partial

**4.5 SBERT model = `sentence-transformers/all-mpnet-base-v2`** ✅ RESOLVED 2026-04-24
- *Citation:* **Paper 31 (MTEB, Muennighoff et al. EACL 2023)** — `all-mpnet-base-v2` ranks top-tier on the STS (Symmetric Text Similarity) subset, which is the exact task type of rule-pair similarity comparison. **Paper 32 (Sentence-BERT, Reimers & Gurevych EMNLP 2019)** — foundational architecture reference for all SBERT usage.
- *Key findings from literature pass:* AUGMENT (Paper 4) actually uses `stsb-distilroberta-base-v2`, a weaker model than `all-mpnet-base-v2` on MTEB STS — the thesis's model choice is already stronger than the cited prior art. Perplexity's recommendation `multi-qa-mpnet-base-dot-v1` uses **dot-product similarity** (asymmetric retrieval task), not cosine, making it architecturally wrong for symmetric rule-pair STS.
- *Pilot ablation planned:* **Paper 33 (SecureBERT 2.0, Aghaei et al. 2025)** — domain-specific alternative to test on 30–50 (original rule, paraphrased rule) pairs from existing artifacts. If Spearman correlation with `all-mpnet-base-v2` is ≥ 0.90, the current model is confirmed. Otherwise, SecureBERT 2.0 may be preferred for final experiments.

**4.6 Security-keyword-retention criterion**
- *Support:* This is a thesis extension to AUGMENT's framework, explicitly framed as "adding a 4th criterion." Paper 4 does not include this criterion. The *idea* of preserving domain-sensitive vocabulary is partially supported by Paper 20 (SCAFFOLD-CEGIS anchoring) and Paper 23 (MST-wi structural invariants).

**4.7 Inline-code retention criterion**
- *Support:* Falls out of Paper 20's anchoring principle. Threshold = 1.0 (exact retention) is our engineering choice.

### ✅ Validated (resolved 2026-04-17 by adopting AUGMENT defaults)

**4.8 SBERT threshold ≥ 0.75 (AUGMENT default)** — *was 0.80, code change pending*
- *Citation:* Paper 4 (AUGMENT) — exact value used. Paper 6 (LAP) provides empirical calibration (perplexity ratio ≤ 2.0 ↔ SBERT ≥ 0.80 in >90% of cases).
- *Action item:* update `MutationQualityValidator.DEFAULT_SBERT_THRESHOLD` in [quality.py](thesis/rule-mutation/src/mutation/quality.py) from 0.80 to 0.75. All prior experiment runs that used 0.80 should be re-noted as having applied a stricter threshold than the literature default.

**4.9 Perplexity ratio threshold ≤ 2.0 (AUGMENT default)** — *was 2.5, code change pending*
- *Citation:* Paper 4 (AUGMENT) and Paper 6 (LAP) both use ≤ 2.0.
- *Action item:* update `MutationQualityValidator.DEFAULT_PERPLEXITY_THRESHOLD` in [quality.py](thesis/rule-mutation/src/mutation/quality.py) from 2.5 to 2.0.

### ❌ GAP

**4.10 Keyword-retention threshold ≥ 0.70**
- *Gap:* Thesis choice. No paper motivates 0.70 vs 0.60 or 0.80.

**4.11 Security keyword vocabulary (corpus-derived lexicon)** ✅ RESOLVED 2026-04-24
- *Choice:* Replace `_SECURITY_KEYWORDS` frozenset with a corpus-derived lexicon built once at pipeline startup from: (1) inline-code spans in each rule (`ParsedRule.get_inline_code_tokens()`), (2) frontmatter tag values, (3) CWE IDs from frontmatter. These are author-validated identifiers — rule authors marked them as technical anchors. No hand-curation or external download required.
- *Citation:* **Paper 20 (SCAFFOLD-CEGIS)** — semantic anchoring principle; inline-code spans are exactly the "security-critical elements" that must not drift. **Paper 23 (MST-wi)** — structural invariants principle; preserving vocabulary that is structurally marked (via backtick formatting) is a structural-invariant constraint. **MITRE CWE** (standards reference, not a paper) — CWE IDs in frontmatter are the authoritative vulnerability taxonomy source.
- *Optional supplement:* Download MITRE CWE XML once, map CWE ID → CWE name (e.g., "CWE-79" → "cross-site scripting"). Pure data lookup, no classifier, adds ~50 short phrases to the lexicon.
- *Threshold note:* The 0.70 retention threshold (§4.10) may need recalibration as the derived lexicon grows from ~35 to ~100+ terms. Flag in Threats to Validity.

**4.12 Readability-delta criterion**
- *Gap:* Fifth criterion in the code (`quality.py` has *five* criteria, not three — 2026-04-15 audit). The readability delta is not in AUGMENT. Choice of readability metric and threshold is undocumented in the reviewed literature.

---

## 5. Fitness function

*Revised 2026-04-17: γ-term (code_divergence) **kept**, reference code source switched to iteration-0 Qwen baseline.*
*Revised 2026-04-24 (Perplexity pass): **weighted-sum dropped entirely**. New design: lexicographic acceptance. `rule_divergence` demoted to quality gate. `code_divergence` is secondary fitness signal via CodeBLEU.*

**Current (post-Perplexity-pass) design:**
- Primary signal: `semgrep_delta = new.semgrep_score − current.semgrep_score`
- Secondary signal: `code_div = 1.0 − codebleu([baseline_code], [mutated_code])` (via `k4black/codebleu`)
- Acceptance rule: `delta_s > 0` → accept (reward 1.0); `delta_s == 0 AND delta_c > 0` → accept (reward 0.5); else → reject (reward 0.0)
- `rule_divergence` (SBERT ≥ 0.75) is a **quality gate** only — not a fitness term (see §4.8)

**Old formula (retired):** `composite = 1.0·semgrep_delta + 0.3·rule_div + 0.2·code_div` — see §5.6 for why this was dropped.

### ✅ Validated

**5.1 Use a SAST tool (Semgrep) as the primary objective signal**
- *Citation:* Paper 21 (ATheNA) — automated oracle `f_AT`. Paper 24 (SAST-MT) — uses SAST as an oracle target, also flags it has false-negatives (threat to validity).

**5.2 Composite fitness that mixes Semgrep with auxiliary signals**
- *Citation:* Paper 3 (Hyun et al. 2025) — `Context_ASR × PerturbationQuality` is the structural analogue. Paper 9 (METAL) — EFM metric. Paper 21 (ATheNA) — formalises `f_AT × f_MAN`.

**5.3 Code-divergence component (CodeBLEU between generated code and iteration-0 reference)**
- *Citation:* **Paper 29 (CodeBLEU, Ren et al. 2020)** — the metric definition, default weights, and language-specific AST/data-flow matching. Paper 9 (METAL) — output-space divergence as a fitness signal. Paper 17 (SoS) — multi-objective fitness with secondary quality objective.
- *Architecture (2026-04-17):* reference code is captured at iteration 0 from the same Qwen baseline run; see §8.2.
- *Architecture (2026-04-24):* `code_div = 1.0 − calc_codebleu([baseline], [mutated], lang=lang, weights=(0.25,0.25,0.25,0.25))`. Language tag from CyberSecEval v2 test-case metadata (confirmed available). Replaces NL-SBERT-on-code which was the §5.9 gap.

### 🟡 Partial

**5.4 SEVERITY_WEIGHTED (ERROR × 3, WARNING × 1, INFO × 0)**
- *Support:* Weighted severity aggregation is conventional in SAST benchmarking. No specific paper in our set prescribes the 3/1/0 weights — these are Semgrep-community defaults.

**5.5 Delta formulation (candidate − baseline) instead of absolute count**
- *Support:* Paper 24 (SAST-MT) implicitly motivates this — absolute SAST counts are unreliable due to FN/FP, but *relative* deltas are more robust. Not a direct recommendation, but a defensible extrapolation.

### ❌ GAP

**5.6 Composite weights α = 1.0, β = 0.3, γ = 0.2** ✅ ELIMINATED 2026-04-24
- *Resolution:* Weighted-sum composite dropped entirely per Thread 1 decision. **Paper 26 (Chen & Li, TOSEM 2022)** provides the empirical citation: weighted sums miss Pareto-optimal solutions in 77% of SE benchmarks; small weight perturbations change which solution is selected. **Paper 28 (Miettinen 1999)** provides the theoretical alternative: lexicographic ordering is the correct scalarization when objectives have strict asymmetric priority. No sensitivity sweep needed — weights no longer exist.
- *Status:* Dead code in `composite_fitness.py`. The α/β/γ constants should be removed in the next code cleanup pass.

**5.7 `1 − sbert_rule_similarity` as the rule-divergence signal (β component)** ✅ ELIMINATED 2026-04-24
- *Resolution:* `rule_divergence` has been demoted from a fitness term to a quality gate constraint (SBERT ≥ 0.75 in `MutationQualityValidator`). The β-weighted fitness term no longer exists. The SBERT computation itself is preserved in the validator — it just no longer feeds into a composite weighted sum.
- *Implication:* `raw_rule_divergence` in `composite_fitness.py` becomes dead code in the fitness path (retained for logging/debugging). The architectural reason for this demotion: every mutator changes rule text by construction, so rule_div would be monotonically increasing under compounding — a trivially satisfiable tie-breaker that adds no information.

**5.8 Reference-code source change — track the cleanup**
- *Status (2026-04-17):* the external-reference path from `InterestingCase.control_code` into `CompositeFitnessEvaluator(reference_codes=...)` becomes dead code in the fitness pipeline. The `control_code` JSON field is retained for non-fitness uses (debugging, thesis figures).
- *Code touchpoints:*
  - [hill_climber.py:794-797](thesis/rule-mutation/src/optimizer/hill_climber.py#L794-L797) — extend the existing iter-0 loop to also cache `eval_r.generated_code` into `self.composite_evaluator.reference_codes[tc_id]`.
  - Caller (e.g. `scripts/experiments/run_with_rules_map.py`) — construct `CompositeFitnessEvaluator(reference_codes={}, ...)`; stop pre-loading from interesting_cases.
  - No changes to [composite_fitness.py](thesis/rule-mutation/src/evaluation/composite_fitness.py) internals — the dict contract is unchanged.

**5.9 CodeBLEU for code_divergence** ✅ RESOLVED 2026-04-24
- *Citation:* **Paper 29 (CodeBLEU, Ren et al. 2020)** — the metric is specifically designed for code comparison and includes AST and data-flow components that NL-SBERT lacks. `k4black/codebleu` PyPI package provides a drop-in implementation with first-class Python and Java support.
- *Old gap (NL-SBERT-on-code):* closed. Natural-language SBERT (`all-mpnet-base-v2`) applied to code is architecturally mismatched — CodeBLEU's AST and data-flow matching are purpose-built for the task.
- *Implementation note:* `calc_codebleu([baseline_code], [mutated_code], lang="python"|"java", weights=(0.25,0.25,0.25,0.25))`. Language tag sourced from CyberSecEval v2 metadata. Default weights per Ren et al. 2020; fine-tuning is future work.

---

## 6. Multi-mutator pool and bandit

### ✅ Validated

**6.1 UCB1 bandit for mutator selection**
- *Citation:* Paper 19 (SPRIG) — UCB-based pruning for component/mutator selection in system-prompt optimisation. Standard Auer et al. 2002 (not in reviewed set, but referenced by Paper 19).

**6.2 Max mutation depth = 4 per rule**
- *Citation:* Paper 3 (Hyun et al. 2025, Table 1) — "1 to 4 perturbation functions in Cmb_MR."

**6.3 Combinatorial chaining (compound multiple mutators on one rule)**
- *Citation:* Paper 3 (Hyun et al. 2025) — Priority-1 extension in our plan.

### ✅ Validated (resolved 2026-04-24)

**6.4 UCB1 arms defined as mutator-only (9 arms)** ✅ RESOLVED 2026-04-24
- *Choice (updated):* Arms factorized over mutators only (`mutator_name`), not over the joint `(rule_id, mutator_name)` space. With 30–50 SLURM iterations, ~90 joint arms give < 1 pull/arm — the bandit cannot learn. 9 mutator-only arms give 3–4 pulls/arm — a viable learning signal.
- *Citation:* **Paper 19 (SPRIG)** — UCB-based pruning for component/mutator selection operates at the mutator/component level, not joint (target × mutator). The mutator-only factorization is directly analogous. **Paper 26 (Chen & Li)** — the joint factorization would have introduced the same budget fragility as weighted sums; consolidating to mutator-only is the same "reduce complexity to what the budget supports" principle.
- *Rule selection:* becomes a separate deterministic policy (round-robin default). Not a bandit concern.

**6.5 UCB1 exploration constant `c = √2`** ✅ RESOLVED 2026-04-24
- *Citation:* **Paper 34 (Auer, Cesa-Bianchi, Fischer 2002)** — canonical source of the `c = √2` exploration constant with the formal O(log T) regret proof. This was previously implicitly cited via SPRIG; now has a direct citation.
- *Note:* Under the Thread 4 design, UCB1 is the **comparison baseline** rather than the primary strategy. D-UCB and DYTS replace it for main experiments. The exploration constant is thus secondary — it matters for the baseline comparison, not for production runs.

**6.6 Reward scheme: {0.0, 0.5, 1.0} — no clipping needed** ✅ RESOLVED 2026-04-24
- *Choice (updated):* 3-level scalar reward tied to the lexicographic acceptance rule: primary accept → 1.0; secondary accept → 0.5; reject → 0.0. No negative rewards, so clipping is moot.
- *Citation:* **Paper 34 (Auer et al. 2002)** — UCB1 reward is bounded in [0, B]; our reward scheme is bounded in [0, 1.0] by construction. **Paper 36 (DYTS, Sun & Li 2020)** — Beta posterior updates with r ∈ [0, 1] assume this bounded range.
- *Old gap (max(0, ·) clipping):* closed. The clipping was a workaround for negative composite rewards; those no longer exist under the lexicographic design.

### 🟡 Partial

**6.7 GREEDY_BATCH strategy (mutate all rules per iteration, accept-all on improvement)**
- *Support:* Custom strategy. **Paper 17 (SoS)** — crossover operator blending two parent prompts (one high-fitness, one high-quality) is the closest analogue: it evaluates multiple candidates per iteration and selects based on improvement. GREEDY_BATCH is simpler (evaluate all rules in parallel, accept individually) but shares the "multiple candidates per step" structure.
- *Status (2026-04-24):* Remains 🟡. The closest analogue (SoS crossover) is a population-based operator rather than a rule-parallel batch — the analogy is partial. No paper defines this exact variant.

### New: Non-stationary bandit strategies (planned)

**6.8 D-UCB (Discounted UCB) strategy**
- *Citation:* **Paper 35 (Garivier & Moulines, ALT 2011)** — direct source. Handles gradual drift in reward distributions via γ-discount on all historical observations.
- *Hyperparameters:* γ ∈ (0.9, 0.99), ξ = 0.5 (Garivier & Moulines default), B = 1.0 (reward upper bound).
- *Status:* ❌ Planned; implement as `ducb` strategy in `BanditStrategy` abstraction.

**6.9 DYTS (Dynamic Thompson Sampling) strategy — default**
- *Citation:* **Paper 36 (Sun & Li 2020)** — direct source. Fewer hyperparameters (γ only); outperforms UCB family in sparse-reward regimes. **Paper 39 (Chapelle & Li, NeurIPS 2011)** *(optional)* — empirical basis for Thompson sampling in sparse-reward settings.
- *Hyperparameters:* γ ∈ (0.9, 0.99). Prior (α₀, β₀) = (1, 1).
- *Status:* ❌ Planned; implement as `dyts` strategy in `BanditStrategy` abstraction. Default for main experiments.

---

## 7. Generation setup

### ✅ Validated

**7.1 Temperature = 0 for code generation (deterministic)**
- *Citation:* Paper 13 (PERSIST) — high-temperature CoT amplifies behavioural instability; deterministic decoding isolates mutation effect. Paper 8 (Code MT) — single-generation paradigm.

**7.2 Single-model-under-test (no cross-model validation in this pipeline)**
- *Citation:* Paper 3 (Hyun et al. 2025) — single-model setup in their SBST evaluation.

### 🟡 Partial

**7.3 Qwen2.5-Coder-32B-Instruct as the generation model**
- *Support:* Cisco's validation blog (thesis motivation) used a different model. Our choice is driven by DelftBlue GPU availability (A100, 32B fits). No reviewed paper prescribes Qwen2.5-Coder — but none forbid it either; it is a reasonable strong-code-LLM choice.

### ❌ GAP

**7.4 Default sampling parameters besides temperature (top_p, max_new_tokens, etc.)**
- *Gap:* Values in `delftblue_local_backend.py` are engineering defaults, not cited.

**7.5 Quantization setting for inference**
- *Gap:* SLURM script exposes `QUANTIZATION` as an env var. Our default choice is not grounded in a paper.

**7.6 Prompt templating for code generation (how the rule is injected into the chat template)**
- *Gap:* The exact system/user message structure is our convention. Paper 19 (SPRIG) discusses system-prompt optimisation but doesn't prescribe template structure for our case.

---

## 8. Evaluation protocol

### ✅ Validated

**8.1 Per-language reporting (Python + Java) as primary stratification axis**
- *Choice (updated 2026-04-24):* Language (Python / Java) replaces CWE as the primary reporting axis. Two clean groups, natural statistical comparison (vs. 20+ CWE groups). Per-CWE reporting is retired from the design.
- *Citation:* Paper 10 (Tone) — aggregation hides per-domain effects; per-language is the domain split. Paper 14 (CAIBench) — multi-domain cybersecurity evaluation. **Paper 37 (CyberSecEval v2)** — Python + Java are the two programmatic languages in the benchmark.
- *CWE note:* CWE is retained as a **retrieval join key** between test cases and rules (kept unchanged in the pipeline). CWE is only retired as a *reporting* stratification axis. See §8.5 and §9.1 for this distinction.

**8.2 Baseline control (original rule) computed fresh at iteration 0** — *clarified 2026-04-17*
- *How it works:* the baseline is **not** loaded from an external file. [hill_climber.py:777-797](thesis/rule-mutation/src/optimizer/hill_climber.py#L777-L797) runs `_evaluate_with_per_prompt_rules` with `target_rule_id=None, mutator_fn=None, phase="baseline"` before the iteration loop starts. Per-case Semgrep fitness is cached into `self._baseline_fitness_per_case`, and **per-case generated code will additionally be cached into `self.composite_evaluator.reference_codes` in the same loop** (see §5.8). Both caches are looked up by each subsequent iteration: α uses the fitness cache, γ uses the code cache.
- *Implication:* the pipeline is fully self-contained per run. Baseline Semgrep score and γ reference code come from the same iteration-0 generation → one consistent baseline for both α and γ. External `interesting_cases.control_code` is retained for debugging / thesis figures but no longer needed by the fitness pipeline.
- *Citation:* Paper 17 (SoS) — baseline-relative selection. Paper 20 (SCAFFOLD-CEGIS) — comparison to un-mutated baseline is the key experimental primitive.

### 🟡 Partial

**8.3 CyberSecEval v2 as the primary evaluation dataset** ✅ RESOLVED 2026-04-24
- *Citation:* **Paper 37 (Bhatt et al. 2024, arXiv:2404.13161)** — CyberSecEval **v2** is the correct citation for `walledai/CyberSecEval`. Version-corrected from Perplexity's implicit v1 (arXiv:2312.04724, Bhatt et al. 2023) attribution. The HuggingFace dataset `walledai/CyberSecEval` with `instruct` config is explicitly v2.
- *Multi-dataset strategy:* **Paper 38 (LLMSecEval, Tony et al. MSR 2023)** — cross-check dataset for secondary robustness experiment. Linear wall-time (separate SLURM submission), not multiplicative. Paper 40 (SecurityEval, Siddiq & Santos 2022) *(optional)* — third cross-check if needed.

**8.4 Separation of "interesting cases" (filtered) vs full prompt set**
- *Support:* Paper 3 (Hyun et al. 2025) and Paper 11 (STELLAR) both do test-case selection/prioritisation, but our specific filtering criteria are a pipeline artefact, not a cited method.

### ❌ GAP

**8.5 CWE-based stratification of the test-case universe** ✅ ELIMINATED 2026-04-24
- *Resolution:* CWE-based **reporting** stratification removed from the design (Thread 6 decision). The gap stops existing because the design choice is simply retired. CWE subdivision was a leftover from cloning Cisco's CodeGuard validation pipeline structure; it was never validated as the right stratification axis for the thesis's phrasing-brittleness claim.
- *What remains:* CWE is kept as a **retrieval join key** (`rule_retrieval_mapping_local.py`'s `CWE → rules_map`) — a free metadata join that requires no design justification. `LIMIT_PER_CWE` becomes `LIMIT_PER_LANGUAGE` or total `LIMIT_CASES` cap (code change pending).
- *Reporting axis:* Python + Java language split (§8.1). Two groups, clean statistical comparison.

**8.6 Number of test prompts per experiment run (N_CASES)**
- *Gap:* The specific values used in SLURM scripts (5–96–222–1916) are driven by wall-time budget, not by a statistical power argument in the literature.

**8.7 Number of hill-climb iterations (`N_ITERATIONS`)**
- *Gap:* Plan recommends "50 for initial experiments, 150 for full runs" based on "8 rules × 4 depth × ~20 % acceptance." The 20 % acceptance assumption is not literature-backed; it is an empirical guess.

---

## 9. Dataset / input pipeline

### ❌ GAP (entire subsystem)

**9.1 Retrieval-map construction (CWE → rules) via a separate Qwen2.5-Coder-32B run**
- *Gap:* Our two-phase architecture (retrieval-then-mutate) is engineered around DelftBlue's job-length limits and HF cache mechanics. No paper in our set prescribes this two-phase pipeline.

**9.2 `LIMIT_PER_CWE = 5` default**
- *Gap:* Chosen to keep retrieval runs tractable (Paper 14 CAIBench suggests multi-domain evaluation, but not this specific cap).

**9.3 `alwaysApply` rule handling (crypto-algorithms / digital-certificates / hardcoded-credentials always injected)**
- *Gap:* A CodeGuard platform convention, not a thesis-literature choice.

---

## 10. Mutator-specific implementation details (deep gaps)

The following details are inside individual mutators and, while not load-bearing for the thesis argument, would ideally be traceable to literature for a defensive reviewer. **All of these are currently uncited.**

| Detail | Location | Gap |
|---|---|---|
| nlpaug SynonymAug backend (WordNet vs embeddings) | `rule_based.py:SynonymReplacementMutator` | Choice of WordNet over contextual embeddings is a fallback after transformers>=5.0 broke `ContextualWordEmbsAug`; no paper prefers WordNet for our task. |
| `aug_p` values (0.3 synonym, 0.1 insertion) | `rule_based.py` | No citation for these fractions. |
| Filler-word list | `rule_based.py:_SimpleWordInserter._FILLER_WORDS` | 20 hand-picked words. |
| Negation-stopword list for AddRandomWord | `rule_based.py:_NEGATION_STOPWORDS` | 16 hand-picked words. |
| `_SECURITY_KEYWORDS` for SectionReorder degrade mode | `rule_based.py` | Hand-picked list — distinct from the validator's keyword list above. Potential consistency issue. |
| Few-shot prompt templates for LLM mutators | `llm_based.py` | AUGMENT-style approach is cited; the exact example text and the exact constraints are authored, not from any paper. |
| Jaccard / word-count bounds in per-mutator adherence checks | `quality.py` | Heuristic bounds (e.g. "paraphrase Jaccard ∈ [0.3, 0.8]") are our tuning choices. |
| LLM-mutation retry logic in `validate_with_retry` | `quality.py` | Engineering mechanism — retry on failure, back off after N tries. No cited protocol. |

---

## 11. Priority ranking of gaps to close

*Revised 2026-04-17 after supervisor-prep pass.*
*Revised 2026-04-24 after Perplexity deep-research pass. Items marked ✓ RESOLVED below were all closed in this pass.*

**✓ RESOLVED — Perplexity pass (2026-04-24)**
- ~~§1.6 Single-objective vs Pareto~~ → Lexicographic acceptance (Chen & Li P26, Miettinen P28, ATheNA P21).
- ~~§4.5 SBERT model choice~~ → `all-mpnet-base-v2` justified by MTEB (P31) + Sentence-BERT (P32).
- ~~§4.11 `_SECURITY_KEYWORDS` frozenset~~ → corpus-derived lexicon (Papers 20, 23, MITRE CWE).
- ~~§5.6 Composite weights α/β/γ~~ → Weights eliminated; lexicographic replaces weighted sum.
- ~~§5.7 rule_div as fitness β term~~ → rule_div demoted to quality gate; β term retired.
- ~~§5.9 NL-SBERT-on-code for γ~~ → CodeBLEU (P29) replaces NL-SBERT for code_divergence.
- ~~§6.5 UCB1 c = 1.41~~ → Auer et al. 2002 (P34) canonical citation.
- ~~§6.6 Clipping negative rewards~~ → Auto-resolved by 3-level reward {0, 0.5, 1.0}.
- ~~§8.3 CyberSecEval citation~~ → Version-corrected to v2 (Bhatt et al. 2024, P37).
- ~~§8.5 CWE stratification~~ → Eliminated; language replaces CWE for reporting.

**✓ RESOLVED — Supervisor-prep pass (2026-04-17)**
- ~~§4.8 SBERT 0.80 threshold~~ → reverted to AUGMENT 0.75.
- ~~§4.9 Perplexity 2.5 threshold~~ → reverted to AUGMENT 2.0.
- ~~Model-mismatched γ reference~~ → reference_codes from iteration-0 Qwen baseline.

**REMAINING GAPS — implementation pending (code changes not yet made)**

The following are code implementation tasks, not literature tasks — papers exist; code doesn't yet:

1. **Lexicographic acceptance rule** (§1.6) — papers done; `hill_climber.py` acceptance logic needs rewrite.
2. **CodeBLEU for code_div** (§5.9) — papers done; `composite_fitness.py` needs CodeBLEU integration.
3. **D-UCB + DYTS strategies** (§6.8, §6.9) — papers done; `BanditStrategy` abstraction + implementations needed.
4. **Mutator-only arm factorization** (§6.4) — papers done; bandit arm indexing in `hill_climber.py` needs update.
5. **corpus-derived lexicon** (§4.11) — papers done; `build_security_lexicon()` helper needed in `quality.py`.
6. **CWE → language stratification** (§8.5) — papers done; `LIMIT_PER_CWE` → `LIMIT_PER_LANGUAGE` change needed.
7. **SecureBERT 2.0 ablation** (§4.5) — papers done; 30–50 rule pairs ablation run needed (~1 day).
8. **LLMSecEval ingestion adapter** (§8.3) — papers done; adapter script needed (~3–4 hours).

**MEDIUM PRIORITY — remaining uncited items (expected to stay uncited)**

9. **FluffMutator + VerbWeakeningMutator (§2.9, §2.10).** Scheduled for removal. Once removed, the gap disappears.
10. **Readability-delta criterion (§4.12).** Fifth validator criterion with no AUGMENT-style citation. Low user-priority defensive-review item.
11. **Mutator hyperparameters (§2.11).** `aug_p = 0.3/0.1`, negation-stopword list (~16 entries), filler-word list (~20 words). Engineering choices; no paper prescribes these values. Acceptable to leave uncited.
12. **Generation sampling parameters (§7.4, §7.5, §7.6).** top_p, max_new_tokens, quantization, prompt template. Engineering defaults; not expected to have literature citations.
13. **N_CASES and N_ITERATIONS (§8.6, §8.7).** Power analysis for these values would be a novel contribution. Defensible as engineering choices with documented rationale.

**RESEARCH DELIVERABLES remaining**
- **SecureBERT 2.0 ablation note** → Spearman correlation + threshold calibration plot on 30–50 rule pairs. ~1 day.
- **LLMSecEval cross-check SLURM run** → After main experiments are complete. 1 submission, ~1–2h wall time.
- **(Optional) SecurityEval third cross-check** → If LLMSecEval cross-check raises questions about generalization.

---

## 12. What is safely out of scope

To keep the search focused, the following items are **deliberately** uncited and **should stay uncited**, because they are engineering details or thesis-specific conventions for which no literature is expected:

- Directory layout, file naming, SLURM scripting conventions.
- Conda environment, HF cache path, `activate_sbst.sh`.
- Logging format, `bd` (beads) tracker usage, experiment-results archiving.
- `mask_inline_code` placeholder tokens, restore-map implementation (§3.3).
- The decision to cache SBERT embeddings or lazy-load models.
- Any code-hygiene detail (type hints, dataclass vs class, etc.).

These are listed here only so a future search run doesn't waste effort trying to find literature for them.

---

*End of mapping.*
