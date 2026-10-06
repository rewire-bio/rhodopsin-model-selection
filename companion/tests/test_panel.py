"""Tests for the failure modes that would silently corrupt a result.

These are not smoke tests. Each one targets a way the panel could produce a
plausible-looking wavelength number that is wrong: a substituted data file, a leaked
label, a reordered prediction vector, a cropped sequence, a constant predictor scored
as if it had a rank correlation, or a historical configuration quietly replaced.

Tests that need the real archive or the real weights are skipped when the cache is
absent, and say so, rather than silently passing on synthetic data.
"""
from __future__ import annotations

import gzip
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from rhomax_panel import analysis, data, features, metrics, models
from rhomax_panel.cli import ARCHIVED_METRICS, HISTORICAL

def _find_cache() -> Path:
    """Locate the data cache without assuming where this checkout sits.

    Checked in order: RHOMAX_CACHE, ./cache beside the package, and the workspace
    layout used while the article was written. Without this the real-data tests skip
    silently in a relocated checkout, which is exactly where you most want them to run.
    """
    if env := os.environ.get("RHOMAX_CACHE"):
        return Path(env).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    for candidate in (root / "cache", root.parent / "runs" / "cache", Path.cwd() / "cache"):
        if (candidate / "by_wild_type.csv.gz").exists():
            return candidate
    return root / "cache"


CACHE = _find_cache()
ARCHIVE = CACHE / "by_wild_type.csv.gz"
needs_archive = pytest.mark.skipif(
    not ARCHIVE.exists(),
    reason=f"pinned archive not found (looked in {CACHE}); set RHOMAX_CACHE to run these",
)


# --------------------------------------------------------------------------- data


def _synthetic_csv(tmp_path: Path, rows: list[tuple[str, float, str, str]]) -> Path:
    body = "sequence,target,set,validation\n" + "".join(
        f"{s},{t},{st},{v}\n" for s, t, st, v in rows
    )
    path = tmp_path / "fake.csv.gz"
    path.write_bytes(gzip.compress(body.encode()))
    return path


def test_substituted_data_file_is_refused(tmp_path):
    """A different split must not be scored as if it were the pinned one."""
    path = _synthetic_csv(tmp_path, [("ACDE", 500.0, "train", "False")])
    with pytest.raises(ValueError, match="pinned v3 hash"):
        data.parse(path)


def test_substituted_file_can_be_inspected_but_is_marked(tmp_path):
    path = _synthetic_csv(tmp_path, [("ACDE", 500.0, "train", "False")])
    receipt = data.verify(path, allow_unverified=True)
    assert receipt["csv_sha256_matches_pin"] is False
    assert receipt["gz_origin"] == "unrecognised"


def test_wrong_split_counts_are_refused(tmp_path):
    """Right columns, right alphabet, wrong cohort: still refused."""
    rows = [("ACDE", 500.0, "train", "False"), ("ACDF", 510.0, "test", "False")]
    path = _synthetic_csv(tmp_path, rows)
    with pytest.raises(ValueError, match="Split counts"):
        data.parse(path, allow_unverified=True)


def test_test_row_cannot_also_be_validation(tmp_path):
    path = _synthetic_csv(tmp_path, [("ACDE", 500.0, "test", "True")])
    with pytest.raises(ValueError, match="both test and validation"):
        data.parse(path, allow_unverified=True)


def test_non_standard_residue_is_refused(tmp_path):
    path = _synthetic_csv(tmp_path, [("ACDEX", 500.0, "train", "False")])
    with pytest.raises(ValueError, match="outside the 20-letter alphabet"):
        data.parse(path, allow_unverified=True)


def test_seq_id_is_stable_and_case_insensitive():
    assert data.seq_id("ACDE") == data.seq_id(" acde ")
    assert data.seq_id("ACDE") != data.seq_id("ACDF")


# ----------------------------------------------------------------------- features


def test_composition_22_shape_and_normalisation():
    matrix = features.composition_22(["ACDE", "AAAA"])
    assert matrix.shape == (2, 22)
    # Columns 1..20 are residue fractions and must sum to 1 on a 20-letter sequence.
    assert np.allclose(matrix[:, 1:21].sum(axis=1), 1.0)
    # The unknown-character column is identically zero on this alphabet.
    assert np.allclose(matrix[:, 21], 0.0)
    assert math.isclose(matrix[0, 0], math.log1p(4))


