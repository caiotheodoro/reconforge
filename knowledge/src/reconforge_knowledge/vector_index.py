"""Lightweight local vector index for retrieval candidates feeding the gate.

Primary backend: scikit-learn TF-IDF + cosine similarity (pure-python,
offline-safe, deterministic). Optional backend: sentence-transformers with a
small local model (BAAI/bge-small-en-v1.5); selected via
``RECONFORGE_VECTOR_BACKEND=sentence-transformers`` and falls back to TF-IDF
if the model cannot be imported/downloaded.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional, Sequence, Tuple

from .schema import Relation, Triples

logger = logging.getLogger("reconforge_knowledge.vector_index")

# Split camelCase / PascalCase names into words: "HerstattRisk" -> "Herstatt Risk".
_CAMEL_SPLIT = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[0-9])(?=[A-Za-z])|(?<=[A-Za-z])(?=[0-9])"
)


def split_name(name: str) -> str:
    """PascalCase/camelCase name -> space-separated words (for lexical matching)."""
    return _CAMEL_SPLIT.sub(" ", name)


def _index_text(rel: Relation, triples: Triples) -> str:
    """Triple text enriched with split names + entity aliases so lexical
    retrieval works for both deterministic (aliases) and LLM (no aliases)
    extractions."""
    parts = [rel.triple_text, split_name(rel.head), split_name(rel.tail)]
    by_name = {e.name: e for e in triples.entities}
    for name in (rel.head, rel.tail):
        entity = by_name.get(name)
        if entity is not None:
            aliases = entity.properties.get("aliases")
            if aliases:
                if isinstance(aliases, str):
                    parts.append(aliases)
                else:
                    parts.extend(str(a) for a in aliases)
    return " ".join(parts)


class VectorIndex:
    """Retrieve top-k triples for a query string."""

    def __init__(
        self,
        triples: Triples,
        backend: Optional[str] = None,
        model_name: str = "BAAI/bge-small-en-v1.5",
    ) -> None:
        self.triples = triples
        self.corpus: List[str] = [_index_text(r, triples) for r in triples.relations]
        backend = backend or os.getenv("RECONFORGE_VECTOR_BACKEND", "tfidf")
        self.backend = "tfidf"
        if backend == "sentence-transformers":
            self._try_sentence_transformers(model_name)
        if self.backend == "tfidf":
            self._build_tfidf()

    # -- sentence-transformers (optional) ---------------------------------- #
    def _try_sentence_transformers(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            model = SentenceTransformer(model_name)
            logger.info("sentence-transformers backend with %s", model_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sentence-transformers unavailable (%s); using TF-IDF", exc)
            return
        self.backend = "sentence-transformers"
        self._st_model = model
        self._st_emb = model.encode(self.corpus, normalize_embeddings=True)

    def _build_tfidf(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        if not self.corpus:
            raise ValueError("cannot build index over an empty triple corpus")
        self._tfidf = TfidfVectorizer(lowercase=True, token_pattern=r"(?u)\b[a-z0-9.#]+\b")
        self._tfidf_matrix = self._tfidf.fit_transform(self.corpus)

    # -- query ------------------------------------------------------------- #
    def query(self, text: str, top_k: int = 8) -> List[Tuple[Relation, float]]:
        """Return the top-k (Relation, score) pairs, best first."""
        if not self.triples.relations:
            return []
        if self.backend == "sentence-transformers":
            import numpy as np

            q = self._st_model.encode([text], normalize_embeddings=True)[0]
            scores = self._st_emb @ q
            order = np.argsort(-scores)[:top_k]
            return [
                (self.triples.relations[int(i)], round(float(scores[int(i)]), 4))
                for i in order
            ]
        scores = self._tfidf_matrix @ self._tfidf.transform([text]).T
        scores = scores.toarray().ravel()
        order = scores.argsort()[::-1][:top_k]
        return [
            (self.triples.relations[int(i)], round(float(scores[int(i)]), 4))
            for i in order
            if scores[int(i)] > 0.0
        ]
