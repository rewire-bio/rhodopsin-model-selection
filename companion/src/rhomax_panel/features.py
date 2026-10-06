"""Feature extractors for the five historical configurations.

The two composition variants are reimplemented to match the archived configurations
exactly, including their constant-zero columns. Those zero columns are preserved
rather than pruned, because the point of rerunning a historical configuration is to
rerun it, not to improve it.
"""
from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path

import numpy as np

from .data import AMINO_ACIDS, Row, CSV_SHA256

# Pinned checkpoint identities, verified before loading the official pickle.
CHECKPOINTS = {
    "esm2_t6_8M_UR50D": {
        "layer": 6,
        "dimension": 320,
        "sha256": "46f002a9870c9bdecd0ea887acb1f9a38a6b561e8f8bf8a6990b679b9d31b928",
        "url": "https://dl.fbaipublicfiles.com/fair-esm/models/esm2_t6_8M_UR50D.pt",
    },
    "esm2_t12_35M_UR50D": {
        "layer": 12,
        "dimension": 480,
        "sha256": "7f21e80e61d16a71735163ef555d3009afb0c98da74c48e29df08606973cc55e",
        "url": "https://dl.fbaipublicfiles.com/fair-esm/models/esm2_t12_35M_UR50D.pt",
    },
}


def composition_22(sequences: list[str]) -> np.ndarray:
    """log1p(length), 20 residue fractions, unknown fraction.

    The unknown fraction is identically zero on this archive, because the archive uses
    only the 20 standard residues. The column is kept because the historical
    configuration had it.
    """
    out = []
    for sequence in sequences:
        counts = [sequence.count(letter) for letter in AMINO_ACIDS]
        out.append(
            [math.log1p(len(sequence))]
            + [c / len(sequence) for c in counts]
            + [(len(sequence) - sum(counts)) / len(sequence)]
        )
    return np.asarray(out, dtype=float)


def composition_40(sequences: list[str]) -> np.ndarray:
    """20 residue fractions for each of two colon-separated components.

    Rhomax sequences have no colon, so the second component is empty and its 20
    columns are identically zero. This reproduces the archived 40-feature control.
    """
    out = []
    for sequence in sequences:
        parts = sequence.split(":")
        if len(parts) == 1:
            parts.append("")
        if len(parts) != 2:
            raise ValueError("Expected one sequence or a colon-delimited pair")
        out.append(
            [part.count(letter) / max(len(part), 1) for part in parts for letter in AMINO_ACIDS]
        )
    return np.asarray(out, dtype=float)


def verify_checkpoint(path: Path, model_name: str) -> str:
    """Hash the weights before ``torch.load`` touches the official pickle."""
    if model_name not in CHECKPOINTS:
        raise ValueError(f"Unsupported checkpoint identity: {model_name}")
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != CHECKPOINTS[model_name]["sha256"]:
        raise ValueError(
            f"{path} does not match the pinned {model_name} weights. Refusing to load "
            "unverified bytes."
        )
    return digest


def esm2_embeddings(
    rows: list[Row],
    checkpoint: Path,
    model_name: str,
    *,
    device: str = "cpu",
    batch_size: int = 4,
    threads: int = 4,
    seed: int = 0,
) -> tuple[np.ndarray, dict]:
    """Frozen final-layer residue-mean embeddings, excluding BOS, EOS and padding.

    Returns the matrix in ``rows`` order plus a timing and provenance receipt.
    """
    if batch_size < 1 or threads < 1:
        raise ValueError("batch_size and threads must be positive")
    import esm
    import torch

    specification = CHECKPOINTS[model_name]
    digest = verify_checkpoint(checkpoint, model_name)
    layer = specification["layer"]

    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    np.random.seed(seed)

    load_start = time.perf_counter()
    data = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model, alphabet = esm.pretrained.load_model_and_alphabet_core(model_name, data, regression_data=None)
    model.eval().to(device)
    converter = alphabet.get_batch_converter()
    load_seconds = time.perf_counter() - load_start

    vectors = np.empty((len(rows), specification["dimension"]), dtype=np.float64)
    embed_start = time.perf_counter()
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        _, _, tokens = converter([(r.seq_id, r.sequence) for r in batch])
        with torch.inference_mode():
            representations = model(
                tokens.to(device), repr_layers=[layer], return_contacts=False
            )["representations"][layer]
        for offset, row in enumerate(batch):
            # Slice 1..len+1 drops BOS at 0 and everything from EOS onwards, so padding
            # never enters the mean regardless of what else shares the batch.
            vectors[start + offset] = (
                representations[offset, 1 : len(row.sequence) + 1].mean(0).float().cpu().numpy()
            )
    embed_seconds = time.perf_counter() - embed_start

    receipt = {
        "model": model_name,
        "checkpoint_sha256": digest,
        "checkpoint_url": specification["url"],
        "representation_layer": layer,
        "dimension": specification["dimension"],
        "pooling": "mean over residues excluding BOS/EOS and padding",
        "encoder_frozen": True,
        "device": device,
        "batch_size": batch_size,
        "torch_threads": threads,
        "torch_seed": seed,
        "torch_version": torch.__version__,
        "fair_esm_version": "2.0.0",
        "sequences_encoded": len(rows),
        "load_seconds": load_seconds,
        "embed_seconds": embed_seconds,
        "training_overlap": "unreported; UniRef50 pretraining may overlap these proteins",
        "published_result_reproduction": False,
    }
    return vectors, receipt