def test_composition_40_second_component_is_zero_without_a_colon():
    matrix = features.composition_40(["ACDE"])
    assert matrix.shape == (1, 40)
    assert np.allclose(matrix[0, 20:], 0.0)
    assert np.allclose(matrix[0, :20].sum(), 1.0)


def test_the_two_composition_variants_differ_only_as_documented():
    """They are catalogued as distinct configurations; the difference is the length term.

    If this ever stops holding, the two historical configurations are no longer the ones
    that were archived.
    """
    sequences = ["ACDEACDE", "AAAACCCC", "WYWYWYWY"]
    a = features.composition_22(sequences)
    b = features.composition_40(sequences)
    assert np.allclose(a[:, 1:21], b[:, :20])
    assert not np.allclose(a[:, 0], 0.0)  # log1p(length) is the extra information


def test_checkpoint_hash_mismatch_is_refused(tmp_path):
    fake = tmp_path / "weights.pt"
    fake.write_bytes(b"not the real weights")
    with pytest.raises(ValueError, match="pinned"):
        features.verify_checkpoint(fake, "esm2_t6_8M_UR50D")


def test_unknown_checkpoint_identity_is_refused(tmp_path):
    fake = tmp_path / "weights.pt"
    fake.write_bytes(b"x")
    with pytest.raises(ValueError, match="Unsupported checkpoint identity"):
        features.verify_checkpoint(fake, "esm2_t33_650M_UR50D")


# ------------------------------------------------------------------------- models


def _toy_rows() -> list[data.Row]:
    rows = []
    sequences = ["AAAA", "AAAC", "AACC", "ACCC", "CCCC", "CCCD", "CCDD", "CDDD"]
    splits = ["train"] * 4 + ["validation"] * 2 + ["test"] * 2
    for i, (sequence, split) in enumerate(zip(sequences, splits)):
        rows.append(data.Row(i, data.seq_id(sequence), sequence, 500.0 + 10 * i, split))
    return rows


def test_ridge_probe_never_reads_validation_or_test_labels():
    """Corrupting held-out labels must not move a single prediction.

    This is the leakage test. If a future edit lets validation or test targets reach
    the fit, these predictions will change and this test fails.
    """
    rows = _toy_rows()
    matrix = features.composition_22([r.sequence for r in rows])
    before = models.ridge_probe(matrix, rows)

    poisoned = [
        data.Row(r.csv_row, r.seq_id, r.sequence, r.target + 1000.0, r.split)
        if r.split != "train"
        else r
        for r in rows
    ]
    after = models.ridge_probe(matrix, poisoned)
    assert np.allclose(before, after)


def test_training_mean_is_the_training_mean_only():
    rows = _toy_rows()
    expected = float(np.mean([r.target for r in rows if r.split == "train"]))
    values = models.training_mean(rows)
    assert np.allclose(values, expected)
    assert len(values) == sum(r.split == "test" for r in rows)


def test_nearest_training_sequence_falls_back_when_no_length_matches():
    rows = [
        data.Row(0, "a", "AAAA", 500.0, "train"),
        data.Row(1, "b", "AAAC", 520.0, "train"),
        data.Row(2, "c", "AAACC", 600.0, "test"),  # length 5: no training match
        data.Row(3, "d", "AAAA", 999.0, "test"),  # exact match to row 0
    ]
    predictions, distances, neighbours = models.nearest_training_sequence(rows)
    assert distances[0] == 1.0 and neighbours[0] is None
    assert predictions[0] == pytest.approx(510.0)  # the training mean
    assert distances[1] == 0.0 and neighbours[1] == "a"
    assert predictions[1] == pytest.approx(500.0)


def test_normalised_distance_is_one_when_lengths_differ():
    assert models.normalised_distance("AAAA", "AAAAA") == 1.0
    assert models.normalised_distance("AAAA", "AAAA") == 0.0
    assert models.normalised_distance("AAAA", "AAAC") == pytest.approx(0.25)


