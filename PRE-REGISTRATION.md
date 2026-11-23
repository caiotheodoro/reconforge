# ReconForge — Pre-Registration

**Committed before any Round 2 experiment runs. Tagged `prereg-v1`.**

Date: 2026-08-29
Repo state at registration: see the git tag `prereg-v1`.

This document fixes the hypotheses, the primary endpoint, the decision rules and
both outcome branches **before** the experiments that decide them. Nothing below
may be revised after seeing a Round 2+ result. If something here turns out to be
badly specified, the revision is recorded as a dated amendment with its
rationale, and the affected analysis is reported as exploratory rather than
confirmatory.

---

## 1. Background and the claim under test

ReconForge publishes: *a Qwen3-1.7B LoRA fine-tuned on a laptop beats DeepSeek
v4-flash on severity-weighted recall (R_w), the metric that matters for
reconciliation.* Current dev-set values: champion ×5 R_w 0.9007 [0.876, 0.924]
vs DeepSeek 0.8719, paired ΔR_w +0.029 [0.008, 0.052], p ≈ 0.009.

Round 1 established that the comparison behind that claim is confounded on three
axes, each measured and committed:

| Confound | Evidence |
|---|---|
| Decode budget is unmatched | champion votes over 5 samples @ temp 0.6; DeepSeek and base get 1 greedy sample (`docs/validation/runconfig.json`) |
| The deciding class is undefined in the shared prompt | PARTIAL_MATCH contributes ~97% of ΔR_w; `SYSTEM_PROMPT` names it without defining it |
| The deciding class is memorizable | its 32 benchmark items use 9 surface pairs, **all 9 present in training**, overlap fraction 1.0 (`docs/validation/partial-match-overlap.json`) |

Plus: the champion is a single training run whose only sibling of the identical
recipe scored R_w 0.729 vs 0.913, and no held-out-from-selection number exists.

## 2. Hypotheses

- **H1 (capability).** Under matched decode budget, a matched rubric-defined
  prompt, and held-out abbreviation variants, the 1.7B fine-tune still achieves a
  higher R_w than DeepSeek v4-flash, with a 95% paired-bootstrap CI on ΔR_w
  excluding 0.
- **H2 (eval-construction artifact).** The published margin is produced by the
  measurement setup — decode-budget asymmetry, an undefined label, and
  memorizable surface forms — and does not survive matching. Under matched
  conditions the models are indistinguishable on R_w, or DeepSeek leads.

Both are publishable. H2 is not a failure; it is a result about how vertical
benchmark headlines are manufactured, and this repo has unusually direct evidence
for it.

## 3. Primary endpoint (single, confirmatory)

**ΔR_w = R_w(ours) − R_w(DeepSeek v4-flash)**, computed on the frozen test pool,
under Section 4's matched conditions, with a 95% paired bootstrap over tasks
(10,000 resamples, same resampled indices for both models, seed 11).

**Decision rule:** H1 is supported if and only if the ΔR_w point estimate is
positive **and** its 95% CI excludes 0 **and** every guard in Section 5 holds.
Otherwise H2 fires.

Exactly one primary endpoint is declared. Every other metric in this project —
accuracy, flag precision/recall/F1, normalized cost, per-class recall, ECE,
parse rate, per-seed variance — is **secondary**: reported in full, never used to
declare the claim supported. No multiplicity correction is applied to the primary
because there is exactly one confirmatory test.

## 4. Matched conditions (all must hold, or the comparison is not run)

1. **Same tasks.** Identical task pool, identical order, identical scoring code.
2. **Same prompt.** Every model receives the rubric-extended prompt that defines
   PARTIAL_MATCH, FIELD_CORRUPTION, VALUE_DATE_MISMATCH and DUPLICATE
   explicitly. Each model is additionally reported under its own best prompt as a
   labelled secondary row.
3. **Same decode budget.** Every model gets N = 5 samples at temperature 0.6 with
   a decision-level majority vote over `(verdict, exception_type)`. The full
   {×1, ×3, ×5} grid is reported for every model as secondary.
