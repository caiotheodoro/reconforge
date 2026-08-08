"""Decision service :9102 — consumes recon.raw-pairs, calls the model, routes verdicts.

Routing (config-driven):
  - verdict ESCALATE, or severity in DECISION_ESCALATE_SEVERITIES, or
    confidence < DECISION_CONFIDENCE_THRESHOLD  -> recon.escalations + durable HITL workflow
  - else -> recon.verdicts (and recon.exceptions when verdict is EXCEPTION)
Every outcome is recorded to the ledger (source=model) for auditability.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI, HTTPException
from temporalio.client import Client

from reconforge_system.config import Settings, load_settings
from reconforge_system.contracts import Escalation, LedgerEntry, Pair, Verdict
from reconforge_system.decision_core import Outcome, classify
from reconforge_system.kafka_util import (
    DropToLedgerFallback,
    Publisher,
    TOPIC_ESCALATIONS,
    TOPIC_EXCEPTIONS,
    TOPIC_RAW_PAIRS,
    TOPIC_VERDICTS,
    make_consumer,
    make_producer,
    publish_or_fallback_async,
)
from reconforge_system.model_client import ModelOutputError, ModelServiceClient
from reconforge_system.temporal_util import start_decision_workflow

logger = logging.getLogger(__name__)


class VerdictProvider(Protocol):
    async def complete_verdict(self, pair: Pair) -> Verdict: ...


class LedgerClient:
    def __init__(self, ledger_url: str):
        import httpx

        self._url = ledger_url
        self._client = httpx.AsyncClient(base_url=ledger_url, timeout=10)

    async def record_entry(self, entry: LedgerEntry) -> None:
        resp = await self._client.post("/entries", json=entry.model_dump(mode="json"))
        if resp.status_code not in (200, 201, 409):
            raise RuntimeError(f"ledger write failed: {resp.status_code} {resp.text[:200]}")


class WorkflowStarter(Protocol):
    async def start(self, pair: dict, provisional: dict) -> str | None: ...


class TemporalWorkflowStarter:
    def __init__(self, settings: Settings, client: Client | None = None):
        self._settings = settings
        self._client = client

    async def start(self, pair: dict, provisional: dict) -> str | None:
        if self._client is None:
            if not self._settings.temporal_configured:
                logger.info("temporal not configured; skipping durable HITL workflow start")
                return None
            self._client = await make_client(self._settings)
        return await start_decision_workflow(
            self._client,
            pair,
            provisional,
            self._settings.temporal_task_queue,
            self._settings.review_timeout_hours,
        )


class DecisionPipeline:
    def __init__(
        self,
        model: VerdictProvider,
        publisher: Publisher,
        ledger: LedgerClient,
        settings: Settings,
        workflow_starter: WorkflowStarter | None = None,
        fallback: DropToLedgerFallback | None = None,
    ):
        self._model = model
        self._publisher = publisher
        self._ledger = ledger
        self._settings = settings
        self._workflow_starter = workflow_starter
        self._fallback = fallback or DropToLedgerFallback(settings.ledger_url)

    async def process(self, pair: Pair, event_id: uuid.UUID | None = None) -> dict[str, Any]:
        event_id = event_id or uuid.uuid4()
        try:
            verdict = await self._model.complete_verdict(pair)
        except ModelOutputError as exc:
            verdict = Verdict(
                verdict="ESCALATE",
                exception_type=None,
                severity="LOW",
                confidence=0.0,
                reason=str(exc)[:40],
                resolution="flag-review",
            )
        decision = classify(
            verdict,
            self._settings.decision_confidence_threshold,
            self._settings.escalate_severities,
        )
        entry = LedgerEntry(
            task_id=pair.task_id,
            event_id=event_id,
            pair=pair,
            verdict=verdict,
            source="model",
        )
        await self._ledger.record_entry(entry)

        result: dict[str, Any] = {
            "task_id": pair.task_id,
            "event_id": str(event_id),
            "verdict": verdict.model_dump(mode="json"),
            "outcome": decision.outcome.value,
        }

        if decision.outcome == Outcome.ESCALATE:
            escalation = Escalation(
                task_id=pair.task_id,
                event_id=event_id,
                pair=pair,
                provisional_verdict=verdict,
                reason=decision.reason,
            )
            ok, fallback_entry = await publish_or_fallback_async(
                self._publisher,
                TOPIC_ESCALATIONS,
                pair.task_id,
                escalation.model_dump(mode="json"),
                self._fallback,
                retries=self._settings.kafka_retries,
                backoff_s=self._settings.kafka_retry_backoff_s,
            )
            result["topic"] = TOPIC_ESCALATIONS
            result["kafka_published"] = ok
            result["ledger_fallback"] = fallback_entry is not None
            if self._workflow_starter is not None:
                workflow_id = await self._workflow_starter.start(
                    pair.model_dump(mode="json"), verdict.model_dump(mode="json")
                )
                result["workflow_id"] = workflow_id
            return result

        topics = [TOPIC_VERDICTS]
        if verdict.verdict == "EXCEPTION":
            topics.append(TOPIC_EXCEPTIONS)
        published = True
        for topic in topics:
            ok, fallback_entry = await publish_or_fallback_async(
                self._publisher,
                topic,
                pair.task_id,
                verdict.model_dump(mode="json"),
                self._fallback,
                retries=self._settings.kafka_retries,
                backoff_s=self._settings.kafka_retry_backoff_s,
            )
            published = published and ok
            if not ok and fallback_entry is None:
                published = False
        result["topics"] = topics
        result["kafka_published"] = published
        return result

    async def run_consumer(self) -> None:
        consumer = make_consumer(
            self._settings.kafka_broker,
            self._settings.decision_consumer_group,
            [TOPIC_RAW_PAIRS],
        )
        logger.info("decision consumer listening on %s", TOPIC_RAW_PAIRS)
        while True:
            messages = await asyncio.to_thread(consumer.poll, timeout_ms=1000)
            for _, records in messages.items():
                for record in records:
                    try:
                        pair = Pair(**record.value)
                        await self.process(pair)
                        consumer.commit()
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("failed to process pair %s: %s", record.key, exc)


def create_app(
    settings: Settings | None = None,
    pipeline: DecisionPipeline | None = None,
    startup: Any | None = None,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = None
        if startup is not None:
            task = asyncio.create_task(startup())
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title="reconforge-decision", lifespan=lifespan)
    app.state.pipeline = pipeline

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "decision"}

    @app.post("/decide")
    async def decide(pair: Pair) -> dict[str, Any]:
        if app.state.pipeline is None:
            raise HTTPException(status_code=503, detail="pipeline not initialized")
        return await app.state.pipeline.process(pair)

    return app


def _build_pipeline(settings: Settings) -> DecisionPipeline:
    from reconforge_system.kafka_util import KafkaPublisherAdapter

    publisher = KafkaPublisherAdapter(make_producer(settings.kafka_broker, client_id="reconforge-decision"))
    return DecisionPipeline(
        model=ModelServiceClient(settings.model_service_url, settings.model_service_model),
        publisher=publisher,
        ledger=LedgerClient(settings.ledger_url),
        settings=settings,
        workflow_starter=TemporalWorkflowStarter(settings),
        fallback=DropToLedgerFallback(settings.ledger_url),
    )


def run_decision() -> None:
    settings = load_settings()
    pipeline = _build_pipeline(settings)
    app = create_app(
        settings=settings,
        pipeline=pipeline,
        startup=pipeline.run_consumer if settings.decision_consume else None,
    )
    uvicorn.run(app, host="0.0.0.0", port=9102, log_level="info")


def main() -> None:
    run_decision()


if __name__ == "__main__":
    main()
