"""Shared metric computations for eval and calibration.

Severity-weighted recall follows CONTRACTS.md: over exception tasks,
R_w = sum_i w_i * caught_i / sum_i w_i, where a HIGH-severity exception is
caught if the model flagged the pair as anything other than MATCH, and a
MEDIUM/LOW exception is caught if the model identified the exact
exception_type.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable

import numpy as np

from .schema import SEVERITY_WEIGHT


def normalize_number(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def is_correct(expected: dict[str, Any], pred: dict[str, Any] | None) -> bool:
    """Exact-match correctness: verdict agrees, and exception_type agrees
    when the task is an EXCEPTION task."""
    if pred is None:
        return False
    if pred["verdict"] != expected["verdict"]:
        return False
    exp_type = expected.get("exception_type")
    if exp_type is not None and pred["exception_type"] != exp_type:
        return False
    return True


def is_caught(expected: dict[str, Any], pred: dict[str, Any] | None) -> bool:
    """Severity-weighted-recall 'caught' predicate per CONTRACTS.md."""
    if pred is None:
        return False
    exp_type = expected.get("exception_type")
    if exp_type is None:
        return False  # MATCH tasks are not part of exception recall
    weight = SEVERITY_WEIGHT.get(exp_type, 0.0)
    if weight >= 0.9:  # HIGH: any flag other than MATCH counts as caught
        return pred["verdict"] != "MATCH"
    return pred["exception_type"] == exp_type  # MEDIUM/LOW: exact type


def severity_weighted_recall(tasks: Iterable[dict[str, Any]], preds: list[dict[str, Any] | None]) -> dict[str, Any]:
    tasks = list(tasks)
    assert len(tasks) == len(preds)
    weights_total = 0.0
    weights_caught = 0.0
    n_exceptions = 0
    per_type: dict[str, dict[str, int]] = {}
    for task, pred in zip(tasks, preds):
        exp_type = task["expected"].get("exception_type")
        if exp_type is None:
            continue
        n_exceptions += 1
        w = SEVERITY_WEIGHT.get(exp_type, 0.0)
        weights_total += w
        caught = 1 if is_caught(task["expected"], pred) else 0
        weights_caught += w * caught
        per_type.setdefault(exp_type, {"n": 0, "caught": 0})
        per_type[exp_type]["n"] += 1
        per_type[exp_type]["caught"] += caught
    return {
        "severity_weighted_recall": round(weights_caught / weights_total, 4) if weights_total else 0.0,
        "n_exceptions": n_exceptions,
        "per_type": {
            t: {"n": v["n"], "caught": v["caught"], "recall": round(v["caught"] / v["n"], 4) if v["n"] else 0.0}
            for t, v in sorted(per_type.items())
        },
    }


def precision_recall_f1(tasks: Iterable[dict[str, Any]], preds: list[dict[str, Any] | None]) -> dict[str, Any]:
    """Flag-level precision / recall / F1 — the false-positive-aware partner to
    severity_weighted_recall (issue #8).

    R_w only scores the exception subset, so a model that flags every clean pair
    pays zero R_w cost. This metric puts the 419 clean (MATCH) tasks back on the
    scoreboard.

    "Flagged" = predicted verdict != MATCH (ESCALATE and EXCEPTION both count; a
    parse failure / None prediction is also a flag, since it is always routed to
    human review — see severity_weighted_cost).

      TP: expected is an exception (exception_type is not None) AND model flagged it
      FP: expected is a clean MATCH               AND model flagged it
      FN: expected is an exception                AND model returned MATCH

    Tasks whose expected verdict is ESCALATE (no exception_type, not MATCH) are
    outside this contract and counted in none of TP/FP/FN.
    """
    tasks = list(tasks)
    assert len(tasks) == len(preds)
    tp = fp = fn = 0
    n_exception = n_clean = 0
    for task, pred in zip(tasks, preds):
        exp = task["expected"]
        exp_type = exp.get("exception_type")
        flagged = pred is None or pred["verdict"] != "MATCH"
        if exp_type is not None:
            n_exception += 1
            if flagged:
                tp += 1
            else:
                fn += 1
        elif exp["verdict"] == "MATCH":
            n_clean += 1
            if flagged:
                fp += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n_exception": n_exception,
        "n_clean": n_clean,
    }


CONFUSION_LABELS = tuple(SEVERITY_WEIGHT.keys()) + ("MATCH", "ESCALATE", "PARSE_FAIL")


def confusion_matrix(tasks: list[dict[str, Any]], preds: list[dict[str, Any] | None]) -> dict[str, dict[str, int]]:
    """Exception-type-level confusion matrix with MATCH / ESCALATE / PARSE_FAIL
    rows+cols. Rows = expected class, cols = predicted class."""
    mat = {r: {c: 0 for c in CONFUSION_LABELS} for r in CONFUSION_LABELS}
    for task, pred in zip(tasks, preds):
        exp = task["expected"]
        if exp.get("exception_type") is not None:
            row = exp["exception_type"]
        else:
            row = exp["verdict"]  # MATCH / ESCALATE
        if pred is None:
            col = "PARSE_FAIL"
        elif pred["exception_type"] is not None:
            col = pred["exception_type"]
        else:
            col = pred["verdict"]
        if col not in CONFUSION_LABELS:
            col = "PARSE_FAIL"
        mat[row][col] += 1
    return mat


def summarize_confusion(mat: dict[str, dict[str, int]]) -> dict[str, Any]:
    rows = []
    for row in CONFUSION_LABELS:
        total = sum(mat[row].values())
        if total == 0:
            continue
        correct = mat[row][row]
        rows.append(
            {
                "class": row,
                "n": total,
                "correct": correct,
                "recall": round(correct / total, 4),
                "top_confusions": sorted(
                    ((c, mat[row][c]) for c in CONFUSION_LABELS if c != row and mat[row][c]),
                    key=lambda kv: -kv[1],
                )[:3],
            }
        )
    return {"by_class": rows}


def accuracy(tasks: list[dict[str, Any]], preds: list[dict[str, Any] | None]) -> dict[str, Any]:
    correct = sum(1 for t, p in zip(tasks, preds) if is_correct(t["expected"], p))
    n = len(tasks)
    return {"accuracy": round(correct / n, 4) if n else 0.0, "correct": correct, "n": n}


def parse_rate(preds: list[dict[str, Any] | None]) -> dict[str, Any]:
    parsed = sum(1 for p in preds if p is not None)
    return {"parse_rate": round(parsed / len(preds), 4) if preds else 0.0, "parsed": parsed, "n": len(preds)}


def ece(confidences: list[float], correct: list[int], n_bins: int = 10) -> dict[str, Any]:
    """Expected calibration error with n_bins confidence bins.

    ECE = sum_b (n_b/N) * |acc_b - conf_b|. Returns the ECE plus the per-bin
    calibration curve (conf_center, accuracy, count) for plotting/audit.
    """
    assert len(confidences) == len(correct)
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for conf, ok in zip(confidences, correct):
        idx = min(n_bins - 1, int(conf * n_bins))
        idx = max(0, idx)
        bins[idx].append((conf, ok))
    curve = []
    total = max(len(confidences), 1)
    ece_val = 0.0
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        conf_mean = sum(c for c, _ in bucket) / len(bucket)
        acc = sum(ok for _, ok in bucket) / len(bucket)
        ece_val += (len(bucket) / total) * abs(acc - conf_mean)
        curve.append(
            {
                "bin": i,
                "conf_min": round(i / n_bins, 3),
                "conf_max": round((i + 1) / n_bins, 3),
                "conf_mean": round(conf_mean, 4),
                "accuracy": round(acc, 4),
                "count": len(bucket),
            }
        )
    return {"ece": round(ece_val, 4), "n_bins": n_bins, "curve": curve}


def severity_weighted_cost(tasks: list[dict[str, Any]], preds: list[dict[str, Any] | None], *, cost_esc: float = 1.0, cost_missed_high: float = 5.0) -> dict[str, Any]:
    """Operational loss under a threshold policy (see calib.py).

    A missed HIGH exception (flagged MATCH / not caught) costs
    `cost_missed_high`; every pair sent to ESCALATE for review costs
    `cost_esc`. Returns total and per-class components.
    """
    n_esc = 0
    n_missed_high = 0
    n_high = 0
    for task, pred in zip(tasks, preds):
        exp = task["expected"]
        if pred is None:
            n_esc += 1  # parse failure is always sent to review
        elif pred["verdict"] == "ESCALATE":
            n_esc += 1
        exp_type = exp.get("exception_type")
        if exp_type is not None and SEVERITY_WEIGHT.get(exp_type, 0) >= 0.9:
            n_high += 1
            if not is_caught(exp, pred):
                # A parse failure (pred is None) on a HIGH-severity task is a
                # miss too -- is_caught(exp, None) is False, so this must not
                # be skipped just because there's no verdict to inspect.
                n_missed_high += 1
    cost = cost_esc * n_esc + cost_missed_high * n_missed_high
    n = max(len(tasks), 1)
    return {
        "total_cost": cost,
        "normalized_cost": round(cost / n, 4),
        "n_escalations": n_esc,
        "n_missed_high": n_missed_high,
        "n_high": n_high,
        "cost_esc": cost_esc,
        "cost_missed_high": cost_missed_high,
    }


def find_best_threshold(
    tasks: list[dict[str, Any]],
    preds: list[dict[str, Any] | None],
    *,
    cost_esc: float = 1.0,
    cost_missed_high: float = 5.0,
    grid_step: float = 0.05,
) -> dict[str, Any]:
    """Grid-search a confidence threshold: below it, the verdict is overridden
    to ESCALATE (flag-review). Minimizes severity-weighted cost."""
    results = []
    thresholds = [round(float(t), 3) for t in np.arange(0.0, 1.0 + grid_step, grid_step)]
    for tau in thresholds:
        adjusted = []
        for p in preds:
            if p is None:
                adjusted.append(None)
            elif p["confidence"] < tau:
                adj = dict(p)
                adj["verdict"] = "ESCALATE"
                adj["exception_type"] = None
                adj["severity"] = "MEDIUM"
                adj["resolution"] = "flag-review"
                adjusted.append(adj)
            else:
                adjusted.append(p)
        cost = severity_weighted_cost(tasks, adjusted, cost_esc=cost_esc, cost_missed_high=cost_missed_high)
        results.append((tau, cost))
    best_tau, best_cost = min(results, key=lambda kv: kv[1]["total_cost"])
    baseline = severity_weighted_cost(tasks, preds, cost_esc=cost_esc, cost_missed_high=cost_missed_high)
    return {
        "best_threshold": float(best_tau),
        "best_total_cost": best_cost["total_cost"],
        "best_normalized_cost": best_cost["normalized_cost"],
        "best_n_escalations": best_cost["n_escalations"],
        "best_n_missed_high": best_cost["n_missed_high"],
        "baseline_total_cost": baseline["total_cost"],
        "baseline_n_escalations": baseline["n_escalations"],
        "baseline_n_missed_high": baseline["n_missed_high"],
        "cost_esc": cost_esc,
        "cost_missed_high": cost_missed_high,
        "grid_step": grid_step,
    }


def predictions_from_outputs(outputs: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Pull the predicted (normalized) verdict dicts out of an eval outputs file."""
    return [o.get("predicted") for o in outputs]


def confusion_summary_text(mat: dict[str, dict[str, int]]) -> str:
    rows = [f"{r:24s} | n={sum(mat[r].values()):4d} | correct={mat[r][r]:4d}" for r in CONFUSION_LABELS if sum(mat[r].values())]
    return "\n".join(rows)
