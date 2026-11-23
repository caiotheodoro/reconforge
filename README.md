# ReconForge

**A financial back-office reconciliation benchmark, a LoRA fine-tune of Qwen3-1.7B scored on it, and the retraction of the claim that the fine-tune beats a frontier model.**

> ## ⚠ Status: the headline is retracted
>
> This repository first said that a 1.7B model fine-tuned on a laptop beats a
> frontier model (DeepSeek v4-flash) on severity-weighted recall, R_w 0.9007
> against 0.8719, a margin of 0.0288 on the 800-task seed-777 pool. That claim
> is withdrawn. The paper is [`paper/reconforge.pdf`](paper/reconforge.pdf)
> (source `paper/reconforge.tex`); it is not peer reviewed.
>
> A pre-registered rule (`PRE-REGISTRATION.md` section 11, dated 2026-08-29,
> before the runs) said that if the standard deviation across training seeds
> exceeded the margin, no single-run claim was supportable. Four runs of the same
> recipe, differing only in the training seed, scored R_w
> **0.7457 / 0.8198 / 0.8353 / 0.9451** on one development pool. The shipped model
> is the highest. The standard deviation is **0.0823, 2.86 times the margin**.
>
> That figure includes the shipped run, which was chosen because it scored well.
> The three runs trained afterwards give SD 0.0479, 1.66 times the margin, with a
> 95% interval on the SD that includes the margin. The comparison is
> **underpowered, not reversed**: four runs, and the spread was measured on a
> 300-task pool (seed 13) while the margin comes from the 800-task pool (seed 777).
> DeepSeek was not scored on the spread pool.
>
> An exploratory rerun with the same prompt (every class defined) and five
> samples for both models gives a matched margin of −0.0288 [−0.0432, −0.0160]
> and the fine-tune fails two of the five registered guards. With each model on
> its own best prompt, DeepSeek still leads by 0.0701. These reruns are on the
> pool the headline was selected on and are not the registered test.
>
> The shipped model's catching every HIGH-severity exception at cost 0.000 is
> not a property of the recipe: the other three runs score nonzero cost.
>
> No score on the frozen seed-999 test pool exists. `docs/THREATS-TO-VALIDITY.md`
> lists what this repository does and does not show, and the errors found in it.
>
> The public record lagged: until this release the repository carried the
> headline with no box, and `PRE-REGISTRATION.md` was not public (it was tagged
> in a local copy, with no third-party timestamp).

## The published run, kept for the record

> The table is the retracted headline's run, shown because it is the artifact the
> retraction is about, not as evidence for it. R_w and flag F1 are the **×5
> self-consistency** run with 95% bootstrap CIs (`docs/validation/intervals.json`,
> `flag-metrics.json`). Seed 777 is held out from *training* (the pool is seed
> 101) but not from *selection*: run-1 vs B2 and ×3 vs ×5 were chosen on it, so the
> figures are development-set numbers. Exact-signature contamination is zero;
> a MinHash audit puts every benchmark task at Jaccard 0.6 or higher to its
> nearest training task.

| Model | Accuracy | Severity-w. recall | Flag precision | Flag F1 | HIGH-severity recall | Parse |
|---|---|---|---|---|---|---|
| **ReconForge Recon (1.7B LoRA, ours)** | 0.805 | **0.901** [0.876, 0.924] | 0.824 [0.784, 0.862] | 0.824 [0.793, 0.853] | **1.000** | 1.000 |
| DeepSeek v4-flash (frontier, zero-shot) | 0.876 | 0.872 | **1.000** [1.000, 1.000] | **0.904** [0.880, 0.926] | — | 0.996 |
| Base Qwen3-1.7B (zero-shot) | — | 0.600 | 0.852 [0.809, 0.893] | 0.717 [0.677, 0.755] | — | 0.999 |

The model in the table catches every high-severity exception on this benchmark at zero API cost and zero reasoning-token overhead. Whether the recipe reliably produces such a run is answered above, and the answer is no.

Flag precision/F1 (95% bootstrap CI, 10k resamples) is the false-positive-aware
partner to R_w — R_w only scores the exception subset, so it can't see a model
that over-flags clean pairs. DeepSeek makes **zero false positives** on the 419
clean pairs and wins on F1 (0.904 vs our 0.824); the fine-tuned model trades
some clean-pair precision for its HIGH-severity recall. R_w alone is gameable:
a degenerate always-ESCALATE model scores R_w 0.6673 at accuracy 0.0 on this
800-task pool — and the base model scores 0.6002, *below* that floor (see
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
- **Contamination**: train/benchmark **exact-signature** overlap = 0. That is
  the precise claim; it is not "the benchmark is unlike the training data".
  A MinHash audit puts 29/800 eval tasks (3.62%) at Jaccard ≥ 0.8 to their
  nearest training neighbour, and the nearest-neighbour histogram has **no mass
  below 0.6** — 771/800 tasks sit in [0.6, 0.8). Both pools come from one
  generator, so this is expected, but it bounds how novel the benchmark is to
  the model. Removing the near-duplicates *raises* every model slightly and
  shifts the champion-vs-DeepSeek R_w margin by +0.0006, so the margin is not
  an artefact of that slice (`docs/validation/dedup-sensitivity.json`).
  The monitor ROC (fires 1.0 on leaked, 0.0 false-fire on clean) demonstrates
  **monitor correctness**, not leak-detection power — an exact-hash monitor
  fires by construction.
- **Calibration**: self-consistency confidence ECE 0.0875 on the ×5 headline
  run (0.1175 on the ×3 run). Both were computed with a whole-JSON majority
  vote; the corrected decision-level vote moves the ×5 figure to 0.0925
  (`docs/validation/majority-vote-audit.json`). HIGH-severity recall 1.0
  [0.980, 1.000] (Wilson, 184/184).
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
make sync && make validate   # forge, knowledge, model, system suites and the paper checks
make paper                   # regenerate the paper's numbers, tables, figures and PDF
make study                   # pilot benchmark (400 tasks, seed 7)
docker compose up -d         # kafka, postgres, neo4j, redis
```

CI (`.github/workflows/ci.yml`) runs the forge tests and the paper checks. The
model suite needs Apple silicon (`mlx-lm`) and the system suite a Temporal dev
server, so those two run locally.

See `docs/BENCHMARK.md`, `docs/DECISIONS.md`, `docs/THREATS-TO-VALIDITY.md`, and
`model/README.md` (HF card).

## Data and license

- Code is `Apache-2.0` (`LICENSE`). The paper (`paper/reconforge.tex`, `.pdf`) is
  `CC BY 4.0`; `CITATION.cff` and `.zenodo.json` carry its metadata (decision
  D-P1 in `docs/DECISIONS.md`).
- All data is synthetic, from the seeded generator in `forge/`. No customer,
  employer or live financial data is used anywhere in this repository.
- The paper's numbers, tables and figures are built from `docs/validation/*.json`
  by `paper/build_assets.py`; `paper/tests/` fails if the prose carries a figure
  that does not trace to one, or if the rendered PDF loses text.
- Not in this repository: the scripts that produced the training-seed and
  matched-comparison artifacts, and the changes to `model/src` they depend on
  (see D-P1). The committed per-task exports are enough to re-score every
  published run and the matched contrasts, and `paper/` does so.
