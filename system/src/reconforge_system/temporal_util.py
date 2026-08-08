"""Temporal Cloud client helpers (TLS + API key auth). Never log the key."""

from __future__ import annotations

import logging
from typing import Any

from temporalio.client import Client

from reconforge_system.config import Settings
from reconforge_system.workflows import DecisionWorkflow

logger = logging.getLogger(__name__)

WORKFLOW_ID_PREFIX = "decision-"


async def make_client(settings: Settings) -> Client:
    if not settings.temporal_configured:
        raise RuntimeError(
            "Temporal not configured: set TEMPORAL_HOST, TEMPORAL_NAMESPACE, TEMPORAL_CLOUD_API_KEY"
        )
    return await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
        api_key=settings.temporal_cloud_api_key,
        tls=True,
    )


async def start_decision_workflow(
    client: Client,
    pair: dict[str, Any],
    provisional: dict[str, Any],
    task_queue: str,
    review_timeout_hours: int,
) -> str | None:
    workflow_id = f"{WORKFLOW_ID_PREFIX}{pair['task_id']}"
    try:
        await client.start_workflow(
            DecisionWorkflow.run,
            args=[pair, provisional, float(review_timeout_hours)],
            id=workflow_id,
            task_queue=task_queue,
        )
        return workflow_id
    except Exception as exc:  # noqa: BLE001 — AlreadyStarted is idempotent here
        if "already started" in str(exc).lower() or "AlreadyStarted" in type(exc).__name__:
            logger.info("workflow %s already running; not restarted", workflow_id)
            return workflow_id
        logger.warning("failed to start decision workflow %s: %s", workflow_id, exc)
        return None


async def signal_decision_workflow(
    client: Client,
    task_id: str,
    resolution: dict[str, Any],
) -> bool:
    handle = client.get_workflow_handle(f"{WORKFLOW_ID_PREFIX}{task_id}")
    try:
        await handle.signal("review-resolution", resolution)
        return True
    except Exception as exc:  # noqa: BLE001 — workflow may be closed/timed out
        logger.info("signal review-resolution for %s not delivered: %s", task_id, exc)
        return False
