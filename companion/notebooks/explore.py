# %% [markdown]
# # Exploring the Rhomax wavelength panel
#
# Source form of the companion notebook, in jupytext percent format. Build the `.ipynb`
# with:
#
# ```bash
# jupytext --to notebook notebooks/explore.py
# ```
#
# It is kept as a plain script so it diffs and tests like code. `make_notebook.py`
# converts and executes it without needing jupytext installed.
#
# Run the panel first:
#
# ```bash
# rhomax-panel --cache ./cache panel --output ./results
# rhomax-panel --cache ./cache analyse --output ./results --baseline training-mean
# ```
#
# The endpoint throughout is peak absorption wavelength in nanometres. Nothing here says
# anything about activation, expression, photostability or cellular function.

# %%
import json
import os
from pathlib import Path

import numpy as np

RESULTS = Path(os.environ.get("RHOMAX_RESULTS", "./results"))
CACHE = Path(os.environ.get("RHOMAX_CACHE", "./cache"))

rows = json.loads((RESULTS / "test-predictions.json").read_text())
receipt = json.loads((RESULTS / "panel-receipt.json").read_text())
print(f"{len(rows)} held-out rows, target units {receipt['source']['target_units']}")

# %% [markdown]
# ## 1. Did the historical configurations reproduce?
#
# This is the first thing to check. If any row says anything other than `match`, nothing
# below is worth reading.

# %%
for record in receipt["reproduction_vs_archive"]:
    print(f"{record['configuration']:<16} {record['status']}")

# %% [markdown]
# ## 2. Rank correlation against error in nanometres
#
# The ordering differs. That is the article's point, and it is visible in two columns.

# %%
scores = receipt["scores"]
print(f"{'configuration':<20}{'Spearman':>12}{'MAE nm':>10}{'RMSE nm':>10}")
for key, score in sorted(scores.items(), key=lambda kv: kv[1]["mae_nm"]):
    rho = "undefined" if score["spearman"] is None else f"{score['spearman']:+.4f}"
    print(f"{key:<20}{rho:>12}{score['mae_nm']:>10.2f}{score['rmse_nm']:>10.2f}")

# %% [markdown]
# ## 3. How much do the predictions actually move?
#
# A model whose predictions span 2 nm cannot resolve a 32 nm spread, whatever its rank
# correlation says. This single cell explains most of the table above.

# %%
measured = np.array([r["measured_nm"] for r in rows])
print(f"measured spread: sd {measured.std(ddof=1):.2f} nm, "
      f"range {measured.min():.0f} to {measured.max():.0f} nm\n")
for key in scores:
    values = np.array([r[f"pred_{key}_nm"] for r in rows])
    correlation = "n/a" if np.ptp(values) == 0 else f"{np.corrcoef(measured, values)[0, 1]:+.3f}"
    print(f"{key:<20} sd {values.std(ddof=1):6.2f} nm   span {np.ptp(values):6.2f} nm   r {correlation}")

# %% [markdown]
# ## 4. Distance to the training set
#
# Half the held-out rows have no training sequence even of the same length. That is the
# transfer problem stated as a count.

# %%
distances = np.array([r["nearest_train_distance"] for r in rows])
print(f"rows with no equal-length training sequence: {(distances >= 1.0).sum()} of {len(rows)}")
print(f"rows within 5% Hamming of a training sequence: {(distances <= 0.05).sum()}")
print(f"rows between those two: {((distances > 0.05) & (distances < 1.0)).sum()}")

# %% [markdown]
# ## 5. Try your own shortlist criterion
#
# The article fixes capacity 10 and the band 540 to 560 nm before evaluating, and that is
# the number it reports. Changing them here is a sensitivity check, not a new headline
# result. The random reference moves with the band, so compare against it, not against the
# previous band's number.

# %%
def shortlist(key: str, capacity: int = 10, band: tuple[float, float] = (540.0, 560.0)):
    values = np.array([r[f"pred_{key}_nm"] for r in rows])
    if np.ptp(values) == 0:
        return f"{key}: no shortlist exists, every row ties"
    centre = (band[0] + band[1]) / 2
    order = np.argsort(np.abs(values - centre), kind="stable")[:capacity]
    chosen = measured[order]
    hits = int(((chosen >= band[0]) & (chosen <= band[1])).sum())
    prevalence = float(((measured >= band[0]) & (measured <= band[1])).mean())
    return (f"{key}: {hits}/{capacity} in band "
            f"(random expectation {prevalence:.2f})")


for key in ("composition-22", "esm2-8m", "esm2-35m", "nearest-train-seq", "training-mean"):
    print(shortlist(key))

# %% [markdown]
# ## 6. The rows the shortlist actually picked
#
# `seq_id` is a local digest of the sequence. The archive publishes no identifier of any
# kind, so these are not accessions and should not be cited as such.

# %%
values = np.array([r["pred_composition-22_nm"] for r in rows])
order = np.argsort(np.abs(values - 550.0), kind="stable")[:10]
print(f"{'seq_id':<14}{'csv_row':>8}{'predicted':>11}{'measured':>10}{'d_nn':>7}")
for index in order:
    row = rows[index]
    print(f"{row['seq_id']:<14}{row['csv_row']:>8}{row['pred_composition-22_nm']:>11.1f}"
          f"{row['measured_nm']:>10.0f}{row['nearest_train_distance']:>7.2f}")

# %% [markdown]
# ## 7. What the intervals cost
#
# Post-hoc, and not a calibration claim. A 90% interval calibrated on the unused validation
# rows needs roughly ±38 nm and still under-covers on test.

# %%
analysis_path = RESULTS / "exploratory-analysis.json"
if analysis_path.exists():
    feasibility = json.loads(analysis_path.read_text())["post_hoc"]["validation_interval_feasibility"]
    for key, record in feasibility.items():
        low, high = record["observed_test_coverage_wilson95"]
        print(f"{key:<20} ±{record['half_width_nm']:5.1f} nm  "
              f"coverage {record['observed_test_coverage']:.3f} "
              f"[{low:.3f}, {high:.3f}]  nominal {record['nominal_coverage']}")
else:
    print("run the analyse subcommand first")
