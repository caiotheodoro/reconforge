"""reconforge_knowledge: GraphRAG extraction, Neo4j loader, grounded gate.

This package is the retrieval layer of ReconForge. It extracts typed
entities/relations from the domain corpus (docs/corpus), loads them into
Neo4j, and grounds decision claims against the graph via a verdict gate
(SUPPORT / CONTRADICT / SILENT) with auditable evidence chains.
"""

__version__ = "0.1.0"

from .schema import (
    ENTITY_TYPES,
    RELATION_TYPES,
    Entity,
    Relation,
    Triples,
    validate_extraction,
)

__all__ = [
    "__version__",
    "ENTITY_TYPES",
    "RELATION_TYPES",
    "Entity",
    "Relation",
    "Triples",
    "validate_extraction",
]
