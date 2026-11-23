# ReconForge Benchmark — Head-to-Head

**Benchmark**: 800 held-out tasks, generation seed 777 (never used for
training; the training pool is generation seed 101 — verified empirically,
see `docs/TRAINING.md`; cross-set **exact-signature** overlap verified = 0,
re-confirmed under seed 101). Exact-overlap 0 is the precise claim. A MinHash
audit puts 29/800 (3.62%) at Jaccard ≥ 0.8 to the nearest training neighbour,
with **no** task below 0.6 and 771/800 in [0.6, 0.8) — expected from a shared
generator, and a bound on how novel the benchmark is to the model. Dropping the
near-duplicates raises every model slightly and moves the champion-vs-DeepSeek
R_w margin by +0.0006, so the margin does not come from that slice
(`docs/validation/dedup-sensitivity.json`). Task distribution: 48%
(381 of 800) exceptions across 9 classes with severity weights (A3), adversarial
near-misses included. Scored with forge's `score_verdicts` — severity-weighted
recall, per-class recall, escalation precision (precision of predictions
labeled `ESCALATE` specifically, scored over **all** tasks so that escalating a
clean pair costs precision — see the correction note below) — plus flag-level precision/recall/F1
(precision/recall of *any* non-MATCH prediction, `EXCEPTION` or `ESCALATE`;
see issue #8) shown in the Results table below as **Flag precision/F1**. The
two are different metrics that can diverge; don't read one off the other.
Same system prompt, same yardstick for every model.

**Scoring rules (CONTRACTS.md)**: HIGH severity = caught if flagged as
anything other than MATCH; MEDIUM/LOW = caught only with the exact
exception_type. Severity-weighted recall = Σw·caught / Σw.

**R_w needs a partner metric.** R_w is computed over the exception subset only —
the 419 clean (MATCH) tasks are not in the denominator, so a model that flags
every clean pair pays zero R_w cost. See "Why R_w needs a partner" below for the
degenerate escalate-everything demonstration. The partner metrics reported here:

- **Flag precision / recall / F1** (`metrics.precision_recall_f1`): a "flag" is
  any predicted verdict ≠ MATCH. TP = expected exception, flagged; FP = expected
  clean MATCH, flagged; FN = expected exception, returned MATCH. This puts the
  clean tasks back on the scoreboard.
- **Severity-weighted cost** (`metrics.severity_weighted_cost`): operational
  loss at `cost_esc = 1.0` per pair routed to human review and
  `cost_missed_high = 5.0` per missed HIGH exception (the function's existing
  defaults; stated here rather than left implicit). Normalized = cost / n.

95% bootstrap CIs: 10,000 task resamples, seed 11. Regenerate everything below
with `uv run python model/scripts/rescore_flag_metrics.py` →
`docs/validation/flag-metrics.json`.

> **Selection caveat.** The seed-777 benchmark is held out from *training* (the
> training pool is generation seed 101, verified), but **not from selection**.
> Every checkpoint / mix / sampling decision — run-1 vs the B2 rebalanced mix,
> ×3 vs ×5 self-consistency — was made by comparing on this same 800-task set
> that the headline metrics are reported on. The headline is therefore a
> dev-set number, not a held-out-from-selection one. A newly designated seed
> (999) is frozen as the test set: its task signatures are committed in
> `docs/validation/frozen-test-seed-999-signatures.json` and nothing has been
> scored against it. Discipline going forward: `docs/TRAINING.md` → Selection
> policy.

## Results

| Model | Accuracy | Severity-w. recall | Flag precision [95% CI] | Flag F1 [95% CI] | Norm. cost [95% CI] | HIGH recall | Parse rate | Notes |
|---|---|---|---|---|---|---|---|---|
| Base Qwen3-1.7B-4bit (zero-shot) | — | 0.6002 | 0.852 [0.809, 0.894] | 0.717 [0.677, 0.755] | 0.145 [0.089, 0.206] | — | 0.9988 | ablation: what the fine-tune bought |
| Fine-tuned Qwen3-1.7B (iter 700, separate aborted run) | 0.7812 | 0.7291 | — | — | — | — | 1.0000 | self-consistency ×3; unreproducible — weights overwritten by the champion run, retained for narrative only |
| DeepSeek `deepseek-v4-flash` | **0.8762** | 0.8719 | **1.000** [1.000, 1.000] | **0.904** [0.880, 0.926] | **0.013** [0.001, 0.031] | — | 0.9962 | frontier baseline, zero-shot; 0 false positives |
| **Fine-tuned Qwen3-1.7B (champion / iter 700, ×5) — headline** | 0.8050 | **0.9007** [0.876, 0.924] | **0.824** [0.784, 0.862] | **0.824** [0.793, 0.853] | **0.000** [0.000, 0.000] | **1.0000** | **1.0000** | self-consistency ×5, loss plateau 0.088; 67 false positives |
| Fine-tuned Qwen3-1.7B (champion / iter 700, ×3) | 0.8050 | 0.9128 | 0.813 [0.773, 0.850] | 0.827 [0.797, 0.856] | 0.000 [0.000, 0.000] | 1.0000 | 1.0000 | secondary / sampling-sensitivity row (no CI computed for R_w); self-consistency ×3; 74 false positives |

> The champion adapter is the **iter-700** checkpoint (last persisted save;
> the final run's loop ran to step 740 but the MLX-LoRA saver writes every 50
> steps). SHA-256
> `4754fe569b703f075725f0415a9ae70664fda6d7d66a865e956be2ff69bacdfa`. The eval
> run and its artifacts are still named `full-740` after the run's step count.
> The `iter 700, separate aborted run` row is a different, earlier run.

**Headline: the local fine-tuned 1.7B beats the frontier model on the metric
that matters.** Severity-weighted recall 0.9007 [0.876, 0.924] (×5
self-consistency, the headline run) vs 0.872 for DeepSeek, with
perfect HIGH-severity recall (all 4 HIGH classes: AMOUNT_MISMATCH 73/73,
FX_CONVERSION_ERROR 32/32, BENEFICIARY_MISMATCH 42/42, COUNTERPARTY_MISMATCH
37/37), 100% parse discipline, zero API cost, zero reasoning tokens.

**Counter-headline: DeepSeek wins on flag F1.** It makes **zero false positives**
on the 419 clean pairs (precision 1.000) and wins F1 0.904 vs the champion's
0.824 (×5 headline; the ×3 row is 0.827) — the fine-tuned model does **not**
win on F1. It buys its HIGH-severity recall partly by over-flagging clean
pairs (67 FP for the champion at ×5, 74 at ×3). Both numbers are real; which one you
optimize is a policy choice, and the point of issue #8 is that the leaderboard
must show both. The severity-weighted cost column tells the operational story:
the fine-tuned model's cost is 0.000 (it never escalates, never misses a HIGH),
DeepSeek's is 0.013 (5 escalations, 1 parse failure on a HIGH-severity task
also counts as a missed HIGH), and the degenerate escalate-everything
model below is 1.000.

