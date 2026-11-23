"""The paper's numbers trace to committed artifacts, and the rendered PDF says what the source says.

Three failure modes, each of which has happened in this workspace:
  * a number typed into prose that no artifact supports (lacuna: four typed from the wrong artifact);
  * a build that is green while the PDF has lost text (vernier: doubled backslashes silently ate
    an abstract and a result);
  * a headline that drifts from the registered rule or from the artifacts it cites.

Run from paper/:  uv run pytest
The render tests need tectonic and pdftotext and are skipped, loudly, where they are missing;
CI installs both and sets PAPER_REQUIRE_RENDER=1 so a skip there is a failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
VAL = ROOT / "docs" / "validation"
sys.path.insert(0, str(HERE))

import build_assets  # noqa: E402
import texutil  # noqa: E402

TEX = HERE / "reconforge.tex"
REQUIRE_RENDER = os.environ.get("PAPER_REQUIRE_RENDER") == "1"


def J(name):
    return json.loads((VAL / name).read_text())


# --- generated assets are what the artifacts produce ---------------------------------


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    out = tmp_path_factory.mktemp("assets")
    build_assets.build(out)
    return out


def test_committed_numbers_and_tables_match_a_fresh_build(rebuilt):
    for p in sorted((rebuilt / "generated").glob("*.tex")):
        committed = HERE / "generated" / p.name
        assert committed.exists(), f"{p.name} is generated but not committed"
        assert committed.read_text() == p.read_text(), (
            f"paper/generated/{p.name} is stale: run `cd paper && uv run python build_assets.py`"
        )


def test_figures_are_built(rebuilt):
    for name in ("fig_seeds.pdf", "fig_checkpoints.pdf"):
        assert (rebuilt / "figures" / name).stat().st_size > 5_000
        assert (HERE / "figures" / name).exists(), f"{name} is not committed"


# --- no typed measurements in the prose ----------------------------------------------

# Identifiers and names, not measurements. Each is checked against the artifacts below.
SEED_LABELS = {"7", "13", "101", "202", "303", "777", "999"}
NAMES = {"1.7", "3", "4", "20022", "10", "0009", "0005", "7343", "981", "2026", "11", "2.0", "95"}  # 95: the nominal interval level every interval here is stated at
# Dates the text states; each is a fact about the record, listed here so a new one is a decision.
DATES = {"2026-08-07", "2026-08-08", "2026-08-27", "2026-08-29", "2026-09-05", "2026-11-23"}


def _prose() -> str:
    s = TEX.read_text().split("\\begin{document}", 1)[1]
    s = re.sub(r"(?m)(?<!\\)%.*$", "", s)  # comments
    s = re.sub(r"\\author\{.*?\}\n", "", s, flags=re.S)
    s = re.sub(r"\\(?:input|includegraphics|label|ref|cite[tp]?|bibliographystyle|bibliography|url)(?:\[[^\]]*\])?\{[^}]*\}", " ", s)
    s = re.sub(r"\\setlength\{?\\[A-Za-z]+\}?\{[^}]*\}", " ", s)
    s = re.sub(r"\\newcommand.*", "", s)
    s = re.sub(r"\\[A-Za-z]+\{\}", " ", s)  # number macros
    s = re.sub(r"\\texttt\{[^}]*\}", " ", s)  # file names
    for d in DATES:
        s = s.replace(d, " ")
    s = re.sub(r"Qwen3-1\.7B|v4-flash|1\.7B|CIFAR-10|ISO 20022|Apache-2\.0|CC BY 4\.0|\\S\\ref|section 11|\bF1\b|\\mathbf 1|24455455|iter 700|steps 150 and 200|0\.05|80\\%|100\\%|1\.0|0\.2|df = [23]", " ", s)
    s = re.sub(r"\\begin\{tabular\}.*?\\end\{tabular\}", " ", s, flags=re.S)
    return s


def test_prose_carries_no_hand_typed_numbers():
    found = set(re.findall(r"\d+(?:\.\d+)?", _prose()))
    stray = sorted(found - SEED_LABELS - NAMES)
    assert not stray, (
        f"numerals in the prose that are neither a macro from generated/numbers.tex nor a listed "
        f"identifier: {stray}. Add the figure to build_assets.py so it traces to an artifact."
    )


def test_seed_labels_are_the_artifacts():
    tsv = J("training-seed-variance.json")
    assert {"101", "202", "303"} == set(tsv["per_seed"])
    assert str(tsv["dev_seed"]) == "13"
    assert str(J("frozen-test-seed-999-signatures.json")["seed"]) == "999"
    assert J("baselines.json")["benchmark"]["seed"] == 777
    assert "7" in J("multiseed-matrix.json")["per_seed"] and "13" in J("multiseed-matrix.json")["per_seed"]


def test_every_macro_the_prose_calls_is_defined():
    mac = texutil.macros()
    called = set(re.findall(r"\\([A-Za-z]+)\{\}", TEX.read_text().split("\\begin{document}", 1)[1]))
    assert not (called - set(mac)), sorted(called - set(mac))


# --- the artifacts say what the paper says ------------------------------------------


def test_spread_statistics_recompute_from_the_four_scores():
    from scipy.stats import chi2

    tsv = J("training-seed-variance.json")
    rw = tsv["severity_weighted_recall"]
    vals = [tsv["per_seed"][k]["severity_weighted_recall"] for k in ("101", "202", "303")] + [tsv["champion_r_w_same_pool"]]
    assert sorted(vals) == sorted(rw["values"])
    assert abs(statistics.stdev(vals) - rw["sd"]) < 5e-5
    assert abs(statistics.fmean(vals) - rw["mean"]) < 5e-5
    lo = (3 * rw["sd"] ** 2 / chi2.ppf(0.975, 3)) ** 0.5
    hi = (3 * rw["sd"] ** 2 / chi2.ppf(0.025, 3)) ** 0.5
    assert abs(lo - rw["sigma_ci95_chi2"][0]) < 5e-4 and abs(hi - rw["sigma_ci95_chi2"][1]) < 5e-4
    margin = tsv["prereg_evaluation"]["observed_margin"]
    mac = texutil.macros()
    assert f"{rw['sd'] / margin:.2f}" == mac["sdOverMargin"] == "2.86"
    # the registered rule, applied as written
    assert rw["sd"] > margin
    assert tsv["prereg_evaluation"]["section_11_sd_exceeds_margin"] is True


def test_fresh_runs_alone_do_not_clear_the_margin_and_the_paper_says_so():
    """The shipped run was selected, so the paper reports the three unselected runs too. If this
    ever flips (e.g. a fourth fresh run lands) the abstract's claim about it must be revisited."""
    mac = texutil.macros()
    assert float(mac["rwFreshSDlo"]) < float(mac["margin"]) < float(mac["rwFreshSDhi"])
    assert float(mac["freshSDoverMargin"]) > 1.0
    assert float(mac["shipGapOverMargin"]) > 1.0
    assert "includes the margin" in texutil.abstract()
    assert "underpowered rather than reversed" in texutil.abstract()


