"""Pilot benchmark — verifier-as-oracle gate + scoring metrics.

- ``run_pilot``: computes the oracle agreement between the canonical
  verifier and the generator's ``expected`` (the A4 gate; must be 100%),
  the verifier's severity-weighted recall (1.0 by construction), and
  publishes ``pilot-<seed>.json`` to ``docs/validation/``.
- ``score_verdicts``: scores an arbitrary model's verdicts against the
  authoritative ``expected`` — verdict accuracy, severity-weighted recall
  (CONTRACTS.md: caught = flagged non-MATCH for HIGH severity, correct
  exception_type for MEDIUM/LOW), per-class confusion matrix, escalation
  precision.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from reconforge_forge import taxonomy
from reconforge_forge.task import Task
from reconforge_forge.verifier import verify_task

LEAK_FRACTIONS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.5)

_MATCH = "MATCH"


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def score_verdicts(
    tasks: Iterable[Task],
    model_verdicts: dict[str, dict[str, Any]] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Score model verdicts against the authoritative expected labels."""
    tasks = list(tasks)

    def lookup(task: Task) -> dict[str, Any]:
        if isinstance(model_verdicts, dict):
            return model_verdicts[task.task_id]
        return model_verdicts[tasks.index(task)]

    n = len(tasks)
    n_parse_misses = 0
    correct_verdict = 0
    weight_sum = 0.0
    caught_weight = 0.0
    severity_recall: dict[str, list[bool]] = {"HIGH": [], "MEDIUM": [], "LOW": []}
    confusion: dict[str, dict[str, int]] = {}
    n_exception = 0
    n_esc = 0
    esc_correct = 0
    n_exception_type_correct = 0

    for task in tasks:
        exp = task.expected
        mv = lookup(task)
        if mv is None:  # parse failure / no verdict emitted — count as a miss
            n_parse_misses += 1
        m_verdict = "MATCH" if mv is None else str(mv.get("verdict", "MATCH"))
        m_type = None if mv is None else mv.get("exception_type")
        exp_type = exp.get("exception_type")
        exp_verdict = exp.get("verdict", _MATCH)

        if m_verdict == exp_verdict:
            correct_verdict += 1

        row = confusion.setdefault("MATCH" if exp_verdict == _MATCH else exp_type, {})
        col = m_type if m_verdict != _MATCH else _MATCH
        row[col] = row.get(col, 0) + 1

        if exp_verdict == _MATCH:
            continue
        n_exception += 1
        severity = exp["severity"]
        if severity == "HIGH":
            caught = m_verdict != _MATCH
        else:
            caught = m_type == exp_type
            if caught:
                n_exception_type_correct += 1
        severity_recall[severity].append(caught)
        weight = taxonomy.SEVERITY_WEIGHTS[exp_type]
        weight_sum += weight
        if caught:
            caught_weight += weight

        if m_verdict == "ESCALATE":
            n_esc += 1
            if exp_verdict != _MATCH:
                esc_correct += 1

    def rate(hits: list[bool]) -> float:
        return round(sum(hits) / len(hits), 4) if hits else None

    return {
        "n_tasks": n,
        "n_parse_misses": n_parse_misses,
        "verdict_accuracy": round(correct_verdict / max(n, 1), 4),
        "n_exception_tasks": n_exception,
        "exception_type_accuracy": round(n_exception_type_correct / max(n_exception, 1), 4),
        "severity_weighted_recall": round(caught_weight / max(weight_sum, 1e-12), 4),
        "severity_recall_by_severity": {
            "HIGH": rate(severity_recall["HIGH"]),
            "MEDIUM": rate(severity_recall["MEDIUM"]),
            "LOW": rate(severity_recall["LOW"]),
        },
        "confusion_matrix": confusion,
        "escalation_precision": round(esc_correct / max(n_esc, 1), 4),
        "n_escalations": n_esc,
    }


def run_pilot(
    tasks: list[Task],
    seed: int,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the pilot: verifier-as-oracle agreement + verifier scoring.

    Writes ``pilot-<seed>.json`` to ``out_dir`` (default the shared
    ``docs/validation/``). The artifact is canonical JSON — byte-identical
    for the same seed.
    """
    verdicts = {t.task_id: verify_task(t) for t in tasks}
    n = len(tasks)
    agreed = 0
    disagreements: list[dict[str, Any]] = []
    for t in tasks:
        v = verdicts[t.task_id]
        same = (
            v["verdict"] == t.expected["verdict"]
            and v["exception_type"] == t.expected["exception_type"]
        )
        if same:
            agreed += 1
        else:
            disagreements.append(
                {
                    "task_id": t.task_id,
                    "expected": t.expected,
                    "verifier": v,
                }
            )

    scored = score_verdicts(tasks, verdicts)
    exception_dist: dict[str, int] = {}
    verdict_dist: dict[str, int] = {}
    for t in tasks:
        verdict_dist[t.expected["verdict"]] = verdict_dist.get(t.expected["verdict"], 0) + 1
        et = t.expected.get("exception_type")
        exception_dist[et if et is not None else "MATCH"] = (
            exception_dist.get(et if et is not None else "MATCH", 0) + 1
        )
    diffs = [t.difficulty for t in tasks]

    result: dict[str, Any] = {
        "benchmark": "reconforge-pilot",
        "seed": seed,
        "n_tasks": n,
        "oracle_agreement": round(agreed / max(n, 1), 4),
        "n_oracle_agreed": agreed,
        "severity_weighted_recall_verifier": scored["severity_weighted_recall"],
        "verdict_distribution": verdict_dist,
        "exception_distribution": exception_dist,
        "difficulty": {
            "mean": round(sum(diffs) / max(len(diffs), 1), 4),
            "min": min(diffs) if diffs else None,
            "max": max(diffs) if diffs else None,
        },
        "oracle_disagreements": disagreements,
        "scoring": scored,
        "tasks": [t.to_dict() for t in tasks],
    }

    if out_dir is not None:
        path = Path(out_dir) / f"pilot-{seed}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canonical_json(result) + "\n", encoding="utf-8")

    return result
