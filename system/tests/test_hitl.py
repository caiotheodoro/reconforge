from __future__ import annotations

from fastapi.testclient import TestClient

from reconforge_system.services.hitl import create_app


class FakeLedgerApi:
    def __init__(self) -> None:
        self.reviews: dict[str, dict] = {
            "recon-1": {
                "task_id": "recon-1",
                "pair": {"task_id": "recon-1", "seed": 1},
                "provisional": {
                    "verdict": "EXCEPTION",
                    "exception_type": "AMOUNT_MISMATCH",
                    "severity": "HIGH",
                    "confidence": 0.55,
                    "reason": "amount differs",
                    "resolution": "escalate",
                },
                "status": "pending",
            }
        }
        self.entries: list[dict] = []
        self.resolutions: list[tuple[str, dict]] = []

    async def get_review(self, task_id: str) -> dict | None:
        return self.reviews.get(task_id)

    async def pending_reviews(self) -> list[dict]:
        return [r for r in self.reviews.values() if r.get("status") == "pending"]

    async def resolve_review(self, task_id: str, resolution: dict) -> None:
        self.resolutions.append((task_id, resolution))
        self.reviews[task_id]["status"] = "resolved"

    async def record_entry(self, entry: dict) -> None:
        self.entries.append(entry)


class TestHitl:
    def test_queue_lists_pending(self):
        client = TestClient(create_app(ledger=FakeLedgerApi(), signal_fn=lambda t, r: _ok(t, r)))
        resp = client.get("/queue")
        assert resp.status_code == 200
        assert resp.json()["queue_size"] == 1

    def test_approve_resolves_and_records_human_entry(self):
        ledger = FakeLedgerApi()
        signals: list[tuple[str, dict]] = []

        async def signal_fn(task_id: str, resolution: dict) -> bool:
            signals.append((task_id, resolution))
            return True

        client = TestClient(create_app(ledger=ledger, signal_fn=signal_fn))
        resp = client.post("/review/recon-1", json={"task_id": "recon-1", "decision": "APPROVE", "note": "ok"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "human"
        assert body["workflow_signalled"] is True
        assert body["final_verdict"]["exception_type"] == "AMOUNT_MISMATCH"
        assert ledger.entries[0]["source"] == "human"
        assert signals[0][0] == "recon-1"
        assert signals[0][1]["decision"] == "APPROVE"

    def test_change_overrides_verdict(self):
        ledger = FakeLedgerApi()
        client = TestClient(create_app(ledger=ledger, signal_fn=lambda t, r: _ok(t, r)))
        final = {
            "verdict": "EXCEPTION",
            "exception_type": "FX_CONVERSION_ERROR",
            "severity": "HIGH",
            "confidence": 0.9,
            "reason": "rate wrong",
            "resolution": "rebook",
        }
        resp = client.post(
            "/review/recon-1",
            json={"task_id": "recon-1", "decision": "CHANGE", "note": "fx", "final_verdict": final},
        )
        assert resp.json()["final_verdict"]["exception_type"] == "FX_CONVERSION_ERROR"
        assert ledger.entries[0]["verdict"]["exception_type"] == "FX_CONVERSION_ERROR"

    def test_reject_unknown_task_404(self):
        ledger = FakeLedgerApi()
        client = TestClient(create_app(ledger=ledger, signal_fn=lambda t, r: _ok(t, r)))
        resp = client.post("/review/ghost", json={"task_id": "ghost", "decision": "APPROVE"})
        assert resp.status_code == 404

    def test_task_id_mismatch_422(self):
        client = TestClient(create_app(ledger=FakeLedgerApi(), signal_fn=lambda t, r: _ok(t, r)))
        resp = client.post("/review/recon-1", json={"task_id": "other", "decision": "APPROVE"})
        assert resp.status_code == 422


async def _ok(task_id: str, resolution: dict) -> bool:
    return True
