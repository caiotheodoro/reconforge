"""Verifier tests: tolerance semantics, normalization, exception detection,
and the verifier-as-oracle discipline (fields only, never expected)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from reconforge_forge.task import Task
from reconforge_forge.taxonomy import EXCEPTION_TYPES
from reconforge_forge.verifier import verify_task


def _task(ledger: dict, statement: dict | None, expected=None) -> Task:
    return Task(
        task_id="t1",
        seed=1,
        difficulty=0.7,
        ledger=ledger,
        statement=statement,
        expected=expected or {},
    )


def _pair(**overrides):
    side = overrides.pop("side", "statement")
    base = {
        "message_type": "MT103",
        "ref": "OUR-REF-001" if side == "ledger" else "CP-REF-001",
        "amount": "1250.00",
        "ccy": "USD",
        "value_date": "2026-08-07",
        "counterparty": "BANK-ACCT-1234",
        "beneficiary": "ACME CORP",
        "fx_rate": None,
    }
    base.update(overrides)
    if side == "ledger":
        base.setdefault("booked_at", "2026-08-06T14:02:11Z")
    return base


def _task_pair(statement_overrides=None, ledger_overrides=None) -> Task:
    ledger = _pair(side="ledger", **(ledger_overrides or {}))
    statement = _pair(**(statement_overrides or {}))
    return _task(ledger, statement)


def test_clean_pair_is_match():
    r = verify_task(_task_pair())
    assert r["verdict"] == "MATCH"
    assert r["exception_type"] is None
    assert r["confidence"] == 1.0
    assert len(r["reason"].split()) < 10


def test_amount_normalization_strips_trailing_zeros():
    r = verify_task(_task_pair({"amount": "1250"}))
    assert r["verdict"] == "MATCH"


def test_ccy_normalization_uppercase():
    r = verify_task(_task_pair({"ccy": "usd"}, {"ccy": "USD"}))
    assert r["verdict"] == "MATCH"


def test_ref_trimming():
    r = verify_task(_task_pair({"ref": " CP-REF-001 "}))
    assert r["verdict"] == "MATCH"


def test_rounding_tolerance_boundary_is_match():
    a = "1000.00"
    b = "1005.00"
    assert abs(Decimal(b) - Decimal(a)) <= Decimal("0.005") * max(
        abs(Decimal(a)), abs(Decimal(b))
    )
    r = verify_task(_task_pair({"amount": b}, {"amount": a}))
    assert r["verdict"] == "MATCH"


def test_amount_beyond_tolerance_is_mismatch():
    r = verify_task(_task_pair({"amount": "1006.00"}))
    assert r["verdict"] == "EXCEPTION"
    assert r["exception_type"] == "AMOUNT_MISMATCH"
    assert r["severity"] == "HIGH"


def test_fx_implied_rate_within_window_is_match():
    r = verify_task(_task_pair(
        {"amount": "1250.00", "ccy": "USD", "fx_rate": None},
        {"amount": "1150.00", "ccy": "EUR", "fx_rate": 0.92},
    ))
    assert r["verdict"] == "MATCH"


def test_fx_wrong_rate_is_conversion_error():
    r = verify_task(_task_pair(
        {"amount": "1250.00", "ccy": "USD", "fx_rate": None},
        {"amount": "1150.00", "ccy": "EUR", "fx_rate": 0.85},
    ))
    assert r["verdict"] == "EXCEPTION"
    assert r["exception_type"] == "FX_CONVERSION_ERROR"


def test_fx_rate_within_window_is_match():
    r = verify_task(_task_pair(
        {"amount": "1000.00", "ccy": "USD", "fx_rate": None},
        {"amount": "920.00", "ccy": "EUR", "fx_rate": 0.9245},
    ))
    assert r["verdict"] == "MATCH"


def test_fx_rate_just_beyond_window_is_error():
    r = verify_task(_task_pair(
        {"amount": "1000.00", "ccy": "USD", "fx_rate": None},
        {"amount": "920.00", "ccy": "EUR", "fx_rate": 0.9255},
    ))
    assert r["exception_type"] == "FX_CONVERSION_ERROR"


def test_beneficiary_mismatch():
    r = verify_task(_task_pair({"beneficiary": "BLUESTONE CAPITAL LLP"}))
    assert r["exception_type"] == "BENEFICIARY_MISMATCH"


def test_beneficiary_normalization_variant_is_match():
    r = verify_task(_task_pair({"beneficiary": "acme corp"}))
    assert r["verdict"] == "MATCH"


def test_beneficiary_near_equal_is_partial_match():
    r = verify_task(_task_pair({"beneficiary": "ACME CORPORATION"}))
    assert r["exception_type"] == "PARTIAL_MATCH"


def test_counterparty_mismatch():
    r = verify_task(_task_pair({"counterparty": "GOLDENGATE-501"}))
    assert r["exception_type"] == "COUNTERPARTY_MISMATCH"


def test_counterparty_truncation_is_partial_match():
    r = verify_task(_task_pair(
        {"counterparty": "CHASUS33"},
        {"counterparty": "CHASUS33XXX"},
    ))
    assert r["exception_type"] == "PARTIAL_MATCH"


def test_weekend_value_date_is_mismatch():
    r = verify_task(_task_pair({"value_date": "2026-08-08"}))  # Saturday
    assert r["exception_type"] == "VALUE_DATE_MISMATCH"
    assert r["severity"] == "MEDIUM"


def test_late_booking_is_value_date_mismatch():
    ledger = _pair(side="ledger", booked_at="2026-08-02T10:00:00Z")
    r = verify_task(_task(ledger, _pair()))
    assert r["exception_type"] == "VALUE_DATE_MISMATCH"


def test_value_date_business_day_ok():
    r = verify_task(_task_pair(
        {"value_date": "2026-08-10"},
        {"value_date": "2026-08-10", "booked_at": "2026-08-08T10:00:00Z"},
    ))
    assert r["verdict"] == "MATCH"


def test_differing_value_dates_is_mismatch():
    r = verify_task(_task_pair({"value_date": "2026-08-10"}))
    assert r["exception_type"] == "VALUE_DATE_MISMATCH"


def test_missing_statement_is_missing_message():
    r = verify_task(_task(_pair(side="ledger"), None))
    assert r["exception_type"] == "MISSING_MESSAGE"
    assert r["severity"] == "MEDIUM"


def test_duplicate_ref_is_duplicate():
    r = verify_task(_task_pair({"ref": "OUR-REF-001"}))
    assert r["exception_type"] == "DUPLICATE"
    assert r["severity"] == "LOW"


def test_field_corruption_amount_precision():
    r = verify_task(_task_pair({"amount": "1250.001"}))
    assert r["exception_type"] == "FIELD_CORRUPTION"


def test_field_corruption_invalid_ccy():
    r = verify_task(_task_pair({"ccy": "EURO"}))
    assert r["exception_type"] == "FIELD_CORRUPTION"


def test_field_corruption_malformed_date():
    r = verify_task(_task_pair({"value_date": "2026/08/07"}))
    assert r["exception_type"] == "FIELD_CORRUPTION"


def test_verifier_never_reads_expected():
    honest = verify_task(_task_pair())
    planted = verify_task(_task_pair({"amount": "1250.001"}))
    lying = _task_pair({"amount": "1250.001"})
    lying.expected["exception_type"] = "DUPLICATE"
    recomputed = verify_task(lying)
    assert recomputed == planted
    assert recomputed["exception_type"] == "FIELD_CORRUPTION"
    assert recomputed != honest


def test_verifier_ignores_expected_verdict_field():
    t = _task_pair()
    t.expected["verdict"] = "EXCEPTION"
    r = verify_task(t)
    assert r["verdict"] == "MATCH"


def test_exception_verdicts_and_taxonomy_coverage():
    cases = {
        "AMOUNT_MISMATCH": {"amount": "1300.00"},
        "BENEFICIARY_MISMATCH": {"beneficiary": "BLUESTONE CAPITAL LLP"},
        "COUNTERPARTY_MISMATCH": {"counterparty": "GOLDENGATE-501"},
        "VALUE_DATE_MISMATCH": {"value_date": "2026-08-08"},
        "DUPLICATE": {"ref": "OUR-REF-001"},
        "FIELD_CORRUPTION": {"ccy": "EURO"},
    }
    for etype, ov in cases.items():
        r = verify_task(_task_pair(ov))
        assert r["verdict"] == "EXCEPTION"
        assert r["exception_type"] == etype
        assert r["exception_type"] in EXCEPTION_TYPES
