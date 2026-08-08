"""Schema definitions for the ReconForge knowledge graph.

Fixed by CONTRACTS.md ("Entity/relation schema for the knowledge graph").
Every extractor output and every gate verdict must validate against this
module before it leaves the package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

ENTITY_TYPES = frozenset(
    {
        "MessageType",
        "Field",
        "PaymentInstruction",
        "SettlementSystem",
        "Risk",
        "Rule",
        "Instrument",
        "Workflow",
        "Currency",
        "DateConvention",
    }
)

RELATION_TYPES = frozenset(
    {
        "COVERS",
        "REQUIRES",
        "HAS_FIELD",
        "CONFLICTS_WITH",
        "TRIGGERS",
        "APPLIES_TO",
        "MITIGATES",
        "RELATED_TO",
        "COUNTERPART_OF",
    }
)

VERDICTS = ("SUPPORT", "CONTRADICT", "SILENT")


@dataclass(slots=True)
class Entity:
    """A typed knowledge-graph entity (node)."""

    name: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:  # dedupe by (name, type) per CONTRACTS.md
        return hash((self.name, self.type))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Entity) and (self.name, self.type) == (
            other.name,
            other.type,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "type": self.type, "properties": dict(self.properties)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Entity":
        return cls(
            name=str(d["name"]).strip(),
            type=str(d.get("type", "")).strip(),
            properties=dict(d.get("properties") or {}),
        )


@dataclass(slots=True)
class Relation:
    """A typed, evidence-bearing edge between two entities."""

    head: str
    relation: str
    tail: str
    evidence: str = ""
    confidence: float = 0.6
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "head": self.head,
            "relation": self.relation,
            "tail": self.tail,
            "evidence": self.evidence,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Relation":
        return cls(
            head=str(d["head"]).strip(),
            relation=str(d["relation"]).strip(),
            tail=str(d["tail"]).strip(),
            evidence=str(d.get("evidence") or ""),
            confidence=float(d.get("confidence", 0.6)),
            source=str(d.get("source") or ""),
        )

    @property
    def triple_text(self) -> str:
        """Human-readable triple used by the vector index and the gate."""
        return f"{self.head} {self.relation} {self.tail}"


@dataclass(slots=True)
class Triples:
    """The whole corpus as a searchable triple collection."""

    relations: List[Relation] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate_extraction(self.entities, self.relations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relations": [r.to_dict() for r in self.relations],
        }


def validate_entity(e: Entity) -> None:
    if not e.name:
        raise ValueError(f"entity with empty name: {e!r}")
    if e.type not in ENTITY_TYPES:
        raise ValueError(
            f"entity {e.name!r} has unknown type {e.type!r}; "
            f"allowed: {sorted(ENTITY_TYPES)}"
        )


def validate_relation(r: Relation) -> None:
    if not r.head or not r.tail:
        raise ValueError(f"relation with empty head/tail: {r!r}")
    if r.relation not in RELATION_TYPES:
        raise ValueError(
            f"relation {r.head} -[{r.relation}]-> {r.tail} uses unknown type "
            f"{r.relation!r}; allowed: {sorted(RELATION_TYPES)}"
        )
    if not (0.0 <= r.confidence <= 1.0):
        raise ValueError(f"relation confidence out of range: {r.confidence!r}")


def validate_extraction(entities: List[Entity], relations: List[Relation]) -> None:
    """Raise ValueError if the extraction is not schema-valid.

    Also ensures relation endpoints exist as entities so the Neo4j MERGE
    never creates dangling nodes.
    """
    for e in entities:
        validate_entity(e)
    names = {e.name for e in entities}
    for r in relations:
        validate_relation(r)
        if r.head not in names or r.tail not in names:
            raise ValueError(
                f"relation {r.head} -[{r.relation}]-> {r.tail} references an "
                f"entity that is not in the extraction: {sorted(names)}"
            )
