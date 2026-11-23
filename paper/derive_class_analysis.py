#!/usr/bin/env python3
"""Post hoc nine-class margin decomposition and non-PARTIAL_MATCH sensitivity (P3).

Reads the committed per-task exports under docs/validation/ and taxonomy.json, first
verifies exact reproduction of the committed point margins (E-A, E'-A, D-C, E'-C), and
writes docs/validation/class-decomposition-and-clustering.json.

    cd paper && uv run python derive_class_analysis.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from derive_best_prompt import RESAMPLES, SEED, SEV, TAX, W, caught_vector, load, paired

ROOT = Path(__file__).resolve().parent.parent
VAL = ROOT / "docs" / "validation"


def per_class_stats(rows, preds) -> tuple[dict[str, dict], float]:
    caught: dict[str, int] = {et: 0 for et in TAX["exception_types"]}
    counts: dict[str, int] = {et: 0 for et in TAX["exception_types"]}
    tot_w = 0.0
    for r, p in zip(rows, preds):
        e = r["expected"]
        if e["verdict"] == "MATCH":
            continue
        et = e["exception_type"]
        flagged = bool(p) and p.get("verdict") in ("EXCEPTION", "ESCALATE")
        ok = flagged and (SEV[et] == "HIGH" or p.get("exception_type") == et)
        counts[et] += 1
        caught[et] += int(ok)
        tot_w += W[et]
    out = {}
    for et in TAX["exception_types"]:
        n = counts[et]
        k = caught[et]
        out[et] = {
            "n": n,
            "caught": k,
            "recall": round(k / n, 4) if n else 0.0,
            "weight": W[et],
            "severity": SEV[et],
            "weighted_contrib": (W[et] * k) / tot_w,
        }
    return out, tot_w


def paired_excluding(a, b, exclude_types: set[str], label: str) -> dict:
    rows_a, preds_a = a
    rows_b, preds_b = b
    wa, ca = caught_vector(rows_a, preds_a)
    wb, cb = caught_vector(rows_b, preds_b)
    assert wa == wb
    keep = [
        i for i, r in enumerate(rows_a)
        if r["expected"]["verdict"] == "MATCH" or r["expected"]["exception_type"] not in exclude_types
    ]
    wa_k = [wa[i] for i in keep]
    ga_k = [wa[i] * ca[i] for i in keep]
    gb_k = [wb[i] * cb[i] for i in keep]
    n = len(keep)
    point = sum(ga_k) / sum(wa_k) - sum(gb_k) / sum(wa_k)
    rng = random.Random(f"{SEED}:{label}")
    diffs = []
    for _ in range(RESAMPLES):
        idx = [rng.randrange(n) for _ in range(n)]
        tw = sum(wa_k[i] for i in idx)
        diffs.append(sum(ga_k[i] for i in idx) / tw - sum(gb_k[i] for i in idx) / tw)
    s = sorted(diffs)
    m = len(s) - 1
    lo, hi = s[round(0.025 * m)], s[round(0.975 * m)]
    return {
        "n_tasks_kept": n,
        "n_exceptions_kept": sum(1 for x in wa_k if x > 0),
        "rw_a": round(sum(ga_k) / sum(wa_k), 4),
        "rw_b": round(sum(gb_k) / sum(wa_k), 4),
        "point": round(point, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "excludes_zero": not (lo <= 0.0 <= hi),
    }


def compute() -> dict:
    A = load("bench-deepseek-full.json")
    C = load("bench-deepseek-matched-rubric-x5.json")
    D = load("bench-eval-matched-rubric-x5.json")
    E = load("bench-eval-champion-x5.json", reaggregate=False)
    Ep = load("bench-eval-champion-x5.json", reaggregate=True)

    # Sanity gate against committed contrasts
    mc = json.loads((VAL / "matched-comparison.json").read_text())["effects"]
    bp = json.loads((VAL / "best-prompt-comparison.json").read_text())["effect_Eprime_minus_C"]
    assert paired(E, A, "pub_check")["point"] == mc["published_margin_as_reported_E_minus_A"]["point"]
    assert paired(Ep, A, "pubc_check")["point"] == mc["published_margin_corrected_vote_Eprime_minus_A"]["point"]
    assert paired(D, C, "mat_check")["point"] == mc["matched_margin_D_minus_C"]["point"]
    assert paired(Ep, C, "bp_check")["point"] == bp["point"]

    st_A, tot_w = per_class_stats(*A)
    st_C, _ = per_class_stats(*C)
    st_E, _ = per_class_stats(*E)
    st_Ep, _ = per_class_stats(*Ep)

    classes = []
    for et in TAX["exception_types"]:
        classes.append({
            "exception_type": et,
            "severity": SEV[et],
            "weight": W[et],
            "n": st_E[et]["n"],
            "caught_E": st_E[et]["caught"],
            "caught_Eprime": st_Ep[et]["caught"],
            "caught_A": st_A[et]["caught"],
            "caught_C": st_C[et]["caught"],
            "recall_E": st_E[et]["recall"],
            "recall_Eprime": st_Ep[et]["recall"],
            "recall_A": st_A[et]["recall"],
            "recall_C": st_C[et]["recall"],
            "contrib_E_minus_A": round(st_E[et]["weighted_contrib"] - st_A[et]["weighted_contrib"], 4),
            "contrib_Eprime_minus_A": round(st_Ep[et]["weighted_contrib"] - st_A[et]["weighted_contrib"], 4),
            "contrib_Eprime_minus_C": round(st_Ep[et]["weighted_contrib"] - st_C[et]["weighted_contrib"], 4),
        })

    excl = {"PARTIAL_MATCH"}
    no_pm = {
        "E_minus_A": paired_excluding(E, A, excl, "no_pm_E_minus_A"),
        "Eprime_minus_A": paired_excluding(Ep, A, excl, "no_pm_Eprime_minus_A"),
        "D_minus_C": paired_excluding(D, C, excl, "no_pm_D_minus_C"),
        "Eprime_minus_C": paired_excluding(Ep, C, excl, "no_pm_Eprime_minus_C"),
    }

    return {
        "_comment": (
            "Post hoc nine-class R_w decomposition and non-PARTIAL_MATCH paired sensitivity (P3), "
            "computed from committed per-task exports under docs/validation/ using the same paired "
            "bootstrap estimator (10,000 resamples, seed 11) as paper/derive_best_prompt.py."
        ),
        "resamples": RESAMPLES,
        "seed": SEED,
        "total_exception_weight": round(tot_w, 4),
        "per_class": classes,
        "excluding_partial_match": no_pm,
    }


def main() -> int:
    out = compute()
    path = VAL / "class-decomposition-and-clustering.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print("wrote", path)
    for k, v in out["excluding_partial_match"].items():
        print(f"  no-PM {k}: {v['point']:+.4f} {v['ci95']} (rw_a={v['rw_a']}, rw_b={v['rw_b']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
