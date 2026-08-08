# ReconForge — Decision Log

Every architectural decision is recorded here with its rationale. Agents append
entries as they make decisions (format below). The A1 base-model decision and
severity weights are the fixed defaults from the plan; revise only with
measured evidence.

## Format

```
## YYYY-MM-DD — <study id> — <title>
- Decision: ...
- Rationale: ...
- Evidence: (file/metrics)
- Alternatives rejected: ...
```

---

## 2026-08-07 — A1 (default) — Base model: Qwen/Qwen3-1.7B
- Decision: Qwen3-1.7B (Apache-2.0, 32k context), non-thinking worker mode,
  MLX-LoRA fine-tune.
- Rationale: 16GB M5 budget (no CUDA → vLLM impossible, MLX native); narrow
  structured task → 1.7B sufficient; license-safe for public portfolio;
  Qwen3 agent/tool-calling support (SOTA small model, Qwen3 report 2505.09388).
- Evidence: pending A1 pilot (200-task zero-shot).
- Alternatives rejected: Qwen2.5-1.5B (older), Qwen3-0.6B (weaker structured
  output), 7-8B class (does not fit training budget).

## 2026-08-07 — A3 — Exception taxonomy + severity weights
- Decision: 9 exception classes with weights 1.0/0.9/0.6/0.2 as in
  CONTRACTS.md; primary metric = severity-weighted recall.
- Rationale: financial-risk ordering (principal at risk > misdirection >
  timing/STP > data quality); optimizing raw accuracy would reward models
  that only fix low-severity cases.
- Evidence: domain analysis (FX/back-office ops).

## 2026-08-07 — S1 — One uv project per service-suite (single venv at system/)
- Decision: one `pyproject.toml` + one venv for all six services instead of
  per-service venvs.
- Rationale: all services import the same `contracts.py`, `kafka_util.py`,
  `config.py`; they are thin HTTP seams co-deployed by one compose host;
  single `uv sync` keeps the integrator's job trivial; matches the root
  Makefile (`cd system && uv run pytest`).
- Evidence: system/ green suite (`uv run pytest -q -m "not integration"`).
- Alternatives rejected: per-service pyprojects (duplicated contracts, 6 syncs).

## 2026-08-07 — S2 — Decision routing thresholds (config-driven)
- Decision: escalate iff verdict==ESCALATE or severity in
  DECISION_ESCALATE_SEVERITIES (default ["HIGH"]) or confidence <
  DECISION_CONFIDENCE_THRESHOLD (default 0.6); else record to
  recon.verdicts (EXCEPTION verdicts also to recon.exceptions). All
  env-overridable via pydantic-settings.
- Rationale: matches CONTRACTS.md "anything other than MATCH for HIGH
  severity" catch rule for severity-weighted recall; low-confidence results
  must reach a human before any STP action.
- Evidence: test_decision.py.

## 2026-08-07 — S3 — Ledger is the single DB writer; reviews live in Postgres
- Decision: only `ledger` (9103) writes Postgres (`recon_entries`,
  `recon_reviews`); decision/hitl/cadence call it over HTTP. Drop-to-ledger
  fallback records a `source=system` entry when Kafka is down.
- Rationale: one audit-trail writer = one schema/validation owner; the audit
  trail must survive Kafka outages; reviews are durable (not in-memory),
  which the HITL queue needs across restarts.
- Evidence: test_ledger.py + postgres:16 smoke test (migration 001_init
  applied, task_id idempotency verified).
- Alternatives rejected: hitl queue in Redis (ephemeral, second writer), or
  Temporal-only queue (no SQL query surface for GET /queue).

## 2026-08-07 — S4 — Durable-HITL: Temporal signal pattern, activity-persisted queue
- Decision: `DecisionWorkflow` persists the "requires-review" state via the
  `open_review` activity (ledger `recon_reviews` row), then blocks on the
  `review-resolution` signal with a configurable timeout (default 24h);
  signal name is explicitly `name="review-resolution"` (Python SDK would
  otherwise register the handler as the method name and silently buffer the
  signal). Timeout produces a deterministic timed-out completion with
  `source=system`.
