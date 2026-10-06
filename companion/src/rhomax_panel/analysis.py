"""Exploratory analyses frozen in evidence/frozen-exploratory-protocol.md.

Everything here was specified before any test error was computed. The grouping is a
declared reconstruction, because the released archive publishes no wild-type label:
the split is named ``by_wild_type`` upstream but the grouping itself is not in the file.
"""
from __future__ import annotations

import numpy as np

from .data import Row
from .metrics import mae

# Frozen bin edges on the length-gated normalised Hamming distance to the training set.
BIN_EDGES = (("near", 0.0, 0.05), ("mid", 0.05, 0.25), ("far", 0.25, 1.0))
NO_LENGTH_MATCH = "no_length_match"
MIN_BIN_N = 10

# Frozen shortlist decision parameters.
CAPACITY = 10
BAND = (540.0, 560.0)
BAND_CENTRE = 550.0

# Arrays saved beside the predictions that are not themselves predictions. Kept here so
# every consumer filters on the same list; diagnostics once treated a boolean mask as a
# prediction column and crashed on it.
NON_PREDICTION_KEYS = frozenset({"seq_ids", "targets", "distances", "has_length_match"})

BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20261001
MIN_EFFECT_NM = 2.0


def distance_bin(distance: float, has_length_match: bool | None = None) -> str:
    """Frozen bins: near <= 0.05 < mid <= 0.25 < far < 1.0, and no-length-match stands alone.

    ``has_length_match`` is authoritative when supplied. The frozen protocol used
    distance == 1.0 as the sentinel for "no equal-length training sequence", but that is
    ambiguous: an equal-length neighbour differing at every position also scores 1.0.
    Passing the flag resolves it without changing any bin edge.
    """
    if has_length_match is False:
        return NO_LENGTH_MATCH
    if has_length_match is None and distance >= 1.0:
        return NO_LENGTH_MATCH
    if distance <= 0.05:
        return "near"
    if distance <= 0.25:
        return "mid"
    return "far"


def reconstruct_groups(rows: list[Row], *, threshold: float = 0.10) -> list[str]:
    """Single-linkage clusters within equal length at <= ``threshold`` Hamming fraction.

    This is a reconstruction of background structure, not the archive's grouping. It is
    named as such everywhere it is reported.
    """
    sequences = [r.sequence for r in rows]
    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_length: dict[int, list[int]] = {}
    for index, sequence in enumerate(sequences):
        by_length.setdefault(len(sequence), []).append(index)
    for length, indices in by_length.items():
        limit = max(1, int(threshold * length))
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = indices[i], indices[j]
                if sum(1 for x, y in zip(sequences[a], sequences[b]) if x != y) <= limit:
                    union(a, b)

    members: dict[int, list[int]] = {}
    for index in range(len(rows)):
        members.setdefault(find(index), []).append(index)
    # Order by descending size then ascending first csv_row, as frozen.
    ordered = sorted(members.values(), key=lambda m: (-len(m), rows[m[0]].csv_row))
    labels = [""] * len(rows)
    for position, member_indices in enumerate(ordered, start=1):
        for index in member_indices:
            labels[index] = f"bg{position:02d}"
    return labels


def per_bin_errors(
    targets: np.ndarray,
    predictions: dict[str, np.ndarray],
    distances: np.ndarray,
    has_length_match: list[bool] | None = None,
) -> list[dict]:
    """MAE per frozen distance bin. Every value here is descriptive.

    No paired interval is computed within a bin, so a between-method gap inside a bin is
    never a supported difference. ``meets_min_bin_size`` reports only the protocol's
    minimum-size gate, below which no claim may be made at all.
    """
    flags = has_length_match if has_length_match is not None else [None] * len(distances)
    bins = np.asarray([distance_bin(d, f) for d, f in zip(distances, flags)])
    out = []
    for name in [b[0] for b in BIN_EDGES] + [NO_LENGTH_MATCH]:
        mask = bins == name
        count = int(mask.sum())
        record = {
            "bin": name,
            "n": count,
            "meets_min_bin_size": count >= MIN_BIN_N,
            "min_bin_size": MIN_BIN_N,
            "evidence_status": "descriptive only; no paired interval was computed within bins",
            "mae_nm": {},
        }
        if count:
            record["target_nm"] = {
                "min": float(targets[mask].min()),
                "max": float(targets[mask].max()),
                "mean": float(targets[mask].mean()),
            }
            for label, values in predictions.items():
                record["mae_nm"][label] = mae(targets[mask], values[mask])
        out.append(record)
    return out


