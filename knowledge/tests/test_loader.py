"""Loader tests.

Unit tests use a fully mocked driver (hermetic, always run). A real-Neo4j
integration test is skipped when bolt://localhost:7687 is unreachable.
"""

import socket

import pytest

from reconforge_knowledge.deterministic_extractor import extract_document
from reconforge_knowledge.loader import Neo4jLoader


class FakeResult:
    def single(self):
        return self

    def value(self):
        return 7

    def __iter__(self):
        return iter(())


class FakeSession:
    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeDriver:
    def __init__(self):
        self.sessions = []
        self.closed = False

    def session(self, database=None):
        session = FakeSession()
        self.sessions.append(session)
        return session

    def close(self):
        self.closed = True


@pytest.fixture
def loader():
    ld = Neo4jLoader(uri="bolt://unused", auth=("neo4j", "unused"))
    ld.driver = FakeDriver()
    return ld


def test_ensure_schema_creates_unique_constraint(loader):
    loader.ensure_schema()
    sessions = loader.driver.sessions
    assert len(sessions) >= 2
    constraint_q = sessions[0].calls[0][0]
    index_q = sessions[1].calls[0][0]
    assert "CREATE CONSTRAINT" in constraint_q
    assert "IS UNIQUE" in constraint_q
    assert "CREATE INDEX" in index_q
    assert "(n.name, n.type)" in index_q


def test_load_issues_merge_for_every_entity_and_relation(loader):
    triples = extract_document(
        "MT103 is the single customer credit transfer. CLS mitigates Herstatt risk.",
        source="test.md",
    )
    stats = loader.load(triples)
    assert stats["entities"] == len(triples.entities)
    assert stats["relations"] == len(triples.relations)

    all_queries = [q for s in loader.driver.sessions for q, _ in s.calls]
    merges = [q for q in all_queries if "MERGE" in q]
    assert len(merges) >= len(triples.relations)
    assert any("name: $h" in q and "name: $t" in q for q in merges)


def test_load_twice_is_idempotent_in_queries(loader):
    triples = extract_document(
        "MT103 is the single customer credit transfer. CLS mitigates Herstatt risk.",
        source="test.md",
    )
    loader.load(triples)
    first = [q for s in loader.driver.sessions for q, _ in s.calls]
    loader.load(triples)
    second = [q for s in loader.driver.sessions for q, _ in s.calls]
    # second run issues exactly the same merge statements (idempotent design)
    assert second == first + first


def test_stats_and_wipe(loader):
    assert loader.stats() == {"nodes": 7, "edges": 7}
    loader.wipe()
    assert loader.driver.sessions[-1].calls[0][0].startswith("MATCH (n)")


def test_context_manager_closes_driver(loader):
    with loader:
        pass
    assert loader.driver.closed


# --------------------------------------------------------------------------- #
# Real-Neo4j integration (skipped when unreachable)
# --------------------------------------------------------------------------- #
def _neo4j_reachable() -> bool:
    try:
        from reconforge_knowledge._llm import get_neo4j_config

        cfg = get_neo4j_config()
        host = cfg["uri"].split("//")[-1].split(":")[0]
        port = int(cfg["uri"].split(":")[-1])
        with socket.create_connection((host, port), timeout=2):
            return True
    except (OSError, ValueError):
        return False


@pytest.mark.skipif(not _neo4j_reachable(), reason="Neo4j not reachable")
def test_real_neo4j_load_is_idempotent():
    neo4j_driver = pytest.importorskip("neo4j")
    from reconforge_knowledge.deterministic_extractor import extract_document
    from reconforge_knowledge.loader import Neo4jLoader

    triples = extract_document(
        "MT103 is the single customer credit transfer. CLS mitigates Herstatt risk.",
        source="test.md",
    )
    with Neo4jLoader() as loader:
        loader.wipe()
        loader.load(triples)
        first = loader.stats()
        loader.load(triples)
        second = loader.stats()
        loader.wipe()
    assert first == second
    assert first["nodes"] == len(triples.entities)
    assert first["edges"] == len(triples.relations)
