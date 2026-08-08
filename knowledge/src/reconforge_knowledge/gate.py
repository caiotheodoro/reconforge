"""Grounded gate: claim -> SUPPORT | CONTRADICT | SILENT + evidence chain.

Pipeline: (1) embed claim, retrieve top-k triples via
:mod:`reconforge_knowledge.vector_index`; (2) build context = triples + doc
source refs; (3) verdict from the LLM judge when the API is available, else
a deterministic lexical matcher (token overlap with light stemming).

The evidence chain always lists the actual triples (head-relation-tail +
source doc) used, so the decision pipeline can show an auditable trail.

``ground(pair, provisional)`` is the seam the system workstream's gate
service (system/src/reconforge_system/services/gate.py) awaits:
``result = await gate(pair=..., provisional=...)`` -> dict.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ._llm import llm_available
from .deterministic_extractor import extract_documents as _deterministic_extract
from .extractor import latest_cache_file, read_extracted
from .gate_llm import llm_judge
from .schema import VERDICTS, Relation, Triples
from .vector_index import VectorIndex

logger = logging.getLogger("reconforge_knowledge.gate")

STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "do", "does", "did",
        "of", "in", "on", "at", "to", "for", "with", "and", "or", "but",
        "what", "which", "who", "how", "why", "when", "it", "its", "this",
        "that", "not", "no", "as", "by", "be", "has", "have", "had", "s",
        "than", "can", "will", "would", "should",
    }
)

SUPPORT_COVERAGE = 0.35
CONTRADICT_COVERAGE = 0.30
CONTRADICT_MIN_TOKENS = 2
CONFLICT_RELATION = "CONFLICTS_WITH"

# Claims phrased as *questions about relations* must not be CONTRADICTed by a
# CONFLICTS_WITH triple about two of their concepts.
RELATIONAL_QUERY_WORDS = frozenset(
    {"relation", "relate", "connect", "link", "difference", "between", "counterpart", "equivalent"}
)


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9.#]+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def _stem(word: str) -> str:
    if len(word) <= 4:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing"):
        base = word[:-3]
        return base + "e" if base.endswith("e") else base
    if word.endswith("ed"):
        return word[:-2] if not word[:-2].endswith("d") else word[:-1]
    if word.endswith("es"):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def _coverage(claim_tokens: Sequence[str], triple_tokens: Sequence[str]) -> Tuple[int, float]:
    claim_stemmed = {_stem(t) for t in claim_tokens}
    triple_stemmed = {_stem(t) for t in triple_tokens}
    if not claim_stemmed:
        return 0, 0.0
    overlap = len(claim_stemmed & triple_stemmed)
    return overlap, overlap / len(claim_stemmed)


@dataclass(slots=True)
class GroundedVerdict:
    claim: str
    verdict: str
    reason: str
    mode: str  # "llm" | "lexical"
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    retrieved: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "verdict": self.verdict,
            "reason": self.reason,
            "mode": self.mode,
            "evidence": self.evidence,
            "retrieved": self.retrieved,
        }


def _evidence_entry(rel: Relation, score: float) -> Dict[str, Any]:
    return {
        "triple": rel.triple_text,
        "head": rel.head,
        "relation": rel.relation,
        "tail": rel.tail,
        "source": rel.source,
        "confidence": rel.confidence,
        "evidence_quote": rel.evidence,
        "retrieval_score": score,
    }


def _entity_tokens(triples: Triples, name: str) -> List[str]:
    parts = [name]
    for entity in triples.entities:
        if entity.name == name:
            aliases = entity.properties.get("aliases")
            if aliases:
                if isinstance(aliases, str):
                    parts.append(aliases)
                else:
                    parts.extend(str(a) for a in aliases)
    return _tokens(" ".join(parts))


def _triple_tokens(triples: Triples, rel: Relation) -> List[str]:
    """Triple tokens enriched with split camelCase names + entity aliases."""
    from .vector_index import split_name

    parts = [rel.triple_text, split_name(rel.head), split_name(rel.tail)]
    for entity in triples.entities:
        if entity.name in (rel.head, rel.tail):
            aliases = entity.properties.get("aliases")
            if aliases:
                if isinstance(aliases, str):
                    parts.append(aliases)
                else:
                    parts.extend(str(a) for a in aliases)
    return _tokens(" ".join(parts))


class GroundedGate:
    """Ground claims against the extracted triples."""

    def __init__(self, triples: Triples, vector_backend: Optional[str] = None) -> None:
        self.triples = triples
        self.index = VectorIndex(triples, backend=vector_backend)

    # ------------------------------------------------------------------ #
    def ground_claim(
        self,
        claim: str,
        top_k: int = 8,
        use_llm: Optional[bool] = None,
    ) -> GroundedVerdict:
        """Ground a single claim.

        ``use_llm``: None -> auto (LLM if available), True/False -> force.
        """
        retrieved = self.index.query(claim, top_k=top_k)
        trail = [_evidence_entry(rel, score) for rel, score in retrieved]

        if use_llm is None:
            use_llm = llm_available()
        if use_llm:
            try:
                judge = llm_judge(claim, retrieved)
                evidence = []
                for triple_text in judge["evidence"]:
                    match = next(
                        (r for r, _ in retrieved if r.triple_text == triple_text), None
                    )
                    if match is not None:
                        score = next(
                            s for r, s in retrieved if r.triple_text == triple_text
                        )
                        evidence.append(_evidence_entry(match, score))
                return GroundedVerdict(
                    claim=claim,
                    verdict=judge["verdict"],
                    reason=judge["reason"],
                    mode="llm",
                    evidence=evidence,
                    retrieved=trail,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM judge failed (%s); falling back to lexical", exc)

        return self._lexical_verdict(claim, retrieved, trail)

    # ------------------------------------------------------------------ #
    def _lexical_verdict(
        self,
        claim: str,
        retrieved: List[Tuple[Relation, float]],
        trail: List[Dict[str, Any]],
    ) -> GroundedVerdict:
        claim_tokens = _tokens(claim)
        claim_stems = {_stem(t) for t in claim_tokens}

        conflicts: List[Tuple[Relation, float, float, int]] = []
        supports: List[Tuple[Relation, float, float, int]] = []
        for rel, score in retrieved:
            triple_tokens = _triple_tokens(self.triples, rel)
            overlap, coverage = _coverage(claim_tokens, triple_tokens)
            if rel.relation == CONFLICT_RELATION:
                # A CONFLICTS_WITH triple can only contradict a claim that is
                # explicitly about the triple's head concept (its canonical
                # name token must appear in the claim). This keeps entity
                # aliases (which describe *other* relations) from leaking in.
                head_in_claim = bool(
                    claim_stems & {_stem(t) for t in _tokens(rel.head)}
                )
                conflicts.append((rel, score, coverage, overlap, head_in_claim))
            else:
                supports.append((rel, score, coverage, overlap))

        is_relational_query = any(
            _stem(w) in {_stem(t) for t in claim_tokens} for w in RELATIONAL_QUERY_WORDS
        )
        if not is_relational_query:
            best_conflict = max(
                (c for c in conflicts if c[4]),
                key=lambda c: (c[2], c[3]),
                default=None,
            )
            if (
                best_conflict is not None
                and best_conflict[3] >= CONTRADICT_MIN_TOKENS
                and best_conflict[2] >= CONTRADICT_COVERAGE
            ):
                rel, score, coverage, overlap, _ = best_conflict
                return GroundedVerdict(
                    claim=claim,
                    verdict="CONTRADICT",
                    reason=(
                        f"evidence contradicts the claim: {rel.head} {rel.relation} "
                        f"{rel.tail} (coverage {coverage:.2f})"
                    ),
                    mode="lexical",
                    evidence=[_evidence_entry(rel, score)],
                    retrieved=trail,
                )

        best = max(supports, key=lambda item: item[2], default=None)
        if best is not None and best[2] >= SUPPORT_COVERAGE:
            rel, score, coverage, _ = best
            return GroundedVerdict(
                claim=claim,
                verdict="SUPPORT",
                reason=(
                    f"closest evidence supports the claim: {rel.head} "
                    f"{rel.relation} {rel.tail} (coverage {coverage:.2f})"
                ),
                mode="lexical",
                evidence=[_evidence_entry(rel, score)],
                retrieved=trail,
            )

        reason = "no retrieved triple reaches the lexical support threshold"
        if retrieved:
            closest = retrieved[0]
            reason = (
                f"no retrieved triple reaches the lexical support threshold; "
                f"closest was {closest[0].triple_text}"
            )
        return GroundedVerdict(
            claim=claim,
            verdict="SILENT",
            reason=reason,
            mode="lexical",
            evidence=[trail[0]] if trail else [],
            retrieved=trail,
        )

    def ground_many(
        self, claims: List[str], top_k: int = 8
    ) -> List[GroundedVerdict]:
        return [self.ground_claim(c, top_k=top_k) for c in claims]


# --------------------------------------------------------------------------- #
# System seam: reconforge_knowledge.gate.ground(pair, provisional)
# --------------------------------------------------------------------------- #
def _corpus_dir() -> Path:
    here = Path(__file__).resolve().parent
    repo = here.parent.parent.parent
    corpus = repo / "docs" / "corpus"
    if corpus.is_dir() and list(corpus.glob("*.md")):
        return corpus
    return here.parent.parent / "sample_corpus"


def _load_triples_for_gate() -> Triples:
    """Best available triples: cache file -> canonical -> offline extraction."""
    cached = latest_cache_file()
    if cached is not None:
        return read_extracted(cached)
    canonical = Path(__file__).resolve().parent.parent.parent / "data" / "extracted.json"
    if canonical.exists():
        return read_extracted(canonical)
    corpus = _corpus_dir()
    docs = [(p.name, p.read_text(encoding="utf-8")) for p in sorted(corpus.glob("*.md"))]
    return _deterministic_extract(docs)


_gate_cache: Optional[GroundedGate] = None


def _get_gate() -> GroundedGate:
    global _gate_cache
    if _gate_cache is None:
        _gate_cache = GroundedGate(_load_triples_for_gate())
    return _gate_cache


def _as_dict(obj: Any) -> Dict[str, Any]:
    """Duck-type pydantic models (reconforge_system.contracts) or plain dicts."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump()
    return dict(obj)


