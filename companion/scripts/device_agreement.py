"""Known-answer check: do CPU and MPS agree on the embeddings and the final metrics?

Run this before trusting any accelerator timing. The panel's headline numbers are CPU
numbers; this script exists so that an MPS run is never silently assumed equivalent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from rhomax_panel import data, features, metrics, models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="./cache")
    parser.add_argument("--model", default="esm2_t6_8M_UR50D", choices=sorted(features.CHECKPOINTS))
    parser.add_argument("--limit", type=int, default=40, help="sequences to encode on both devices")
    parser.add_argument("--output")
    args = parser.parse_args()

    import torch

    if not torch.backends.mps.is_available():
        print(json.dumps({"status": "skipped", "reason": "MPS not available on this machine"}, indent=2))
        return 0

    cache = Path(args.cache).expanduser().resolve()
    rows, _ = data.load(cache)
    subset = rows[: args.limit]
    checkpoint = cache / f"{args.model}.pt"

    cpu, cpu_receipt = features.esm2_embeddings(subset, checkpoint, args.model, device="cpu")
    mps, mps_receipt = features.esm2_embeddings(subset, checkpoint, args.model, device="mps")

    difference = np.abs(cpu - mps)
    # Also check what the disagreement does to a downstream wavelength prediction, since
    # that is the quantity anybody actually reads.
    full_cpu, _ = features.esm2_embeddings(rows, checkpoint, args.model, device="cpu")
    predictions_cpu = models.ridge_probe(full_cpu, rows)
    targets = np.asarray([r.target for r in data.by_split(rows, "test")])

    report = {
        "status": "ran",
        "model": args.model,
        "sequences_compared": len(subset),
        "embedding_max_abs_difference": float(difference.max()),
        "embedding_mean_abs_difference": float(difference.mean()),
        "cpu_embed_seconds": cpu_receipt["embed_seconds"],
        "mps_embed_seconds": mps_receipt["embed_seconds"],
        "cpu_reference_metrics": metrics.score_all(targets, predictions_cpu),
        "interpretation": (
            "Headline numbers in this companion are CPU numbers. MPS is reported only as a "
            "device-agreement check. A nonzero maximum difference is expected from "
            "float arithmetic; it is reported rather than asserted away."
        ),
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
