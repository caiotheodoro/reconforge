"""reconforge_knowledge CLI: extract | load | gate-qa.

Examples::

    uv run python -m reconforge_knowledge.cli extract --offline
    uv run python -m reconforge_knowledge.cli load --extracted knowledge/data/extracted.json
    uv run python -m reconforge_knowledge.cli gate-qa --probes 3 --offline
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from .deterministic_extractor import extract_documents as deterministic_extract
from .deterministic_extractor import load_gold_triples
from .extractor import extract_documents, merge_result as extractor_merge, read_extracted, resolve_corpus_dir
from .gate import GroundedGate
from .loader import Neo4jLoader
from .probe_qa import PROBES
from .schema import Triples

logger = logging.getLogger("reconforge_knowledge.cli")

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CANONICAL_EXTRACTED = DATA_DIR / "extracted.json"


def _default_corpus_dir() -> Path:
    return resolve_corpus_dir()


def _read_markdown_docs(source: Path) -> List[tuple]:
    docs: List[tuple] = []
    for path in sorted(source.glob("*.md")):
        docs.append((path.name, path.read_text(encoding="utf-8")))
    if not docs:
        raise SystemExit(f"no *.md files found in {source}")
    return docs


def _write_canonical(result, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "mode": result.mode,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entities": [e.to_dict() for e in result.triples.entities],
        "relations": [r.to_dict() for r in result.triples.relations],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #
def cmd_extract(args: argparse.Namespace) -> int:
    source = Path(args.source) if args.source else _default_corpus_dir()
    docs = _read_markdown_docs(source)
    result = extract_documents(docs, offline=args.offline, use_cache=not args.no_cache)
    if args.with_gold and not args.offline:
        raise SystemExit("--with-gold requires --offline (gold loader is deterministic)")
    if args.with_gold:
        gold = load_gold_triples()
        all_entities = list(result.triples.entities) + list(gold.entities)
        all_relations = list(result.triples.relations) + list(gold.relations)
        result = extractor_merge(all_entities, all_relations, result.mode)
    _write_canonical(result, CANONICAL_EXTRACTED)
    stats = result.stats()
    print(f"mode:        {result.mode}")
    print(f"docs:        {len(docs)} -> {stats['chunks'] or len(docs)} chunk(s)")
    print(f"entities:    {stats['entities']}")
    print(f"relations:   {stats['relations']}")
    print(f"api_calls:   {stats['api_calls']}")
    print(f"wrote:       {CANONICAL_EXTRACTED}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted) if args.extracted else CANONICAL_EXTRACTED
    if not extracted.exists():
        raise SystemExit(f"extraction file not found: {extracted}")
    triples = read_extracted(extracted)
    with Neo4jLoader() as loader:
        if args.wipe_first:
            loader.wipe()
        loader.load(triples)
        stats = loader.stats()
        print(f"nodes: {stats['nodes']}")
        print(f"edges: {stats['edges']}")
        if args.idempotency_check:
            loader.load(triples)
            stats2 = loader.stats()
            same = stats == stats2
            print(f"idempotency check (load twice): {'OK' if same else 'FAILED'}")
            print(f"  after 1st load: {stats}")
            print(f"  after 2nd load: {stats2}")
    return 0


def cmd_wipe(args: argparse.Namespace) -> None:
    with Neo4jLoader() as loader:
        loader.wipe()
        print(f"graph wiped; nodes: {loader.stats()['nodes']}")


def cmd_gate_qa(args: argparse.Namespace) -> int:
    triples: Optional[Triples] = None
    if args.extracted:
        triples = read_extracted(Path(args.extracted))
    elif CANONICAL_EXTRACTED.exists():
        triples = read_extracted(CANONICAL_EXTRACTED)
    else:
        source = Path(args.source) if args.source else _default_corpus_dir()
        print(f"(no extraction on disk; running offline extraction on {source})")
        triples = deterministic_extract(_read_markdown_docs(source))

    gate = GroundedGate(triples)
    probes = PROBES[: args.probes] if args.probes else PROBES

    print(f"gate mode:   {'offline (lexical)' if args.offline else 'llm (auto)'}")
    print(f"triples:     {len(triples.relations)} | entities: {len(triples.entities)}")
    print()
    matched = 0
    for probe in probes:
        verdict = gate.ground_claim(
            probe.question, top_k=args.top_k, use_llm=False if args.offline else None
        )
        correct = verdict.verdict == probe.target_verdict
        matched += int(correct)
        print(f"--- {probe.id} [{verdict.mode}] ---")
        print(f"Q: {probe.question}")
        print(f"Verdict: {verdict.verdict}  (expected {probe.target_verdict}, "
              f"{'MATCH' if correct else 'DIFFERS'})")
        print(f"Reason: {verdict.reason}")
        for entry in verdict.evidence:
            print(
                f"  * {entry['triple']}  (source={entry['source']}, "
                f"conf={entry['confidence']}, score={entry['retrieval_score']})"
            )
        print(f"Expected answer: {probe.expected_answer}")
        print()
    total = len(probes)
    print(f"verdict agreement with targets: {matched}/{total}")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reconforge_knowledge.cli")
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="extract triples from corpus docs")
    p_extract.add_argument("--source", help="directory of .md corpus docs")
    p_extract.add_argument("--offline", action="store_true", help="no API (deterministic)")
    p_extract.add_argument("--no-cache", action="store_true", help="ignore extraction cache")
    p_extract.add_argument("--with-gold", action="store_true",
                           help="merge docs/corpus/gold-triples.json (offline)")
    p_extract.set_defaults(func=cmd_extract)

    p_load = sub.add_parser("load", help="load extraction into Neo4j (idempotent MERGE)")
    p_load.add_argument("--extracted", help="extraction JSON (default data/extracted.json)")
    p_load.add_argument("--wipe-first", action="store_true", help="DETACH DELETE before load")
    p_load.add_argument("--idempotency-check", action="store_true", help="load twice, compare stats")
    p_load.set_defaults(func=cmd_load)

    p_wipe = sub.add_parser("wipe", help="DETACH DELETE the whole graph")
    p_wipe.set_defaults(func=cmd_wipe)

    p_qa = sub.add_parser("gate-qa", help="run gate over probe questions")
    p_qa.add_argument("--probes", type=int, help="number of probes to run (default all)")
    p_qa.add_argument("--top-k", type=int, default=8, help="triples retrieved per claim")
    p_qa.add_argument("--offline", action="store_true", help="force lexical verdicts")
    p_qa.add_argument("--extracted", help="extraction JSON")
    p_qa.add_argument("--source", help="corpus dir if no extraction on disk")
    p_qa.set_defaults(func=cmd_gate_qa)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
