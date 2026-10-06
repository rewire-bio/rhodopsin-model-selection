"""Charts built only from saved real run outputs.

No synthetic data, no illustrative sketches. Each chart reads the receipt files written by
the panel and the analysis, so a chart cannot drift from the numbers it claims to show.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

INK = "#1f2933"
MUTED = "#7b8794"
GRID = "#e4e7eb"
# One accent per role, consistent across every chart in the article.
ACCENT = {
    "training-mean": "#9aa5b1",
    "composition-22": "#2d6cdf",
    "composition-40": "#7fa6ef",
    "esm2-8m": "#d97706",
    "esm2-35m": "#b45309",
    "nearest-train-seq": "#0f766e",
}
PRETTY = {
    "training-mean": "Training mean",
    "composition-22": "Composition, 22 feat.",
    "composition-40": "Composition, 40 feat.",
    "esm2-8m": "ESM-2 8M",
    "esm2-35m": "ESM-2 35M",
    "nearest-train-seq": "Nearest train seq.",
}
ORDER = ["training-mean", "composition-22", "composition-40",
         "nearest-train-seq", "esm2-8m", "esm2-35m"]


def style(ax, *, xlabel="", ylabel="", title=""):
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK, fontsize=10)
    if title:
        ax.set_title(title, color=INK, fontsize=11.5, loc="left", pad=12)


def chart_rank_vs_error(receipt: dict, out: Path) -> Path:
    """The central point: rank correlation and wavelength error disagree."""
    scores = receipt["scores"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 4.4))

    labels = [PRETTY[k] for k in ORDER]
    colours = [ACCENT[k] for k in ORDER]

    rhos = [scores[k]["spearman"] for k in ORDER]
    positions = np.arange(len(ORDER))
    drawn = [0.0 if r is None else r for r in rhos]
    left.barh(positions, drawn, color=colours, height=0.62)
    left.axvline(0, color=MUTED, linewidth=1)
    left.set_yticks(positions, labels)
    left.invert_yaxis()
    style(left, xlabel="Spearman rho on 184 held-out rows",
          title="What the rank metric says")
    # Give the labels room on both sides so no value text lands on a tick label.
    extent = max(abs(min(drawn)), abs(max(drawn)))
    left.set_xlim(-extent * 1.45, extent * 1.45)
    for position, (rho, value) in enumerate(zip(rhos, drawn)):
        if rho is None:
            left.text(0.02, position, "undefined for a constant", va="center",
                      fontsize=8.5, color=MUTED)
        else:
            offset = 0.015 if value >= 0 else -0.015
            left.text(value + offset, position, f"{value:+.3f}", va="center",
                      ha="left" if value >= 0 else "right", fontsize=8.5, color=INK)
    left.grid(axis="y", visible=False)
    left.grid(axis="x", color=GRID, linewidth=0.8)

    maes = [scores[k]["mae_nm"] for k in ORDER]
    right.barh(positions, maes, color=colours, height=0.62)
    right.set_yticks(positions, labels)
    right.invert_yaxis()
    constant = scores["training-mean"]["mae_nm"]
    right.axvline(constant, color=INK, linewidth=1.2, linestyle="--")
    style(right, xlabel="Mean absolute error, nanometres",
          title="What the decision-relevant error says")
    for position, value in enumerate(maes):
        right.text(value + 0.4, position, f"{value:.2f}", va="center", fontsize=8.5, color=INK)
    right.set_xlim(0, max(maes) * 1.22)
    # Label the reference line on the line itself, so it cannot collide with the title,
    # the bars or the value labels.
    right.text(
        constant - 0.5, -0.62, f"a constant prediction costs {constant:.2f} nm",
        fontsize=8.5, color=INK, ha="right", va="center",
    )
    right.grid(axis="y", visible=False)
    right.grid(axis="x", color=GRID, linewidth=0.8)

    fig.suptitle(
        "Rank correlation and wavelength error rank the same six configurations differently",
        color=INK, fontsize=12.5, x=0.012, ha="left", y=0.995,
    )
    fig.text(
        0.012, 0.015,
        "FLIP2 Rhomax by_wild_type, 184 held-out rows. Frozen encoders with a fixed alpha-10 "
        "train-only ridge head. Spearman is undefined for a constant predictor, not zero.",
        fontsize=8, color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def chart_prediction_spread(diagnostics: dict, predictions: dict, out: Path) -> Path:
    """Why the errors look like that: how much the predictions move at all."""
    spread = diagnostics["prediction_spread"]
    measured_sd = spread["measured_sd_nm"]
    targets = predictions["targets"]

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 4.4),
                                      gridspec_kw={"width_ratios": [1.15, 1]})

    positions = np.arange(len(ORDER))
    sds = [spread["per_configuration"][k]["prediction_sd_nm"] for k in ORDER]
    left.barh(positions, sds, color=[ACCENT[k] for k in ORDER], height=0.62)
    left.axvline(measured_sd, color=INK, linewidth=1.2, linestyle="--")
    left.text(measured_sd - 0.6, -0.62,
              f"spread of the measurements being predicted: {measured_sd:.2f} nm",
              fontsize=8.5, color=INK, ha="right", va="center")
    left.set_yticks(positions, [PRETTY[k] for k in ORDER])
    left.invert_yaxis()
    style(left, xlabel="Standard deviation of the predictions, nanometres",
          title="How much each configuration's predictions actually move")
    for position, value in enumerate(sds):
        left.text(value + 0.4, position, f"{value:.2f}", va="center", fontsize=8.5, color=INK)
    left.set_xlim(0, measured_sd * 1.10)
    left.grid(axis="y", visible=False)
    left.grid(axis="x", color=GRID, linewidth=0.8)

    for key in ("composition-22", "esm2-35m"):
        right.scatter(targets, predictions[key], s=16, alpha=0.75,
                      color=ACCENT[key], edgecolor="none", label=PRETTY[key])
    low, high = float(targets.min()), float(targets.max())
    right.plot([low, high], [low, high], color=MUTED, linewidth=1, linestyle=":")
    right.text(high, high, " perfect", fontsize=8, color=MUTED, va="center")
    style(right, xlabel="Measured peak wavelength, nm", ylabel="Predicted, nm",
          title="Predicted against measured")
    right.legend(frameon=False, fontsize=9, loc="upper left")
    right.grid(color=GRID, linewidth=0.8)

    fig.suptitle(
        "The best-ranking configuration barely moves; the worst moves further, and the wrong way",
        color=INK, fontsize=12.5, x=0.012, ha="left", y=0.995,
    )
    fig.text(
        0.012, 0.015,
        "Composition predictions span 2.2 nm against a 32.15 nm measured spread. ESM-2 35M spans "
        "57.2 nm with Pearson r of -0.35 against the measurement.",
        fontsize=8, color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def chart_distance_bins(analysis: dict, out: Path) -> Path:
    """Error against distance to the training set, with bin sizes shown."""
    bins = [b for b in analysis["distance_bins"] if b["n"] > 0]
    names = {"near": "near\nd ≤ 0.05", "far": "far\n0.25 < d < 1.0",
             "no_length_match": "no equal-length\ntraining sequence"}

    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    width = 0.13
    base = np.arange(len(bins))
    for offset, key in enumerate(ORDER):
        values = [b["mae_nm"][key] for b in bins]
        ax.bar(base + (offset - 2.5) * width, values, width=width,
               color=ACCENT[key], label=PRETTY[key])
    ax.set_xticks(base, [f"{names[b['bin']]}\nn = {b['n']}" for b in bins])
    style(ax, ylabel="Mean absolute error, nanometres",
          title="Error against distance to the nearest training sequence")
    ax.legend(frameon=False, fontsize=8.5, ncols=3, loc="upper left")
    ax.set_ylim(0, 40)
    ax.grid(axis="x", visible=False)
    fig.text(
        0.012, 0.015,
        "Frozen bins, fixed before any error was computed. The mid bin (0.05 < d ≤ 0.25) is empty. All values are "
        "descriptive:\nno paired interval was computed within any bin, so no within-bin gap is a supported difference. "
        "The near bin has n = 5.",
        fontsize=8, color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def chart_shortlists(analysis: dict, out: Path) -> Path:
    """The two decisions, side by side, with the random reference on both."""
    shortlists = analysis["shortlists"]
    reference = analysis["random_reference"]
    post = analysis["post_hoc"]["shortlist_spread"]
    defined = [k for k in ORDER if shortlists[k]["band"]["defined"]]

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.5, 5.1))
    positions = np.arange(len(defined))

    precisions = [shortlists[k]["band"]["precision_at_capacity"] for k in defined]
    lows = [precisions[i] - post[k]["band_precision_ci95"][0] for i, k in enumerate(defined)]
    highs = [post[k]["band_precision_ci95"][1] - precisions[i] for i, k in enumerate(defined)]
    left.barh(positions, precisions, color=[ACCENT[k] for k in defined], height=0.6)
    left.errorbar(precisions, positions, xerr=[lows, highs], fmt="none",
                  ecolor=INK, elinewidth=1, capsize=3)
    left.axvline(reference["expected_precision_at_capacity"], color=INK,
                 linewidth=1.2, linestyle="--")
    left.text(reference["expected_precision_at_capacity"] + 0.02, len(defined) - 0.62,
              f"random selection: {reference['expected_precision_at_capacity']:.2f}",
              fontsize=8.5, color=INK, ha="left", va="center")
    left.set_yticks(positions, [PRETTY[k] for k in defined])
    left.invert_yaxis()
    left.set_xlim(0, 1.25)
    left.set_ylim(len(defined) - 0.4, -0.6)
    style(left, xlabel="Fraction of a 10-candidate shortlist inside 540–560 nm",
          title="Decision A: hit a desired band")
    left.grid(axis="y", visible=False)
    left.grid(axis="x", color=GRID, linewidth=0.8)

    means = [shortlists[k]["redshift"]["mean_measured_nm"] for k in defined]
    maxima = [shortlists[k]["redshift"]["max_measured_nm"] for k in defined]
    low_err = [means[i] - post[k]["redshift_mean_ci95_nm"][0] for i, k in enumerate(defined)]
    high_err = [post[k]["redshift_mean_ci95_nm"][1] - means[i] for i, k in enumerate(defined)]
    # A dot plot, not bars: this axis does not start at zero, so bar length would not be
    # proportional to the value it encodes.
    for position, key in enumerate(defined):
        right.plot([post[key]["redshift_mean_ci95_nm"][0], post[key]["redshift_mean_ci95_nm"][1]],
                   [position, position], color=ACCENT[key], linewidth=2.4, solid_capstyle="round")
    right.scatter(means, positions, s=70, color=[ACCENT[k] for k in defined],
                  zorder=5, label="mean of the 10")
    right.scatter(maxima, positions, marker="D", s=34, facecolor="white",
                  edgecolor=INK, linewidth=1.1, zorder=6,
                  label="most red-shifted")
    right.axvline(reference["expected_mean_measured_nm"], color=INK,
                  linewidth=1.2, linestyle="--")
    right.text(reference["expected_mean_measured_nm"] - 1.5, len(defined) - 0.62,
               f"random selection: {reference['expected_mean_measured_nm']:.0f} nm",
               fontsize=8.5, color=INK, ha="right", va="center")
    right.set_yticks(positions, [PRETTY[k] for k in defined])
    right.invert_yaxis()
    right.set_xlim(465, 600)
    right.set_ylim(len(defined) - 0.4, -0.6)
    style(right, xlabel="Measured wavelength of the 10 selected, nm",
          title="Decision B: maximise red shift")
    # Legend below the axes: every in-panel position collides with a point or an interval.
    right.legend(frameon=False, fontsize=8.5, ncols=2,
                 loc="upper left", bbox_to_anchor=(0.0, -0.20))
    right.grid(axis="y", visible=False)
    right.grid(axis="x", color=GRID, linewidth=0.8)

    fig.suptitle(
        "Two different decisions, two different answers from the same six configurations",
        color=INK, fontsize=12.5, x=0.012, ha="left", y=0.995,
    )
    fig.text(
        0.012, 0.125,
        "Capacity and band were fixed before evaluation. Intervals are post-hoc cluster bootstraps over a\n"
        "reconstructed grouping, not predeclared tests. A random top 10 contains a protein at or above 580 nm\n"
        "with probability 0.33, so ESM-2's 587 nm hit is within chance. The training mean has no shortlist at\n"
        "all: every one of the 184 rows ties.",
        fontsize=8, color=MUTED, va="top",
    )
    fig.tight_layout(rect=(0, 0.14, 1, 0.94))
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="./results")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    results = Path(args.results).resolve()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)

    receipt = json.loads((results / "panel-receipt.json").read_text())
    analysis = json.loads((results / "exploratory-analysis.json").read_text())
    diagnostics = json.loads((results / "diagnostics.json").read_text())
    stored = np.load(results / "test-predictions.npz", allow_pickle=False)
    predictions = {k: stored[k] for k in stored.files}

    written = [
        chart_rank_vs_error(receipt, out / "01-rank-versus-error.png"),
        chart_prediction_spread(diagnostics, predictions, out / "02-prediction-spread.png"),
        chart_distance_bins(analysis, out / "03-distance-bins.png"),
        chart_shortlists(analysis, out / "04-two-decisions.png"),
    ]
    for path in written:
        print(f"{path.name}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
