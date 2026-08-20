"""§11.1 — 95% bootstrap CIs and paired significance tests over the existing
per-task eval exports (docs/validation/bench-eval-champion-x5.json,
bench-deepseek-full.json, bench-eval-base-ablation.json).

No new inference: this resamples the *tasks*, re-scores with the same
is_correct/is_caught rules used for the headline numbers (reconforge_model.metrics),
and reports percentile CIs. Champion vs DeepSeek gets a paired bootstrap test
(same 800-task set both models were run on) since it's the comparison the
card's one-liner makes.

Usage: uv run python scripts/intervals.py
Output: docs/validation/intervals.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from reconforge_model.metrics import accuracy, is_correct, is_caught, severity_weighted_recall
from reconforge_model.schema import SEVERITY_WEIGHT

VALIDATION_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "validation"
RESAMPLES = 10_000
SEED = 11

RUNS = {
    "reconforge_recon": "bench-eval-champion-x5.json",
    "deepseek_v4_flash": "bench-deepseek-full.json",
    "base_qwen3_1_7b": "bench-eval-base-ablation.json",
}


def load_run(name: str) -> dict:
    data = json.loads((VALIDATION_DIR / name).read_text())
    per_task = data["per_task"]
    tasks = [{"expected": t["expected"]} for t in per_task]
    preds = [t.get("predicted") for t in per_task]
    return {"tasks": tasks, "preds": preds}


def percentile_ci(values: list[float], lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
    s = sorted(values)
    n = len(s)
    lo_i = max(0, min(n - 1, round(lo / 100 * (n - 1))))
    hi_i = max(0, min(n - 1, round(hi / 100 * (n - 1))))
    return round(s[lo_i], 4), round(s[hi_i], 4)


def bootstrap_metric(tasks: list[dict], preds: list, metric_fn, rng: random.Random) -> list[float]:
    n = len(tasks)
    idx_universe = range(n)
    out = []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in idx_universe]
        rt = [tasks[i] for i in idx]
        rp = [preds[i] for i in idx]
        out.append(metric_fn(rt, rp))
    return out


def acc_metric(tasks, preds) -> float:
    return accuracy(tasks, preds)["accuracy"]


def rw_metric(tasks, preds) -> float:
    return severity_weighted_recall(tasks, preds)["severity_weighted_recall"]


def per_type_recall_metric(tasks, preds) -> dict[str, float]:
    return {t: v["recall"] for t, v in severity_weighted_recall(tasks, preds)["per_type"].items()}


def _weight_tier(exception_type: str) -> str:
    w = SEVERITY_WEIGHT.get(exception_type, 0.0)
    if w >= 0.9:
        return "HIGH"
    if w >= 0.5:
        return "MEDIUM"
    return "LOW"


def severity_band_recall_metric(tasks, preds) -> dict[str, float]:
    """§3.4's HIGH/MEDIUM/LOW Recall columns == reconforge_forge.benchmark's
    severity_recall_by_severity: is_caught rate (same rule as R_w) over
    exception tasks only, tiered by the exception TYPE's R_w weight
    (>=0.9 HIGH, 0.5-0.9 MEDIUM, <0.5 LOW) -- NOT the task's own literal
    `expected.severity` field. Verified to reproduce the stored
    bench-eval-*.json per_type_recall numbers exactly."""
    n: dict[str, int] = {}
    caught: dict[str, int] = {}
    for t, p in zip(tasks, preds):
        exp_type = t["expected"].get("exception_type")
        if exp_type is None:
            continue
        tier = _weight_tier(exp_type)
        n[tier] = n.get(tier, 0) + 1
        caught[tier] = caught.get(tier, 0) + (1 if is_caught(t["expected"], p) else 0)
    return {tier: caught[tier] / n[tier] for tier in n}


def type_exact_recall_metric(tasks, preds) -> dict[str, float]:
    """§3.5's per-exception-type recall: exact verdict+type match, grouped by
    the *expected* exception_type (matches summarize_confusion's diagonal
    recall) -- distinct from severity_weighted_recall's HIGH-lenient
    is_caught rule used for the R_w headline number."""
    n = {}
    correct = {}
    for t, p in zip(tasks, preds):
        exp_type = t["expected"].get("exception_type")
        if exp_type is None:
            continue
        n[exp_type] = n.get(exp_type, 0) + 1
        correct[exp_type] = correct.get(exp_type, 0) + (1 if is_correct(t["expected"], p) else 0)
    return {t: correct[t] / n[t] for t in n}


def main() -> None:
    runs = {name: load_run(fname) for name, fname in RUNS.items()}

    result: dict = {"resamples": RESAMPLES, "seed": SEED, "runs": {}}

    for name, run in runs.items():
        rng = random.Random(f"{SEED}:{name}")
        tasks, preds = run["tasks"], run["preds"]
        point_acc = acc_metric(tasks, preds)
        point_rw = rw_metric(tasks, preds)
        boot_acc = bootstrap_metric(tasks, preds, acc_metric, rng)
        boot_rw = bootstrap_metric(tasks, preds, rw_metric, rng)
        result["runs"][name] = {
            "n": len(tasks),
            "accuracy": {"point": point_acc, "ci95": list(percentile_ci(boot_acc))},
            "severity_weighted_recall": {"point": point_rw, "ci95": list(percentile_ci(boot_rw))},
        }
        point_band = severity_band_recall_metric(tasks, preds)
        boot_band: dict[str, list[float]] = {b: [] for b in point_band}
        band_rng = random.Random(f"{SEED}:{name}:band")
        n_all = len(tasks)
        for _ in range(RESAMPLES):
            idx = [band_rng.randrange(n_all) for _ in range(n_all)]
            rec = severity_band_recall_metric([tasks[i] for i in idx], [preds[i] for i in idx])
            for b in boot_band:
                boot_band[b].append(rec.get(b, 0.0))
        result["runs"][name]["severity_band_recall"] = {
            b: {"point": point_band[b], "ci95": list(percentile_ci(boot_band[b]))}
            for b in sorted(point_band)
        }

        if name == "reconforge_recon":
            point_pt = type_exact_recall_metric(tasks, preds)
            boot_pt: dict[str, list[float]] = {t: [] for t in point_pt}
            n = len(tasks)
            pt_rng = random.Random(f"{SEED}:{name}:per_type")
            for _ in range(RESAMPLES):
                idx = [pt_rng.randrange(n) for _ in range(n)]
                rt = [tasks[i] for i in idx]
                rp = [preds[i] for i in idx]
                rec = type_exact_recall_metric(rt, rp)
                for t in boot_pt:
                    boot_pt[t].append(rec.get(t, 0.0))
            result["runs"][name]["per_exception_type_recall"] = {
                t: {"point": point_pt[t], "ci95": list(percentile_ci(boot_pt[t]))}
                for t in sorted(point_pt)
            }

    # Paired bootstrap significance: champion vs DeepSeek, same 800-task set,
    # resample task indices jointly so both models see the same resample.
    champ = runs["reconforge_recon"]
    ds = runs["deepseek_v4_flash"]
    assert len(champ["tasks"]) == len(ds["tasks"]) == 800
    rng = random.Random(f"{SEED}:paired")
    n = len(champ["tasks"])
    diffs_acc, diffs_rw = [], []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        ct, cp = [champ["tasks"][i] for i in idx], [champ["preds"][i] for i in idx]
        dt, dp = [ds["tasks"][i] for i in idx], [ds["preds"][i] for i in idx]
        diffs_acc.append(acc_metric(ct, cp) - acc_metric(dt, dp))
        diffs_rw.append(rw_metric(ct, cp) - rw_metric(dt, dp))

    def sig_summary(diffs: list[float]) -> dict:
        lo, hi = percentile_ci(diffs)
        # two-sided bootstrap p-value: fraction of resamples where the sign
        # flips relative to the observed point-estimate direction
        point = sum(diffs) / len(diffs)
        frac_opposite = sum(1 for d in diffs if (d <= 0) == (point > 0)) / len(diffs)
        p_approx = round(2 * min(frac_opposite, 1 - frac_opposite), 4)
        return {"diff_point": round(point, 4), "diff_ci95": [lo, hi],
                "significant_at_0.05": not (lo <= 0.0 <= hi), "p_approx": p_approx}

    result["champion_vs_deepseek"] = {
        "accuracy_diff": sig_summary(diffs_acc),
        "severity_weighted_recall_diff": sig_summary(diffs_rw),
    }

    out_path = VALIDATION_DIR / "intervals.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
