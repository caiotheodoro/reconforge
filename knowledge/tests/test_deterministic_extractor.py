"""Deterministic extractor tests: hermetic, no API, no network."""

import pytest

from reconforge_knowledge.deterministic_extractor import (
    extract_document,
    extract_documents,
)
from reconforge_knowledge.schema import ENTITY_TYPES, RELATION_TYPES, validate_extraction

SAMPLE_DOC = """
SWIFT MT103 is the single customer credit transfer. A customer credit transfer
does not carry a cover payment: the MT202 COV moves the cover funds between
correspondent nostro accounts, sent to the reimbursing bank. Plain MT202 must
not be used as the cover for a customer credit transfer since 2009. Herstatt
risk is foreign-exchange settlement risk; CLS was created after the Herstatt
bank failure and mitigates Herstatt risk through payment versus payment (PvP)
settlement. Value date conventions: FX spot settles T+2, equities T+1, SEPA
credit transfers D+1. Straight through processing (STP) requires clean data.
The MT940 end-of-day statement and camt.053 are counterparts; MT300 confirms
an FX trade.
"""


def test_extract_document_is_non_empty_and_schema_valid():
    triples = extract_document(SAMPLE_DOC, source="test.md")
    assert len(triples.entities) > 0
    assert len(triples.relations) > 0
    # contract: every relation uses only CONTRACTS.md relation types
    for rel in triples.relations:
        assert rel.relation in RELATION_TYPES
    for ent in triples.entities:
        assert ent.type in ENTITY_TYPES
    # explicit validation passes (would raise otherwise)
    validate_extraction(triples.entities, triples.relations)


def test_extract_document_is_deterministic():
    a = extract_document(SAMPLE_DOC, source="test.md")
    b = extract_document(SAMPLE_DOC, source="test.md")
    assert a.to_dict() == b.to_dict()


def test_extract_documents_dedupes_entities_and_relations():
    doc_a = "MT103 is the single customer credit transfer sent to the beneficiary."
    doc_b = "MT103 does not carry a cover payment; MT202 COV moves the cover."
    merged = extract_documents([("a.md", doc_a), ("b.md", doc_b)])
    mt103_entities = [e for e in merged.entities if e.name == "MT103"]
    assert len(mt103_entities) == 1
    assert mt103_entities[0].type == "MessageType"
    triple_keys = {(r.head, r.relation, r.tail) for r in merged.relations}
    assert ("MT103", "COVERS", "SingleCustomerCreditTransfer") in triple_keys


def test_extract_document_without_message_types_is_empty_but_valid():
    triples = extract_document("nothing relevant here", source="empty.md")
    assert isinstance(triples.entities, list)
    assert isinstance(triples.relations, list)


def test_gold_loader_is_schema_valid():
    from reconforge_knowledge.deterministic_extractor import load_gold_triples

    gold = load_gold_triples()
    assert len(gold.relations) > 0
    for rel in gold.relations:
        assert rel.relation in RELATION_TYPES
        assert rel.confidence > 0.0
    validate_extraction(gold.entities, gold.relations)