def build_claim(pair: Any, provisional: Any) -> str:
    """Compose a claim sentence from a recon pair + provisional verdict.

    Works with pydantic models or plain dicts; never imports the system
    package (keeps the knowledge package dependency-free of reconforge_system).
    """
    p = _as_dict(pair)
    v = _as_dict(provisional)
    ledger = p.get("ledger") or {}
    statement = p.get("statement") or {}
    if not isinstance(ledger, dict):
        ledger = _as_dict(ledger)
    if not isinstance(statement, dict):
        statement = _as_dict(statement)

    parts: List[str] = []
    lm = ledger.get("message_type") or "UNKNOWN"
    sm = statement.get("message_type") or "UNKNOWN"
    parts.append(f"Ledger message {lm} against statement message {sm}")
    amount = ledger.get("amount")
    ccy = ledger.get("ccy")
    if amount:
        parts.append(f"for {amount} {ccy or ''}".rstrip())
    if ledger.get("value_date"):
        parts.append(f"with value date {ledger['value_date']}")
    verdict = v.get("verdict")
    exception = v.get("exception_type")
    if verdict:
        parts.append(f"has provisional verdict {verdict}")
    if exception:
        parts.append(f"with exception {exception}")
    if v.get("severity"):
        parts.append(f"severity {v['severity']}")
    if v.get("reason"):
        parts.append(f"reason: {v['reason']}")
    return " ".join(parts)


