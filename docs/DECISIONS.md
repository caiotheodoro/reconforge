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
- Evidence: 100% oracle agreement on the committed pilot, 300 tasks
  (`docs/validation/pilot-7-n300.json`). Earlier text said 400, which was the
  `make study` task count rather than the committed artifact's; the artifact
  name now carries the count and `make study` regenerates exactly this file.
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
  run's adapter (training ran to iter 740; last persisted save iter 700 —
  see docs/TRAINING.md) under evaluation.

## 2026-08-08 — M12 — Full head-to-head: fine-tuned 1.7B BEATS DeepSeek on R_w
- Decision: run1 adapter (iter-700, last persisted save of the run that
  trained to iter 740 — see docs/TRAINING.md) is the benchmark candidate
  (self-consistency x3).
- Evidence (800-task held-out bench, seed 777): accuracy 0.8050 (DS 0.8762),
  severity-weighted recall 0.9128 (DS 0.8719), HIGH recall 1.0000, parse
  1.0000, ECE 0.1175, 0 escalations. Base ablation: R_w 0.6002.
- Reading: the LoRA trades low-weight-class accuracy for the money axis.
  Remaining hole = LOW classes (DUPLICATE 0/31, FIELD_CORRUPTION 13/37);
  fixable by B2 data composition + E3 escalation policy.

## 2026-08-08 — C1 — Judge calibration study (golden-100, seed 333)
- Decision: golden set = 100 fresh tasks (seed 333, unused elsewhere), labels =
  verifier-as-oracle, judges = DeepSeek-v4-flash (temp 0.1) and the fine-tuned
  worker (greedy). Cohen's kappa is the recalibration target.
- Evidence: DeepSeek kappa 0.7407 / agreement 0.82; local fine-tuned judge
  0.7361 / 0.81. Both below the 0.85 Airbnb EDD bar -> judge refinement is an
  open workstream (judge-specific fine-tune or rubric changes); weekly
  recalibration schedule has a live target.

## 2026-08-08 — I2 — Temporal Cloud live integration (first end-to-end)
- Decision: DecisionWorkflow (durable HITL) ran against reconforge.drilv with
  real Postgres + Kafka: workflow start -> ledger /reviews 201 -> review
  signal -> record_final_verdict -> ledger /entries 201 (source=human) ->
  Kafka publish. Verified audit entry via GET /entries/{task_id}.
- Fixes en route: Verdict contract gained review_state; Pair contract made
  seed/difficulty/expected optional (production pairs carry no oracle label);
  compose kafka switched to apache/kafka:3.9.0 (bitnami pulls fail from this
  registry) with KRaft server.properties at system/kafka/.

## 2026-08-08 — I3 — Kafka broker switch
- Decision: apache/kafka:3.9.0 (KRaft, node.id=0, combined roles) replacing
  bitnami/kafka (unavailable: docker.io 404 on bitnami tags).
- Rationale: same protocol/port (9092), no client changes; config now at
  system/kafka/server.properties.

## 2026-08-08 — B2 (completed) — Training-mix rebalancing is a NEGATIVE result
- Decision: champion = run1 adapter (default mix, iter-700 — last persisted
  save of the run that trained to iter 740, see docs/TRAINING.md — R_w
  0.9128). B2 (rebalanced mix, iter 590) rejected.
- Evidence: B2 vs run1 on identical 800-task benchmark — HIGH 1.0->0.89,
  MEDIUM 0.84->0.40 (PARTIAL_MATCH 26->1, VALUE_DATE 37->8), AMOUNT 73->56,
  DUPLICATE 0->1, FIELD_CORRUPTION 13->16. R_w 0.7230 vs 0.9128.
- Mechanism: cutting the training weight of classes the benchmark tests
  heavily destroyed recall on exactly those classes; upsampled rare classes
  gained ~nothing (DUPLICATE is a signal-representation problem, not a count
  problem — 124 examples were enough; the model learned "all fields agree ->
  MATCH").
- Conclusion: training distribution must MATCH deployment distribution;
  class rebalancing trades real recall for phantom recall. DUPLICATE
  detection is best handled by the rule verifier pre-check in the gate layer,
  not by training more examples.

## 2026-08-08 — C2 — Judge rubric fix closes the 0.85 bar for DeepSeek, breaks the local judge
- Decision: added `JUDGE_SYSTEM_PROMPT` (model/src/reconforge_model/schema.py)
  — additive to, not a replacement of, the worker's `SYSTEM_PROMPT` — with
  explicit matching rules for the four classes C1 only named but never
  defined: VALUE_DATE_MISMATCH (business-day + late-booking threshold),
  PARTIAL_MATCH (F4 near-equal-name definition), FIELD_CORRUPTION, DUPLICATE
  (F1 trimmed-ref equality). Reran the golden-100 study (seed 333, same as
  C1) via the new `model/src/reconforge_model/judge_calib.py` against both
  raters with the new prompt.
- Evidence: DeepSeek judge kappa 0.7407 -> **0.9037** (agreement 0.82 ->
  0.93), clears the 0.85 bar. Local fine-tuned worker-as-judge kappa 0.7361
  -> **0.3672** (agreement 0.81 -> 0.42) — regression, not an improvement.
  Confusion table shows the local judge now hallucinates VALUE_DATE_MISMATCH
  (27/100) and PARTIAL_MATCH (15/100) on true MATCH pairs — it over-fires
  rather than under-fires with the extended prompt.
  Artifacts: docs/validation/judge-calib-rubric-v2.json,
  golden-100-rubric-v2.jsonl, golden-100-local-judge-rubric-v2.jsonl.
- Mechanism: the local judge IS the fine-tuned worker, trained exclusively
  on `SYSTEM_PROMPT`'s exact text (dataset_builder.py bakes it into every
  training record). Extra rubric text is off-distribution for a 1.7B model
  fine-tuned on one fixed prompt; DeepSeek, never prompt-tuned, follows the
  added instructions correctly. The fix that helps a frontier judge actively
  hurts a small fine-tuned one — prompt engineering does not transfer
  across judge architectures here.