- Rationale: mirrors production agent-harness durable signal patterns; the
  review is both queryable (SQL) and durable (Temporal) with a guaranteed
  terminal state (human verdict or timeout), satisfying auditability.
- Evidence: test_workflows.py env tests (signal path, timeout path).
- Alternatives rejected: review state only in Temporal (no queue query),
  only in Kafka (no durable state machine).

## 2026-08-07 — S5 — Cadence schedules: 4 Temporal Schedules
- Decision: `recon-contamination-probe` (daily 03:00), `recon-judge-
  recalibration` (weekly Mon 04:00), `recon-drift-check` (hourly; PSI on
  exception-type distribution vs DRIFT_BASELINE_JSON, threshold
  DRIFT_PSI_THRESHOLD=0.10 -> `retrain-triggered` + external hook stub),
  `recon-benchmark` (on-demand, paused schedule, seeds [7,13,42]).
  All cadence events published to `recon.cadence-events` via an activity
  (workflows stay deterministic); registration is idempotent
  (create-or-update) via ScheduleClient.
- Rationale: cadence = measurement loop that closes the retrain loop; PSI on
  the exception-type distribution is the cheapest stable drift signal
  available from the ledger before model-side metrics exist.
- Evidence: schedule_registry builds valid Schedule objects against
  temporalio 1.31; CadenceWorkflows exercised in the test env.
- Alternatives rejected: drift on raw verdict counts (not normalized), drift
  on model confidence (unstable pre-calibration).

## 2026-08-07 — S6 — Deterministic workflow cores, all I/O in activities
- Decision: workflows import only stdlib + `reconforge_system.drift` (pure
  PSI); every external effect (kafka publish, ledger HTTP, forge/knowledge
  imports) lives in activities with lazy imports; `reconforge_forge` /
  `reconforge_knowledge` are optional with explicit "stub" markers in their
  outputs.
- Rationale: Temporal sandbox determinism is the audit guarantee; the
  other workstreams can land later without touching workflow code.
- Evidence: CadenceEvents carry `source: "stub"` until forge/knowledge land.

## 2026-08-07 — S7 — Test infrastructure choices
- Decision: unit tests use injected fakes (publisher, model client, ledger
  store, workflow starter); one `MemoryStore` mirrors Postgres semantics;
  workflow tests use the temporalio embedded dev server with the `temporal`
  CLI binary supplied via `dev_server_existing_path` (SDK download host
  temporal.download unreachable on this network). Integration tests require
  `--run-integration`.
- Rationale: exit gate must be green with zero infra; real Postgres verified
  once via docker smoke test (port 5433, container removed afterwards).
- Evidence: 59 unit tests green; postgres integration test passed.


## 2026-08-07 — F1 — Verifier single-exception priority order
- Decision: the verifier classifies a pair by the FIRST rule that fires in a
  fixed priority: MISSING_MESSAGE > FIELD_CORRUPTION > AMOUNT/FX > DUPLICATE
  (trimmed ref equality) > BENEFICIARY (near-equal -> PARTIAL_MATCH, else
  BENEFICIARY_MISMATCH) > COUNTERPARTY (same) > VALUE_DATE > MATCH.
- Rationale: a pair can deviate in several fields; a deterministic priority
  is what makes verifier/expected agreement (the A4 gate) a property rather
  than an accident. The generator injects exactly one exception per task and
  shares the priority, so the gate holds by construction.
- Evidence: 100% oracle agreement on 400-task pilot (docs/validation/pilot-7.json).
- Alternatives rejected: multi-field reporting (breaks the single-verdict
  schema); probabilistic classification (non-deterministic).

## 2026-08-07 — F2 — Generator self-check loop enforces the oracle gate
- Decision: every candidate task is run through verify_task before
  acceptance; on disagreement the pair is regenerated (bounded tries,
  deterministic fallback). Same seed -> same sequence of draws, so the loop
  is reproducible.
- Rationale: 100% oracle agreement "must" hold; building it into generation
  (not post-hoc reconciliation) keeps it guaranteed even when tolerance
  boundaries and rounding interact (FX implied-rate vs stated-rate rounding).
- Evidence: 0 rebuilds needed across 1000 tasks (seed 7) after base-pair fix
  (F3); the loop is a safety net, not a crutch.
