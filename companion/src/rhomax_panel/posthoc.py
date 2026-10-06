"""Analyses added AFTER the frozen protocol's results were seen.

Kept in a separate module so that the distinction is structural rather than a comment
somebody can delete. Everything here is labelled ``post_hoc_not_predeclared`` in its
output. None of it may be reported as confirmatory, and none of it is used to choose
between configurations.

Two things live here:

1. Cluster-bootstrap intervals for the shortlist metrics. The frozen protocol
   predeclared intervals for MAE differences only. The shortlist numbers are single
   realisations of picking 10 of 184 rows, so reporting them bare would invite
   over-reading. Showing a labelled post-hoc interval is more honest than withholding
   the spread, but it is not a predeclared test.
2. A feasibility check on validation-calibrated prediction intervals. The frozen
   protocol permits this only if it can be done honestly and requires it to be dropped
   otherwise. This reports what the data can and cannot support.
"""
from __future__ import annotations

import numpy as np

from .analysis import BAND, BAND_CENTRE, CAPACITY
from .data import Row
from .metrics import paired_vectors


def _band_precision(targets: np.ndarray, predictions: np.ndarray, capacity: int) -> float | None:
    if np.ptp(predictions) == 0 or len(targets) < capacity:
        return None
    order = np.argsort(np.abs(predictions - BAND_CENTRE), kind="stable")[:capacity]
    chosen = targets[order]
    return float(((chosen >= BAND[0]) & (chosen <= BAND[1])).sum() / capacity)


def _redshift_mean(targets: np.ndarray, predictions: np.ndarray, capacity: int) -> float | None:
    if np.ptp(predictions) == 0 or len(targets) < capacity:
        return None
    order = np.argsort(-predictions, kind="stable")[:capacity]
    return float(targets[order].mean())


def shortlist_bootstrap(
    targets: np.ndarray,
    predictions: np.ndarray,
    groups: list[str],
    *,
    draws: int = 10_000,
    seed: int = 20261001,
    capacity: int = CAPACITY,
) -> dict:
    """Cluster-bootstrap spread for the two shortlist metrics.

    Capacity is held at a constant FRACTION of the resampled list, not a constant count,
    because resampled lists vary in length when groups are unequal. The realised spread
    of capacity is reported so an interval is never read as "exactly 10".
    """
    targets, predictions = paired_vectors(targets, predictions)
    if len(groups) != len(targets) or draws < 1 or not 1 <= capacity <= len(targets):
        raise ValueError("Bootstrap needs matching groups, positive draws and feasible capacity")
    if np.ptp(predictions) == 0:
        return {
            "post_hoc_not_predeclared": True,
            "defined": False,
            "reason": "constant predictor: no shortlist exists to resample",
        }
    groups_array = np.asarray(groups)
    unique = np.unique(groups_array)
    index = {g: np.flatnonzero(groups_array == g) for g in unique}
    fraction = capacity / len(targets)

    rng = np.random.default_rng(seed)
    precisions, means, caps, skipped = [], [], [], 0
    for _ in range(draws):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        rows = np.concatenate([index[g] for g in drawn])
        cap = max(1, int(round(fraction * len(rows))))
        precision = _band_precision(targets[rows], predictions[rows], cap)
        mean = _redshift_mean(targets[rows], predictions[rows], cap)
        if precision is None or mean is None:
            skipped += 1
            continue
        precisions.append(precision)
        means.append(mean)
        caps.append(cap)

    if not precisions:
        return {"post_hoc_not_predeclared": True, "defined": False,
                "reason": "no usable bootstrap draws", "draws": draws, "seed": seed,
                "usable_draws": 0, "skipped_draws": skipped}
    precisions, means, caps = np.asarray(precisions), np.asarray(means), np.asarray(caps)
    return {
        "post_hoc_not_predeclared": True,
        "defined": True,
        "draws": draws,
        "seed": seed,
        "usable_draws": int(len(precisions)),
        "skipped_draws": skipped,
        "resampling_unit": "reconstructed background group (declared rule, not an archive label)",
        "groups": int(len(unique)),
        "realised_capacity": {
            "requested": capacity,
            "list_fraction": round(fraction, 5),
            "mean": float(caps.mean()),
            "min": int(caps.min()),
            "max": int(caps.max()),
        },
        "observed_band_precision": _band_precision(targets, predictions, capacity),
        "band_precision_ci95": [float(x) for x in np.percentile(precisions, [2.5, 97.5])],
        "observed_redshift_mean_nm": _redshift_mean(targets, predictions, capacity),
        "redshift_mean_ci95_nm": [float(x) for x in np.percentile(means, [2.5, 97.5])],
        "caveat": (
            "Resampling whole reconstructed groups changes which backgrounds are present, "
            "so these intervals mix sampling noise with background composition. They "
            "describe spread, not a test."
        ),
    }


def validation_interval_feasibility(
    rows: list[Row],
    validation_predictions: np.ndarray,
    test_predictions: np.ndarray,
    test_targets: np.ndarray,
    validation_groups: list[str],
) -> dict:
    """Report what a validation-calibrated interval can and cannot establish here.

    A width is calibrated on the 116 unused validation rows to hit nominal 90% coverage,
    then applied to test. Observed test coverage is reported with a binomial interval.
    This is deliberately NOT presented as a calibration guarantee: the validation rows
    are one held-out set, the archive publishes no background labels, and a single
    coverage number cannot demonstrate coverage under background shift.
    """
    validation = [r for r in rows if r.split == "validation"]
    validation_targets = np.asarray([r.target for r in validation], dtype=float)
    residuals = np.abs(validation_targets - validation_predictions)
    # Conformal-style width: the 90th percentile of validation absolute residuals.
    width = float(np.quantile(residuals, 0.90, method="higher"))

    covered = np.abs(test_targets - test_predictions) <= width
    n, k = len(test_targets), int(covered.sum())
    coverage = k / n
    # Wilson interval, which behaves sensibly near the boundaries.
    z = 1.959963984540054
    centre = (k + z * z / 2) / (n + z * z)
    spread = z * np.sqrt(coverage * (1 - coverage) / n + z * z / (4 * n * n)) / (1 + z * z / n)

    group_sizes = {g: validation_groups.count(g) for g in set(validation_groups)}
    return {
        "post_hoc_not_predeclared": True,
        "method": "absolute-residual width at the 90th percentile of the 116 unused validation rows",
        "nominal_coverage": 0.90,
        "half_width_nm": width,
        "interval_width_nm": 2 * width,
        "observed_test_coverage": coverage,
        "observed_test_coverage_wilson95": [float(centre - spread), float(centre + spread)],
        "test_n": n,
        "validation_n": len(validation),
        "validation_reconstructed_groups": len(group_sizes),
        "validation_singleton_groups": sum(1 for s in group_sizes.values() if s == 1),
        "calibration_claim": "NONE",
        "why_no_claim": (
            "Calibration under background shift would need several independent held-out "
            "background sets. The archive publishes no background labels and the validation "
            "rows are a single held-out set, so this is one observed coverage number on one "
            "split, not a guarantee. The historical protocol left these validation labels "
            "unused; this check is the only place they are read, and it is reported "
            "separately for that reason."
        ),
    }
