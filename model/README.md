---
license: apache-2.0
base_model: mlx-community/Qwen3-1.7B-4bit
base_model_relation: adapter
library_name: mlx
tags:
  - fine-tune
  - finance
  - reconciliation
  - mlx
  - lora
  - structured-outputs
  - json-mode
  - agent-evaluation
  - severity-weighted
pipeline_tag: text-generation
metrics:
  - accuracy
  - recall
  - precision
  - f1
datasets:
  - caiotheodoro/recon-eval
model-index:
  - name: reconforge-recon-lora
    results:
      - task:
          type: text-generation
          name: Financial Reconciliation Verdict Classification
        dataset:
          name: ReconEval
          type: caiotheodoro/recon-eval
          revision: v0.1.0
        metrics:
          - name: Accuracy
            type: accuracy
            value: 0.805
          - name: Severity-Weighted Recall
            type: recall
            value: 0.9007
          - name: Flag Precision
            type: precision
            value: 0.8241
          - name: Flag F1
            type: f1
            value: 0.8241
          - name: HIGH-Severity Recall
            type: recall
            value: 1.000
          - name: Structured Output Parse Rate
            type: accuracy
            value: 1.000
          - name: Expected Calibration Error
            type: accuracy
            value: 0.0875
---

# ReconForge Recon — Financial Reconciliation Verdict Model

