"""Dataset builder: forge tasks -> Qwen chat-format train/val JSONL.

Stratified split by (difficulty decile, exception_type) with per-bin
proportional allocation, deterministic under a fixed seed, and a
contamination guard (task_id + field-level signature overlap must be 0).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .schema import SYSTEM_PROMPT, canonical_verdict_json, render_user_message

DIFFICULTY_BINS = 10  # deciles

DEFAULT_SOURCE = "forge"
FORGE_IMPORTS = [
    ("reconforge_forge", "generate_tasks"),
    ("reconforge_forge.generator", "generate_tasks"),
    ("reconforge_forge.generate", "generate_tasks"),
    ("reconforge_forge.cli", "generate_tasks"),
]

try:  # pragma: no cover - exercised in the smoke run
    from reconforge_forge import generate_tasks as _forge_generate_tasks  # type: ignore

    HAS_FORGE = True
except ImportError:  # pragma: no cover
    _forge_generate_tasks = None
    HAS_FORGE = False


def _as_dict(task: Any) -> dict[str, Any]:
    """Accept forge Task objects or plain dicts (stub emits dicts)."""
    if hasattr(task, "to_dict"):
        return task.to_dict()
    return task


def task_signature(task: dict[str, Any]) -> str:
    """Field-level signature of the pair (for contamination checking)."""
    task = _as_dict(task)

    def _norm(side: dict[str, Any] | None) -> dict[str, Any]:
        if not side:
            return {"missing": True}
        return {k: str(v) for k, v in sorted(side.items()) if k not in ("booked_at",)}

    payload = json.dumps(
        [_norm(task.get("ledger")), _norm(task.get("statement"))],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def stratify_split(
    tasks: list[dict[str, Any]], train_frac: float, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-bin proportional allocation over (difficulty decile, exception_type)."""
    tasks = [_as_dict(t) for t in tasks]
    bins: dict[tuple[int, str | None], list[dict[str, Any]]] = defaultdict(list)
    for t in tasks:
        decile = min(DIFFICULTY_BINS - 1, int(float(t["difficulty"]) * DIFFICULTY_BINS))
        bins[(decile, t["expected"].get("exception_type"))].append(t)

    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for bucket in bins.values():
        rng.shuffle(bucket)
        n = len(bucket)
        n_train = int(round(n * train_frac))
        if n >= 2:
            n_train = max(1, min(n - 1, n_train))
        train.extend(bucket[:n_train])
        val.extend(bucket[n_train:])
    return train, val


def build_datasets(
    tasks: list[dict[str, Any]],
    train_frac: float = 0.8,
    seed: int = 7,
    out_dir: str | Path = "data",
) -> dict[str, Any]:
    """Build train/val JSONL from schema-identical tasks. Returns stats dict.

    Raises ValueError if the train/val task signatures overlap (contamination).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train, val = stratify_split(tasks, train_frac, random.Random(seed))

    train_ids = {t["task_id"] for t in train}
    val_ids = {t["task_id"] for t in val}
    id_overlap = train_ids & val_ids

    train_sigs = {task_signature(t) for t in train}
    val_sigs = {task_signature(t) for t in val}
    sig_overlap = train_sigs & val_sigs
    overlap_frac = len(sig_overlap) / max(len(val_sigs), 1)

    if id_overlap:
        raise ValueError(f"task_id leakage: {len(id_overlap)} ids in both splits")
    if overlap_frac > 0:
        raise ValueError(
            f"contamination guard: {len(sig_overlap)}/{len(val_sigs)} val task "
            f"signatures collide with train (overlap {overlap_frac:.3f} > 0)"
        )

    def _record(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task["task_id"],
            "difficulty": task["difficulty"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_user_message(task)},
                {"role": "assistant", "content": canonical_verdict_json(task["expected"])},
            ],
        }

    def _write(rows: list[dict[str, Any]], name: str) -> None:
        with open(out_dir / name, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")

    train_records = [_record(t) for t in sorted(train, key=lambda t: t["task_id"])]
    val_records = [_record(t) for t in sorted(val, key=lambda t: t["task_id"])]
    _write(train_records, "train.jsonl")
    _write(val_records, "val.jsonl")

    def _dist(rows: list[dict[str, Any]]) -> dict[str, float]:
        counts = Counter(int(float(t["difficulty"]) * DIFFICULTY_BINS) for t in rows)
        return {str(b): round(counts[b] / len(rows), 4) for b in sorted(counts)}

    return {
        "n_tasks": len(tasks),
        "n_train": len(train),
        "n_val": len(val),
        "train_frac": train_frac,
        "seed": seed,
        "id_overlap": len(id_overlap),
        "signature_overlap_frac": overlap_frac,
        "train_difficulty_hist": _dist(train),
        "val_difficulty_hist": _dist(val),
        "train_exception_counts": dict(Counter(t["expected"].get("exception_type") for t in train)),
        "val_exception_counts": dict(Counter(t["expected"].get("exception_type") for t in val)),
        "out_dir": str(out_dir),
    }


def load_tasks(
    path: str | Path | None = None, n: int = 500, seed: int = 7
) -> list[dict[str, Any]]:
    """Load tasks from a JSON/JSONL file, or from forge if installed, or fall
    back to the checked-in stub in tests/fake_forge.py (schema-identical).

    Forge import contract: `generate_tasks(n=..., seed=...)` returning a list
    of task dicts per CONTRACTS.md. Attempts several known entrypoints.
    """
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"tasks file not found: {p}")
        if p.suffix == ".json":
            with open(p) as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "tasks" in data:
                return data["tasks"]
            return data
        with open(p) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    if HAS_FORGE and _forge_generate_tasks is not None:
        return _forge_generate_tasks(n=n, seed=seed)

    import importlib

    for module_name, func_name in FORGE_IMPORTS:
        try:
            mod = importlib.import_module(module_name)
            gen = getattr(mod, func_name)
            tasks = gen(n=n, seed=seed)
            if isinstance(tasks, list) and tasks:
                return tasks
        except (ImportError, AttributeError, TypeError):
            continue

    # Fall back to the local schema-identical stub (smoke + offline dev).
    tests_dir = Path(__file__).resolve().parents[2] / "tests"
    sys.path.insert(0, str(tests_dir))
    from fake_forge import generate_tasks as stub_generate  # type: ignore

    return stub_generate(n=n, seed=seed)


def build_dataset_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build train/val JSONL from forge tasks")
    parser.add_argument("--tasks", type=str, default=None, help="JSON/JSONL of task dicts")
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--train-frac", type=float, default=0.8)
    parser.add_argument("--out-dir", type=str, default="data")
    parser.add_argument(
        "--source",
        choices=["auto", "forge", "stub"],
        default="auto",
        help="Task source: forge package, local stub, or auto (forge first, stub fallback)",
    )
    args = parser.parse_args(argv)

    if args.source == "forge" and not HAS_FORGE:
        print("error: --source forge requested but reconforge_forge is not importable", file=sys.stderr)
        return 2

    tasks: list[dict[str, Any]]
    if args.source == "stub":
        tests_dir = Path(__file__).resolve().parents[2] / "tests"
        sys.path.insert(0, str(tests_dir))
        from fake_forge import generate_tasks as stub_generate  # type: ignore

        tasks = stub_generate(n=args.n, seed=args.seed)
    else:
        tasks = load_tasks(path=args.tasks, n=args.n, seed=args.seed)

    stats = build_datasets(
        tasks, train_frac=args.train_frac, seed=args.seed, out_dir=args.out_dir
    )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(build_dataset_cli())
