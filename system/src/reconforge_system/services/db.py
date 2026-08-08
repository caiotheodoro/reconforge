"""Async Postgres access for the ledger service (single writer to the audit tables)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from reconforge_system.config import Settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Pool(Protocol):
    async def fetchrow(self, query: str, *args: Any) -> Any | None: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class EntryRow:
    task_id: str
    event_id: str
    pair: dict | None
    verdict: dict | None
    source: str
    created_at: str


@dataclass(frozen=True)
class ReviewRow:
    task_id: str
    pair: dict | None
    provisional: dict | None
    status: str
    decision: str | None
    note: str | None
    final_verdict: dict | None
    created_at: str
    resolved_at: str | None


class Store(Protocol):
    async def apply_migrations(self) -> list[str]: ...
    async def upsert_entry(self, entry: dict[str, Any]) -> tuple[EntryRow, bool]: ...
    async def get_entry(self, task_id: str) -> EntryRow | None: ...
    async def entry_stats(self, window_hours: int = 168) -> dict[str, Any]: ...
    async def upsert_review(self, review: dict[str, Any]) -> ReviewRow: ...
    async def get_review(self, task_id: str) -> ReviewRow | None: ...
    async def pending_reviews(self, limit: int = 100) -> list[ReviewRow]: ...
    async def resolve_review(
        self, task_id: str, decision: str, note: str, final_verdict: dict | None
    ) -> ReviewRow | None: ...
    async def mark_review_timed_out(self, task_id: str) -> ReviewRow | None: ...
    async def healthcheck(self) -> bool: ...


class LedgerStore(Store):
    def __init__(self, pool: Pool):
        self._pool = pool

    async def apply_migrations(self) -> list[str]:
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS recon_schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = []
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration.stem
            already = await self._pool.fetchval(
                "SELECT 1 FROM recon_schema_migrations WHERE version = $1", version
            )
            if already:
                continue
            sql = migration.read_text()
            async with self._pool.acquire() as conn:  # type: ignore[attr-defined]
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO recon_schema_migrations (version) VALUES ($1)", version
                    )
            applied.append(version)
        return applied

    async def upsert_entry(self, entry: dict[str, Any]) -> tuple[EntryRow, bool]:
        row = await self._pool.fetchrow(
            """
            INSERT INTO recon_entries (task_id, event_id, pair, verdict, source)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (task_id) DO NOTHING
            RETURNING task_id, event_id, pair, verdict, source, created_at
            """,
            entry["task_id"],
            str(entry["event_id"]),
            json.dumps(entry.get("pair")) if entry.get("pair") else None,
            json.dumps(entry.get("verdict")) if entry.get("verdict") else None,
            entry["source"],
        )
        if row is not None:
            return _entry_row(row), True
        existing = await self.get_entry(entry["task_id"])
        if existing is None:
            raise RuntimeError(f"upsert race for task {entry['task_id']}")
        return existing, False

    async def get_entry(self, task_id: str) -> EntryRow | None:
        row = await self._pool.fetchrow(
            "SELECT task_id, event_id, pair, verdict, source, created_at "
            "FROM recon_entries WHERE task_id = $1",
            task_id,
        )
        return _entry_row(row) if row else None

    async def entry_stats(self, window_hours: int = 168) -> dict[str, Any]:
        rows = await self._pool.fetch(
            """
            SELECT COALESCE(verdict->>'exception_type', 'NONE') AS exception_type,
                   COUNT(*) AS n
            FROM recon_entries
            WHERE verdict IS NOT NULL
              AND source <> 'system'
              AND verdict->>'verdict' = 'EXCEPTION'
              AND created_at >= now() - make_interval(hours => $1)
            GROUP BY 1
            """,
            int(window_hours),
        )
        distribution = {str(r["exception_type"]): int(r["n"]) for r in rows}
        total = sum(distribution.values())
        severity_rows = await self._pool.fetch(
            """
            SELECT verdict->>'severity' AS severity, COUNT(*) AS n
            FROM recon_entries
            WHERE verdict IS NOT NULL
              AND source <> 'system'
              AND created_at >= now() - make_interval(hours => $1)
            GROUP BY 1
            """,
            int(window_hours),
        )
        return {
            "window_hours": int(window_hours),
            "total": total,
            "distribution": distribution,
            "by_severity": {str(r["severity"]): int(r["n"]) for r in severity_rows},
        }

    async def upsert_review(self, review: dict[str, Any]) -> ReviewRow:
        row = await self._pool.fetchrow(
            """
            INSERT INTO recon_reviews (task_id, pair, provisional)
            VALUES ($1, $2, $3)
            ON CONFLICT (task_id) DO UPDATE
            SET pair = EXCLUDED.pair, provisional = EXCLUDED.provisional,
                status = CASE WHEN recon_reviews.status = 'pending' THEN 'pending' ELSE recon_reviews.status END
            RETURNING task_id, pair, provisional, status, decision, note, final_verdict, created_at, resolved_at
            """,
            review["task_id"],
            json.dumps(review.get("pair")) if review.get("pair") else None,
            json.dumps(review.get("provisional")) if review.get("provisional") else None,
        )
        return _review_row(row)

    async def get_review(self, task_id: str) -> ReviewRow | None:
        row = await self._pool.fetchrow(
            "SELECT task_id, pair, provisional, status, decision, note, final_verdict, created_at, resolved_at "
            "FROM recon_reviews WHERE task_id = $1",
            task_id,
        )
        return _review_row(row) if row else None

    async def pending_reviews(self, limit: int = 100) -> list[ReviewRow]:
        rows = await self._pool.fetch(
            "SELECT task_id, pair, provisional, status, decision, note, final_verdict, created_at, resolved_at "
            "FROM recon_reviews WHERE status = 'pending' ORDER BY created_at ASC LIMIT $1",
            int(limit),
        )
        return [_review_row(r) for r in rows]

    async def resolve_review(
        self, task_id: str, decision: str, note: str, final_verdict: dict | None
    ) -> ReviewRow | None:
        row = await self._pool.fetchrow(
            """
            UPDATE recon_reviews
            SET status = 'resolved', decision = $2, note = $3,
                final_verdict = $4, resolved_at = now()
            WHERE task_id = $1 AND status = 'pending'
            RETURNING task_id, pair, provisional, status, decision, note, final_verdict, created_at, resolved_at
            """,
            task_id,
            decision,
            note,
            json.dumps(final_verdict) if final_verdict else None,
        )
        return _review_row(row) if row else None

    async def mark_review_timed_out(self, task_id: str) -> ReviewRow | None:
        row = await self._pool.fetchrow(
            """
            UPDATE recon_reviews
            SET status = 'timed-out', resolved_at = now()
            WHERE task_id = $1 AND status = 'pending'
            RETURNING task_id, pair, provisional, status, decision, note, final_verdict, created_at, resolved_at
            """,
            task_id,
        )
        return _review_row(row) if row else None

    async def healthcheck(self) -> bool:
        try:
            await self._pool.fetchval("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False


def _entry_row(row: Any) -> EntryRow:
    return EntryRow(
        task_id=row["task_id"],
        event_id=str(row["event_id"]),
        pair=json.loads(row["pair"]) if row.get("pair") else None,
        verdict=json.loads(row["verdict"]) if row.get("verdict") else None,
        source=row["source"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
    )


def _review_row(row: Any) -> ReviewRow:
    return ReviewRow(
        task_id=row["task_id"],
        pair=json.loads(row["pair"]) if row.get("pair") else None,
        provisional=json.loads(row["provisional"]) if row.get("provisional") else None,
        status=row["status"],
        decision=row.get("decision"),
        note=row.get("note"),
        final_verdict=json.loads(row["final_verdict"]) if row.get("final_verdict") else None,
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        resolved_at=row["resolved_at"].isoformat() if row.get("resolved_at") else None,
    )
