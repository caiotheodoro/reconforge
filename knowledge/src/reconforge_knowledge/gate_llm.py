"""LLM judge: compares a claim against retrieved triples/context.

Used by :mod:`reconforge_knowledge.gate` when the API is available. Returns
a schema-valid verdict JSON: {"verdict", "evidence", "reason"}. Retries via
``_llm.chat_json``; any failure propagates so the gate can fall back to the
deterministic lexical matcher.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence, Tuple

from ._llm import chat_json
from .schema import VERDICTS, Relation

logger = logging.getLogger("reconforge_knowledge.gate_llm")

SYSTEM_PROMPT = """\
You are the grounding judge for a financial reconciliation knowledge graph.
You receive a CLAIM and numbered EVIDENCE items. Each evidence item is a
fact triple (head RELATION tail) with a source quote and document reference.

Return one verdict:
- SUPPORT: the evidence establishes that the claim is true (or gives a
  positive answer to it).
- CONTRADICT: the evidence establishes that the claim is false (e.g. a
  CONFLICTS_WITH triple between the claim's concepts, or an explicit
  statement to the contrary). A "no" answer to a yes/no claim is CONTRADICT.
- SILENT: the evidence neither supports nor contradicts the claim.

Rules:
- Use ONLY the evidence provided; do not import outside knowledge.
- evidence: list of the evidence item numbers (integers) that justify the
  verdict. Empty list for SILENT.
- reason: one short sentence, citing the decisive triple(s).

Output JSON ONLY:
{"verdict": "SUPPORT|CONTRADICT|SILENT", "evidence": [1, 3], "reason": "..."}
"""


def llm_judge(
    claim: str,
    triples: Sequence[Tuple[Relation, float]],
) -> Dict[str, Any]:
    """Ask the model for a verdict over the retrieved (triple, score) pairs.

    Returns {"verdict", "evidence" (list of triple texts), "reason"}.
    """
    lines: List[str] = []
    for idx, (rel, score) in enumerate(triples, start=1):
        quote = (rel.evidence or "").strip()
        source = rel.source or "unknown"
        lines.append(
            f"[{idx}] {rel.head} {rel.relation} {rel.tail} "
            f"(confidence {rel.confidence:.2f}, score {score:.3f}, "
            f"source {source})"
        )
        if quote:
            lines.append(f"     quote: {quote}")
    context = "\n".join(lines) if lines else "(no evidence retrieved)"
    reply = chat_json(
        SYSTEM_PROMPT,
        f"CLAIM: {claim}\n\nEVIDENCE:\n{context}",
        temperature=0.0,
    )

    verdict = str(reply.get("verdict", "SILENT")).strip().upper()
    if verdict not in VERDICTS:
        verdict = "SILENT"
    reason = str(reply.get("reason", "")).strip() or "no reason given"

    evidence_refs: List[str] = []
    raw_refs = reply.get("evidence") or []
    for ref in raw_refs:
        if isinstance(ref, int) and 1 <= ref <= len(triples):
            rel = triples[ref - 1][0]
            evidence_refs.append(rel.triple_text)
        elif isinstance(ref, str):
            matched = False
            for rel, _score in triples:
                if ref.strip() == rel.triple_text or ref.strip() in rel.triple_text:
                    evidence_refs.append(rel.triple_text)
                    matched = True
                    break
            if not matched:
                evidence_refs.append(ref)

    return {"verdict": verdict, "evidence": evidence_refs, "reason": reason}
