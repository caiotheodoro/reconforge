"""Cadence worker — Temporal worker for cadence workflows + schedule registration.

Modes:
  worker     : run the worker on "reconforge-main" (cadence workflows + activities)
  schedules  : idempotently register the cadence Schedules with Temporal Cloud
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from reconforge_system.config import Settings, load_settings
from reconforge_system.temporal_util import make_client
from reconforge_system.workflows import ALL_ACTIVITIES, ALL_WORKFLOWS

logger = logging.getLogger(__name__)


async def run_worker(settings: Settings) -> None:
    client: Client = await make_client(settings)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=ALL_WORKFLOWS,
        activities=ALL_ACTIVITIES,
    )
    logger.info("cadence worker listening on %s (namespace %s)", settings.temporal_task_queue, settings.temporal_namespace)
    await worker.run()


def main() -> None:
    import sys

    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    mode = sys.argv[1] if len(sys.argv) > 1 else "worker"
    if mode == "worker":
        asyncio.run(run_worker(settings))
    elif mode == "schedules":
        from reconforge_system.schedule_registry import register_all_schedules

        asyncio.run(register_all_schedules(settings))
    else:
        raise SystemExit(f"unknown mode {mode!r}; expected worker|schedules")


if __name__ == "__main__":
    main()
