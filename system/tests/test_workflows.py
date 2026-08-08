from __future__ import annotations

import uuid

from temporalio import activity
from temporalio.worker import Worker

from reconforge_system.drift import DriftReport, exception_drift, psi
from reconforge_system.workflows import (
    BenchmarkWorkflow,
    ContaminationProbeWorkflow,
    DecisionWorkflow,
    DriftRetrainWorkflow,
    JudgeRecalibrationWorkflow,
    apply_review_decision,
)


def _queue() -> str:
    return f"tq-{uuid.uuid4().hex[:10]}"


PROVISIONAL = {
    "verdict": "EXCEPTION",
    "exception_type": "AMOUNT_MISMATCH",
    "severity": "HIGH",
    "confidence": 0.55,
    "reason": "amount differs",
    "resolution": "escalate",
}

PAIR = {
    "task_id": "recon-000001",
    "seed": 42,
    "difficulty": 0.7,
    "ledger": {"message_type": "MT103", "ref": "OUR-REF-001", "amount": "1250.00"},
    "statement": {"message_type": "MT940", "ref": "CP-REF-001", "amount": "1250.00"},
    "expected": {"verdict": "MATCH", "exception_type": None, "severity": "LOW", "explanation": "x", "resolution": "auto-adjust"},
}


class TestDriftPure:
    def test_psi_identical_distributions_zero(self):
        dist = {"AMOUNT_MISMATCH": 5, "DUPLICATE": 5}
        assert psi(dist, dict(dist)) == 0.0

    def test_psi_shift_detected(self):
        base = {"AMOUNT_MISMATCH": 50, "DUPLICATE": 50}
        current = {"AMOUNT_MISMATCH": 2, "DUPLICATE": 98}
        assert psi(current, base) > 1.0

    def test_drift_fires_above_threshold(self):
        report = exception_drift(
            {"AMOUNT_MISMATCH": 10, "DUPLICATE": 90},
            {"AMOUNT_MISMATCH": 50, "DUPLICATE": 50},
            0.10,
        )
        assert isinstance(report, DriftReport)
        assert report.fired is True
        assert report.psi > 0.10

    def test_drift_not_fired_below_threshold(self):
        report = exception_drift({"AMOUNT_MISMATCH": 51, "DUPLICATE": 49}, {"AMOUNT_MISMATCH": 50, "DUPLICATE": 50}, 0.10)
        assert report.fired is False

    def test_empty_distribution_does_not_fire(self):
        report = exception_drift({}, {"AMOUNT_MISMATCH": 1}, 0.10)
        assert report.fired is False


class TestReviewDecision:
    def test_approve_keeps_provisional(self):
        assert apply_review_decision(PROVISIONAL, {"decision": "APPROVE"}) == PROVISIONAL

    def test_reject_overrides_to_match(self):
        final = apply_review_decision(PROVISIONAL, {"decision": "REJECT", "note": "verified manually"})
        assert final["verdict"] == "MATCH"
        assert final["exception_type"] is None
        assert final["resolution"] == "reject"

    def test_change_uses_provided_verdict(self):
        new = {**PROVISIONAL, "exception_type": "FX_CONVERSION_ERROR", "resolution": "rebook"}
        final = apply_review_decision(PROVISIONAL, {"decision": "CHANGE", "final_verdict": new})
        assert final["exception_type"] == "FX_CONVERSION_ERROR"

    def test_change_with_invalid_verdict_falls_back_to_provisional(self):
        final = apply_review_decision(PROVISIONAL, {"decision": "CHANGE", "final_verdict": {"verdict": "NOPE"}})
        assert final == PROVISIONAL

    def test_unknown_decision_passthrough(self):
        assert apply_review_decision(PROVISIONAL, {"decision": "MAYBE"}) == PROVISIONAL


class _ActivitySpy:
    def __init__(self) -> None:
        self.opens: list[tuple] = []
        self.finals: list[tuple] = []
        self.timeouts: list[str] = []
        self.cadence_events: list[dict] = []


def _spy_activities(spy: _ActivitySpy):
    @activity.defn(name="open_review")
    async def fake_open_review(pair, provisional):
        spy.opens.append((pair, provisional))
        return {"opened": True, "task_id": pair["task_id"]}

    @activity.defn(name="record_final_verdict")
    async def fake_record_final(pair, final, state, note, source):
        spy.finals.append((pair, final, state, note, source))
        return {"task_id": pair["task_id"]}

    @activity.defn(name="record_review_timeout")
    async def fake_record_timeout(task_id):
        spy.timeouts.append(task_id)
        return {"task_id": task_id}

    @activity.defn(name="publish_cadence_event")
    async def fake_publish_event(event):
        spy.cadence_events.append(event)
        return {"published": True}

    @activity.defn(name="fetch_ledger_stats")
    async def fake_fetch_stats(window_hours):
        return {"distribution": {"AMOUNT_MISMATCH": 90, "DUPLICATE": 10}, "total": 100}

    @activity.defn(name="check_contamination")
    async def fake_check_contamination(dataset_ref):
        return {"contaminated": False, "source": "stub", "dataset_ref": dataset_ref}

    @activity.defn(name="recompute_kappa")
    async def fake_kappa():
        return {"kappa": 0.85, "golden_size": 50, "source": "stub"}

    @activity.defn(name="run_forge_pilot")
    async def fake_pilot(seeds):
        return {"seeds": seeds, "results": {"recall": 0.9}, "source": "stub"}

    @activity.defn(name="trigger_retrain")
    async def fake_retrain(payload):
        return {"triggered": False}

    return [
        fake_open_review,
        fake_record_final,
        fake_record_timeout,
        fake_publish_event,
        fake_fetch_stats,
        fake_check_contamination,
        fake_kappa,
        fake_pilot,
        fake_retrain,
    ]


