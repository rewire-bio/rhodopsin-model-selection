"""Pinned FLIP2 Rhomax ``by_wild_type`` loading, with byte verification.

The upstream archive publishes four columns and no identifiers. Nothing in this
module invents biological metadata: identifiers are local digests of the sequence
itself, and the split assignment is read from the archive exactly as released.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import math
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Pinned upstream identity. See evidence/source-ledger.md for provenance.
ZENODO_URL = "https://zenodo.org/api/records/18433203/files/rhomax/by_wild_type.csv.gz/content"
MIRROR_URL = "https://flip.protein.properties/assets/splits/rhomax/by_wild_type.csv.gz"
DATASET_VERSION = "zenodo-18433203-v3"
# The compressed bytes differ between Zenodo and the FLIP mirror; the decompressed
# CSV is identical and is the only hash treated as the dataset's identity.
GZ_SHA256_ZENODO = "2d4bda268708bf2e161735bf77dd7ec503c233b42d4f4ab1abb3090eae6b6755"
GZ_SHA256_MIRROR = "7c6d2f02cb89310378ac9897c321fbbd909fb0757ac88803dcce84f5f6b05ce3"
GZ_MD5_ZENODO = "286781669d083104cc399ae8a561afc5"
CSV_SHA256 = "8e78f6a16cd5298131dca83130d4b94cc0ab4ae9c699460880441c19a65f656f"

EXPECTED_COUNTS = {"train": 584, "validation": 116, "test": 184}
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
TARGET_UNITS = "nm"
# Observed in the pinned archive; used only to bound user FASTA input, never to filter
# the benchmark rows.
ARCHIVE_LENGTH_RANGE = (227, 365)
ESM_MAX_LENGTH = 1022


@dataclass(frozen=True)
class Row:
    """One archived measurement.

    ``seq_id`` is a workspace-local identifier, not an upstream accession: the archive
    publishes no identifier of any kind.
    """

    csv_row: int
    seq_id: str
    sequence: str
    target: float
    split: str


def seq_id(sequence: str) -> str:
    return hashlib.sha256(sequence.strip().upper().encode()).hexdigest()[:12]


def download(cache: Path, *, url: str = ZENODO_URL, timeout: int = 600) -> Path:
    """Fetch the pinned archive into ``cache`` unless already present."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "by_wild_type.csv.gz"
    if not path.exists():
        tmp = path.with_suffix(".gz.partial")
        with urllib.request.urlopen(url, timeout=timeout) as response, tmp.open("wb") as out:
            while chunk := response.read(1 << 16):
                out.write(chunk)
        os.replace(tmp, path)
    return path


def verify(path: Path, *, allow_unverified: bool = False) -> dict:
    """Hash the archive and refuse a substituted split unless explicitly permitted."""
    raw = Path(path).read_bytes()
    gz_sha = hashlib.sha256(raw).hexdigest()
    csv_bytes = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    origin = {GZ_SHA256_ZENODO: "zenodo", GZ_SHA256_MIRROR: "flip-mirror"}.get(gz_sha, "unrecognised")
    receipt = {
        "dataset_version": DATASET_VERSION,
        "gz_sha256": gz_sha,
        "gz_md5": hashlib.md5(raw).hexdigest(),
        "gz_origin": origin,
        "csv_sha256": csv_sha,
        "csv_sha256_matches_pin": csv_sha == CSV_SHA256,
    }
    if csv_sha != CSV_SHA256 and not allow_unverified:
        raise ValueError(
            "Decompressed Rhomax CSV does not match the pinned v3 hash; refusing to "
            "substitute a different split. Re-download, or pass allow_unverified to "
            "inspect deliberately."
        )
    return receipt


def parse(path: Path, *, allow_unverified: bool = False) -> tuple[list[Row], dict]:
    """Read the archive into rows, preserving every archived assignment."""
    receipt = verify(path, allow_unverified=allow_unverified)
    raw = Path(path).read_bytes()
    csv_bytes = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    if set(reader.fieldnames or []) != {"sequence", "set", "validation", "target"}:
        raise ValueError(f"Unexpected Rhomax columns: {reader.fieldnames}")

    rows: list[Row] = []
    for index, record in enumerate(reader):
        flag, declared = record["validation"], record["set"]
        if flag not in ("True", "False") or declared not in ("train", "test"):
            raise ValueError(f"Unexpected split/validation pair at row {index}: {declared}/{flag}")
        if declared == "test" and flag == "True":
            raise ValueError(f"Row {index} is both test and validation")
        split = "validation" if flag == "True" else declared
        sequence = record["sequence"]
        if not sequence or set(sequence) - set(AMINO_ACIDS):
            raise ValueError(f"Row {index} carries residues outside the 20-letter alphabet")
        target = float(record["target"])
        if not math.isfinite(target):
            raise ValueError(f"Row {index} has a non-finite target")
        rows.append(Row(index, seq_id(sequence), sequence, target, split))

    counts = {s: sum(r.split == s for r in rows) for s in EXPECTED_COUNTS}
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"Split counts {counts} differ from the pinned manifest {EXPECTED_COUNTS}")
    receipt |= {"rows": len(rows), "split_counts": counts, "target_units": TARGET_UNITS}
    return rows, receipt


def load(cache: Path, *, allow_unverified: bool = False) -> tuple[list[Row], dict]:
    return parse(download(Path(cache)), allow_unverified=allow_unverified)


def by_split(rows: list[Row], split: str) -> list[Row]:
    return [r for r in rows if r.split == split]


def read_fasta(path: Path) -> list[tuple[str, str]]:
    """Minimal FASTA reader for unlabelled user inference.

    Deliberately strict: it validates the alphabet and length rather than silently
    cropping or substituting residues, because a quietly truncated sequence would
    produce a confident wavelength number for a protein the caller did not supply.

    Lines beginning with ';' are treated as comments, per the original Pearson FASTA
    format. Everything else outside a header must be residues.
    """
    entries: list[tuple[str, str]] = []
    name, chunks = None, []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith(">"):
            if name is not None:
                entries.append((name, "".join(chunks)))
            name, chunks = line[1:].strip() or f"record_{len(entries) + 1}", []
        else:
            if name is None:
                raise ValueError("FASTA content appeared before the first '>' header")
            chunks.append(line.upper())
    if name is not None:
        entries.append((name, "".join(chunks)))
    if not entries:
        raise ValueError("No FASTA records found")

    seen: set[str] = set()
    for record_name, sequence in entries:
        if record_name in seen:
            raise ValueError(f"Duplicate FASTA header: {record_name}")
        seen.add(record_name)
        if not sequence:
            raise ValueError(f"Record {record_name} has no residues")
        bad = sorted(set(sequence) - set(AMINO_ACIDS))
        if bad:
            raise ValueError(
                f"Record {record_name} contains residues outside the 20-letter alphabet: "
                f"{''.join(bad)}. The probes were fitted on the 20 standard residues only; "
                "ambiguity codes and gaps are not supported."
            )
        if not 1 <= len(sequence) <= ESM_MAX_LENGTH:
            raise ValueError(
                f"Record {record_name} has {len(sequence)} residues; supported range is "
                f"1..{ESM_MAX_LENGTH} and no cropping is applied."
            )
    return entries
