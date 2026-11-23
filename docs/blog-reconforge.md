Back-office reconciliation is a narrow, well-specified task: match a ledger entry against a bank statement, and when they disagree, name the exception. It looks like exactly the kind of job a small fine-tuned model should win — bounded vocabulary, structured output, no open-ended reasoning.

So I built a benchmark for it, fine-tuned [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) on a laptop, and measured it against DeepSeek v4-flash.

Six properties of that benchmark turned out to determine the answer more than either model did. Each is measurable, each takes under a day to check, and each is what a vertical benchmark produces by default rather than by mistake. This post is those six, with the reconciliation task as the worked example.

The measured answer, for completeness, from an exploratory rerun (not the registered test): on matched prompts at matched decode budgets, DeepSeek leads on every metric. The 1.7B reaches the same neighbourhood at a fraction of the latency and zero marginal cost.

## The task and the metric

Every trade, transfer and FX deal produces two records: your ledger entry and the counterparty's statement. Ops matches them, straight-through when they agree, investigates when they don't. An exception is an amount off by a fraction, a wrong FX rate applied at booking, a beneficiary name that doesn't match, a value date on a non-business day, or a message that never arrived.

These fail with different financial severity. A missed amount mismatch is principal at risk; a duplicate is a rebook at worst. So the headline metric is severity-weighted recall: each caught exception weighted by what missing it costs, summed over the exception set.

That premise is sound. Everything interesting below happens downstream of it.

## The benchmark

800 tasks from a seeded, difficulty-parameterized generator — SWIFT and ISO 20022 message pairs with injected exceptions, adversarial near-misses, nine exception types with fixed severity weights.

Three construction properties, each enforced by code rather than assumed:

**Verifier-as-oracle.** An independent program recomputes each verdict from the ledger and statement fields alone, never reading the generator's label. It walks a fixed priority order — missing message, field corruption, amount or FX, duplicate, beneficiary or counterparty, value date, match — because a pair can deviate on several fields at once, and without a fixed order "the verifier agrees with ground truth" is an accident of which field you check first. Every generated pair is run through it and regenerated on disagreement.

**Determinism.** Same seed, byte-identical output. Every published table regenerates from committed per-task exports with one command, and CI fails if any drifts.

**Exact-signature contamination checking.** Each task carries a SHA-256 of its sorted (field, value) pairs across both sides. Train and eval share zero signatures.

All three hold. None of them was sufficient, and the first useful finding is why.

## 1. Zero contamination, measured against the wrong thing

Exact-signature overlap is 0. True, and nearly uninformative.

The nearest-neighbour Jaccard histogram between eval and train has **no mass below 0.6**, with **771 of 800** eval tasks sitting between 0.6 and 0.8 similarity to a training example. Both pools come from one generator, so this is expected — and it bounds how novel the benchmark ever was.

Dropping the 29 tasks above 0.8 moves the headline margin by 0.0006, so near-duplicates weren't driving the result. The lesson is narrower: a contamination check that tests the strictest possible definition will pass, and passing tells you almost nothing about novelty.

## 2. The baseline had negative skill

Measured against the zero-shot base model, fine-tuning looks like a 30-point gain in severity-weighted recall: 0.600 to 0.901.

A policy that flags every pair `AMOUNT_MISMATCH` without reading it scores **0.667**. The base model scores **0.600** — worse than a constant that ignores its input.

Measuring improvement from an uncalibrated baseline tells you nothing about the axis. Score the trivial policies first: always-match, always-flag, stratified-random, and the rules oracle. If your baseline loses to a constant, you don't yet know what any number on that axis means.

## 3. The metric rewards the failure it exists to catch

Severity-weighted recall scores the exception subset only. The 419 clean pairs never enter the denominator, so flagging them is free.

The textbook demonstration is a degenerate always-escalate policy: 0.667 severity-weighted recall at **accuracy 0.000**.

The version that matters is subtler. Give the fine-tune a prompt that defines the exception classes explicitly and its severity-weighted recall *rises* to 0.940 — while accuracy falls from 0.805 to **0.434** and flag precision from 0.824 to **0.508**. It starts flagging everything and the metric pays it. The headline number improves as the model gets materially worse.

Any recall-style metric scored over a subset needs a partner metric that sees what it ignores. Report flag precision and operational cost beside it, always.

## 4. One memorizable class carried the whole margin