- Alternatives rejected: post-generation filtering (silently shrinks the
  pilot below n); trusting exact boundary math (fragile across rounding).

## 2026-08-07 — F3 — Base pair shares beneficiary/counterparty/value-date
- Decision: the generator draws one beneficiary, one counterparty, one
  value date, and one amount family per task and copies them to both sides;
  only the injected exception diverges the sides.
- Rationale: the pair is one payment seen from ledger and statement; drawing
  names independently made ~90% of base pairs look like mismatches, forcing
  the self-check loop to rebuild ~7x per task (measured 4257 verifier evals
  for 500 tasks before the fix, 500 after).
- Evidence: rebuild count 4257 -> 500 (0 failing) for seed 7.
- Alternatives rejected: adding noise-vs-mismatch discrimination to the
  verifier (would have blurred the PARTIAL_MATCH semantics).

## 2026-08-07 — F4 — PARTIAL_MATCH definition: near-equal names
- Decision: PARTIAL_MATCH fires when beneficiary/counterparty strings are
  near-equal (token-subset/one-token-drift, or raw-prefix truncation for
  compact identifiers like BICs) while all hard fields match; fully
  different names are BENEFICIARY/COUNTERPARTY_MISMATCH.
- Rationale: a crisp, shareable discriminator between "misdirected funds"
  (reject) and "ambiguous naming" (human review) that both generator and
  verifier implement identically; severity MEDIUM 0.5 per the A3 taxonomy.
- Evidence: verifier unit tests + generator oracle gate.
- Alternatives rejected: fuzzy similarity thresholds (non-deterministic
  perception), making PARTIAL_MATCH the catch-all remainder (absorbs
  everything).

