"""Client for the local MLX model service (OpenAI-compatible, base_url from env)."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from reconforge_system.contracts import Pair, Verdict

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a bank back-office reconciliation analyst. Given a ledger message and a "
    "bank statement record, decide whether they reconcile. Return strict JSON matching "
    "the schema: {\"verdict\": \"MATCH|EXCEPTION|ESCALATE\", \"exception_type\": "
    "\"AMOUNT_MISMATCH|FX_CONVERSION_ERROR|BENEFICIARY_MISMATCH|COUNTERPARTY_MISMATCH|"
    "VALUE_DATE_MISMATCH|MISSING_MESSAGE|DUPLICATE|FIELD_CORRUPTION|PARTIAL_MATCH|null\", "
    "\"severity\": \"LOW|MEDIUM|HIGH\", \"confidence\": 0.0, \"reason\": \"<10 words\", "
    "\"resolution\": \"auto-adjust|escalate|reject|rebook|flag-review\"}. "
    "Set exception_type to null when verdict is MATCH. Never include text outside the JSON."
)


class ModelOutputError(RuntimeError):
    pass


class ModelServiceClient:
    def __init__(self, base_url: str, model: str):
        self._client = AsyncOpenAI(base_url=base_url, api_key="reconforge-local", timeout=60)
        self._model = model

    async def complete_verdict(self, pair: Pair) -> Verdict:
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(pair.model_dump(mode="json"), indent=2)},
            ],
            temperature=0.0,
        )
        raw = (completion.choices[0].message.content or "").strip()
        return self._parse_verdict(raw)

    @staticmethod
    def _parse_verdict(raw: str) -> Verdict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            start, end = cleaned.index("{"), cleaned.rindex("}")
            data: dict[str, Any] = json.loads(cleaned[start : end + 1])
        except (ValueError, json.JSONDecodeError) as exc:
            raise ModelOutputError(f"model returned non-JSON output: {raw[:200]!r}") from exc
        try:
            return Verdict(**data)
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError family
            raise ModelOutputError(f"model returned invalid verdict: {exc}") from exc
