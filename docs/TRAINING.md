# ReconForge training process

What we trained, in order, on which mix, what the bench said, and what we kept. Dated entries live in `DECISIONS.md`. The public number lives in `README.md` and `model/README.md`. Kafka and Temporal did not change the weights.

**Stack.** Base `mlx-community/Qwen3-1.7B-4bit`, thinking off. MLX-LoRA r=16 α=32 dropout 0.05, AdamW 1e-5, batch 2, grad checkpoint, max seq 2048. Apple M5, 16 GB. Train/val seed 7, stratified by (difficulty decile, exception type), 3198 / 802. Bench seed 777, n=800, exact signature overlap 0. Oracle is the forge verifier.

**Rules that never moved.** No 777 in train. Gold is the verifier, not a judge. Stop on loss plateau, not the step budget. Champion stays the default mix unless a new run beats it on the same 800 tasks.

## Stack lock (2026-08-07)

A1/M4: 1.7B 4-bit MLX, not a full-precision convert. M3: batch 4 thrashed the 16 GB machine (12.8 GB). Batch 2 + grad checkpoint peaked at 3.2 GB on smoke; val loss 2.74 → 0.18 in 60 steps. M2: split keeps every exception class in both sides. Assistant target is the verdict dict in Qwen chat JSONL (M1).

## Champion run, M10 (2026-08-08)

Budget 1500 steps. Stopped at 740. Train loss 2.4 → 0.088 from about step 330, then flat. Peak memory 3.35 GB. About 100 minutes. Adapter `adapters/lora-full/0000700_final`, later `adapters/champion`.

## Head-to-head, M11–M12 (2026-08-08)

Same system prompt and scorer as the student.

DeepSeek v4-flash (M11): accuracy 0.8762, R_w 0.8719, parse 0.996, escalation precision 1.0 (2 esc).

Iter-740, self-consistency ×3 (M12, `docs/BENCHMARK.md`): accuracy 0.8050, R_w **0.9128**, HIGH 1.0000, parse 1.0000, ECE 0.1175, 0 escalations. Base Qwen3-1.7B R_w 0.6002.

The Hub card later reports the champion ×5 run: accuracy 0.805, R_w **0.9007**, HIGH 1.000, parse 1.000, ECE 0.0875. Same adapter. ×3 and ×5 are both real. Do not collapse them into one number.

LOW hole on the ×3 bench: DUPLICATE 0/31, FIELD_CORRUPTION 13/37.

## B2 rebalance (2026-08-08)

Upsampled DUPLICATE and FIELD_CORRUPTION, cut AMOUNT / PARTIAL / VALUE_DATE. Retrain 590 steps.

On the same 800 tasks vs run 1: HIGH 1.0 → 0.89, MEDIUM 0.84 → 0.40, AMOUNT 73 → 56, PARTIAL 26 → 1, VALUE_DATE 37 → 8, DUPLICATE 0 → 1, FIELD_CORRUPTION 13 → 16. R_w **0.7230**.

Champion stays run 1. Cutting a class the bench tests destroys that class. DUPLICATE is a ref-equality check, not a count problem (124 examples were already enough for the model to learn “all fields agree → MATCH”).

## C2 judge prompt (2026-08-08)

Added `JUDGE_SYSTEM_PROMPT` for the weekly judge. Left the worker `SYSTEM_PROMPT` alone. Weights unchanged. DeepSeek judge kappa 0.7407 → 0.9037. Local worker-as-judge 0.7361 → 0.3672. The worker was trained on one prompt; extra rubric text is off-distribution. Production judge is DeepSeek plus the rubric. Local judge needs its own fine-tune if we want it.

## What is on Hub now

- Adapter: [`caiotheodoro/reconforge-recon-lora`](https://huggingface.co/caiotheodoro/reconforge-recon-lora) = champion (iter 740, default mix)
- Gold: [`caiotheodoro/recon-eval`](https://huggingface.co/datasets/caiotheodoro/recon-eval) (`eval` 800, `train` 3198, `golden` 100)
- Collection: [`ReconForge`](https://huggingface.co/collections/caiotheodoro/reconforge-6a89e9d6539e5b51403dd9ca)

Card metrics are the ×5 run. README headline is the ×3 run in `docs/BENCHMARK.md`.

## Stop

DUPLICATE stays a gate-layer equality check. A local judge, if wanted, is a new SFT on the rubric prompt, not another mix of the worker.
