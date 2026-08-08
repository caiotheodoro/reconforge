"""Seeded synthetic pair generator (CONTRACTS.md task schema).

Produces realistic ledger-vs-statement reconciliation pairs with
authoritative ``expected`` verdicts. Design principles:

- **Determinism**: every draw goes through one ``random.Random``; the same
  ``seed`` reproduces a byte-identical task list.
- **Realism**: SWIFT-ish fields (ref/amount/ccy/value_date/counterparty/
  beneficiary/fx_rate/booked_at), message-type priors (ledger = INTERNAL or
  the booked message; statement = MT940/camt.053/...).
- **Adversarial near-misses**: AMOUNT_MISMATCH pairs are injected *beyond*
  the 0.5% rounding tolerance while near-miss noise keeps MATCH pairs *just
  inside* it; FX errors use wrong-but-plausible rates (0.5% < off < 5%).
- **Oracle gate by construction**: every candidate task is verified with
  ``verify_task`` before acceptance; if the verifier disagrees with the
  injected truth, the pair is regenerated. Exhausted tries fall back to a
  trivially-agreeing pair. This makes the pilot's 100% verifier/expected
  agreement a property, not a hope.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from reconforge_forge import taxonomy
from reconforge_forge.task import Task
from reconforge_forge.verifier import verify_task

BASE_EXCEPTION_PROBABILITY = 0.45
FX_PRIOR_BASE = 0.30
MIN_DIFFICULTY = 0.1
MAX_DIFFICULTY = 2.0
_MAX_REBUILD_TRIES = 48

HOME_CCY = "USD"
FOREIGN_CCYS: tuple[str, ...] = ("EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "BRL")
FOREIGN_CCY_WEIGHTS: tuple[float, ...] = (0.30, 0.20, 0.10, 0.10, 0.10, 0.10, 0.10)

# Per-currency USD rate bands (per 1 USD).
FX_RATE_BANDS: dict[str, tuple[float, float]] = {
    "EUR": (0.85, 1.15),
    "GBP": (0.75, 0.95),
    "JPY": (95.0, 160.0),
    "CHF": (0.85, 1.05),
    "CAD": (1.25, 1.45),
    "AUD": (1.35, 1.65),
    "BRL": (5.0, 6.2),
}

DEFAULT_EXCEPTION_MIX: dict[str, float] = {
    "AMOUNT_MISMATCH": 0.20,
    "FX_CONVERSION_ERROR": 0.10,
    "BENEFICIARY_MISMATCH": 0.10,
    "COUNTERPARTY_MISMATCH": 0.10,
    "VALUE_DATE_MISMATCH": 0.12,
    "MISSING_MESSAGE": 0.12,
    "DUPLICATE": 0.08,
    "FIELD_CORRUPTION": 0.08,
    "PARTIAL_MATCH": 0.10,
}

MESSAGE_TYPE_PRIORS_LEDGER: dict[str, float] = {
    "INTERNAL": 0.30,
    "MT103": 0.20,
    "MT202": 0.15,
    "MT300": 0.10,
    "pacs.008": 0.10,
    "pacs.009": 0.05,
    "MT940": 0.05,
    "camt.054": 0.05,
}

MESSAGE_TYPE_PRIORS_STATEMENT: dict[str, float] = {
    "MT940": 0.35,
    "camt.053": 0.25,
    "camt.054": 0.15,
    "MT103": 0.10,
    "MT202": 0.10,
    "MT300": 0.05,
}

BENEFICIARY_NAMES: tuple[str, ...] = (
    "ACME CORPORATION",
    "GLOBAL BANKING SERVICES",
    "NORDWIND LOGISTICS GMBH",
    "HELIOS ENERGY LLC",
    "ATLAS FREIGHT CO",
)

# Fully-disjoint mismatch pool: no name in this pool is near-equal to a name
# in BENEFICIARY_NAMES (tokens are disjoint).
BENEFICIARY_MISMATCH_NAMES: tuple[str, ...] = (
    "BLUESTONE CAPITAL LLP",
    "MERIDIAN TRADING INC",
    "SUNRISE COMMODITIES LTD",
    "PEAKVIEW HOLDINGS AG",
    "CASTLE ROCK PARTNERS",
)

# Near-equal partial-match variants (abbreviation/truncation of the base).
BENEFICIARY_VARIANTS: dict[str, str] = {
    "ACME CORPORATION": "ACME CORP",
    "GLOBAL BANKING SERVICES": "GLOBAL BANKING",
    "NORDWIND LOGISTICS GMBH": "NORDWIND LOGISTICS",
    "HELIOS ENERGY LLC": "HELIOS ENERGY",
    "ATLAS FREIGHT CO": "ATLAS FREIGHT",
}

COUNTERPARTIES: tuple[str, ...] = (
    "BANK-ACCT-1234",
    "CHASUS33XXX",
    "BKTRIBSPXXX",
    "HLBKRSEOSEX",
    "DEUTDEFFXXX",
)

COUNTERPARTY_MISMATCHES: tuple[str, ...] = (
    "GOLDENGATE-501",
    "SSBMLWBIXXX",
    "BKLNGB2LXXX",
    "ICRAINB4XXX",
    "HSBCGB2LXXX",
)

COUNTERPARTY_VARIANTS: dict[str, str] = {
    "BANK-ACCT-1234": "BANK-ACCT-12",
    "CHASUS33XXX": "CHASUS33",
    "BKTRIBSPXXX": "BKTRIBSP",
    "HLBKRSEOSEX": "HLBKRSEOS",
    "DEUTDEFFXXX": "DEUTDEFF",
}

CORRUPTION_KINDS: tuple[str, ...] = (
    "amount_precision",
    "invalid_ccy",
    "malformed_date",
)


def _weighted(rng: random.Random, choices: tuple[str, ...],
              weights: tuple[float, ...]) -> str:
    return rng.choices(list(choices), weights=list(weights), k=1)[0]


def _round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"))


def _amount_str(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _rand_amount(rng: random.Random, lo_cents: int) -> str:
    return _amount_str(rng.randint(lo_cents, 99_999_999))


def _rand_amount_delta(rng: random.Random, lo: float, hi: float) -> Decimal:
    return Decimal(str(rng.uniform(lo, hi)))


def _business_day(rng: random.Random) -> datetime:
    start = datetime(2025, 6, 1)
    end = datetime(2026, 12, 31)
    d = start + timedelta(days=rng.randint(0, (end - start).days))
    if d.weekday() >= 5:
        d += timedelta(days=(7 - d.weekday()))
    return d


def _booked_at(rng: random.Random, value_date: datetime, lag_days: int) -> str:
    booked = value_date - timedelta(days=lag_days)
    hh = rng.randint(0, 23)
    mm = rng.randint(0, 59)
    ss = rng.randint(0, 59)
    return f"{booked.strftime('%Y-%m-%d')}T{hh:02d}:{mm:02d}:{ss:02d}Z"


def _ref(rng: random.Random, prefix: str, seq: int) -> str:
    return f"{prefix}-{rng.choice(('REF', 'PAY', 'INS'))}-{seq:06d}"


def _base_pair(
    rng: random.Random, seq: int, fx: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Draw a mutually-consistent ledger/statement pair (no exceptions).

    One beneficiary/counterparty/value_date/amount family is drawn once and
    shared by both sides — the pair is the same payment viewed from the
    ledger and the statement; only injected exceptions diverge the sides.
    """
    bene = rng.choice(BENEFICIARY_NAMES)
    cpty = rng.choice(COUNTERPARTIES)
    if fx:
        fccy = _weighted(rng, FOREIGN_CCYS, FOREIGN_CCY_WEIGHTS)
        rate = Decimal(str(rng.uniform(*FX_RATE_BANDS[fccy])))
        foreign_cents = rng.randint(20_000, 99_999_999)
        local = _round2(Decimal(foreign_cents) / 100 / rate)
        if local < 100:
            local = Decimal(100)
        local_cents = int(local * 100)
        famount = _amount_str(foreign_cents)
        lamount = _amount_str(local_cents)
        # Implied rate from the ROUNDED amounts — the "effective" booking rate.
        implied = Decimal(foreign_cents) / Decimal(local_cents)
        stated = float(implied.quantize(Decimal("0.0001")))
        if rng.random() < 0.5:
            ledger, statement = (
                {"message_type": _weighted(rng, tuple(MESSAGE_TYPE_PRIORS_LEDGER),
                                           tuple(MESSAGE_TYPE_PRIORS_LEDGER.values())),
                 "ref": _ref(rng, "OUR", seq),
                 "amount": lamount, "ccy": HOME_CCY,
                 "value_date": "", "counterparty": cpty,
                 "beneficiary": bene, "fx_rate": None},
                {"message_type": _weighted(rng, tuple(MESSAGE_TYPE_PRIORS_STATEMENT),
                                           tuple(MESSAGE_TYPE_PRIORS_STATEMENT.values())),
                 "ref": _ref(rng, "CP", seq),
                 "amount": famount, "ccy": fccy,
                 "value_date": "", "counterparty": cpty,
                 "beneficiary": bene, "fx_rate": stated},
            )
        else:
            ledger, statement = (
                {"message_type": _weighted(rng, tuple(MESSAGE_TYPE_PRIORS_LEDGER),
                                           tuple(MESSAGE_TYPE_PRIORS_LEDGER.values())),
                 "ref": _ref(rng, "OUR", seq),
                 "amount": famount, "ccy": fccy,
                 "value_date": "", "counterparty": cpty,
                 "beneficiary": bene, "fx_rate": stated},
                {"message_type": _weighted(rng, tuple(MESSAGE_TYPE_PRIORS_STATEMENT),
                                           tuple(MESSAGE_TYPE_PRIORS_STATEMENT.values())),
                 "ref": _ref(rng, "CP", seq),
                 "amount": lamount, "ccy": HOME_CCY,
                 "value_date": "", "counterparty": cpty,
                 "beneficiary": bene, "fx_rate": None},
            )
    else:
        amt = _rand_amount(rng, 10_000)
        msg_l = _weighted(rng, tuple(MESSAGE_TYPE_PRIORS_LEDGER),
                          tuple(MESSAGE_TYPE_PRIORS_LEDGER.values()))
        msg_s = _weighted(rng, tuple(MESSAGE_TYPE_PRIORS_STATEMENT),
                          tuple(MESSAGE_TYPE_PRIORS_STATEMENT.values()))
        ledger = {
            "message_type": msg_l, "ref": _ref(rng, "OUR", seq),
            "amount": amt, "ccy": HOME_CCY, "value_date": "",
            "counterparty": cpty, "beneficiary": bene, "fx_rate": None,
        }
        statement = {
            "message_type": msg_s, "ref": _ref(rng, "CP", seq),
            "amount": amt, "ccy": HOME_CCY, "value_date": "",
            "counterparty": cpty, "beneficiary": bene, "fx_rate": None,
        }
    vd = _business_day(rng)
    lag = rng.randint(0, 2)
    for side in (ledger, statement):
        side["value_date"] = vd.strftime("%Y-%m-%d")
    ledger["booked_at"] = _booked_at(rng, vd, lag)
    return ledger, statement


