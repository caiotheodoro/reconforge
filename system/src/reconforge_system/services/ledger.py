"""Ledger service :9103 — single writer to Postgres audit trail (recon_entries, recon_reviews)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Query

from reconforge_system.config import Settings, load_settings
from reconforge_system.contracts import LedgerEntry
from reconforge_system.services.db import LedgerStore, Pool

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, store: LedgerStore | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.store is None:
            pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=1, max_size=5)
            app.state.store = LedgerStore(pool)
            try:
                applied = await app.state.store.apply_migrations()
                if applied:
                    logger.info("applied migrations: %s", applied)
            except Exception:
                await pool.close()
                raise
            app.state.pool = pool
        yield
        if hasattr(app.state, "pool"):
            await app.state.pool.close()

    app = FastAPI(title="reconforge-ledger", lifespan=lifespan)
    app.state.store = store

    @app.get("/health")
    async def health() -> dict[str, Any]:
        ok = await app.state.store.healthcheck()
        if not ok:
            raise HTTPException(status_code=503, detail="database unreachable")
        return {"status": "ok", "service": "ledger"}

    @app.post("/entries", status_code=201)
    async def post_entry(entry: LedgerEntry) -> dict[str, Any]:
        data = entry.model_dump(mode="json")
        row, created = await app.state.store.upsert_entry(data)
        if not created:
            return {
                "entry": row.__dict__,
                "duplicate": True,
                "message": "task_id already recorded; existing entry returned",
            }
        return {"entry": row.__dict__, "duplicate": False}

    @app.get("/entries/{task_id}")
    async def get_entry(task_id: str) -> dict[str, Any]:
        row = await app.state.store.get_entry(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no ledger entry for task")
        return {"entry": row.__dict__}

    @app.get("/entries-stats")
    async def entry_stats(
        window_hours: int = Query(default=168, ge=1, le=24 * 90)
    ) -> dict[str, Any]:
        return await app.state.store.entry_stats(window_hours)

    @app.post("/reviews", status_code=201)
    async def post_review(review: dict[str, Any]) -> dict[str, Any]:
        if "task_id" not in review:
            raise HTTPException(status_code=422, detail="task_id required")
        row = await app.state.store.upsert_review(review)
        return {"review": row.__dict__}

    @app.get("/reviews/pending")
    async def pending_reviews(limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
        rows = await app.state.store.pending_reviews(limit)
        return {"reviews": [r.__dict__ for r in rows]}

    @app.get("/reviews/{task_id}")
    async def get_review(task_id: str) -> dict[str, Any]:
        row = await app.state.store.get_review(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no review for task")
        return {"review": row.__dict__}

    @app.patch("/reviews/{task_id}/resolve")
    async def resolve_review(
        task_id: str, resolution: dict[str, Any]
    ) -> dict[str, Any]:
        decision = resolution.get("decision")
        if decision not in ("APPROVE", "REJECT", "CHANGE"):
            raise HTTPException(status_code=422, detail="decision must be APPROVE|REJECT|CHANGE")
        row = await app.state.store.resolve_review(
            task_id,
            decision,
            str(resolution.get("note", "")),
            resolution.get("final_verdict"),
        )
        if row is None:
            existing = await app.state.store.get_review(task_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="no review for task")
            raise HTTPException(status_code=409, detail="review is not pending")
        return {"review": row.__dict__}

    @app.post("/reviews/{task_id}/timeout")
    async def timeout_review(task_id: str) -> dict[str, Any]:
        row = await app.state.store.mark_review_timed_out(task_id)
        if row is None:
            existing = await app.state.store.get_review(task_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="no review for task")
            raise HTTPException(status_code=409, detail="review is not pending")
        return {"review": row.__dict__}

    return app


app = create_app()


def main() -> None:
    uvicorn.run("reconforge_system.services.ledger:app", host="0.0.0.0", port=9103, log_level="info")


if __name__ == "__main__":
    main()
