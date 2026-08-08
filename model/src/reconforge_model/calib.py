"""Calibration: ECE (10 bins) on the confidence field vs correctness, plus a
confidence-threshold search that minimizes severity-weighted operational cost.

Cost model (documented assumption): missing a HIGH-severity exception costs
5x as much as sending a pair to human review (ESCALATE). Rationale: a missed
AMOUNT_MISMATCH / FX error is principal at risk (A3 weighting), while an
escalation is a bounded human-review cost. Both components are configurable.

Consumes the artifact written by eval.py (`model-eval-{run}.json`, which
carries per-prediction confidence + correctness), so no regeneration is needed.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import metrics

SHARED_ARTIFACTS = Path("/Users/caiotheodoro/Documents/personal/reconforge/docs/validation")
DEFAULT_COST_ESC = 1.0
DEFAULT_COST_MISSED_HIGH = 5.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calib.py", description="ECE + threshold search")
    parser.add_argument("--eval-artifact", required=True, help="model-eval-{run}.json from eval.py")
    parser.add_argument("--run", default="smoke", help="run id for the calib artifact")
    parser.add_argument("--cost-esc", type=float, default=DEFAULT_COST_ESC)
    parser.add_argument("--cost-missed-high", type=float, default=DEFAULT_COST_MISSED_HIGH)
    parser.add_argument("--grid-step", type=float, default=0.05)
    parser.add_argument("--out-dir", type=str, default=str(SHARED_ARTIFACTS))
    opts = parser.parse_args(argv)

    with open(opts.eval_artifact) as fh:
        artifact = json.load(fh)

    outputs = artifact["per_prediction"]
    confidences = [o["confidence"] if o["confidence"] is not None else 0.0 for o in outputs]
    correctness = [1 if o["correct"] else 0 for o in outputs]
    cal = metrics.ece(confidences, correctness, n_bins=10)

    tasks = []
    for o in outputs:
        tasks.append(
            {
                "expected": o["expected"],
                "difficulty": o["difficulty"],
            }
        )
    preds = metrics.predictions_from_outputs(outputs)
    threshold = metrics.find_best_threshold(
        tasks,
        preds,
        cost_esc=opts.cost_esc,
        cost_missed_high=opts.cost_missed_high,
        grid_step=opts.grid_step,
    )
    baseline_cost = metrics.severity_weighted_cost(tasks, preds, cost_esc=opts.cost_esc, cost_missed_high=opts.cost_missed_high)

    out = {
        "run": opts.run,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_artifact": str(opts.eval_artifact),
        "n": len(outputs),
        "ece": cal,
        "threshold_search": threshold,
        "baseline_cost": baseline_cost,
        "cost_model": {
            "cost_esc": opts.cost_esc,
            "cost_missed_high": opts.cost_missed_high,
            "assumption": (
                "a missed HIGH exception (principal at risk) costs "
                f"{opts.cost_missed_high}x; an ESCALATE-to-review costs "
                f"{opts.cost_esc}x"
            ),
        },
    }
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"model-calib-{opts.run}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")

    print("=" * 64)
    print(f"run: {opts.run} | n={out['n']}")
    print(f"ECE (10 bins)          : {cal['ece']:.4f}")
    print("calibration curve (bin | conf | acc | n):")
    for b in cal["curve"]:
        print(f"  {b['bin']:2d} | {b['conf_mean']:.3f} | {b['accuracy']:.3f} | {b['count']}")
    print(f"threshold search (esc={opts.cost_esc}, missed_high={opts.cost_missed_high}x):")
    print(f"  best threshold       : {threshold['best_threshold']}")
    print(f"  best cost            : {threshold['best_total_cost']} "
          f"(escalations={threshold['best_n_escalations']}, missed_high={threshold['best_n_missed_high']})")
    print(f"  baseline cost        : {baseline_cost['total_cost']} "
          f"(escalations={baseline_cost['n_escalations']}, missed_high={baseline_cost['n_missed_high']})")
    print("=" * 64)
    print(f"artifact -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
