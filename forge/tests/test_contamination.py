"""Contamination monitor tests: signature stability, leak probe behavior,
and the ROC study (fire-on-leaked ~1.0, false-fire-on-clean ~0.0)."""
from __future__ import annotations

from reconforge_forge.contamination import (
    evaluate_monitor,
    leak_probe,
    signatures,
    task_signature,
)
from reconforge_forge.generator import generate_tasks
from reconforge_forge.task import Task


def test_signature_ignores_metadata():
    t1 = generate_tasks(1, seed=1)[0]
    t2 = Task.from_dict({**t1.to_dict(), "task_id": "recon-999999"})
    assert task_signature(t1) == task_signature(t2)


def test_signature_differs_across_seeds():
    a = generate_tasks(1, seed=1)[0]
    b = generate_tasks(1, seed=2)[0]
    assert task_signature(a) != task_signature(b)


def test_signature_roundtrip_stable():
    tasks = generate_tasks(10, seed=3)
    sigs1 = signatures(tasks)
    sigs2 = signatures([Task.from_dict(t.to_dict()) for t in tasks])
    assert sigs1 == sigs2
    assert len(sigs1) == len(tasks)


def test_leak_probe_clean_is_silent():
    train = generate_tasks(100, seed=1)
    eval_clean = generate_tasks(100, seed=2)
    r = leak_probe(train, eval_clean)
    assert r["overlap"] == 0.0
    assert r["fired"] is False


def test_leak_probe_fires_on_leaked():
    train = generate_tasks(100, seed=1)
    eval_leaked = [Task.from_dict(train[i].to_dict()) for i in range(0, 100, 10)]
    eval_leaked += generate_tasks(50, seed=2)
    r = leak_probe(train, eval_leaked)
    assert r["fired"] is True
    assert r["overlap"] >= 0.05


def test_leak_probe_overlap_is_exact_fraction():
    train = generate_tasks(100, seed=1)
    leaked = [Task.from_dict(train[i].to_dict()) for i in range(10)]
    clean = generate_tasks(90, seed=2)
    r = leak_probe(train, leaked + clean)
    assert r["overlap"] == 0.1
    assert r["fired"] is True


def test_evaluate_monitor_roc_headline_numbers():
    train = generate_tasks(200, seed=7)
    eval_clean = generate_tasks(200, seed=7007)
    res = evaluate_monitor(train, eval_clean, seed=7)
    assert len(res["points"]) == 4
    for p in res["points"]:
        assert p["fire_on_leaked"] == 1.0, p
        assert p["false_fire_on_clean"] == 0.0, p


def test_evaluate_monitor_deterministic():
    train = generate_tasks(100, seed=7)
    eval_clean = generate_tasks(100, seed=7007)
    a = evaluate_monitor(train, eval_clean, seed=7)
    b = evaluate_monitor(train, eval_clean, seed=7)
    assert a == b


def test_evaluate_monitor_seed_sensitivity():
    train = generate_tasks(100, seed=7)
    eval_clean = generate_tasks(100, seed=7007)
    a = evaluate_monitor(train, eval_clean, seed=7)
    b = evaluate_monitor(train, eval_clean, seed=8)
    assert a != b
