# Threats to Validity

Written for a reader deciding how much weight to put on anything in this repo.
Ordered by how much damage each does to the conclusions, not by how comfortable
they are to state. Every number here is measured and traceable to an artifact in
`docs/validation/`.

---

## 1. The original headline was wrong, and the way it was wrong is the point

The published claim — a 1.7B fine-tune beating a frontier model on
severity-weighted recall — failed two independent pre-registered tests.

**Training-seed variance.** Four runs of one recipe, identical except the seed,
score R_w 0.7457 / 0.8198 / 0.8353 / 0.9451. SD **0.0823**, which is **2.86×**
the 0.0288 margin the claim rested on. The shipped model is the top of that
range. Its defining property — catching every HIGH-severity exception at zero
operational cost — is not a property of the recipe; the other three runs all miss
HIGH exceptions. `training-seed-variance.json`

**Matched conditions.** The published comparison gave the champion 5 votes at
temperature 0.6 and gave DeepSeek 1 greedy sample, on a prompt that *names*
PARTIAL_MATCH, FIELD_CORRUPTION, VALUE_DATE_MISMATCH and DUPLICATE without
defining any of them. Matching both axes flips the margin from **+0.0269**
[+0.0064, +0.0493] to **−0.0288** [−0.0432, −0.0160]. `matched-comparison.json`

Three caveats on that result, none of which change its direction:
- It is **exploratory, not confirmatory**. It runs on seed-777 (v1), violating
  §4.5's held-out-surface-forms requirement. The violation is conservative — the
  overlap favours the champion — so a compliant pool would push it further
  negative.
- The published figure is quoted as **+0.0269**, not the +0.0288 in the original
  paper. The original was aggregated with whole-dict voting, which §4.4 forbids;
  under a consistent rule the two numbers are not mirror images.
- The condition isolating the **decode-budget** effect was never collected. The
  evidence supports "does not survive a matched prompt" strongly; the budget's
  separate contribution is unmeasured.

Neither result required new insight. Both required running an experiment that had
never been run.

## 2. R_w is gameable, and our own model games it

Severity-weighted recall is scored over the exception subset only, so a model
that flags every clean pair pays nothing. Demonstrated three ways in this repo:

- an always-ESCALATE policy scores R_w 0.6673 at accuracy 0.000;
- the zero-shot base model scores R_w 0.6002 — **below** the 0.6673 available
  from flagging everything `AMOUNT_MISMATCH` without reading it, i.e. negative
  skill (`baselines.json`);
- the champion under the rubric prompt raises R_w to 0.9401 while its accuracy
  **halves** to 0.4338 and flag precision falls to 0.5083.

Any R_w figure in this repo, including ones favourable to us, must be read beside
flag precision/F1 and normalized cost.

## 3. Synthetic data, and an eval pool that is close to training

All data is generated. No live financial records, no real counterparties, no
production loss history.

Contamination is stated precisely: **exact-signature overlap is 0**. That is not
the same as the eval being unlike training. The nearest-neighbour Jaccard
histogram has **no mass below 0.6**, and **771 of 800** eval tasks sit in
[0.6, 0.8) of a training example. Expected from one generator, and a hard bound
on how novel the benchmark is to the model. Removing the 29 near-duplicates
(J ≥ 0.8) moves the champion-vs-DeepSeek margin by +0.0006, so the margin is not
an artefact of that slice. `contamination.json`, `dedup-sensitivity.json`

## 4. Construct validity of the class that decided the result

PARTIAL_MATCH contributed ~97% of the three-sample margin and 112% of the ×5 headline margin (the other eight classes net slightly negative). Its 32 benchmark items are
generated from **9 distinct surface pairs, all 9 of which appear in training** —
overlap fraction 1.0. "Learned to recognise abbreviated names" and "memorised ten
strings" predict the same score. The benchmark cannot separate them.
`partial-match-overlap.json`

Separately, 12 of 37 FIELD_CORRUPTION items are `malformed_date`, which is
indistinguishable from VALUE_DATE_MISMATCH unless the model has internalised the
verifier's priority order — an order the prompt never states.
`taxonomy-collision.json`

