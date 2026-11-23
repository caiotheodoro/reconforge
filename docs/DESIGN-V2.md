# Design: Confirmatory v2 Evaluation on the Frozen Seed-999 Pool

Status: **design, not a registration.** Written 2026-11-23 alongside `paper-v2.0` (P3).
Nothing here is frozen, no new model or API run has been executed, and every choice marked
**owner** remains open. `PRE-REGISTRATION.md` (v1, SHA-256 `00aa755f...`) stays frozen and
untouched.

## Why

The v1/v2 audit established that the previously published `+0.0288` $R_w$ margin of a 1.7B
LoRA fine-tune over DeepSeek v4-flash is underpowered (`SD 0.0823` across 4 runs; `0.0479`
across 3 unselected runs), relies on a single memorised class (`PARTIAL_MATCH`, 9/9 pairs
in training), and reverses under matched-prompt (`-0.0288`) and own-best-prompt (`-0.0701`)
exploratory reruns. Five concrete gaps prevent a confirmatory verdict today:

1. **Unscored frozen pool.** `docs/validation/frozen-test-seed-999-signatures.json` (800 tasks)
   was committed on 2026-08-27 before scoring and remains untouched.
2. **Small seed count & cross-pool comparison.** Only 3 unselected training seeds were trained
   (and scored on the 300-task seed-13 dev pool, whereas DeepSeek was scored on seed-777).
3. **Missing condition B.** DeepSeek with the defined-class prompt and 1 greedy sample was
   halted by provider credit exhaustion, leaving the prompt-definition and decode-budget
   effects bundled.
4. **Memorised `PARTIAL_MATCH` vocabulary.** All 9 benchmark abbreviation pairs appeared in
   training; a confirmatory pool requires held-out abbreviation pairs (`PRE-REGISTRATION.md` §4.5).
5. **Uncommitted round-2 scripts and per-task exports.** The three fresh training-seed runs
   kept only summary JSONs, not per-task exports or generating scripts.

## Planned Confirmatory Protocol

1. **Held-out generator split (`seed-999` + held-out abbreviation table):**
   - Score on the frozen 800-task `seed-999` pool (plus a dedicated held-out `PARTIAL_MATCH`
     split whose abbreviation pairs have zero overlap with the seed-101 training set).
2. **Multi-seed fine-tuning arm (owner decides $K$):**
   - Train $K \ge 10$ (or $K = 22$ for 80% power at the 3-run SD `0.0479`) fresh LoRA seeds
     with identical validation cadence, committed training script, and committed per-task JSON
     exports for every seed.
   - Select checkpoints strictly on a separate validation pool (seed 13), never on `seed-999`.
3. **Full 2×2 comparator factorial on `seed-999`:**
   - Condition A: frontier comparator, base prompt, 1 greedy sample.
   - Condition B: frontier comparator, defined-class prompt, 1 greedy sample (isolating the
     prompt-definition effect from the 5-sample decode budget).
   - Condition C: frontier comparator, defined-class prompt, 5 samples.
   - Condition E': fine-tune (all $K$ seeds), training prompt, 5 samples (decision-level vote).
   - Pin or log the exact comparator API model snapshot/date, and run a second frontier
     comparator to reduce single-provider dependence.
4. **Primary endpoint and guards:**
   - Primary endpoint: own-best-prompt paired difference `E' - C` on `seed-999` across all $K$
     training seeds (reporting both the across-seed mean, SD, and one-sample $t$-interval, plus
     paired task+pair-clustered bootstrap).
   - All five guards (`flag_precision`, `flag_f1`, `normalized_cost`, `parse_rate`, `HIGH recall`)
     evaluated per seed with zero missing exports.
5. **External timestamp and release hygiene:**
   - Sign and push the v2 registration tag (`prereg-v2`) and deposit an external timestamp
     (OSF or Zenodo) before running any model on `seed-999`.
   - Update the live Hugging Face model card (`caiotheodoro/reconforge-recon-lora`) to match
     `model/README.md`.
