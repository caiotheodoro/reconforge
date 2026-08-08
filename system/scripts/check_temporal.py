"""Read-only Temporal Cloud connectivity check (describe namespace). Never prints the API key."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import temporalio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reconforge_system.config import load_settings  # noqa: E402
from reconforge_system.temporal_util import make_client  # noqa: E402


async def check() -> None:
    settings = load_settings()
    print(f"host:        {settings.temporal_host}")
    print(f"namespace:   {settings.temporal_namespace}")
    print(f"account:     {settings.temporal_cloud_account_id}")
    print(f"api key:     {'<set>' if settings.temporal_cloud_api_key else '<MISSING>'}")
    print(f"task queue:  {settings.temporal_task_queue}")
    if not settings.temporal_configured:
        print("RESULT: FAIL — temporal env vars not configured")
        return
    client = await make_client(settings)
    req = temporalio.api.workflowservice.v1.DescribeNamespaceRequest(
        namespace=settings.temporal_namespace
    )
    ns = await client.workflow_service.describe_namespace(req)
    print(f"namespace state: {ns.namespace_info.state}")
    print(f"namespace id:    {ns.namespace_info.id}")
    print(f"supports_schedules: {ns.namespace_info.supports_schedules}")
    print("RESULT: OK — Temporal Cloud reachable, namespace describes successfully")


if __name__ == "__main__":
    asyncio.run(check())
