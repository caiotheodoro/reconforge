"""Temporal workflows + activities for ReconForge (task queue "reconforge-main").

Durable-HITL pattern: DecisionWorkflow persists an open-review state via an
activity, then blocks on the `review-resolution` signal with a timeout; the hitl
service resolves via the Temporal signal. Cadence workflows (contamination,
recalibration, benchmark, drift-retrain) publish CadenceEvents to
recon.cadence-events. All external effects are activities (deterministic core).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from reconforge_system.drift import exception_drift

logger = logging.getLogger(__name__)

HITL_SIGNAL = "review-resolution"
HITL_WAIT_SIGNAL = "requires-review"


def apply_review_decision(provisional: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    decision = resolution.get("decision")
    if decision == "APPROVE":
        return provisional
    if decision == "CHANGE":
        final = resolution.get("final_verdict")
        if isinstance(final, dict) and final.get("verdict") in ("MATCH", "EXCEPTION", "ESCALATE"):
            return final
        return provisional
    if decision == "REJECT":
        return {
            **provisional,
            "verdict": "MATCH",
            "exception_type": None,
            "resolution": "reject",
            "reason": "human rejected exception",
        }
    return provisional


# ---------------------------------------------------------------- activities

@activity.defn
async def open_review(pair: dict[str, Any], provisional: dict[str, Any]) -> dict[str, Any]:
    import httpx

    from reconforge_system.config import load_settings

    settings = load_settings()
    resp = await httpx.AsyncClient(timeout=10).post(
        f"{settings.ledger_url}/reviews",
        json={"task_id": pair["task_id"], "pair": pair, "provisional": provisional},
    )
    resp.raise_for_status()
    return {"opened": True, "task_id": pair["task_id"], "status": resp.status_code}


@activity.defn
async def record_review_timeout(task_id: str) -> dict[str, Any]:
    import httpx

    from reconforge_system.config import load_settings

    settings = load_settings()
    resp = await httpx.AsyncClient(timeout=10).post(f"{settings.ledger_url}/reviews/{task_id}/timeout")
    resp.raise_for_status()
    return {"task_id": task_id, "status": resp.status_code}


@activity.defn
async def record_final_verdict(
    pair: dict[str, Any],
    final: dict[str, Any],
    review_state: str,
    note: str,
    source: str,
) -> dict[str, Any]:
    import httpx

    from reconforge_system.config import load_settings
    from reconforge_system.kafka_util import (
        DropToLedgerFallback,
        TOPIC_VERDICTS,
        KafkaPublisherAdapter,
        make_producer,
        publish_or_fallback_async,
    )

    settings = load_settings()
    async with httpx.AsyncClient(base_url=settings.ledger_url, timeout=10) as client:
        entry = {
            "task_id": pair["task_id"],
            "event_id": str(uuid.uuid4()),
            "pair": pair,
            "verdict": final,
            "source": source,
        }
        resp = await client.post("/entries", json=entry)
        resp.raise_for_status()
    publisher = KafkaPublisherAdapter(make_producer(settings.kafka_broker, client_id="reconforge-decision"))
    try:
        await publish_or_fallback_async(
            publisher,
            TOPIC_VERDICTS,
            pair["task_id"],
            final,
            DropToLedgerFallback(settings.ledger_url),
            retries=settings.kafka_retries,
            backoff_s=settings.kafka_retry_backoff_s,
        )
    finally:
        publisher.close()
    return {"task_id": pair["task_id"], "source": source, "review_state": review_state}


@activity.defn
async def fetch_ledger_stats(window_hours: int) -> dict[str, Any]:
    import httpx

    from reconforge_system.config import load_settings

    settings = load_settings()
    resp = await httpx.AsyncClient(base_url=settings.ledger_url, timeout=15).get(
        "/entries-stats", params={"window_hours": int(window_hours)}
    )
    resp.raise_for_status()
    return resp.json()


@activity.defn
async def publish_cadence_event(event: dict[str, Any]) -> dict[str, Any]:
    import datetime

    from reconforge_system.config import load_settings
    from reconforge_system.kafka_util import (
        DropToLedgerFallback,
        TOPIC_CADENCE_EVENTS,
        KafkaPublisherAdapter,
        make_producer,
        publish_or_fallback_async,
    )

    settings = load_settings()
    stamped = {
        "type": event["type"],
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "payload": event.get("payload", {}),
    }
    publisher = None
    try:
        publisher = KafkaPublisherAdapter(make_producer(settings.kafka_broker, client_id="reconforge-cadence"))
        ok, fallback = await publish_or_fallback_async(
            publisher,
            TOPIC_CADENCE_EVENTS,
            f"{event['type']}-{event.get('at', 'now')}",
            stamped,
            DropToLedgerFallback(settings.ledger_url),
            retries=settings.kafka_retries,
            backoff_s=settings.kafka_retry_backoff_s,
        )
        return {"published": ok, "ledger_fallback": fallback is not None, "event": stamped}
    finally:
        if publisher is not None:
            publisher.close()


@activity.defn
async def check_contamination(dataset_ref: str) -> dict[str, Any]:
    try:
        from reconforge_forge.contamination import check_latest  # type: ignore[import-not-found]

        return await check_latest(dataset_ref=dataset_ref)
    except Exception as exc:  # noqa: BLE001 — forge not installed or not yet implemented
        logger.info("forge contamination check unavailable: %s", exc)
        return {"contaminated": False, "matches": 0, "source": "stub", "dataset_ref": dataset_ref}


@activity.defn
async def recompute_kappa() -> dict[str, Any]:
    try:
        from reconforge_forge.eval import judge_kappa  # type: ignore[import-not-found]

        return await judge_kappa()
    except Exception as exc:  # noqa: BLE001
        logger.info("judge kappa recompute unavailable: %s", exc)
        return {"kappa": None, "golden_size": 0, "source": "stub"}


@activity.defn
async def run_forge_pilot(seeds: list[int]) -> dict[str, Any]:
    try:
        from reconforge_forge.benchmark import run_pilot  # type: ignore[import-not-found]

        return await run_pilot(seeds=seeds)
    except Exception as exc:  # noqa: BLE001
        logger.info("forge pilot unavailable: %s", exc)
        return {"seeds": seeds, "results": None, "source": "stub"}


@activity.defn
async def trigger_retrain(payload: dict[str, Any]) -> dict[str, Any]:
    logger.warning("retrain hook is a stub — external trigger not implemented yet")
    return {"triggered": False, "hook": "external", "payload_keys": sorted(payload.keys())}


# ---------------------------------------------------------------- workflows

@workflow.defn
class DecisionWorkflow:
    """Durable HITL: open a review, wait for human resolution, finalize.

    The `requires-review` effect is persisted by the open_review activity (the
    hitl queue in the ledger); the workflow then blocks on the
    `review-resolution` signal for up to review_timeout_hours and completes with
    the final verdict regardless of outcome (deterministic completion).
    """

    def __init__(self) -> None:
        self._resolution: dict[str, Any] | None = None

    @workflow.run
    async def run(self, pair: dict[str, Any], provisional: dict[str, Any], review_timeout_hours: float = 24.0) -> dict[str, Any]:
        timeout = timedelta(hours=float(review_timeout_hours))
        await workflow.execute_activity(
            open_review,
            args=[pair, provisional],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        try:
            await workflow.wait_condition(lambda: self._resolution is not None, timeout=timeout)
            resolved = True
        except asyncio.TimeoutError:
            resolved = False
        if resolved:
            final = apply_review_decision(provisional, self._resolution)
            state, note, source = "resolved", str(self._resolution.get("note", "")), "human"
        else:
            final = {**provisional, "review_state": "timed-out"}
            state, note, source = "timed-out", "HITL review timed out", "system"
            await workflow.execute_activity(
                record_review_timeout,
                args=[pair["task_id"]],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        await workflow.execute_activity(
            record_final_verdict,
            args=[pair, final, state, note, source],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return {
            "task_id": pair["task_id"],
            "review_state": state,
            "final_verdict": final,
            "note": note,
            "source": source,
        }

    @workflow.signal(name=HITL_SIGNAL)
    async def review_resolution(self, resolution: dict[str, Any]) -> None:
        self._resolution = resolution


@workflow.defn
class ContaminationProbeWorkflow:
    """Nightly: forge contamination check of the latest dataset vs benchmark."""

    @workflow.run
    async def run(self, dataset_ref: str = "latest") -> dict[str, Any]:
        result = await workflow.execute_activity(
            check_contamination,
            args=[dataset_ref],
            start_to_close_timeout=timedelta(minutes=5),
            result_type=dict,
        )
        contaminated = bool(result.get("contaminated"))
        if contaminated:
            await workflow.execute_activity(
                publish_cadence_event,
                args=[{
                    "type": "contamination-alert",
                    "payload": {
                        "dataset_ref": dataset_ref,
                        "matches": result.get("matches", 0),
                        "details": result.get("details", {}),
                        "source": result.get("source", "stub"),
                    },
                }],
                start_to_close_timeout=timedelta(seconds=60),
            )
        return {"contaminated": contaminated, "source": result.get("source", "stub")}


@workflow.defn
class JudgeRecalibrationWorkflow:
    """Weekly: recompute judge kappa over the golden set, publish the result."""

    @workflow.run
    async def run(self) -> dict[str, Any]:
        result = await workflow.execute_activity(
            recompute_kappa,
            start_to_close_timeout=timedelta(minutes=5),
            result_type=dict,
        )
        await workflow.execute_activity(
            publish_cadence_event,
            args=[{
                "type": "recalibration-complete",
                "payload": {
                    "kappa": result.get("kappa"),
                    "golden_size": result.get("golden_size", 0),
                    "source": result.get("source", "stub"),
                },
            }],
            start_to_close_timeout=timedelta(seconds=60),
        )
        return result


@workflow.defn
class BenchmarkWorkflow:
    """Per-release: forge pilot on fixed seeds, publish benchmark results."""

    @workflow.run
    async def run(self, seeds: list[int] | None = None) -> dict[str, Any]:
        seeds = list(seeds or [7, 13, 42])
        results = await workflow.execute_activity(
            run_forge_pilot,
            args=[seeds],
            start_to_close_timeout=timedelta(hours=1),
            result_type=dict,
        )
        await workflow.execute_activity(
            publish_cadence_event,
            args=[{
                "type": "benchmark-complete",
                "payload": {
                    "seeds": seeds,
                    "results": results.get("results"),
                    "source": results.get("source", "stub"),
                },
            }],
            start_to_close_timeout=timedelta(seconds=60),
        )
        return results


@workflow.defn
class DriftRetrainWorkflow:
    """Cadence heart: PSI on exception-type distribution vs baseline; fire retrain."""

    @workflow.run
    async def run(
        self,
        baseline: dict[str, float] | None = None,
        threshold: float = 0.10,
        window_hours: int = 168,
    ) -> dict[str, Any]:
        stats = await workflow.execute_activity(
            fetch_ledger_stats,
            args=[int(window_hours)],
            start_to_close_timeout=timedelta(seconds=60),
            result_type=dict,
        )
        report = exception_drift(stats.get("distribution", {}), baseline or {}, float(threshold))
        if report.fired:
            payload = {
                "psi": report.psi,
                "threshold": report.threshold,
                "detail": report.detail,
                "window_hours": int(window_hours),
                "distribution": stats.get("distribution", {}),
            }
            await workflow.execute_activity(
                publish_cadence_event,
                args=[{"type": "retrain-triggered", "payload": payload}],
                start_to_close_timeout=timedelta(seconds=60),
            )
            await workflow.execute_activity(
                trigger_retrain,
                args=[payload],
                start_to_close_timeout=timedelta(seconds=60),
            )
        return {
            "fired": report.fired,
            "psi": report.psi,
            "threshold": report.threshold,
            "window_hours": int(window_hours),
        }


ALL_WORKFLOWS = [
    DecisionWorkflow,
    ContaminationProbeWorkflow,
    JudgeRecalibrationWorkflow,
    BenchmarkWorkflow,
    DriftRetrainWorkflow,
]

ALL_ACTIVITIES = [
    open_review,
    record_review_timeout,
    record_final_verdict,
    fetch_ledger_stats,
    publish_cadence_event,
    check_contamination,
    recompute_kappa,
    run_forge_pilot,
    trigger_retrain,
]
