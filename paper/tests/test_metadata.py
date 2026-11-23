"""The README's retraction box, the deposit metadata and the decision log say what the paper says."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import export_metadata  # noqa: E402
import texutil  # noqa: E402

README = (ROOT / "README.md").read_text()


def _box() -> str:
    return README.split("## ⚠ Status: the headline is retracted", 1)[1].split("## The published run", 1)[0]


def test_zenodo_json_is_what_the_paper_generates():
    committed = json.loads((ROOT / ".zenodo.json").read_text())
    assert committed == export_metadata.zenodo(), "run `cd paper && uv run python export_metadata.py`"


def test_zenodo_metadata_is_the_deposit_we_intend():
    z = json.loads((ROOT / ".zenodo.json").read_text())
    assert z["creators"] == [{"name": "Theodoro, Caio", "orcid": "0009-0005-7343-981X"}]
    assert z["license"] == "cc-by-4.0" and z["upload_type"] == "publication" and z["publication_type"] == "preprint"
    assert "Not peer reviewed" in z["description"]
    assert z["description"].startswith(texutil.abstract())
    assert z["related_identifiers"][0]["identifier"] == "https://github.com/caiotheodoro/reconforge"
    cited = re.findall(r"arXiv:(\d{4}\.\d{5})", (HERE / "refs.bib").read_text())
    assert [r["identifier"] for r in z["related_identifiers"][1:]] == [f"arXiv:{i}" for i in cited]
    assert len(z["references"]) == len(cited)


def test_citation_cff_names_the_same_paper():
    cff = (ROOT / "CITATION.cff").read_text()
    assert texutil.title() in cff
    assert "0009-0005-7343-981X" in cff


def test_readme_box_states_the_paper_s_numbers():
    mac = texutil.macros()
    box = _box().replace("−", "-").replace("\n> ", " ")
    for key in ("rwSeedLow", "rwSeedMidLow", "rwSeedMidHigh", "rwShipped", "rwSD", "rwFreshSD", "bestPromptAbs", "margin"):
        assert mac[key] in box, f"README box lacks {key} = {mac[key]}"
    assert mac["sdOverMargin"] in box and mac["freshSDoverMargin"] in box
    assert mac["matMargin"].replace("$-$", "-") in box
    assert "underpowered, not reversed" in box
    assert "fails two of the five" in box
    assert "3 of the 5" not in README and "3 of 5" not in README, "the guard count was corrected to two"


def test_readme_does_not_lead_with_the_retracted_claim():
    first = README.split("\n\n", 2)[1]
    assert "retraction" in first and "beats" in first.split("retraction")[1], "the first line must frame the claim as retracted"
    assert README.index("Status: the headline is retracted") < README.index("| Model |")


def test_decision_log_records_the_release():
    log = (ROOT / "docs" / "DECISIONS.md").read_text()
    entry = log.split("## 2026-11-23", 1)
    assert len(entry) == 2, "no dated entry for the paper release"
    body = entry[1]
    assert "Reversal" in body
    assert "not the registration clock" in body.lower() or "not the registration" in body.lower()


def test_frozen_text_is_untouched():
    """PRE-REGISTRATION.md is frozen. Its digest is recorded here so a change is a decision."""
    import hashlib

    digest = hashlib.sha256((ROOT / "PRE-REGISTRATION.md").read_bytes()).hexdigest()
    assert digest == "00aa755f35cc320fc09133196f1c7373b12466601eb08e3b3dc9210b0e76cb37", "PRE-REGISTRATION.md changed; frozen text is never edited"