def test_headline_numbers_are_the_published_and_rescored_ones():
    mac = texutil.macros()
    base = J("baselines.json")["models"]
    assert mac["rescoredChamp"] == f"{base['champion_x5']['severity_weighted_recall']:.4f}"
    assert mac["rescoredDS"] == f"{base['deepseek_v4_flash']['severity_weighted_recall']:.4f}"
    assert mac["rescoredBase"] == f"{base['base_qwen3_1_7b']['severity_weighted_recall']:.4f}"
    assert abs(float(mac["rescoredMargin"]) - float(mac["margin"])) < 5e-5


def test_best_prompt_contrast_is_reproducible():
    """paper/derive_best_prompt.py reproduces two committed contrasts before it computes the new
    one; run it and check the committed artifact is what it produces."""
    import derive_best_prompt as d

    C = d.load("bench-deepseek-matched-rubric-x5.json")
    Ep = d.load("bench-eval-champion-x5.json", reaggregate=True)
    got = d.paired(Ep, C, "bestprompt")
    want = J("best-prompt-comparison.json")["effect_Eprime_minus_C"]
    assert got["point"] == want["point"] and got["ci95"] == want["ci95"]
    assert got["point"] < 0 and got["excludes_zero"]


def test_the_frozen_pool_has_no_score_in_the_repository():
    """The paper says no score on seed 999 exists. Fail if an artifact scored on it is added
    without the paper changing."""
    hits = [p.name for p in VAL.glob("*.json") if p.name != "frozen-test-seed-999-signatures.json" and '"seed": 999' in p.read_text()[:4000]]
    assert not hits, f"an artifact mentions seed 999: {hits}; the paper's statement about the frozen pool must be revisited"