def test_ridge_settings_are_the_archived_ones():
    """Guards against a tuned variant quietly replacing a historical configuration."""
    assert models.RIDGE["alpha"] == 10.0
    assert models.RIDGE["fit_intercept"] is True
    assert models.RIDGE["feature_scaling"] == "none"
    assert models.RIDGE["refit"] == "train only"
    assert models.RIDGE["validation_use"] == "none; fixed hyperparameters"


# ------------------------------------------------------------------------ metrics


def test_spearman_is_none_not_zero_for_a_constant_predictor():
    targets = np.asarray([500.0, 510.0, 520.0])
    assert metrics.spearman(targets, np.full(3, 7.0)) is None
    assert metrics.spearman(np.full(3, 500.0), targets) is None


def test_score_all_reports_undefined_spearman_without_inventing_a_number():
    targets = np.asarray([500.0, 510.0, 520.0])
    scores = metrics.score_all(targets, np.full(3, 505.0))
    assert scores["spearman"] is None
    assert scores["mae_nm"] > 0
    assert 0.0 <= scores["ndcg"] <= 1.0


def test_ndcg_uses_the_min_shifted_relevance_transform():
    """Upstream shifts targets by their minimum even when the minimum is positive."""
    targets = np.asarray([500.0, 510.0, 520.0])
    perfect = metrics.ndcg(targets, targets)
    assert perfect == pytest.approx(1.0)
    # The lowest-wavelength item gets zero gain under the shift, so ranking it first
    # cannot be rescued by its absolute value being large.
    inverted = metrics.ndcg(targets, -targets)
    assert inverted < perfect


def test_ndcg_ties_are_averaged_so_a_constant_predictor_is_order_invariant():
    targets = np.asarray([500.0, 510.0, 520.0, 530.0])
    constant = np.full(4, 1.0)
    first = metrics.ndcg(targets, constant)
    order = np.asarray([2, 0, 3, 1])
    second = metrics.ndcg(targets[order], constant)
    assert first == pytest.approx(second)


def test_mae_and_rmse_are_in_the_target_units():
    targets = np.asarray([500.0, 520.0])
    predictions = np.asarray([510.0, 510.0])
    assert metrics.mae(targets, predictions) == pytest.approx(10.0)
    assert metrics.rmse(targets, predictions) == pytest.approx(10.0)


# ----------------------------------------------------------------------- analysis


def test_distance_bins_use_the_frozen_edges():
    assert analysis.distance_bin(0.0) == "near"
    assert analysis.distance_bin(0.05) == "near"
    assert analysis.distance_bin(0.0500001) == "mid"
    assert analysis.distance_bin(0.25) == "mid"
    assert analysis.distance_bin(0.26) == "far"
    assert analysis.distance_bin(0.999) == "far"
    assert analysis.distance_bin(1.0) == analysis.NO_LENGTH_MATCH


def test_distance_bin_flag_overrides_the_sentinel():
    """An equal-length neighbour differing everywhere scores 1.0 but is still a neighbour."""
    assert analysis.distance_bin(1.0) == analysis.NO_LENGTH_MATCH
    assert analysis.distance_bin(1.0, True) == "far"
    assert analysis.distance_bin(0.01, False) == analysis.NO_LENGTH_MATCH


def test_nearest_neighbour_picks_an_equal_length_row_that_differs_everywhere():
    rows = [
        data.Row(0, "a", "AAAA", 500.0, "train"),
        data.Row(1, "b", "CCCC", 600.0, "test"),
    ]
    predictions, distances, neighbours = models.nearest_training_sequence(rows)
    assert neighbours[0] == "a"  # a real neighbour, not a fallback
    assert distances[0] == pytest.approx(1.0)
    assert predictions[0] == pytest.approx(500.0)


def test_shortlist_refuses_capacity_beyond_the_available_rows():
    rows = [data.Row(i, f"s{i}", "A" * (4 + i), 500.0 + i, "test") for i in range(3)]
    targets = np.asarray([500.0, 501.0, 502.0])
    predictions = np.asarray([1.0, 2.0, 3.0])
    out = analysis.shortlist_band(rows, targets, predictions, capacity=10)
    assert out["defined"] is False and "exceeds" in out["reason"]


