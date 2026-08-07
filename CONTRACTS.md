# ReconForge — Shared Contracts

This file is the coordination contract for every parallel workstream. If you
change something here, update this file first. All agents must follow it.

## Repo layout (ownership boundaries — do not cross)

| Path | Owner | What it is |
|---|---|---|
| `docs/corpus/` | corpus agent | Research corpus, gold triples, extraction schema |
| `forge/` | forge agent | Python package `reconforge_forge`: generator, verifier, benchmark, contamination monitor |
| `knowledge/` | knowledge agent | Python package `reconforge_knowledge`: GraphRAG extraction, Neo4j loader, grounded gate |
| `model/` | model agent | Dataset builder, MLX-LoRA training, eval |
| `system/` | system agent | Microservices, Temporal workers, cadence |
| `docs/validation/` | shared | Generated study/benchmark artifacts (JSON) |
| `docker-compose.yaml`, `Makefile`, `CONTRACTS.md`, `README.md`, `.env*` | root | Shared infra and contracts |

No agent may edit files outside its directory except `docs/validation/` and
root `CONTRACTS.md` (append-only).

## Task schema (the "pair" — every system input)

```json
{
  "task_id": "recon-000001",
  "seed": 42,
  "difficulty": 0.7,
  "ledger": {
    "message_type": "MT103",
    "ref": "OUR-REF-001",
    "amount": "1250.00",
    "ccy": "USD",
    "value_date": "2026-08-07",
    "counterparty": "BANK-ACCT-1234",
    "beneficiary": "ACME CORP",
    "fx_rate": null,
    "booked_at": "2026-08-06T14:02:11Z"
  },
  "statement": {
    "message_type": "MT940",
    "ref": "CP-REF-001",
    "amount": "1250.00",
    "ccy": "USD",
    "value_date": "2026-08-07",
    "counterparty": "BANK-ACCT-1234",
    "beneficiary": "ACME CORP"
  },
  "expected": {
    "verdict": "MATCH",
    "exception_type": null,
    "severity": "LOW",
    "explanation": "canonical explanation",
    "resolution": "auto-adjust"
  }
}
```

`message_type` ∈ {MT103, MT202, MT300, MT940, pacs.008, pacs.009, camt.054,
camt.053, INTERNAL}. Ledger side may carry `fx_rate` (rate applied at booking);
statement side may carry `fx_rate` too. At most one of the two sides is a
foreign-currency record when FX is involved.

## Verdict schema (every model/decision output)

```json
{
  "verdict": "MATCH | EXCEPTION | ESCALATE",
  "exception_type": null | "AMOUNT_MISMATCH | FX_CONVERSION_ERROR | BENEFICIARY_MISMATCH | COUNTERPARTY_MISMATCH | VALUE_DATE_MISMATCH | MISSING_MESSAGE | DUPLICATE | FIELD_CORRUPTION | PARTIAL_MATCH",
  "severity": "LOW | MEDIUM | HIGH",
  "confidence": 0.0,
  "reason": "short reason, <10 words",
  "resolution": "auto-adjust | escalate | reject | rebook | flag-review"
}
```

## Exception taxonomy + severity weights (fixed — A3)

| exception_type | severity | weight | rationale |
|---|---|---|---|
| AMOUNT_MISMATCH | HIGH | 1.0 | principal at risk |
| FX_CONVERSION_ERROR | HIGH | 1.0 | wrong rate applied |
| BENEFICIARY_MISMATCH | HIGH | 0.9 | misdirected funds |
| COUNTERPARTY_MISMATCH | HIGH | 0.9 | wrong counterparty |
| VALUE_DATE_MISMATCH | MEDIUM | 0.6 | settlement timing/interest |
| MISSING_MESSAGE | MEDIUM | 0.6 | breaks STP |
| PARTIAL_MATCH | MEDIUM | 0.5 | ambiguous, needs human |
| DUPLICATE | LOW | 0.2 | double-booking risk |
| FIELD_CORRUPTION | LOW | 0.2 | data quality |

**Severity-weighted recall** (primary metric): `R_w = Σ w_i·1[caught_i] / Σ w_i`
over exception tasks, where caught = model flagged the pair as anything other
than MATCH for HIGH severity, or correctly identified the exception type for
MEDIUM/LOW. Define precisely in `forge`; score it in benchmark.

**Verifier-as-oracle rule**: the verifier recomputes the verdict from the
fields ONLY. It must never read `expected`. The oracle gate is: 100%
agreement between verifier and `expected` over the pilot set, deterministically.

