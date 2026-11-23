#!/usr/bin/env python3
"""Generate every number, table and figure in paper/reconforge.tex from committed artifacts.

Nothing in the paper's prose carries a hand-typed measurement: the prose calls a macro
(\\rwSD, ...) defined in paper/generated/numbers.tex, and tables and figures are written
here. tests/test_paper.py regenerates all of it into a scratch directory and fails if the
committed copy differs, and fails if a numeral appears in the prose outside the macros.

Run from the repo root:  cd paper && uv run python build_assets.py
Artifacts read (all under docs/validation/ unless noted): training-seed-variance,
multiseed-matrix, matched-comparison, best-prompt-comparison, baselines, variance-decomposition,
checkpoint-loss-correlation, checkpoint-selection, partial-match-overlap,
dedup-sensitivity, contamination, flag-metrics, intervals, runconfig,
frozen-test-seed-999-signatures, bench-eval-champion-x5, bench-deepseek-full,
bench-eval-base-ablation; ../taxonomy.json (weights).
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VAL = ROOT / "docs" / "validation"


def J(name: str):
    return json.loads((VAL / name).read_text())


def f4(x: float) -> str:
    return f"{x:.4f}"


def f3(x: float) -> str:
    return f"{x:.3f}"


def f2(x: float) -> str:
    return f"{x:.2f}"


def sgn4(x: float) -> str:
    """Signed, with a true minus sign for LaTeX math-free text."""
    return ("+" if x >= 0 else "$-$") + f"{abs(x):.4f}"


def rescore(per_task: list[dict], weights: dict[str, float], sev: dict[str, str]):
    """Independent re-implementation of CONTRACTS.md's R_w, from the per-task exports.

    HIGH exception: caught if flagged as anything other than MATCH. MEDIUM/LOW: caught
    only with the exact exception_type. Returns (R_w, caught-by-class, n-by-class, FP)."""
    tot = got = 0.0
    caught: dict[str, int] = {}
    n: dict[str, int] = {}
    fp = 0
    for t in per_task:
        e, p = t["expected"], t.get("predicted")
        flagged = bool(p) and p.get("verdict") in ("EXCEPTION", "ESCALATE")
        if e["verdict"] == "MATCH":
            fp += flagged
            continue
        et = e["exception_type"]
        ok = flagged and (sev[et] == "HIGH" or p.get("exception_type") == et)
        tot += weights[et]
        got += weights[et] * ok
        caught[et] = caught.get(et, 0) + int(ok)
        n[et] = n.get(et, 0) + 1
    return got / tot, caught, n, fp, tot


def build_numbers() -> dict[str, str]:
    N: dict[str, str] = {}

    # --- training-seed study (the registered test) -----------------------------------
    tsv = J("training-seed-variance.json")
    ms = J("multiseed-matrix.json")
    rw = tsv["severity_weighted_recall"]
    fresh = {k: v for k, v in tsv["per_seed"].items()}
    champ13 = ms["per_seed"]["13"]
    vals4 = rw["values"]
    N["nSeedRuns"] = str(rw["n"])
    N["nSeedFresh"] = str(len(fresh))
    N["nPoolTasks"] = str(tsv["n_tasks"])
    N["devPoolSeed"] = str(tsv["dev_seed"])
    N["decodeSamples"] = str(tsv["decoding"]["samples"])
    N["decodeTemp"] = str(tsv["decoding"]["temperature"])
    N["rwSeedLow"] = f4(fresh["202"]["severity_weighted_recall"])
    N["rwSeedMidLow"] = f4(fresh["303"]["severity_weighted_recall"])
    N["rwSeedMidHigh"] = f4(fresh["101"]["severity_weighted_recall"])
    N["rwShipped"] = f4(tsv["champion_r_w_same_pool"])
    N["costSeedLow"] = f3(fresh["202"]["normalized_cost"])
    N["costSeedMidLow"] = f3(fresh["303"]["normalized_cost"])
    N["costSeedMidHigh"] = f3(fresh["101"]["normalized_cost"])
    N["costShipped"] = f3(champ13["normalized_cost"])
    N["rwMean"] = f4(rw["mean"])
    N["rwSD"] = f4(rw["sd"])
    N["rwRange"] = f4(rw["range"])
    N["rwMeanMinusSD"] = f4(rw["mean_minus_1sd"])
    N["rwSDlo"] = f4(rw["sigma_ci95_chi2"][0])
    N["rwSDhi"] = f4(rw["sigma_ci95_chi2"][1])
    N["rwSDoneSided"] = f4(rw["sigma_one_sided_95_lower"])
    N["rwSDnoDecode"] = f4(rw["sd_excluding_decode_noise"])
    margin = tsv["prereg_evaluation"]["observed_margin"]
    ds_rw = tsv["prereg_evaluation"]["deepseek_r_w_seed777"]
    N["margin"] = f4(margin)
    N["dsRw"] = f4(ds_rw)
    N["sdOverMargin"] = f2(rw["sd"] / margin)
    N["rangeOverMargin"] = f2(rw["range"] / margin)
    # The three fresh runs alone: the shipped run was chosen for scoring well, so it is
    # not an unselected draw of the recipe.
    fv = [fresh[k]["severity_weighted_recall"] for k in ("202", "303", "101")]
    fm, fsd = statistics.fmean(fv), statistics.stdev(fv)
    N["rwFreshMean"] = f4(fm)
    N["rwFreshSD"] = f4(fsd)
    N["freshSDoverMargin"] = f2(fsd / margin)
    from scipy.stats import chi2, norm  # noqa: PLC0415

    lo = (2 * fsd**2 / chi2.ppf(0.975, 2)) ** 0.5
    hi = (2 * fsd**2 / chi2.ppf(0.025, 2)) ** 0.5
    N["rwFreshSDlo"] = f4(lo)
    N["rwFreshSDhi"] = f4(hi)
    N["shipGapFresh"] = f4(tsv["champion_r_w_same_pool"] - fm)
    N["shipGapOverMargin"] = f2((tsv["champion_r_w_same_pool"] - fm) / margin)
    N["freshMax"] = f4(max(fv))
    from scipy.stats import t as tdist  # noqa: PLC0415

    tstat = (fm - ds_rw) / (fsd / len(fv) ** 0.5)
    N["tFresh"] = "$-$" + f2(abs(tstat))
    N["pFresh"] = f2(2 * tdist.sf(abs(tstat), len(fv) - 1))
    N["freshGapToDS"] = f4(ds_rw - fm)
    # Runs needed to see a margin this size against this SD (one-sample, two-sided 5%,
    # power 80%), taking the SD from all four runs. A planning figure, not a result.
    za, zb = norm.ppf(0.975), norm.ppf(0.80)
    N["seedsNeeded"] = str(int(-(-(((za + zb) * rw["sd"] / margin) ** 2) // 1)))
    N["seedsNeededFresh"] = str(int(-(-(((za + zb) * fsd / margin) ** 2) // 1)))
    # Same weights, two pools: the champion on the seed-777 pool and on the dev pool.
    var = J("variance-decomposition.json")
    N["rwChampPoolBench"] = f4(J("baselines.json")["models"]["champion_x5"]["severity_weighted_recall"])
    dev_mean = J("multiseed-matrix.json")["across_seed"]["severity_weighted_recall"]["mean"]
    N["poolMeanShift"] = f4(dev_mean - float(N["rwChampPoolBench"]))
    N["poolShift"] = f4(tsv["champion_r_w_same_pool"] - float(N["rwChampPoolBench"]))
    N["poolShiftOverMargin"] = f2((tsv["champion_r_w_same_pool"] - float(N["rwChampPoolBench"])) / margin)
    N["rwSamplingMarginal"] = f4(var["sampling_marginal"]["delta"])
    N["samplingOverMargin"] = f2(var["sampling_marginal"]["fraction_of_headline_margin"])
    N["rwEvalPoolSD"] = f4(var["eval_pool_seed"]["sd"])
    N["evalPoolOverMargin"] = f2(var["eval_pool_seed"]["sd_as_fraction_of_margin"])
    N["rwEvalPoolLow"] = f4(min(var["eval_pool_seed"]["values"]))
    N["devPoolSeedList"] = ", ".join(sorted(J("multiseed-matrix.json")["per_seed"], key=int))
    N["evalPoolRange"] = f4(var["eval_pool_seed"]["range"])
    N["rwEvalPoolHigh"] = f4(max(var["eval_pool_seed"]["values"]))
    N["rwChampXthree"] = f4(var["sampling_marginal"]["champion_x3"])
    N["rwTrainSeedGapOld"] = f4(var["training_seed"]["delta"])
    N["marginXthree"] = f4(var["sampling_marginal"]["champion_x3"] - ds_rw)
    N["rwSiblingXthree"] = f4(var["training_seed"]["sibling_run_same_recipe"])

    # --- the published comparison ----------------------------------------------------
    base = J("baselines.json")
    mc = J("matched-comparison.json")
    fm_ = J("flag-metrics.json")["runs"]
    iv = J("intervals.json")
    N["nBench"] = str(base["benchmark"]["n_tasks"])
    N["nClean"] = str(base["benchmark"]["n_clean"])
    N["nExc"] = str(base["benchmark"]["n_exception"])
    N["rwChamp"] = f4(base["models"]["champion_x5"]["severity_weighted_recall"])
    N["rwChampLo"] = f3(iv["runs"]["reconforge_recon"]["severity_weighted_recall"]["ci95"][0])
    N["rwChampHi"] = f3(iv["runs"]["reconforge_recon"]["severity_weighted_recall"]["ci95"][1])
    N["rwDS"] = f4(base["models"]["deepseek_v4_flash"]["severity_weighted_recall"])
    N["rwDSLo"] = f3(iv["runs"]["deepseek_v4_flash"]["severity_weighted_recall"]["ci95"][0])
    N["rwDSHi"] = f3(iv["runs"]["deepseek_v4_flash"]["severity_weighted_recall"]["ci95"][1])
    N["rwBase"] = f4(base["models"]["base_qwen3_1_7b"]["severity_weighted_recall"])
    eff = mc["effects"]
    pub = eff["published_margin_as_reported_E_minus_A"]
    pubc = eff["published_margin_corrected_vote_Eprime_minus_A"]
    mat = eff["matched_margin_D_minus_C"]
    comb = eff["combined_definition_plus_budget_C_minus_A"]
    rub = eff["rubric_cost_to_champion_D_minus_Eprime"]
    N["pubMargin"] = sgn4(pub["point"])
    N["pubMarginLo"] = sgn4(pub["ci95"][0])
    N["pubMarginHi"] = sgn4(pub["ci95"][1])
    N["pubMarginCorr"] = sgn4(pubc["point"])
    N["pubMarginCorrLo"] = sgn4(pubc["ci95"][0])
    N["pubMarginCorrHi"] = sgn4(pubc["ci95"][1])
    N["matMargin"] = sgn4(mat["point"])
    N["matMarginLo"] = sgn4(mat["ci95"][0])
    N["matMarginHi"] = sgn4(mat["ci95"][1])
    N["combEffect"] = sgn4(comb["point"])
    N["combEffectLo"] = sgn4(comb["ci95"][0])
    N["combEffectHi"] = sgn4(comb["ci95"][1])
    N["rubricEffect"] = sgn4(rub["point"])
    bp = J("best-prompt-comparison.json")["effect_Eprime_minus_C"]
    N["bestPrompt"] = sgn4(bp["point"])
    N["bestPromptAbs"] = f4(abs(bp["point"]))
    N["bestPromptLo"] = sgn4(bp["ci95"][0])
    N["bestPromptHi"] = sgn4(bp["ci95"][1])
    N["sdOverCorrMargin"] = f2(rw["sd"] / pubc["point"])
    c = mc["conditions"]
    N["accMatChamp"] = f4(c["D_champion_rubric_x5"]["accuracy"])
    N["accMatDS"] = f4(c["C_deepseek_rubric_x5"]["accuracy"])
    N["precMatChamp"] = f4(c["D_champion_rubric_x5"]["flag_precision"])
    N["fOneMatChamp"] = f4(c["D_champion_rubric_x5"]["flag_f1"])
    N["fOneMatDS"] = f4(c["C_deepseek_rubric_x5"]["flag_f1"])
    N["rwMatChamp"] = f4(c["D_champion_rubric_x5"]["severity_weighted_recall"])
    N["rwMatDS"] = f4(c["C_deepseek_rubric_x5"]["severity_weighted_recall"])
    N["rwChampCorr"] = f4(c["E_prime_champion_base_x5_corrected_vote"]["severity_weighted_recall"])
    N["fpChamp"] = str(fm_["reconforge_recon_x5"]["counts"]["fp"])
    N["fpDS"] = str(fm_["deepseek_v4_flash"]["counts"]["fp"])
    N["fOneChamp"] = f3(fm_["reconforge_recon_x5"]["f1"]["point"])
    N["fOneDS"] = f3(fm_["deepseek_v4_flash"]["f1"]["point"])
    N["highRecall"] = f3(iv["runs"]["reconforge_recon"]["severity_band_recall"]["HIGH"]["point"])
    N["nHigh"] = str(iv["runs"]["reconforge_recon"]["severity_band_recall"]["HIGH"]["n"])

    # --- re-scoring from the per-task exports, and where the margin came from -------
    tax = json.loads((ROOT / "taxonomy.json").read_text())
    w, sev = tax["severity_weights"], tax["severity_by_exception"]
    r_c, cc, nn, fp_c, tot = rescore(J("bench-eval-champion-x5.json")["per_task"], w, sev)
    r_d, cd, _, fp_d, _ = rescore(J("bench-deepseek-full.json")["per_task"], w, sev)
    r_b, *_ = rescore(J("bench-eval-base-ablation.json")["per_task"], w, sev)
    N["rescoredChamp"] = f4(r_c)
    N["rescoredDS"] = f4(r_d)
    N["rescoredBase"] = f4(r_b)
    N["rescoredMargin"] = f4(r_c - r_d)
    share = w["PARTIAL_MATCH"] * (cc["PARTIAL_MATCH"] - cd["PARTIAL_MATCH"]) / tot
    N["partialContrib"] = f4(share)
    N["partialShare"] = str(round(100 * share / (r_c - r_d)))
    N["partialChamp"] = str(cc["PARTIAL_MATCH"])
    N["partialDS"] = str(cd["PARTIAL_MATCH"])
    N["partialN"] = str(nn["PARTIAL_MATCH"])
    N["rescoredFP"] = str(fp_c)
    N["rescoredFPds"] = str(fp_d)
    r_3, c3, n3, _, tot3 = rescore(J("bench-eval-full-740.json")["per_task"], w, sev)
    share3 = w["PARTIAL_MATCH"] * (c3["PARTIAL_MATCH"] - cd["PARTIAL_MATCH"]) / tot3 / (r_3 - r_d)
    N["partialShareXthree"] = str(round(100 * share3))
    N["ciPct"] = "95"  # the nominal level every interval in this project is stated at
    pm = J("partial-match-overlap.json")
    N["pmPairs"] = str(pm["distinct_pairs_in_benchmark"])
    N["pmShared"] = str(pm["pairs_in_both"])
    N["pmTableSize"] = str(pm["variant_table_size"])

    # --- floors and contamination ------------------------------------------------------
    pol = base["policies"]
    N["floorRw"] = f4(pol["always_exception"]["severity_weighted_recall"])
    N["floorAcc"] = f4(pol["always_exception"]["accuracy"])
    _sb = base["skill_normalized"]["severity_weighted_recall"]["models"]["base_qwen3_1_7b"]
    N["skillBase"] = ("$-$" if _sb < 0 else "") + f4(abs(_sb))
    N["skillChamp"] = f4(base["skill_normalized"]["severity_weighted_recall"]["models"]["champion_x5"])
    N["skillDS"] = f4(base["skill_normalized"]["severity_weighted_recall"]["models"]["deepseek_v4_flash"])
    N["skillFOneChamp"] = f4(base["skill_normalized"]["flag_f1"]["models"]["champion_x5"])
    N["skillFOneDS"] = f4(base["skill_normalized"]["flag_f1"]["models"]["deepseek_v4_flash"])
    N["skillAccChamp"] = f4(base["skill_normalized"]["accuracy"]["models"]["champion_x5"])
    N["skillAccDS"] = f4(base["skill_normalized"]["accuracy"]["models"]["deepseek_v4_flash"])
    con = J("contamination.json")
    nd = con["near_duplicate_audit"]
    N["exactOverlap"] = str(int(con["exact_overlap"]["overlap"]))
    N["nearDup"] = str(nd["near_duplicate_count"])
    N["nearDupPct"] = f"{100 * nd['near_duplicate_rate']:.2f}"
    N["nMidBand"] = str(J("dedup-sensitivity.json")["tasks_between_0.6_and_0.8"])
    N["nTrain"] = str(nd["n_train"])
    N["nnHigh"] = str(nd["threshold"])
    hist = nd["nearest_neighbour_similarity_histogram"]
    N["nnFloor"] = str(min(float(k.strip("[(").split(",")[0]) for k, v in hist.items() if v > 0))
    N["resamples"] = f"{J('matched-comparison.json')['resamples']:,}".replace(",", "{,}")
    from derive_best_prompt import majority  # noqa: PLC0415

    changed = 0
    for t in J("bench-eval-champion-x5.json")["per_task"]:
        smp = [x for x in (t.get("samples") or []) if x]
        pr = t.get("predicted")
        a = (pr.get("verdict"), pr.get("exception_type")) if pr else None
        b = (lambda m: (m.get("verdict"), m.get("exception_type")))(majority(smp)) if smp else None
        changed += a != b
    N["voteChanges"] = str(changed)
    N["dedupShift"] = f4(J("dedup-sensitivity.json")["headline_margin"]["margin_shift"])
    sig = J("frozen-test-seed-999-signatures.json")
    N["nFrozen"] = str(sig["n_unique_signatures"])
    N["frozenSeed"] = str(sig["seed"])

    # --- checkpoint selection (one run, fourteen checkpoints, dev pool) -----------------
    cl = J("checkpoint-loss-correlation.json")
    cs = J("checkpoint-selection.json")
    N["nCkpt"] = str(cl["n_checkpoints"])
    N["ckptRho"] = ("$-$" if cl["spearman_rho_tie_corrected"] < 0 else "") + f3(abs(cl["spearman_rho_tie_corrected"]))
    N["ckptSpread"] = f3(cl["spread_all"]["spread"])
    N["ckptSpreadX"] = f2(cl["spread_all"]["x_headline_margin"])
    N["plateauSpread"] = f4(cl["spread_at_lowest_loss"]["spread"])
    N["plateauSpreadX"] = f2(cl["spread_at_lowest_loss"]["x_headline_margin"])
    N["plateauN"] = str(cl["spread_at_lowest_loss"]["n"])
    N["ckptPoolTasks"] = str(cs["n_tasks"])
    pc = {r["iter"]: r for r in cl["per_checkpoint"]}
    N["lossBefore"] = f3(pc[150]["val_loss"])
    N["lossAfter"] = f3(pc[200]["val_loss"])
    N["rwBefore"] = f4(pc[150]["severity_weighted_recall"])
    N["rwAfter"] = f4(pc[200]["severity_weighted_recall"])
    N["rwShippedCkpt"] = f4(pc[700]["severity_weighted_recall"])
    # --- decode configuration ---------------------------------------------------------
    rc = J("runconfig.json")
    N["tempChamp"] = str(rc["reconforge_recon"]["temperature"])
    N["samplesChamp"] = str(rc["reconforge_recon"]["samples_per_task"])
    N["tempDS"] = str(rc["deepseek_v4_flash"]["temperature"])
    return N


def write_numbers(N: dict[str, str], out: Path) -> None:
    lines = ["% Generated by paper/build_assets.py from docs/validation/*.json. Do not edit."]
    for k in sorted(N):
        assert k.isalpha(), k
        lines.append(f"\\newcommand{{\\{k}}}{{{N[k]}}}")
    out.write_text("\n".join(lines) + "\n")


def tables(N: dict[str, str]) -> dict[str, str]:
    T: dict[str, str] = {}
    base = J("baselines.json")
    fm_ = J("flag-metrics.json")["runs"]
    iv = J("intervals.json")["runs"]

    def row(name, accv, rwv, rwci, p, f1, cost, high):
        return f"{name} & {accv} & {rwv}{rwci} & {p} & {f1} & {cost} & {high} \\\\"

    ch, dsm, bm = base["models"]["champion_x5"], base["models"]["deepseek_v4_flash"], base["models"]["base_qwen3_1_7b"]

    def ci(d):
        return f" [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]"

    rows = [
        row("Fine-tune, shipped run ($\\times$5)", f4(ch["accuracy"]),
            f4(ch["severity_weighted_recall"]), ci(iv["reconforge_recon"]["severity_weighted_recall"]),
            f"{ch['flag_precision']:.3f}", f"{ch['flag_f1']:.3f}", f"{ch['normalized_cost']:.3f}", f3(iv["reconforge_recon"]["severity_band_recall"]["HIGH"]["point"])),
        row("DeepSeek v4-flash, zero-shot", f4(dsm["accuracy"]), f4(dsm["severity_weighted_recall"]),
            ci(iv["deepseek_v4_flash"]["severity_weighted_recall"]), f"{dsm['flag_precision']:.3f}",
            f"{dsm['flag_f1']:.3f}", f"{dsm['normalized_cost']:.3f}", f3(iv["deepseek_v4_flash"]["severity_band_recall"]["HIGH"]["point"])),
        row("Base Qwen3-1.7B, zero-shot", f4(bm["accuracy"]), f4(bm["severity_weighted_recall"]),
            ci(iv["base_qwen3_1_7b"]["severity_weighted_recall"]), f"{bm['flag_precision']:.3f}",
            f"{bm['flag_f1']:.3f}", f"{bm['normalized_cost']:.3f}", f3(iv["base_qwen3_1_7b"]["severity_band_recall"]["HIGH"]["point"])),
    ]
    T["tab_published"] = (
        "\\begin{tabular}{@{}lrlrrrr@{}}\n\\toprule\n"
        "Model & Accuracy & $R_w$ [95\\% CI] & Flag prec. & Flag F1 & Cost & HIGH rec. \\\\\n\\midrule\n"
        + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n"
    )
    del fm_

    tsv = J("training-seed-variance.json")
    ms = J("multiseed-matrix.json")["per_seed"]["13"]
    seeds = [("202", False), ("303", False), ("101", False)]
    rws = []
    for s, _ in seeds:
        v = tsv["per_seed"][s]
        rws.append((int(s), v["severity_weighted_recall"], v["accuracy"], v["flag_precision"], v["normalized_cost"], "fresh"))
    rws.append((7, tsv["champion_r_w_same_pool"], ms["accuracy"], ms["flag_precision"], ms["normalized_cost"], "shipped"))
    rws.sort(key=lambda r: r[1])
    lines = []
    for s, r, a, p, c, kind in rws:
        label = f"{s} (shipped)" if kind == "shipped" else f"{s}"
        lines.append(f"{label} & {r:.4f} & {a:.4f} & {p:.4f} & {c:.3f} \\\\")
    lines.append("\\midrule")
    rwb = tsv["severity_weighted_recall"]
    lines.append(f"mean of four & {rwb['mean']:.4f} & & & \\\\")
    lines.append(f"SD of four & {rwb['sd']:.4f} & & & \\\\")
    lines.append(f"mean of the three fresh runs & {N['rwFreshMean']} & & & \\\\")
    lines.append(f"SD of the three fresh runs & {N['rwFreshSD']} & & & \\\\")
    T["tab_seeds"] = (
        "\\begin{tabular}{@{}lrrrr@{}}\n\\toprule\n"
        "Training seed & $R_w$ & Accuracy & Flag prec. & Cost \\\\\n\\midrule\n"
        + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n"
    )

    mc = J("matched-comparison.json")["conditions"]
    conds = [
        ("A", "DeepSeek, shared prompt, 1 greedy sample (as published)", "A_deepseek_base_x1"),
        ("C", "DeepSeek, defined-class prompt, 5 samples", "C_deepseek_rubric_x5"),
        ("E$'$", "Fine-tune, shared prompt, 5 samples (as published, vote corrected)", "E_prime_champion_base_x5_corrected_vote"),
        ("D", "Fine-tune, defined-class prompt, 5 samples", "D_champion_rubric_x5"),
    ]
    lines = []
    for tag, desc, key in conds:
        v = mc[key]
        lines.append(f"{tag} & {desc} & {v['accuracy']:.4f} & {v['severity_weighted_recall']:.4f} & {v['flag_precision']:.4f} & {v['flag_f1']:.4f} \\\\")
    T["tab_matched"] = (
        "\\begin{tabular}{@{}cp{6.6cm}rrrr@{}}\n\\toprule\n"
        " & Condition & Accuracy & $R_w$ & Flag prec. & Flag F1 \\\\\n\\midrule\n"
        + "\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n"
    )

    eff = J("matched-comparison.json")["effects"]
    bpe = J("best-prompt-comparison.json")["effect_Eprime_minus_C"]
    def eline(label, key):
        e = eff[key]
        return f"{label} & {sgn4(e['point'])} & [{sgn4(e['ci95'][0])}, {sgn4(e['ci95'][1])}] \\\\"
    T["tab_effects"] = (
        "\\begin{tabular}{@{}lrr@{}}\n\\toprule\n"
        "Paired difference in $R_w$ & Point & 95\\% CI \\\\\n\\midrule\n"
        + "\n".join([
            eline("Published margin, E$-$A", "published_margin_as_reported_E_minus_A"),
            eline("Published margin, vote corrected, E$'-$A", "published_margin_corrected_vote_Eprime_minus_A"),
            eline("Same prompt and budget for the frontier model, C$-$A", "combined_definition_plus_budget_C_minus_A"),
            eline("Defined-class prompt for the fine-tune, D$-$E$'$", "rubric_cost_to_champion_D_minus_Eprime"),
            eline("Matched margin, D$-$C (exploratory)", "matched_margin_D_minus_C"),
            f"Each model on its own prompt, E$'-$C & {sgn4(bpe['point'])} & [{sgn4(bpe['ci95'][0])}, {sgn4(bpe['ci95'][1])}] \\\\",
        ]) + "\n\\bottomrule\n\\end{tabular}\n"
    )

    var = J("variance-decomposition.json")
    mg = var["headline_margin_r_w"]
    rows = [
        ("Task resampling (redraw 800 tasks)", f"{var['task_resampling']['width']:.4f}", "CI width", "--"),
        ("Sampling: $\\times$3 against $\\times$5 on one set of weights", f"{var['sampling_marginal']['delta']:.4f}", "one difference", f"{var['sampling_marginal']['delta']/mg:.2f}"),
        ("Evaluation pool (three generator seeds, 300 tasks each)", f"{var['eval_pool_seed']['sd']:.4f}", "SD", f"{var['eval_pool_seed']['sd']/mg:.2f}"),
        ("Training seed (four runs of one recipe)", N["rwSD"], "SD", N["sdOverMargin"]),
    ]
    T["tab_variance"] = (
        "\\begin{tabular}{@{}lrlr@{}}\n\\toprule\n"
        "Source of variation & Size in $R_w$ & Statistic & $\\div$ margin \\\\\n\\midrule\n"
        + "\n".join(f"{a} & {b} & {c} & {d} \\\\" for a, b, c, d in rows) + "\n\\bottomrule\n\\end{tabular}\n"
    )

    pol = base["policies"]
    fl = [
        ("Always MATCH", pol["always_match"]),
        ("Always EXCEPTION (AMOUNT\\_MISMATCH)", pol["always_exception"]),
        ("Stratified random", pol["stratified_random"]),
        ("Base Qwen3-1.7B", base["models"]["base_qwen3_1_7b"]),
        ("DeepSeek v4-flash", base["models"]["deepseek_v4_flash"]),
        ("Fine-tuned 1.7B, shipped run", base["models"]["champion_x5"]),
        ("Rules oracle (ceiling by construction)", pol["rules_oracle"]),
    ]
    T["tab_floors"] = (
        "\\begin{tabular}{@{}lrrr@{}}\n\\toprule\nPolicy or model & Accuracy & $R_w$ & Flag F1 \\\\\n\\midrule\n"
        + "\n".join(f"{n} & {v['accuracy']:.4f} & {v['severity_weighted_recall']:.4f} & {v['flag_f1']:.4f} \\\\" for n, v in fl)
        + "\n\\bottomrule\n\\end{tabular}\n"
    )
    return T


def figures(N: dict[str, str], outdir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
        "pdf.fonttype": 42, "ps.fonttype": 42, "axes.linewidth": 0.6,
    })
    INK, MUTE, BLUE, ORANGE = "#222222", "#6b6b6b", "#1f5fa8", "#c4600a"

    tsv = J("training-seed-variance.json")
    margin = tsv["prereg_evaluation"]["observed_margin"]
    ds = tsv["prereg_evaluation"]["deepseek_r_w_seed777"]
    pts = [(f"seed {s}", tsv["per_seed"][s]["severity_weighted_recall"], False) for s in ("202", "303", "101")]
    pts.append(("seed 7\n(shipped)", tsv["champion_r_w_same_pool"], True))
    pts.sort(key=lambda p: p[1])
    fig, ax = plt.subplots(figsize=(5.4, 3.0))
    xs = range(len(pts))
    for x, (lab, v, ship) in zip(xs, pts):
        ax.plot([x], [v], "o", ms=8, color=ORANGE if ship else BLUE, mec="white", mew=1.5, zorder=3)
        ax.annotate(f"{v:.4f}", (x, v), textcoords="offset points", xytext=(0, 9), ha="center", color=INK, fontsize=8)
    ax.set_xticks(list(xs), [p[0] for p in pts])
    rw = tsv["severity_weighted_recall"]
    ax.axhspan(rw["mean"] - rw["sd"], rw["mean"] + rw["sd"], color=BLUE, alpha=0.08, lw=0)
    ax.axhline(rw["mean"], color=BLUE, lw=0.8, alpha=0.6)
    ax.text(3.45, rw["mean"], "mean of four\n$\\pm$1 SD", va="center", ha="left", fontsize=7.5, color=MUTE)
    ax.axhline(ds, color=MUTE, lw=0.9, ls=(0, (4, 3)))
    ax.text(-0.45, ds + 0.004, f"DeepSeek on the 800-task pool ({ds:.4f})", fontsize=7.5, color=MUTE, va="bottom")
    # the claimed margin, drawn at the same scale beside the spread
    xm = 3.3
    ax.plot([xm, xm], [ds, ds + margin], color=INK, lw=2.2, solid_capstyle="butt")
    ax.text(xm + 0.08, ds + margin / 2 + 0.002, "claimed\nmargin", fontsize=7.5, color=INK, va="center")
    ax.set_xlim(-0.55, 4.5)
    ax.set_ylim(0.70, 1.0)
    ax.set_ylabel("severity-weighted recall $R_w$")
    ax.grid(axis="y", lw=0.4, color="#dddddd")
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(outdir / "fig_seeds.pdf")
    plt.close(fig)

    cl = J("checkpoint-loss-correlation.json")["per_checkpoint"]
    it = [r["iter"] for r in cl]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(5.4, 3.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    a1.plot(it, [r["severity_weighted_recall"] for r in cl], "-o", color=BLUE, ms=4, lw=1)
    a1.plot([700], [cl[-1]["severity_weighted_recall"]], "o", ms=7, color=ORANGE, mec="white", mew=1.2, zorder=3)
    a1.annotate("shipped (iter 700)", (700, cl[-1]["severity_weighted_recall"]), textcoords="offset points",
                xytext=(-8, -2), ha="right", va="top", fontsize=7.5, color=INK)
    a1.annotate("loss improves,\n$R_w$ collapses", (200, [r for r in cl if r["iter"] == 200][0]["severity_weighted_recall"]),
                textcoords="offset points", xytext=(14, -6), fontsize=7.5, color=MUTE, va="top")
    a1.set_ylabel("$R_w$ on dev pool")
    a1.grid(axis="y", lw=0.4, color="#dddddd")
    a2.plot(it, [r["val_loss"] for r in cl], "-o", color=MUTE, ms=3.5, lw=1)
    a2.set_ylim(0.08, 0.16)
    a2.set_ylabel("validation loss")
    a2.set_xlabel("training step (one run, fourteen saved checkpoints)")
    a2.grid(axis="y", lw=0.4, color="#dddddd")
    fig.tight_layout()
    fig.savefig(outdir / "fig_checkpoints.pdf")
    plt.close(fig)


def build(out: Path) -> dict[str, str]:
    (out / "generated").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    N = build_numbers()
    write_numbers(N, out / "generated" / "numbers.tex")
    for name, body in tables(N).items():
        (out / "generated" / f"{name}.tex").write_text(body)
    figures(N, out / "figures")
    return N


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    build(dest)
    print(f"wrote numbers, tables and figures under {dest}")