Decomposing the margin by exception type: **PARTIAL_MATCH accounts for all of it.** At the five-sample headline run the fine-tune catches 22 of 32 and DeepSeek 5, and that class alone contributes more than the whole margin (the other eight classes net slightly negative). At three samples, the figure this post first used, it was about 97%, with 26 of 32.

Two properties of that class explain the gap without any reference to capability.

The shared prompt *names* PARTIAL_MATCH and never defines it. DeepSeek's errors scatter across BENEFICIARY_MISMATCH, COUNTERPARTY_MISMATCH and MATCH — defensible readings of an unstated rule, which is what a model guessing at an undefined label looks like.

And the 32 eval items are generated from **9 abbreviation pairs, every one of which appears in the training data**. Overlap fraction 1.0. "Learned to recognise abbreviated counterparty names" and "memorised nine strings" predict the identical score.

When one class dominates a margin, that class is the experiment. Check whether it is defined for both sides and whether its surface forms are held out.

## 5. Seed variance exceeded the effect being measured

Four runs of one recipe — same data, same hyperparameters, same 700 steps, differing only in the random seed:

| seed | severity-weighted recall | operational cost |
| --- | --- | --- |
| 202 | 0.7457 | 0.267 |
| 303 | 0.8198 | 0.167 |
| 101 | 0.8353 | 0.150 |
| 7 | 0.9451 | 0.000 |

Standard deviation **0.0823**, against a margin of **0.0288**. Run-to-run variance is **2.9× the effect**.

The best of those runs catches every high-severity exception at zero operational cost. The other three all miss high-severity exceptions. That property belongs to one draw, not to the recipe — and a single training run reported as a result cannot distinguish the two.

If run-to-run variance exceeds your effect, you do not have an effect yet. This is one afternoon of retraining and it is the check most likely to be skipped, because a result already in hand feels like a reason to stop.

## 6. The comparison was never matched

The head-to-head gave the fine-tune **five samples with majority voting** and gave DeepSeek **one greedy sample**, on the prompt that names four exception classes without defining them.

Give DeepSeek the same prompt and the same budget: severity-weighted recall 0.872 → **0.969**, accuracy **0.949**, flag precision **1.000**. It leads on every metric. The margin inverts, from +0.027 to −0.029, both intervals excluding zero.

That comparison is exploratory rather than confirmatory — it runs on the same pool whose PARTIAL_MATCH items overlap training completely, a bias favouring the small model. A clean pool moves it further against, not back.

## Where that leaves the small model

A 1.7B fine-tune reaches the same neighbourhood as a frontier model on a narrow operational task — at a fraction of the latency, zero marginal cost, running offline, with 100% output-parse discipline. For an ops pipeline processing thousands of pairs a day, those properties are worth more than a few points of recall.

The frontier model is more accurate, and under matched conditions it leads on every metric measured here. Both statements are results; neither is a correction of the other.

## How the checks were run

The falsification conditions were fixed in advance — a dated pre-registration naming the primary endpoint, the numeric guard thresholds, the multi-seed protocol, and both outcome branches, written before any of these experiments ran. Each stage was then reviewed adversarially, with the reviewer asked to break the conclusion rather than confirm it.

Those reviews caught four overstatements in my own analysis: a regression introduced while fixing the scoring harness, a rank correlation computed with a formula invalid under ties, a claim about my own toolchain asserted without checking, and two numbers computed under different aggregation rules that produced a symmetry I'd highlighted twice.

**Three of the four favoured the argument I was making.** That is the base rate to assume for unreviewed work, including this post.

## The six checks

None require new theory. All fit in a day:

1. **Measure similarity, not just identity.** Exact-hash contamination will pass. Report the nearest-neighbour distribution between your splits.
2. **Establish a floor.** Score the trivial policies. If your baseline loses to a constant, the axis isn't calibrated.
3. **Try to game your own metric** — with the model you're about to promote, not a strawman.
4. **Decompose the margin by class.** If one class carries it, ask whether it is defined for both sides and whether its surface forms are held out.
5. **Retrain with a different seed.** If run-to-run variance exceeds your effect, you don't have one yet.
6. **Match the budget and the prompt.** Count the samples each side gets. Read your prompt as a model that has never seen it would.

---

*Everything is reproducible: one command regenerates all 17 published artifacts byte-identically from committed per-task exports. The repository includes a threats-to-validity document listing what this work does not show.*
