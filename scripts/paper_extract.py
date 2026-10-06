#!/usr/bin/env python3
"""Format archived historical results into LaTeX tables for the imported-evidence paper.

Formatting and extraction only; nothing is recomputed. Values are read from members of the
archived `downloads/rhomax-wavelength-results.tar.gz` (read in memory, never extracted). The
archive digest is checked against `evidence/import-manifest.json` and every member against the
member digests recorded in `evidence/migration-audit.json`. Values that the original article
printed are cross-checked numerically at the article's printed precision (ARTICLE below); any
disagreement stops the build. Standard library only; no network, no environment creation.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARPATH = "downloads/rhomax-wavelength-results.tar.gz"
PREFIX = "rhomax-wavelength-results/"
GEN = ROOT / "paper/generated"
NAMES = {"composition-22": "Composition, 22 features", "composition-40": "Composition, 40 features",
         "training-mean": "Training mean", "nearest-train-seq": "Nearest training sequence",
         "esm2-8m": "ESM-2 8M, layer 6, residue mean", "esm2-35m": "ESM-2 35M, layer 12, residue mean"}
SHORT = {"composition-22": "Composition-22", "composition-40": "Composition-40", "training-mean": "Training mean",
         "nearest-train-seq": "Nearest sequence", "esm2-8m": "ESM-2 8M", "esm2-35m": "ESM-2 35M"}
T2_ORDER = ["composition-22", "composition-40", "training-mean", "nearest-train-seq", "esm2-8m", "esm2-35m"]

# Values printed in the original article (Table 2, 3, 4, 5, 6, 8 and text), checked at printed precision.
ARTICLE = {
    "spearman": {"composition-22": "+0.418", "composition-40": "+0.418", "nearest-train-seq": "+0.3385", "esm2-8m": "-0.146", "esm2-35m": "-0.222"},
    "ndcg": {"composition-22": "0.9548", "composition-40": "0.9548", "training-mean": "0.9207", "nearest-train-seq": "0.9453", "esm2-8m": "0.8965", "esm2-35m": "0.9073"},
    "mae": {"composition-22": "24.36", "composition-40": "24.36", "training-mean": "24.60", "nearest-train-seq": "27.50", "esm2-8m": "28.90", "esm2-35m": "29.16"},
    "rmse": {"composition-22": "32.29", "composition-40": "32.29", "training-mean": "32.50", "nearest-train-seq": "34.73", "esm2-8m": "41.23", "esm2-35m": "39.04"},
    "dmae": {"composition-22": ("-0.24", "-0.45", "-0.05"), "composition-40": ("-0.24", "-0.45", "-0.05"),
             "nearest-train-seq": ("+2.90", "-7.86", "+12.21"), "esm2-8m": ("+4.30", "-0.58", "+11.26"), "esm2-35m": ("+4.56", "+0.80", "+9.25")},
    "spread": {"composition-22": ("0.65", "2.2", "2.0", "+0.3621"), "esm2-35m": ("13.66", "57.2", "42.5", "-0.3488"),
               "esm2-8m": ("15.73", "54.7", "48.9", "-0.3120"), "nearest-train-seq": ("19.69", "75.0", "61.2", "+0.2550")},
    "bandA": {"composition-22": ("0.90", "6.30", "0.33", "1.00"), "nearest-train-seq": ("0.60", "17.40", "0.09", "1.00"),
              "esm2-8m": ("0.40", "23.60", "0.00", "0.88"), "esm2-35m": ("0.00", "69.80", "0.00", "0.20")},
    "redB": {"composition-22": ("553.50", "564", "546.0", "560.6"), "nearest-train-seq": ("550.20", "564", "513.6", "560.0"),
             "esm2-35m": ("544.00", "587", "489.5", "558.6"), "esm2-8m": ("506.20", "587", "474.7", "556.8")},
    "bins_near": {"nearest-train-seq": "6.60", "esm2-8m": "13.49", "composition-22": "15.11", "training-mean": "16.16", "esm2-35m": "16.29"},
    "bins_far": {"nearest-train-seq": "31.38", "esm2-8m": "28.18", "composition-22": "24.47", "training-mean": "24.71", "esm2-35m": "26.38"},
    "bins_nolen": {"nearest-train-seq": "24.97", "esm2-8m": "30.41", "composition-22": "24.76", "training-mean": "24.97", "esm2-35m": "32.49"},
    "probe": {"training-mean": ("37.7", "0.772", "0.706", "0.826"), "composition-22": ("38.1", "0.783", "0.718", "0.836"),
              "nearest-train-seq": ("41.7", "0.788", "0.723", "0.841"), "esm2-35m": ("43.4", "0.766", "0.700", "0.822"),
              "esm2-8m": ("47.5", "0.837", "0.777", "0.883")},
    "scalars": {"random_precision": "0.3098", "random_dev": "26.31", "random_mean": "534.43", "measured_sd": "32.15",
                "ndcg_worst": "0.8131", "ndcg_rand_mean": "0.9207", "ndcg_p2.5": "0.8975", "ndcg_p97.5": "0.9403",
                "p580": "0.3283", "p585": "0.2018", "var_comp22": "0.00105706", "var_comp40": "0.00034495", "var_esm35": "0.0817550",
                "embed35": "35.2", "embed8": "13.2", "mps": "2.22", "cpu": "0.55"},
}


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def close(value: float, printed: str) -> bool:
    s = printed.replace("−", "-")
    digits = len(s.split(".")[1]) if "." in s else 0
    return abs(value - float(s)) <= 0.5 * 10 ** (-digits) + 1e-12


def sgn(x: float, nd: int) -> str:
    s = f"{x:+.{nd}f}"
    return "$" + ("+0." + "0" * nd if s == "-0." + "0" * nd else s) + "$"


def main() -> None:
    GEN.mkdir(parents=True, exist_ok=True)
    manifest = {f["path"]: f["sha256"] for f in json.loads((ROOT / "evidence/import-manifest.json").read_text())["files"]}
    audit = json.loads((ROOT / "evidence/migration-audit.json").read_text())
    members = {m["path"]: m["sha256"] for a in audit["archives"] if a["path"] == TARPATH for m in a["members"]}
    raw = (ROOT / TARPATH).read_bytes()
    if sha256(raw) != manifest[TARPATH]:
        sys.exit("results archive digest mismatch")
    tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    used: dict[str, str] = {}

    def read(name: str):
        data = tf.extractfile(PREFIX + name).read()  # in-memory read of one member
        if sha256(data) != members[PREFIX + name]:
            sys.exit(f"member digest mismatch: {name}")
        used[PREFIX + name] = members[PREFIX + name]
        return json.loads(data) if name.endswith(".json") else data.decode()

    PR = read("panel-receipt.json")
    EA = read("exploratory-analysis.json")
    DG = read("diagnostics.json")
    NR = read("ndcg-finite-reference.json")
    DA = read("device-agreement.json")
    TP = read("test-predictions.json")
    IR = read("independent-recomputation.txt")
    archived_names = sorted(n[len(PREFIX):] for n in members)
    mism: list[str] = []

    def check(label: str, value, printed: str) -> None:
        if value is None or not close(float(value), printed):
            mism.append(f"{label}: archive {value!r} vs article {printed!r}")

    sc = PR["scores"]
    boot = EA["paired_bootstrap_vs_training-mean"]

    # ---- Table 2: panel
    lines = []
    for k in T2_ORDER:
        s = sc[k]
        if k in ARTICLE["spearman"]:
            check(f"spearman {k}", s["spearman"], ARTICLE["spearman"][k])
        check(f"ndcg {k}", s["ndcg"], ARTICLE["ndcg"][k])
        check(f"mae {k}", s["mae_nm"], ARTICLE["mae"][k])
        check(f"rmse {k}", s["rmse_nm"], ARTICLE["rmse"][k])
        rho = "undefined" if s["spearman"] is None else sgn(s["spearman"], 3)
        if k == "training-mean":
            d, ci, verdict = "baseline", "n/a", "comparator"
        else:
            b = boot[k]
            w = ARTICLE["dmae"][k]
            check(f"dmae {k}", b["observed_delta_mae_nm"], w[0])
            check(f"dmae lo {k}", b["ci95_low"], w[1])
            check(f"dmae hi {k}", b["ci95_high"], w[2])
            d = sgn(b["observed_delta_mae_nm"], 2)
            ci = f"[{sgn(b['ci95_low'], 2)}, {sgn(b['ci95_high'], 2)}]"
            if b["supported_difference"]:
                verdict = "supported: worse than a constant" if b["observed_delta_mae_nm"] > 0 else "supported"
            elif b["interval_excludes_zero"]:
                verdict = "direction resolved, below the 2\\,nm threshold"
            else:
                verdict = "no supported difference"
        lines.append(f"{NAMES[k]} & {rho} & {s['ndcg']:.4f} & {s['mae_nm']:.2f} & {s['rmse_nm']:.2f} & {d} & {ci} & {verdict} \\\\")
    (GEN / "tab_panel.tex").write_text("\n".join(lines) + "\n")

    # Appendix: bootstrap details
    lines = []
    for k in T2_ORDER[:2] + T2_ORDER[3:]:
        b = boot[k]
        lines.append(f"{SHORT[k]} & {sgn(b['observed_delta_mae_nm'], 4)} & [{sgn(b['ci95_low'], 4)}, {sgn(b['ci95_high'], 4)}] & "
                     f"{sgn(b['bootstrap_bias_nm'], 4)} & {b['fraction_favouring_candidate']:.4f} & "
                     f"{'yes' if b['interval_excludes_zero'] else 'no'} & {'yes' if b['meets_min_effect'] else 'no'} & "
                     f"{'yes' if b['supported_difference'] else 'no'} \\\\")
    (GEN / "tab_bootstrap.tex").write_text("\n".join(lines) + "\n")

    # ---- Table 3: prediction spread
    ps = DG["prediction_spread"]
    check("measured sd", ps["measured_sd_nm"], ARTICLE["scalars"]["measured_sd"])
    lines = ["Training mean & 0.00 & 0.0 & 0\\% & undefined \\\\"]
    for k in ("composition-22", "composition-40", "esm2-35m", "esm2-8m", "nearest-train-seq"):
        p = ps["per_configuration"][k]
        if k in ARTICLE["spread"]:
            w = ARTICLE["spread"][k]
            check(f"spread sd {k}", p["prediction_sd_nm"], w[0])
            check(f"spread span {k}", p["prediction_span_nm"], w[1])
            check(f"spread pct {k}", 100 * p["sd_as_fraction_of_measured"], w[2])
            check(f"spread r {k}", p["pearson_r_with_measured"], w[3])
        lines.append(f"{SHORT[k]} & {p['prediction_sd_nm']:.2f} & {p['prediction_span_nm']:.1f} & "
                     f"{100 * p['sd_as_fraction_of_measured']:.1f}\\% & {sgn(p['pearson_r_with_measured'], 4)} \\\\")
    (GEN / "tab_spread.tex").write_text("\n".join(lines) + "\n")

    # ---- Regularisation table
    reg = DG["fixed_alpha_is_not_fixed_regularisation"]["per_representation"]
    check("var comp22", reg["composition-22"]["total_variance_over_alpha"], ARTICLE["scalars"]["var_comp22"])
    check("var comp40", reg["composition-40"]["total_variance_over_alpha"], ARTICLE["scalars"]["var_comp40"])
    check("var esm35", reg["esm2-35m"]["total_variance_over_alpha"], ARTICLE["scalars"]["var_esm35"])
    lines = [f"{SHORT[k]} & {v['dimension']} & {v['constant_columns']} & {v['total_feature_variance']:.6f} & "
             f"{v['total_variance_over_alpha']:.8f} \\\\" for k, v in reg.items()]
    (GEN / "tab_regularisation.tex").write_text("\n".join(lines) + "\n")

    # ---- Decision A and B
    rr = EA["random_reference"]
    check("random precision", rr["expected_precision_at_capacity"], ARTICLE["scalars"]["random_precision"])
    check("random dev", rr["expected_mean_abs_deviation_from_centre_nm"], ARTICLE["scalars"]["random_dev"])
    check("random mean", rr["expected_mean_measured_nm"], ARTICLE["scalars"]["random_mean"])
    sl, ph = EA["shortlists"], EA["post_hoc"]["shortlist_spread"]
    linesA, linesB = [], []
    for k in ("composition-22", "composition-40", "nearest-train-seq", "esm2-8m", "esm2-35m"):
        a, b, p = sl[k]["band"], sl[k]["redshift"], ph[k]
        if k in ARTICLE["bandA"]:
            w = ARTICLE["bandA"][k]
            check(f"A prec {k}", a["precision_at_capacity"], w[0])
            check(f"A dev {k}", a["mean_abs_deviation_from_centre_nm"], w[1])
            check(f"A lo {k}", p["band_precision_ci95"][0], w[2])
            check(f"A hi {k}", p["band_precision_ci95"][1], w[3])
            w = ARTICLE["redB"][k]
            check(f"B mean {k}", b["mean_measured_nm"], w[0])
            check(f"B max {k}", b["max_measured_nm"], w[1])
            check(f"B lo {k}", p["redshift_mean_ci95_nm"][0], w[2])
            check(f"B hi {k}", p["redshift_mean_ci95_nm"][1], w[3])
        linesA.append(f"{SHORT[k]} & {a['in_band_count']}/{a['capacity']} & {a['precision_at_capacity']:.2f} & "
                      f"{a['mean_abs_deviation_from_centre_nm']:.2f} & [{p['band_precision_ci95'][0]:.2f}, {p['band_precision_ci95'][1]:.2f}] \\\\")
        linesB.append((b["mean_measured_nm"], f"{SHORT[k]} & {b['mean_measured_nm']:.2f} & {b['max_measured_nm']:.0f} & "
                       f"[{p['redshift_mean_ci95_nm'][0]:.1f}, {p['redshift_mean_ci95_nm'][1]:.1f}] \\\\"))
    linesA.append("Training mean & no shortlist & n/a & n/a & n/a \\\\")
    linesA.append(f"Uniform random (analytic) & n/a & {rr['expected_precision_at_capacity']:.4f} & "
                  f"{rr['expected_mean_abs_deviation_from_centre_nm']:.2f} & n/a \\\\")
    measured = sorted((r["measured_nm"] for r in TP), reverse=True)
    oracle = sum(measured[:10]) / 10  # arithmetic mean of the ten largest archived targets (formatting of the oracle row)
    linesB.append((oracle + 1e6, f"Oracle (best possible top 10) & {oracle:.2f} & {measured[0]:.0f} & n/a \\\\"))
    linesB.append((rr["expected_mean_measured_nm"], f"Uniform random (analytic) & {rr['expected_mean_measured_nm']:.2f} & n/a & n/a \\\\"))
    if f"{oracle:.2f}" != "583.30":
        mism.append(f"oracle top-ten mean {oracle:.2f} != 583.30")
    linesB.sort(key=lambda t: -t[0])
    (GEN / "tab_decisionA.tex").write_text("\n".join(linesA) + "\n")
    (GEN / "tab_decisionB.tex").write_text("\n".join(l for _, l in linesB) + "\nTraining mean & no shortlist & n/a & n/a \\\\\n")

    # Appendix: red-shift shortlists (measured nm in rank order)
    lines = []
    for k in ("composition-22", "nearest-train-seq", "esm2-8m", "esm2-35m"):
        sel = sl[k]["redshift"]["selected"]
        vals = " & ".join(f"{int(r['measured_nm'])}" for r in sel)
        lines.append(f"{SHORT[k]} & {vals} \\\\")
    (GEN / "tab_shortlistB.tex").write_text("\n".join(lines) + "\n")

    # ---- Distance bins
    bins = {b["bin"]: b for b in EA["distance_bins"]}
    order = ["nearest-train-seq", "esm2-8m", "composition-22", "training-mean", "esm2-35m"]
    for name, key in (("near", "bins_near"), ("far", "bins_far"), ("no_length_match", "bins_nolen")):
        for k in order:
            check(f"bin {name} {k}", bins[name]["mae_nm"][k], ARTICLE[key][k])
    lab = {"near": "near, $d \\le 0.05$", "mid": "mid, $0.05 < d \\le 0.25$", "far": "far, $0.25 < d < 1.0$",
           "no_length_match": "no equal-length training sequence"}
    lines = []
    for name in ("near", "mid", "far", "no_length_match"):
        b = bins[name]
        meets = "yes" if b["meets_min_bin_size"] else ("no, empty" if b["n"] == 0 else "no")
        if b["n"] == 0:
            lines.append(f"{lab[name]} & 0 & {meets} & n/a & " + " & ".join("n/a" for _ in order) + " \\\\")
            continue
        t = b["target_nm"]
        cells = []
        best = min(b["mae_nm"][k] for k in order)
        for k in order:
            v = f"{b['mae_nm'][k]:.2f}"
            cells.append(f"\\textbf{{{v}}}" if name == "near" and b["mae_nm"][k] == best else v)
        lines.append(f"{lab[name]} & {b['n']} & {meets} & {t['min']:.0f}--{t['max']:.0f} & " + " & ".join(cells) + " \\\\")
    (GEN / "tab_bins.tex").write_text("\n".join(lines) + "\n")
    comp_same = all(abs(bins[n]["mae_nm"]["composition-22"] - bins[n]["mae_nm"]["composition-40"]) < 0.005
                    for n in ("near", "far", "no_length_match"))
    if not comp_same:
        mism.append("composition variants differ at two decimals in a bin")

    # ---- Example rows (as selected in the original article's Table 7)
    by = {r["seq_id"]: r for r in TP}
    lines = []
    for sid in ("1126648311d3", "78c26b0b585d", "1937f73b396e", "c28e8cbcbc78", "848b6cf05e5c", "781ca2b1c04b"):
        r = by[sid]
        d = r["nearest_train_distance"]
        nn = r["nearest_train_seq_id"]
        dtxt = f"{d:.4f}" if nn else "1.0000, no match"
        nntext = "\\texttt{" + nn + "}" if nn else "none"
        lines.append(f"\\texttt{{{sid}}} & {r['csv_row']} & {r['length']} & {r['measured_nm']:.0f} & {dtxt} & "
                     f"{nntext} & {r['pred_nearest-train-seq_nm']:.2f} & "
                     f"{r['pred_composition-22_nm']:.2f} & {r['pred_esm2-35m_nm']:.2f} \\\\")
    (GEN / "tab_rows.tex").write_text("\n".join(lines) + "\n")

    # ---- Interval probe
    vif = EA["post_hoc"]["validation_interval_feasibility"]
    lines = []
    for k in ("training-mean", "composition-22", "composition-40", "nearest-train-seq", "esm2-35m", "esm2-8m"):
        v = vif[k]
        if k in ARTICLE["probe"]:
            w = ARTICLE["probe"][k]
            check(f"probe hw {k}", v["half_width_nm"], w[0])
            check(f"probe cov {k}", v["observed_test_coverage"], w[1])
            check(f"probe lo {k}", v["observed_test_coverage_wilson95"][0], w[2])
            check(f"probe hi {k}", v["observed_test_coverage_wilson95"][1], w[3])
        lo, hi = v["observed_test_coverage_wilson95"]
        lines.append(f"{SHORT[k]} & {v['half_width_nm']:.1f} & {v['observed_test_coverage']:.3f} & [{lo:.3f}, {hi:.3f}] & "
                     f"{v['nominal_coverage']:.2f} \\\\")
    (GEN / "tab_probe.tex").write_text("\n".join(lines) + "\n")

    # ---- Per-group MAE (appendix)
    lines = []
    for g in EA["per_group"]:
        m = g["mae_nm"]
        n = g.get("n", g.get("rows", ""))
        lines.append(f"{g['group']} & {n} & " + " & ".join(f"{m[k]:.2f}" for k in
                     ("training-mean", "composition-22", "nearest-train-seq", "esm2-8m", "esm2-35m")) + " \\\\")
    (GEN / "tab_groups.tex").write_text("\n".join(lines) + "\n")

    # ---- Reproduction check (appendix)
    lines = []
    for r in PR["reproduction_vs_archive"]:
        c = r["checks"]
        sp = c["spearman"]
        spa = "undefined" if sp["archived"] is None else f"{sp['archived']:+.8f}"
        spd = "n/a" if sp.get("absolute_difference") is None else f"{sp['absolute_difference']:g}"
        lines.append(f"{SHORT[r['configuration']]} & {spa} & {spd} & {c['ndcg']['archived']:.8f} & "
                     f"{c['ndcg']['absolute_difference']:g} & {r['status']} \\\\")
    (GEN / "tab_repro.tex").write_text("\n".join(lines) + "\n")

    # ---- Timings
    ts = PR["timings_seconds"]
    lines = []
    for k in ("training-mean", "composition-22", "composition-40", "nearest-train-seq", "esm2-8m", "esm2-35m"):
        t = ts[k]
        feat = t.get("feature_seconds")
        emb = t.get("embedding", {}).get("embed_seconds")
        lines.append(f"{SHORT[k]} & {('%.4f' % feat) if feat is not None else ('%.1f' % emb if emb else '--')} & "
                     f"{t['fit_predict_seconds']:.4f} \\\\")
    (GEN / "tab_timings.tex").write_text("\n".join(lines) + "\n")
    check("embed35", ts["esm2-35m"]["embedding"]["embed_seconds"], ARTICLE["scalars"]["embed35"])
    check("embed8", ts["esm2-8m"]["embedding"]["embed_seconds"], ARTICLE["scalars"]["embed8"])
    check("mps", DA["mps_embed_seconds"], ARTICLE["scalars"]["mps"])
    check("cpu", DA["cpu_embed_seconds"], ARTICLE["scalars"]["cpu"])

    # ---- NDCG scale and chance levels
    rp = NR["random_permutations"]
    check("ndcg worst", NR["worst_ranking_reverse_order"], ARTICLE["scalars"]["ndcg_worst"])
    check("ndcg rand mean", rp["mean"], ARTICLE["scalars"]["ndcg_rand_mean"])
    check("ndcg p2.5", rp["p2_5"], ARTICLE["scalars"]["ndcg_p2.5"])
    check("ndcg p97.5", rp["p97_5"], ARTICLE["scalars"]["ndcg_p97.5"])
    ch = DG["chance_level_for_a_red_shifted_hit"]
    check("p580", ch["at_least_one_ge_580nm"]["probability_under_uniform_random_shortlist"], ARTICLE["scalars"]["p580"])
    check("p585", ch["at_least_one_ge_585nm"]["probability_under_uniform_random_shortlist"], ARTICLE["scalars"]["p585"])
    lines = [f"$\\ge {k.split('_')[-1].replace('nm', '')}$\\,nm & {v['rows_at_or_above']} & "
             f"{v['probability_under_uniform_random_shortlist']:.4f} \\\\" for k, v in ch.items()]
    (GEN / "tab_chance.tex").write_text("\n".join(lines) + "\n")

    env = PR["environment"]
    grp = EA["grouping"]
    mac = {
        "NdcgWorst": f"{NR['worst_ranking_reverse_order']:.4f}", "NdcgRandMean": f"{rp['mean']:.4f}",
        "NdcgRandLo": f"{rp['p2_5']:.4f}", "NdcgRandHi": f"{rp['p97_5']:.4f}", "NdcgDraws": f"{rp['draws']:,}",
        "NdcgSeed": str(rp["seed"]), "Groups": str(grp["groups"]), "Singletons": str(grp["singletons"]),
        "LargestGroup": str(grp["largest"]), "RowsBigGroups": str(grp["rows_in_groups_of_at_least_10"]),
        "Draws": f"{boot['esm2-35m']['draws']:,}", "BootSeed": str(boot["esm2-35m"]["seed"]),
        "WallSeconds": f"{PR['total_wall_seconds']:.1f}", "PeakRSS": f"{PR['peak_rss_mb'] / 1024:.2f}",
        "EnvPython": env["python"], "EnvTorch": env["torch"], "EnvSklearn": env["scikit-learn"], "EnvNumpy": env["numpy"],
        "EnvScipy": env["scipy"], "Fallbacks": str(PR["nearest_neighbour_fallbacks"]),
        "DeviceMaxDiff": f"{DA['embedding_max_abs_difference']:.1e}", "DeviceSeqs": str(DA["sequences_compared"]),
        "ShortlistDepthMin": str(ph["composition-22"]["realised_capacity"]["min"]),
        "ShortlistDepthMax": str(ph["composition-22"]["realised_capacity"]["max"]),
    }
    (GEN / "macros.tex").write_text("".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in mac.items()))

    receipt = {
        "schema_version": 1,
        "kind": "formatting/extraction only; no recomputation (the oracle row is the mean of the ten largest archived test targets)",
        "archive": TARPATH, "archive_sha256": manifest[TARPATH],
        "archive_members_present": archived_names,
        "members_read_in_memory": used,
        "independent_recomputation_excerpt": IR.strip().splitlines()[-1],
        "cross_check_against_article_values": "Tables 2-6 and 8, NDCG scale, chance levels, regularisation ratios, timings (numeric, at printed precision)",
        "cross_check_mismatches": mism,
        "generated": sorted(name for name in (
            "macros.tex", "tab_panel.tex", "tab_bootstrap.tex", "tab_spread.tex",
            "tab_regularisation.tex", "tab_decisionA.tex", "tab_decisionB.tex",
            "tab_shortlistB.tex", "tab_bins.tex", "tab_rows.tex", "tab_probe.tex",
            "tab_groups.tex", "tab_repro.tex", "tab_timings.tex", "tab_chance.tex")),
    }
    (GEN / "extraction-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if mism:
        print("\n".join(mism))
        sys.exit("generated tables disagree with the article's reported values")
    print(f"extracted {len(used)} archive members; {len(receipt['generated'])} generated files; 0 mismatches")


if __name__ == "__main__":
    main()