4. **Same aggregation.** The corrected `_majority`. Whole-dict voting is not used
   for any model — it is near-lossless for the canonical-output fine-tune and
   collapses to a single random sample for free-text baselines, which would
   silently favour the fine-tune.
5. **Held-out surface forms.** PARTIAL_MATCH items are generated from
   abbreviation pairs disjoint from the training table, with a test asserting
   disjointness.

## 5. Guard conditions (pre-declared, must all hold for H1)

R_w is scored over the exception subset only and is known-gameable: an
always-ESCALATE policy scores R_w **0.6673** on this 800-task benchmark at
accuracy 0.0 (`docs/validation/baselines.json`; the 0.696 quoted in earlier text
is the same policy on the 88-task smoke fixture, whose 73% exception rate is not
this pool's 48%). A higher R_w therefore
does not by itself mean a better model. H1 requires, on the same run:

| Guard | Threshold | Rationale |
|---|---|---|
| **G-a** Flag precision | ≥ 0.75 | Bounds how much R_w is bought by over-flagging clean pairs |
| **G-b** Flag F1 | ≥ 0.80, and within 0.10 absolute of the best model's | The model may trade some precision for HIGH recall, but not collapse |
| **G-c** Normalized severity-weighted cost | ≤ DeepSeek's on the same run | The operational metric; not gameable by escalate-everything |
| **G-d** Parse rate | ≥ 0.99 | A structured-output claim requires structured output |
| **G-e** HIGH-severity recall | ≥ 0.95 | The claim is specifically about the expensive classes |

**Disclosure.** These thresholds were chosen with the current dev-set values
visible (champion ×5: flag precision 0.8241, F1 0.8241, cost 0.000, parse 1.000,
HIGH recall 1.000; DeepSeek: precision 1.000, F1 0.9036, cost 0.0125). They are
set where the current champion passes. That is deliberate — the guards exist to
catch a *collapse* under matched conditions, not to re-litigate the known
precision gap — but a reader should know they were not set blind, and that
G-b's 0.10 margin is the one doing real work.

## 6. Variance protocol

Three different quantities, reported separately and never conflated:

- **Task-resampling** — 95% percentile bootstrap over tasks (composite metrics);
  Wilson score intervals for simple k/n proportions.
- **Sampling marginal** — spread across independent N-sample runs of the same
  checkpoint on the same pool. Already known to be material: ×3 vs ×5 moves R_w
  0.9128 → 0.9007, about 1.2 points against the **2.88-point** headline margin
  (champion ×5 0.9007 − DeepSeek 0.8719). An earlier draft said 4.1 points,
  which was the ×3 margin — inconsistent with §3's ×5 endpoint. See Amendment 1.
- **Training-seed variance** — ≥ 3 training seeds of the champion recipe.
  **H1 must hold at mean − 1 SD across training seeds, not at the best run.**
  The existing evidence for why: two runs of the identical recipe scored 0.913
  and 0.729.

## 7. Dataset versioning

The generator is versioned rather than mutated in place.

- **v1** stays frozen. Every currently published artifact remains reproducible
  from it, including the seed-999 signature file.
- **v2** carries the construct-validity fixes: PARTIAL_MATCH abbreviation pairs
  partitioned into disjoint train/eval sets, and the FIELD_CORRUPTION
  `malformed_date` variant no longer colliding with VALUE_DATE_MISMATCH.
- Round 2+ experiments run on **v2**. Because v2 changes what any seed produces,
  the v1 seed-999 signatures no longer describe a v2 pool; a **new test seed is
  designated and its v2 signatures committed before anything is scored on it**.

## 8. Data splits and the single-use rule

- **Dev.** Used for every choice — checkpoint, LoRA recipe, mix, sampling count,
  prompt. Reported freely. Under v2: the primary dev pool plus seeds 7/13/42.
- **Test.** One frozen pool, signatures committed before any scoring. Scored
  **at most once per published claim**, and **never** used to choose between
  candidates. If it is ever used for selection it is burned: a new seed is
  designated, its signatures committed, and the rotation recorded.
- The seed-777 pool is dev, permanently. It has already been used for selection
  (run-1 vs B2, ×3 vs ×5) and cannot be rehabilitated.

## 9. Stopping rules

- **Training.** Stop on the loss plateau. That rule chooses *when* to stop and
  explicitly **not** which checkpoint is better — B2 finished at lower validation
  loss (0.090 vs 0.091) and 19 R_w points worse. Checkpoint selection is by
  dev-ladder score across all persisted checkpoints.
- **RL.** Stop on the dev-ladder full profile, not on reward. A reward
  improvement accompanied by a regression-suite drop is a stop, not a success.
- **Analysis.** No metric is added to the primary after seeing results. New
  metrics are secondary and labelled exploratory.

## 10. Outcome branches, written before the result

**If H1 fires** (ΔR_w > 0, CI excludes 0, all guards hold, at mean − 1 SD across
training seeds, on the frozen test pool scored once):

> The claim is upgraded, not merely retained: it survives matched decode budget,
> a matched rubric prompt, held-out surface forms, multi-seed training variance,
> and a held-out test pool. README, BENCHMARK, HANDOFF, both cards and the blog
> are updated to the test-pool number with its interval, and the dev-set number
> is retired to a secondary row.

**If H2 fires** (any of: CI includes 0, ΔR_w ≤ 0, or any guard fails):

> The headline becomes: *a 1.7B fine-tune matches a frontier model on a narrow
> reconciliation task at a fraction of the latency and zero marginal cost; the
> previously published margin was an eval-construction artifact.* The write-up
> becomes finding C3 and states which of the three confounds carried the margin,
> with the per-condition decomposition. Every public artifact is corrected to the
> matched number. This is consistent with the repo's existing B2 and C2
> negative-result record, and is the stronger methodological contribution.

**Either way**, the following are published regardless of which branch fires:
floors and the rules-oracle ceiling with skill-normalized scores, the full
matched-budget grid, across-seed and sampling variance, dedup sensitivity, the
near-duplicate distribution, and the threats-to-validity document.

## 11. What would falsify the whole approach

Stated so it cannot be quietly avoided later:

- If the rules-oracle ceiling is reachable by a trivial policy, the benchmark
  does not measure a capability worth reporting.
- If across-training-seed SD exceeds the observed ΔR_w, no single-run claim in
  either direction is supportable at this sample size, and the honest report is
  that the comparison is underpowered.
- If the model's advantage disappears once every class is defined in the prompt,
  the contribution is a prompt-engineering result, not a fine-tuning one.

---

## Amendments

Revisions to this document after tagging. Section 0 requires each to be dated,
justified, and to state whether it touches anything the outcome depends on. No
amendment here changes a hypothesis, the primary endpoint, a guard threshold, or
an outcome branch.

### Amendment 1 — 2026-08-29 — two arithmetic corrections, no change to any decision rule

Both found by an independent adversarial verification of Round 2, not by me, and
both are corrections to numbers used as *motivation* rather than as decision rules.

1. **§5 cited the always-ESCALATE floor as R_w 0.696.** That figure is from the
   88-task smoke fixture, whose exception rate is 73%. On the 800-task benchmark
   this document actually governs, the exception rate is 48% and the same policy
   scores **0.6673** (`docs/validation/baselines.json`). The guard thresholds in
   §5 are unchanged — they were set against the champion's measured values, not
   against this floor — but the sentence justifying why R_w needs guards was
   quoting a number from the wrong pool.
2. **§6 described the headline margin as 4.1 points.** That is the ×3 margin
   (0.9128 − 0.8719), while §3 designates the ×5 comparison as the primary
   endpoint. The consistent figure is **2.88 points** (0.9007 − 0.8719). This
   makes the sampling marginal 0.42× of the margin rather than 0.29× — i.e. the
   correction works *against* the strength of the claim, not for it.

Neither correction was made after seeing a Round 2+ experimental result that
depends on it: the guards have not yet been evaluated against any matched-budget
run, and no test-pool number exists.
