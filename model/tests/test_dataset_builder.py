"""Dataset builder tests: stratification quality, no leakage, determinism."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fake_forge import generate_tasks  # noqa: E402

from reconforge_model.dataset_builder import (  # noqa: E402
    build_datasets,
    stratify_split,
    task_signature,
)


def _read(path):
    return [json.loads(line) for line in open(path)]


def test_stratify_disjoint_and_balanced():
    tasks = generate_tasks(n=600, seed=3)
    train, val = stratify_split(tasks, 0.8, __import__("random").Random(7))
    assert len(train) + len(val) == len(tasks)
    assert len(train) > 0 and len(val) > 0
    assert not ({t["task_id"] for t in train} & {t["task_id"] for t in val})


def test_build_datasets_no_leakage_and_contamination_guard():
    tasks = generate_tasks(n=600, seed=3)
    stats = build_datasets(tasks, train_frac=0.8, seed=7, out_dir="data/test-leak")
    assert stats["id_overlap"] == 0
    assert stats["signature_overlap_frac"] == 0.0


def test_build_datasets_deterministic():
    tasks = generate_tasks(n=400, seed=5)
    build_datasets(tasks, train_frac=0.8, seed=7, out_dir="data/test-det-a")
    build_datasets(tasks, train_frac=0.8, seed=7, out_dir="data/test-det-b")
    a = [json.loads(l) for l in open("data/test-det-a/train.jsonl")]
    b = [json.loads(l) for l in open("data/test-det-b/train.jsonl")]
    assert a == b
    va = [json.loads(l) for l in open("data/test-det-a/val.jsonl")]
    vb = [json.loads(l) for l in open("data/test-det-b/val.jsonl")]
    assert va == vb


def test_stratification_matches_difficulty_and_types():
    tasks = generate_tasks(n=600, seed=3)
    stats = build_datasets(tasks, train_frac=0.8, seed=7, out_dir="data/test-strat")

    def decile_dist(records):
        counts = Counter()
        for r in records:
            counts[min(9, int(r["difficulty"] * 10))] += 1
        return counts

    train = _read("data/test-strat/train.jsonl")
    val = _read("data/test-strat/val.jsonl")
    td, vd = decile_dist(train), decile_dist(val)
    assert set(td) == set(vd), "both splits should cover the same difficulty deciles"
    for b in td:
        assert vd[b] > 0, f"val missing difficulty decile {b}"
        # proportional: val fraction ~ 0.2 within tolerance
        frac = vd[b] / (td[b] + vd[b])
        assert 0.1 <= frac <= 0.35, f"decile {b} split fraction {frac:.3f} off"
    # exception-type coverage in both splits (9 exception types + MATCH)
    train_types = {r["messages"][-1]["content"] for r in train}
    val_types = {r["messages"][-1]["content"] for r in val}
    assert len(train_types) == 10
    assert len(val_types) == 10


def test_train_and_val_have_both_verdict_classes():
    tasks = generate_tasks(n=600, seed=3)
    build_datasets(tasks, train_frac=0.8, seed=7, out_dir="data/test-classes")
    train = _read("data/test-classes/train.jsonl")
    val = _read("data/test-classes/val.jsonl")
    assert any('"MATCH"' in r["messages"][-1]["content"] for r in train)
    assert any('"MATCH"' in r["messages"][-1]["content"] for r in val)
    assert any('"EXCEPTION"' in r["messages"][-1]["content"] for r in train)
    assert any('"EXCEPTION"' in r["messages"][-1]["content"] for r in val)


def test_contamination_guard_refuses_overlap():
    tasks = generate_tasks(n=50, seed=3)
    # duplicate every val task signature by cloning the pair with a new id
    dupes = []
    for t in tasks:
        t2 = json.loads(json.dumps(t))
        t2["task_id"] = "x-" + t["task_id"]
        dupes.append(t2)
    import pytest

    with pytest.raises(ValueError, match="contamination"):
        build_datasets(tasks + dupes, train_frac=0.8, seed=7, out_dir="data/test-contam")


def test_task_signature_is_field_sensitive():
    t = generate_tasks(n=1, seed=3)[0]
    s1 = task_signature(t)
    t2 = json.loads(json.dumps(t))
    t2["statement"]["amount"] = "999999.00"
    assert task_signature(t2) != s1
    # same pair, different task_id -> same signature
    t3 = json.loads(json.dumps(t))
    t3["task_id"] = "other-id"
    assert task_signature(t3) == s1
