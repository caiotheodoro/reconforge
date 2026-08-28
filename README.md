# ReconForge

**Benchmark-grade evaluation for financial back-office reconciliation agents.**

A locally fine-tuned Qwen3-1.7B (MLX-LoRA, ~2h on an Apple M5) that beats a
frontier model on the metric that matters — severity-weighted recall — on a
benchmark built with reproduced ARC-style methodology, with the whole system
running on Kafka + Temporal Cloud + a Postgres audit ledger.

## The headline (800-task held-out benchmark, seed 777, zero contamination)

> R_w / flag F1 are the **×5 self-consistency** champion run, with 95% bootstrap
> CIs (`docs/validation/intervals.json`, `flag-metrics.json`). The ×3 run
> (R_w 0.913, no CI) is retained in `docs/BENCHMARK.md` as a secondary
> sampling-sensitivity row, not the headline.
>
> **Selection caveat:** seed 777 is held out from *training* (the pool is seed
> 101), but not from *selection* — run-1 vs B2 and ×3 vs ×5 were both chosen on
> this set, so the headline is a dev-set number. Seed 999 is now frozen as the
> untouched test set (`docs/validation/frozen-test-seed-999-signatures.json`);
> see `docs/TRAINING.md` → Selection policy.

| Model | Accuracy | Severity-w. recall | Flag precision | Flag F1 | HIGH-severity recall | Parse |
|---|---|---|---|---|---|---|
| **ReconForge Recon (1.7B LoRA, ours)** | 0.805 | **0.901** [0.876, 0.924] | 0.824 [0.784, 0.862] | 0.824 [0.793, 0.853] | **1.000** | 1.000 |
| DeepSeek v4-flash (frontier, zero-shot) | 0.876 | 0.872 | **1.000** [1.000, 1.000] | **0.904** [0.880, 0.926] | — | 0.996 |
| Base Qwen3-1.7B (zero-shot) | — | 0.600 | 0.852 [0.809, 0.893] | 0.717 [0.677, 0.755] | — | 0.999 |

A 1.7B model fine-tuned on a laptop catches every high-severity exception on
the benchmark and wins severity-weighted recall over a frontier model — at
zero API cost and zero reasoning-token overhead.

Flag precision/F1 (95% bootstrap CI, 10k resamples) is the false-positive-aware
partner to R_w — R_w only scores the exception subset, so it can't see a model
that over-flags clean pairs. DeepSeek makes **zero false positives** on the 419
clean pairs and wins on F1 (0.904 vs our 0.824); the fine-tuned model trades
some clean-pair precision for its HIGH-severity recall. R_w alone is gameable:
a degenerate always-ESCALATE model scores R_w 0.696 at accuracy 0.0 (see
`docs/BENCHMARK.md`). Regenerate with `uv run python model/scripts/rescore_flag_metrics.py`.

## The system

```
forge/      seeded generator, verifier-as-oracle (100% agreement), pilot
            benchmark, signature contamination monitor, cadence seams
knowledge/  domain corpus (SWIFT MT, ISO 20022, settlement risk), Neo4j
            graph, grounded gate (SUPPORT/CONTRADICT/SILENT + evidence)
model/      dataset builder, MLX-LoRA training, benchmark eval, DeepSeek
            head-to-head, HF model card
system/     FastAPI services (ingest/decision/ledger/gate/hitl), Kafka,
            Temporal Cloud workflows + cadence schedules, Postgres audit
docs/       corpus, benchmark report, decision log, study results
```

## Verified claims

- **Verifier-as-oracle**: 100% agreement on generated pairs, byte-identical
  across runs (determinism).
- **Contamination**: monitor fires 1.0 on leaked sets, 0.0 false-fire on
  clean; train/benchmark signature overlap = 0.
- **Calibration**: self-consistency confidence ECE 0.118; HIGH-severity recall
  1.0.
- **Cadence (Temporal Cloud, live)**: nightly contamination probe, weekly
  judge recalibration (DeepSeek judge kappa 0.90, bar cleared; local judge
  0.37, open — see Honest limits), per-release
  benchmark matrix, drift-triggered retrain workflow. Durable HITL proven
  end-to-end: workflow → ledger → human signal → final verdict, audited.
- **Studies**: S1-S6-era sweeps + B2 negative result (training-mix rebalancing
  hurts; distribution matching beats rebalancing) + C1 judge kappa golden
  set.

## Honest limits

- Synthetic data only (the methodology is the subject, not live data).
- DUPLICATE recall ≈ 0 — a representation problem, fixed in production by the
  rule verifier pre-check, not the model (measured in B2).
- Local fine-tuned judge kappa 0.37 (regressed from 0.74 by the rubric fix
  that fixed the DeepSeek judge to 0.90) — open workstream, needs a
  judge-specific fine-tune, not more prompting.
- Base-model + eval numbers are self-measured on a self-built benchmark;
  that's the point (the methodology is published with the numbers).

## Run

```sh
make sync && make validate   # all suites green (169 passed, 1 skipped)
make study                   # pilot benchmark (400 tasks, seed 7)
docker compose up -d         # kafka, postgres, neo4j, redis
```

See `docs/BENCHMARK.md`, `docs/DECISIONS.md`, and `model/README.md` (HF card).
