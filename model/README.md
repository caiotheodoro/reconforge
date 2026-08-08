---
license: apache-2.0
base_model: mlx-community/Qwen3-1.7B-4bit
tags:
  - fine-tune
  - finance
  - reconciliation
  - mlx
  - lora
datasets:
  - synthetic (reconforge generator)
metrics:
  - accuracy
  - severity-weighted recall
---

# ReconForge Recon — reconciliation verdict model

A LoRA fine-tune of **Qwen3-1.7B** (4-bit, MLX) that classifies financial
back-office reconciliation pairs: given a ledger entry and a counterparty
statement entry, emit a structured verdict — `MATCH | EXCEPTION(type) |
ESCALATE` with severity, confidence, and resolution.

**Headline result (800-task held-out benchmark, seed 777, zero
contamination):**

| Model | Accuracy | Severity-weighted recall | HIGH-severity recall | Parse rate |
|---|---|---|---|---|
| **ReconForge Recon (this model)** | 0.805 | **0.913** | **1.000** | 1.000 |
| DeepSeek v4-flash (frontier, zero-shot) | 0.876 | 0.872 | — | 0.996 |
| Base Qwen3-1.7B (zero-shot) | — | 0.600 | — | 0.999 |

On the metric that matters for ops — severity-weighted recall (missing a
high-severity exception is money) — a 1.7B model fine-tuned on a laptop beats
a frontier model, at zero API cost and zero reasoning-token overhead.

## Training

- **Method**: MLX-LoRA (rank 16, alpha 32, dropout 0.05, grad checkpoint,
  batch 2), 4-bit Qwen3-1.7B base, 740 iterations, ~1h40 on Apple M5 (16GB).
- **Data**: 3,198 synthetic reconciliation pairs (train) + 802 (val) from the
  ReconForge generator: seeded, difficulty-parameterized, adversarial
  near-misses (rounding-tolerance boundary pairs, wrong-but-plausible FX
  rates), 9 exception classes with severity weights. Train/val stratified by
  (difficulty decile, exception type); zero signature overlap.
- **Benchmark**: 800 held-out tasks from a different seed (777); zero
  signature overlap with training verified (SHA-256 pair signatures).
- **Non-thinking mode** (`enable_thinking=False`): structured task, no
  reasoning budget needed — 38 tokens/verdict.

## Scoring (CONTRACTS of the benchmark)

- HIGH-severity exception caught = flagged as anything other than MATCH.
- MEDIUM/LOW caught = exact exception_type identified.
- R_w = Σ w·caught / Σ w over exception tasks, weights: AMOUNT_MISMATCH &
  FX_CONVERSION_ERROR 1.0, BENEFICIARY & COUNTERPARTY 0.9, VALUE_DATE &
  MISSING_MESSAGE 0.6, PARTIAL_MATCH 0.5, DUPLICATE & FIELD_CORRUPTION 0.2.

## Known weaknesses (honest)

- **DUPLICATE recall ≈ 0**: the signal (statement ref == ledger ref) is
  subtle; a B2 study showed more training data does not fix it — production
  should catch duplicates with the rule verifier pre-check, not the model.
- **Zero escalations**: the model never says "unsure"; the system layer
  compensates (HIGH severity → always escalate for HITL review).
- **Judge calibration**: as an LLM judge this model reaches Cohen's kappa
  0.74 vs the oracle (same as DeepSeek) — below the 0.85 target.
- Synthetic data only; the methodology is the subject, not live financial
  data.

## Reproduce

```sh
# datasets + benchmark
cd model && PYTHONPATH=../forge/src:src uv run python -m reconforge_model.benchmark_eval \
  --adapter-path adapters/champion --tasks-file data/benchmark.jsonl --run x5 --samples 5
```

Full pipeline: [github.com/caiotheodoro/reconforge](https://github.com/caiotheodoro/reconforge).