def ground_sync(
    pair: Any,
    provisional: Any,
    top_k: int = 8,
    use_llm: Optional[bool] = None,
) -> Dict[str, Any]:
    """Sync implementation of the seam (see ``ground``)."""
    claim = build_claim(pair, provisional)
    verdict = _get_gate().ground_claim(claim, top_k=top_k, use_llm=use_llm)
    result = verdict.to_dict()
    result["gated"] = True
    return result


async def ground(
    pair: Any,
    provisional: Any,
    top_k: int = 8,
    use_llm: Optional[bool] = None,
) -> Dict[str, Any]:
    """System seam, awaited by the gate service:

    ``result = await gate(pair=..., provisional=...)`` (see
    system/src/reconforge_system/services/gate.py).

    Returns {"verdict": SUPPORT|CONTRADICT|SILENT, "evidence": [...],
    "reason": "...", "claim": ..., "mode": ..., "gated": True}.
    """
    return await asyncio.to_thread(ground_sync, pair, provisional, top_k, use_llm)


def verify_seam() -> Dict[str, Any]:
    """Self-check for the system contract: ground() with dummy payloads."""
    pair = {
        "task_id": "recon-test",
        "ledger": {"message_type": "MT103", "ref": "R1", "amount": "100.00",
                   "ccy": "USD", "value_date": "2026-08-07"},
        "statement": {"message_type": "MT940", "ref": "S1", "amount": "100.00",
                      "ccy": "USD", "value_date": "2026-08-07"},
    }
    provisional = {"verdict": "EXCEPTION", "exception_type": "VALUE_DATE_MISMATCH",
                   "severity": "MEDIUM", "reason": "late value date"}
    return ground_sync(pair, provisional, use_llm=False)