def _apply_match_noise(
    rng: random.Random, difficulty: float,
    ledger: dict[str, Any], statement: dict[str, Any],
) -> None:
    """Near-miss distractors that normalization/tolerance must absorb."""
    p = 0.15 + 0.45 * min(1.0, difficulty / 2.0)
    if rng.random() >= p:
        return
    kind = rng.choice(("amount", "beneficiary", "counterparty"))
    if kind == "amount":
        hi = 0.002 + 0.002 * min(1.0, difficulty / 2.0)
        delta = _rand_amount_delta(rng, 0.0005, hi)
        a = Decimal(statement["amount"])
        statement["amount"] = _amount_str(int(_round2(a * (1 + delta)) * 100))
    elif kind == "beneficiary":
        statement["beneficiary"] = _case_variant(rng, ledger["beneficiary"])
    else:
        statement["counterparty"] = _case_variant(rng, ledger["counterparty"])


def _case_variant(rng: random.Random, name: str) -> str:
    if rng.random() < 0.5:
        return " ".join(name.upper().split())
    return name.lower().strip()


def _inject(
    rng: random.Random, difficulty: float, exception_type: str,
    ledger: dict[str, Any], statement: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Mutate the pair to realize the injected exception. Returns the new
    statement (None only for MISSING_MESSAGE)."""
    if exception_type == "MISSING_MESSAGE":
        return None
    assert statement is not None

    if exception_type == "AMOUNT_MISMATCH":
        lo = max(0.006, 0.05 - 0.044 * min(1.0, difficulty / 2.0))
        delta = _rand_amount_delta(rng, lo, 0.05)
        a = Decimal(statement["amount"])
        statement["amount"] = _amount_str(int(_round2(a * (1 + delta)) * 100))
        return statement

    if exception_type == "FX_CONVERSION_ERROR":
        fccy = _weighted(rng, FOREIGN_CCYS, FOREIGN_CCY_WEIGHTS)
        true_rate = Decimal(str(rng.uniform(*FX_RATE_BANDS[fccy])))
        lo = max(0.008, 0.05 - 0.042 * min(1.0, difficulty / 2.0))
        phi = _rand_amount_delta(rng, lo, 0.05)
        wrong_rate = float((true_rate * (1 + phi)).quantize(Decimal("0.0001")))
        foreign_cents = rng.randint(20_000, 99_999_999)
        local_cents = int(_round2(Decimal(foreign_cents) / 100 / true_rate) * 100)
        if local_cents < 10_000:
            local_cents = 10_000
        famount = _amount_str(foreign_cents)
        lamount = _amount_str(local_cents)
        if rng.random() < 0.5:
            ledger["amount"], ledger["ccy"], ledger["fx_rate"] = lamount, HOME_CCY, None
            statement["amount"], statement["ccy"], statement["fx_rate"] = famount, fccy, wrong_rate
        else:
            ledger["amount"], ledger["ccy"], ledger["fx_rate"] = famount, fccy, wrong_rate
            statement["amount"], statement["ccy"], statement["fx_rate"] = lamount, HOME_CCY, None
        return statement

    if exception_type == "BENEFICIARY_MISMATCH":
        statement["beneficiary"] = rng.choice(BENEFICIARY_MISMATCH_NAMES)
        return statement

    if exception_type == "COUNTERPARTY_MISMATCH":
        statement["counterparty"] = rng.choice(COUNTERPARTY_MISMATCHES)
        return statement

    if exception_type == "PARTIAL_MATCH":
        if rng.random() < 0.5:
            base = ledger["beneficiary"]
            if base in BENEFICIARY_VARIANTS:
                statement["beneficiary"] = BENEFICIARY_VARIANTS[base]
        else:
            base = ledger["counterparty"]
            if base in COUNTERPARTY_VARIANTS:
                statement["counterparty"] = COUNTERPARTY_VARIANTS[base]
        return statement

    if exception_type == "VALUE_DATE_MISMATCH":
        vd = datetime.strptime(ledger["value_date"], "%Y-%m-%d")
        variant = rng.choice(("weekend", "shifted", "late_booking"))
        if variant == "weekend":
            sat = vd + timedelta(days=(5 - vd.weekday()))
            statement["value_date"] = sat.strftime("%Y-%m-%d")
        elif variant == "shifted":
            shift = rng.randint(3, 7)
            nd = vd + timedelta(days=shift)
            if nd.weekday() >= 5:
                nd += timedelta(days=(7 - nd.weekday()))
            statement["value_date"] = nd.strftime("%Y-%m-%d")
        else:
            lag = rng.randint(3, 5)
            ledger["booked_at"] = _booked_at(rng, vd, lag)
        return statement

    if exception_type == "DUPLICATE":
        statement["ref"] = ledger["ref"]
        return statement

    if exception_type == "FIELD_CORRUPTION":
        kind = rng.choice(CORRUPTION_KINDS)
        if kind == "amount_precision":
            a = Decimal(statement["amount"])
            statement["amount"] = f"{a:.3f}"
        elif kind == "invalid_ccy":
            statement["ccy"] = rng.choice(("EURO", "usdx", "ZZZ"))
        else:
            statement["value_date"] = rng.choice(
                ("2026/08/07", "07-08-2026", "2026-13-01")
            )
        return statement

    raise ValueError(f"unknown exception type: {exception_type}")


def _expected_for(exception_type: str | None, difficulty: float) -> dict[str, Any]:
    if exception_type is None:
        return {
            "verdict": "MATCH",
            "exception_type": None,
            "severity": taxonomy.MATCH_SEVERITY,
            "explanation": taxonomy.EXPLANATION_BY_EXCEPTION[None],
            "resolution": taxonomy.MATCH_RESOLUTION,
        }
    return {
        "verdict": "EXCEPTION",
        "exception_type": exception_type,
        "severity": taxonomy.SEVERITY_BY_EXCEPTION[exception_type],
        "explanation": taxonomy.EXPLANATION_BY_EXCEPTION[exception_type],
        "resolution": taxonomy.RESOLUTION_BY_EXCEPTION[exception_type],
    }


def _oracle_agrees(task: Task) -> bool:
    verdict = verify_task(task)
    return (
        verdict["verdict"] == task.expected["verdict"]
        and verdict["exception_type"] == task.expected["exception_type"]
    )


def _make_task(
    rng: random.Random, i: int, seed: int, difficulty: float, exception_type: str | None
) -> Task:
    for _ in range(_MAX_REBUILD_TRIES):
        ledger, statement = _base_pair(rng, i + 1, fx=False)
        statement = _inject(rng, difficulty, exception_type, ledger, statement) \
            if exception_type else statement
        if exception_type is None:
            _apply_match_noise(rng, difficulty, ledger, statement)
        task = Task(
            task_id=f"recon-{i + 1:06d}",
            seed=seed,
            difficulty=difficulty,
            ledger=ledger,
            statement=statement,
            expected=_expected_for(exception_type, difficulty),
        )
        if _oracle_agrees(task):
            return task
    # Deterministic fallback: a trivially-agreeing plain MATCH pair.
    amount = _amount_str(rng.randint(10_000, 99_999_999))
    vd = _business_day(rng)
    lag = rng.randint(0, 2)
    ledger = {
        "message_type": "INTERNAL", "ref": f"OUR-REF-{i + 1:06d}",
        "amount": amount, "ccy": HOME_CCY, "value_date": vd.strftime("%Y-%m-%d"),
        "counterparty": "BANK-ACCT-1234", "beneficiary": "ACME CORPORATION",
        "fx_rate": None, "booked_at": _booked_at(rng, vd, lag),
    }
    statement = {
        "message_type": "MT940", "ref": f"CP-REF-{i + 1:06d}",
        "amount": amount, "ccy": HOME_CCY, "value_date": vd.strftime("%Y-%m-%d"),
        "counterparty": "BANK-ACCT-1234", "beneficiary": "ACME CORPORATION",
        "fx_rate": None,
    }
    return Task(
        task_id=f"recon-{i + 1:06d}",
        seed=seed,
        difficulty=difficulty,
        ledger=ledger,
        statement=statement,
        expected=_expected_for(None, difficulty),
    )


def _sample_difficulty(
    rng: random.Random, difficulty_prior_mean: float, difficulty_prior_scale: float
) -> float:
    d = rng.gauss(difficulty_prior_mean, 0.35 * difficulty_prior_scale)
    return round(min(MAX_DIFFICULTY, max(MIN_DIFFICULTY, d)), 4)


def _exception_probability(difficulty: float) -> float:
    return 0.25 + 0.45 * min(1.0, difficulty / MAX_DIFFICULTY) ** 0.7


def generate_tasks(
    n_tasks: int,
    seed: int,
    difficulty_prior_mean: float = 0.7,
    difficulty_prior_scale: float = 1.0,
    exception_mix: dict[str, float] | None = None,
    random_state: random.Random | None = None,
) -> list[Task]:
    """Generate ``n_tasks`` deterministic reconciliation tasks.

    Same ``seed`` (or same ``random_state``) -> identical task list.
    """
    rng = random_state if random_state is not None else random.Random(seed)
    mix = dict(exception_mix or DEFAULT_EXCEPTION_MIX)
    mix_types = tuple(mix)
    mix_weights = tuple(float(mix[t]) for t in mix_types)

    tasks: list[Task] = []
    for i in range(n_tasks):
        difficulty = _sample_difficulty(rng, difficulty_prior_mean, difficulty_prior_scale)
        if rng.random() < _exception_probability(difficulty):
            exception_type = rng.choices(mix_types, weights=mix_weights, k=1)[0]
        else:
            exception_type = None
        tasks.append(_make_task(rng, i, seed, difficulty, exception_type))
    return tasks
