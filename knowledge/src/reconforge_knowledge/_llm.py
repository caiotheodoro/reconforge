"""Shared environment + LLM-client helpers.

Secrets are read from the repository ``.env`` only (never hardcoded, never
committed). The DeepSeek API is OpenAI-compatible, so we use the ``openai``
client with a custom ``base_url``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

REPO_ROOT_CANDIDATES = (
    Path.cwd(),
    Path(__file__).resolve().parent.parent.parent.parent.parent,
    Path.home() / "Documents" / "personal" / "reconforge",
)


def _locate_env() -> Optional[Path]:
    for base in REPO_ROOT_CANDIDATES:
        env = base / ".env"
        if env.is_file():
            return env
    return None


def load_env() -> None:
    env_path = _locate_env()
    if env_path is not None:
        load_dotenv(env_path, override=False)


def repo_root() -> Path:
    env_path = _locate_env()
    if env_path is not None:
        return env_path.parent
    return REPO_ROOT_CANDIDATES[0]


def get_model_config() -> Dict[str, str]:
    """Resolve model provider settings (values may be empty)."""
    load_env()
    return {
        "base_url": os.getenv("MODEL_PROVIDER_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("MODEL_PROVIDER_MODEL_ID", "deepseek-v4-flash"),
        "api_key": os.getenv("MODEL_PROVIDER_API_KEY", ""),
    }


def get_neo4j_config() -> Dict[str, str]:
    load_env()
    return {
        "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "auth": os.getenv("NEO4J_AUTH", "neo4j/reconforge_local"),
    }


def llm_available() -> bool:
    """True when a usable API key is configured (no network call)."""
    return bool(get_model_config()["api_key"])


class LLMUnavailable(RuntimeError):
    """Raised when the LLM API is required but not configured."""


_client_cache: Any = None


def get_client() -> Any:
    """Lazily build the OpenAI-compatible client (cached)."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    cfg = get_model_config()
    if not cfg["api_key"]:
        raise LLMUnavailable(
            "MODEL_PROVIDER_API_KEY is not set; run with --offline or set it in .env"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("openai package not installed") from exc

    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    _client_cache = client
    return client


def _is_retryable(exc: BaseException) -> bool:
    import openai

    if isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
        ),
    ):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code >= 500
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def chat_json(system: str, user: str, temperature: float = 0.0) -> Dict[str, Any]:
    """Call the model and parse a JSON object from the reply.

    Robust to code fences and trailing prose. Retries on rate-limit/5xx.
    """
    client = get_client()
    cfg = get_model_config()
    response = client.chat.completions.create(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return _parse_json_object(content)


def _parse_json_object(content: str) -> Dict[str, Any]:
    import json

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[len(text.split("\n")[0]) :].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model reply: {content[:200]!r}")
    return json.loads(text[start : end + 1])
