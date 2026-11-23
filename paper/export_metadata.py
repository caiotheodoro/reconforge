#!/usr/bin/env python3
"""Write .zenodo.json and check CITATION.cff against the paper.

The title, the abstract (macros expanded), the reference strings and the cited arXiv ids all
come from paper/reconforge.tex and paper/refs.bib, so the deposit metadata cannot drift from
the paper. tests/test_metadata.py regenerates and compares.

    cd paper && uv run python export_metadata.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import texutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO_URL = "https://github.com/caiotheodoro/reconforge"
ORCID = "0009-0005-7343-981X"
VERSION = "paper-v2.0"
PUBLICATION_DATE = "2026-08-07"  # first repository commit (de7405f), per owner date rule
NOTES = (
    "Work begun 7 August 2026 (first repository commit de7405f); first preprint version "
    "(paper-v1.0, Zenodo record 24455455) compiled and deposited 23 November 2026. "
    "This version, paper-v2.0, is of 23 November 2026."
)
KEYWORDS = ["fine-tuning", "random seeds", "variance decomposition", "LoRA", "pre-registration", "evaluation"]

ACCENTS = {r'{\"e}': "ë", r"{\c{c}}": "ç", r"{\'e}": "é"}


def _tex(s: str) -> str:
    for a, b in ACCENTS.items():
        s = s.replace(a, b)
    s = s.replace("\\_", "_")
    return re.sub(r"[{}]", "", s)


def bib_entries() -> list[dict]:
    text = (HERE / "refs.bib").read_text()
    out = []
    for m in re.finditer(r"@\w+\{([^,]+),(.*?)\n\}", text, flags=re.S):
        fields = dict(re.findall(r"(\w+)\s*=\s*\{(.*)\},?\s*$", m.group(2), flags=re.M))
        fields["key"] = m.group(1)
        out.append(fields)
    return out


def reference_string(e: dict) -> str:
    names = []
    for a in e["author"].split(" and "):
        last, first = (x.strip() for x in a.split(",", 1))
        names.append(f"{first} {last}")
    if len(names) == 1:
        authors = names[0]
    elif len(names) == 2:
        authors = " and ".join(names)
    else:
        authors = ", ".join(names[:-1]) + ", and " + names[-1]
    note = f" {e['note']}." if e.get("note") else ""
    return _tex(f"{authors}. {e['title']}. {e['journal']}, {e['year']}.{note}")


def arxiv_id(e: dict) -> str:
    return re.search(r"arXiv:(\d{4}\.\d{5})", e["journal"]).group(1)


def zenodo() -> dict:
    mac = texutil.macros()
    desc = texutil.abstract(mac) + f" Not peer reviewed. Code, data and artifacts: {REPO_URL}"
    entries = bib_entries()
    related = [{"relation": "isSupplementedBy", "identifier": REPO_URL, "resource_type": "software", "scheme": "url"}]
    related += [
        {"relation": "cites", "identifier": f"arXiv:{arxiv_id(e)}", "resource_type": "publication-preprint", "scheme": "arxiv"}
        for e in entries
    ]
    return {
        "title": texutil.title(),
        "upload_type": "publication",
        "publication_type": "preprint",
        "creators": [
            {"name": "Theodoro, Caio", "affiliation": "Avenza Labs", "orcid": ORCID},
            {"name": "Basso Sberse, João Vitor", "affiliation": "Avenza Labs", "orcid": "0009-0005-7111-1474"},
        ],
        "publication_date": PUBLICATION_DATE,
        "license": "cc-by-4.0",
        "description": desc,
        "notes": NOTES,
        "keywords": KEYWORDS,
        "language": "eng",
        "references": [reference_string(e) for e in entries],
        "related_identifiers": related,
        "version": VERSION,
    }


def main() -> None:
    (ROOT / ".zenodo.json").write_text(json.dumps(zenodo(), indent=2, ensure_ascii=False) + "\n")
    print("wrote .zenodo.json")


if __name__ == "__main__":
    main()
