# ReconForge Benchmark — Head-to-Head

**Benchmark**: 800 held-out tasks, seed 777 (never used for training, seed 101
was; cross-set signature overlap verified = 0). Task distribution: ~45%
exceptions across 9 classes with severity weights (A3), adversarial
near-misses included. Scored with forge's `score_verdicts` — severity-weighted
recall, per-class recall, escalation precision (precision of predictions
labeled `ESCALATE` specifically) — plus flag-level precision/recall/F1
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

## Results

| Model | Accuracy | Severity-w. recall | Flag precision [95% CI] | Flag F1 [95% CI] | Norm. cost [95% CI] | HIGH recall | Parse rate | Notes |
|---|---|---|---|---|---|---|---|---|
| Base Qwen3-1.7B-4bit (zero-shot) | — | 0.6002 | 0.852 [0.809, 0.894] | 0.717 [0.677, 0.755] | 0.145 [0.089, 0.206] | — | 0.9988 | ablation: what the fine-tune bought |
| Fine-tuned Qwen3-1.7B (iter 700, abort) | 0.7812 | 0.7291 | — | — | — | — | 1.0000 | self-consistency ×3 |
| DeepSeek `deepseek-v4-flash` | **0.8762** | 0.8719 | **1.000** [1.000, 1.000] | **0.904** [0.880, 0.926] | **0.013** [0.001, 0.031] | — | 0.9962 | frontier baseline, zero-shot; 0 false positives |
| **Fine-tuned Qwen3-1.7B (iter 740)** | 0.8050 | **0.9128** | 0.813 [0.773, 0.850] | 0.827 [0.797, 0.856] | **0.000** [0.000, 0.000] | **1.0000** | **1.0000** | self-consistency ×3, loss plateau 0.088; 74 false positives |
| Fine-tuned Qwen3-1.7B (champion ×5) | 0.8050 | 0.9007 | 0.824 [0.784, 0.862] | 0.824 [0.793, 0.853] | 0.000 [0.000, 0.000] | 1.0000 | 1.0000 | self-consistency ×5; 67 false positives |

**Headline: the local fine-tuned 1.7B beats the frontier model on the metric
that matters.** Severity-weighted recall 0.913 vs 0.872 for DeepSeek, with
perfect HIGH-severity recall (all 4 HIGH classes: AMOUNT_MISMATCH 73/73,
FX_CONVERSION_ERROR 32/32, BENEFICIARY_MISMATCH 42/42, COUNTERPARTY_MISMATCH
31/37), 100% parse discipline, zero API cost, zero reasoning tokens.

**Counter-headline: DeepSeek wins on flag F1.** It makes **zero false positives**
on the 419 clean pairs (precision 1.000) and wins F1 0.904 vs the fine-tuned
model's 0.827 — the champion ×5 model does **not** win on F1 (0.824). The
fine-tuned model buys its HIGH-severity recall partly by over-flagging clean
pairs (74 FP at iter 740, 67 at ×5). Both numbers are real; which one you
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
- The fine-tune bought +31 points of R_w over the base model (+13 already at
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

| Class | run1 (default mix) | B2 (rebalanced) |
|---|---|---|
| HIGH recall | **1.0** | 0.89 |
| MEDIUM recall | **0.84** | 0.40 |
| AMOUNT_MISMATCH correct | **73** | 56 |
| PARTIAL_MATCH correct | **26** | 1 |
| VALUE_DATE_MISMATCH correct | **37** | 8 |
| DUPLICATE correct | 0 | 1 |
| FIELD_CORRUPTION correct | 13 | **16** |
| **R_w** | **0.9128** | 0.7230 |

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
