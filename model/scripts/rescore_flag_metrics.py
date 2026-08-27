"""Issue #8 — re-score the committed eval exports with a false-positive-aware
partner metric for severity_weighted_recall (R_w).

R_w skips every clean (MATCH) task, so a model that flags all 419 clean pairs
pays zero R_w cost. `docs/validation/model-eval-smoke-20260807.json` — a
degenerate always-ESCALATE model — scores R_w 0.696 (beating the real base-model
baseline 0.600) at accuracy 0.0. This script runs two metrics that DO see the
clean tasks over the same already-committed per-task exports (no inference, no
model runs):

  - metrics.precision_recall_f1  — flag-level precision / recall / F1
  - metrics.severity_weighted_cost — operational loss

Cost model (stated explicitly, not left implicit): cost_esc = 1.0 per pair sent
to human review, cost_missed_high = 5.0 per missed HIGH-severity exception.
These are metrics.severity_weighted_cost's existing defaults.

95% percentile bootstrap CIs (10,000 task resamples, seeded) reuse
scripts/intervals.py's bootstrap_metric / percentile_ci helpers.

Usage: uv run python scripts/rescore_flag_metrics.py
Output: docs/validation/flag-metrics.json  (+ a table on stdout)
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from reconforge_model.metrics import precision_recall_f1, severity_weighted_cost

from intervals import bootstrap_metric, percentile_ci  # noqa: E402

VALIDATION_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "validation"
RESAMPLES = 10_000
SEED = 11
COST_ESC = 1.0
COST_MISSED_HIGH = 5.0

# 4 real exports + the degenerate smoke fixture.
RUNS = {
    "reconforge_recon_iter740": "bench-eval-full-740.json",
    "reconforge_recon_x5": "bench-eval-champion-x5.json",
    "deepseek_v4_flash": "bench-deepseek-full.json",
    "base_qwen3_1_7b": "bench-eval-base-ablation.json",
    "escalate_everything_smoke": "model-eval-smoke-20260807.json",
}


def load_run(name: str) -> dict:
    data = json.loads((VALIDATION_DIR / name).read_text())
    # the smoke fixture stores its per-task rows under `per_prediction`.
    per_task = data.get("per_task") or data["per_prediction"]
    tasks = [{"expected": t["expected"]} for t in per_task]
    preds = [t.get("predicted") for t in per_task]
    return {"tasks": tasks, "preds": preds}


def prf_metric(tasks, preds) -> dict[str, float]:
    """precision/recall/f1 from one precision_recall_f1 call, so a single
    bootstrap pass yields all three CIs from the same resample instead of
    three separate resamples each re-deriving the full confusion count."""
    prf = precision_recall_f1(tasks, preds)
    return {k: prf[k] for k in ("precision", "recall", "f1")}


def norm_cost_metric(tasks, preds) -> float:
    return severity_weighted_cost(
        tasks, preds, cost_esc=COST_ESC, cost_missed_high=COST_MISSED_HIGH
    )["normalized_cost"]


def main() -> None:
    result: dict = {
        "resamples": RESAMPLES,
        "seed": SEED,
        "cost_model": {"cost_esc": COST_ESC, "cost_missed_high": COST_MISSED_HIGH},
        "runs": {},
    }

    for name, fname in RUNS.items():
        run = load_run(fname)
        tasks, preds = run["tasks"], run["preds"]
        prf = precision_recall_f1(tasks, preds)
        cost = severity_weighted_cost(
            tasks, preds, cost_esc=COST_ESC, cost_missed_high=COST_MISSED_HIGH
        )
        entry: dict = {
            "source": fname,
            "n": len(tasks),
            "counts": {k: prf[k] for k in ("tp", "fp", "fn", "n_exception", "n_clean")},
            "severity_weighted_cost": cost,
        }

        # One bootstrap pass for precision/recall/f1 (same resample -> all
        # three CIs, and one precision_recall_f1 call per resample instead of
        # three), mirroring intervals.py's severity_band_recall_metric.
        prf_rng = random.Random(f"{SEED}:{name}:prf")
        boot_prf = bootstrap_metric(tasks, preds, prf_metric, prf_rng)
        for label in ("precision", "recall", "f1"):
            ci = percentile_ci([b[label] for b in boot_prf])
            entry[label] = {"point": prf[label], "ci95": list(ci)}

        cost_rng = random.Random(f"{SEED}:{name}:normalized_cost")
        boot_cost = bootstrap_metric(tasks, preds, norm_cost_metric, cost_rng)
        entry["normalized_cost"] = {
            "point": cost["normalized_cost"],
            "ci95": list(percentile_ci(boot_cost)),
        }
        result["runs"][name] = entry

    out_path = VALIDATION_DIR / "flag-metrics.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(f"cost model: cost_esc={COST_ESC}, cost_missed_high={COST_MISSED_HIGH} "
          f"(severity_weighted_cost defaults)\n")
    hdr = f"{'run':28s} {'n':>4s} {'prec [95% CI]':>22s} {'F1 [95% CI]':>22s} {'norm.cost [95% CI]':>24s}  fp"
    print(hdr)
    print("-" * len(hdr))
    for name, e in result["runs"].items():
        p, f, c = e["precision"], e["f1"], e["normalized_cost"]
        print(
            f"{name:28s} {e['n']:4d} "
            f"{p['point']:.3f} [{p['ci95'][0]:.3f},{p['ci95'][1]:.3f}] "
            f"{f['point']:.3f} [{f['ci95'][0]:.3f},{f['ci95'][1]:.3f}] "
            f"{c['point']:.3f} [{c['ci95'][0]:.3f},{c['ci95'][1]:.3f}]  "
            f"{e['counts']['fp']}"
        )
    print("\nwrote", out_path)


if __name__ == "__main__":
    main()
