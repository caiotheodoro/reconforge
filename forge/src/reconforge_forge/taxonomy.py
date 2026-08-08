"""ReconForge exception taxonomy (fixed — A3, CONTRACTS.md).

Single source of truth for the nine exception types, severity weights,
verdict/severity/resolution vocabularies, and the canonical explanations
shared by the generator (expected) and the verifier (reason).
"""
from __future__ import annotations

EXCEPTION_TYPES: tuple[str, ...] = (
    "AMOUNT_MISMATCH",
    "FX_CONVERSION_ERROR",
    "BENEFICIARY_MISMATCH",
    "COUNTERPARTY_MISMATCH",
    "VALUE_DATE_MISMATCH",
    "MISSING_MESSAGE",
    "DUPLICATE",
    "FIELD_CORRUPTION",
    "PARTIAL_MATCH",
)

SEVERITY_WEIGHTS: dict[str, float] = {
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

VERDICTS: tuple[str, ...] = ("MATCH", "EXCEPTION", "ESCALATE")
SEVERITY_LEVELS: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")
RESOLUTIONS: tuple[str, ...] = ("auto-adjust", "escalate", "reject", "rebook", "flag-review")

SEVERITY_BY_EXCEPTION: dict[str, str] = {
    "AMOUNT_MISMATCH": "HIGH",
    "FX_CONVERSION_ERROR": "HIGH",
    "BENEFICIARY_MISMATCH": "HIGH",
    "COUNTERPARTY_MISMATCH": "HIGH",
    "VALUE_DATE_MISMATCH": "MEDIUM",
    "MISSING_MESSAGE": "MEDIUM",
    "PARTIAL_MATCH": "MEDIUM",
    "DUPLICATE": "LOW",
    "FIELD_CORRUPTION": "LOW",
}

RESOLUTION_BY_EXCEPTION: dict[str, str] = {
    "AMOUNT_MISMATCH": "escalate",
    "FX_CONVERSION_ERROR": "rebook",
    "BENEFICIARY_MISMATCH": "reject",
    "COUNTERPARTY_MISMATCH": "reject",
    "VALUE_DATE_MISMATCH": "auto-adjust",
    "MISSING_MESSAGE": "flag-review",
    "PARTIAL_MATCH": "flag-review",
    "DUPLICATE": "auto-adjust",
    "FIELD_CORRUPTION": "flag-review",
}

EXPLANATION_BY_EXCEPTION: dict[str | None, str] = {
    None: "all normalized fields agree within tolerance",
    "AMOUNT_MISMATCH": "amounts differ beyond rounding tolerance",
    "FX_CONVERSION_ERROR": "implied FX rate differs from stated rate beyond tolerance",
    "BENEFICIARY_MISMATCH": "beneficiary names differ",
    "COUNTERPARTY_MISMATCH": "counterparty identifiers differ",
    "VALUE_DATE_MISMATCH": "value date is invalid, late-booked, or differs between sides",
    "MISSING_MESSAGE": "statement message is absent",
    "DUPLICATE": "statement duplicates an already-booked instruction",
    "FIELD_CORRUPTION": "one side carries a malformed field",
    "PARTIAL_MATCH": "fields partially agree, needs human review",
}

REASON_BY_EXCEPTION: dict[str | None, str] = {
    None: "fields agree within tolerance",
    "AMOUNT_MISMATCH": "amounts differ beyond tolerance",
    "FX_CONVERSION_ERROR": "implied rate differs from stated",
    "BENEFICIARY_MISMATCH": "beneficiary names differ",
    "COUNTERPARTY_MISMATCH": "counterparty identifiers differ",
    "VALUE_DATE_MISMATCH": "value date invalid or differs",
    "MISSING_MESSAGE": "statement message missing",
    "DUPLICATE": "statement duplicates booked instruction",
    "FIELD_CORRUPTION": "malformed field on one side",
    "PARTIAL_MATCH": "fields partially agree, needs review",
}

MATCH_SEVERITY = "LOW"
MATCH_RESOLUTION = "auto-adjust"

# Known currencies for FIELD_CORRUPTION detection (ccy validation).
KNOWN_CCYS: frozenset[str] = frozenset(
    {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "BRL"}
)
