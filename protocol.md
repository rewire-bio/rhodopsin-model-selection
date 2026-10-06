# Rhodopsin wavelength model selection

Status: historical study imported; no newly approved experiment or harness reproduction.

The released study predicts peak absorption wavelength on the fixed FLIP2 Rhomax
`by_wild_type` split: 584 training, 116 validation and 184 test rows. The historical
analysis protocol, input provenance and result receipts are preserved in
`downloads/rhomax-wavelength-results.tar.gz`, including
`frozen-exploratory-protocol.md` and `source-ledger.md`. The original detailed article
is preserved at `article/original.md`.

The fixed panel comprises the training mean, two composition/ridge configurations,
two frozen ESM-2/ridge configurations and a nearest-training-sequence control.
Targets are standardised on training rows only. Historical errors, reconstructed-group
bootstrap intervals and shortlist decisions are exploratory. Validation interval and
shortlist spread analyses are labelled post hoc. No biological function beyond the
wavelength endpoint is established.

The October 2026 maintenance audit adds integrity checks and synthetic regression tests;
it does not change model settings, regenerate predictions or replace historical results.
See `evidence/reviews/2026-10-06-maintenance-audit.md`.

A new scientific run requires a separate concrete amendment covering inputs, methods,
predeclared tolerances, runtime/storage limits and user approval. The root harness
experiment and reproduction commands remain disabled until that work is completed.
The paper build, when available, formats imported evidence and is not a new experiment.
