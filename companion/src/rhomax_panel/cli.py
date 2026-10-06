"""Command line entry point.

Subcommands:
  verify     hash-check the pinned archive and print its split counts
  panel      run the five historical configurations plus the new control, and score
  analyse    run the frozen exploratory analyses on a completed panel
  predict    score an unlabelled user FASTA, kept separate from benchmark evaluation
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np

from . import analysis, data, features, metrics, models, posthoc

# The five historical configurations, exactly as archived. Reruns must not substitute
# tuned variants; see evidence/frozen-exploratory-protocol.md section 9.
HISTORICAL = ("training-mean", "composition-40", "composition-22", "esm2-8m", "esm2-35m")
NEW_CONTROL = "nearest-train-seq"

LABELS = {
    "training-mean": "Training mean (constant)",
    "composition-40": "Composition, 40 features + fixed ridge",
    "composition-22": "Composition, 22 features + fixed ridge",
    "esm2-8m": "ESM-2 8M frozen residue mean + fixed ridge",
    "esm2-35m": "ESM-2 35M frozen residue mean + fixed ridge",
    NEW_CONTROL: "Nearest training sequence (new control)",
}

ARCHIVED_METRICS = {
    "training-mean": {"spearman": None, "ndcg": 0.9206667522227658},
    "composition-40": {"spearman": 0.41818225155801514, "ndcg": 0.954819941821582},
    "composition-22": {"spearman": 0.41798958279508075, "ndcg": 0.9548154942827918},
    "esm2-8m": {"spearman": -0.1463506755340845, "ndcg": 0.8964799835636942},
    "esm2-35m": {"spearman": -0.2217595033467806, "ndcg": 0.9072580204736261},
}

ENDPOINT_SCOPE = (
    "Endpoint is peak absorption wavelength in nm only. Nothing here establishes "
    "activation efficiency, expression, photostability, ion transport or cellular function."
)


def peak_rss_mb() -> float:
    # macOS reports ru_maxrss in bytes, Linux in kilobytes.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1 << 20) if sys.platform == "darwin" else value / 1024


def environment() -> dict:
    import sklearn
    import scipy

    record = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
    }
    try:
        import torch

        record["torch"] = torch.__version__
    except ImportError:
        record["torch"] = "not installed"
    return record


def _cache(args) -> Path:
    return Path(args.cache).expanduser().resolve()


def cmd_verify(args) -> int:
    rows, receipt = data.load(_cache(args), allow_unverified=args.allow_unverified)
    print(json.dumps({"source": receipt, "endpoint_scope": ENDPOINT_SCOPE}, indent=2))
    return 0


def _embedding_matrix(rows, name, args, cache: Path, receipts: dict) -> np.ndarray:
    key = features.embedding_cache_key(name, data.CSV_SHA256)
    path = cache / f"embeddings-{name}-{key}.npz"
    if path.exists() and not args.refresh_embeddings:
        stored = np.load(path, allow_pickle=False)
        if list(stored["seq_ids"]) != [r.seq_id for r in rows]:
            raise ValueError(f"Cached embeddings in {path} do not match the loaded rows")
        receipts[name] = {
            "source": "cache",
            "path": path.name,
            "cache_bytes": path.stat().st_size,
            "note": "reused cached embeddings; timings are not a fresh measurement",
        }
        return stored["vectors"]

    checkpoint = cache / f"{name}.pt"
    if not checkpoint.exists():
        raise FileNotFoundError(
            f"{checkpoint} is missing. Download it from "
            f"{features.CHECKPOINTS[name]['url']} into {cache}."
        )
    vectors, receipt = features.esm2_embeddings(
        rows, checkpoint, name, device=args.device, batch_size=args.batch_size, threads=args.threads
    )
    np.savez(path, vectors=vectors, seq_ids=np.asarray([r.seq_id for r in rows]))
    receipt |= {"source": "fresh run", "path": path.name, "cache_bytes": path.stat().st_size}
    receipts[name] = receipt
    return vectors


def cmd_panel(args) -> int:
    cache = _cache(args)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    rows, source_receipt = data.load(cache, allow_unverified=args.allow_unverified)
    test = data.by_split(rows, "test")
    targets = np.asarray([r.target for r in test], dtype=float)

    predictions: dict[str, np.ndarray] = {}
    # Validation predictions are produced but NOT used to choose anything. They exist
    # only so the post-hoc interval feasibility check can read them, which is reported
    # separately. The historical protocol left these labels unused and still does.
    validation: dict[str, np.ndarray] = {}
    timings: dict[str, dict] = {}
    embedding_receipts: dict[str, dict] = {}

    fit_start = time.perf_counter()
    predictions["training-mean"] = models.training_mean(rows)
    validation["training-mean"] = models.training_mean(rows, target_split="validation")
    timings["training-mean"] = {"fit_predict_seconds": time.perf_counter() - fit_start}

    for label, builder in (("composition-40", features.composition_40), ("composition-22", features.composition_22)):
        feature_start = time.perf_counter()
        matrix = builder([r.sequence for r in rows])
        featured = time.perf_counter()
        predictions[label] = models.ridge_probe(matrix, rows)
        validation[label] = models.ridge_probe(matrix, rows, target_split="validation")
        timings[label] = {
            "feature_seconds": featured - feature_start,
            "fit_predict_seconds": time.perf_counter() - featured,
            "feature_dimension": int(matrix.shape[1]),
            "constant_zero_columns": int((matrix.std(axis=0) == 0).sum()),
        }

    for label, name in (("esm2-8m", "esm2_t6_8M_UR50D"), ("esm2-35m", "esm2_t12_35M_UR50D")):
        if args.skip_esm:
            continue
        matrix = _embedding_matrix(rows, name, args, cache, embedding_receipts)
        fit_start = time.perf_counter()
        predictions[label] = models.ridge_probe(matrix, rows)
        validation[label] = models.ridge_probe(matrix, rows, target_split="validation")
        timings[label] = {
            "fit_predict_seconds": time.perf_counter() - fit_start,
            "feature_dimension": int(matrix.shape[1]),
            "embedding": embedding_receipts[name],
        }

    control_start = time.perf_counter()
    nn_predictions, nn_distances, nn_neighbours = models.nearest_training_sequence(rows)
    predictions[NEW_CONTROL] = nn_predictions
    validation[NEW_CONTROL] = models.nearest_training_sequence(rows, target_split="validation")[0]
    timings[NEW_CONTROL] = {"fit_predict_seconds": time.perf_counter() - control_start}

    scores = {label: metrics.score_all(targets, values) for label, values in predictions.items()}

    # Reproduction check against the archived historical metrics.
    reproduction = []
    for label in HISTORICAL:
        if label not in scores:
            reproduction.append({"configuration": label, "status": "not run"})
            continue
        archived, got = ARCHIVED_METRICS[label], scores[label]
        checks = {}
        for metric in ("spearman", "ndcg"):
            expected, actual = archived[metric], got[metric]
            if expected is None or actual is None:
                checks[metric] = {
                    "archived": expected,
                    "recomputed": actual,
                    "agrees": expected is None and actual is None,
                }
            else:
                checks[metric] = {
                    "archived": expected,
                    "recomputed": actual,
                    "absolute_difference": abs(actual - expected),
                    "agrees": abs(actual - expected) <= args.tolerance,
                }
        reproduction.append(
            {
                "configuration": label,
                "checks": checks,
                "status": "match" if all(c["agrees"] for c in checks.values()) else "DIFFERS",
            }
        )

    receipt = {
        "run_kind": "independent reimplementation of the archived protocol",
        "reproduces_published_model_score": False,
        "endpoint_scope": ENDPOINT_SCOPE,
        "source": source_receipt,
        "ridge": models.RIDGE,
        "ndcg_policy": metrics.NDCG_POLICY,
        "upstream_evaluator": metrics.UPSTREAM_EVALUATOR,
        "environment": environment(),
        "timings_seconds": timings,
        "total_wall_seconds": time.perf_counter() - started,
        "peak_rss_mb": peak_rss_mb(),
        "tolerance": args.tolerance,
        "reproduction_vs_archive": reproduction,
        "scores": scores,
        "nearest_neighbour_fallbacks": int(sum(1 for n in nn_neighbours if n is None)),
    }
    (output / "panel-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    export = [
        {
            "seq_id": row.seq_id,
            "csv_row": row.csv_row,
            "split": row.split,
            "length": len(row.sequence),
            "measured_nm": row.target,
            "nearest_train_distance": float(nn_distances[index]),
            "nearest_train_seq_id": nn_neighbours[index],
            **{f"pred_{label}_nm": float(values[index]) for label, values in predictions.items()},
        }
        for index, row in enumerate(test)
    ]
    (output / "test-predictions.json").write_text(json.dumps(export, indent=2) + "\n")
    np.savez(
        output / "test-predictions.npz",
        seq_ids=np.asarray([r.seq_id for r in test]),
        targets=targets,
        distances=nn_distances,
        has_length_match=np.asarray([n is not None for n in nn_neighbours]),
        **{label: values for label, values in predictions.items()},
    )
    np.savez(
        output / "validation-predictions.npz",
        seq_ids=np.asarray([r.seq_id for r in data.by_split(rows, "validation")]),
        **{label: values for label, values in validation.items()},
    )

    print(f"Wrote {output / 'panel-receipt.json'} and {output / 'test-predictions.json'}")
    for label in list(HISTORICAL) + [NEW_CONTROL]:
        if label not in scores:
            continue
        s = scores[label]
        rho = "undefined" if s["spearman"] is None else f"{s['spearman']:+.4f}"
        print(f"  {LABELS[label]:<48} MAE {s['mae_nm']:7.2f} nm  rho {rho:>9}  NDCG {s['ndcg']:.4f}")
    failures = [r for r in reproduction if r["status"] == "DIFFERS"]
    if failures:
        print(f"\nReproduction DIFFERS for: {', '.join(r['configuration'] for r in failures)}")
        return 1
    return 0


def cmd_analyse(args) -> int:
    cache = _cache(args)
    output = Path(args.output).resolve()
    stored = np.load(output / "test-predictions.npz", allow_pickle=False)
    rows, _ = data.load(cache, allow_unverified=args.allow_unverified)
    test = data.by_split(rows, "test")
    if list(stored["seq_ids"]) != [r.seq_id for r in test]:
        raise ValueError("Stored predictions do not match the loaded test rows")

    targets = stored["targets"]
    distances = stored["distances"]
    # Older result files predate this flag; fall back to the distance sentinel for them.
    length_match = (
        [bool(x) for x in stored["has_length_match"]]
        if "has_length_match" in stored.files
        else None
    )
    predictions = {
        key: stored[key]
        for key in stored.files
        if key not in analysis.NON_PREDICTION_KEYS
    }
    groups = analysis.reconstruct_groups(test)

    sizes = {g: groups.count(g) for g in set(groups)}
    report = {
        "experiment": "rhomax-background-distance-exploratory-2026-10-01",
        "status": "exploratory, not preregistered, not confirmatory",
        "endpoint_scope": ENDPOINT_SCOPE,
        "grouping": {
            "rule": "equal sequence length and single-linkage Hamming distance <= 10% of length",
            "provenance": "DECLARED RECONSTRUCTION. The archive publishes no wild-type label.",
            "groups": len(sizes),
            "singletons": sum(1 for s in sizes.values() if s == 1),
            "largest": max(sizes.values()),
            "rows_in_groups_of_at_least_10": sum(s for s in sizes.values() if s >= 10),
        },
        "unsupported_gates": [
            {
                "gate": "repeated held-out-background cross-validation",
                "status": "not attempted",
                "reason": "the archive publishes no wild-type labels, so held-out backgrounds "
                          "cannot be defined from the released data without inventing them",
            },
            {
                "gate": "calibrated prediction intervals under background shift",
                "status": "not claimed",
                "reason": "the 116 validation rows are a single held-out set with no independent "
                          "background replication, so coverage under shift cannot be established",
            },
            {
                "gate": "aligned one-hot ridge",
                "status": "not attempted",
                "reason": "no reproducible alignment and insertion policy was fixed; lengths "
                          "differ by up to 138 residues across backgrounds",
            },
        ],
        "distance_bins": analysis.per_bin_errors(
            targets, predictions, distances, length_match
        ),
        "per_group": analysis.per_group_errors(targets, predictions, groups),
        "shortlists": {
            label: {
                "band": analysis.shortlist_band(test, targets, values),
                "redshift": analysis.shortlist_redshift(test, targets, values),
            }
            for label, values in predictions.items()
        },
        "random_reference": analysis.random_selection_reference(targets),
    }

    baseline = args.baseline
    if baseline not in predictions:
        raise ValueError(f"Baseline {baseline} not present in {sorted(predictions)}")
    report["paired_bootstrap_vs_" + baseline] = {
        label: analysis.paired_group_bootstrap(targets, predictions[baseline], values, groups)
        for label, values in predictions.items()
        if label != baseline
    }

    # Everything below was added after the frozen results were seen and is labelled so.
    report["post_hoc"] = {
        "status": "added after seeing the frozen analyses; not predeclared, not confirmatory",
        "shortlist_spread": {
            label: posthoc.shortlist_bootstrap(targets, values, groups)
            for label, values in predictions.items()
        },
    }
    validation_path = output / "validation-predictions.npz"
    if validation_path.exists():
        stored_validation = np.load(validation_path, allow_pickle=False)
        validation_rows = data.by_split(rows, "validation")
        if list(stored_validation["seq_ids"]) != [r.seq_id for r in validation_rows]:
            raise ValueError("Stored validation predictions do not match the loaded validation rows")
        validation_groups = analysis.reconstruct_groups(validation_rows)
        report["post_hoc"]["validation_interval_feasibility"] = {
            label: posthoc.validation_interval_feasibility(
                rows, stored_validation[label], predictions[label], targets, validation_groups
            )
            for label in predictions
            if label in stored_validation.files
        }
    else:
        report["post_hoc"]["validation_interval_feasibility"] = {
            "status": "skipped",
            "reason": f"{validation_path.name} not present; rerun the panel to produce it",
        }

    path = output / "exploratory-analysis.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {path}")
    print(
        f"  reconstructed groups: {report['grouping']['groups']} "
        f"({report['grouping']['singletons']} singletons, largest {report['grouping']['largest']})"
    )
    for label, record in report["paired_bootstrap_vs_" + baseline].items():
        print(
            f"  {label:<20} vs {baseline}: dMAE {record['observed_delta_mae_nm']:+7.2f} nm "
            f"[{record['ci95_low']:+.2f}, {record['ci95_high']:+.2f}] -> {record['interpretation']}"
        )
    return 0


def cmd_predict(args) -> int:
    """Score an unlabelled FASTA. This is inference, not held-out evaluation."""
    cache = _cache(args)
    entries = data.read_fasta(Path(args.fasta))
    rows, source_receipt = data.load(cache, allow_unverified=args.allow_unverified)

    synthetic = [
        data.Row(-(i + 1), data.seq_id(sequence), sequence, float("nan"), "user")
        for i, (_, sequence) in enumerate(entries)
    ]
    combined = rows + synthetic

    if args.configuration == "composition-22":
        matrix = features.composition_22([r.sequence for r in combined])
    elif args.configuration == "composition-40":
        matrix = features.composition_40([r.sequence for r in combined])
    else:
        name = {"esm2-8m": "esm2_t6_8M_UR50D", "esm2-35m": "esm2_t12_35M_UR50D"}[args.configuration]
        checkpoint = cache / f"{name}.pt"
        if not checkpoint.exists():
            raise FileNotFoundError(f"{checkpoint} is missing; see {features.CHECKPOINTS[name]['url']}")
        matrix, _ = features.esm2_embeddings(
            combined, checkpoint, name, device=args.device, batch_size=args.batch_size, threads=args.threads
        )

    values = models.ridge_probe(matrix, combined, target_split="user")
    train_targets = np.asarray([r.target for r in rows if r.split == "train"], dtype=float)
    nn_predictions, nn_distances, nn_neighbours = models.nearest_training_sequence(
        combined, target_split="user"
    )

    out = {
        "mode": "unlabelled inference on user sequences, NOT held-out benchmark evaluation",
        "configuration": args.configuration,
        "endpoint_scope": ENDPOINT_SCOPE,
        "source": source_receipt,
        "training_population": {
            "n": int(len(train_targets)),
            "measured_nm_min": float(train_targets.min()),
            "measured_nm_max": float(train_targets.max()),
            "measured_nm_mean": float(train_targets.mean()),
        },
        "caveat": (
            "A prediction outside the training wavelength range is an extrapolation by a "
            "linear head and carries no measured error estimate. Distance to the nearest "
            "training sequence is reported so that can be judged; distance 1.0 means no "
            "training sequence of the same length, the regime in which this panel was "
            "least accurate."
        ),
        "records": [
            {
                "name": name,
                "seq_id": data.seq_id(sequence),
                "length": len(sequence),
                "predicted_nm": float(values[i]),
                "outside_training_range": not (
                    train_targets.min() <= values[i] <= train_targets.max()
                ),
                "nearest_train_distance": float(nn_distances[i]),
                "nearest_train_seq_id": nn_neighbours[i],
                "nearest_train_measured_nm": float(nn_predictions[i]),
            }
            for i, (name, sequence) in enumerate(entries)
        ],
    }
    text = json.dumps(out, indent=2) + "\n"
    if args.output_json:
        Path(args.output_json).write_text(text)
    print(text, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rhomax-panel", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", default="./cache", help="directory for the archive, weights and embeddings")
    parser.add_argument("--allow-unverified", action="store_true",
                        help="proceed when the archive hash differs from the pin (not for results)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify", help="hash-check the pinned archive").set_defaults(func=cmd_verify)

    panel = sub.add_parser("panel", help="run the five historical configurations plus the new control")
    panel.add_argument("--output", default="./results")
    panel.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    panel.add_argument("--batch-size", type=int, default=4)
    panel.add_argument("--threads", type=int, default=4)
    panel.add_argument("--tolerance", type=float, default=1e-9)
    panel.add_argument("--skip-esm", action="store_true", help="composition and mean only; no weights needed")
    panel.add_argument("--refresh-embeddings", action="store_true")
    panel.set_defaults(func=cmd_panel)

    analyse = sub.add_parser("analyse", help="run the frozen exploratory analyses")
    analyse.add_argument("--output", default="./results")
    analyse.add_argument("--baseline", default="training-mean")
    analyse.set_defaults(func=cmd_analyse)

    predict = sub.add_parser("predict", help="unlabelled inference on a user FASTA")
    predict.add_argument("fasta")
    predict.add_argument("--configuration", default="composition-22",
                         choices=["composition-22", "composition-40", "esm2-8m", "esm2-35m"])
    predict.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    predict.add_argument("--batch-size", type=int, default=4)
    predict.add_argument("--threads", type=int, default=4)
    predict.add_argument("--output-json")
    predict.set_defaults(func=cmd_predict)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
