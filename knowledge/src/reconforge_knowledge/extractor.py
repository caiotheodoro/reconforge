"""LLM-based GraphRAG extraction (DeepSeek, OpenAI-compatible).

One doc -> typed entities + typed relations with evidence and confidence.
- Chunks large docs at ~2000 tokens with overlap.
- Retries via tenacity on rate-limit/5xx (see ``_llm.chat_json``).
- Robust JSON parsing (code fences stripped).
- Per-chunk fallback to :mod:`reconforge_knowledge.deterministic_extractor`
  when the API fails entirely.
- Results cached in ``data/extracted.json`` (re-runs never re-call the API).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ._llm import chat_json, llm_available
from .deterministic_extractor import extract_document as _deterministic_doc
from .schema import Entity, Relation, Triples, validate_extraction, validate_relation

logger = logging.getLogger("reconforge_knowledge.extractor")

DEFAULT_CHUNK_TOKENS = 2000
DEFAULT_CHUNK_OVERLAP = 200

SYSTEM_PROMPT = """\
You are an information-extraction engine for a financial back-office
reconciliation knowledge graph (ReconForge). Extract typed entities and
typed relations from the document, strictly following the schema.

ENTITY TYPES (exactly one per entity):
- MessageType: a SWIFT/ISO message type, e.g. MT103, MT202, MT300, MT940, \
pacs.008, pacs.009, camt.053, camt.054, INTERNAL.
- Field: a field or attribute inside a message (tag or label), e.g. \
"field-32A ValueDateAndAmount", "GrpHdr GroupHeader".
- PaymentInstruction: a payment product or instruction flow, e.g. customer \
credit transfer, cover payment, general financial institution transfer.
- SettlementSystem: settlement/payment infrastructure, e.g. CLS, SWIFT \
network, TARGET2, Fedwire.
- Risk: a risk, e.g. Herstatt risk, settlement risk, counterparty risk.
- Rule: a convention or processing rule, e.g. cut-off time, late-value-date \
rule, T+1/T+2 convention.
- Instrument: a financial instrument or artifact, e.g. FX trade, trade \
confirmation, account statement, bond.
- Workflow: a process, e.g. straight-through processing (STP), interest \
adjustment, deferral to next business day.
- Currency: an ISO currency, e.g. USD, EUR, GBP.
- DateConvention: a date convention, e.g. value date, T+1, T+2.

RELATION TYPES (exactly one per relation, head and tail are entity NAMES):
- COVERS: head represents/carries the tail (e.g. MT103 COVERS \
CustomerCreditTransfer, MT940 COVERS AccountStatement).
- REQUIRES: head needs the tail to work (e.g. STP REQUIRES clean data).
- HAS_FIELD: a MessageType has a Field.
- CONFLICTS_WITH: head and tail are incompatible; also use it for stated \
negations (e.g. MT103 CONFLICTS_WITH CoverPayment encodes "MT103 does not \
require a cover payment").
- TRIGGERS: head causes/leads to tail (e.g. LateValueDateRule TRIGGERS \
ValueDateMismatchRisk).
- APPLIES_TO: head applies to tail (e.g. ValueDate APPLIES_TO \
CustomerCreditTransfer, a cut-off APPLIES_TO STP).
- MITIGATES: head reduces the risk tail (e.g. CLS MITIGATES HerstattRisk).
- RELATED_TO: general domain association.
- COUNTERPART_OF: head and tail are equivalent counterparts in different \
formats (e.g. MT103 COUNTERPART_OF pacs.008, MT940 COUNTERPART_OF camt.053).

RULES:
- Entity names: short canonical names (e.g. "CustomerCreditTransfer").
- Extract ONLY facts stated in the document; do not invent.
- Every relation endpoint must appear in the entities list of the same chunk.
- evidence: a short verbatim quote from the document supporting the relation.
- confidence: 0.0-1.0, how certain you are that the document states this.
- Output JSON ONLY:
{"entities": [{"name": "...", "type": "...", "properties": {}}],
 "relations": [{"head": "...", "relation": "...", "tail": "...",
                "evidence": "...", "confidence": 0.9}]}
