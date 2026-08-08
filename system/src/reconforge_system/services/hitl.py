"""HITL service :9105 — review queue + resolution for escalations.

GET  /queue                  -> pending reviews (proxied from the ledger)
POST /review/{task_id}       -> resolve an escalation (APPROVE/REJECT/CHANGE + note);
                                final verdict is written to the ledger with source="human"
                                and the durable DecisionWorkflow is signaled.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Protocol

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException

from reconforge_system.config import Settings, load_settings
from reconforge_system.contracts import ReviewResolution
from reconforge_system.workflows import apply_review_decision

logger = logging.getLogger(__name__)

SignalFn = Callable[[str, dict[str, Any]], Awaitable[bool]]


class LedgerApi(Protocol):
    async def get_review(self, task_id: str) -> dict[str, Any] | None: ...
    async def pending_reviews(self) -> list[dict[str, Any]]: ...
    async def resolve_review(self, task_id: str, resolution: dict[str, Any]) -> None: ...
    async def record_entry(self, entry: dict[str, Any]) -> None: ...


class HttpLedgerApi:
    def __init__(self, ledger_url: str):
        self._client = httpx.AsyncClient(base_url=ledger_url, timeout=10)

    async def get_review(self, task_id: str) -> dict[str, Any] | None:
        resp = await self._client.get(f"/reviews/{task_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("review")

    async def pending_reviews(self) -> list[dict[str, Any]]:
        resp = await self._client.get("/reviews/pending")
        resp.raise_for_status()
        return resp.json().get("reviews", [])

    async def resolve_review(self, task_id: str, resolution: dict[str, Any]) -> None:
        resp = await self._client.patch(f"/reviews/{task_id}/resolve", json=resolution)
        if resp.status_code == 404:
            raise LookupError(f"no review for task {task_id}")
        if resp.status_code == 409:
            raise LookupError(f"review for task {task_id} is not pending")
        resp.raise_for_status()

    async def record_entry(self, entry: dict[str, Any]) -> None:
        resp = await self._client.post("/entries", json=entry)
        if resp.status_code not in (200, 201, 409):
            raise RuntimeError(f"ledger write failed: {resp.status_code}")


async def _signal_resolution(task_id: str, resolution: dict[str, Any]) -> bool:
    from temporalio.exceptions import WorkflowNotFoundError

    from reconforge_system.temporal_util import make_client, signal_decision_workflow

    settings = load_settings()
    if not settings.temporal_configured:
        logger.info("temporal not configured; durable workflow signal skipped")
        return False
    client = await make_client(settings)
    try:
        return await signal_decision_workflow(client, task_id, resolution)
    except WorkflowNotFoundError:
        return False


def create_app(
    settings: Settings | None = None,
    ledger: LedgerApi | None = None,
    signal_fn: SignalFn | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    _ledger = ledger or HttpLedgerApi(settings.ledger_url)
    _signal = signal_fn or _signal_resolution
    app = FastAPI(title="reconforge-hitl")
    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "hitl"}

    @app.get("/queue")
    async def queue() -> dict[str, Any]:
        reviews = await _ledger.pending_reviews()
        return {"queue_size": len(reviews), "reviews": reviews}

    @app.post("/review/{task_id}")
    async def review(task_id: str, resolution: ReviewResolution) -> dict[str, Any]:
        if task_id != resolution.task_id:
            raise HTTPException(status_code=422, detail="task_id in path and body must match")
        existing = await _ledger.get_review(task_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="no pending review for task")
        provisional = existing.get("provisional") or {}
        final = apply_review_decision(provisional, resolution.model_dump(mode="json"))
        resolution_payload = {
            "decision": resolution.decision,
            "note": resolution.note,
            "final_verdict": final,
        }
        await _ledger.resolve_review(task_id, resolution_payload)
        await _ledger.record_entry(
            {
                "task_id": task_id,
                "event_id": str(uuid.uuid4()),
                "pair": existing.get("pair"),
                "verdict": final,
                "source": "human",
            }
        )
        signalled = await _signal(task_id, resolution_payload)
        return {
            "task_id": task_id,
            "decision": resolution.decision,
            "final_verdict": final,
            "source": "human",
            "workflow_signalled": signalled,
        }

    return app


app = create_app()


def main() -> None:
    uvicorn.run("reconforge_system.services.hitl:app", host="0.0.0.0", port=9105, log_level="info")


if __name__ == "__main__":
    main()
