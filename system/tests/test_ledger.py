from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from reconforge_system.services.ledger import create_app


def make_entry(task_id: str = "recon-000001", source: str = "model", verdict: dict | None = None):
    return {
        "task_id": task_id,
        "event_id": str(uuid.uuid4()),
        "pair": None,
        "verdict": verdict
        or {
            "verdict": "MATCH",
            "exception_type": None,
            "severity": "LOW",
            "confidence": 0.99,
            "reason": "reconciles",
            "resolution": "auto-adjust",
        },
        "source": source,
    }


def make_exception_entry(task_id: str, exception_type: str, severity: str = "MEDIUM"):
    return make_entry(
        task_id=task_id,
        verdict={
            "verdict": "EXCEPTION",
            "exception_type": exception_type,
            "severity": severity,
            "confidence": 0.8,
            "reason": "exception",
            "resolution": "flag-review",
        },
    )


class TestStore:
    async def test_upsert_idempotent_by_task_id(self, memory_store):
        first, created1 = await memory_store.upsert_entry(make_entry("t-1"))
        second, created2 = await memory_store.upsert_entry(make_entry("t-1"))
        assert created1 is True
        assert created2 is False
        assert first.task_id == second.task_id
        assert first.event_id == second.event_id

    async def test_get_entry_missing(self, memory_store):
        assert await memory_store.get_entry("nope") is None

    async def test_stats_distribution(self, memory_store):
        await memory_store.upsert_entry(make_exception_entry("t-1", "AMOUNT_MISMATCH"))
        await memory_store.upsert_entry(make_exception_entry("t-2", "AMOUNT_MISMATCH"))
        await memory_store.upsert_entry(make_exception_entry("t-3", "DUPLICATE", "LOW"))
        await memory_store.upsert_entry(make_entry("t-4"))
        stats = await memory_store.entry_stats()
        assert stats["distribution"] == {"AMOUNT_MISMATCH": 2, "DUPLICATE": 1}

    async def test_review_lifecycle(self, memory_store):
        await memory_store.upsert_review({"task_id": "t-1", "pair": {}, "provisional": {}})
        assert len(await memory_store.pending_reviews()) == 1
        resolved = await memory_store.resolve_review("t-1", "APPROVE", "looks good", None)
        assert resolved.status == "resolved"
        assert await memory_store.resolve_review("t-1", "REJECT", "", None) is None
        assert await memory_store.pending_reviews() == []
        assert await memory_store.mark_review_timed_out("t-1") is None


class TestHttp:
    def test_post_and_get_entry(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        body = make_entry("recon-http-1")
        resp = client.post("/entries", json=body)
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["duplicate"] is False
        got = client.get("/entries/recon-http-1")
        assert got.status_code == 200
        assert got.json()["entry"]["task_id"] == "recon-http-1"

    def test_duplicate_post_returns_existing(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        body = make_entry("recon-http-2")
        client.post("/entries", json=body)
        dup = client.post("/entries", json=body)
        assert dup.status_code == 201
        assert dup.json()["duplicate"] is True

    def test_get_missing_entry_404(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        assert client.get("/entries/ghost").status_code == 404

    def test_invalid_source_rejected(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        body = make_entry("recon-http-3", source="kafka")
        assert client.post("/entries", json=body).status_code == 422

    def test_reviews_endpoints(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        client.post("/reviews", json={"task_id": "r-1", "pair": {"a": 1}, "provisional": {"v": "MATCH"}})
        queue = client.get("/reviews/pending")
        assert queue.json()["reviews"][0]["task_id"] == "r-1"
        resolved = client.patch("/reviews/r-1/resolve", json={"decision": "APPROVE", "note": "ok"})
        assert resolved.json()["review"]["status"] == "resolved"
        conflict = client.patch("/reviews/r-1/resolve", json={"decision": "REJECT"})
        assert conflict.status_code == 409
        assert client.patch("/reviews/r-9/resolve", json={"decision": "REJECT"}).status_code == 404
        assert client.patch("/reviews/r-1/resolve", json={"decision": "MAYBE"}).status_code == 422

    def test_entries_stats_endpoint(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        client.post("/entries", json=make_exception_entry("s-1", "FX_CONVERSION_ERROR"))
        stats = client.get("/entries-stats")
        assert stats.json()["distribution"] == {"FX_CONVERSION_ERROR": 1}

    def test_health(self, memory_store):
        client = TestClient(create_app(store=memory_store))
        assert client.get("/health").status_code == 200


@pytest.mark.integration
async def test_postgres_migration_and_idempotency():
    """Real postgres smoke test (docker run postgres:16)."""
    import asyncpg

    from reconforge_system.config import load_settings
    from reconforge_system.services.db import LedgerStore

    settings = load_settings()
    pool = await asyncpg.create_pool(
        settings.postgres_dsn, min_size=1, max_size=1, timeout=5
    )
    try:
        store = LedgerStore(pool)
        applied = await store.apply_migrations()
        assert "001_init" in applied
        entry = make_entry("pg-smoke-1")
        _, created1 = await store.upsert_entry(entry)
        _, created2 = await store.upsert_entry(entry)
        assert created1 is True
        assert created2 is False
        got = await store.get_entry("pg-smoke-1")
        assert got.event_id == str(entry["event_id"])
        await store.upsert_review({"task_id": "pg-smoke-2", "pair": None, "provisional": None})
        assert len(await store.pending_reviews()) == 1
    finally:
        await pool.close()
