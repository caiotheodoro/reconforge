# ReconForge System — Microservice Skeleton

Event-driven pipeline (Kafka) + durable workflows (Temporal Cloud) + cadence jobs
(schedules + drift-triggered retrain) + HITL review flow for ReconForge.

This package is the production-shape of the system. The model, knowledge and
forge internals are built in parallel; every seam below is designed against the
stable schemas in `CONTRACTS.md` (`Pair`, `Verdict`, `LedgerEntry`,
`Escalation`, `CadenceEvent`).

## Layout decision

One uv project + one venv at `system/` (not per-service). Rationale: all six
services import the same `contracts.py` / `kafka_util.py` / `config.py`; they
are thin HTTP seams co-deployed by the same compose host, and a single
`uv sync` keeps the integrator's job trivial.

```
system/
  pyproject.toml
  src/reconforge_system/
    contracts.py        # pydantic models EXACTLY per CONTRACTS.md
    config.py           # pydantic-settings (env-overridable, reads repo root .env)
    kafka_util.py       # topic constants + producer/consumer + drop-to-ledger fallback
    decision_core.py    # pure threshold classification
    drift.py            # pure PSI drift detection
    model_client.py     # OpenAI client to the local MLX model service
    temporal_util.py    # Temporal Cloud client (TLS + API key), workflow start/signal
    workflows.py        # Temporal workflows + activities (deterministic core)
    schedule_registry.py# cadence schedules + idempotent registration
    services/
      ingest.py   :9101 POST /pairs
      decision.py :9102 GET /health + Kafka consumer -> model -> route
      ledger.py   :9103 POST /entries, GET /entries/{task_id}, stats, reviews
      gate.py     :9104 POST /ground (knowledge gate seam)
      hitl.py     :9105 GET /queue, POST /review/{task_id}
      cadence.py  worker / schedules CLI
      migrations/001_init.sql
  tests/               # pytest, -m "not integration" by default
  scripts/check_temporal.py   # read-only Temporal Cloud connectivity check
```

## Architecture

```
                     +-----------+    recon.raw-pairs    +-------------+
  pair JSON ------>  | ingest    |---------------------->|  decision   |
                     +-----------+                       +-------------+
                                                              |  model verdict
                                                +-------------+-------------+
                                     escalate/ |             |              | record verdict
                                    low-conf   v             v              v
                                   +-----------+      recon.verdicts    recon.exceptions
                                   |  kafka    |      (kafka)           (kafka)
                                   +-----------+            |                 |
                                                             v                 v
                                       +---------------+   ledger (Postgres)  |
   hitl GET /queue <--- recon_reviews |  ledger :9103  |<---------------------+
   hitl POST /review -> PATCH + entry |   recon_entries| (audit trail: model/human/system)
                                       +---------------+  source="human"      |
                                        ^      | stats                        |
                                        |      v                              |
   DecisionWorkflow (Temporal) --------|      v                              |
     open_review activity -> POST /reviews                                    |
     wait review-resolution signal (24h)                                      |
     timeout -> PATCH timed-out, final verdict source=system                  |
                                                      cadence events:          |
   ContaminationProbe  (nightly 03:00) -----------------------+               |
   JudgeRecalibration (weekly Mon 04:00) ---------------------+-> recon.cadence-events
   Benchmark          (per-release, on-demand trigger) -------+   (kafka + ledger fallback)
   DriftRetrain       (hourly: PSI on exception-type ---------+
                       distribution vs baseline -> retrain-triggered)
```

## Services and ports

| Service  | Port | Entrypoint            | Role |
|---|---|---|---|
| ingest   | 9101 | `reconforge-ingest`   | validate `Pair`, publish `recon.raw-pairs` |
| decision | 9102 | `reconforge-decision` | consume pairs, call model (`MODEL_SERVICE_URL`), route + record ledger |
| ledger   | 9103 | `reconforge-ledger`   | single DB writer: `recon_entries`, `recon_reviews`, stats |
| gate     | 9104 | `reconforge-gate`     | knowledge gate seam (stub until knowledge package lands) |
| hitl     | 9105 | `reconforge-hitl`     | review queue + resolution (signal to Temporal) |
| cadence  | —    | `reconforge-cadence`  | Temporal worker (task queue `reconforge-main`) |

## Kafka topics

`recon.raw-pairs`, `recon.verdicts`, `recon.exceptions`, `recon.escalations`,
`recon.cadence-events` (KRaft auto-create in compose). Producers retry then
drop-to-ledger fallback: if Kafka is down the event is recorded to
`recon_entries` with `source=system` and a `fallback_topic` marker so nothing
is silently lost.