def test_shortlist_refuses_zero_capacity_and_non_finite_predictions():
    rows = [data.Row(i, f"s{i}", "A" * (4 + i), 500.0 + i, "test") for i in range(3)]
    targets = np.asarray([500.0, 501.0, 502.0])
    assert analysis.shortlist_band(rows, targets, np.asarray([1.0, 2.0, 3.0]), capacity=0)["defined"] is False
    nan = np.asarray([1.0, np.nan, 3.0])
    out = analysis.shortlist_redshift(rows, targets, nan, capacity=2)
    assert out["defined"] is False and "non-finite" in out["reason"]


def test_shortlist_precision_divides_by_the_realised_capacity():
    rows = [data.Row(i, f"s{i}", "A" * (4 + i), 0.0, "test") for i in range(3)]
    targets = np.asarray([550.0, 551.0, 400.0])
    predictions = np.asarray([550.0, 551.0, 400.0])
    out = analysis.shortlist_band(rows, targets, predictions, capacity=3)
    assert out["realised_capacity"] == 3
    assert out["precision_at_capacity"] == pytest.approx(2 / 3)


def test_per_bin_errors_are_marked_descriptive():
    targets = np.asarray([500.0, 510.0, 520.0])
    predictions = {"m": np.asarray([505.0, 505.0, 505.0])}
    bins = analysis.per_bin_errors(targets, predictions, np.asarray([0.0, 0.5, 1.0]))
    assert all("descriptive" in b["evidence_status"] for b in bins)
    assert all("sufficient_for_difference_claim" not in b for b in bins)


def test_shortlist_is_undefined_for_a_constant_predictor():
    rows = _toy_rows()[:2]
    targets = np.asarray([550.0, 600.0])
    constant = np.full(2, 539.0)
    band = analysis.shortlist_band(rows, targets, constant, capacity=2)
    redshift = analysis.shortlist_redshift(rows, targets, constant, capacity=2)
    assert band["defined"] is False and redshift["defined"] is False


def test_shortlist_band_and_redshift_can_disagree():
    """The two decisions are genuinely different and the code must not conflate them."""
    rows = [
        data.Row(i, f"s{i}", "A" * (4 + i), t, "test")
        for i, t in enumerate([550.0, 600.0, 450.0])
    ]
    targets = np.asarray([550.0, 600.0, 450.0])
    predictions = np.asarray([551.0, 599.0, 449.0])
    band = analysis.shortlist_band(rows, targets, predictions, capacity=1)
    redshift = analysis.shortlist_redshift(rows, targets, predictions, capacity=1)
    assert band["selected"][0]["measured_nm"] == 550.0
    assert redshift["selected"][0]["measured_nm"] == 600.0


def test_paired_bootstrap_separates_the_three_outcomes():
    rng = np.random.default_rng(0)
    targets = rng.normal(540, 30, 120)
    groups = [f"bg{i // 4:02d}" for i in range(120)]
    identical = analysis.paired_group_bootstrap(targets, targets + 5.0, targets + 5.0, groups, draws=300)
    assert identical["observed_delta_mae_nm"] == pytest.approx(0.0)
    assert identical["supported_difference"] is False
    assert "not evidence of equivalence" in identical["interpretation"]

    worse = analysis.paired_group_bootstrap(targets, targets, targets + 40.0, groups, draws=300)
    assert worse["observed_delta_mae_nm"] > 2.0
    assert worse["supported_difference"] is True


def test_reconstructed_groups_are_named_by_descending_size():
    # Three length-4 near neighbours cluster; the length-5 and length-6 rows stand alone.
    rows = [
        data.Row(i, f"s{i}", s, 500.0, "test")
        for i, s in enumerate(["AAAA", "AAAC", "AAAD", "CCCCC", "WWWWWW"])
    ]
    labels = analysis.reconstruct_groups(rows)
    assert labels[0] == labels[1] == labels[2] == "bg01"
    assert len({labels[3], labels[4]}) == 2


# --------------------------------------------------------------------- user FASTA


def test_fasta_rejects_ambiguity_codes(tmp_path):
    path = tmp_path / "x.fasta"
    path.write_text(">a\nACDEX\n")
    with pytest.raises(ValueError, match="outside the 20-letter alphabet"):
        data.read_fasta(path)


def test_fasta_rejects_sequences_beyond_the_encoder_limit(tmp_path):
    path = tmp_path / "x.fasta"
    path.write_text(">a\n" + "A" * (data.ESM_MAX_LENGTH + 1) + "\n")
    with pytest.raises(ValueError, match="no cropping is applied"):
        data.read_fasta(path)


