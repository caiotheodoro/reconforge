"""Gate service :9104 — thin HTTP seam around the knowledge ground-truth gate.

Wraps `reconforge_knowledge` when importable; otherwise returns a SILENT stub
verdict marked with "stub": true. The knowledge package plugs in later without
touching this contract.
"""

from __future__ import annotations

import importlib
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from reconforge_system.config import load_settings
from reconforge_system.contracts import Pair, Verdict


class GroundRequest(BaseModel):
    task_id: str
    pair: Pair
    provisional_verdict: Verdict


def _load_knowledge_gate() -> Any | None:
    try:
        module = importlib.import_module("reconforge_knowledge.gate")
        return getattr(module, "ground", None)
    except ImportError:
        return None


def create_app() -> FastAPI:
    load_settings()
    app = FastAPI(title="reconforge-gate")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "gate"}

    @app.post("/ground")
    async def ground(request: GroundRequest) -> dict[str, Any]:
        gate = _load_knowledge_gate()
        if gate is None:
            return {
                "task_id": request.task_id,
                "stub": True,
                "gated": False,
                "verdict": None,
                "reason": "knowledge gate not installed; pair passed through silently",
            }
        result = await gate(pair=request.pair, provisional=request.provisional_verdict)
        result = result if isinstance(result, dict) else {"verdict": result}
        result.setdefault("stub", False)
        result.setdefault("gated", True)
        result["task_id"] = request.task_id
        return result

    return app


app = create_app()


def main() -> None:
    uvicorn.run("reconforge_system.services.gate:app", host="0.0.0.0", port=9104, log_level="info")


if __name__ == "__main__":
    main()
