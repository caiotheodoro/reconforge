"""Schema tests: constants must match CONTRACTS.md exactly (hermetic, offline)."""

import pytest

from reconforge_knowledge import ENTITY_TYPES, RELATION_TYPES
from reconforge_knowledge.schema import (
    Entity,
    Relation,
    Triples,
    validate_extraction,
    validate_relation,
)

CONTRACTS_ENTITY_TYPES = {
    "MessageType", "Field", "PaymentInstruction", "SettlementSystem",
    "Risk", "Rule", "Instrument", "Workflow", "Currency", "DateConvention",
}

CONTRACTS_RELATION_TYPES = {
    "COVERS", "REQUIRES", "HAS_FIELD", "CONFLICTS_WITH", "TRIGGERS",
    "APPLIES_TO", "MITIGATES", "RELATED_TO", "COUNTERPART_OF",
}


def test_entity_types_match_contracts():
    assert set(ENTITY_TYPES) == CONTRACTS_ENTITY_TYPES
    assert len(ENTITY_TYPES) == 10


def test_relation_types_match_contracts():
    assert set(RELATION_TYPES) == CONTRACTS_RELATION_TYPES
    assert len(RELATION_TYPES) == 9


def test_validate_relation_rejects_unknown_type():
    rel = Relation(head="A", relation="FOLLOWS", tail="B")
    with pytest.raises(ValueError, match="unknown type"):
        validate_relation(rel)


def test_validate_extraction_rejects_dangling_endpoints():
    entities = [Entity(name="A", type="MessageType")]
    relations = [Relation(head="A", relation="COVERS", tail="Ghost")]
    with pytest.raises(ValueError, match="references an entity"):
        validate_extraction(entities, relations)


def test_relation_round_trip():
    rel = Relation(
        head="CLS", relation="MITIGATES", tail="HerstattRisk",
        evidence="quote", confidence=0.97, source="docs/corpus/settlement-risk.md",
    )
    restored = Relation.from_dict(rel.to_dict())
    assert restored == rel
    assert restored.triple_text == "CLS MITIGATES HerstattRisk"


def test_entity_dedup_by_name_and_type():
    a1 = Entity(name="MT103", type="MessageType")
    a2 = Entity(name="MT103", type="MessageType")
    b = Entity(name="MT103", type="Field")
    assert len({a1, a2, b}) == 2


def test_triples_constructor_validates():
    with pytest.raises(ValueError):
        Triples(
            entities=[Entity(name="A", type="MessageType")],
            relations=[Relation(head="A", relation="WIBBLE", tail="B")],
        )