## 2026-08-07 — F5 — FX semantics: stated rate is the effective rate
- Decision: for MATCH FX pairs the stated fx_rate is the implied rate
  computed from the ROUNDED local/foreign amounts (4dp), so verifier
  agreement is exact; FX_CONVERSION_ERROR tasks state a wrong-but-plausible
  rate (0.8%-5% off the true rate, min distance > verifier's 0.5% window).
- Rationale: amount rounding shifts the implied rate slightly; anchoring the
  stated rate to the rounded amounts removes that disagreement source, and
  the injection floor (0.8%) keeps the error outside the verifier window
  with margin after rounding.
- Evidence: 0 rebuilds across 1000 tasks; FX unit tests at window boundary.
- Alternatives rejected: stating the pre-rounding "true" rate (boundary
  collisions with the 0.5% window).

## 2026-08-07 — F6 — Contamination monitor: exact value-level hash signatures
- Decision: task signature = SHA-256 of sorted (field,value) pairs over
  ledger+statement (metadata excluded); leak probe fires when any eval
  signature matches the train set.
- Rationale: exact-match signatures give a clean ROC (fire-on-leaked = 1.0,
  false-fire-on-clean = 0.0 across leak fractions 0.05-0.5); value-level
  (not format-level) matching is the Gemini-3-style leak evidence — a model
  reproducing exact pair content it was never shown.
- Evidence: docs/validation/contamination-roc.json.
- Alternatives rejected: n-gram similarity (tunable, noisier; exactness is
  the right bar for "the same pair is in training data").

## 2026-08-07 — F7 — Environment note: macOS UF_HIDDEN on uv .venv
- Decision: the forge .venv intermittently gets the macOS hidden file flag on
  its files, which makes CPython 3.11's site module skip `_editable_impl_*.pth`
  and silently breaks `import reconforge_forge` ("Skipping hidden .pth
  file"). Remediation: `chflags -R nohidden .venv`. A clean `uv venv && uv
  sync && uv run pytest` does not reproduce it deterministically (external
  macOS file-flag behavior, likely Finder/FileProvider touching
  ~/Documents).
- Rationale: environment triage, recorded so other agents know the symptom
  and the one-liner if it reappears.

## 2026-08-07 — M1 — Dataset: Qwen chat JSONL with verdict-dict assistant targets
- Decision: each forge task becomes one {"messages": [system, user, assistant]}
  record; assistant content is the canonical verdict dict (camelCase keys:
  verdict/exception_type/severity/confidence/reason/resolution), serialized
  with sort_keys+compact separators for byte-stability; expected.explanation
  is truncated to <=10 words into "reason".
- Rationale: exact-JSON targets teach the worker to emit schema-valid JSON
  (parse-rate goal); byte-stable targets make dataset reproducibility
  checkable via file hash.
- Evidence: tests/test_schema.py round-trips 50 stub tasks.
- Alternatives rejected: free-text verdicts (would tank parse rate); keeping
  forge's "explanation" key (breaks the CONTRACTS verdict schema).

## 2026-08-07 — M2 — Split: (difficulty decile, exception_type) stratified
- Decision: bins = (floor(difficulty*10), exception_type) with per-bin
  proportional allocation under a seeded RNG (seed 7); train/val disjoint on
  task_id AND on SHA-256 field-level pair signatures (contamination guard
  refuses to build if overlap > 0); each split sorted by task_id for stable
  files. MATCH tasks are a (decile, None) bin so both splits keep a MATCH
  class.
- Rationale: matches the forge difficulty calibration intent (public split
  predicts private split) at finer resolution than the reference trust
  implementation's 5-bin difficulty-only split, and guarantees every
  exception class appears in both splits (required for per-class recall).
- Evidence: tests/test_dataset_builder.py (histograms, fractions in
  [0.10, 0.35], leak guard fires on clones).
- Alternatives rejected: random shuffle (unbalanced classes, leak risk),
  difficulty-only stratification (val can lose rare classes like PARTIAL_MATCH).

## 2026-08-07 — M3 — QLoRA config: rank 16 / alpha 32 / dropout 0.05, adamw 1e-5
- Decision: defaults per mission; scale = alpha/rank = 2.0 (mlx-lm LoRA scale
  convention); 16/28 layers tuned; batch 2 + --grad-checkpoint + allocator
  cache clear at 2g for the smoke footprint.
- Rationale: measured first run peaked at 12.8GB with batch 4 and no grad
  checkpoint (thrashed into swap on the 16GB M5); with batch 2 + grad
  checkpoint peak is 3.2GB, val loss 2.74 -> 0.18 in 60 steps (4.2 min).
- Evidence: model/adapters/lora-smoke/train_summary.json; docs/validation/
  model-eval-smoke-20260807.json.
- Alternatives rejected: batch 4 (OOM-thrash), full fine-tune (out of budget).

## 2026-08-07 — M4 — Base model: mlx-community/Qwen3-1.7B-4bit (non-thinking)
- Decision: the community 4-bit MLX conversion of Qwen/Qwen3-1.7B (Apache-2.0)
  as training base; tokenizer forced to non-thinking mode by setting
  has_thinking=False + apply_chat_template(enable_thinking=False) at eval,
  which renders the empty <think>\n\n</think> generation prompt.
- Rationale: exists on the hub (verified), 1.2GB weights -> QLoRA peak 3.2GB
  leaves headroom for concurrent light agents; avoids a full-precision
  convert step. Non-thinking is required for the worker contract (no CoT in
  the JSON answer).
- Evidence: smoke run; template render verified (decode shows the empty think
  block).
- Alternatives rejected: BF16 base + on-the-fly 4-bit quantize (identical
  memory, more download); Qwen3-1.7B-8bit (unnecessary with QLoRA).

## 2026-08-07 — M5 — Package install workaround: uv package=false + PYTHONPATH
- Decision: the project is NOT editable-installed into the venv. uv marks all
  venv files with the macOS UF_HIDDEN flag and CPython's site.addpackage
  silently skips hidden *.pth, so hatchling's _editable_impl_*.pth never
  loads. Instead: [tool.uv] package=false, tests/conftest.py and
  scripts/smoke.sh put src/ on sys.path.
- Rationale: deterministic across machines (vs chflags remediation which
  re-breaks on every uv sync re-creating the .pth); keeps `uv sync && uv run
  pytest -q` green as the exit gate. Same root cause as forge F7.
- Evidence: uv sync && uv run pytest -q -> 24 passed; chflags experiment
  reproduced the skip/works flip deterministically.
- Alternatives rejected: chflags nohidden after each sync (fragile, must be
  re-applied by every caller).

## 2026-08-07 — M6 — Confidence & calibration: threshold cost model 5x/1x
- Decision: calibration grid-searches a confidence threshold below which the
  verdict is overridden to ESCALATE (flag-review); cost = 5 * missed-HIGH +
  1 * escalations. Assumption documented in calib.py: a missed HIGH exception
  is principal at risk (A3) and costs 5x a bounded human review.
- Rationale: ECE is a diagnostic, not an operational target; the threshold
  search ties calibration to the severity-weighted operational objective.
- Evidence: model-calib-smoke-20260807.json (degenerate: smoke model never
  emits confidence, so ECE=0 and threshold=0 — see M7).
- Alternatives rejected: raw ECE minimization (ignores asymmetric costs).

## 2026-08-07 — M7 — Open issue: model emits confidence=0.0 (calibration vacuous)
- Decision: keep confidence in the schema but do NOT weight it in the loss
  for the smoke; flag for the full wave.
- Rationale: the 60-step smoke model (stub dataset, ESCALATE-everything
  policy) never produced a nonzero confidence, making ECE and threshold
  search vacuous (ECE=0.0). The full-wave fixes: (a) longer training on
  forge's higher-volume data, (b) sample-augmented confidence targets
  (self-consistency) or temperature-scaled post-hoc calibration from a
  calibration split.
- Evidence: docs/validation/model-eval-smoke-20260807.json (all predicted
  confidence 0.0); smoke accuracy 0.0, severity-weighted recall 0.696.
- Alternatives rejected: removing confidence (schema contract); hand-tuning
  a constant threshold (no signal yet).

## 2026-08-07 — K1 — Knowledge schema confirmed identical to corpus
- Decision: reconforge_knowledge.schema.ENTITY_TYPES / RELATION_TYPES are the
  fixed CONTRACTS.md sets; verified byte-for-byte against docs/corpus/entity-schema.md.
  No discrepancy. All extraction (LLM + deterministic + gold loader) validates
  through schema.validate_extraction before anything leaves the package.
- Rationale: the knowledge graph is the retrieval layer for the D2 study; a
  single source of truth (CONTRACTS.md) avoids drift between workstreams.

## 2026-08-07 — K2 — Deterministic extractor aligned with gold-triples.json
- Decision: the deterministic (offline) fact table mirrors the corpus gold
  triples (same head/relation/tail names where they exist, e.g.
  MT202COV COVERS CoverPaymentForCustomerCreditTransfer, CLS MITIGATES
  HerstattRisk, camt.053 COUNTERPART_OF MT940) so offline and gold-loaded
  graphs merge without (name,type) collisions. Confidence ~0.6; message-type
  presence 0.8; gold loader keeps gold confidences.
- Rationale: offline mode must be usable as the fallback retrieval base for
  the gate service, and gold triples should merge cleanly.
- Evidence: extract --offline --with-gold on docs/corpus -> 91 entities,
  88 relations, 0 invalid relation types.

## 2026-08-07 — K3 — Negations encoded as CONFLICTS_WITH (documented)
- Decision: "X does not require/carry Y" facts (e.g. MT103 does not carry the
  cover; MT202 plain must not be used as a customer cover) are encoded as
  `head CONFLICTS_WITH tail` in the graph. The lexical gate returns CONTRADICT
  only when the claim contains the conflict triple's head concept (canonical
  name token) and coverage >= 0.30 with >= 2 overlapping tokens; claims phrased
  as relational questions (relation/connect/link/difference/between/
  counterpart/...) never take the CONTRADICT branch.
- Rationale: CONTRACTS has no negation relation; CONFLICTS_WITH is the only
  carrier. Probe P01 ("Does MT103 require cover ...?") -> CONTRADICT offline
  and via LLM judge. This encoding is documented here so the corpus agent and
  the forge agent interpret CONFLICTS_WITH consistently.

## 2026-08-07 — K4 — Lexical gate thresholds and alias enrichment
- Decision: offline lexical verdicts use stemmed token-overlap coverage with
  SUPPORT_COVERAGE=0.35 and CONTRADICT_COVERAGE=0.30 (min 2 tokens). Entity
  aliases (properties["aliases"]) are appended to the triple index text and to
  the gate's token set so camelCase canonical names match natural-language
  claims. Canonical names (e.g. SingleCustomerCreditTransfer) are kept
  gold-faithful; natural phrases live in aliases.
- Rationale: pure TF-IDF on camelCase tokens cannot match "which system
  mitigates Herstatt risk" against "CLS MITIGATES HerstattRisk". Verified
  12/12 probe targets offline on the real corpus.
- Evidence: gate-qa --offline (12 probes) -> 12/12 agreement.

## 2026-08-07 — K5 — Neo4j Community Edition: name-unique + composite index
- Decision: ensure_schema() creates `REQUIRE n.name IS UNIQUE` plus a
  composite index `ON (n.name, n.type)` instead of a NODE KEY constraint.
  NODE KEY (the literal reading of CONTRACTS "unique on (Entity,name) and
  (Entity,type)") requires Enterprise Edition; Community fails with
  Schema.ConstraintCreationFailed. Entity names are unique across types in the
  corpus (verified), so name-uniqueness + composite index preserves MERGE
  semantics. Loader remains fully idempotent (MERGE on name+type).
- Evidence: load --wipe-first --idempotency-check -> 91 nodes / 88 edges
  identical after two loads.

## 2026-08-07 — K6 — Gate system seam contract (reconforge_knowledge.gate.ground)
- Decision: `ground` is an **async** callable matching the system gate
  service's `await gate(pair=..., provisional=...)` (system/src/reconforge_system/
  services/gate.py). It duck-types pydantic models or plain dicts, builds a
  claim from pair + provisional verdict, and returns
  {"verdict": SUPPORT|CONTRADICT|SILENT, "evidence": [triples], "reason": ...,
  "claim": ..., "mode": ..., "gated": true}. ground_sync() is the sync twin.
  The knowledge package never imports reconforge_system (no reverse dependency).
- Evidence: seam simulation with pydantic-style models + asyncio.run ->
  dict returned; verified 2026-08-07.

## 2026-08-07 — K7 — Extraction cache versioning
- Decision: extraction results cache to knowledge/data/extracted-<hash>.json
  keyed by (doc content hashes, mode, CACHE_VERSION). CACHE_VERSION bumped to 2
  when the fact table/types changed; stale caches were the cause of a
  (name,type) collision (MT103Cover MessageType vs PaymentInstruction) that
  surfaced only at Neo4j load time.
- Rationale: re-runs must not re-call the API, but cache invalidation must be
  explicit when extraction logic changes.

## 2026-08-07 — K8 — Open issues / infra notes
- docker-compose neo4j cannot boot on this machine: heap 1G + pagecache 256M
  exceeds the 1g mem_limit ("Invalid memory configuration - exceeds physical
  memory"). Smoke test used `docker run -e NEO4J_server_memory_heap_max__size=512M
  -e NEO4J_server_memory_pagecache_size=128M`. Infra owner should fix compose
  (reduce heap to 512M or raise mem_limit).
- uv-managed CPython 3.11.15 on macOS marks venv files with the UF_HIDDEN flag
  and skips hidden .pth files, silently breaking editable installs
  (site.py "Skipping hidden .pth file"). Workaround in place: a
  knowledge/.venv/lib/python3.11/site-packages/sitecustomize.py that re-adds
  src/ to sys.path (survives uv sync; not a managed package) plus a
  tests/conftest.py shim. A fresh `uv venv` recreates the problem; remove and
  re-add the sitecustomize if the venv is rebuilt.
- P08 (nostro vs vostro) targets SILENT on the current corpus: the corpus
  mentions "nostro accounts" but not "vostro"; the D2 study should treat P08
  as a retrieval-coverage probe (expected: no supporting triple).

## 2026-08-07 — K9 — LLM extraction validated on the real corpus; camelCase splitting
- Decision: ran the DeepSeek extraction once over docs/corpus (5 docs -> 8
  chunks, 8 API calls, cached in knowledge/data/extracted-b1f7ad3d52af741a.json).
  Result: 264 entities, 305 relations, 0 schema-invalid relations/entities.
  LLM entities carry no aliases, so lexical matching now ALSO splits
  camelCase/PascalCase names into words (vector_index.split_name, applied in
  the index text and the gate's triple tokens). The CONTRADICT head-check keeps
  raw (unsplit) name tokens so e.g. "valuedatemismatch" does not leak into
  claims containing "value date mismatch".
- Evidence: with the fix, the lexical gate scores 12/12 on the deterministic
  graph and 9/12 on the LLM graph. LLM-graph misses: P01 (negation "MT103 does
  not carry the cover" was not extracted by the LLM -> SUPPORT instead of
  CONTRADICT), P06 (camt.053-MT940 counterpart triple at coverage 0.33, just
  below the 0.35 SUPPORT threshold), P12 (no "LateValueDateRule TRIGGERS
  ValueDateMismatch" in the LLM output). These are graph-coverage gaps of the
  LLM pass, not gate defects; online (LLM-judge) mode handles them via reasoning.
- Note: the canonical knowledge/data/extracted.json is kept as the
  deterministic+gold graph (91 entities / 88 relations) because it is the
  graph validated in the Neo4j smoke test and against the probe targets.

## 2026-08-08 — M8 — DeepSeek provider behavior + concurrent eval
- Decision: max_tokens=1024 for deepseek-v4-flash (reasoning tokens eat small budgets,
  causing empty responses); 16-worker concurrent eval with JSONL checkpoint (resumable).
- Rationale: measured 33/60 empty responses at max_tokens=256, 1/60 at 1024 (empty→retry
  loop); serial 800-task run exceeded 45min, concurrent 16 → ~2min with zero losses.
- Evidence: bench-deepseek-full.json (accuracy 0.8762, R_w 0.8719, 0 empty).

## 2026-08-08 — M9 — score_verdicts robustness
- Decision: forge score_verdicts treats None predictions as parse misses (n_parse_misses),
  not crashes; verdict_accuracy/recall unaffected semantically (a miss is a miss).
- Rationale: real frontier models emit unparseable/empty outputs; the scorer must count
  them honestly, not blow up.

## 2026-08-08 — I1 — macOS venv hermeticity
- Decision: pytest `pythonpath = ["src"]` in all four workstreams + `make sync` does
  `uv sync --no-editable` + `chflags -R nohidden .venv`.
- Rationale: uv marks new venvs UF_HIDDEN by design; CPython 3.11+ skips .pth files
  under hidden dirs → editable installs silently break on every fresh venv (observed 4x).

## 2026-08-08 — M10 — Full training run (iter 740 of 1500, stopped at plateau)
- Decision: stopped at iter 740 (train loss plateaued at 0.088 since ~iter 330;
  val trajectory flat). ETA for 1500 steps was +2.5h at ~5.2 it/min with no
  expected gain; adapter preserved at adapters/lora-full/0000700_final.
- Rationale: loss-curve plateau is the stopping rule, not the step budget.
- Evidence: train-full.log (loss 2.4 -> 0.088, peak mem 3.35GB).

## 2026-08-08 — M11 — DeepSeek head-to-head baseline (800-task bench, seed 777)
- Decision: deepseek-v4-flash scored as the frontier baseline on the held-out
  benchmark with the identical system prompt + scoring.
- Evidence: accuracy 0.8762, severity-weighted R 0.8719, escalation precision
  1.0, parse 99.6%. Fine-tuned @700 steps (old run): 0.781 / 0.729. New
  iter-740 adapter under evaluation.

## 2026-08-08 — M12 — Full head-to-head: fine-tuned 1.7B BEATS DeepSeek on R_w
- Decision: iter-740 adapter is the benchmark candidate (self-consistency x3).
- Evidence (800-task held-out bench, seed 777): accuracy 0.8050 (DS 0.8762),
  severity-weighted recall 0.9128 (DS 0.8719), HIGH recall 1.0000, parse
  1.0000, ECE 0.1175, 0 escalations. Base ablation: R_w 0.6002.
- Reading: the LoRA trades low-weight-class accuracy for the money axis.
  Remaining hole = LOW classes (DUPLICATE 0/31, FIELD_CORRUPTION 13/37);
  fixable by B2 data composition + E3 escalation policy.
