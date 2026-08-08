"""Ingest service :9101 — POST /pairs validates a Pair and publishes it to recon.raw-pairs."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from reconforge_system.config import Settings, load_settings
from reconforge_system.contracts import Pair
from reconforge_system.kafka_util import (
    DropToLedgerFallback,
    KafkaPublisherAdapter,
    TOPIC_RAW_PAIRS,
    make_producer,
    publish_or_fallback_async,
)

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    publisher: KafkaPublisherAdapter | None = None,
    fallback: DropToLedgerFallback | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    fallback = fallback or DropToLedgerFallback(settings.ledger_url)
    _producer_ref: dict[str, KafkaPublisherAdapter | None] = {"producer": publisher}

    def get_publisher() -> KafkaPublisherAdapter:
        if _producer_ref["producer"] is None:
            _producer_ref["producer"] = KafkaPublisherAdapter(
                make_producer(settings.kafka_broker, client_id="reconforge-ingest")
            )
        return _producer_ref["producer"]  # type: ignore[return-value]

    app = FastAPI(title="reconforge-ingest")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ingest"}

    @app.post("/pairs", status_code=202)
    async def ingest_pair(pair: Pair) -> dict[str, Any]:
        event_id = uuid.uuid4()
        payload = pair.model_dump(mode="json")
        payload["event_id"] = str(event_id)
        ok, fallback_entry = await publish_or_fallback_async(
            get_publisher(),
            TOPIC_RAW_PAIRS,
            pair.task_id,
            payload,
            fallback,
            retries=settings.kafka_retries,
            backoff_s=settings.kafka_retry_backoff_s,
        )
        if not ok and fallback_entry is None:
            raise HTTPException(status_code=503, detail="kafka unavailable and ledger fallback failed")
        return {
            "task_id": pair.task_id,
            "event_id": str(event_id),
            "topic": TOPIC_RAW_PAIRS,
            "accepted": True,
            "kafka_published": ok,
            "ledger_fallback": fallback_entry is not None,
        }

    return app


app = create_app()


def main() -> None:
    uvicorn.run("reconforge_system.services.ingest:app", host="0.0.0.0", port=9101, log_level="info")


if __name__ == "__main__":
    main()
