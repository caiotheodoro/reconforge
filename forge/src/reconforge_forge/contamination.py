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

# --- Near-duplicate audit (MinHash over character shingles) ---------------
#
# Exact-signature overlap (above) is zero by construction once ``leak_probe``
# fires clean, but train/eval come from the *same generator* under different
# seeds, so a near-duplicate — same template, one field jittered — is the
# real contamination risk exact hashing cannot see. This estimates Jaccard
# similarity between character-shingle sets via MinHash so an 800x3198
# audit stays cheap, and reports both the near-dup count at a threshold and
# a nearest-neighbour similarity histogram.

_MERSENNE_PRIME = (1 << 61) - 1


def _shingles(task: Task, k: int = 5) -> set[str]:
    """Character k-shingles over the same canonical content string used for
    the exact signature (metadata excluded), so a near-dup audit and the
    exact-overlap probe agree on what "content" means."""
    pairs: list[tuple[str, Any]] = []
    for side in ("ledger", "statement"):
        rec = getattr(task, side)
        if rec is None:
            continue
        for key in sorted(rec):
            pairs.append((f"{side}.{key}", rec[key]))
    text = _canonical_json(pairs)
    if len(text) < k:
        return {text}
    return {text[i : i + k] for i in range(len(text) - k + 1)}


def _minhash_perms(num_perm: int, seed: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    return [
        (rng.randrange(1, _MERSENNE_PRIME), rng.randrange(0, _MERSENNE_PRIME))
        for _ in range(num_perm)
    ]


def minhash_signature(
    shingle_set: set[str], perms: list[tuple[int, int]]
) -> tuple[int, ...]:
    if not shingle_set:
        return tuple(_MERSENNE_PRIME for _ in perms)
    hashed = [
        int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "big")
        for s in shingle_set
    ]
    return tuple(
        min((a * x + b) % _MERSENNE_PRIME for x in hashed) for (a, b) in perms
    )


def jaccard_estimate(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
    assert len(sig_a) == len(sig_b)
    return sum(1 for x, y in zip(sig_a, sig_b) if x == y) / len(sig_a)


def near_duplicate_report(
    train_tasks: list[Task],
    eval_tasks: list[Task],
    shingle_size: int = 5,
    num_perm: int = 128,
    threshold: float = 0.8,
    seed: int = 11,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """For each eval task, estimate Jaccard similarity (MinHash) to its
    nearest train task by character-shingle overlap. Reports the near-dup
    count at ``threshold`` and a similarity histogram (0.0-1.0, 0.1-wide
    bins) over the best-match distances.

    This bounds contamination *within this train/eval boundary only* — it
    says nothing about whether a third-party API model saw similar data in
    pretraining.
    """
    perms = _minhash_perms(num_perm, seed)
    train_sigs = [minhash_signature(_shingles(t, shingle_size), perms) for t in train_tasks]

    best_sims: list[float] = []
    near_dup_ids: list[str] = []
    for et in eval_tasks:
        esig = minhash_signature(_shingles(et, shingle_size), perms)
        best = max((jaccard_estimate(esig, tsig) for tsig in train_sigs), default=0.0)
        best_sims.append(round(best, 4))
        if best >= threshold:
            near_dup_ids.append(et.task_id)

    bins = [round(i * 0.1, 1) for i in range(11)]
    histogram = {
        f"[{lo:.1f},{hi:.1f})": sum(1 for s in best_sims if lo <= s < hi)
        for lo, hi in zip(bins[:-1], bins[1:])
    }
    histogram[f"[1.0,1.0]"] = sum(1 for s in best_sims if s >= 1.0)

    result: dict[str, Any] = {
        "study": "reconforge-near-duplicate-audit",
        "method": "minhash",
        "shingle_size": shingle_size,
        "num_perm": num_perm,
        "threshold": threshold,
        "seed": seed,
        "n_train": len(train_tasks),
        "n_eval": len(eval_tasks),
        "near_duplicate_count": len(near_dup_ids),
        "near_duplicate_rate": round(len(near_dup_ids) / max(len(eval_tasks), 1), 4),
        "near_duplicate_task_ids": near_dup_ids,
        "nearest_neighbour_similarity_histogram": histogram,
        "note": (
            "Bounds contamination within this dataset's train/eval boundary "
            "only. Says nothing about third-party API model pretraining "
            "exposure to similar data."
        ),
    }
    if out_dir is not None:
        path = Path(out_dir) / "near-duplicate-audit.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canonical_json(result) + "\n", encoding="utf-8")
    return result
