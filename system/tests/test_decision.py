from __future__ import annotations

import pytest

from reconforge_system.contracts import Pair, Verdict
from reconforge_system.decision_core import Outcome, classify
from reconforge_system.kafka_util import TOPIC_ESCALATIONS, TOPIC_EXCEPTIONS, TOPIC_VERDICTS
from reconforge_system.services.decision import DecisionPipeline
from tests.fakes import FakeFallback, FakeLedgerClient, FakeModel, FakePublisher, FakeWorkflowStarter


def make_verdict(**overrides) -> Verdict:
    base = {
        "verdict": "MATCH",
        "exception_type": None,
        "severity": "LOW",
        "confidence": 0.98,
        "reason": "amounts reconcile",
        "resolution": "auto-adjust",
    }
    base.update(overrides)
    return Verdict(**base)


class TestClassify:
    def test_low_confidence_escalates(self):
        decision = classify(make_verdict(confidence=0.4), 0.6, ["HIGH"])
        assert decision.outcome == Outcome.ESCALATE

    def test_high_severity_always_escalates(self):
        decision = classify(make_verdict(severity="HIGH", confidence=0.99), 0.6, ["HIGH"])
        assert decision.outcome == Outcome.ESCALATE

    def test_escalate_verdict_escalates(self):
        decision = classify(make_verdict(verdict="ESCALATE", severity="MEDIUM"), 0.6, ["HIGH"])
        assert decision.outcome == Outcome.ESCALATE

    def test_high_confidence_match_records(self):
        decision = classify(make_verdict(), 0.6, ["HIGH"])
        assert decision.outcome == Outcome.VERDICT

    def test_exception_records_exception(self):
        decision = classify(
            make_verdict(verdict="EXCEPTION", exception_type="AMOUNT_MISMATCH", severity="MEDIUM"),
            0.6,
            ["HIGH"],
        )
        assert decision.outcome == Outcome.EXCEPTION

    def test_medium_severity_exception_does_not_escalate(self):
        decision = classify(
            make_verdict(verdict="EXCEPTION", exception_type="DUPLICATE", severity="LOW"),
            0.6,
            ["HIGH"],
        )
        assert decision.outcome == Outcome.EXCEPTION


async def run_pipeline(verdicts, settings, fail_kafka=False, error=False, starter=None):
    publisher = FakePublisher(fail=fail_kafka)
    ledger = FakeLedgerClient()
    fallback = FakeFallback()
    pipeline = DecisionPipeline(
        model=FakeModel(verdicts, error=error),
        publisher=publisher,
        ledger=ledger,
        settings=settings,
        workflow_starter=starter,
        fallback=fallback,
    )
    return pipeline, publisher, ledger, fallback


class TestPipeline:
    async def test_match_records_verdict_and_ledger(self, sample_pair_dict, settings, match_verdict):
        pipeline, publisher, ledger, _ = await run_pipeline([match_verdict], settings)
        result = await pipeline.process(Pair(**sample_pair_dict))
        assert result["outcome"] == "verdict"
        assert result["topics"] == [TOPIC_VERDICTS]
        assert publisher.calls[0][0] == TOPIC_VERDICTS
        assert publisher.calls[0][1] == "recon-000001"
        assert ledger.entries[0]["source"] == "model"
        assert ledger.entries[0]["task_id"] == "recon-000001"
        assert ledger.entries[0]["verdict"]["verdict"] == "MATCH"

    async def test_exception_publishes_to_exceptions_topic(
        self, sample_pair_dict, settings
    ):
        verdict = {
            "verdict": "EXCEPTION",
            "exception_type": "AMOUNT_MISMATCH",
            "severity": "HIGH",
            "confidence": 0.9,
            "reason": "amount off by 100",
            "resolution": "escalate",
        }
        pipeline, publisher, _, _ = await run_pipeline([verdict], settings)
        result = await pipeline.process(Pair(**sample_pair_dict))
        assert result["outcome"] == "escalate"
        topics = [c[0] for c in publisher.calls]
        assert topics == [TOPIC_ESCALATIONS]

    async def test_exception_records_verdict_topic(self, sample_pair_dict, settings):
        verdict = {
            "verdict": "EXCEPTION",
            "exception_type": "VALUE_DATE_MISMATCH",
            "severity": "MEDIUM",
            "confidence": 0.85,
            "reason": "date off by one",
            "resolution": "flag-review",
        }
        pipeline, publisher, _, _ = await run_pipeline([verdict], settings)
        result = await pipeline.process(Pair(**sample_pair_dict))
        assert result["outcome"] == "exception"
        topics = [c[0] for c in publisher.calls]
        assert TOPIC_VERDICTS in topics and TOPIC_EXCEPTIONS in topics

    async def test_low_confidence_escalates_and_starts_workflow(
        self, sample_pair_dict, settings, match_verdict
    ):
        verdict = {**match_verdict, "confidence": 0.4}
        starter = FakeWorkflowStarter()
        pipeline, publisher, ledger, _ = await run_pipeline([verdict], settings, starter=starter)
        result = await pipeline.process(Pair(**sample_pair_dict))
        assert result["outcome"] == "escalate"
        assert publisher.calls[0][0] == TOPIC_ESCALATIONS
        assert starter.started[0][0]["task_id"] == "recon-000001"
        assert starter.started[0][1]["confidence"] == 0.4
        assert ledger.entries[0]["source"] == "model"

    async def test_kafka_failure_falls_back_to_ledger(self, sample_pair_dict, settings, match_verdict):
        pipeline, publisher, _, fallback = await run_pipeline(
            [match_verdict], settings, fail_kafka=True
        )
        result = await pipeline.process(Pair(**sample_pair_dict))
        assert result["kafka_published"] is False
        assert fallback.records[0][0] == "recon-000001"
        assert fallback.records[0][1] == TOPIC_VERDICTS

    async def test_model_output_error_escalates(self, sample_pair_dict, settings):
        pipeline, publisher, _, _ = await run_pipeline([], settings, error=True)
        result = await pipeline.process(Pair(**sample_pair_dict))
        assert result["outcome"] == "escalate"
        assert result["verdict"]["verdict"] == "ESCALATE"
        assert result["verdict"]["resolution"] == "flag-review"
        assert publisher.calls[0][0] == TOPIC_ESCALATIONS
