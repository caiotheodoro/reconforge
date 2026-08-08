from __future__ import annotations

from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests that need real infra (postgres/kafka)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_integration = config.getoption("--run-integration")
    if run_integration:
        return
    skip = pytest.mark.skip(reason="integration test; pass --run-integration to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def sample_pair_dict() -> dict[str, Any]:
    return {
        "task_id": "recon-000001",
        "seed": 42,
        "difficulty": 0.7,
        "ledger": {
            "message_type": "MT103",
            "ref": "OUR-REF-001",
            "amount": "1250.00",
            "ccy": "USD",
            "value_date": "2026-08-07",
            "counterparty": "BANK-ACCT-1234",
            "beneficiary": "ACME CORP",
            "fx_rate": None,
            "booked_at": "2026-08-06T14:02:11Z",
        },
        "statement": {
            "message_type": "MT940",
            "ref": "CP-REF-001",
            "amount": "1250.00",
            "ccy": "USD",
            "value_date": "2026-08-07",
            "counterparty": "BANK-ACCT-1234",
            "beneficiary": "ACME CORP",
        },
        "expected": {
            "verdict": "MATCH",
            "exception_type": None,
            "severity": "LOW",
            "explanation": "canonical explanation",
            "resolution": "auto-adjust",
        },
    }


@pytest.fixture
def match_verdict() -> dict[str, Any]:
    return {
        "verdict": "MATCH",
        "exception_type": None,
        "severity": "LOW",
        "confidence": 0.98,
        "reason": "amounts and refs reconcile",
        "resolution": "auto-adjust",
    }


@pytest.fixture
def memory_store():
    from tests.fakes import MemoryStore

    return MemoryStore()


@pytest.fixture
def settings() -> Any:
    from reconforge_system.config import Settings

    return Settings()


@pytest.fixture
async def temporal_env():
    from temporalio.testing import WorkflowEnvironment

    try:
        env = await WorkflowEnvironment.start_local(dev_server_existing_path=_cli_path())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"temporal test server unavailable: {exc}")
    yield env
    await env.shutdown()


def _cli_path() -> str | None:
    import os
    from pathlib import Path

    env_path = os.environ.get("TEMPORAL_CLI_EXISTING_PATH")
    if env_path:
        return env_path
    candidates = [
        Path(os.environ.get("TMPDIR", "/tmp")) / "opencode" / "temporal-cli" / "temporal",
        Path.home() / ".temporal-cli" / "temporal",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None
