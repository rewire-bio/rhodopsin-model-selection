# Rhodopsin wavelength model selection

Standalone study repository, migrated from the model-selection article series.

- [Historical-evidence paper (PDF)](paper/rhodopsin-model-selection.pdf)
- [Paper source](paper/main.tex) and [evidence mapping](evidence/paper-migration-map.json)
- [Maintenance audit](evidence/reviews/2026-10-06-maintenance-audit.md)
- [Original detailed article](article/original.md)
- [Executable companion](companion/README.md)
- [Source provenance](evidence/import-manifest.json)
- [Byte-identical published original](article/published-original.md)
- [Migration preservation audit](evidence/migration-audit.json)
- [Recovered original prediction arrays](evidence/recovered-original-results/README.md)

## Status

The original measurements and code are imported. The historical-evidence manuscript and PDF are complete; independent scientific reproduction remains pending. The generic harness configuration is unconfigured and must not be used to claim verified results. Follow the companion README for the original runnable workflow. No new experiment, human approval, or independent reproduction is claimed by this migration.

The repository will hold the detailed methods and paper; the blog will provide a shorter accessible explanation. Original third-party licences and notices remain applicable; no blanket relicensing is applied.

## Validation and paper build

Run `make setup` followed by `make test` for the maintained companion checks. These
synthetic tests do not reproduce the scientific panel. Optional tests clearly skip when
pinned data or completed-run files are absent.

`make paper` requires Python 3.11 (managed by uv), pdfLaTeX and BibTeX. It verifies the
preserved evidence, regenerates numerical tables and the historical claim ledger, and
builds `paper/build/main.pdf`. The checked-in PDF and receipt record a clean source
snapshot and the actual TeX engine versions. This formatting build does not download
data, generate embeddings, fit models or rerun the exploratory analysis. Original
publication archives remain unchanged; use `companion/README.md` for maintained code.