A LoRA fine-tune of Qwen3-1.7B for financial back-office reconciliation. It
trades raw accuracy (0.805 vs DeepSeek v4-flash's 0.876) for severity-weighted
recall (0.901 vs 0.872) and perfect recall on HIGH-severity exceptions — the
error class that actually costs money — at zero API cost, offline, on Apple
Silicon. Both the accuracy loss and the R_w gain are statistically significant
(95% bootstrap CI over 10,000 resamples, paired on the same 800-task set — see
Results). Trained in ~100 minutes on an M5.

**The trade-off has a second side.** R_w is scored over the exception subset
only, so it cannot see false positives on clean pairs. On the flag-level F1
(precision + recall over all 800 tasks), **DeepSeek wins**: it makes zero false
positives on the 419 clean pairs (precision 1.000, F1 0.904 [0.880, 0.926]),
while this model over-flags 67 clean pairs (precision 0.824, F1 0.824
[0.794, 0.852]). This model's edge is HIGH-severity recall and operational cost
(0 escalations, 0 missed HIGH → severity-weighted cost 0.000 vs DeepSeek's
0.006); DeepSeek's edge is clean-pair discipline. Report both — see Results.

## Quick Start

```python
# Block 1 — load the adapter
# Requires: mlx==0.32.0, mlx-lm==0.31.3, Python 3.11+ (pinned to this repo's
# training/eval environment — see reconforge/model/uv.lock)
from huggingface_hub import snapshot_download
from mlx_lm.lora import load

adapter_dir = snapshot_download("caiotheodoro/reconforge-recon-lora")
model, tokenizer = load(
    "mlx-community/Qwen3-1.7B-4bit",
    adapter_path=adapter_dir,
    tokenizer_config={"trust_remote_code": True},
)
```

```python
# Block 2 — build the prompt
import json

SYSTEM_PROMPT = """You are ReconForge, a financial back-office reconciliation operations engine. \
You reconcile a single ledger entry against a single bank statement entry and return a structured verdict.

Your output MUST be exactly one JSON object with these keys:
- "verdict": "MATCH" | "EXCEPTION" | "ESCALATE"
- "exception_type": null or one of AMOUNT_MISMATCH, FX_CONVERSION_ERROR, \
BENEFICIARY_MISMATCH, COUNTERPARTY_MISMATCH, VALUE_DATE_MISMATCH, MISSING_MESSAGE, \
DUPLICATE, FIELD_CORRUPTION, PARTIAL_MATCH
- "severity": "LOW" | "MEDIUM" | "HIGH"
- "confidence": float in [0, 1]
- "reason": short reason, under 10 words
- "resolution": one of "auto-adjust", "escalate", "reject", "rebook", "flag-review"
"""

user_prompt = """Reconcile the following ledger entry against the bank statement.

LEDGER ENTRY:
{
  "amount": "10000.00", "ccy": "USD", "counterparty": "Acme Corp",
  "beneficiary": "Acme Corp", "value_date": "2024-01-15",
  "message_type": "MT300", "ref": "OUR-REF-000001"
}

BANK STATEMENT:
{
  "amount": "9999.50", "ccy": "USD", "counterparty": "Acme Corp",
  "beneficiary": "Acme Corp", "value_date": "2024-01-15",
  "message_type": "MT940", "ref": "CP-PAY-000001"
}

Return the verdict JSON object only."""
```

```python
# Block 3 — generate
from mlx_lm.generate import generate

for attr in ("has_thinking", "enable_thinking"):
    if hasattr(tokenizer, attr):
        setattr(tokenizer, attr, False)

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": user_prompt},
]
prompt = tokenizer.apply_chat_template(
    messages, add_generation_prompt=True, enable_thinking=False, return_dict=False
)
response = generate(
    model, tokenizer, prompt, max_tokens=128,   # single greedy sample --
                                                 # a minimal usage example,
                                                 # NOT the eval config
)
verdict = json.loads(response)
print(f"{verdict['verdict']} / {verdict['exception_type']} / {verdict['severity']}")
```

> **This Quick Start uses one greedy sample. It is a minimal usage example,
> not the eval configuration.** The Results below were produced with
> self-consistency sampling (5 samples, temp=0.6, majority vote) — see the
> Run configuration table. A single greedy sample will not reproduce the
> reported numbers.
>
> The model is trained in non-thinking mode (`enable_thinking=False`) and
> emits ~38 tokens per verdict on average. Leaving thinking enabled changes
> the output format and breaks the parse.

## Results

**Eval set:** ReconEval `v0.1.0`, 800 held-out tasks, seed 777, exact-overlap
contamination 0/800 (near-duplicate rate 3.6% at Jaccard ≥ 0.8 — see
[recon-eval](https://huggingface.co/datasets/caiotheodoro/recon-eval)).

All CIs are 95% bootstrap intervals, 10,000 resamples, seed 11, over the same
800-task set per model (`reconforge/model/scripts/intervals.py` for accuracy /
R_w / HIGH recall; `reconforge/model/scripts/rescore_flag_metrics.py` for flag
precision / F1 / severity-weighted cost).

| Model | Params | Accuracy [95% CI] | R_w [95% CI] | Flag precision [95% CI] | Flag F1 [95% CI] | HIGH Recall [95% CI] | Norm. cost [95% CI] | Parse | Cost |
|---|---|---|---|---|---|---|---|---|---|
| **ReconForge Recon** | 1.7B | 0.805 [0.778, 0.833] | **0.901** [0.876, 0.924] | 0.824 [0.785, 0.862] | 0.824 [0.794, 0.852] | **1.000** [1.000, 1.000] | **0.000** [0.000, 0.000] | 1.000 | $0 |
| DeepSeek v4-flash | — | 0.876 [0.853, 0.899] | 0.872 [0.843, 0.899] | **1.000** [1.000, 1.000] | **0.904** [0.880, 0.926] | 0.995 [0.983, 1.000] | 0.006 [0.001, 0.013] | 0.996 | API (per-token; not independently verified here) |
| Base Qwen3-1.7B | 1.7B | 0.678 [0.645, 0.710] | 0.600 [0.548, 0.650] | 0.852 [0.809, 0.893] | 0.717 [0.677, 0.755] | 0.875 [0.825, 0.921] | 0.145 [0.089, 0.206] | 0.999 | $0 |

Flag precision / F1 is the false-positive-aware partner to R_w (issue #8): a
"flag" is any predicted verdict ≠ MATCH, scored over all 800 tasks. R_w alone
is gameable — a degenerate always-ESCALATE model scores R_w 0.696 at accuracy
0.0 (`docs/BENCHMARK.md`). **DeepSeek makes zero false positives on the 419
clean pairs and wins on F1 (0.904 vs 0.824); this model does not.** The
severity-weighted cost column (cost_esc = 1.0 per review, cost_missed_high =
5.0 per missed HIGH — `metrics.severity_weighted_cost` defaults) is where this
model leads: 0.000 (never escalates, never misses a HIGH) vs DeepSeek's 0.006.

**Champion vs. DeepSeek v4-flash, paired bootstrap (same 800 tasks, 10,000 resamples):**

| Comparison | Difference | 95% CI | Significant (α=0.05) |
|---|---|---|---|
| Accuracy (Recon − DeepSeek) | −0.071 | [−0.096, −0.046] | Yes — DeepSeek higher |
| R_w (Recon − DeepSeek) | +0.029 | [0.008, 0.052] | Yes — ReconForge Recon higher |

Both gaps are real, not noise: ReconForge Recon trades a statistically
significant amount of raw accuracy for a statistically significant gain in
severity-weighted recall.

**Run configuration:**

| | ReconForge Recon | DeepSeek v4-flash | Base Qwen3-1.7B |
|---|---|---|---|
| Temperature | 0.6 | 0.0 | 0.0 |
| top_p | 1.0 | (provider default) | 1.0 |
| max tokens | 256 | 1024 | 256 |
| Samples per task | 5 (self-consistency, majority vote) | 1 | 1 (greedy) |
| Prompt version | `v1` | `v1` | `v1` |
| Thinking mode | off | n/a | off |
| Eval date | 2026-08-08 | 2026-08-08 | 2026-08-08 |
| Model revision | `adapters/champion` @ this repo | API snapshot 2026-08-08 (provider exposes no pinned revision id) | `mlx-community/Qwen3-1.7B-4bit`, no adapter |

Full machine-readable run configs: `docs/validation/runconfig.json` in the
source repo.

> R_w is severity-weighted recall over the exception subset only (381 of the
> 800 tasks). It is **not** computed over the full eval set. Parse failures
> count as misses and remain in the denominator
> (`reconforge_model/metrics.py`), the conservative choice.
>
> ECE for ReconForge Recon is 0.0875 (self-consistency ECE, from the champion
> eval run). DeepSeek and base Qwen do not use self-consistency sampling in
> this eval, so a comparable ECE was not computed for them here — reported as
> not available rather than estimated.

### Per-Exception Recall (ReconForge Recon)

Exact verdict+type match recall, with 95% bootstrap CI, grouped by the
*expected* exception type:

| Exception Type | Recall [95% CI] | n | R_w weight |
|---|---|---|---|
| AMOUNT_MISMATCH | 1.000 [1.000, 1.000] | 73 | 1.0 |
| FX_CONVERSION_ERROR | 1.000 [1.000, 1.000] | 32 | 1.0 |
| BENEFICIARY_MISMATCH | 1.000 [1.000, 1.000] | 42 | 0.9 |
| MISSING_MESSAGE | 1.000 [1.000, 1.000] | 45 | 0.6 |
| COUNTERPARTY_MISMATCH | 0.865 [0.744, 0.970] | 37 | 0.9 |
| VALUE_DATE_MISMATCH | 0.692 [0.564, 0.814] | 52 | 0.6 |
| PARTIAL_MATCH | 0.688 [0.517, 0.846] | 32 | 0.5 |
| FIELD_CORRUPTION | 0.270 [0.133, 0.421] | 37 | 0.2 |
| DUPLICATE | 0.000 [0.000, 0.000] | 31 | 0.2 |

The weight column is included deliberately: R_w = 0.901 despite two recall
figures below 0.3 (FIELD_CORRUPTION, DUPLICATE), because those two types
carry the lowest weights — a reader who cannot see that will assume the
headline is inflated. Note the CI widths at n = 31–52: COUNTERPARTY_MISMATCH's
point estimate (0.865) carries a CI spanning [0.744, 0.970] — treat single
decimal-place differences between runs at this sample size as noise, not
signal.

## Training

| Parameter | Value |
|---|---|
| Base model | `mlx-community/Qwen3-1.7B-4bit` |
| Method | MLX-LoRA |
| LoRA rank / alpha / dropout | 16 / 32 / 0.05 |
| Target modules | All linear layers (16 layers) |
| Optimizer | AdamW |
| Learning rate | 1e-5 |
| Batch size | 2 |
| Max sequence length | 2048 |
| Grad checkpointing | Enabled |
| Seed | 7 |
| Iterations | 740 (early stopped at plateau) |
| Train loss | 2.4 → 0.088 |

**Compute infrastructure:** Apple M5, 16 GB unified memory. Wall time ~100
min (740 iterations). Peak memory 3.346 GB. No GPU cluster, no distributed
training. macOS version at training time was not captured — not restated here
as a placeholder.

**Framework versions:** `mlx==0.32.0`, `mlx-lm==0.31.3`, Python `3.11.15`
(from `reconforge/model/uv.lock`).

**CO2:** Not measured. Order-of-magnitude: ~100 minutes of M5 CPU/GPU package
power on a laptop-class chip — negligible relative to any cloud training run,
but not formally estimated (`co2_eq_emissions` was not computed and is not
asserted here).

**Training data:** 3,198 synthetic reconciliation pairs (train, seed 7) + 802
(val). Stratified split by (difficulty decile, exception type). Contamination
guard: SHA-256 field-level pair signatures, zero exact overlap between train
and eval — see [recon-eval](https://huggingface.co/datasets/caiotheodoro/recon-eval)
for the full audit including the near-duplicate rate this exact-hash check
does not cover.

## Ablation — DUPLICATE recall across two checkpoints

| Run | Train pairs | Self-consistency | DUPLICATE recall | R_w | Accuracy |
|---|---|---|---|---|---|
| champion (740 iters) | 3,198 | x5 | 0.000 (0/31) | 0.901 | 0.805 |
| b2 (590 iters) | 3,201 | x3 | 0.032 (1/31) | 0.723 | 0.769 |

(Flag precision / F1 for the b2 run was not re-scored — outside issue #8's
scope. The champion ×5 run's flag F1 is 0.824 [0.794, 0.852]; see Results.)

Both runs used almost identical training-pair counts (3,198 vs 3,201) — so
this pair of runs does **not** cleanly isolate a data-scale effect: b2 also
differs in checkpoint (590 vs 740 iterations) and eval self-consistency (x3
vs x5), both of which move R_w and accuracy on their own. What the data does
support: at comparable data volume, DUPLICATE recall stayed at or near zero
across both checkpoints (0/31 and 1/31), while every other metric moved
substantially between the two runs. That is consistent with — but does not
prove — the discriminating signal for DUPLICATE (`statement.reference ==
ledger.reference` while all other fields match) being a single
exact-equality predicate the model doesn't reliably attend to, rather than a
data-volume problem. A clean data-scaling ablation (same checkpoint,
different train-set sizes) has not been run; treat the "architecture/scale
limit, not data limit" framing as a hypothesis this ablation is consistent
with, not a proven conclusion. Either way, DUPLICATE detection is free and
exact with a deterministic reference-equality pre-check — see Out-of-scope
use.

## Uses

**Direct use.** Classifying ledger↔statement reconciliation pairs into
MATCH / EXCEPTION(type, severity) / ESCALATE with a structured JSON verdict.

**Downstream use.** As one scorer inside a larger reconciliation pipeline, behind
a rule pre-check and in front of a human review queue.

**Out-of-scope use — read this before deploying.**

- **Duplicate detection.** Recall is 0.000 on the eval set. Use a
  deterministic reference-equality check. Routing duplicates to this model
  means missing (nearly) all of them.
- **Uncertainty signalling.** The model emits ESCALATE zero times in this
  eval. It has no demonstrated way to say "unsure." **The system layer must
  compensate: every HIGH-severity verdict routes to human review
  unconditionally.** This is a deployment requirement, not a caveat.
- **Live financial data.** Trained on synthetic pairs only. Performance on
  real ledgers is unmeasured.
- **Autonomous judging.** As an LLM judge against the oracle on a 100-task
  golden set, it reaches Cohen's kappa 0.74 (computed directly from
  `docs/validation/golden-100.jsonl`), below a 0.85 threshold for
  unsupervised use.
- **Any non-reconciliation domain.** Single-domain by construction; does not
  transfer to payment repair or settlement.

## Limitations and Bias

1. **Synthetic data only.** Generated from a parameterized oracle, not
   sampled from production systems. Real reconciliation traffic has
   correlations, seasonality, and counterparty long tails this data does not
   model. Treat the absolute numbers as an upper bound.
2. **DUPLICATE recall ~0.** See Ablation above — not fixable by the
   data-volume change tested so far.
3. **Zero escalations observed** in this eval run — see Out-of-scope use.
4. **Judge calibration gap.** Kappa 0.74 vs oracle. ECE 0.0875 self-consistency
   — treat any single-sample deployment as uncalibrated relative to this
   number, which was measured under 5-sample self-consistency.
5. **Single-domain.** No transfer evidence to payment repair or settlement.
6. **Generator bias.** The eval set inherits every bias of the generator,
   including its exception-type mix and difficulty distribution. A model
   tuned to that generator will look better than it is on any other
   distribution. The near-duplicate audit (3.6% at Jaccard ≥ 0.8) bounds
   train/eval leakage; it says nothing about generalization beyond the
   generator's distribution.

## Card metadata

- **Authors:** Caio Theodoro
- **Contact:** via the HF repo discussions tab
- **Repository:** https://github.com/caiotheodoro/reconforge

**Synthetic data.** All tasks are generated, not drawn from live financial
systems. No real counterparties, account identifiers, or personal data are
present. The methodology is the contribution; the data is an instrument for
measuring it.

**Not production-validated.** Nothing here is financial advice or a validated
control. Any deployment touching real money requires independent validation
and a human-in-the-loop review path for high-severity cases.

## Citation

```bibtex
@misc{theodoro2026reconforge,
  title  = {ReconForge: Severity-Weighted Evaluation for Financial Reconciliation Agents},
  author = {Caio Theodoro},
  year   = {2026},
  url    = {https://github.com/caiotheodoro/reconforge},
  note   = {LoRA adapter for Qwen3-1.7B, Apache-2.0}
}
```
