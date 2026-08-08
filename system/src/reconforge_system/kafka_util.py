"""Kafka topic constants and resilient producer/consumer helpers (kafka-python)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Protocol

from kafka import KafkaConsumer, KafkaProducer

from reconforge_system.contracts import LedgerEntry

logger = logging.getLogger(__name__)

TOPIC_RAW_PAIRS = "recon.raw-pairs"
TOPIC_VERDICTS = "recon.verdicts"
TOPIC_EXCEPTIONS = "recon.exceptions"
TOPIC_ESCALATIONS = "recon.escalations"
TOPIC_CADENCE_EVENTS = "recon.cadence-events"

ALL_TOPICS = [
    TOPIC_RAW_PAIRS,
    TOPIC_VERDICTS,
    TOPIC_EXCEPTIONS,
    TOPIC_ESCALATIONS,
    TOPIC_CADENCE_EVENTS,
]


class Publisher(Protocol):
    def publish(
        self, topic: str, key: str, payload: dict[str, Any], retries: int = 3, backoff_s: float = 0.5
    ) -> bool: ...


def make_producer(broker: str, client_id: str = "reconforge") -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=broker,
        client_id=client_id,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: str(k).encode("utf-8"),
        acks="all",
        retries=5,
        request_timeout_ms=10000,
        linger_ms=10,
    )


def make_consumer(broker: str, group_id: str, topics: list[str]) -> KafkaConsumer:
    return KafkaConsumer(
        *topics,
        bootstrap_servers=broker,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        key_deserializer=lambda b: b.decode("utf-8") if b else None,
    )


def publish_json(
    producer: Publisher,
    topic: str,
    key: str,
    payload: dict[str, Any],
    retries: int = 3,
    backoff_s: float = 0.5,
) -> bool:
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            producer.publish(topic=topic, key=key, payload=payload)
            return True
        except Exception as exc:  # noqa: BLE001 — kafka-python raises a family of errors
            last_exc = exc
            if attempt < max(1, retries) - 1:
                time.sleep(backoff_s * (2**attempt))
    logger.warning("kafka publish failed for %s/%s after %d tries: %s", topic, key, retries, last_exc)
    return False


class KafkaPublisherAdapter:
    """Adapts the blocking kafka-python producer to the async event loop."""

    def __init__(self, producer: KafkaProducer):
        self._producer = producer

    def publish(
        self, topic: str, key: str, payload: dict[str, Any], retries: int = 3, backoff_s: float = 0.5
    ) -> bool:
        return publish_json(self._producer, topic, key, payload, retries=retries, backoff_s=backoff_s)

    def close(self) -> None:
        self._producer.close(timeout=5)


class DropToLedgerFallback:
    """Records a 'kafka-unavailable' audit entry in the ledger when publishing fails."""

    def __init__(self, ledger_url: str):
        self.ledger_url = ledger_url

    def record_fallback(self, key: str, topic: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        import httpx

        entry = LedgerEntry(
            task_id=key,
            event_id=uuid.uuid4(),
            pair=None,
            verdict=None,
            source="system",
        ).model_dump(mode="json")
        entry["verdict"] = {
            "verdict": "ESCALATE",
            "exception_type": "FIELD_CORRUPTION",
            "severity": "LOW",
            "confidence": 0.0,
            "reason": "kafka unavailable",
            "resolution": "flag-review",
        }
        entry["pair"] = None
        entry["fallback_topic"] = topic
        entry["fallback_payload"] = payload
        try:
            resp = httpx.post(f"{self.ledger_url}/entries", json=entry, timeout=5)
            if resp.status_code in (200, 201, 409):
                return entry
            logger.warning("ledger fallback write failed: status=%s", resp.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ledger fallback write failed: %s", exc)
        return None


def publish_or_fallback(
    publisher: Publisher,
    topic: str,
    key: str,
    payload: dict[str, Any],
    fallback: DropToLedgerFallback | None,
    retries: int = 3,
    backoff_s: float = 0.5,
) -> tuple[bool, dict[str, Any] | None]:
    if publisher.publish(topic, key, payload, retries=retries, backoff_s=backoff_s):
        return True, None
    if fallback is not None:
        return False, fallback.record_fallback(key, topic, payload)
    return False, None


async def publish_or_fallback_async(
    publisher: Publisher,
    topic: str,
    key: str,
    payload: dict[str, Any],
    fallback: DropToLedgerFallback | None,
    retries: int = 3,
    backoff_s: float = 0.5,
) -> tuple[bool, dict[str, Any] | None]:
    return await asyncio.to_thread(
        publish_or_fallback, publisher, topic, key, payload, fallback, retries, backoff_s
    )
