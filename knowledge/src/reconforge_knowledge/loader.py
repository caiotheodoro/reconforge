"""Neo4j loader with idempotent MERGE semantics.

- ``ensure_schema()``: node-key constraint on (name, type) so MERGE on
  (name, type) is unique and idempotent.  (CONTRACTS.md asks for uniqueness
  on ``(Entity, name)`` and ``(Entity, type)``; type alone is not unique
  across nodes, so the composite node key is the faithful, loadable
  formulation — see DECISIONS.md.)
- ``load()``: MERGE entity nodes, then MERGE relationships with
  {evidence, confidence, source} properties. Running twice yields an
  identical graph.
- ``wipe()``: DETACH DELETE all nodes for a clean re-index.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from neo4j import GraphDatabase

from ._llm import get_neo4j_config
from .schema import Relation, Triples

logger = logging.getLogger("reconforge_knowledge.loader")

ENTITY_LABEL = "Entity"


class Neo4jLoader:
    def __init__(
        self,
        uri: Optional[str] = None,
        auth: Optional[Tuple[str, str]] = None,
        database: str = "neo4j",
    ) -> None:
        cfg = get_neo4j_config()
        self.uri = uri or cfg["uri"]
        self.auth = auth or tuple(cfg["auth"].split("/", 1))
        self.driver = GraphDatabase.driver(self.uri, auth=self.auth)
        self.database = database

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jLoader":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _run(self, query: str, **params: Any) -> Any:
        with self.driver.session(database=self.database) as session:
            return session.run(query, **params)

    # -- schema ------------------------------------------------------------ #
    def ensure_schema(self) -> None:
        # (name, type) node-key constraints require Enterprise Edition; on
        # Community we enforce name-uniqueness (entity names are unique across
        # types in this corpus) plus a composite index for MERGE performance.
        # See DECISIONS.md.
        self._run(
            f"CREATE CONSTRAINT entity_name_unique IF NOT EXISTS "
            f"FOR (n:{ENTITY_LABEL}) REQUIRE n.name IS UNIQUE"
        )
        self._run(
            f"CREATE INDEX entity_name_type_idx IF NOT EXISTS "
            f"FOR (n:{ENTITY_LABEL}) ON (n.name, n.type)"
        )

    # -- load -------------------------------------------------------------- #
    def load(self, triples: Triples, *, batch_size: int = 500) -> Dict[str, int]:
        """Idempotent load: MERGE on (name, type) + MERGE relationships."""
        self.ensure_schema()
        name_to_type = {e.name: e.type for e in triples.entities}
        with self.driver.session(database=self.database) as session:
            for entity in triples.entities:
                params = {"name": entity.name, "type": entity.type}
                result = session.run(
                    f"MERGE (n:{ENTITY_LABEL} {{name: $name, type: $type}}) "
                    "RETURN elementId(n)",
                    **params,
                )
                result.single()

            # relationships in batches of MERGE per pair+type
            relations = triples.relations
            for start in range(0, len(relations), batch_size):
                for rel in relations[start : start + batch_size]:
                    session.run(
                        f"MATCH (h:{ENTITY_LABEL} {{name: $h, type: $ht}}) "
                        f"MATCH (t:{ENTITY_LABEL} {{name: $t, type: $tt}}) "
                        f"MERGE (h)-[r:{rel.relation}]->(t) "
                        "ON CREATE SET r.evidence = $evidence, "
                        "r.confidence = $confidence, r.source = $source "
                        "ON MATCH SET r.evidence = $evidence, "
                        "r.confidence = $confidence, r.source = $source",
                        h=rel.head, ht=name_to_type[rel.head],
                        t=rel.tail, tt=name_to_type[rel.tail],
                        evidence=rel.evidence, confidence=rel.confidence,
                        source=rel.source,
                    )
        logger.info(
            "loaded %d entities, %d relations",
            len(triples.entities), len(relations),
        )
        return {"entities": len(triples.entities), "relations": len(relations)}

    # -- stats / wipe ------------------------------------------------------ #
    def stats(self) -> Dict[str, int]:
        with self.driver.session(database=self.database) as session:
            nodes = session.run(f"MATCH (n:{ENTITY_LABEL}) RETURN count(n)").single().value()
            rels = session.run(
                "MATCH ()-[r]->() RETURN count(r)"
            ).single().value()
        return {"nodes": int(nodes), "edges": int(rels)}

    def wipe(self) -> None:
        self._run("MATCH (n) DETACH DELETE n")
        logger.info("graph wiped")