def embedding_cache_key(model_name: str, csv_sha256: str) -> str:
    """Cache identity binds the checkpoint and the exact data bytes."""
    layer = CHECKPOINTS[model_name]["layer"]
    material = f"{model_name}:layer{layer}:{CHECKPOINTS[model_name]['sha256']}:{csv_sha256}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _vectors_digest(vectors: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(vectors).tobytes()).hexdigest()


def save_embedding_cache(path: Path, vectors: np.ndarray, rows: list[Row], model_name: str,
                         receipt: dict, *, device: str) -> None:
    import json

    _validate_vectors(vectors, rows, model_name)
    metadata = {
        "schema_version": 1, "model": model_name,
        "checkpoint_sha256": CHECKPOINTS[model_name]["sha256"],
        "dataset_csv_sha256": CSV_SHA256,
        "pooling": "final-layer residue mean excluding BOS/EOS/padding",
        "device": device, "vectors_sha256": _vectors_digest(vectors),
        "generation_receipt": receipt,
    }
    np.savez(path, vectors=vectors, seq_ids=np.asarray([r.seq_id for r in rows]),
             metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)))


def _validate_vectors(vectors: np.ndarray, rows: list[Row], model_name: str) -> None:
    expected = (len(rows), CHECKPOINTS[model_name]["dimension"])
    if vectors.shape != expected or not np.isfinite(vectors).all():
        raise ValueError(f"Embedding matrix must be finite with shape {expected}")


def load_embedding_cache(path: Path, rows: list[Row], model_name: str, *, device: str | None = None):
    """A cache checksum detects accidental corruption; it is not an authenticity signature."""
    import json
    from .data import CSV_SHA256

    with np.load(path, allow_pickle=False) as stored:
        if "metadata_json" not in stored:
            raise ValueError("Legacy embeddings lack provenance; use panel --refresh-embeddings")
        metadata = json.loads(str(stored["metadata_json"]))
        expected = {"schema_version": 1, "model": model_name,
                    "checkpoint_sha256": CHECKPOINTS[model_name]["sha256"],
                    "dataset_csv_sha256": CSV_SHA256,
                    "pooling": "final-layer residue mean excluding BOS/EOS/padding"}
        if any(metadata.get(k) != v for k, v in expected.items()):
            raise ValueError("Embedding cache encoder provenance mismatch; refresh embeddings")
        if device is not None and metadata.get("device") != device:
            raise ValueError("Embedding cache device mismatch; use panel --refresh-embeddings")
        if not isinstance(metadata.get("generation_receipt"), dict):
            raise ValueError("Embedding cache generation receipt is missing")
        if not np.array_equal(stored["seq_ids"], [r.seq_id for r in rows]):
            raise ValueError("Embedding cache row IDs differ from loaded rows")
        vectors = stored["vectors"]
        _validate_vectors(vectors, rows, model_name)
        if _vectors_digest(vectors) != metadata.get("vectors_sha256"):
            raise ValueError("Embedding cache vector checksum mismatch")
    return vectors, metadata
