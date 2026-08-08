"""Cadence schedule definitions + idempotent registration with Temporal ScheduleClient.

Schedules:
  recon-contamination-probe   nightly  (default 03:00)   ContaminationProbeWorkflow
  recon-judge-recalibration   weekly   (default Mon 04:00) JudgeRecalibrationWorkflow
  recon-benchmark             per-release (on-demand trigger, no cron)
  recon-drift-check           hourly                     DriftRetrainWorkflow
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.service import RPCError

from reconforge_system.config import Settings, load_settings
from reconforge_system.workflows import (
    BenchmarkWorkflow,
    ContaminationProbeWorkflow,
    DriftRetrainWorkflow,
    JudgeRecalibrationWorkflow,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleDef:
    schedule_id: str
    workflow_fn: Any
    args: list[Any]
    cron: str | None
    note: str

    @property
    def workflow_name(self) -> str:
        return getattr(self.workflow_fn, "__name__", str(self.workflow_fn))

    @property
    def paused(self) -> bool:
        return self.cron is None


def build_schedule_defs(settings: Settings) -> list[ScheduleDef]:
    return [
        ScheduleDef(
            schedule_id="recon-contamination-probe",
            workflow_fn=ContaminationProbeWorkflow.run,
            args=["latest"],
            cron=settings.contamination_cron,
            note="nightly contamination probe of the latest dataset vs benchmark",
        ),
        ScheduleDef(
            schedule_id="recon-judge-recalibration",
            workflow_fn=JudgeRecalibrationWorkflow.run,
            args=[],
            cron=settings.recalibration_cron,
            note="weekly judge kappa recomputation over the golden set",
        ),
        ScheduleDef(
            schedule_id="recon-benchmark",
            workflow_fn=BenchmarkWorkflow.run,
            args=[[7, 13, 42]],
            cron=None,
            note="per-release benchmark on fixed seeds (on-demand trigger)",
        ),
        ScheduleDef(
            schedule_id="recon-drift-check",
            workflow_fn=DriftRetrainWorkflow.run,
            args=[
                settings.drift_baseline,
                settings.drift_psi_threshold,
                settings.drift_stats_window_hours,
            ],
            cron=settings.drift_cron,
            note="hourly PSI drift check on exception-type distribution vs baseline",
        ),
    ]


def _to_schedule(defn: ScheduleDef) -> Schedule:
    action = ScheduleActionStartWorkflow(
        defn.workflow_fn,
        args=defn.args,
        id=f"cadence-{defn.schedule_id}",
        task_queue="reconforge-main",
    )
    spec = ScheduleSpec(cron_expressions=[defn.cron] if defn.cron else None)
    return Schedule(
        spec=spec,
        action=action,
        state=ScheduleState(paused=defn.paused, note=defn.note),
    )


async def upsert_schedule(client: Client, defn: ScheduleDef) -> bool:
    schedule = _to_schedule(defn)
    try:
        await client.create_schedule(defn.schedule_id, schedule)
        logger.info("created schedule %s (%s)", defn.schedule_id, defn.note)
        return True
    except RPCError as exc:
        if exc.status.name == "ALREADY_EXISTS":
            handle = client.get_schedule_handle(defn.schedule_id)
            await handle.update(schedule)
            logger.info("updated existing schedule %s (%s)", defn.schedule_id, defn.note)
            return True
        raise


async def register_all_schedules(settings: Settings | None = None) -> list[str]:
    settings = settings or load_settings()
    client: Client = await make_client(settings)
    registered: list[str] = []
    for defn in build_schedule_defs(settings):
        await upsert_schedule(client, defn)
        registered.append(defn.schedule_id)
    logger.info("schedules registered: %s", ", ".join(registered))
    return registered


async def trigger_benchmark(client: Client, seeds: list[int] | None = None) -> str:
    handle = client.get_schedule_handle("recon-benchmark")
    await handle.trigger(overlap_policy="SKIP")
    return handle.schedule_id


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(register_all_schedules())


if __name__ == "__main__":
    main()
