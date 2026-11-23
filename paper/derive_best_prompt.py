#!/usr/bin/env python3
"""Each model on the prompt it did best with: the fine-tune on the prompt it was trained
on (condition E', vote corrected) against DeepSeek on the defined-class prompt with five
samples (condition C).

docs/validation/matched-comparison.json holds the other four contrasts, all produced by
model/scripts/matched_comparison.py. None of them is this one: D-C hands the fine-tune a
prompt it was never trained on, and E'-A hands DeepSeek the weaker prompt and one sample.
A reader who thinks D-C is unfair to the small model will ask for E'-C, so it is derived
here from the same committed per-task exports, with the same estimator.

It does not import the model package. It re-implements the scoring rule from CONTRACTS.md
(weights in taxonomy.json) and the decision-level majority vote, and first reproduces two
of the committed contrasts (point estimates exactly, interval ends to within one unit in the
fourth decimal); if either is off, it stops.

    cd paper && uv run python derive_best_prompt.py
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAL = ROOT / "docs" / "validation"
RESAMPLES = 10_000
SEED = 11  # the committed contrasts use random.Random(f"{SEED}:{label}")

TAX = json.loads((ROOT / "taxonomy.json").read_text())
W, SEV = TAX["severity_weights"], TAX["severity_by_exception"]


def _decision(s: dict) -> tuple:
    return (s.get("verdict"), s.get("exception_type"))


def majority(samples: list[dict]) -> dict:
    counts = Counter(_decision(s) for s in samples)
    winner, _ = counts.most_common(1)[0]
    return next(s for s in samples if _decision(s) == winner)


def load(name: str, reaggregate: bool = False):
    rows = json.loads((VAL / name).read_text())["per_task"]
    out = []
    for r in rows:
        if reaggregate:
            samples = [x for x in (r.get("samples") or []) if x]
            out.append(majority(samples) if samples else None)
        else:
            out.append(r.get("predicted"))
    return rows, out


def caught_vector(rows, preds):
    """(weight_i, caught_i) for every exception task, in task order; None for clean."""
    w, c = [], []
    for r, p in zip(rows, preds):
        e = r["expected"]
        if e["verdict"] == "MATCH":
            w.append(0.0)
            c.append(0)
            continue
        et = e["exception_type"]
        flagged = bool(p) and p.get("verdict") in ("EXCEPTION", "ESCALATE")
        ok = flagged and (SEV[et] == "HIGH" or p.get("exception_type") == et)
        w.append(W[et])
        c.append(int(ok))
    return w, c


def paired(a, b, label: str) -> dict:
    wa, ca = caught_vector(*a)
    wb, cb = caught_vector(*b)
    assert wa == wb
    n = len(wa)
    ga = [x * y for x, y in zip(wa, ca)]
    gb = [x * y for x, y in zip(wb, cb)]
    point = sum(ga) / sum(wa) - sum(gb) / sum(wb)
    rng = random.Random(f"{SEED}:{label}")
    diffs = []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        tw = sum(wa[i] for i in idx)
        diffs.append(sum(ga[i] for i in idx) / tw - sum(gb[i] for i in idx) / tw)
    s = sorted(diffs)
    m = len(s) - 1
    lo, hi = s[round(0.025 * m)], s[round(0.975 * m)]
    return {"point": round(point, 4), "ci95": [round(lo, 4), round(hi, 4)], "excludes_zero": not (lo <= 0.0 <= hi)}


def main() -> int:
    A = load("bench-deepseek-full.json")
    C = load("bench-deepseek-matched-rubric-x5.json")
    D = load("bench-eval-matched-rubric-x5.json")
    Ep = load("bench-eval-champion-x5.json", reaggregate=True)
    committed = json.loads((VAL / "matched-comparison.json").read_text())["effects"]
    for label, a, b, key in (
        ("matched", D, C, "matched_margin_D_minus_C"),
        ("published_corrected", Ep, A, "published_margin_corrected_vote_Eprime_minus_A"),
    ):
        got = paired(a, b, label)
        want = committed[key]
        assert got["point"] == want["point"], (key, got, want)
        # interval ends are percentiles of 10,000 resampled differences and may differ in the last place
        assert all(abs(x - y) <= 0.0001 + 1e-9 for x, y in zip(got["ci95"], want["ci95"])), (key, got, want)
    result = paired(Ep, C, "bestprompt")
    out = {
        "_comment": (
            "The fine-tune on the prompt it was trained on (E', vote corrected) against DeepSeek "
            "on the defined-class prompt with five samples (C): each model on its own best prompt, "
            "both at five samples. Derived by paper/derive_best_prompt.py from the committed "
            "per-task exports with the estimator of model/scripts/matched_comparison.py; the script "
            "first reproduces D-C and E'-A from matched-comparison.json and stops if either differs. "
            "Exploratory on the same seed-777 pool for the same reasons as the other contrasts."
        ),
        "resamples": RESAMPLES,
        "seed": SEED,
        "effect_Eprime_minus_C": result,
    }
    (VAL / "best-prompt-comparison.json").write_text(json.dumps(out, indent=2) + "\n")
    print("reproduced two committed contrasts; E'-C =", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