def test_fasta_rejects_duplicate_headers(tmp_path):
    path = tmp_path / "x.fasta"
    path.write_text(">a\nACDE\n>a\nACDF\n")
    with pytest.raises(ValueError, match="Duplicate FASTA header"):
        data.read_fasta(path)


def test_fasta_rejects_content_before_a_header(tmp_path):
    path = tmp_path / "x.fasta"
    path.write_text("ACDE\n>a\nACDF\n")
    with pytest.raises(ValueError, match="before the first"):
        data.read_fasta(path)


def test_fasta_joins_wrapped_lines(tmp_path):
    path = tmp_path / "x.fasta"
    path.write_text(">a\nACDE\nFGHI\n")
    assert data.read_fasta(path) == [("a", "ACDEFGHI")]


def test_fasta_skips_legacy_semicolon_comments(tmp_path):
    """Pearson-format ';' comments are comments, not residues."""
    path = tmp_path / "x.fasta"
    path.write_text("; provenance note\n>a\nACDE\n; another note\nFGHI\n")
    assert data.read_fasta(path) == [("a", "ACDEFGHI")]


# ------------------------------------------------------- real-data integration


@needs_archive
def test_real_archive_matches_the_pinned_identity_and_counts():
    rows, receipt = data.parse(ARCHIVE)
    assert receipt["csv_sha256"] == data.CSV_SHA256
    assert receipt["split_counts"] == {"train": 584, "validation": 116, "test": 184}
    assert receipt["target_units"] == "nm"
    assert len(rows) == 884
    assert max(len(r.sequence) for r in rows) == 365
    assert min(len(r.sequence) for r in rows) == 227


@needs_archive
def test_no_exact_sequence_overlap_between_splits():
    rows, _ = data.parse(ARCHIVE)
    sets = {s: {r.sequence for r in rows if r.split == s} for s in ("train", "validation", "test")}
    assert not sets["train"] & sets["test"]
    assert not sets["train"] & sets["validation"]
    assert not sets["validation"] & sets["test"]


@needs_archive
def test_composition_configurations_reproduce_the_archived_metrics():
    """The reproduction claim itself, as a test. No weights needed."""
    rows, _ = data.parse(ARCHIVE)
    test = data.by_split(rows, "test")
    targets = np.asarray([r.target for r in test])
    for label, builder in (
        ("composition-22", features.composition_22),
        ("composition-40", features.composition_40),
    ):
        matrix = builder([r.sequence for r in rows])
        predictions = models.ridge_probe(matrix, rows)
        assert metrics.spearman(targets, predictions) == pytest.approx(
            ARCHIVED_METRICS[label]["spearman"], abs=1e-9
        )
        assert metrics.ndcg(targets, predictions) == pytest.approx(
            ARCHIVED_METRICS[label]["ndcg"], abs=1e-9
        )


@needs_archive
def test_training_mean_reproduces_the_archived_ndcg_and_has_no_spearman():
    rows, _ = data.parse(ARCHIVE)
    targets = np.asarray([r.target for r in data.by_split(rows, "test")])
    predictions = models.training_mean(rows)
    assert metrics.spearman(targets, predictions) is None
    assert metrics.ndcg(targets, predictions) == pytest.approx(
        ARCHIVED_METRICS["training-mean"]["ndcg"], abs=1e-9
    )


@needs_archive
def test_archived_metric_table_covers_every_historical_configuration():
    assert set(ARCHIVED_METRICS) == set(HISTORICAL)
    assert len(HISTORICAL) == 5


RESULTS = Path(os.environ.get("RHOMAX_RESULTS", Path(__file__).resolve().parents[1] / "results"))


@pytest.mark.skipif(not (RESULTS / "panel-receipt.json").exists(), reason="no completed panel run")
def test_completed_run_reports_a_match_for_every_configuration():
    receipt = json.loads((RESULTS / "panel-receipt.json").read_text())
    statuses = {r["configuration"]: r["status"] for r in receipt["reproduction_vs_archive"]}
    assert set(statuses) == set(HISTORICAL)
    assert all(s == "match" for s in statuses.values()), statuses
