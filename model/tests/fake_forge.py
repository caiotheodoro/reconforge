"""Deterministic stub for the `reconforge_forge` package (built in parallel by
the forge agent). Emits schema-identical tasks per CONTRACTS.md:

    {"task_id", "seed", "difficulty", "ledger": {...}, "statement": {...}, "expected": {...}}

Used by tests and the smoke run until the real forge generator is importable.
The smoke script imports this file directly (tests/ is not a package, so it
pins to the checked-in copy). The task `expected` dicts match CONTRACTS.md:
verdict, exception_type, severity, explanation, resolution.
"""
from __future__ import annotations

import json
import random
from typing import Any

MESSAGE_TYPES = ("MT103", "MT202", "MT300", "MT940", "pacs.008", "pacs.009", "camt.054", "camt.053", "INTERNAL")
CURRENCIES = ("USD", "EUR", "GBP", "BRL")
COUNTERPARTIES = (
    "BANK-ACCT-1001",
    "BANK-ACCT-1002",
    "BANK-ACCT-2001",
    "BANK-ACCT-2002",
    "BANK-ACCT-3001",
)
BENEFICIARIES = ("ACME CORP", "GLOBEX LTD", "INITEK GMBH", "UMBRELLA SA", "STERLING CO")

_EXPECTED_META: dict[str, tuple[str, str]] = {
    "AMOUNT_MISMATCH": ("HIGH", "auto-adjust"),
    "FX_CONVERSION_ERROR": ("HIGH", "rebook"),
    "BENEFICIARY_MISMATCH": ("HIGH", "flag-review"),
    "COUNTERPARTY_MISMATCH": ("HIGH", "flag-review"),
    "VALUE_DATE_MISMATCH": ("MEDIUM", "flag-review"),
    "MISSING_MESSAGE": ("MEDIUM", "escalate"),
    "PARTIAL_MATCH": ("MEDIUM", "flag-review"),
    "DUPLICATE": ("LOW", "auto-adjust"),
    "FIELD_CORRUPTION": ("LOW", "flag-review"),
}
_EXPLANATIONS = {
    "AMOUNT_MISMATCH": "amounts differ beyond tolerance",
    "FX_CONVERSION_ERROR": "implied FX rate off the stated rate",
    "BENEFICIARY_MISMATCH": "beneficiary differs between sides",
    "COUNTERPARTY_MISMATCH": "counterparty differs between sides",
    "VALUE_DATE_MISMATCH": "value date differs between sides",
    "MISSING_MESSAGE": "statement side missing for this pair",
    "PARTIAL_MATCH": "some fields agree, others differ",
    "DUPLICATE": "same ref booked twice on the ledger",
    "FIELD_CORRUPTION": "field value is corrupt or unparsable",
}


def _base_ledger(rng: random.Random) -> dict[str, Any]:
    return {
        "message_type": rng.choice(MESSAGE_TYPES),
        "ref": f"OUR-REF-{rng.randint(1, 9999):04d}",
        "amount": f"{rng.uniform(100.0, 1_000_000.0):.2f}",
        "ccy": rng.choice(CURRENCIES),
        "value_date": "2026-08-07",
        "counterparty": rng.choice(COUNTERPARTIES),
        "beneficiary": rng.choice(BENEFICIARIES),
        "fx_rate": None,
        "booked_at": "2026-08-06T14:02:11Z",
    }


def _statement(rng: random.Random, ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_type": rng.choice(("MT940", "camt.053", "camt.054")),
        "ref": f"CP-REF-{rng.randint(1, 9999):04d}",
        "amount": ledger["amount"],
        "ccy": ledger["ccy"],
        "value_date": ledger["value_date"],
        "counterparty": ledger["counterparty"],
        "beneficiary": ledger["beneficiary"],
    }


def _mutate(rng: random.Random, ledger: dict[str, Any], exception_type: str) -> dict[str, Any]:
    stmt = _statement(rng, ledger)
    if exception_type == "AMOUNT_MISMATCH":
        stmt["amount"] = f"{float(ledger['amount']) * rng.uniform(1.02, 1.25):.2f}"
    elif exception_type == "BENEFICIARY_MISMATCH":
        stmt["beneficiary"] = rng.choice([b for b in BENEFICIARIES if b != ledger["beneficiary"]])
    elif exception_type == "COUNTERPARTY_MISMATCH":
        stmt["counterparty"] = rng.choice([c for c in COUNTERPARTIES if c != ledger["counterparty"]])
    elif exception_type == "VALUE_DATE_MISMATCH":
        stmt["value_date"] = "2026-08-08"
    elif exception_type == "MISSING_MESSAGE":
        stmt = {}
    elif exception_type == "DUPLICATE":
        stmt["ref"] = ledger["ref"]
    elif exception_type == "FIELD_CORRUPTION":
        stmt["amount"] = "1,2500.00"
    elif exception_type == "FX_CONVERSION_ERROR":
        stmt["ccy"] = "EUR"
        stmt["fx_rate"] = "0.8900"
    elif exception_type == "PARTIAL_MATCH":
        stmt["beneficiary"] = rng.choice([b for b in BENEFICIARIES if b != ledger["beneficiary"]])
        stmt["value_date"] = "2026-08-08"
    return stmt


def generate_tasks(n: int = 500, seed: int = 7) -> list[dict[str, Any]]:
    """Deterministic schema-identical task generator (forge-compatible stub)."""
    rng = random.Random(seed)
    types = list(_EXPECTED_META)
    tasks: list[dict[str, Any]] = []
    for i in range(n):
        ledger = _base_ledger(rng)
        if rng.random() < 0.3:
            exception_type = None
            expected = {
                "verdict": "MATCH",
                "exception_type": None,
                "severity": "LOW",
                "explanation": "all fields agree within tolerance",
                "resolution": "auto-adjust",
            }
            statement = _statement(rng, ledger)
        else:
            exception_type = rng.choice(types)
            severity, resolution = _EXPECTED_META[exception_type]
            expected = {
                "verdict": "EXCEPTION",
                "exception_type": exception_type,
                "severity": severity,
                "explanation": _EXPLANATIONS[exception_type],
                "resolution": resolution,
            }
            statement = _mutate(rng, ledger, exception_type)
        tasks.append(
            {
                "task_id": f"recon-{i + 1:06d}",
                "seed": seed,
                "difficulty": round(rng.uniform(0.2, 0.95), 4),
                "ledger": ledger,
                "statement": statement,
                "expected": expected,
            }
        )
    return tasks


def save_tasks(tasks: list[dict[str, Any]], path: str) -> None:
    with open(path, "w") as fh:
        for task in tasks:
            fh.write(json.dumps(task, sort_keys=True) + "\n")
