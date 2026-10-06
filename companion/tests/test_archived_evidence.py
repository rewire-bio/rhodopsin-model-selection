"""Check existing prediction bytes against reported metrics without model execution."""
import json
from pathlib import Path
import tarfile

import numpy as np
import pytest

from rhomax_panel import metrics

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('name', ['training-mean', 'composition-22', 'composition-40',
                                  'nearest-train-seq', 'esm2-8m', 'esm2-35m'])
def test_recovered_predictions_match_published_metrics_and_rows(name):
    with tarfile.open(ROOT / 'downloads/rhomax-wavelength-results.tar.gz') as archive:
        receipt = json.load(archive.extractfile('rhomax-wavelength-results/panel-receipt.json'))
        records = json.load(archive.extractfile('rhomax-wavelength-results/test-predictions.json'))
    with np.load(ROOT / 'evidence/recovered-original-results/test-predictions.npz') as stored:
        assert list(stored['seq_ids']) == [r['seq_id'] for r in records]
        np.testing.assert_array_equal(stored['targets'], [r['measured_nm'] for r in records])
        np.testing.assert_array_equal(stored[name], [r[f'pred_{name}_nm'] for r in records])
        got = metrics.score_all(stored['targets'], stored[name])
    for key, expected in receipt['scores'][name].items():
        if expected is None:
            assert got[key] is None
        else:
            assert got[key] == pytest.approx(expected, abs=1e-9, rel=0)