## 5. The benchmark's ceiling is 1.0 by construction

The rules-oracle "ceiling" is the verifier, and the generator enforces
verifier/expected agreement at construction time. It therefore scores 1.0 on any
pool by construction, not as a measured result. It is a sanity check on the
scoring path, not evidence the task is solvable by rules.

## 6. Selection pressure on the dev pool

Seed 777 has been used for selection (run-1 vs B2, ×3 vs ×5) and is permanently a
dev pool. Seed 999 is frozen with committed signatures and **has never been
scored**. There is no held-out-from-selection number in this repo. Any figure
quoted on seed 777 is a dev-set figure.

## 7. What the RL result does and does not show

GRPO did not train. It collapsed exploration after a single update — rollout
diversity went from 2 distinct outputs to 1 on the probed tasks — so 59 of 60
steps produced no gradient. This is a property of applying GRPO to a
near-deterministic SFT policy at these settings, **not** evidence that RL cannot
help this task. The standard mitigations were deliberately not applied, because
tuning them after observing the failure would be indistinguishable from fitting
hyperparameters to the outcome.

The reward also cannot see type errors on 8 of the 10 classes: naming the wrong
type on a MEDIUM/LOW exception is not an escalation, not a missed HIGH, and not a
false flag, so right and wrong score identically. `rl-taskset.json`

## 8. Single domain, single scale, single provider

One vertical (back-office reconciliation), one model scale (1.7B), one frontier
comparator (deepseek-v4-flash at an unpinned API snapshot). No evidence of
transfer to another domain, another scale, or another provider. The frontier
model's pretraining exposure to similar data is **unmeasured** and unmeasurable
from here.

## 9. Statistical limits

- Intervals on proportions use Wilson; composites use a percentile bootstrap over
  tasks. Which method applies is recorded per metric in `intervals.json`.
- Three variances are reported separately and must not be conflated: task
  resampling, sampling marginal (0.0121), and training seed (0.0823). The
  published CIs measure only the first.
- The training-seed SD is estimated from n=4. Its χ² interval is
  [0.0466, 0.3068] — wide. The conclusion "underpowered" is what that interval
  says directly; the threshold rule that fires on it is the weaker instrument.
- Judge kappa: the production judge's 0.9037 has CI [0.828, 0.968], whose lower
  bound is **below** the 0.85 bar it is said to clear. At n=100 the data cannot
  distinguish it from a judge sitting exactly at the threshold.

## 10. One condition is missing

Condition B (DeepSeek, rubric prompt, ×1 greedy) would have split the +0.0970
combined effect into a definition effect and a decode-budget effect. The provider
account was exhausted mid-experiment (HTTP 402), so only the combined figure is
measurable. It is reported as unmeasured rather than estimated.

## 11. Errors found in this work, by whom

Every wave of this project was reviewed by an independent adversarial pass, and
every one of them found something asserted too confidently:

- a regression introduced while fixing the scoring harness (null formatting crash);
- a Spearman correlation computed with a formula invalid under ties (−0.578,
  correctly −0.608 — and the error favoured the argument being made);
- a claim that MLX validation consumes the training RNG stream, asserted without
  checking and false, which had excluded a legitimate fourth sample;
- an RL task filter selecting on correctness variance rather than reward variance,
  wasting 83% of groups;
- a confident mechanistic explanation for an API failure (token-budget overrun)
  invented from partial evidence — and the replacement explanation was itself
  asserted rather than demonstrated, since the discriminating evidence had been
  deleted. The cause is recorded as unknown;
- quoting a published margin (+0.0288) computed under an aggregation rule the
  pre-registration forbids, against a matched margin computed under the correct
  one, producing an apparent symmetry that does not exist;
- miscounting the failed guards as 3 of 5 when the correct figure is 2 of 5, by
  splitting one guard across two table rows and omitting another.

This list is here because the corrections are the reason the retraction is
trustworthy, and because a reader should assume the same rate of error in
anything here that has *not* been independently checked.