## Why R_w needs a partner — the escalate-everything demonstration

`docs/validation/model-eval-smoke-20260807.json` is a real export from a
degenerate model that returns ESCALATE on every task (88-task smoke fixture,
64 exceptions / 24 clean). It gets **every verdict wrong** — accuracy 0.0,
zero exact matches — yet:

| Metric | escalate-everything | Base Qwen3-1.7B (real baseline) |
|---|---|---|
| Accuracy | 0.000 | 0.678 |
| **Severity-weighted recall (R_w)** | **0.696** | **0.600** |
| Flag precision [95% CI] | 0.727 [0.636, 0.818] | 0.852 [0.809, 0.894] |
| Flag recall | 1.000 | 0.619 |
| Flag F1 [95% CI] | 0.842 [0.778, 0.900] | 0.717 [0.677, 0.755] |
| **Normalized cost [95% CI]** | **1.000 [1.000, 1.000]** | 0.145 [0.089, 0.206] |

On R_w alone the always-ESCALATE model **beats the real base-model baseline**
(0.696 > 0.600) at accuracy 0.0, because R_w never scores the clean tasks it
flags. Its flag F1 also looks deceptively fine (0.842) — but only because this
fixture is 73% exceptions; on the 800-task benchmark's ~48% exception rate the
same model would score precision ≈ 0.48, F1 ≈ 0.65. The metric that catches it
unconditionally is severity-weighted cost: 1.000 (it escalates all 88 pairs),
~7× the real base model's 0.145. **Report R_w with flag F1 and cost, never
alone.**

