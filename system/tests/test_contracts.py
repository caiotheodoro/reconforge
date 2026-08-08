from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from reconforge_system.contracts import CadenceEvent, Escalation, LedgerEntry, Pair, ReviewResolution, Verdict


def test_valid_pair_passes(sample_pair_dict):
    pair = Pair(**sample_pair_dict)
    assert pair.task_id == "recon-000001"
    assert pair.ledger.message_type == "MT103"
    assert pair.statement.value_date == datetime.date(2026, 8, 7)
    assert pair.expected.verdict == "MATCH"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d.update({"ledger": {**d["ledger"], "message_type": "MT999"}}),
        lambda d: d.update({"statement": {**d["statement"], "amount": None}}),
        lambda d: d.update({"difficulty": 1.5}),
        lambda d: d.update({"expected": {**d["expected"], "severity": "CRITICAL"}}),
        lambda d: d.pop("ledger"),
    ],
)
def test_invalid_pair_fails(sample_pair_dict, mutator):
    bad = dict(sample_pair_dict)
    mutator(bad)
    with pytest.raises(ValidationError):
        Pair(**bad)


def test_verdict_confidence_bounds():
    Verdict(
        verdict="MATCH",
        exception_type=None,
        severity="LOW",
        confidence=1.0,
        reason="ok",
        resolution="auto-adjust",
    )
    with pytest.raises(ValidationError):
        Verdict(
            verdict="MATCH",
            exception_type=None,
            severity="LOW",
            confidence=1.01,
            reason="ok",
            resolution="auto-adjust",
        )


def test_verdict_exception_type_must_be_taxonomy():
    with pytest.raises(ValidationError):
        Verdict(
            verdict="EXCEPTION",
            exception_type="NOT_A_TYPE",
            severity="HIGH",
            confidence=0.9,
            reason="bad",
            resolution="escalate",
        )


def test_verdict_exception_type_none_allowed_for_match():
    Verdict(
        verdict="MATCH",
        exception_type=None,
        severity="LOW",
        confidence=0.9,
        reason="ok",
        resolution="auto-adjust",
    )


def test_cadence_event_types():
    for event_type in ("contamination-alert", "recalibration-complete", "benchmark-complete", "retrain-triggered"):
        event = CadenceEvent(type=event_type, payload={"k": 1})
        assert event.at.tzinfo is not None
    with pytest.raises(ValidationError):
        CadenceEvent(type="not-a-type")


def test_escalation_defaults_timestamp(sample_pair_dict, match_verdict):
    escalation = Escalation(
        task_id="recon-1",
        event_id="12345678-1234-5678-1234-567812345678",
        pair=Pair(**sample_pair_dict),
        provisional_verdict=Verdict(**match_verdict),
        reason="low confidence",
    )
    assert escalation.created_at is not None


def test_review_resolution_requires_valid_decision():
    ReviewResolution(task_id="t", decision="APPROVE")
    ReviewResolution(task_id="t", decision="CHANGE", final_verdict=None)
    with pytest.raises(ValidationError):
        ReviewResolution(task_id="t", decision="MAYBE")


def test_ledger_entry_requires_source_enum(sample_pair_dict, match_verdict):
    LedgerEntry(
        task_id="t",
        event_id="12345678-1234-5678-1234-567812345678",
        pair=Pair(**sample_pair_dict),
        verdict=Verdict(**match_verdict),
        source="model",
    )
    with pytest.raises(ValidationError):
        LedgerEntry(task_id="t", event_id="12345678-1234-5678-1234-567812345678", source="kafka")
