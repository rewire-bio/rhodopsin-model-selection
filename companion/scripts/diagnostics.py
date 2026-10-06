"""Diagnostics that explain WHY the panel behaves as it does.

Three questions, each answered from the completed run rather than asserted:

1. How much do the predictions actually vary, compared with the thing being predicted?
   A model whose predictions span 2 nm against a 32 nm measured spread is a constant
   with a wobble, whatever its rank correlation says.
2. Does a fixed, unscaled ridge alpha hold regularisation constant when the
   representation changes? It does not, and the size of the effect is reported here.
3. Is a red-shifted hit in a top-10 shortlist evidence of skill, or is it within chance?
   The exact hypergeometric chance level is computed so the answer is not a guess.
"""
from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path

import numpy as np

from rhomax_panel import analysis, data, features


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", default="./cache")
    parser.add_argument("--results", default="./results")
    parser.add_argument("--output")
    parser.add_argument("--capacity", type=int, default=10)
    args = parser.parse_args()

    cache = Path(args.cache).expanduser().resolve()
    stored = np.load(Path(args.results).resolve() / "test-predictions.npz", allow_pickle=False)
    targets = stored["targets"]
    labels = [k for k in stored.files if k not in analysis.NON_PREDICTION_KEYS]

    spread = {
        "measured_sd_nm": float(targets.std(ddof=1)),
        "measured_range_nm": [float(targets.min()), float(targets.max())],
        "per_configuration": {},
    }
    for label in labels:
        values = stored[label]
        sd = float(values.std(ddof=1))
        spread["per_configuration"][label] = {
            "prediction_sd_nm": sd,
            "prediction_range_nm": [float(values.min()), float(values.max())],
            "prediction_span_nm": float(values.max() - values.min()),
            "sd_as_fraction_of_measured": sd / float(targets.std(ddof=1)),
            "pearson_r_with_measured": (
                None if np.ptp(values) == 0 else float(np.corrcoef(targets, values)[0, 1])
            ),
        }

    # Why the spreads differ: alpha is fixed at 10 and features are not scaled, so the
    # shrinkage each representation feels depends on that representation's own scale.
    rows, _ = data.load(cache)
    sequences = [r.sequence for r in rows]
    matrices = {
        "composition-22": features.composition_22(sequences),
        "composition-40": features.composition_40(sequences),
    }
    for label, name in (("esm2-8m", "esm2_t6_8M_UR50D"), ("esm2-35m", "esm2_t12_35M_UR50D")):
        path = cache / f"embeddings-{name}-{features.embedding_cache_key(name, data.CSV_SHA256)}.npz"
        if path.exists():
            matrices[label] = np.load(path, allow_pickle=False)["vectors"]

    scale = {
        "alpha": 10.0,
        "feature_scaling": "none (as archived)",
        "note": (
            "Ridge shrinkage is governed by feature variance relative to alpha. With alpha "
            "fixed and no feature scaling, the same alpha is a far heavier penalty for "
            "small-scale composition fractions than for ESM-2 embeddings, so the five "
            "configurations do not share a common amount of regularisation."
        ),
        "per_representation": {
            label: {
                "dimension": int(matrix.shape[1]),
                "mean_abs_value": float(np.abs(matrix).mean()),
                "total_feature_variance": float(matrix.var(axis=0).sum()),
                "total_variance_over_alpha": float(matrix.var(axis=0).sum() / 10.0),
                "constant_columns": int((matrix.std(axis=0) == 0).sum()),
            }
            for label, matrix in matrices.items()
        },
    }

    n, capacity = len(targets), args.capacity
    chance = {}
    for threshold in (570.0, 580.0, 585.0):
        hits = int((targets >= threshold).sum())
        chance[f"at_least_one_ge_{threshold:.0f}nm"] = {
            "rows_at_or_above": hits,
            "population": n,
            "capacity": capacity,
            "probability_under_uniform_random_shortlist": (
                1.0 - comb(n - hits, capacity) / comb(n, capacity) if hits <= n - capacity else 1.0
            ),
        }

    report = {
        "prediction_spread": spread,
        "fixed_alpha_is_not_fixed_regularisation": scale,
        "chance_level_for_a_red_shifted_hit": chance,
        "reading": (
            "A high rank correlation with a 2 nm prediction span does not give a usable "
            "wavelength estimate, and a single red-shifted protein appearing in a top-10 "
            "shortlist is not evidence of skill when the chance level is around one in three."
        ),
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