class TestDecisionWorkflowEnv:
    async def test_signal_path(self, temporal_env):
        spy = _ActivitySpy()
        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[DecisionWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                handle = await temporal_env.client.start_workflow(
                    DecisionWorkflow.run,
                    args=[PAIR, PROVISIONAL, 24.0],
                    id="wf-signal-1",
                    task_queue=queue,
                )
                await handle.signal("review-resolution", {"decision": "APPROVE", "note": "human ok"})
                result = await handle.result()
                assert result["review_state"] == "resolved"
                assert result["final_verdict"] == PROVISIONAL
                assert result["source"] == "human"
                assert spy.opens and spy.finals
                final_call = spy.finals[0]
                assert final_call[3] == "human ok"

    async def test_timeout_path(self, temporal_env):
        spy = _ActivitySpy()
        env = temporal_env
        async with env:
            queue = _queue()
            worker = Worker(
                env.client,
                task_queue=queue,
                workflows=[DecisionWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                handle = await env.client.start_workflow(
                    DecisionWorkflow.run,
                    args=[PAIR, PROVISIONAL, 0.0002],
                    id="wf-timeout-1",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result["review_state"] == "timed-out"
                assert result["final_verdict"]["review_state"] == "timed-out"
                assert result["source"] == "system"
                assert spy.timeouts == ["recon-000001"]

    async def test_no_review_without_signal_before_timeout(self, temporal_env):
        spy = _ActivitySpy()
        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[DecisionWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                handle = await temporal_env.client.start_workflow(
                    DecisionWorkflow.run,
                    args=[PAIR, PROVISIONAL, 0.0002],
                    id="wf-timeout-2",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result["review_state"] == "timed-out"


class TestCadenceWorkflowsEnv:
    async def test_contamination_probe_no_fire(self, temporal_env):
        spy = _ActivitySpy()
        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[ContaminationProbeWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                handle = await temporal_env.client.start_workflow(
                    ContaminationProbeWorkflow.run,
                    args=["latest"],
                    id="wf-contam-1",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result == {"contaminated": False, "source": "stub"}
                assert spy.cadence_events == []

    async def test_contamination_probe_fires_alert(self, temporal_env):
        spy = _ActivitySpy()

        @activity.defn(name="check_contamination")
        async def fake_check_contamination(dataset_ref):
            return {"contaminated": True, "matches": 3, "source": "stub", "dataset_ref": dataset_ref}

        @activity.defn(name="publish_cadence_event")
        async def fake_publish_event(event):
            spy.cadence_events.append(event)
            return {"published": True}

        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[ContaminationProbeWorkflow],
                activities=[fake_check_contamination, fake_publish_event],
            )
            async with worker:
                handle = await temporal_env.client.start_workflow(
                    ContaminationProbeWorkflow.run,
                    args=["latest"],
                    id="wf-contam-2",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result["contaminated"] is True
                assert spy.cadence_events[0]["type"] == "contamination-alert"
                assert spy.cadence_events[0]["payload"]["matches"] == 3

    async def test_drift_workflow_fires_retrain(self, temporal_env):
        spy = _ActivitySpy()
        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[DriftRetrainWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                baseline = {"AMOUNT_MISMATCH": 50.0, "DUPLICATE": 50.0}
                handle = await temporal_env.client.start_workflow(
                    DriftRetrainWorkflow.run,
                    args=[baseline, 0.10, 168],
                    id="wf-drift-1",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result["fired"] is True
                assert result["psi"] > 0.10
                assert spy.cadence_events[0]["type"] == "retrain-triggered"

    async def test_recalibration_publishes_kappa(self, temporal_env):
        spy = _ActivitySpy()
        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[JudgeRecalibrationWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                handle = await temporal_env.client.start_workflow(
                    JudgeRecalibrationWorkflow.run,
                    id="wf-kappa-1",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result["kappa"] == 0.85
                assert spy.cadence_events[0]["type"] == "recalibration-complete"

    async def test_benchmark_publishes_results(self, temporal_env):
        spy = _ActivitySpy()
        async with temporal_env:
            queue = _queue()
            worker = Worker(
                temporal_env.client,
                task_queue=queue,
                workflows=[BenchmarkWorkflow],
                activities=_spy_activities(spy),
            )
            async with worker:
                handle = await temporal_env.client.start_workflow(
                    BenchmarkWorkflow.run,
                    args=[[7, 13, 42]],
                    id="wf-bench-1",
                    task_queue=queue,
                )
                result = await handle.result()
                assert result["results"] == {"recall": 0.9}
                assert spy.cadence_events[0]["type"] == "benchmark-complete"
                assert spy.cadence_events[0]["payload"]["seeds"] == [7, 13, 42]