def per_group_errors(targets: np.ndarray, predictions: dict[str, np.ndarray], groups: list[str]) -> list[dict]:
    groups_array = np.asarray(groups)
    out = []
    for name in sorted(set(groups), key=lambda g: (-int((groups_array == g).sum()), g)):
        mask = groups_array == name
        out.append(
            {
                "group": name,
                "n": int(mask.sum()),
                "target_nm_mean": float(targets[mask].mean()),
                "target_nm_min": float(targets[mask].min()),
                "target_nm_max": float(targets[mask].max()),
                "mae_nm": {label: mae(targets[mask], values[mask]) for label, values in predictions.items()},
            }
        )
    return out


def paired_group_bootstrap(
    targets: np.ndarray,
    baseline: np.ndarray,
    candidate: np.ndarray,
    groups: list[str],
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """95% interval for candidate-minus-baseline MAE, resampling whole groups.

    Both predictors score the same resampled rows, so the difference is paired. The
    point estimate is the difference observed on the full test set, not the mean of the
    resampled differences, which carries bootstrap bias.
    """
    groups_array = np.asarray(groups)
    unique = np.unique(groups_array)
    index = {g: np.flatnonzero(groups_array == g) for g in unique}
    sizes = {g: len(v) for g, v in index.items()}
    singletons = sum(1 for g in unique if sizes[g] == 1)

    observed = mae(targets, candidate) - mae(targets, baseline)

    rng = np.random.default_rng(seed)
    deltas = np.empty(draws, dtype=float)
    for draw in range(draws):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        rows = np.concatenate([index[g] for g in drawn])
        deltas[draw] = mae(targets[rows], candidate[rows]) - mae(targets[rows], baseline[rows])

    low, high = (float(x) for x in np.percentile(deltas, [2.5, 97.5]))
    excludes_zero = low > 0 or high < 0
    meets_threshold = abs(observed) >= MIN_EFFECT_NM
    supported = excludes_zero and meets_threshold
    # Three distinct outcomes, kept distinct. Collapsing the middle case into "no
    # difference" would misreport a real but tiny effect as an absence of one.
    if supported:
        interpretation = "supported difference"
    elif excludes_zero:
        interpretation = (
            f"direction resolved but magnitude below the {MIN_EFFECT_NM:g} nm reporting "
            "threshold, so it is too small to act on"
        )
    else:
        interpretation = "no supported difference, which is not evidence of equivalence"
    return {
        "observed_delta_mae_nm": observed,
        "ci95_low": low,
        "ci95_high": high,
        "bootstrap_bias_nm": float(deltas.mean() - observed),
        "fraction_favouring_candidate": float((deltas < 0).mean()),
        "draws": draws,
        "seed": seed,
        "resampling_unit": "reconstructed background group (declared rule, not an archive label)",
        "groups": int(len(unique)),
        "singleton_groups": singletons,
        "largest_group_n": int(max(sizes.values())),
        "supported_difference": bool(supported),
        "interval_excludes_zero": bool(excludes_zero),
        "meets_min_effect": bool(meets_threshold),
        "min_effect_nm": MIN_EFFECT_NM,
        "interpretation": interpretation,
    }


def _shortlist_guard(capacity: int, targets: np.ndarray, predictions: np.ndarray) -> dict | None:
    """Reasons a shortlist cannot be formed. Returns None when it can.

    A shortlist that silently shrinks, or that ranks NaNs, would still produce a number,
    and that number would look like a result. Refuse instead.
    """
    if int(capacity) < 1:
        return {"reason": f"capacity must be at least 1, got {capacity}"}
    if len(targets) == 0:
        return {"reason": "no rows to select from"}
    if capacity > len(targets):
        return {"reason": f"capacity {capacity} exceeds the {len(targets)} rows available"}
    if not np.isfinite(predictions).all():
        return {"reason": "predictions contain non-finite values, so no ranking is defined"}
    if np.ptp(predictions) == 0:
        return {"reason": "constant predictor: every row ties, so no shortlist is defined"}
    return None


def shortlist_band(
    rows: list[Row],
    targets: np.ndarray,
    predictions: np.ndarray,
    *,
    capacity: int = CAPACITY,
    band: tuple[float, float] = BAND,
    centre: float = BAND_CENTRE,
) -> dict:
    """Decision A: pick the ``capacity`` candidates predicted closest to ``centre``.

    Precision is divided by the realised shortlist length, never by a requested capacity
    that could not be filled, which would silently depress the score.
    """
    problem = _shortlist_guard(capacity, targets, predictions)
    if problem:
        return {"decision": "A_desired_band", "defined": False, **problem}
    order = np.argsort(np.abs(predictions - centre), kind="stable")[:capacity]
    realised = int(len(order))
    chosen = targets[order]
    inside = int(((chosen >= band[0]) & (chosen <= band[1])).sum())
    return {
        "decision": "A_desired_band",
        "defined": True,
        "capacity": capacity,
        "realised_capacity": realised,
        "band_nm": list(band),
        "centre_nm": centre,
        "in_band_count": inside,
        "precision_at_capacity": inside / realised,
        "mean_abs_deviation_from_centre_nm": float(np.mean(np.abs(chosen - centre))),
        "selected": [
            {"seq_id": rows[i].seq_id, "csv_row": rows[i].csv_row,
             "predicted_nm": float(predictions[i]), "measured_nm": float(targets[i])}
            for i in order
        ],
    }


def shortlist_redshift(
    rows: list[Row], targets: np.ndarray, predictions: np.ndarray, *, capacity: int = CAPACITY
) -> dict:
    """Decision B: pick the ``capacity`` most red-shifted predictions."""
    problem = _shortlist_guard(capacity, targets, predictions)
    if problem:
        return {"decision": "B_maximise_red_shift", "defined": False, **problem}
    order = np.argsort(-predictions, kind="stable")[:capacity]
    chosen = targets[order]
    return {
        "decision": "B_maximise_red_shift",
        "defined": True,
        "capacity": capacity,
        "realised_capacity": int(len(order)),
        "mean_measured_nm": float(chosen.mean()),
        "max_measured_nm": float(chosen.max()),
        "selected": [
            {"seq_id": rows[i].seq_id, "csv_row": rows[i].csv_row,
             "predicted_nm": float(predictions[i]), "measured_nm": float(targets[i])}
            for i in order
        ],
    }


def random_selection_reference(targets: np.ndarray, *, capacity: int = CAPACITY, band: tuple[float, float] = BAND, centre: float = BAND_CENTRE) -> dict:
    """Analytic expectation for a uniform random shortlist of ``capacity`` rows.

    No seeded draw is used, so no seed choice can flatter or penalise the reference.
    """
    inside = (targets >= band[0]) & (targets <= band[1])
    return {
        "reference": "uniform random selection, analytic expectation",
        "capacity": capacity,
        "expected_precision_at_capacity": float(inside.mean()),
        "expected_mean_abs_deviation_from_centre_nm": float(np.mean(np.abs(targets - centre))),
        "expected_mean_measured_nm": float(targets.mean()),
        "band_prevalence_count": int(inside.sum()),
        "population_n": int(len(targets)),
    }