## Verifier tolerance semantics

- **Normalization**: amounts decimal-normalized (strip trailing zeros, 2dp
  default), ccy uppercased, dates ISO `YYYY-MM-DD`, refs trimmed.
- **Rounding tolerance**: amounts equal if `|a−b| ≤ 0.005·max(|a|,|b|)`.
- **FX-aware**: when one side is foreign currency, implied rate =
  `amount_foreign / amount_local`; valid if implied rate within ±0.5% of the
  other side's stated `fx_rate` (or of the generator's injected rate window).
  A pair whose amounts are otherwise plausible but the rate is off by more
  than the window → `FX_CONVERSION_ERROR`.
- **Date conventions**: value_date must be a business day per a simple weekday
  rule (no holiday calendar); value_date > booked date + 2 calendar days is a
  `VALUE_DATE_MISMATCH` (late booking) only when the generator injected it.

## Entity/relation schema for the knowledge graph (fixed)

Entity types: `MessageType`, `Field`, `PaymentInstruction`, `SettlementSystem`,
`Risk`, `Rule`, `Instrument`, `Workflow`, `Currency`, `DateConvention`.
Relation types: `COVERS`, `REQUIRES`, `HAS_FIELD`, `CONFLICTS_WITH`,
`TRIGGERS`, `APPLIES_TO`, `MITIGATES`, `RELATED_TO`, `COUNTERPART_OF`.

Gold-triples file format: `docs/corpus/gold-triples.json` =
`[{ "head": "MT103", "relation": "COVERS", "tail": "CustomerCreditTransfer",
"source": "url-or-doc-ref", "confidence": 0.95 }]`.

## Infrastructure (root `docker-compose.yaml` — M5, 16GB budget)

| Service | Image | Port | Memory cap |
|---|---|---|---|
| kafka | bitnami/kafka:latest (KRaft, single node) | 9092 | 1g |
| postgres | postgres:16 | 5432 | 512m |
| neo4j | neo4j:5-community | 7474, 7687 | 1g |
| redis | redis:7 | 6379 | 128m |
| model | mlx_lm.server (host process) | 9100 | — |
| ingest | FastAPI | 9101 | — |
| decision | FastAPI | 9102 | — |
| ledger | FastAPI | 9103 | — |
| gate | FastAPI | 9104 | — |
| hitl | FastAPI + Temporal worker | 9105 | — |
| cadence | Temporal worker (schedules) | — | — |

Kafka topics (KRaft, auto-create): `recon.raw-pairs`, `recon.verdicts`,
`recon.exceptions`, `recon.escalations`, `recon.cadence-events`.

## Environment variables (read from `.env`, never hardcode secrets)

`TEMPORAL_CLOUD_API_KEY`, `TEMPORAL_CLOUD_ACCOUNT_ID`, `TEMPORAL_NAMESPACE`
(=`reconforge.drilv`), `TEMPORAL_HOST`,
`MODEL_PROVIDER_BASE_URL` (=https://api.deepseek.com),
`MODEL_PROVIDER_MODEL_ID` (=deepseek-v4-flash), `MODEL_PROVIDER_API_KEY`,
`POSTGRES_USER/PASSWORD/DB/PORT`, `NEO4J_AUTH`, `KAFKA_BROKER`, `REDIS_URL`,
`MODEL_SERVICE_URL`, `MLX_BASE_MODEL`.

## Base model (fixed — A1 default, may be revised with evidence)

`Qwen/Qwen3-1.7B`, Apache-2.0. Non-thinking mode (worker): chat template with
`enable_thinking=False`. Fine-tune via `mlx_lm` LoRA (QLoRA on Q8/Q4 base if
needed for memory). Adapters → `model/adapters/`. Serve via `mlx_lm.server`
with `--adapter-path`.

## Cross-cutting rules

- **Secrets**: never write keys in code, tests, or logs. Read from env.
- **Determinism**: every generator/benchmark entrypoint takes `--seed`; same
  seed → byte-identical outputs.
- **Heavy compute etiquette**: only ONE heavy consumer at a time on this M5.
  Full MLX training and full `docker compose up` must not run concurrently.
  Smoke tests (single service, short runs) are fine.
- **Reference implementation** to study before writing forge code:
  `/Users/caiotheodoro/Documents/personal/research/apps/trust/py/src/trust/forge/`
  (reuse patterns, don't copy wholesale; this project is standalone).
