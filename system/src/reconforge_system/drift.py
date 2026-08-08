"""Drift detection over the verdict ledger: PSI on exception-type distribution (pure functions)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

EPSILON = 1e-6


def psi(actual: dict[str, float], baseline: dict[str, float]) -> float:
    keys = set(actual) | set(baseline)
    if not keys:
        return 0.0
    total_a = sum(actual.values())
    total_b = sum(baseline.values())
    if total_a <= 0 or total_b <= 0:
        return float("inf")
    acc = 0.0
    for key in keys:
        pa = min(max(actual.get(key, 0.0) / total_a, EPSILON), 1.0)
        pb = min(max(baseline.get(key, 0.0) / total_b, EPSILON), 1.0)
        acc += (pa - pb) * math.log(pa / pb)
    return acc


@dataclass(frozen=True)
class DriftReport:
    psi: float
    fired: bool
    threshold: float
    detail: dict = field(default_factory=dict)


def exception_drift(
    current: dict[str, float],
    baseline: dict[str, float],
    threshold: float,
) -> DriftReport:
    value = psi(current, baseline)
    fired = bool(math.isfinite(value) and value > threshold)
    return DriftReport(
        psi=value,
        fired=fired,
        threshold=threshold,
        detail={
            "rule": "psi_exception_type_distribution",
            "baseline_sum": sum(baseline.values()),
            "current_sum": sum(current.values()),
        },
    )
