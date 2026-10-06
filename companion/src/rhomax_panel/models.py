"""Predictors: the archived fixed ridge probe, the training mean, and a new control.

The ridge settings are the archived ones and are not tunable from the command line.
Making them tunable would make it too easy to quietly replace a historical
configuration with a better one and then compare it against the historical panel.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from .data import Row

# Archived probe settings: alpha 10, no feature scaling, train-only target scaling.
RIDGE = {
    "name": "rewire-frozen-embedding-ridge-v1",
    "alpha": 10.0,
    "solver": "auto",
    "tol": 1e-5,
    "max_iter": 1000000,
    "fit_intercept": True,
    "feature_scaling": "none",
    "target_scaling": "StandardScaler fitted only on train labels",
    "validation_use": "none; fixed hyperparameters",
    "refit": "train only",
}


def ridge_probe(features: np.ndarray, rows: list[Row], target_split: str = "test") -> np.ndarray:
    """Fit alpha-10 ridge on training rows only; predict ``target_split`` in nm.

    Targets are standardised using training labels alone and predictions are mapped
    back to nanometres, so nothing in the output depends on validation or test labels.
    """
    train = np.asarray([r.split == "train" for r in rows])
    wanted = np.asarray([r.split == target_split for r in rows])
    y = np.asarray([r.target for r in rows if r.split == "train"], dtype=float)[:, None]

    scaler = StandardScaler().fit(y)
    head = Ridge(
        alpha=RIDGE["alpha"],
        solver=RIDGE["solver"],
        tol=RIDGE["tol"],
        max_iter=RIDGE["max_iter"],
        fit_intercept=RIDGE["fit_intercept"],
    )
    head.fit(features[train], scaler.transform(y).ravel())
    scaled = head.predict(features[wanted])[:, None]
    return scaler.inverse_transform(scaled).ravel()


def training_mean(rows: list[Row], target_split: str = "test") -> np.ndarray:
    """Constant prediction: the arithmetic mean of the training targets, in nm."""
    train = [r.target for r in rows if r.split == "train"]
    value = float(np.mean(train))
    count = sum(r.split == target_split for r in rows)
    return np.full(count, value, dtype=float)


def normalised_distance(a: str, b: str) -> float:
    """Length-gated normalised Hamming distance; 1.0 when lengths differ.

    Frozen in the exploratory protocol before any error was computed. Unequal lengths
    are assigned the maximum distance rather than aligned, because no reproducible
    alignment and insertion policy was fixed. The cost is that a near-identical
    sequence with a single indel looks maximally distant, which is reported, not hidden.
    """
    if len(a) != len(b):
        return 1.0
    if not a:
        return 0.0
    return sum(1 for x, y in zip(a, b) if x != y) / len(a)


def nearest_training_sequence(rows: list[Row], target_split: str = "test") -> tuple[np.ndarray, np.ndarray, list[str | None]]:
    """Nearest-neighbour control plus the distance used for the frozen bins.

    Returns predictions in nm, the distance to the nearest training sequence, and the
    ``seq_id`` of that neighbour (``None`` when no equal-length training sequence
    exists and the training mean is used instead).

    ``neighbour is None`` is the only signal for "no equal-length training sequence".
    A distance of 1.0 alone is ambiguous: an equal-length neighbour differing at every
    position also has distance 1.0, and is still a real neighbour. In the pinned archive
    the largest equal-length nearest distance is 0.9375 (test) and 0.9491 (validation), so
    this distinction changes no reported number, but user FASTA input can hit it.
    """
    train = [r for r in rows if r.split == "train"]
    wanted = [r for r in rows if r.split == target_split]
    fallback = float(np.mean([r.target for r in train]))

    predictions = np.empty(len(wanted), dtype=float)
    distances = np.empty(len(wanted), dtype=float)
    neighbours: list[str | None] = []

    by_length: dict[int, list[Row]] = {}
    for row in train:
        by_length.setdefault(len(row.sequence), []).append(row)
    # Ties at equal minimum distance resolve to the lowest training csv_row.
    for bucket in by_length.values():
        bucket.sort(key=lambda r: r.csv_row)

    for index, row in enumerate(wanted):
        candidates = by_length.get(len(row.sequence), [])
        # Start above the maximum possible distance so an equal-length candidate is always
        # chosen, even one that differs at every position.
        best, best_distance = None, float("inf")
        for candidate in candidates:
            distance = normalised_distance(row.sequence, candidate.sequence)
            if distance < best_distance:
                best, best_distance = candidate, distance
        distances[index] = best_distance if best is not None else 1.0
        if best is None:
            predictions[index] = fallback
            neighbours.append(None)
        else:
            predictions[index] = best.target
            neighbours.append(best.seq_id)
    return predictions, distances, neighbours