- Decision: DeepSeek + `JUDGE_SYSTEM_PROMPT` is the production judge for the
  weekly recalibration schedule (clears 0.85). The local judge keeps
  `SYSTEM_PROMPT` unchanged (kappa stays 0.7361, still below bar) — using it
  as a judge remains an open item, not fixed by this study; a judge-specific
  fine-tune (training the local model ON the rubric-extended prompt, not
  just prompting it) is the correct next step if a local judge is needed.
- Follow-up fix (same commit): `forge/src/reconforge_forge/seams.py
  ::judge_kappa()` auto-selects the newest `golden-*.jsonl` by mtime for the
  weekly workflow. The local-judge artifact's filename also matched that
  glob and, being written after the DeepSeek one, was newest on disk — the
  schedule would have silently recalibrated against the 0.37-kappa run.
  Glob now excludes `*local-judge*` filenames so the schedule always picks a
  DeepSeek-judge artifact. Verified: 55 forge tests still green.
- Alternatives rejected: judge-specific fine-tune first (HANDOFF's other
  candidate) — deferred since the cheap rubric fix already closes the bar
  for the judge that's actually in production use (DeepSeek).

## 2026-08-29 — F8 — FIELD_CORRUPTION / VALUE_DATE_MISMATCH collision: documented, not silently rescored
- Decision: the `malformed_date` corruption variant writes a garbled string into
  `statement.value_date`, which makes the item simultaneously "a field is
  corrupt" and "the value date is wrong". The verifier resolves it by the F1
  priority order (FIELD_CORRUPTION outranks VALUE_DATE_MISMATCH) but the prompt
  never states that order, so `VALUE_DATE_MISMATCH` is a defensible reading of an
  ambiguous item rather than a model error. Both scorings are now published;
  strict remains the headline rule.
- Evidence: `docs/validation/taxonomy-collision.json`. 12 of the 37 benchmark
  FIELD_CORRUPTION items are `malformed_date`. Confusions into
  VALUE_DATE_MISMATCH: champion ×5 12, champion ×3 11, DeepSeek 7, base 10.
  Under collision-tolerant scoring FIELD_CORRUPTION recall roughly doubles
  (champion ×5 0.2703 → 0.5946) but R_w moves only 0.9007 → 0.9098, because the
  class carries weight 0.2. DeepSeek moves 0.8719 → 0.8772, so the margin widens
  slightly (+0.0288 → +0.0326) rather than closing.
- Consequence for B2: the B2 study read FIELD_CORRUPTION recall as an
  improvement target. Part of that class's apparent difficulty is label
  ambiguity, not model weakness, so "upsampling FIELD_CORRUPTION barely helped"
  is partly explained by the ceiling being lower than the strict score implies.
- Not fixed in the generator yet, deliberately: changing task generation changes
  what seed 777 produces, which would break the reproducibility of every
  published export and invalidate the committed seed-999 frozen-test signatures.
  The fix belongs in a versioned generator (v2) alongside the PARTIAL_MATCH
  held-out variants, with a newly frozen test seed — see the Round 1 review.
