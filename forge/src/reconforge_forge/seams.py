"""System-facing async seams for the cadence layer.

These are the entrypoints the Temporal workflows in ``system/`` call:
- ``check_latest``   — nightly contamination probe over a dataset vs the
                       published benchmark set
- ``judge_kappa``    — weekly judge recalibration (Cohen's kappa over the
                       golden set, when one exists)
- ``run_pilot``      — per-release benchmark run across seeds

They are thin wrappers over the deterministic sync API so the workflows can
``await`` them directly. Return-key names are pinned by the system contracts
(see ``system/src/reconforge_system/workflows.py``).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from reconforge_forge.benchmark import run_pilot as _run_pilot_sync
from reconforge_forge.contamination import leak_probe
from reconforge_forge.generator import generate_tasks
from reconforge_forge.task import Task

VALIDATION_DIR = Path(__file__).resolve().parents[4] / "docs" / "validation"
DEFAULT_SEEDS = (7, 13, 42)


def cohens_kappa(rater_a: list[str], rater_b: list[str]) -> float:
    """Cohen's kappa for two raters over identical-length categorical lists."""
    if len(rater_a) != len(rater_b) or not rater_a:
        return 0.0
    n = len(rater_a)
    categories = sorted(set(rater_a) | set(rater_b))
    agree = sum(1 for a, b in zip(rater_a, rater_b) if a == b)
    p_o = agree / n
    counts_a = {c: rater_a.count(c) / n for c in categories}
    counts_b = {c: rater_b.count(c) / n for c in categories}
    p_e = sum(counts_a[c] * counts_b[c] for c in categories)
    if p_e == 1.0:
        return 1.0 if p_o == 1.0 else 0.0
    return round((p_o - p_e) / (1.0 - p_e), 4)


def _load_tasks(path: str | Path) -> list[Task]:
    p = Path(path)
    if p.is_dir():
        tasks: list[Task] = []
        for child in sorted(p.glob("*.jsonl")):
            tasks.extend(_load_tasks(child))
        return tasks
    raw = p.read_text(encoding="utf-8")
    if p.suffix == ".jsonl":
        return [Task.from_dict(json.loads(line)) for line in raw.splitlines() if line.strip()]
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("tasks", [data])
    return [Task.from_dict(t) for t in data]


def _latest_benchmark_tasks() -> list[Task]:
    """Reference eval set: the published pilot artifacts, newest seed first."""
    candidates = sorted(
        VALIDATION_DIR.glob("pilot-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    tasks: list[Task] = []
    for p in candidates:
        tasks.extend(_load_tasks(p))
        if len(tasks) >= 200:
            break
    return tasks


async def check_latest(dataset_ref: str) -> dict[str, Any]:
    """Nightly contamination probe: overlap of a live dataset's task
    signatures with the published benchmark set."""
    try:
        dataset = _load_tasks(dataset_ref)
        benchmark = _latest_benchmark_tasks()
        if not dataset or not benchmark:
            return {
                "contaminated": False,
                "matches": 0,
                "overlap": 0.0,
                "dataset_ref": dataset_ref,
                "source": "forge",
                "note": "empty dataset or no benchmark artifacts",
            }
        result = leak_probe(benchmark, dataset)
        return {
            "contaminated": bool(result["fired"]),
            "matches": int(result["overlap"] * len(dataset)),
            "overlap": result["overlap"],
            "dataset_ref": dataset_ref,
            "source": "forge",
        }
    except Exception as exc:  # noqa: BLE001 — fail open to the stub in system
        return {"contaminated": False, "matches": 0, "dataset_ref": dataset_ref, "source": "error", "error": str(exc)}


async def judge_kappa(golden_path: str | None = None) -> dict[str, Any]:
    """Weekly judge recalibration: Cohen's kappa between the judge and the
    golden set's authoritative labels, when a golden file exists.

    Golden format: JSONL of ``{"label": str, "judge": str}`` records.
    """
    if golden_path is None:
        candidates = sorted(
            VALIDATION_DIR.glob("golden-*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        golden_path = str(candidates[0]) if candidates else None
    if golden_path is None:
        return {"kappa": None, "golden_size": 0, "source": "forge", "note": "no golden set published yet"}
    records = _load_golden(golden_path)
    if not records:
        return {"kappa": None, "golden_size": 0, "source": "forge", "note": "empty golden set"}
    kappa = cohens_kappa([r["label"] for r in records], [r["judge"] for r in records])
    agreement = round(sum(1 for r in records if r["label"] == r["judge"]) / len(records), 4)
    return {
        "kappa": kappa,
        "agreement": agreement,
        "golden_size": len(records),
        "golden_path": golden_path,
        "source": "forge",
    }


def _load_golden(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


async def run_pilot(seeds: list[int] | tuple[int, ...] = DEFAULT_SEEDS, n_tasks: int = 400) -> dict[str, Any]:
    """Per-release benchmark: generate + pilot per seed, aggregate results."""
    results: dict[str, Any] = {}
    for seed in seeds:
        tasks = generate_tasks(n_tasks=n_tasks, seed=seed)
        results[str(seed)] = _run_pilot_sync(tasks, seed, out_dir=VALIDATION_DIR)
    return {
        "seeds": list(seeds),
        "n_tasks": n_tasks,
        "results": results,
        "oracle_agreement_min": min(r["oracle_agreement"] for r in results.values()),
        "source": "forge",
    }


if __name__ == "__main__":  # pragma: no cover — manual smoke
    async def _main() -> None:
        print(json.dumps(await check_latest("nope"), indent=2))
        print(json.dumps(await judge_kappa(), indent=2))
        pilot = await run_pilot(seeds=[7], n_tasks=100)
        print(json.dumps({k: pilot[k] for k in ("seeds", "oracle_agreement_min", "source")}, indent=2))

    asyncio.run(_main())