# --- the rendered PDF ----------------------------------------------------------------


def _have_render_tools() -> bool:
    return bool(shutil.which("tectonic") and shutil.which("pdftotext"))


@pytest.fixture(scope="module")
def pdf_text(tmp_path_factory):
    if not _have_render_tools():
        if REQUIRE_RENDER:
            pytest.fail("tectonic and pdftotext are required (PAPER_REQUIRE_RENDER=1)")
        pytest.skip("tectonic or pdftotext not installed: the render checks did not run")
    work = tmp_path_factory.mktemp("render")
    (work / "out").mkdir()
    shutil.copytree(HERE, work / "paper", ignore=shutil.ignore_patterns(".venv", "__pycache__", "tests", "reconforge.pdf", ".pytest_cache"))
    r = subprocess.run(["tectonic", "reconforge.tex", "--outdir", str(work / "out")],
                       cwd=work / "paper", capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    log = r.stderr
    pdf = work / "out" / "reconforge.pdf"
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return {"text": txt, "log": log, "pdf": pdf}


def test_render_has_no_overfull_boxes_or_missing_references(pdf_text):
    assert "Overfull" not in pdf_text["log"], "an overfull box: a table or line runs off the page"
    assert "undefined" not in pdf_text["log"].lower()


def test_render_has_no_garbled_citations_or_leaked_commands(pdf_text):
    t = pdf_text["text"]
    for bad in ("[?]", "(?)", "??", "\\", "{", "}", "undefined"):
        assert bad not in t, f"found {bad!r} in the rendered text"


def test_render_abstract_carries_every_number_the_source_abstract_does(pdf_text):
    """vernier's defect: the build was green and the abstract had lost its figures."""
    flat = re.sub(r"\s+", " ", pdf_text["text"].replace("\ufb01", "fi").replace("\ufb02", "fl").replace("\u2212", "-"))
    abstract = texutil.abstract()
    figures = re.findall(r"-?\d+(?:\.\d+)?", abstract)
    assert len(figures) >= 10
    head = flat.split("1 Introduction", 1)[0]
    for f in figures:
        assert f.lstrip("-") in head, f"abstract figure {f} is missing from the rendered abstract"
    assert len(head.split()) > 200


def test_render_has_both_figures_all_tables_and_every_reference(pdf_text):
    t = pdf_text["text"]
    for label in ("Figure 1:", "Figure 2:", "Table 1:", "Table 2:", "Table 3:", "Table 4:", "Table 5:", "Table 6:", "Table 7:"):
        assert label in t, f"{label} caption missing from the render"
    keys = set(re.findall(r"\\cite[tp]?\{([^}]*)\}", TEX.read_text()))
    keys = {k.strip() for group in keys for k in group.split(",")}
    bib_keys = set(re.findall(r"@\w+\{([^,]+),", (HERE / "refs.bib").read_text()))
    assert keys <= bib_keys, sorted(keys - bib_keys)
    assert bib_keys <= keys, f"refs.bib has entries nobody cites: {sorted(bib_keys - keys)}"
    refs_section = t.split("References", 1)[1]
    squeezed = re.sub(r"\s+", "", refs_section)  # ids wrap across lines in the layout text
    ids = set(re.findall(r"arXivpreprintarXiv:(\d{4}\.\d{5})", squeezed))
    assert ids == set(re.findall(r"arXiv:(\d{4}\.\d{5})", (HERE / "refs.bib").read_text())), "a reference is missing or garbled in the render"


def test_page_count_is_in_range(pdf_text):
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf_text["pdf"])], capture_output=True, text=True).stdout).group(1))
    assert 6 <= n <= 14, f"{n} pages"