- Alternatives rejected: silently rescoring under the tolerant rule (hides a
  construct-validity defect behind a better number); stating the priority order
  in the prompt (turns a taxonomy problem into a prompt-engineering one, and
  would invalidate the trained adapter's prompt contract).

## 2026-08-29 — F9 — PARTIAL_MATCH has total train/eval surface overlap (construct-validity defect)
- Decision: record the defect and gate the headline on resolving it. Do not
  reinterpret the existing PARTIAL_MATCH result as evidence of capability until
  the champion has been scored on abbreviation pairs it never trained on.
- Evidence: `docs/validation/partial-match-overlap.json`. The generator builds
  every PARTIAL_MATCH item from a fixed 10-entry variant table
  (`BENEFICIARY_VARIANTS`, `COUNTERPARTY_VARIANTS`). The seed-777 benchmark's 32
  PARTIAL_MATCH tasks use **9 distinct surface pairs, and all 9 also appear in
  the seed-101 training pool** — overlap fraction 1.0, zero unseen pairs.
- Why it matters: per issue #18, PARTIAL_MATCH contributes ~97% of the
  champion's R_w margin over DeepSeek (champion catches 26/32, DeepSeek 5/32).
  With complete surface overlap, "the fine-tune learned to recognise abbreviated
  counterparty names" and "the fine-tune memorised ten strings" predict the same
  benchmark score. The current data cannot separate them, so the margin does not
  yet support the capability claim the write-up makes.
- Note this is a *different* confound from the prompt-definition one in #18. The
  shared prompt never defines PARTIAL_MATCH, which independently disadvantages
  DeepSeek. Both must be closed before the class's contribution is interpretable:
  the rubric prompt fixes the definition confound, held-out variant pairs fix the
  memorization confound.
- Resolution requires generating PARTIAL_MATCH items from pairs disjoint from
  training, which changes task generation — see the versioned-generator decision.
- Alternatives rejected: dropping PARTIAL_MATCH from the headline metric (it is a
  legitimate operational class, and removing the class that decides the result
  after seeing the result is exactly the move pre-registration exists to prevent).

## 2026-08-29 — E3 — Escalation policy is unanswerable on a pool where HIGH recall is already 1.0
- Decision: close the E3 escalation-threshold study as **not answerable on the
  seed-777 benchmark**, rather than reporting a threshold. Reopen it only on a
  pool or model where HIGH-severity exceptions are actually missed.
- Evidence: `docs/validation/escalation-calibration.json`.
  1. The existing calibration path is vacuous. `find_best_threshold` keys off
     `predicted.confidence`, which the champion emits as exactly 1.0 on all 800
     tasks — no threshold in (0, 1] changes a single verdict. It had only ever
     been run against the 88-task smoke fixture, where the stub reported 0.0
     everywhere: degenerate from the other end.
  2. Self-consistency agreement *is* a real error signal: mean 0.897 on correct
     predictions vs 0.810 on wrong ones (gap 0.087, n=644/156). Weak, but real,
     and only meaningful at all after the decision-level vote fix.
  3. It still buys nothing here, and the reason is structural. The operational
     cost is `1.0·escalations + 5.0·missed_HIGH`. The champion has 0 escalations
     and 0 missed HIGH, so cost is already 0.000; every escalation adds at least
     1.0 and prevents nothing, because there is no missed HIGH left to prevent.
     The optimal threshold is 0.0 by construction, not by tuning.
- Reading: "the model never says unsure" is described elsewhere as a cost of pure
  SFT. On this pool, under this cost model, it is optimal behaviour. The
  escalation question only becomes live where HIGH recall is below 1.0 — a harder
  pool, the base model, or the champion once matched conditions and held-out
  variants reduce its HIGH recall. Any future escalation policy must be justified
  against a run that actually misses HIGH exceptions.
- Alternatives rejected: tuning a threshold anyway and reporting the number
  (it would be a tuned-on-nothing artifact of a degenerate optimum); changing the
  cost model until escalation looks worthwhile (that is fitting the metric to the
  desired conclusion).

## 2026-08-29 — R4-scope — What a GRPO round can and cannot reach on this distribution
- Decision: proceed with the RL round, but scope it to the false-positive problem
  rather than to R_w, and drop DUPLICATE from the RL objective entirely.
- Evidence: `docs/validation/solve-rate.json`, measured from the champion's
  stored ×5 draws — no new inference. Solve rate per task over 5 samples,
  "solved" by the same `is_correct` rule the benchmark scores with.
- **The trainable band is real**: 306/800 tasks (38.2%) sit in the 10–80% band.
  49.8% are always-solved and 12.0% never-solved; both contribute variance rather
  than advantage to GRPO. A band this size justifies the compute.
- **71% of that signal is MATCH tasks** (216 of 306 in-band items are clean
  pairs). So an RL round on the severity-weighted-cost reward would spend most of
  its gradient learning not to over-flag clean pairs. That is precisely the
  champion's measured weakness — 67 false positives, flag precision 0.824 against
  DeepSeek's 1.000 — and it is a *guard* metric under PRE-REGISTRATION §5, not
  the primary endpoint. The honest framing of Round 4 is therefore "RL to fix the
  false-positive gap", not "RL to raise R_w".
- **Three classes are unreachable by RL on this distribution**, for two different
  reasons:
  - `DUPLICATE` — 31/31 always fail, 0 in band. Every rollout is wrong, so there
    is no advantage to compute and GRPO cannot move it. This is a third
    independent confirmation of the B2 finding (data-count doesn't fix it) and
    the F9 reading (it is representational): the model never learned reference
    equality as a signal distinct from field agreement. The fix stays
    architectural — the verifier pre-check in the gate.
  - `FX_CONVERSION_ERROR` (32/32) and `MISSING_MESSAGE` (45/45) — always solved,
    saturated, nothing left to learn.
- Consequence for the reward: severity-weighted cost remains the right objective
  (it is the only one that prices false escalations), but the expected gain is on
  flag precision/F1 and normalized cost, with R_w roughly flat. Round 4 should be
  judged on that basis, and a flat R_w should not be read as failure.
- Alternatives rejected: filtering the RL set to exception tasks only (throws away
  71% of the available signal and the specific weakness worth fixing); including
  DUPLICATE to "give it a chance" (zero advantage signal, pure wasted compute).

## 2026-08-29 — R4-stack — GRPO must be implemented on MLX, not imported
- Finding: `mlx_lm` 0.31.3 has **no RL surface at all**. `mlx_lm.tuner.trainer`
  exposes `default_loss`, `train`, `evaluate` and nothing else; the source
  mentions none of `grpo`, `ppo`, `reward`, `advantage`, `policy_gradient`, or
  `kl`. The published stack is supervised-only.
- Decision: implement a GRPO loop against MLX rather than moving the RL round to
  a CUDA box with TRL/verl.
- Rationale, and it is a methodological one rather than a cost one: the champion
  is a LoRA over `mlx-community/Qwen3-1.7B-4bit`. Training the RL variant on
  CUDA would mean a different base quantization and a different runtime, so any
  RL-vs-SFT comparison would confound the algorithm with the stack — exactly the
  class of unmatched comparison this whole effort exists to remove
  (PRE-REGISTRATION §4). Keeping RL on the same base and the same sampler is
  what makes "GRPO beat SFT" a statement about GRPO.
- What has to be written: rollout sampling from the current policy, group-relative
  advantage `A_i = (r_i − mean r) / std r`, token log-probs under the policy,
  a policy-gradient loss with a KL penalty to the SFT reference, and a LoRA
  update. `mlx_lm.tuner.trainer.train` cannot be reused as-is because its batch
  iterator has no place to generate rollouts; the loop is custom.
- Already in place from the environment gate: the reward (`rl_reward.rl_cost`,
  three error modes, no free optimum, CI-gated) and the trainable task set
  (306 in-band tasks from `solve-rate.json`).
- Cost estimate on the M5: 8 rollouts × ~0.85 s per task, 8 tasks per step ≈ 56 s
  per step, so ~100 steps is roughly 1.5 h — the same order as the SFT runs.
- Alternatives rejected: TRL/verl on a rented GPU (breaks base-model
  comparability, and the AWS budget is better spent on seed replication than on
  re-establishing a baseline that already exists); skipping GRPO for
  rejection-sampled SFT alone (that is Round 3.3 and answers a different
  question — it cannot show whether on-policy optimisation beats imitation).

## 2026-08-29 — R4-scale — GRPO is implemented and gated, but this hardware cannot run it at a defensible scale
- Decision: do **not** run a token-scale GRPO round on the M5 and report it.
  Escalate the scale question instead.
- Measured, not estimated (`model/scripts/train_grpo.py` smoke runs):
  - one step = 8 rollouts + one gradient step = **182 s**
  - generation is **3%** of that (0.7 s per rollout); the gradient pass is **97%**
  - amortised **22.8 s per rollout**
- The gradient pass is dominated by the prompt, not the completion. `SYSTEM_PROMPT`
  plus a rendered task is **673 tokens** against ~35 completion tokens, and the
  forward/backward has to cover the whole sequence even though the prompt
  positions are masked out of the loss. Shortening it would change the prompt
  contract the champion was trained under, so it is not available.
- What that buys on this machine: 320 rollouts ≈ 2 h, 1 000 ≈ 6.3 h,
  2 000 ≈ 12.6 h. A 2-hour run is ~40 steps over 8 rollouts each.
- **Why not just run the 2-hour version.** It would be underpowered by
  construction, and this project has just retracted a headline for exactly that
  reason: a single draw reported as a result. Round 3 measured run-to-run SD at
  0.0823 on this recipe; an RL delta smaller than that is unreadable, and 40
  steps is very unlikely to move the policy further than the noise floor. Running
  it and reporting "GRPO improved/did not improve X" would repeat the error the
  retraction was about.
- One genuine optimisation was found and kept: the KL reference term is constant
  with respect to the policy, so it is precomputed once per batch instead of
  running a second full forward inside the differentiated graph
  (`grpo.grpo_loss_cached_ref`). 255 s → 182 s per step, with a test asserting
  the two formulations give identical loss, policy-gradient and KL at three
  values of beta. It is a 29% saving, not an order of magnitude.
- Status: the machinery is complete and verified — reward with no free optimum,
  8-check environment gate, 306-task in-band set, GRPO core with 15 unit tests
  covering advantages, masking, length normalisation and the KL term, and a
  driver that refuses to start unless the gate passes. What is missing is
  throughput, which is a hardware question rather than a correctness one.
- Options, for an explicit decision rather than a default:
  1. **Rent a GPU** (~$30 of the $60 budget). Fastest path to a defensible run,
     but the RL variant would train on a different base quantization and runtime
     than the SFT champion, so any RL-vs-SFT comparison confounds algorithm with
     stack — the same class of unmatched comparison this work exists to remove.
     Mitigable by also re-running the SFT baseline on the same rented stack,
     which roughly doubles the cost.
  2. **Accept ~6 h on the M5** for ~1 000 rollouts. Same base, same runtime,
     genuinely comparable; still modest for RL but no longer a token run.
  3. **Report GRPO as built-and-gated, not run.** Honest, cheap, and the
     environment gate already produced a real finding (the reward hack) without
     any training.

## 2026-08-29 — R4-filter — The RL task filter selected on the wrong quantity, and the reward covers only 2 of 10 classes
- Finding 1 — **the filter was wrong**. The RL set was built from the `is_correct`
  solve-rate band (10–80%). GRPO needs within-group variance in the **reward**,
  and the reward is coarser than the correctness rule: `is_correct` requires the
  exact `exception_type`, while `rl_cost` prices only escalations, missed HIGHs
  and false flags. A task whose rollouts alternate between two *wrong* exception
  types therefore varies under `is_correct` and is **constant** under the reward.
  It looks trainable and yields no advantage.
- Measured consequence: the first GRPO run dropped **83%** of sampled groups as
  degenerate — 1 gradient update in 3 steps, and that one on half a batch. The
  run was stopped rather than left to burn ~6 h producing almost no gradient.
- Rebuilt on reward variance directly (`model/scripts/rl_reward_variance.py`,
  measured from the champion's stored ×5 draws, no inference): **236/800 tasks
  (29.5%) carry reward signal**. Of the old 306-task band, **70 had none**; and
  zero tasks had reward signal without being in the band, so the old filter was a
  strict superset — it was not missing signal, it was admitting noise.
- Finding 2 — **and this is the larger one**. The surviving set is
  **216 MATCH + 20 AMOUNT_MISMATCH, 91.5% clean pairs**. Every other exception
  class has *zero* reward variance, by construction: for a MEDIUM/LOW exception,
  naming the wrong type is not priced — it is not an escalation, not a missed
  HIGH, and not a false flag, so right-type and wrong-type score identically.
  **The reward cannot see type errors on 8 of the 10 classes.**
- Consequence for what GRPO can possibly achieve here: it can reduce false flags
  on clean pairs and improve AMOUNT_MISMATCH recall. It cannot improve
  exception-type accuracy for DUPLICATE, FIELD_CORRUPTION, VALUE_DATE_MISMATCH,
  PARTIAL_MATCH, MISSING_MESSAGE, BENEFICIARY or COUNTERPARTY. That is a property
  of the reward, not of the algorithm or the model.
- Deliberately **not** changing the reward now. Adding a wrong-type cost after
  observing that the current reward limits learning would be a post-hoc
  modification made to get a better result, which is the move this project has
  spent four rounds removing. The reward was specified and gated before the run;
  it stays, and its coverage limits are reported as a finding.
- The environment health gate did not catch this. It verified the reward
  separates *policies* and has no free optimum; it never checked whether the
  reward varies across *rollouts of a single prompt*, which is the property GRPO
  actually consumes. A gate check for that has been added.

## 2026-08-29 — R4-result — GRPO collapses exploration after one update; reported as a negative result, not tuned away
- Result: the GRPO round **failed to train**, and the reason is diagnosed rather
  than guessed. One gradient update in 60 steps; steps 2–60 all produced zero
  within-group reward variance.
- Cause: **entropy collapse after a single update.** Measured directly by probing
  rollout diversity before and after one step (same tasks, same sampler,
  temp 0.6, G=8):

  | task | distinct rollouts before | after one update |
  |---|---|---|
  | recon-000003 | 2 | **1** |
  | recon-000005 | 1 | 1 |
  | recon-000009 | 2 | **1** |
  | recon-000010 | 1 | **1** (and its reward moved −1.0 → 0.0) |

  The policy becomes deterministic at temp 0.6, so every later group is
  degenerate and GRPO has nothing to compute an advantage from.
- Why it happens here: the starting policy is already extremely low-entropy — a
  heavily-SFT'd model that emits 9 distinct reason strings across 800 predictions
  with confidence pinned at 1.0. AdamW's per-parameter step is ~lr regardless of
  gradient magnitude, so one step at lr 1e-5 with KL β=0.02 is enough to tip a
  near-deterministic distribution over the edge.
- **Not tuned away, deliberately.** The standard fixes are well known — entropy
  bonus, much lower or non-adaptive learning rate, stronger KL, ratio clipping.
  Applying them now, after seeing the failure, until a number improves is exactly
  the outcome-tuning this project spent five rounds removing, and it would be
  indistinguishable from fitting hyperparameters to the eval. A proper
  hyperparameter study is the honest next step and it is not in this budget.
- What the round does establish, all of it measured:
  1. The reward had a **free optimum** (flag-everything scored 0.000, tying the
     oracle). Caught by the environment gate before any GPU spend.
  2. The task filter selected on the **wrong quantity** — correctness variance,
     not reward variance — wasting 83% of groups until corrected.
  3. The reward is **blind to type errors on 8 of the 10 classes**, so GRPO here
     could only ever have touched false flags and AMOUNT_MISMATCH.
  4. A near-deterministic SFT policy **collapses under GRPO** at otherwise
     reasonable settings.
  Each of those is a finding about running RL on this kind of task, and three of
  the four were invisible until something was actually executed.
- Status: GRPO implementation is complete and unit-tested (15 tests over
  advantages, masking, length normalisation, KL, and the cached-reference
  equivalence). The blocker is not correctness, it is that this policy/reward
  pairing needs exploration control that has not been designed or budgeted.

## 2026-08-30 — R5 — Matched comparison: the margin inverts, and three corrections to how it was first reported
- Result: under a matched prompt and matched decode budget the R_w margin goes
  from **+0.0269** [+0.0064, +0.0493] to **−0.0288** [−0.0432, −0.0160]. Both
  intervals exclude zero. DeepSeek leads accuracy (0.9487 vs 0.4338) and flag F1
  (0.9604 vs 0.6649), and is level on cost and HIGH recall.
  `docs/validation/matched-comparison.json`
- The champion fails **2 of the 5** pre-registered guards under matched
  conditions (G-a flag precision 0.5083; G-b flag F1 0.6649 and 0.296 behind the
  best). Its R_w *rises* to 0.9401 while accuracy falls to 0.4338 — the rubric is
  off-distribution for a model trained on one fixed prompt, it degenerates toward
  flagging everything, and R_w rewards that because it never scores clean pairs.
- **Three corrections, all from independent adversarial review, all recorded
  because the first version of this result was wrong in ways that flattered it:**
  1. The published margin was quoted as +0.0288, computed with whole-dict voting
     — which §4.4 forbids. Under the rule every other condition uses it is
     **+0.0269**, and the eye-catching +0.0288/−0.0288 symmetry was an artefact
     of comparing two different estimators. E′ (re-aggregated) is now the quoted
     figure; the vote rule changes 8 of 800 decisions.
  2. "Fails 3 of 5 guards" was a miscount: the table split G-b across two rows
     and silently omitted G-d, which passes. It is **2 of 5**.
  3. The section was headlined as the pre-registered confirmatory test. It is
     **exploratory**: §4.5 requires held-out abbreviation pairs and §3 names the
     frozen seed-999 pool, and this ran on seed-777 (v1) whose PARTIAL_MATCH
     overlap fraction is 1.0. The violation is conservative — it favours the
     champion — so a compliant pool would push the result further negative.
- Also corrected: an invented mechanism (greedy decoding overrunning the token
  budget) had been asserted in a code comment by the very commit that retracted
  it in the docs. Deleted. The replacement is not a better mechanism but an
  admission that the discriminating evidence was deleted with the checkpoint, so
  the cause of that condition's failure is **unknown**.
- Provenance gap closed: `compare_deepseek` now records prompt, sample count,
  temperature and max_tokens in the artifact. The matched DeepSeek run could not
  previously prove from its own artifact which prompt produced it.
- What is still missing: condition B (rubric, ×1) and a DeepSeek base-prompt ×5
  run. Without them the +0.0970 cannot be split into definition and budget
  effects, so "the margin does not survive a matched prompt" is supported while
  the budget's separate contribution is not established.

## 2026-11-23 — P1 — The retraction is released as a paper, and the repository now says what the working copy said
- Decision: publish the retraction as `paper/reconforge.tex` (PDF built with tectonic,
  numbers/tables/figures generated from `docs/validation/*.json` by `paper/build_assets.py`),
  commit the recovered retraction work, and prepare a Zenodo draft. This entry is dated by the
  day the commit is made; it dates nothing earlier.
- What was found. The public repository (last commit 2026-09-05) carried the headline with no
  retraction; the retraction (README box, `PRE-REGISTRATION.md`, `THREATS-TO-VALIDITY.md`,
  rewritten `BENCHMARK.md`/`DECISIONS.md`/`HANDOFF.md`/`TRAINING.md`/blog, 21 artifacts, the
  CI workflow, scripts and tests) existed only in an uncommitted iCloud working copy. The Hub
  model card source (`model/README.md`) still led with the claim.
- What was committed from that copy: the docs above, `PRE-REGISTRATION.md` (verbatim; its
  SHA-256 is pinned in `paper/tests/test_metadata.py`), `taxonomy.json`, `ruff.toml`,
  `mypy.ini`, and every `docs/validation/*.json` artifact the paper cites. `docs/validation/pilot-7.json`
  is superseded by `pilot-7-n300.json` in that copy and is left as committed.
- What was not committed: the scripts that produced the round-2 artifacts
  (`model/scripts/{train_seed_study.sh,score_seed_study.py,multiseed_matrix.py,matched_comparison.py,...}`),
  the `model/src` and `forge/src` changes they import, their tests, the copy's CI workflow (replaced by `.github/workflows/ci.yml`, which runs the forge tests
  and the paper checks only), and the evidence logs `runconfig.json` names under `model/data/*.log`.
  They were not recovered intact, and committing scripts that do not run against the committed
  source would misstate the record. They remain in the owner's iCloud copy. The artifacts and the
  committed per-task exports are enough to re-score every published run; `paper/` does so and
  also derives one new contrast (`docs/validation/best-prompt-comparison.json`), after first
  reproducing two committed ones.
- Corrections made here, each found on a cold re-read: the README box said the matched rerun
  "fails 3 of the 5 guards" (it is 2 of 5); "~97% of the margin from PARTIAL_MATCH" is the
  three-sample margin, at the five-sample headline it is 112% (recomputed from the per-task
  exports); BENCHMARK listed COUNTERPARTY_MISMATCH as 31/37 caught where the HIGH rule gives 37/37;
  the exception rate was "~45%" and is 48%; the blog and the Hub card source said the matched
  result as if it were the registered test (it is exploratory). Edits are to non-frozen text only;
  `PRE-REGISTRATION.md` and `CONTRACTS.md` are unchanged (the iCloud copy's `CONTRACTS.md` differs
  from the committed one by 47 bytes; the committed one stands).
- A weakness the paper states and the earlier docs did not: the 2.86x figure includes the shipped
  run, which was chosen for scoring well. The three unselected runs give SD 0.0479, 1.66x, with
  a chi-square interval that includes the margin. The comparison is underpowered, not reversed.
- Registration provenance. The tag `prereg-v1` (annotated, unsigned, 2026-08-29 21:50 UTC, tagger
  email a work address) and `prereg-v1-amend1` exist only in the iCloud copy's git; they were not
  pushed. The only external clock in this repository is GitHub's commit date: the seed-999
  signatures were committed 2026-08-27 (`56185d0`), and this release is 2026-11-23. The paper
  says the registration date is the author's word.
- The deposit. A Zenodo draft (preprint, CC BY 4.0, ORCID 0009-0005-7343-981X) was prepared and
  left unpublished; its record id is not recorded here because it is not final. When it is
  published its real creation date goes in a later entry, as D110 does in lacuna. The deposit is
  not the registration clock: it dates the paper, made after every run here, and nothing about
  when the registration was fixed.
- Not done, and said so in the paper: no score on the frozen seed-999 pool (that needs the frontier
  model and a set of trained runs); no further training seeds; no DeepSeek run on the seed-13
  pool; the Hub model card itself was not updated (only its source in `model/README.md`).
- Clean room: `docs/HANDOFF.md` named an employer's product in a parenthetical ("Adopt AI harness
  pattern"); that phrase is now generic. Nothing else in the tree names the employer or its product.
- Early commits in the public history (`be301ea`, `0cf03a7`, `56185d0`, `38984b2`, `dd642b7`,
  `5613be1`) carry a work email as author. History was not rewritten.
- Reversal: this entry changes no frozen text. If a number in the paper is found wrong, a later
  entry corrects it and a corrected paper goes up as a new version. The retraction itself is
  reversed only by a test registered before it runs: at least three training seeds scored with the
  frontier model on the frozen seed-999 pool, the claim holding at the mean minus one standard
  deviation. If the Zenodo draft is deleted or never published, this entry stands as the record
  of what the repository contained on 2026-11-23.

## 2026-11-23 — P2 — The paper is deposited on Zenodo; the deposit is not the registration clock
- Deposit. `paper/reconforge.pdf` (12 pages, built from commit `5598896`) is Zenodo record 24455455,
  DOI 10.5281/zenodo.24455455; the DOI for all versions is 10.5281/zenodo.24455454. The record was
  created on 2026-11-23 at 05:29 UTC (Zenodo's own timestamp) and published the same day by the
  owner. The publication date on the record is 2026-11-23, the day of this release, which is also the
  paper's first public appearance. The file's md5 is `7b21298cd0d57329cac990884e1dfdc6`.
- On the record: preprint, CC BY 4.0 set in Zenodo's metadata only (the PDF carries no licence line;
  the repository stays Apache-2.0), author with ORCID and no affiliation, the abstract plus "Not peer
  reviewed", 26 reference strings from `paper/refs.bib`, the repository as a supplement and the 26 cited
  arXiv papers as cited works (`.zenodo.json` holds the same metadata). `CITATION.cff` and the README
  name the DOI.
- The file cannot change; metadata can. A later entry corrects any statement on the record found
  wrong, and a corrected paper goes up as a new version under the same concept DOI.
- Not the registration. The deposit dates the paper, made after every run here. It dates nothing about
  when `PRE-REGISTRATION.md` was fixed. The only external clocks are GitHub's commit dates: the
  seed-999 signatures on 2026-08-27 (`56185d0`) and this release.
- Open items, recorded as they stand and not repaired by editing history:
  - Generating code. The scripts and `model/src`/`forge/src` changes behind the round-2 artifacts
    (`train_seed_study.sh`, `score_seed_study.py`, `multiseed_matrix.py`, `matched_comparison.py` and
    others), their tests, and the evidence logs `runconfig.json` names are not committed; they remain in
    the owner's iCloud copy. Table 2 of the paper (the three new training-seed runs) is summary scores
    only; the per-task exports of those runs were not kept.
  - Registration tags. `prereg-v1` and `prereg-v1-amend1` exist only in the iCloud copy's git, are
    unsigned, name a work email as tagger, and were not pushed or signed here. Whether to publish them
    is the owner's decision; until then the registration date is the author's word.
  - Work email in history. Commits `be301ea`, `0cf03a7`, `56185d0`, `38984b2`, `dd642b7` and `5613be1`
    carry a work address as author. History was not rewritten.
  - Hugging Face. The live model card for `caiotheodoro/reconforge-recon-lora` may still carry the
    retracted headline; only its source (`model/README.md`) was corrected here.
- Reversal: this entry changes no frozen text. If the record is found wrong in a statement, metadata
  is corrected and this log gets a new entry. If the paper is withdrawn, the record is marked so on
  Zenodo and a later entry here says why; the retraction of the claim itself stands either way and is
  reversed only by the test named in P1.

## 2026-11-23 — P3 — Pre-analysis plan for paper v2: per-class margin decomposition, non-PARTIAL_MATCH sensitivity, and v2 framing
- Context. After v1 (`5598896`, Zenodo record 24455455), an audit of all six papers noted that
  `paper/reconforge.tex` leads with confessional retraction framing ("I published that... The claim
  is retracted", title beginning with "a retraction"), carries repo housekeeping and a self-audit
  mistake list in the main body (§8 "Errors found in my own analysis"), lacks a Conclusion section,
  recommends decomposing the margin by class (§6 item 3) without printing the nine-class table, and
  does not report the paired margin excluding the memorised `PARTIAL_MATCH` class.
- Pre-specified zero-spend post-hoc analyses (written before running `paper/derive_class_analysis.py`
  on the committed `docs/validation/bench-*.json` per-task exports):
  1. **Complete nine-class decomposition.** For each of the nine exception classes in `taxonomy.json`,
     compute $n$, severity, weight, recall under conditions E (published fine-tune, x5), E' (vote-corrected
     fine-tune, x5), A (DeepSeek base, x1), and C (DeepSeek defined-class prompt, x5), plus exact signed
     contribution to `E - A`, `E' - A`, and `E' - C`.
  2. **Non-`PARTIAL_MATCH` paired margin sensitivity.** Excluding the 32 `PARTIAL_MATCH` tasks (whose 9
     abbreviation pairs all appear in training), compute the paired difference in $R_w$ over the remaining
     8 exception classes (349 exception tasks) for `E - A`, `E' - A`, `D - C`, and `E' - C` with 10,000
     paired bootstrap resamples (seed 11, same estimator as `paper/derive_best_prompt.py`).
  3. **Paper v2 revamp, date, and affiliation.** Reframe `paper/reconforge.tex` to lead with the five
     diagnostic findings (retaining the retraction and the registered "underpowered rather than reversed"
     verdict), add contribution bullets and a Conclusion section, move the repo timeline and analysis
     corrections to Appendix A, set the publication date to `2026-08-07` (first repository commit
     `de7405f`, following the owner's date rule across all repositories), set affiliation to Avenza Labs
     (`avenza.cloud`), and draft `docs/DESIGN-V2.md` for the confirmatory `seed-999` study.
- What stays untouched: `PRE-REGISTRATION.md` (SHA-256 unchanged), every previously committed artifact
  under `docs/validation/`, and the retraction verdict.
- Reversal: if a calculation defect is found in `paper/derive_class_analysis.py`, its output
  `docs/validation/class-decomposition-and-clustering.json` is regenerated under a later entry.

## 2026-11-23 — P4 — Paper v2 revamp, per-class decomposition results, date (2026-08-07), Avenza Labs affiliation, and DESIGN-V2
- Post-hoc results (`paper/derive_class_analysis.py` -> `docs/validation/class-decomposition-and-clustering.json`,
  run after P3 `886d959`):
  - Across all 4 HIGH-severity classes, both models sit at or near ceiling (DeepSeek A misses 1 of 37
    `COUNTERPARTY_MISMATCH`; DeepSeek C reaches 100% on all 4 HIGH classes).
  - Excluding `PARTIAL_MATCH` (leaving 349 exception tasks across 8 classes), the published `+0.0288`
    margin vanishes (`-0.0036`, 95% paired bootstrap CI `[-0.0178, +0.0105]`, `0.9145` vs `0.9181`;
    identical under vote correction `E'-A`). DeepSeek's exploratory lead persists without
    `PARTIAL_MATCH`: `D-C` = `-0.0186 [-0.0300, -0.0084]`, `E'-C` = `-0.0524 [-0.0742, -0.0326]`.
- Paper v2 (`paper/reconforge.tex`, `paper/reconforge.pdf`):
  - Retitled to lead with the empirical findings (*When a Small Fine-Tune's Margin Sits Inside Its
    Training-Seed Spread: Variance Decomposition, Class Memorization, and Prompt Confounds in
    Financial Reconciliation*); abstract leads with the five diagnostic findings while retaining the
    retraction and the registered "underpowered rather than reversed" verdict.
  - Added contribution bullets (§1), nine-class decomposition Table 3 (§4.2), a dedicated Conclusion
    (§7), and moved repo timeline and the six internal-review corrections into Appendix A.
  - Set author affiliation to Avenza Labs (`avenza.cloud`) across `paper/reconforge.tex`,
    `CITATION.cff`, and `.zenodo.json`.
  - Set publication date to `2026-08-07` (first repository commit `de7405f`) in `CITATION.cff` and
    `.zenodo.json` (`version: "paper-v2.0"`, `notes` recording 2026-08-07 work start, 2026-11-23 v1
    deposit, and 2026-11-23 v2 revision).
  - Drafted `docs/DESIGN-V2.md` for the confirmatory `seed-999` multi-seed study.
- Reversal: `paper-v1.0` stays at tag `5598896` and Zenodo record 24455455; any further correction
  goes up as a new version under concept DOI `10.5281/zenodo.24455454`.



## 2026-11-23 — P5 — Paper v2.0 deposited on Zenodo (record 24483799, DOI 10.5281/zenodo.24483799)
- Deposit. New version of record 24455455 (concept DOI `10.5281/zenodo.24455454`), created 2026-11-23 21:37 UTC
  (Zenodo's timestamp) and published the same day. Record `24483799`, DOI `10.5281/zenodo.24483799`,
  version label `paper-v2.0`, publication date on the record `2026-08-07` (set from `.zenodo.json` per the
  owner's date rule, see P4).
- File. `paper/reconforge.pdf` at commit `22ba7af`, md5 `586ac7f1d9419f31534f8228fa816cc6`. The Zenodo file
  checksum matches. Files cannot change after publication; the metadata can.
- Metadata on the record: creators Theodoro, Caio and Basso Sberse, João Vitor (both Avenza Labs, ORCIDs in
  `.zenodo.json`), keywords and related works as in `.zenodo.json`, CC BY 4.0, English. The additional
  description (Note with the work-start and v1 deposit dates) did not persist through the Zenodo form and is
  not on the record; the same text is in `.zenodo.json` `notes`.
- The deposit is not the registration clock. Dates in the paper and the repo timeline rest on the commit
  history and the pre-registration, not on the Zenodo timestamp (see P2).
- Reversal. Corrections go up as a new version under the concept DOI `10.5281/zenodo.24455454`. Record
  `24455455` (`paper-v1.0`, tag `5598896`) and record `24483799` (`paper-v2.0`, tag on `22ba7af`) stay as
  deposited. README and `CITATION.cff` point to `24483799` as the current version.
