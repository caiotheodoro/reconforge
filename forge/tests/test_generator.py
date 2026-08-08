"""Generator tests: determinism, realism, exception coverage, and the
100% verifier/expected oracle agreement (the A4 gate)."""
from __future__ import annotations

from reconforge_forge.generator import DEFAULT_EXCEPTION_MIX, generate_tasks
from reconforge_forge.task import Task
from reconforge_forge.taxonomy import EXCEPTION_TYPES, SEVERITY_BY_EXCEPTION
from reconforge_forge.verifier import verify_task


def test_same_seed_identical_tasks():
    a = [t.to_dict() for t in generate_tasks(50, seed=7)]
    b = [t.to_dict() for t in generate_tasks(50, seed=7)]
    assert a == b


def test_same_random_state_identical_tasks():
    import random

    ra = random.Random(42)
    rb = random.Random(42)
    a = [t.to_dict() for t in generate_tasks(50, seed=7, random_state=ra)]
    b = [t.to_dict() for t in generate_tasks(50, seed=7, random_state=rb)]
    assert a == b


def test_different_seeds_differ():
    a = [t.to_dict() for t in generate_tasks(50, seed=7)]
    b = [t.to_dict() for t in generate_tasks(50, seed=8)]
    assert a != b


def test_task_ids_unique_and_formatted():
    tasks = generate_tasks(30, seed=3)
    ids = [t.task_id for t in tasks]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "recon-000001"
    assert all(tid.startswith("recon-") for tid in ids)


def test_difficulty_bounds_and_seed_field():
    tasks = generate_tasks(200, seed=11)
    for t in tasks:
        assert 0.1 <= t.difficulty <= 2.0
        assert t.seed == 11


def test_all_exception_types_and_match_appear():
    tasks = generate_tasks(1200, seed=5)
    kinds = {t.expected["exception_type"] for t in tasks}
    assert kinds == (set(EXCEPTION_TYPES) | {None})


def test_exception_rate_in_sane_range():
    tasks = generate_tasks(400, seed=7)
    exc = sum(1 for t in tasks if t.expected["verdict"] != "MATCH")
    frac = exc / len(tasks)
    assert 0.2 <= frac <= 0.8


def test_exception_mix_override_restricts_types():
    tasks = generate_tasks(
        200, seed=9, exception_mix={"AMOUNT_MISMATCH": 1.0}
    )
    for t in tasks:
        assert t.expected["exception_type"] in (None, "AMOUNT_MISMATCH")


def test_oracle_agreement_is_100_percent():
    tasks = generate_tasks(300, seed=7)
    for t in tasks:
        v = verify_task(t)
        assert v["verdict"] == t.expected["verdict"], t.task_id
        assert v["exception_type"] == t.expected["exception_type"], t.task_id


def test_expected_authoritative_and_consistent():
    tasks = generate_tasks(200, seed=13)
    for t in tasks:
        e = t.expected
        assert e["verdict"] in ("MATCH", "EXCEPTION")
        if e["verdict"] == "MATCH":
            assert e["exception_type"] is None
        else:
            assert e["exception_type"] in EXCEPTION_TYPES
            assert e["severity"] == SEVERITY_BY_EXCEPTION[e["exception_type"]]
            assert e["explanation"]
            assert e["resolution"]


def test_missing_message_tasks_have_null_statement():
    tasks = generate_tasks(400, seed=21)
    mm = [t for t in tasks if t.expected["exception_type"] == "MISSING_MESSAGE"]
    assert mm
    for t in mm:
        assert t.statement is None


def test_non_missing_tasks_have_complete_statement():
    tasks = generate_tasks(200, seed=22)
    for t in tasks:
        if t.statement is None:
            assert t.expected["exception_type"] == "MISSING_MESSAGE"
            continue
        for key in ("message_type", "ref", "amount", "ccy", "value_date",
                    "counterparty", "beneficiary"):
            assert t.statement[key], (t.task_id, key)


def test_amounts_are_two_dp_strings():
    tasks = generate_tasks(150, seed=23)
    for t in tasks:
        for rec in (t.ledger, t.statement):
            if rec is None:
                continue
            if t.expected["exception_type"] == "FIELD_CORRUPTION":
                continue  # corruption injection uses a 3dp amount by design
            assert "." in rec["amount"]
            _, frac = rec["amount"].split(".")
            assert len(frac) == 2


def test_fx_pairs_have_exactly_one_fx_rate():
    tasks = generate_tasks(400, seed=24)
    fx = [
        t for t in tasks
        if t.statement is not None
        and t.expected["exception_type"] != "FIELD_CORRUPTION"
        and t.ledger["ccy"].upper() != t.statement["ccy"].upper()
    ]
    assert fx
    for t in fx:
        lr, sr = t.ledger["fx_rate"], t.statement["fx_rate"]
        assert (lr is None) != (sr is None), t.task_id


def test_fx_conversion_error_tasks_are_fx_pairs():
    tasks = generate_tasks(500, seed=25)
    fxerr = [t for t in tasks if t.expected["exception_type"] == "FX_CONVERSION_ERROR"]
    assert fxerr
    for t in fxerr:
        assert t.ledger["ccy"] != t.statement["ccy"]


def test_amount_mismatch_tasks_are_same_ccy():
    tasks = generate_tasks(400, seed=26)
    for t in tasks:
        if t.expected["exception_type"] == "AMOUNT_MISMATCH":
            assert t.ledger["ccy"] == t.statement["ccy"]


def test_roundtrip_lossless():
    tasks = generate_tasks(20, seed=27)
    for t in tasks:
        assert Task.from_dict(t.to_dict()) == t


def test_difficulty_prior_mean_shifts_distribution():
    low = [t.difficulty for t in generate_tasks(300, seed=1, difficulty_prior_mean=0.2)]
    high = [t.difficulty for t in generate_tasks(300, seed=1, difficulty_prior_mean=1.5)]
    assert sum(low) / len(low) < sum(high) / len(high)


def test_ledger_always_has_booked_at_statement_never():
    tasks = generate_tasks(100, seed=28)
    for t in tasks:
        assert "booked_at" in t.ledger
        if t.statement is not None:
            assert "booked_at" not in t.statement
