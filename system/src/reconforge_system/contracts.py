"""Pydantic contracts, exactly per CONTRACTS.md (task schema, verdict schema, cadence events)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

MESSAGE_TYPES = [
    "MT103",
    "MT202",
    "MT300",
    "MT940",
    "pacs.008",
    "pacs.009",
    "camt.054",
    "camt.053",
    "INTERNAL",
]

VERDICTS = ["MATCH", "EXCEPTION", "ESCALATE"]

EXCEPTION_TYPES = [
    "AMOUNT_MISMATCH",
    "FX_CONVERSION_ERROR",
    "BENEFICIARY_MISMATCH",
    "COUNTERPARTY_MISMATCH",
    "VALUE_DATE_MISMATCH",
    "MISSING_MESSAGE",
    "DUPLICATE",
    "FIELD_CORRUPTION",
    "PARTIAL_MATCH",
]

SEVERITIES = ["LOW", "MEDIUM", "HIGH"]

RESOLUTIONS = ["auto-adjust", "escalate", "reject", "rebook", "flag-review"]

# Exception taxonomy severity weights (fixed, A3) — mirrors CONTRACTS.md table.
SEVERITY_WEIGHTS = {
    "AMOUNT_MISMATCH": 1.0,
    "FX_CONVERSION_ERROR": 1.0,
    "BENEFICIARY_MISMATCH": 0.9,
    "COUNTERPARTY_MISMATCH": 0.9,
    "VALUE_DATE_MISMATCH": 0.6,
    "MISSING_MESSAGE": 0.6,
    "PARTIAL_MATCH": 0.5,
    "DUPLICATE": 0.2,
    "FIELD_CORRUPTION": 0.2,
}

LedgerSource = Literal["model", "human", "system"]
ReviewDecision = Literal["APPROVE", "REJECT", "CHANGE"]
CadenceEventType = Literal[
    "contamination-alert",
    "recalibration-complete",
    "benchmark-complete",
    "retrain-triggered",
]


class LedgerSide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal[
        "MT103", "MT202", "MT300", "MT940", "pacs.008", "pacs.009", "camt.054", "camt.053", "INTERNAL"
    ]
    ref: str
    amount: str
    ccy: str
    value_date: datetime.date
    counterparty: str
    beneficiary: str | None = None
    fx_rate: float | None = None
    booked_at: datetime.datetime | None = None


class StatementSide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal[
        "MT103", "MT202", "MT300", "MT940", "pacs.008", "pacs.009", "camt.054", "camt.053", "INTERNAL"
    ]
    ref: str
    amount: str
    ccy: str
    value_date: datetime.date
    counterparty: str
    beneficiary: str | None = None
    fx_rate: float | None = None


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["MATCH", "EXCEPTION", "ESCALATE"]
    exception_type: str | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    explanation: str
    resolution: str


class Pair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    seed: int | None = None
    difficulty: float | None = Field(default=None, ge=0.0, le=2.0)
    ledger: LedgerSide
    statement: StatementSide | None = None
    expected: Expected | None = None


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["MATCH", "EXCEPTION", "ESCALATE"]
    exception_type: str | None = Field(
        default=None,
        pattern="^(AMOUNT_MISMATCH|FX_CONVERSION_ERROR|BENEFICIARY_MISMATCH|COUNTERPARTY_MISMATCH|VALUE_DATE_MISMATCH|MISSING_MESSAGE|DUPLICATE|FIELD_CORRUPTION|PARTIAL_MATCH)$",
    )
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=200)
    resolution: Literal["auto-adjust", "escalate", "reject", "rebook", "flag-review"]
    review_state: Literal["resolved", "timed-out", "pending", "rejected"] | None = None


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    event_id: uuid.UUID
    pair: Pair | None = None
    verdict: Verdict | None = None
    source: LedgerSource
    created_at: datetime.datetime | None = None


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    event_id: uuid.UUID
    pair: Pair
    provisional_verdict: Verdict
    reason: str
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


class ReviewResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    decision: ReviewDecision
    note: str = Field(default="", max_length=2000)
    final_verdict: Verdict | None = None


class CadenceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CadenceEventType
    at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
