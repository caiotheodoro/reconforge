"""Gate tests: offline lexical verdicts with evidence chains (hermetic)."""

import pytest

from reconforge_knowledge.deterministic_extractor import extract_documents
from reconforge_knowledge.gate import GroundedGate, build_claim, ground, ground_sync
from reconforge_knowledge.schema import VERDICTS

DOC_SWIFT = """
MT103 is the single customer credit transfer. A customer credit transfer does
not carry a cover payment: the MT202 COV moves the cover funds between
correspondent nostro accounts. Plain MT202 must not be used as the cover for
a customer credit transfer since 2009. MT300 confirms an FX trade.
"""

DOC_RISK = """
Herstatt risk is foreign-exchange settlement risk. CLS was created after the
Herstatt bank failure and mitigates Herstatt risk through payment versus
payment (PvP) settlement.
"""


@pytest.fixture(scope="module")
def gate():
    triples = extract_documents([("swift.md", DOC_SWIFT), ("risk.md", DOC_RISK)])
    return GroundedGate(triples)


def test_support_verdict_with_evidence_chain(gate):
    verdict = gate.ground_claim("Which system mitigates Herstatt risk?", use_llm=False)
    assert verdict.verdict == "SUPPORT"
    assert verdict.mode == "lexical"
    assert len(verdict.evidence) >= 1
    entry = verdict.evidence[0]
    assert entry["triple"] == "CLS MITIGATES HerstattRisk"
    assert entry["source"] == "risk.md"
    assert 0.0 <= entry["confidence"] <= 1.0
    assert "retrieval_score" in entry
    # audit trail of what was consulted
    assert len(verdict.retrieved) >= 1


def test_contradict_verdict(gate):
    verdict = gate.ground_claim(
        "Does MT103 require cover for a customer credit transfer?", use_llm=False
    )
    assert verdict.verdict == "CONTRADICT"
    assert verdict.mode == "lexical"
    assert any("CONFLICTS_WITH" in e["triple"] for e in verdict.evidence)


def test_unknown_claim_is_silent(gate):
    verdict = gate.ground_claim(
        "The moon is made of green cheese in the FX market", use_llm=False
    )
    assert verdict.verdict == "SILENT"
    assert isinstance(verdict.reason, str) and verdict.reason


def test_all_verdicts_schema_valid(gate):
    claims = [
        "Which system mitigates Herstatt risk?",
        "Does MT103 require cover for a customer credit transfer?",
        "MT300 confirms an FX trade",
        "The moon is made of green cheese",
    ]
    for verdict in gate.ground_many(claims):
        assert verdict.verdict in VERDICTS
        assert isinstance(verdict.evidence, list)
        for entry in verdict.evidence:
            assert "triple" in entry and "source" in entry and "confidence" in entry


def test_ground_seam_returns_system_contract_dict(gate):
    pair = {
        "task_id": "recon-000001",
        "ledger": {"message_type": "MT103", "amount": "1250.00", "ccy": "USD",
                   "value_date": "2026-08-07"},
        "statement": {"message_type": "MT940", "amount": "1250.00", "ccy": "USD",
                      "value_date": "2026-08-08"},
    }
    provisional = {"verdict": "EXCEPTION", "exception_type": "VALUE_DATE_MISMATCH",
                   "severity": "MEDIUM", "reason": "late value date"}
    result = ground_sync(pair, provisional, use_llm=False)
    assert isinstance(result, dict)
    assert result["verdict"] in VERDICTS
    assert "evidence" in result and isinstance(result["evidence"], list)
    assert "reason" in result and isinstance(result["reason"], str)
    assert result["gated"] is True


def test_ground_seam_is_awaitable():
    import asyncio

    pair = {"ledger": {"message_type": "MT103"}, "statement": {"message_type": "MT940"}}
    provisional = {"verdict": "MATCH", "exception_type": None}
    result = asyncio.run(ground(pair, provisional, use_llm=False))
    assert result["verdict"] in VERDICTS


def test_build_claim_from_pydantic_style_object():
    class D:
        def __init__(self, data):
            self._data = data

        def model_dump(self):
            return self._data

    pair = D({"ledger": {"message_type": "MT202", "amount": "99.00", "ccy": "EUR"},
              "statement": {"message_type": "MT940"}})
    provisional = D({"verdict": "MATCH", "exception_type": None})
    claim = build_claim(pair, provisional)
    assert "MT202" in claim and "MT940" in claim and "99.00" in claim
