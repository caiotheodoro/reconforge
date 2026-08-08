"""Prompt templates, verdict schema, and robust JSON parsing for the ReconForge
reconciliation worker (Qwen3 non-thinking mode).

Follows CONTRACTS.md: the verdict schema, the 9-class exception taxonomy with
fixed severity weights (A3), and the matching rules for the worker.
"""
from __future__ import annotations

import json
import re
from typing import Any

VERDICTS = ("MATCH", "EXCEPTION", "ESCALATE")
EXCEPTION_TYPES = (
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
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
RESOLUTIONS = ("auto-adjust", "escalate", "reject", "rebook", "flag-review")

_VERDICT_KEYS = ("verdict", "exception_type", "severity", "confidence", "reason", "resolution")

# Fixed severity weights per exception type (CONTRACTS.md A3).
SEVERITY_WEIGHT: dict[str, float] = {
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

# Which exception types are HIGH / MEDIUM severity (for severity-weighted recall).
HIGH_TYPES = {t for t, w in SEVERITY_WEIGHT.items() if w >= 0.9}
MEDIUM_TYPES = {t for t, w in SEVERITY_WEIGHT.items() if w >= 0.5 and w < 0.9}
LOW_TYPES = {t for t, w in SEVERITY_WEIGHT.items() if w < 0.5}

SYSTEM_PROMPT = """You are ReconForge, a financial back-office reconciliation operations engine. \
You reconcile a single ledger entry against a single bank statement entry and return a structured verdict.

Your output MUST be exactly one JSON object with these keys:
- "verdict": "MATCH" | "EXCEPTION" | "ESCALATE"
- "exception_type": null or one of AMOUNT_MISMATCH, FX_CONVERSION_ERROR, \
BENEFICIARY_MISMATCH, COUNTERPARTY_MISMATCH, VALUE_DATE_MISMATCH, MISSING_MESSAGE, \
DUPLICATE, FIELD_CORRUPTION, PARTIAL_MATCH
- "severity": "LOW" | "MEDIUM" | "HIGH"
- "confidence": float in [0, 1]
- "reason": short reason, under 10 words
- "resolution": one of "auto-adjust", "escalate", "reject", "rebook", "flag-review"

Matching rules:
- MATCH requires the two sides to agree on: normalized amount (decimal 2dp, \
rounding tolerance of 0.5% of the larger amount), currency, value date, \
counterparty, and beneficiary.
- A currency mismatch is not automatically a MATCH: verify the implied FX rate \
(amount_foreign / amount_local) is within 0.5% of the stated fx_rate. If the \
rate is inconsistent, classify as FX_CONVERSION_ERROR.
- Each exception type maps to a severity: AMOUNT_MISMATCH/FX_CONVERSION_ERROR/\
BENEFICIARY_MISMATCH/COUNTERPARTY_MISMATCH are HIGH; VALUE_DATE_MISMATCH/\
MISSING_MESSAGE/PARTIAL_MATCH are MEDIUM; DUPLICATE/FIELD_CORRUPTION are LOW.
- If the pair is ambiguous and the verdict is not decidable from the fields, \
use "verdict": "ESCALATE" with "resolution": "flag-review".
- A missing counterpart side on the statement is MISSING_MESSAGE, not a MATCH.
- Reply with ONLY the JSON object. No markdown fences, no commentary, no thinking."""

USER_TEMPLATE = """Reconcile the following ledger entry against the bank statement.

LEDGER ENTRY:
{ledger}

BANK STATEMENT:
{statement}

Return the verdict JSON object only."""


def _render_side(side: dict[str, Any] | None) -> str:
    if not side:
        return "null"
    return json.dumps(side, indent=2, sort_keys=True)


def render_user_message(pair: dict[str, Any]) -> str:
    """Render a task pair (ledger+statement) into the user prompt."""
    return USER_TEMPLATE.format(
        ledger=_render_side(pair.get("ledger")),
        statement=_render_side(pair.get("statement")),
    )


def default_severity(exception_type: str | None, verdict: str) -> str:
    if exception_type in HIGH_TYPES:
        return "HIGH"
    if exception_type in MEDIUM_TYPES:
        return "MEDIUM"
    if exception_type in LOW_TYPES:
        return "LOW"
    return "LOW" if verdict == "MATCH" else "MEDIUM"


def normalize_verdict(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize a parsed verdict dict against the schema.

    Hard failures (unknown verdict, EXCEPTION without a valid exception_type)
    return the raw dict untouched so callers can treat it as a parse failure.
    Soft issues (missing severity/resolution/confidence) get filled in.
    """
    verdict = raw.get("verdict")
    if verdict not in VERDICTS:
        return raw
    exception_type = raw.get("exception_type") or None
    if exception_type is not None and exception_type not in EXCEPTION_TYPES:
        return raw
    if verdict == "EXCEPTION" and exception_type is None:
        return raw
    if verdict != "EXCEPTION":
        exception_type = None
    severity = raw.get("severity")
    if severity not in SEVERITIES:
        severity = default_severity(exception_type, verdict)
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    resolution = raw.get("resolution")
    if resolution not in RESOLUTIONS:
        resolution = "flag-review"
    reason = raw.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return {
        "verdict": verdict,
        "exception_type": exception_type,
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
        "resolution": resolution,
    }


def _balanced_json(text: str) -> list[str]:
    """Return candidate JSON substrings starting at each '{' with balanced braces."""
    candidates: list[str] = []
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_str = False
        escape = False
        for j in range(i, len(text)):
            c = text[j]
            if in_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[i : j + 1])
                    break
        else:
            # Unclosed at end of text — try with a synthetic closing brace.
            if depth > 0:
                candidates.append(text[i:] + "}")
    return candidates


def parse_verdict(text: str) -> dict[str, Any] | None:
    """Extract a verdict dict from raw model output. Returns None on hard failure.

    Robust to markdown fences, surrounding commentary, truncation (missing
    closing brace), and soft schema violations (which get normalized defaults).
    """
    if not text or not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S | re.I)
        if fenced:
            stripped = fenced.group(1).strip()
    for candidate in _balanced_json(stripped):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or "verdict" not in parsed:
            continue
        normalized = normalize_verdict(parsed)
        if normalized is parsed:
            continue
        return normalized
    return None


def verdict_from_expected(expected: dict[str, Any]) -> dict[str, Any]:
    """Map a forge task's `expected` field to the canonical verdict dict the
    assistant must output (camelCase keys per CONTRACTS.md)."""
    verdict = expected.get("verdict")
    exception_type = expected.get("exception_type")
    severity = expected.get("severity")
    if severity not in SEVERITIES:
        severity = default_severity(exception_type, verdict)
    reason = expected.get("explanation") or expected.get("reason") or ""
    reason = re.sub(r"\s+", " ", reason).strip()
    if len(reason.split()) > 10:
        reason = " ".join(reason.split()[:10]) + "..."
    return {
        "verdict": verdict,
        "exception_type": exception_type if exception_type in EXCEPTION_TYPES else None,
        "severity": severity,
        "confidence": 1.0,
        "reason": reason,
        "resolution": expected.get("resolution", "flag-review"),
    }


def canonical_verdict_json(expected: dict[str, Any]) -> str:
    """Byte-stable canonical JSON for the assistant training target."""
    return json.dumps(verdict_from_expected(expected), sort_keys=True, separators=(",", ":"))
