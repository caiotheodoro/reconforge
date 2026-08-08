"""Eval metrics tests on handcrafted tiny verdict sets."""
from reconforge_model import metrics
from reconforge_model.schema import verdict_from_expected


def _task(et=None, verdict="MATCH", severity="LOW", difficulty=0.5, tid="t1"):
    return {
        "task_id": tid,
        "difficulty": difficulty,
        "expected": {
            "verdict": verdict,
            "exception_type": et,
            "severity": severity,
            "explanation": "x",
            "resolution": "flag-review",
        },
    }


def _pred(verdict="MATCH", et=None, confidence=1.0):
    return {
        "verdict": verdict,
        "exception_type": et,
        "severity": "LOW",
        "confidence": confidence,
        "reason": "r",
        "resolution": "flag-review",
    }


def test_accuracy_exact_and_partial():
    tasks = [
        _task(et="AMOUNT_MISMATCH", verdict="EXCEPTION", severity="HIGH", tid="a"),
        _task(et="DUPLICATE", verdict="EXCEPTION", severity="LOW", tid="b"),
        _task(et=None, verdict="MATCH", tid="c"),
    ]
    preds = [
        _pred("EXCEPTION", "AMOUNT_MISMATCH"),  # exact
        _pred("EXCEPTION", "BENEFICIARY_MISMATCH"),  # wrong type
        _pred("MATCH", None),  # exact
    ]
    assert metrics.accuracy(tasks, preds)["accuracy"] == round(2 / 3, 4)


def test_accuracy_parse_failure_counts_wrong():
    tasks = [_task(et=None, verdict="MATCH", tid="c")]
    assert metrics.accuracy(tasks, [None])["accuracy"] == 0.0


def test_severity_weighted_recall_high_flag_rule():
    # HIGH: any non-MATCH flag counts as caught, even with the wrong type.
    tasks = [
        _task(et="AMOUNT_MISMATCH", verdict="EXCEPTION", severity="HIGH", tid="a"),
        _task(et="FX_CONVERSION_ERROR", verdict="EXCEPTION", severity="HIGH", tid="b"),
        _task(et="BENEFICIARY_MISMATCH", verdict="EXCEPTION", severity="HIGH", tid="c"),
        _task(et="DUPLICATE", verdict="EXCEPTION", severity="LOW", tid="d"),
    ]
    preds = [
        _pred("EXCEPTION", "BENEFICIARY_MISMATCH"),  # wrong type but flagged -> caught
        _pred("MATCH", None),  # missed high
        _pred("ESCALATE", None),  # caught
        _pred("EXCEPTION", "DUPLICATE"),  # caught
    ]
    res = metrics.severity_weighted_recall(tasks, preds)
    # w = 1.0 + 1.0 + 0.9 (HIGHs) + 0.2 (DUPLICATE); caught = a,c,d
    expected = (1.0 + 0.9 + 0.2) / (1.0 + 1.0 + 0.9 + 0.2)
    assert res["severity_weighted_recall"] == round(expected, 4)
    assert res["n_exceptions"] == 4
    # MEDIUM/LOW require the exact type
    assert res["per_type"]["BENEFICIARY_MISMATCH"]["caught"] == 1
    assert res["per_type"]["DUPLICATE"]["caught"] == 1


def test_severity_weighted_recall_medium_requires_exact_type():
    tasks = [_task(et="VALUE_DATE_MISMATCH", verdict="EXCEPTION", severity="MEDIUM", tid="a")]
    preds = [_pred("EXCEPTION", "MISSING_MESSAGE")]  # flagged but wrong type
    res = metrics.severity_weighted_recall(tasks, preds)
    assert res["severity_weighted_recall"] == 0.0


def test_confusion_matrix_basic():
    tasks = [
        _task(et="AMOUNT_MISMATCH", verdict="EXCEPTION", severity="HIGH", tid="a"),
        _task(et=None, verdict="MATCH", tid="b"),
        _task(et=None, verdict="MATCH", tid="c"),
        _task(et="DUPLICATE", verdict="EXCEPTION", severity="LOW", tid="d"),
    ]
    preds = [_pred("EXCEPTION", "AMOUNT_MISMATCH"), _pred("MATCH"), None, _pred("EXCEPTION", "DUPLICATE")]
    cm = metrics.confusion_matrix(tasks, preds)
    assert cm["AMOUNT_MISMATCH"]["AMOUNT_MISMATCH"] == 1
    assert cm["MATCH"]["MATCH"] == 1
    assert cm["MATCH"]["PARSE_FAIL"] == 1
    assert cm["DUPLICATE"]["DUPLICATE"] == 1


def test_ece_perfect_calibration_is_zero():
    confs = [0.2] * 5 + [0.8] * 5 + [0.5] * 2
    correct = [1, 0, 0, 0, 0] + [1, 1, 1, 1, 0] + [1, 0]
    res = metrics.ece(confs, correct, n_bins=10)
    assert res["ece"] < 1e-6


def test_ece_miscalibration_positive():
    confs = [0.9, 0.9, 0.9, 0.9]
    correct = [0, 0, 0, 0]
    assert metrics.ece(confs, correct, n_bins=10)["ece"] > 0.5


def test_threshold_search_reduces_cost_with_bad_calibration():
    # Model overconfident: misses a HIGH with high confidence.
    tasks = [
        _task(et="AMOUNT_MISMATCH", verdict="EXCEPTION", severity="HIGH", tid="a"),
        _task(et="AMOUNT_MISMATCH", verdict="EXCEPTION", severity="HIGH", tid="b"),
        _task(et=None, verdict="MATCH", tid="c"),
    ]
    preds = [
        _pred("MATCH", None, confidence=0.9),  # missed high, confident
        _pred("EXCEPTION", "AMOUNT_MISMATCH", confidence=0.9),
        _pred("MATCH", None, confidence=0.9),
    ]
    res = metrics.find_best_threshold(tasks, preds, cost_esc=1.0, cost_missed_high=5.0)
    assert res["baseline_total_cost"] == 5.0  # one missed high
    assert res["best_total_cost"] < res["baseline_total_cost"]
    assert res["best_threshold"] > 0.0  # low-confidence MATCH gets escalated


def test_caught_definition_matches_contracts():
    # MATCH tasks never count as exceptions for recall
    tasks = [_task(et=None, verdict="MATCH", tid="c")]
    res = metrics.severity_weighted_recall(tasks, [_pred("MATCH")])
    assert res["n_exceptions"] == 0
    assert res["severity_weighted_recall"] == 0.0


def test_verdict_from_expected_roundtrip_used_by_dataset():
    task = _task(et="AMOUNT_MISMATCH", verdict="EXCEPTION", severity="HIGH")
    vd = verdict_from_expected(task["expected"])
    assert vd["confidence"] == 1.0
    assert vd["verdict"] == "EXCEPTION"
    assert vd["exception_type"] == "AMOUNT_MISMATCH"