## Decision thresholds (config)

`DECISION_CONFIDENCE_THRESHOLD` (0.6), `DECISION_ESCALATE_SEVERITIES` (HIGH).
Escalate when: model says ESCALATE, severity is HIGH, or confidence < 0.6.
Otherwise record verdict (EXCEPTION verdicts also go to `recon.exceptions`).
All env-overridable via `pydantic-settings`.

## Durable-HITL design

The `DecisionWorkflow` is the durable HITL state machine (mirrors production
agent-harness signal patterns):

1. `decision` escalates -> publishes `recon.escalations` and starts
   `DecisionWorkflow` (`workflow id = decision-<task_id>`) with pair + provisional verdict.
2. The workflow executes the `open_review` activity (persists a pending row in
   `recon_reviews` via the ledger API — this is the durable "requires-review" event).
3. The workflow blocks on the `review-resolution` signal channel for
   `REVIEW_TIMEOUT_HOURS` (default 24h).
4. `hitl POST /review/{task_id}` resolves: APPROVE keeps the provisional verdict,
   REJECT overrides to MATCH, CHANGE uses the supplied `final_verdict`. The final
   verdict is written to the ledger with `source=human` and the workflow is signaled.
5. On timeout the workflow completes deterministically with
   `review_state=timed-out`, marks the review row timed-out and records the
   provisional verdict with `source=system`.

Every verdict is traceable: `task_id` + `event_id` in `recon_entries`, with
`source` in {model, human, system}.

## Cadence schedules (registered as defined)

| Schedule id | Cron (default) | Workflow | Event emitted on fire |
|---|---|---|---|
| `recon-contamination-probe` | `0 3 * * *` | `ContaminationProbeWorkflow` | `contamination-alert` |
| `recon-judge-recalibration` | `0 4 * * 1` | `JudgeRecalibrationWorkflow` | `recalibration-complete` |
| `recon-benchmark` | on-demand (no cron) | `BenchmarkWorkflow` (seeds `[7,13,42]`) | `benchmark-complete` |
| `recon-drift-check` | `0 * * * *` | `DriftRetrainWorkflow` | `retrain-triggered` |

CadenceEvent JSON: `{"type": ..., "at": ISO, "payload": {...}}`. Schedules are
registered idempotently (create or update) via the Temporal ScheduleClient;
`trigger_benchmark()` fires the per-release benchmark on demand. The drift
check computes PSI between the current exception-type distribution (from the
ledger, `source != system`) and `DRIFT_BASELINE_JSON`; a PSI above
`DRIFT_PSI_THRESHOLD` (0.10) emits `retrain-triggered` and calls the external
retrain hook stub.

## How to run

```bash
cd system
uv sync --no-editable          # see macOS note below
uv run --no-sync reconforge-ledger &       # Postgres must be up (compose)
uv run --no-sync reconforge-ingest &
uv run --no-sync reconforge-decision       # DECISION_CONSUME=true to consume
uv run --no-sync reconforge-cadence worker # Temporal worker
uv run --no-sync reconforge-cadence schedules  # register cadence schedules (Temporal Cloud)
uv run --no-sync python scripts/check_temporal.py  # read-only connectivity check
uv run pytest -q -m "not integration"      # unit tests (no infra needed)
```

Integration tests (real Postgres / Kafka): `uv run pytest -q --run-integration`.

### macOS / iCloud note

On macOS hosts where `~/Documents` is iCloud-synced, iCloud may set the
`hidden` flag (UF_HIDDEN) on venv `.pth` files; CPython's `site` skips hidden
`.pth` files, so editable installs silently stop importing. Symptoms:
`ModuleNotFoundError: No module named 'reconforge_system'` from console scripts
while pytest (which uses `pythonpath=["src"]`) still works. Fix: install
non-editable (`uv sync --no-editable`) or clear the flag
(`chflags nohidden .venv/lib/python3.11/site-packages/*.pth`). Use
`uv run --no-sync` to stop `uv run` from reverting the install mode.

### Temporal workflow tests

The temporalio embedded test server needs a `temporal` CLI binary. The SDK's
default download host (`temporal.download`) may be unreachable on some
networks; the tests look for a binary at `TEMPORAL_CLI_EXISTING_PATH`,
`$TMPDIR/opencode/temporal-cli/temporal`, or `~/.temporal-cli/temporal`.
Time-skipping tests additionally need the temporal test-server binary and skip
when unavailable.

## Verification exit gate

`uv venv --python 3.11 && uv sync && uv run pytest -q -m "not integration"` — green.
