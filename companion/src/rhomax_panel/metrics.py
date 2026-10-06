"""Scoring, including the pinned upstream FLIP2 rank metrics.

Spearman is returned as ``None``, never 0.0, when either vector is constant. A
constant predictor has no rank correlation; writing 0.0 would silently turn an
undefined quantity into a number that looks like a measured result.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score

# Upstream metric definitions: FLIP baselines/aggregate.py L131-135 at revision
# 62cace8735f5610e2743cf06ce0f944b37fffaa6.
UPSTREAM_EVALUATOR = (
    "https://github.com/J-SNACKKB/FLIP/blob/"
    "62cace8735f5610e2743cf06ce0f944b37fffaa6/baselines/aggregate.py#L131-L135"
)

NDCG_POLICY = (
    "Gains are target minus the minimum scored target, including when that minimum is "
    "positive. Linear gain, all items ranked, no cut-off. Ties in the predicted score "
    "are tie-averaged by scikit-learn's default, so a constant predictor gets a "
    "well-defined score that depends only on the label distribution."
)


def paired_vectors(targets, predictions) -> tuple[np.ndarray, np.ndarray]:
    targets, predictions = np.asarray(targets, float), np.asarray(predictions, float)
    if (targets.ndim != 1 or predictions.shape != targets.shape or not len(targets)
            or not np.isfinite(targets).all() or not np.isfinite(predictions).all()):
        raise ValueError("Targets and predictions must be nonempty, finite, equal-length vectors")
    return targets, predictions


def spearman(targets: np.ndarray, predictions: np.ndarray) -> float | None:
    targets, predictions = paired_vectors(targets, predictions)
    if len(targets) < 2 or np.ptp(targets) == 0 or np.ptp(predictions) == 0:
        return None
    return float(spearmanr(targets, predictions).statistic)


def ndcg(targets: np.ndarray, predictions: np.ndarray) -> float:
    """Full-ranking NDCG under the pinned upstream relevance transform."""
    targets, predictions = paired_vectors(targets, predictions)
    relevance = targets - targets.min()
    return float(ndcg_score(relevance[None, :], predictions[None, :]))


def mae(targets: np.ndarray, predictions: np.ndarray) -> float:
    targets, predictions = paired_vectors(targets, predictions)
    return float(np.mean(np.abs(targets - predictions)))


def rmse(targets: np.ndarray, predictions: np.ndarray) -> float:
    targets, predictions = paired_vectors(targets, predictions)
    diff = targets - predictions
    return float(np.sqrt(np.mean(diff**2)))


def score_all(targets: np.ndarray, predictions: np.ndarray) -> dict:
    """Primary errors in nm, plus the two historical rank metrics."""
    return {
        "n": int(len(targets)),
        "mae_nm": mae(targets, predictions),
        "rmse_nm": rmse(targets, predictions),
        "spearman": spearman(targets, predictions),
        "ndcg": ndcg(targets, predictions),
    }
