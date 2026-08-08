"""Signature-based leak probe — the contamination monitor.

A task's **signature** is the SHA-256 of its canonical sorted
(field, value) pairs over ledger + statement (metadata like task_id/seed/
difficulty/expected excluded — the signature fingerprints the *content* of
the pair, which is what can leak into training data).

The monitor is exact-hash: an eval signature present in the train signature
set means that exact pair content already circulates. ``evaluate_monitor``
runs the ROC study (fire-on-leaked vs false-fire-on-clean across leak
fractions) and publishes ``contamination-roc.json``.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from reconforge_forge.benchmark import LEAK_FRACTIONS
from reconforge_forge.task import Task


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def task_signature(task: Task) -> str:
    """Value-level signature: sorted (field, value) pairs over the pair."""
    pairs: list[tuple[str, Any]] = []
    for side in ("ledger", "statement"):
        rec = getattr(task, side)
        if rec is None:
            continue
        for key in sorted(rec):
            pairs.append((f"{side}.{key}", rec[key]))
    payload = _canonical_json(pairs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def signatures(tasks: list[Task]) -> set[str]:
    return {task_signature(t) for t in tasks}


def leak_probe(train_tasks: list[Task], eval_tasks: list[Task]) -> dict[str, Any]:
    """Fraction of eval signatures already present in the train set.

    ``fired`` is True iff the overlap is non-zero — the monitor's alarm.
    """
    train_sigs = signatures(train_tasks)
    if not eval_tasks:
        return {"overlap": 0.0, "fired": False}
    overlap = sum(1 for t in eval_tasks if task_signature(t) in train_sigs)
    frac = round(overlap / len(eval_tasks), 4)
    return {"overlap": frac, "fired": frac > 0.0}


def evaluate_monitor(
    train_tasks: list[Task],
    eval_clean: list[Task],
    seed: int,
    leak_fractions: tuple[float, ...] = LEAK_FRACTIONS,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """ROC study: for each leak fraction, splice that fraction of eval tasks
    with exact copies drawn from the train set and measure the monitor's
    fire-on-leaked and false-fire-on-clean rates. Deterministic in ``seed``."""
    train_sigs = signatures(train_tasks)
    n_eval = len(eval_clean)
    points: list[dict[str, Any]] = []
    for frac in leak_fractions:
        sub_rng = random.Random(f"{seed}:{frac}")
        k = min(n_eval, max(1, round(n_eval * frac)))
        positions = set(sub_rng.sample(range(n_eval), k))
        sources = sub_rng.sample(train_tasks, k)
        fire_leaked = 0
        false_clean = 0
        src_iter = iter(sources)
        for i, t in enumerate(eval_clean):
            if i in positions:
                leaked_sig = task_signature(next(src_iter))
                if leaked_sig in train_sigs:
                    fire_leaked += 1
            else:
                if task_signature(t) in train_sigs:
                    false_clean += 1
        points.append(
            {
                "leak_fraction": frac,
                "n_leaked": k,
                "n_clean": n_eval - k,
                "fire_on_leaked": round(fire_leaked / max(k, 1), 4),
                "false_fire_on_clean": round(false_clean / max(n_eval - k, 1), 4),
            }
        )

    result: dict[str, Any] = {
        "study": "reconforge-contamination-roc",
        "seed": seed,
        "n_train": len(train_tasks),
        "n_eval_clean": n_eval,
        "signature": "sha256 of sorted (field,value) pairs over ledger+statement",
        "points": points,
        "summary": {
            "fire_on_leaked_min": min(p["fire_on_leaked"] for p in points),
            "false_fire_on_clean_max": max(p["false_fire_on_clean"] for p in points),
        },
    }
    if out_dir is not None:
        path = Path(out_dir) / "contamination-roc.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canonical_json(result) + "\n", encoding="utf-8")
    return result