> **Cost catches escalate-everything, not flag-everything.** The sentence above
> is about `always-ESCALATE`, and for that policy cost is decisive (1.000). But
> `severity_weighted_cost` prices escalations and missed HIGH exceptions only —
> it does **not** price raising an `EXCEPTION` on a clean pair. So
> `always-EXCEPTION` scores cost **0.0000**, tying the rules-oracle for the best
> possible score, at flag precision 0.465
> (`docs/validation/rl-env-health.json`). That is acceptable in a published
> operational summary, where a spurious exception really is cheaper than a missed
> mismatch, and unacceptable as an optimisation target. The RL round therefore
> uses a separate `rl_cost` that prices all three error modes; the published
> metric is left unchanged so committed numbers do not move.

## Reading

- **Why the fine-tuned model wins on R_w**: it never misses a HIGH-severity
  exception (the metric's heavy classes); it trades accuracy on low-weight
  classes to get there. DeepSeek spreads its errors more evenly — better raw
  accuracy, worse on the money axis.
- **The remaining hole is LOW severity**: DUPLICATE 0/31, FIELD_CORRUPTION
  13/37. Both weight 0.2 — cheap to fix with data-composition (B2), and
  cheap to tolerate: missing a duplicate is worth 5x less than missing a
  principal mismatch.
- **Zero escalations** is a known cost: the model never says "unsure". The
  E1/E3 threshold work (severity-gated escalation policy) is the fix, and
  would buy both recall robustness and HITL efficiency.
- The fine-tune bought +30 points of R_w over the base model (+13 already at
  iter 700) — the LoRA is doing real work, not the prompt.

## Reproduction

```sh
# benchmark set + datasets (contamination-guarded, deterministic)
cd model
PYTHONPATH=../forge/src:src uv run python -c "..."   # see scripts/README

# deepseek comparison (16 workers, resumable)
uv run python -m reconforge_model.compare_deepseek --tasks-file data/benchmark.jsonl --run full

# local eval (self-consistency x3)
uv run python -m reconforge_model.benchmark_eval --adapter-path adapters/lora-full --tasks-file data/benchmark.jsonl --run full-740 --samples 3
```

Artifacts: `docs/validation/bench-deepseek-full.json`,
`docs/validation/bench-eval-full-700.json`, `bench-eval-full-740.json`.

## B2 study — training-mix rebalancing (negative result)

Attempted fix for the LOW-severity hole: rebalanced the training exception mix
(DUPLICATE 8→22%, FIELD_CORRUPTION 8→15%, cutting AMOUNT/PARTIAL/VALUE_DATE)
and retrained (590 steps). **It made things worse**:

| Class | run1 (default mix, ×3) | B2 (rebalanced, ×3) |
|---|---|---|
| HIGH recall | **1.0** | 0.89 |
| MEDIUM recall | **0.84** | 0.40 |
| AMOUNT_MISMATCH correct | **73** | 56 |
| PARTIAL_MATCH correct | **26** | 1 |
| VALUE_DATE_MISMATCH correct | **37** | 8 |
| DUPLICATE correct | 0 | 1 |
| FIELD_CORRUPTION correct | 13 | **16** |
| **R_w** | **0.9128** | 0.7230 |

Both columns are ×3 self-consistency (the B2 study predates the ×5 headline
run); run1's ×5 R_w is 0.9007 [0.876, 0.924]. The run1-vs-B2 comparison holds
at either sampling count — B2 is worse on every class the benchmark weights
heavily.

Flag precision/F1 for the B2 rebalanced run was not re-scored (outside issue
#8's scope, which covered the 4 headline exports + the smoke fixture); add
`bench-eval-b2-590.json` to `model/scripts/rescore_flag_metrics.py`'s `RUNS`
to compute it.

Reading: distribution matching beats rebalancing. Cutting a class's training
weight destroys its recall on the benchmark; upsampling a subtle-signal class
(DUPLICATE) buys ~nothing — the miss is representational (the model learned
"all fields agree → MATCH"), not a data-count problem. Champion remains the
default-mix run1 adapter. DUPLICATE is caught in production by the verifier
pre-check, not the model.

## Under matched conditions the margin inverts (issue #18) — EXPLORATORY

> **Scope, stated before the numbers.** This is **not** the confirmatory test.
> `PRE-REGISTRATION.md` §4.5 requires PARTIAL_MATCH built from abbreviation pairs
> disjoint from training, and §3 names the frozen seed-999 pool as the endpoint.
> This runs on seed-777 (generator v1), whose PARTIAL_MATCH overlap fraction is
> **1.0** — every surface pair appears in training. §4 says all matched conditions
> must hold or the comparison is not run, so this is exploratory evidence.
> The violation is **conservative**: the overlap favours the champion, so a
> compliant pool would push the matched margin further negative, not back toward
> positive.

The published head-to-head varied two things at once: a 5-vote fine-tune against a
1-shot frontier model, on a prompt that *names* PARTIAL_MATCH, FIELD_CORRUPTION,
VALUE_DATE_MISMATCH and DUPLICATE without defining any of them — on the class
carrying most of the margin (~97% of the three-sample margin; 112% of the five-sample one, see the note under "Construct validity" below). `docs/validation/matched-comparison.json`.

| condition | accuracy | R_w | flag P | flag F1 | cost | HIGH rec |
|---|---|---|---|---|---|---|
| A DeepSeek, base, ×1 *(as published)* | 0.8762 | 0.8719 | 1.0000 | 0.9036 | 0.0125 | 0.9946 |
| C DeepSeek, rubric, ×5 *(matched)* | **0.9487** | **0.9689** | **1.0000** | **0.9604** | 0.0000 | 1.0000 |
| D champion, rubric, ×5 *(matched)* | 0.4338 | 0.9401 | 0.5083 | 0.6649 | 0.0000 | 1.0000 |
| E champion, base, ×5 *(as published)* | 0.8050 | 0.9007 | 0.8241 | 0.8241 | 0.0000 | 1.0000 |

Paired bootstrap on ΔR_w, 10,000 resamples, same task indices for both sides:

| effect | ΔR_w | 95% CI | excludes 0 |
|---|---|---|---|
| published margin, as reported (E−A) | +0.0288 | [+0.0074, +0.0513] | yes |
| published margin, corrected vote (E′−A) | **+0.0269** | [+0.0064, +0.0493] | yes |
| **matched margin (D−C)** | **−0.0288** | [−0.0432, −0.0160] | **yes** |
| giving DeepSeek the same prompt and budget (C−A) | +0.0970 | [+0.0724, +0.1250] | yes |
| what the rubric does to the champion (D−E′) | +0.0413 | [+0.0228, +0.0624] | yes |

**The margin inverts:** +0.0269 for the fine-tune becomes −0.0288 against it,
both intervals excluding zero.

> **Why E′ and not E.** The published champion run was aggregated in 2026-08 with
> whole-dict voting, which `PRE-REGISTRATION.md` §4.4 forbids ("whole-dict voting
> is not used for any model"). Quoting +0.0288 against −0.0288 would compare two
> *different estimators* and manufacture a symmetry. Re-aggregated under the rule
> every other condition uses, the published margin is **+0.0269** — the vote rule
> changes 8 of 800 decisions — and the mirror-image framing disappears. E is kept
> in the table as the historical number.

**A limit on the causal claim.** The published comparison used the same prompt for
both models, so its only unmatched axis was the sample count. The condition that
would isolate the budget effect — DeepSeek, *base* prompt, ×5 — was never run, and
condition B (which would have split the +0.0970) is unmeasured. So the evidence
supports "the margin does not survive a matched **prompt**" strongly, and does not
by itself establish how much the decode budget contributed.

**And the R_w figure understates it, because R_w is being gamed — by our own
model.** Under the rubric prompt the champion's R_w *rises* to 0.9401 while its
accuracy falls to 0.4338 and flag precision to 0.5083. The rubric is
off-distribution for a model trained on one fixed prompt, so it degenerates toward
flagging everything, and R_w rewards that because it never scores the 419 clean
pairs. This is the exact failure mode this document demonstrates with the
always-ESCALATE policy — appearing here in the champion.

**Under matched conditions the champion fails its own pre-registered guards**
(`PRE-REGISTRATION.md` §5, written before any of this ran):

| guard | required | champion (D) | |
|---|---|---|---|
| G-a flag precision | ≥ 0.75 | 0.5083 | **FAIL** |
| G-b flag F1 | ≥ 0.80, and within 0.10 of best | 0.6649, 0.296 behind | **FAIL** (both clauses) |
| G-c cost ≤ comparator | — | 0.0000 vs 0.0000 | pass |
| G-d parse rate | ≥ 0.99 | 1.0000 | pass |
| G-e HIGH recall | ≥ 0.95 | 1.0000 | pass |

**Two of the five guards fail** (G-a, and G-b on both of its clauses). So H1 fails
twice over: the margin reverses, *and* the champion does not clear conditions set
in advance to stop a reversed margin being read as a win. DeepSeek
under matched conditions leads on every metric — accuracy by 0.51, flag F1 by
0.30, R_w by 0.029, level on cost and HIGH recall.

**One condition is missing and is reported as unmeasured, not estimated.**
Condition B (DeepSeek, rubric, ×1 greedy) would have split the +0.0970 into a
definition effect and a budget effect. The provider account was exhausted
mid-experiment (HTTP 402), so only the combined effect is measurable. An earlier
draft of this section attributed B's failure to a token-budget interaction with
greedy decoding; that explanation was invented from partial evidence and is
withdrawn — the cause was simply an empty account.

## The headline does not survive training-seed variance (pre-registered H2)

`PRE-REGISTRATION.md` §11 named this as falsifying, before the experiment ran:

> If across-training-seed SD exceeds the observed ΔR_w, no single-run claim in
> either direction is supportable at this sample size, and the honest report is
> that the comparison is underpowered.

Four runs of one recipe — identical data, hyperparameters and step count,
differing only in the training seed — scored on one pool with one decode seed
(`docs/validation/training-seed-variance.json`):

| training seed | R_w | normalized cost |
|---|---|---|
| 202 | 0.7457 | 0.267 |
| 303 | 0.8198 | 0.167 |
| 101 | 0.8353 | 0.150 |
| **7 (the shipped champion)** | **0.9451** | **0.000** |
| **mean** | **0.8365** (SD 0.0823) | |

**Both conditions resolve against the claim.** §11: SD 0.0823 is **2.86×** the
0.0288 margin — the comparison is underpowered. §6: mean − 1 SD = 0.7542, below
DeepSeek's 0.8719 — H1 is not supported. The χ² interval on σ is
[0.0466, 0.3068], and its one-sided 95% lower bound (0.051) sits **above** the
margin, so σ ≤ margin is rejectable rather than merely unproven.

**The champion's defining property is not a property of the recipe.** It catches
every HIGH-severity exception at cost 0.000. The other three runs miss HIGH
exceptions — costs 0.150, 0.267, 0.167. The mechanism is visible in the
confusion counts: the champion simply flags more aggressively (26 false positives
on 157 clean tasks against the others' 10–14), which is what buys the perfect
HIGH recall. The training seed moves the model along that precision/recall axis,
and the shipped run landed at the favourable end.

This retroactively explains the 0.913-vs-0.729 pair the repo had already flagged
as unexplained run-to-run variance. It was the recipe's spread. Note the range
across all four runs is 0.1994, which is comparable to that pair's 0.1837 gap —
the earlier observation was a two-sample glimpse of this distribution.

**Three limits, stated rather than buried.**

1. *§11 is not fully pool-internal.* The SD is measured on seed-13/300 tasks; the
   0.0288 margin comes from seed-777/800. Pool sensitivity is itself large — the
   same champion weights score 0.9007 on seed-777 and 0.9451 on seed-13, a 0.0444
   shift, 1.5× the margin. A scale correction still leaves the SD above the
   margin, but a like-for-like test needs DeepSeek scored on this pool (Round 5).
2. *The SD is an upper bound on training-seed variance*, because decode-sampling
   noise sits inside it. Deflating by the repo's own sampling marginal (0.0121)
   gives 0.0814 — essentially unchanged.
3. *§6's comparison is cross-pool by construction* and is labelled indicative in
   the artifact. It does not show DeepSeek is better; it shows this recipe's
   typical run does not clear DeepSeek's number.

**Correction.** An earlier version of this analysis excluded the champion,
claiming its validation cadence made the weights incomparable because
"validation consumes RNG". That was asserted, not checked, and it is false here:
`mlx.nn.Dropout.__call__` returns its input unchanged when not training, and at
700 iters over 1599 batches/epoch the training permutation is drawn before the
first eval. Admitting the champion raises the SD from 0.0479 to 0.0823 — the
error was working *in favour of* the claim being retracted, and fixing it also
moved the one-sided σ bound above the margin.

## Checkpoint selection: the loss curve got the right answer, and could not have known

All fourteen 50-step checkpoints from the champion run had been sitting on disk
unscored since training. They are now scored on an independent dev pool (seed 13,
200 tasks, greedy — seed 777 is deliberately not used, it is already burned for
selection). `docs/validation/checkpoint-selection.json`.

**The shipped checkpoint is the best one.** Iter 700 wins on both severity-weighted
recall (0.9612) and flag F1 (0.8731). The loss-plateau stopping rule landed on the
right checkpoint.

That is a real result and it deserves to be stated before the caveat. The caveat
is that the rule could not have known:

| | Value |
|---|---|
| Spearman ρ between validation loss and R_w across the 14 checkpoints | **−0.608** (−1.0 would be a perfect ranker), tie-corrected |
| R_w spread across all 14 checkpoints of one run | **0.2590** (9.0× the 0.0288 headline margin) |
| R_w spread among the 4 checkpoints the loss rates **identically** at 0.091 | **0.0665** (2.3× the margin) |
| R_w spread among the 8 checkpoints at loss ≤ 0.093 | 0.1136 (3.9× the margin) |

> The ρ was first hand-computed as −0.578 using the naive `1 − 6Σd²/(n(n²−1))`
> formula. That formula is only valid without ties, and these losses are heavily
> tied (0.093 ×2, 0.092 ×2, 0.091 ×4), so it returned a tie-break-dependent
> answer. The tie-corrected value is **−0.608**, and it cuts slightly *against*
> the argument here — loss is a marginally better ranker than first reported.
> It is now derived by `model/scripts/checkpoint_loss_correlation.py` and
> re-checked in CI rather than being a hand-computed figure in prose.

Iters 550, 600, 650 and 700 all sit at validation loss 0.091 — indistinguishable to
three decimal places — while their R_w ranges from 0.8947 to 0.9612. Inside the
plateau, where the stopping decision actually gets made, the loss curve has no
discriminating power at all, and the choice among those checkpoints is worth more
than twice the effect the headline claims.

The sharpest single case is iter 150 → 200: validation loss **improved** (0.117 →
0.111) while R_w **collapsed** (0.8920 → 0.7022). Same run, same data, same recipe,
same seed; only the step count differs. That is a stronger demonstration than the
B2-vs-run-1 comparison in issue #12, which confounded the mix change with the run.

Reading: this run got a good checkpoint, not a checkpoint chosen on evidence.
Checkpoint selection belongs on the dev ladder, and the multi-seed and
multi-training-seed work is what determines whether iter 700's margin is stable or
a favourable draw.

## Which variance the intervals measure (issue #20)

Every published interval in this repo is a **task-resampling** bootstrap. It
answers "if I drew a different 800 tasks from this generator, how would the score
move?" It does not answer either question a reader actually has when comparing
two models. Three different quantities, only one of which is properly measured
(`docs/validation/variance-decomposition.json`):

| Variance source | What it measures | Magnitude on R_w | vs the 0.0288 margin | Measured? |
|---|---|---|---|---|
| Task resampling | redraw 800 tasks from the same generator | 0.0483 (CI width) | see note | yes |
| Sampling marginal | same weights, same pool, different decode budget | 0.0121 | 0.42× | partially (n=1 pair) |
| Eval-pool seed | same weights and budget, different draw of tasks | 0.0115 (SD, 3 seeds) | 0.40× | **yes** |
| **Training seed** | same recipe, different seed | **0.1837** | **6.4×** | **no** |

> **Note on the first row.** Comparing an *unpaired* CI width to a *point*
> margin is apples-to-oranges, and reading it as "task noise swamps the margin"
> would be wrong. The right object for the comparison is the **paired** ΔR_w
> interval, which resamples the same task indices for both models:
> **+0.029 [0.008, 0.052], p ≈ 0.009** — it excludes zero
> (`docs/validation/intervals.json`). Task-level noise does *not* dissolve the
> margin. The row is kept because it shows the published interval measures a
> different thing from run-to-run reproducibility, not because it undercuts the
> comparison.

The sampling marginal is the ×3 vs ×5 difference on identical weights and an
identical pool: changing only the decode budget moves R_w by 0.0121, which is 42%
of the margin that difference is being used to support.

The training-seed figure is the gap between the champion and the earlier run of
the identical recipe, both at ×3 (0.9128 − 0.7291 = 0.1837). Note the ratio mixes
decode budgets: the numerator is a ×3 pair while the 0.0288 margin is ×5. Held
consistently at ×5 the ratio is **6.0×** rather than 6.4×; the conclusion is
unchanged. It is **not** a controlled seed comparison —
that run's weights were overwritten and cannot be re-scored — so it is an
indication, not a standard deviation. But it is 6.4× the effect being claimed,
and `PRE-REGISTRATION.md` §11 names exactly this as a falsification condition:

> If across-training-seed SD exceeds the observed ΔR_w, no single-run claim in
> either direction is supportable at this sample size, and the honest report is
> that the comparison is underpowered.

**Eval-pool variance is now measured, and it is small.** Scoring the champion at
×5 across generation seeds 7, 13 and 42 (300 tasks each,
`docs/validation/multiseed-matrix.json`) gives R_w 0.9221 / 0.9451 / 0.9351 —
mean 0.9341, SD **0.0115**, range 0.0230. Redrawing the tasks moves the champion
by well under half the margin.

> **What that does not show.** DeepSeek was not run on seeds 7/13/42, and these
> are 300-task pools against the headline's 800. Reading the champion's 0.9341
> here against DeepSeek's seed-777 0.8719 would be precisely the unmatched
> comparison this work exists to eliminate. The multi-seed result establishes
> the *stability of one model across task draws*, nothing about the contest.

So of the four variances, three are now measured and none of them threatens the
margin: task resampling does not (the paired interval excludes zero), sampling
marginal is 0.42×, eval-pool seed is 0.40×. The one that could still overturn the
claim — training seed, indicated at 6.4× — is the one still uncontrolled. That
narrows the pre-registered underpowered-comparison question to a single
experiment: the ≥3 controlled training seeds §6 requires.

## Floors and ceiling (issue #19)

No model score in this document is interpretable without the band it sits in.
Scored through the same `score_verdicts` path as every model
(`docs/validation/baselines.json`, `forge/src/reconforge_forge/baselines.py`):

| Policy | Accuracy | R_w | Flag F1 | Norm. cost |
|---|---|---|---|---|
| always-MATCH | 0.5238 | 0.0000 | 0.0000 | 1.1500 |
| always-EXCEPTION (AMOUNT_MISMATCH) | 0.0912 | **0.6673** | 0.6452 | 0.0000 |
| always-ESCALATE | 0.0000 | **0.6673** | 0.6452 | 1.0000 |
| majority-class | 0.5238 | 0.0000 | 0.0000 | 1.1500 |
| stratified-random | 0.2913 | 0.3903 | 0.5181 | 0.5062 |
| **rules-oracle (ceiling)** | **1.0000** | **1.0000** | **1.0000** | **0.0000** |

Two things follow immediately.

**The base-model baseline has negative skill on R_w.** Base Qwen3-1.7B scores
R_w 0.6002, *below* the 0.6673 available from flagging every pair
`AMOUNT_MISMATCH` without reading it. Skill-normalized that is **−0.2017**. So
"the fine-tune bought +30 points of R_w over the base model" is measured from a
starting point worse than a one-line policy, and overstates what the fine-tune
demonstrably added. The honest floor for R_w is 0.6673, not 0.6002.

**Skill-normalized, the champion's lead is R_w-only and the gap narrows.**
With floor = best trivial policy and ceiling = rules-oracle:

| Metric | Floor (policy) | Champion ×5 | DeepSeek | Leader |
|---|---|---|---|---|
| Accuracy | 0.5238 (always-MATCH) | 0.5905 | **0.7400** | DeepSeek |
| Severity-weighted recall | 0.6673 (always-EXCEPTION) | **0.7015** | 0.6150 | champion |
| Flag F1 | 0.6452 (always-EXCEPTION) | 0.5042 | **0.7283** | DeepSeek |

The champion leads on exactly one of the three, which is the one the headline
selects. That is not itself illegitimate — R_w is the pre-registered primary
endpoint and the argument for it is stated up front — but the table belongs
beside the headline rather than behind it.

> Note: `always-ESCALATE` scores R_w 0.6673 here, against the 0.696 quoted
> elsewhere in this document. Both are correct; the 0.696 figure is from the
> 88-task smoke fixture (73% exceptions) and this one is from the 800-task
> benchmark (48%). The floor is a property of the pool, not a constant.

## Construct validity: two open confounds on the class that decides the result

Per-class decomposition (issue #18) attributes ~97% of the champion's three-sample R_w margin (0.9128 vs 0.8719; the ×5 headline margin is 0.0288, of which PARTIAL_MATCH contributes 0.0322, i.e. 112%, the other eight classes netting slightly negative; recomputed from the per-task exports in `paper/build_assets.py`)
over DeepSeek to a single class, PARTIAL_MATCH (champion 26/32, DeepSeek 5/32).
Two independent confounds sit on that class, and until both are closed the margin
does not support a capability claim:

1. **Definition.** The shared `SYSTEM_PROMPT` names PARTIAL_MATCH but never
   defines it. DeepSeek's "errors" land on defensible readings of an undefined
   label (BENEFICIARY_MISMATCH 8, COUNTERPARTY_MISMATCH 9, MATCH 10). Study C2
   already showed that giving DeepSeek the rubric definition lifts its oracle
   agreement 0.82 → 0.93; the head-to-head was never rerun with it.
2. **Memorization.** Every PARTIAL_MATCH item comes from a fixed 10-pair
   abbreviation table. The benchmark's 32 items use 9 distinct surface pairs and
   **all 9 appear in the training pool** — overlap fraction 1.0, zero unseen
   pairs (`docs/validation/partial-match-overlap.json`). "Learned the concept"
   and "memorised ten strings" predict the same score here.

On top of both, the decode budgets are unmatched: the champion votes over 5
samples at temperature 0.6 while DeepSeek gets one greedy sample
(`docs/validation/runconfig.json`).

The headline is therefore reported as provisional pending the matched-budget,
rubric-matched, held-out-variant rerun.

## Scoring corrections (issue #11)

Three defects in `score_verdicts` / the self-consistency vote were fixed after
these tables were produced. Corrected values for every committed export are in
`docs/validation/harness-fix-deltas.json` and
`docs/validation/majority-vote-audit.json`.

| Defect | Effect on the tables above |
|---|---|
| `exception_type_accuracy` counted only MEDIUM/LOW type hits in the numerator while the denominator counted all exception tasks | Understated by ~0.45 for every model. Champion ×3 0.3176 → **0.7848**, champion ×5 0.2966 → **0.7664**, DeepSeek 0.2598 → **0.7402**, B2 0.1811 → **0.6089**, base → **0.4304**. Ordering unchanged. The committed pilot reports 0.5 for the *verifier scored against itself*, which is impossible — the oracle defines the types. It now reports 1.0. |
| Escalations were counted only inside the exception-task branch, so false escalations on clean pairs were invisible and the "correct" test was always true | `escalation_precision` was a tautology: 1.0 whenever a model escalated at all, 0.0 (floored denominator) when it never did. DeepSeek's 1.0000 over n=2 was structurally guaranteed, not measured. Now scored over all tasks; models that never escalate report `null`. |
| The self-consistency majority vote compared whole JSON objects, including free-text `reason` and the emitted `confidence` | **No material effect on the published champion numbers.** The fine-tuned model emits 9 distinct reason strings across 800 predictions with confidence always 1.0, so agreeing samples were byte-identical: measured fallback-to-first-sample rate **0.000**, decision differs on 1.0% of tasks, R_w 0.9007 → 0.8988, ECE 0.0875 → 0.0925. It would have been severe for the baselines (DeepSeek emits 282 distinct reasons, base 148), which is why it is fixed before the matched-budget grid. |

**Parse-failure semantics.** An unparseable output is scored as if the model said
`MATCH`, so it counts as a missed exception rather than as an abstention. This
affects DeepSeek's 3 parse failures. The rule is now covered by a test.

**Interval methods (issue #9).** Per-type and per-band recall are simple k/n
proportions and use Wilson score intervals; a percentile bootstrap cannot escape
the boundary (every resample of 73/73 is still 73/73, printing [1.000, 1.000]).
Composite metrics — accuracy, R_w, and the paired champion-vs-DeepSeek diff —
keep the bootstrap. Every entry in `docs/validation/intervals.json` carries a
`method` field.

**Judge kappa now carries intervals, and it changes a conclusion.** The C2
DeepSeek judge is reported as clearing the 0.85 recalibration bar at kappa
0.9037. Its bootstrap CI over the same n=100 golden set is [0.828, 0.968] — the
lower bound is below the bar, so at this sample size the data cannot distinguish
the production judge from one sitting exactly at 0.85. Both readings are
published (`point_above_bar` true, `ci_lower_above_bar` false). Resolving it
needs a larger golden set, not a different judge.
