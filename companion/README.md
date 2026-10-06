# rhomax-wavelength-panel

A reproducible comparison of six ways to predict rhodopsin **peak absorption wavelength in
nanometres** on the FLIP2 Rhomax `by_wild_type` split.

The endpoint is peak absorption wavelength and nothing else. No number produced here says
anything about activation efficiency, expression, photostability, ion transport or cellular
function.

## What it does

Reruns the five configurations that were evaluated historically, exactly as they were
configured, and adds one new interpretable control:

| Key | Configuration |
| --- | --- |
| `training-mean` | constant: the mean of the training targets |
| `composition-40` | 20 residue fractions plus 20 constant-zero columns, fixed alpha-10 ridge |
| `composition-22` | log1p(length), 20 residue fractions, unknown fraction, fixed alpha-10 ridge |
| `esm2-8m` | frozen ESM-2 8M layer-6 residue mean, fixed alpha-10 ridge |
| `esm2-35m` | frozen ESM-2 35M layer-12 residue mean, fixed alpha-10 ridge |
| `nearest-train-seq` | new control: the target of the nearest training sequence |

The ridge settings are not exposed as options. A tuned variant must not be able to
masquerade as one of the historical configurations; there is a test that enforces this.

## Setup

Needs Python 3.11 and about 160 MB of downloads (data plus both checkpoints).

```bash
cd companion
uv venv --python 3.11 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements-locked.txt
VIRTUAL_ENV=.venv uv pip install -e . --no-deps
mkdir -p cache
```

Fetch the pinned inputs. Every one is hash-checked before use, and the run refuses to
proceed on a mismatch rather than quietly scoring a different split:

```bash
curl -L -o cache/by_wild_type.csv.gz \
  "https://zenodo.org/api/records/18433203/files/rhomax/by_wild_type.csv.gz/content"
curl -L -o cache/esm2_t6_8M_UR50D.pt \
  https://dl.fbaipublicfiles.com/fair-esm/models/esm2_t6_8M_UR50D.pt
curl -L -o cache/esm2_t12_35M_UR50D.pt \
  https://dl.fbaipublicfiles.com/fair-esm/models/esm2_t12_35M_UR50D.pt
```

Expected checksums, all verified in code at run time:

| File | sha256 |
| --- | --- |
| `by_wild_type.csv.gz` (Zenodo) | `2d4bda268708bf2e161735bf77dd7ec503c233b42d4f4ab1abb3090eae6b6755` |
| decompressed CSV | `8e78f6a16cd5298131dca83130d4b94cc0ab4ae9c699460880441c19a65f656f` |
| `esm2_t6_8M_UR50D.pt` | `46f002a9870c9bdecd0ea887acb1f9a38a6b561e8f8bf8a6990b679b9d31b928` |
| `esm2_t12_35M_UR50D.pt` | `7f21e80e61d16a71735163ef555d3009afb0c98da74c48e29df08606973cc55e` |

The FLIP mirror at `flip.protein.properties` serves the same CSV inside different gzip
framing, so its archive sha256 is `7c6d2f02cb89310378ac9897c321fbbd909fb0757ac88803dcce84f5f6b05ce3`.
Both are accepted; the decompressed CSV hash is what defines the dataset.

## Quickstart, no weights needed

Composition and the constant only, about 4 seconds on CPU:

```bash
rhomax-panel --cache ./cache verify
rhomax-panel --cache ./cache panel --output ./results --skip-esm
```

This already reproduces three of the five archived configurations.

## Full reproduction

```bash
rhomax-panel --cache ./cache panel --output ./results
rhomax-panel --cache ./cache analyse --output ./results --baseline training-mean
python scripts/diagnostics.py --cache ./cache --results ./results --output ./results/diagnostics.json
```

`panel` exits non-zero if any configuration fails to match its archived Spearman and NDCG
at 1e-9, so a silent drift cannot pass unnoticed.

Measured on an Apple M4, 16 GB, CPU, batch 4, 4 torch threads, across three complete runs:
**49 to 52 s** wall for the full panel, peak RSS **1.37 to 1.48 GB**. In the run whose receipt
ships with this companion, ESM-2 35M encoding of all 884 sequences took 35.2 s and 8M 13.2 s.
Not a hardware-normalised benchmark: one machine, one batch size, three runs.

## Scoring your own sequences

This is unlabelled inference, which is a different thing from held-out evaluation, and the
CLI keeps them apart.

```bash
python scripts/make_example_fasta.py --cache ./cache --output ./example.fasta
rhomax-panel --cache ./cache predict ./example.fasta --configuration composition-22
```

Input rules, enforced rather than patched around:

- the 20 standard amino acids only; ambiguity codes, gaps and `X` are rejected
- 1 to 1022 residues; longer sequences are rejected, never cropped
- duplicate FASTA headers are rejected
- `;` comment lines are allowed, per the original Pearson format

The output reports, per sequence, the predicted wavelength in nm, whether it falls outside
the training range, and the distance to the nearest training sequence. Read that distance:
92 of the 184 benchmark test rows had no training sequence even of the same length, and
that is the regime where this panel was least accurate.

## Accelerator check

```bash
python scripts/device_agreement.py --cache ./cache --model esm2_t6_8M_UR50D
```

On the reference machine CPU and MPS agreed to 1.4e-6 maximum absolute difference, and MPS
was **slower** than CPU for a model this small. All headline numbers are CPU numbers.

## Tests

```bash
python -m pytest tests/ -q
```

The suite includes synthetic regression tests and optional archived-data checks. They target
the ways this code could produce a plausible but wrong wavelength:
a substituted data file, wrong split counts, a leaked held-out label, a constant predictor
scored as though it had a rank correlation, NDCG tie handling, silently cropped user
sequences, and a tuned ridge replacing a historical configuration. Tests needing the real
archive skip with a message when the cache is absent rather than passing on synthetic data.

## What is in here and what is not

Not included, deliberately: source measurements, model weights, and any derived file that
would redistribute either. The archive is CC-BY 4.0 and attributed to Inoue et al. 2021;
this repository downloads it rather than republishing it. The example FASTA is generated at
run time from your local copy for the same reason.

## Licence

The upstream data keeps its own CC-BY 4.0 terms and no new licence is asserted over it.
Licensing of the original code here is an open review item.

## Maintained-code audit (October 2026)

The published archives remain historical evidence. The maintained companion validates saved
labels, neighbour metadata and finite prediction vectors before analysis. Each panel run
requires a new or empty output directory to preserve previous attempts. Embedding caches
now include encoder provenance and a vector checksum. Old cache files require explicit
`panel --refresh-embeddings`; a CPU request rejects a cache generated on another device.
These guards do not alter the fixed models or establish a new scientific reproduction.
Root `make test` runs the companion suite; the root harness and paper remain pending.

The documented `--skip-esm` panel remains available. `analyse` records present and
missing configurations and whether validation predictions exist in `input_scope`.
Partial panels or absent validation inputs are explicitly marked incomplete; absent
validation skips only the labelled post-hoc interval probe. Unknown configuration
columns and mismatched test/validation model sets are refused.
