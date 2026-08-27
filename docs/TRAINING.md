# ReconForge — Training Provenance

Authoritative record of the champion adapter's checkpoint identity and the
seeds behind the training data. Written to stop two labels that had drifted in
earlier docs (issues #3 and #4).

## Seeds — three distinct values

The champion adapter was produced with **generation seed 101, split seed 7,
training-run seed 7**. These are three different seeds that had been conflated:

| Seed | Value | Where it lives | What it controls |
|---|---|---|---|
| Generation seed | **101** | `reconforge_forge.generator.generate_tasks(n, seed)` | The synthetic task pool (ledger/statement pairs + expected verdicts). |
| Split seed | **7** | `reconforge_model.dataset_builder.build_datasets(..., seed=7)` → `stratify_split` | The stratified train/val partition of that pool. |
| Training-run seed | **7** | `reconforge_model.train --seed 7` | The MLX-LoRA run itself (init, data order). |

The benchmark uses a fourth, separate generation seed, **777**.

### Empirical verification (generation seed)

Regenerating the pool with `generate_tasks(4000, seed=101)` and running it
through `build_datasets(train_frac=0.8, seed=7)` reproduces the shipped
`model/data/train.jsonl` (3,198 rows) and `model/data/val.jsonl` (802 rows)
**byte-for-byte** — identical rendered `messages`, identical `task_id`
sequence. Generation seeds 7 (n_train 3,202) and 777 (n_train 3,199) produce
completely different pools with zero rendered-message overlap. So the training
pool's generation seed is 101, established from the artifacts, not from prose.

### Contamination re-check under seed 101

Exact-overlap check (`reconforge_forge.contamination.leak_probe`) of the
seed-101 train split against the seed-777 benchmark: **overlap 0.0, monitor
does not fire** — matches the published
`docs/validation/contamination.json` (`exact_overlap.fired = false`). Zero
train/eval signature overlap holds under the corrected generation seed.

## Checkpoint identity — champion is iter 700, not iter 740

The final training run's loop ran to **step 740** (early stop at the loss
plateau, ~0.088 since step ~330). The MLX-LoRA adapter saver writes every 50
steps, so the **last persisted checkpoint is iter 700**; the loss numbers
logged for steps 710–740 in `model/data/train-full.log` were never written to
disk (the last `Saved adapter weights` line is at `Iter 700`).

The champion adapter is that iter-700 checkpoint:

```
model/adapters/champion/adapters.safetensors
model/adapters/lora-full/adapters.safetensors
model/adapters/lora-full/0000700_final.safetensors
```

all three are byte-identical:

```
SHA-256: 4754fe569b703f075725f0415a9ae70664fda6d7d66a865e956be2ff69bacdfa
```

The benchmark run and its artifacts (`bench-eval-full-740.json`, run name
`full-740`) keep the `740` name after the run's step count; the evaluated
**weights** are iter 700. A separate, earlier aborted run also stopped at iter
700 and scored lower (R_w 0.729) — that is a different run, tracked
separately in `docs/BENCHMARK.md` and `docs/DECISIONS.md`.