"""


def _chunk_tokens(text: str, target_tokens: int, overlap_tokens: int) -> List[str]:
    """Split text into ~target_tokens chunks with overlap.

    Token count approximated by characters/4; split on paragraph/sentence
    boundaries when possible.
    """
    if len(text) <= target_tokens * 4:
        return [text]
    chunks: List[str] = []
    step = target_tokens * 4 - overlap_tokens * 4
    i = 0
    while i < len(text):
        end = min(i + target_tokens * 4, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n\n", i, end), text.rfind(". ", i, end))
            if boundary > i + len(text) * 0.25:
                end = boundary + 1
        chunks.append(text[i:end])
        if end >= len(text):
            break
        i = max(end - overlap_tokens * 4, i + step if step > 0 else end)
    return chunks


@dataclass(slots=True)
class ExtractionResult:
    triples: Triples
    mode: str
    api_calls: int = 0
    chunks: int = 0
    per_doc: Dict[str, Triples] = None  # type: ignore[assignment]

    def stats(self) -> Dict[str, int]:
        return {
            "entities": len(self.triples.entities),
            "relations": len(self.triples.relations),
            "api_calls": self.api_calls,
            "chunks": self.chunks,
        }


def _parse_chunk_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl:].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in reply: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])


def _coerce_chunk(raw: Dict[str, Any], source: str) -> Triples:
    entities: List[Entity] = []
    for e in raw.get("entities", []):
        entities.append(
            Entity(
                name=str(e["name"]).strip(),
                type=str(e.get("type", "")).strip(),
                properties=dict(e.get("properties") or {}),
            )
        )
    relations: List[Relation] = []
    for r in raw.get("relations", []):
        relations.append(
            Relation(
                head=str(r["head"]).strip(),
                relation=str(r["relation"]).strip(),
                tail=str(r["tail"]).strip(),
                evidence=str(r.get("evidence") or ""),
                confidence=float(r.get("confidence", 0.7)),
                source=source,
            )
        )
    validate_extraction(entities, relations)
    return Triples(entities=entities, relations=relations)


def _extract_chunk_llm(chunk: str, source: str) -> Triples:
    reply = chat_json(SYSTEM_PROMPT, f"Document source: {source}\n\n{chunk}")
    return _coerce_chunk(reply, source)


def _extract_chunk_safe(chunk: str, source: str) -> Tuple[Triples, str, int]:
    """LLM extraction with deterministic fallback. Returns (triples, mode, api_calls)."""
    if llm_available():
        try:
            return _extract_chunk_llm(chunk, source), "llm", 1
        except Exception as exc:  # noqa: BLE001 - fallback is the contract
            logger.warning("LLM extraction failed for %s, falling back: %s", source, exc)
    return _deterministic_doc(chunk, source=source), "deterministic", 0


def _merge(chunk_triples: Sequence[Triples]) -> Triples:
    entities: Dict[Tuple[str, str], Entity] = {}
    relations: Dict[Tuple[str, str, str], Relation] = {}
    for triples in chunk_triples:
        for e in triples.entities:
            entities.setdefault((e.name, e.type), e)
        for r in triples.relations:
            key = (r.head, r.relation, r.tail)
            if key not in relations:
                relations[key] = r
            elif r.confidence > relations[key].confidence:
                relations[key] = r
    merged = Triples(entities=list(entities.values()), relations=list(relations.values()))
    validate_extraction(merged.entities, merged.relations)
    return merged


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
# Bump when extraction logic/typings change so stale caches are invalidated.
CACHE_VERSION = 2


def _cache_key(sources: Sequence[Tuple[str, str]], offline: bool) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"v{CACHE_VERSION}|offline={offline}".encode())
    for ref, text in sorted(sources, key=lambda item: item[0]):
        hasher.update(f"\n{ref}\n{len(text)}\n".encode())
        hasher.update(hashlib.sha256(text.encode()).digest())
    return hasher.hexdigest()[:16]


def _cache_path_for(key: str) -> Path:
    here = Path(__file__).resolve().parent.parent.parent
    return here / "data" / f"extracted-{key}.json"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def extract_documents(
    docs: Iterable[Tuple[str, str]],
    *,
    offline: bool = False,
    use_cache: bool = True,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP,
) -> ExtractionResult:
    """Extract typed entities/relations from (source_ref, text) pairs.

    ``offline=True`` uses only the deterministic extractor (no API).
    Cached results (data/extracted-*.json, keyed by content+mode) are
    reused when possible so re-runs do not re-call the API.
    """
    docs = list(docs)
    key = _cache_key(docs, offline)
    cache_path = _cache_path_for(key)

    if use_cache and cache_path.exists():
        logger.info("reusing extraction cache %s", cache_path.name)
        with cache_path.open() as fh:
            payload = json.load(fh)
        entities = [Entity.from_dict(e) for e in payload["entities"]]
        relations = [Relation.from_dict(r) for r in payload["relations"]]
        return ExtractionResult(
            triples=Triples(entities=entities, relations=relations),
            mode=payload.get("mode", "cache"),
        )

    if offline:
        merged = _merge([_deterministic_doc(text, source=ref) for ref, text in docs])
        result = ExtractionResult(triples=merged, mode="offline")
    else:
        chunk_triples: List[Triples] = []
        api_calls = 0
        chunk_count = 0
        for ref, text in docs:
            for chunk in _chunk_tokens(text, chunk_tokens, overlap_tokens):
                chunk_count += 1
                triples, mode, calls = _extract_chunk_safe(chunk, ref)
                api_calls += calls
                logger.debug("chunk %s (%s): %d entities", ref, mode, len(triples.entities))
                chunk_triples.append(triples)
        merged = _merge(chunk_triples)
        result = ExtractionResult(
            triples=merged, mode="mixed", api_calls=api_calls, chunks=chunk_count
        )

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CACHE_VERSION,
            "mode": result.mode,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_key": key,
            "entities": [e.to_dict() for e in result.triples.entities],
            "relations": [r.to_dict() for r in result.triples.relations],
        }
        with cache_path.open("w") as fh:
            json.dump(payload, fh, indent=2)
        logger.info("wrote extraction cache %s", cache_path.name)
    return result


def read_extracted(path: Path) -> Triples:
    """Load a previously written extraction JSON (any cache file)."""
    with Path(path).open() as fh:
        payload = json.load(fh)
    entities = [Entity.from_dict(e) for e in payload["entities"]]
    relations = [Relation.from_dict(r) for r in payload["relations"]]
    return Triples(entities=entities, relations=relations)


def merge_result(
    entities: Sequence[Entity],
    relations: Sequence[Relation],
    mode: str,
    api_calls: int = 0,
    chunks: int = 0,
) -> ExtractionResult:
    """Merge raw entity/relation lists into a validated ExtractionResult."""
    from .schema import Triples as _Triples

    merged = _merge([_Triples(entities=list(entities), relations=list(relations))])
    return ExtractionResult(
        triples=merged, mode=mode, api_calls=api_calls, chunks=chunks
    )


def latest_cache_file() -> Optional[Path]:
    data_dir = _cache_path_for("x").parent
    if not data_dir.exists():
        return None
    matches = sorted(data_dir.glob("extracted-*.json"), key=os.path.getmtime, reverse=True)
    return matches[0] if matches else None


def resolve_corpus_dir() -> Path:
    """docs/corpus/ when present (real corpus), else knowledge/sample_corpus/."""
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent.parent
    repo = here.parent
    corpus = repo / "docs" / "corpus"
    if corpus.is_dir() and list(corpus.glob("*.md")):
        return corpus
    sample = here / "sample_corpus"
    return sample


def validate_relation_types(relations: Sequence[Relation]) -> None:
    """Exit-gate helper: assert every relation type is in the CONTRACTS.md set."""
    for r in relations:
        validate_relation(r)
