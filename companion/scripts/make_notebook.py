"""Convert notebooks/explore.py into an executed .ipynb, with no jupytext dependency.

Splitting on the percent-format cell markers keeps the notebook's source reviewable as a
plain script while still shipping a runnable notebook. Executing it here means a broken
cell is caught in CI rather than by the reader.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CELL = re.compile(r"^# %%(?:\s*\[(?P<kind>\w+)\])?\s*$", re.MULTILINE)


def split_cells(text: str) -> list[tuple[str, str]]:
    marks = list(CELL.finditer(text))
    if not marks:
        raise ValueError("no '# %%' cell markers found")
    cells = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end() : end].strip("\n")
        kind = mark.group("kind") or "code"
        if kind == "markdown":
            body = "\n".join(line.removeprefix("# ").removeprefix("#") for line in body.splitlines())
        if body.strip():
            cells.append((kind, body))
    return cells


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="notebooks/explore.py")
    parser.add_argument("--output", default="notebooks/explore.ipynb")
    parser.add_argument("--execute", action="store_true", help="run the notebook and keep outputs")
    args = parser.parse_args()

    cells = split_cells(Path(args.source).read_text())
    notebook = {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": (body + "\n").splitlines(keepends=True),
                **({"outputs": [], "execution_count": None} if kind == "code" else {}),
            }
            for kind, body in cells
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.13"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(notebook, indent=1) + "\n")
    print(f"wrote {out} with {len(cells)} cells "
          f"({sum(1 for k, _ in cells if k == 'code')} code)")

    if args.execute:
        import subprocess

        result = subprocess.run(
            ["jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", str(out)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(result.stderr[-2000:])
            return result.returncode
        print("executed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
