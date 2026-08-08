from __future__ import annotations

import datetime
from typing import Any

from reconforge_system.contracts import Verdict
from reconforge_system.services.db import EntryRow, ReviewRow


class FakePublisher:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail = fail

    def publish(
        self, topic: str, key: str, payload: dict[str, Any], retries: int = 3, backoff_s: float = 0.5
    ) -> bool:
        self.calls.append((topic, key, payload))
        return not self.fail


class FakeModel:
    def __init__(self, verdicts: list[dict[str, Any]], error: bool = False):
        self.verdicts = list(verdicts)
        self.error = error

    async def complete_verdict(self, pair) -> Verdict:
        if self.error:
            from reconforge_system.model_client import ModelOutputError

            raise ModelOutputError("model output unparseable")
        return Verdict(**self.verdicts.pop(0)) if self.verdicts else None


class FakeLedgerClient:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def record_entry(self, entry) -> None:
        self.entries.append(entry.model_dump(mode="json"))


class FakeWorkflowStarter:
    def __init__(self, started: str | None = "decision-recon-000001") -> None:
        self.started: list[tuple[dict, dict]] = []
        self.workflow_id = started

    async def start(self, pair: dict, provisional: dict) -> str | None:
        self.started.append((pair, provisional))
        return self.workflow_id


class FakeFallback:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict]] = []

    def record_fallback(self, key: str, topic: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.records.append((key, topic, payload))
        return {"task_id": key, "verdict": None}


class MemoryStore:
    """In-memory Store implementation for unit tests (mirrors the Postgres SQL semantics)."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.reviews: dict[str, dict[str, Any]] = {}
        self._tick = 0

    async def apply_migrations(self) -> list[str]:
        return ["001_init"]

    def _now(self) -> str:
        self._tick += 1
        return (
            datetime.datetime(2026, 8, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)
            + datetime.timedelta(seconds=self._tick)
        ).isoformat()

    async def upsert_entry(self, entry: dict[str, Any]) -> tuple[EntryRow, bool]:
        task_id = entry["task_id"]
        if task_id in self.entries:
            return (await self.get_entry(task_id)), False  # type: ignore[return-value]
        row = {
            "task_id": task_id,
            "event_id": str(entry["event_id"]),
            "pair": entry.get("pair"),
            "verdict": entry.get("verdict"),
            "source": entry["source"],
            "created_at": self._now(),
        }
        self.entries[task_id] = row
        return (await self.get_entry(task_id)), True  # type: ignore[return-value]

    async def get_entry(self, task_id: str) -> EntryRow | None:
        row = self.entries.get(task_id)
        if row is None:
            return None
        return EntryRow(**row)

    async def entry_stats(self, window_hours: int = 168) -> dict[str, Any]:
        distribution: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        total = 0
        for row in self.entries.values():
            verdict = row.get("verdict")
            if not verdict or row["source"] == "system":
                continue
            severity = verdict.get("severity", "LOW")
            by_severity[severity] = by_severity.get(severity, 0) + 1
            if verdict.get("verdict") == "EXCEPTION":
                exception_type = verdict.get("exception_type", "NONE")
                distribution[exception_type] = distribution.get(exception_type, 0) + 1
                total += 1
        return {
            "window_hours": int(window_hours),
            "total": total,
            "distribution": distribution,
            "by_severity": by_severity,
        }

    async def upsert_review(self, review: dict[str, Any]) -> ReviewRow:
        task_id = review["task_id"]
        row = {
            "task_id": task_id,
            "pair": review.get("pair"),
            "provisional": review.get("provisional"),
            "status": "pending",
            "decision": None,
            "note": None,
            "final_verdict": None,
            "created_at": self._now(),
            "resolved_at": None,
        }
        self.reviews[task_id] = row
        return await self.get_review(task_id)  # type: ignore[return-value]

    async def get_review(self, task_id: str) -> ReviewRow | None:
        row = self.reviews.get(task_id)
        if row is None:
            return None
        return ReviewRow(**row)

    async def pending_reviews(self, limit: int = 100) -> list[ReviewRow]:
        rows = [r for r in self.reviews.values() if r["status"] == "pending"]
        rows.sort(key=lambda r: r["created_at"])
        return [ReviewRow(**r) for r in rows[:limit]]

    async def resolve_review(
        self, task_id: str, decision: str, note: str, final_verdict: dict | None
    ) -> ReviewRow | None:
        row = self.reviews.get(task_id)
        if row is None or row["status"] != "pending":
            return None
        row["status"] = "resolved"
        row["decision"] = decision
        row["note"] = note
        row["final_verdict"] = final_verdict
        row["resolved_at"] = self._now()
        return ReviewRow(**row)

    async def mark_review_timed_out(self, task_id: str) -> ReviewRow | None:
        row = self.reviews.get(task_id)
        if row is None or row["status"] != "pending":
            return None
        row["status"] = "timed-out"
        row["resolved_at"] = self._now()
        return ReviewRow(**row)

    async def healthcheck(self) -> bool:
        return True
