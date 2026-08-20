# ReconForge

**Benchmark-grade evaluation for financial back-office reconciliation agents.**

A locally fine-tuned Qwen3-1.7B (MLX-LoRA, ~2h on an Apple M5) that beats a
frontier model on the metric that matters — severity-weighted recall — on a
benchmark built with reproduced ARC-style methodology, with the whole system
running on Kafka + Temporal Cloud + a Postgres audit ledger.

## The headline (800-task held-out benchmark, seed 777, zero contamination)

| Model | Accuracy | Severity-w. recall | HIGH-severity recall | Parse |
|---|---|---|---|---|
| **ReconForge Recon (1.7B LoRA, ours)** | 0.805 | **0.913** | **1.000** | 1.000 |
| DeepSeek v4-flash (frontier, zero-shot) | 0.876 | 0.872 | — | 0.996 |
| Base Qwen3-1.7B (zero-shot) | — | 0.600 | — | 0.999 |

A 1.7B model fine-tuned on a laptop catches every high-severity exception on
the benchmark and wins severity-weighted recall over a frontier model — at
zero API cost and zero reasoning-token overhead.

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
make sync && make validate   # all suites green (162 tests)
make study                   # pilot benchmark (400 tasks, seed 7)
docker compose up -d         # kafka, postgres, neo4j, redis
```

See `docs/BENCHMARK.md`, `docs/DECISIONS.md`, and `model/README.md` (HF card).
