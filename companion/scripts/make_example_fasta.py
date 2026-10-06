"""Generate an example FASTA from the locally verified archive.

The sequences are NOT shipped inside this code archive. They are written out from the
cached CC-BY-4.0 source file at run time, so the code archive carries no source data and
the example still exercises the real interface.

The selection rule is fixed and label-free: one training row, one test row that has an
equal-length training neighbour, and one test row that has none. That makes the
distance-to-training signal visible in the output without choosing rows by their targets.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from rhomax_panel import data, models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="./cache")
    parser.add_argument("--output", default="./example.fasta")
    args = parser.parse_args()

    rows, receipt = data.load(Path(args.cache).expanduser().resolve())
    test = data.by_split(rows, "test")
    _, distances, _ = models.nearest_training_sequence(rows)

    train_row = data.by_split(rows, "train")[0]
    with_neighbour = next(r for r, d in zip(test, distances) if d < 1.0)
    without_neighbour = next(r for r, d in zip(test, distances) if d >= 1.0)

    chosen = [
        ("train_row_known_to_the_probe", train_row),
        ("test_row_with_equal_length_training_neighbour", with_neighbour),
        ("test_row_with_no_equal_length_training_neighbour", without_neighbour),
    ]
    lines = [
        "; Derived at run time from FLIP2 Rhomax by_wild_type, CC-BY-4.0.",
        f"; Source CSV sha256 {receipt['csv_sha256']} ({receipt['dataset_version']}).",
        "; Measured wavelengths are deliberately NOT included: this file is input for",
        "; unlabelled inference, not a held-out evaluation set.",
    ]
    for label, row in chosen:
        lines.append(f">{label}|seq_id={row.seq_id}|csv_row={row.csv_row}|split={row.split}")
        sequence = row.sequence
        lines.extend(sequence[i : i + 60] for i in range(0, len(sequence), 60))

    path = Path(args.output)
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path} with {len(chosen)} records (no measured targets included).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
