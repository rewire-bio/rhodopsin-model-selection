"""Validate derived artifacts before they can enter scientific summaries."""
from __future__ import annotations

import numpy as np

from . import analysis, data, models


def finite_vector(value, n: int, name: str) -> np.ndarray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (n,) or not np.isfinite(vector).all():
        raise ValueError(f"{name} must be a finite vector with shape ({n},)")
    return vector


def validate_predictions(stored, rows: list[data.Row], split: str) -> dict[str, np.ndarray]:
    expected = data.by_split(rows, split)
    if "seq_ids" not in stored or not np.array_equal(stored["seq_ids"], [r.seq_id for r in expected]):
        raise ValueError(f"Stored predictions do not match the loaded {split} rows")
    predictions = {
        key: finite_vector(stored[key], len(expected), key)
        for key in stored.files if key not in analysis.NON_PREDICTION_KEYS
    }
    if not predictions:
        raise ValueError(f"No {split} prediction vectors present")
    if split == "test":
        targets = finite_vector(stored["targets"], len(expected), "targets")
        if not np.array_equal(targets, [r.target for r in expected]):
            raise ValueError("Stored targets differ from canonical test labels")
        _, distances, neighbours = models.nearest_training_sequence(rows, target_split=split)
        saved_distances = finite_vector(stored["distances"], len(expected), "distances")
        if not np.array_equal(saved_distances, distances):
            raise ValueError("Stored distances differ from canonical training neighbours")
        if "has_length_match" in stored:
            flags = stored["has_length_match"]
            if flags.dtype != np.dtype(bool) or not np.array_equal(flags, [n is not None for n in neighbours]):
                raise ValueError("Stored has_length_match differs from canonical training neighbours")
    return predictions
