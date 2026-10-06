# Rhodopsin maintenance audit — 6 October 2026

Scope: scientific methods, split/target separation, metrics, reconstructed-group
uncertainty, shortlist logic, data and derived-artifact integrity, command line,
installation, CI, archival preservation and manuscript status. This is a code and
evidence review, not a new scientific experiment or independent training reproduction.

## Findings and fixes

- Issue #2: removed the machine-local editable requirement; made setup install this
  checkout and root tests run the real pytest suite; CI now runs on push/PR. Disabled
  scaffold entry points fail clearly. Replaced the unrelated Monte Carlo protocol text
  with truthful historical-study status.
- Issue #3: both analysis and diagnostics validate row IDs, canonical test labels,
  nearest-training distances/flags and finite, correctly shaped prediction vectors.
  Test and validation model sets must agree. Panel refuses nonempty output directories.
- Issue #4: embedding caches now retain versioned checkpoint, pooling, data and device
  provenance, generation receipts and vector checksums. Legacy caches require explicit
  refresh; no old cache or historical prediction array was regenerated during this audit.
- Issue #5: invalid numerical CLI arguments are refused before I/O; metrics reject
  broadcasting/nonfinite inputs; empty bootstrap samples are explicitly undefined.
  Unverified dataset inspection still refuses nonfinite target values.

## Scientific interpretation

No evidence found that these defects changed the archived measurements. All historical
publication assets, archives and recovered prediction arrays remain byte-identical.
The safeguards stop malformed or stale future artifacts from producing plausible output.
They do not strengthen the statistical conclusions of the original single-split study.

Train-only scaling and fitting are enforced by tests; validation/test labels do not
enter the fitted probe. A clean supervised split does not establish absence of ESM
pretraining overlap. Reconstructed groups are explicitly not upstream wild-type labels.
Whole-group bootstrap intervals remain exploratory and do not establish performance
on independently replicated biological backgrounds. Post-hoc Wilson coverage intervals
are descriptive row-level intervals, whose independent-row assumption is not justified
by a correlated group structure. They should not be read as background-level guarantees.
Fixed alpha with unscaled representations is a configuration comparison, not equal
regularisation or a general comparison of representation families.

## Second pass and residual work

Inspected every companion source module and auxiliary script, archived protocol and
result schemas, root scaffold and manuscript. Added regression fixtures for tampered
labels/distances, shape errors, cache corruption/device mismatch, invalid arguments,
empty bootstrap draws and output overwrite. No changes to model fit settings,
bootstrap seeds, shortlist definitions or historical metrics were required.

The manuscript deliverable is tracked separately in issue #1. The root harness remains
unconfigured; a PDF formatting build must not be called a complete scientific rerun.
Original archives may retain old installation instructions and code by design; readers
should use the maintained companion checkout for execution.
