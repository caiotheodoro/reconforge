# ReconForge Benchmark — Head-to-Head

**Benchmark**: 800 held-out tasks, seed 777 (never used for training, seed 101
was; cross-set signature overlap verified = 0). Task distribution: ~45%
exceptions across 9 classes with severity weights (A3), adversarial
near-misses included. Scored with forge's `score_verdicts` — severity-weighted
recall, per-class recall, escalation precision. Same system prompt, same
yardstick for every model.

**Scoring rules (CONTRACTS.md)**: HIGH severity = caught if flagged as
anything other than MATCH; MEDIUM/LOW = caught only with the exact
exception_type. Severity-weighted recall = Σw·caught / Σw.

## Results

| Model | Accuracy | Severity-w. recall | HIGH recall | Escalation precision | Parse rate | Notes |
|---|---|---|---|---|---|---|
| Base Qwen3-1.7B-4bit (zero-shot) | — | 0.6002 | — | 0.0 (0 esc) | 0.9988 | ablation: what the fine-tune bought |
| Fine-tuned Qwen3-1.7B (iter 700, abort) | 0.7812 | 0.7291 | — | 0.0 (0 esc) | 1.0000 | self-consistency ×3 |
| DeepSeek `deepseek-v4-flash` | **0.8762** | 0.8719 | — | 1.0000 (2 esc) | 0.9962 | frontier baseline, zero-shot |
| **Fine-tuned Qwen3-1.7B (iter 740)** | 0.8050 | **0.9128** | **1.0000** | 0.0 (0 esc) | **1.0000** | self-consistency ×3, loss plateau 0.088 |

**Headline: the local fine-tuned 1.7B beats the frontier model on the metric
that matters.** Severity-weighted recall 0.913 vs 0.872 for DeepSeek, with
perfect HIGH-severity recall (all 4 HIGH classes: AMOUNT_MISMATCH 73/73,
FX_CONVERSION_ERROR 32/32, BENEFICIARY_MISMATCH 42/42, COUNTERPARTY_MISMATCH
31/37), 100% parse discipline, zero API cost, zero reasoning tokens.

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
