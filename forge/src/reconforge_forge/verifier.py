"""Canonical verifier — verifier-as-oracle (CONTRACTS.md tolerance semantics).

Recomputes the verdict from the task FIELDS ONLY. It never reads
``task.expected``. Guarantee: 100% agreement with the generator's
``expected`` over the pilot set (the oracle gate).

Semantics implemented:
- amount equality via |a-b| <= 0.005 * max(|a|,|b|) on decimal-normalized
  2dp amounts;
- FX-aware: when ccys differ and exactly one side carries ``fx_rate``, the
  implied rate (foreign amount / local amount) must lie within +/- 0.5% of
  the stated rate, else FX_CONVERSION_ERROR;
- value dates must be ISO business days (simple weekday rule, no holidays)
  and not later than booked_at + 2 calendar days;
- refs trimmed; beneficiary/counterparty normalized (case/whitespace/
  punctuation-insensitive) for equality, with a near-equal rule for
  PARTIAL_MATCH;
- duplicate = trimmed refs equal;
- single-exception priority order (first rule that fires wins) shared with
  the generator.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from reconforge_forge import taxonomy
from reconforge_forge.task import Task

ROUNDING_TOLERANCE = Decimal("0.005")
FX_TOLERANCE = Decimal("0.005")

_DATE_FMT = "%Y-%m-%d"
_BOOKED_FMT = "%Y-%m-%dT%H:%M:%SZ"
_MAX_BOOKING_LAG_DAYS = 2

_TOKEN_RE = re.compile(r"[A-Z0-9]{2,}")
_NORM_RE = re.compile(r"[^A-Z0-9]")


def _result(
    verdict: str, exception_type: str | None, reason: str
) -> dict[str, Any]:
    if verdict == "MATCH":
        return {
            "verdict": verdict,
            "exception_type": None,
            "severity": taxonomy.MATCH_SEVERITY,
            "confidence": 1.0,
            "reason": reason,
            "resolution": taxonomy.MATCH_RESOLUTION,
        }
    return {
        "verdict": verdict,
        "exception_type": exception_type,
        "severity": taxonomy.SEVERITY_BY_EXCEPTION[exception_type],
        "confidence": 1.0,
        "reason": reason,
        "resolution": taxonomy.RESOLUTION_BY_EXCEPTION[exception_type],
    }


def _amount(raw: Any) -> Decimal:
    return Decimal(str(raw))


def _norm_ref(raw: Any) -> str:
    return str(raw or "").strip()


def _norm_text(raw: Any) -> str:
    """Case/whitespace/punctuation-insensitive normalization."""
    return _NORM_RE.sub("", str(raw or "").upper())


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text))


def _near_equal(a: str, b: str) -> bool:
    """Near-equal names (abbreviation / truncation / one-token drift) —
    the PARTIAL_MATCH trigger. Equality must already have been ruled out.
    Tokenizes the RAW names (space-delimited), not the alnum-stripped
    normalization, so "ACME CORP" vs "ACME CORPORATION" still separates;
    compact identifiers (BICs, refs) are covered by the raw prefix rule."""
    ra, rb = str(a).upper(), str(b).upper()
    ta, tb = _tokens(ra), _tokens(rb)
    if not ta or not tb:
        return False
    if ta == tb:
        return False
    sym_diff = len(ta ^ tb)
    if (ta.issubset(tb) or tb.issubset(ta)) or (sym_diff <= 2 and len(ta & tb) >= 1):
        return True
    if len(ra) >= 4 and len(rb) >= 4:
        return ra.startswith(rb) or rb.startswith(ra)
    return False


def _amounts_equal(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= ROUNDING_TOLERANCE * max(abs(a), abs(b))


def _corrupt(side: dict[str, Any]) -> bool:
    """FIELD_CORRUPTION rule: amount parseable with <= 2 dp and non-negative,
    ccy a known currency, value_date strict ISO, ref/beneficiary/counterparty
    present and printable."""
    if not isinstance(side, dict):
        return True
    try:
        amt = _amount(side.get("amount"))
    except Exception:
        return True
    if amt < 0 or amt.as_tuple().exponent < -2:
        return True
    if str(side.get("ccy") or "").upper() not in taxonomy.KNOWN_CCYS:
        return True
    if not _parse_date(str(side.get("value_date") or "")):
        return True
    for key in ("ref", "beneficiary", "counterparty"):
        val = str(side.get(key) or "").strip()
        if not val or not val.isprintable():
            return True
    return False


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, _DATE_FMT)
    except (TypeError, ValueError):
        return None


def _parse_booked(raw: str) -> datetime | None:
    try:
        return datetime.strptime(str(raw).strip(), _BOOKED_FMT)
    except (TypeError, ValueError):
        return None


def _value_date_valid(side: dict[str, Any]) -> bool:
    d = _parse_date(str(side.get("value_date") or ""))
    if d is None:
        return False
    if d.weekday() >= 5:
        return False
    booked = _parse_booked(str(side.get("booked_at") or ""))
    if booked is not None:
        if d.date() > (booked.date() + timedelta(days=_MAX_BOOKING_LAG_DAYS)):
            return False
    return True


def _resolve_fx(
    ledger: dict[str, Any], statement: dict[str, Any]
) -> tuple[Decimal, Decimal] | None:
    """Returns (implied_rate, stated_rate) when the pair is FX-resolvable
    (exactly one side carries fx_rate and the other holds the local ccy)."""
    lr = ledger.get("fx_rate")
    sr = statement.get("fx_rate")
    if lr is not None and sr is None:
        foreign, local = ledger, statement
        stated = Decimal(str(lr))
    elif sr is not None and lr is None:
        foreign, local = statement, ledger
        stated = Decimal(str(sr))
    else:
        return None
    famount = _amount(foreign["amount"])
    lamount = _amount(local["amount"])
    if lamount == 0:
        return None
    return famount / lamount, stated


def _rate_within_window(implied: Decimal, stated: Decimal) -> bool:
    denom = max(abs(implied), abs(stated))
    if denom == 0:
        return True
    return abs(implied - stated) / denom <= FX_TOLERANCE


def verify_task(task: Task) -> dict[str, Any]:
    """Recompute the verdict from the pair fields ONLY."""
    ledger, statement = task.ledger, task.statement

    if statement is None:
        return _result(
            "EXCEPTION", "MISSING_MESSAGE",
            taxonomy.REASON_BY_EXCEPTION["MISSING_MESSAGE"],
        )

    if _corrupt(ledger) or _corrupt(statement):
        return _result(
            "EXCEPTION", "FIELD_CORRUPTION",
            taxonomy.REASON_BY_EXCEPTION["FIELD_CORRUPTION"],
        )

    ledger_amt = _amount(ledger["amount"])
    stmt_amt = _amount(statement["amount"])
    ledger_ccy = str(ledger["ccy"]).upper()
    stmt_ccy = str(statement["ccy"]).upper()

    if ledger_ccy == stmt_ccy:
        if not _amounts_equal(ledger_amt, stmt_amt):
            return _result(
                "EXCEPTION", "AMOUNT_MISMATCH",
                taxonomy.REASON_BY_EXCEPTION["AMOUNT_MISMATCH"],
            )
    else:
        fx = _resolve_fx(ledger, statement)
        if fx is None or not _rate_within_window(*fx):
            return _result(
                "EXCEPTION", "FX_CONVERSION_ERROR",
                taxonomy.REASON_BY_EXCEPTION["FX_CONVERSION_ERROR"],
            )

    if _norm_ref(ledger["ref"]) == _norm_ref(statement["ref"]):
        return _result(
            "EXCEPTION", "DUPLICATE",
            taxonomy.REASON_BY_EXCEPTION["DUPLICATE"],
        )

    lb, sb = _norm_text(ledger["beneficiary"]), _norm_text(statement["beneficiary"])
    if lb != sb:
        if _near_equal(ledger["beneficiary"], statement["beneficiary"]):
            return _result(
                "EXCEPTION", "PARTIAL_MATCH",
                taxonomy.REASON_BY_EXCEPTION["PARTIAL_MATCH"],
            )
        return _result(
            "EXCEPTION", "BENEFICIARY_MISMATCH",
            taxonomy.REASON_BY_EXCEPTION["BENEFICIARY_MISMATCH"],
        )

    lc, sc = _norm_text(ledger["counterparty"]), _norm_text(statement["counterparty"])
    if lc != sc:
        if _near_equal(ledger["counterparty"], statement["counterparty"]):
            return _result(
                "EXCEPTION", "PARTIAL_MATCH",
                taxonomy.REASON_BY_EXCEPTION["PARTIAL_MATCH"],
            )
        return _result(
            "EXCEPTION", "COUNTERPARTY_MISMATCH",
            taxonomy.REASON_BY_EXCEPTION["COUNTERPARTY_MISMATCH"],
        )

    if not _value_date_valid(ledger) or not _value_date_valid(statement):
        return _result(
            "EXCEPTION", "VALUE_DATE_MISMATCH",
            taxonomy.REASON_BY_EXCEPTION["VALUE_DATE_MISMATCH"],
        )
    if ledger["value_date"] != statement["value_date"]:
        return _result(
            "EXCEPTION", "VALUE_DATE_MISMATCH",
            taxonomy.REASON_BY_EXCEPTION["VALUE_DATE_MISMATCH"],
        )

    return _result("MATCH", None, taxonomy.REASON_BY_EXCEPTION[None])
