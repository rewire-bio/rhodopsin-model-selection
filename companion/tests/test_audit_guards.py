"""Synthetic regressions: these checks are not a new scientific run."""
from pathlib import Path
from types import SimpleNamespace
import json

import numpy as np
import pytest

from rhomax_panel import artifacts, cli, data, features, metrics, models, posthoc


def rows():
    return [data.Row(0, 'a', 'AAAA', 500., 'train'),
            data.Row(1, 'b', 'AAAC', 510., 'test'),
            data.Row(2, 'c', 'CCCCC', 520., 'test')]


def valid_predictions():
    return dict(seq_ids=np.array(['b', 'c']), targets=np.array([510., 520.]),
                distances=np.array([.25, 1.]), has_length_match=np.array([True, False]),
                model=np.array([505., 506.]))


@pytest.mark.parametrize('key,value', [
    ('targets', [999., 520.]), ('distances', [0., 1.]),
    ('has_length_match', [True, True]), ('model', [np.nan, 1.]),
    ('model', [[1.], [2.]]), ('model', [1.]), ('seq_ids', ['c', 'b']),
])
def test_saved_prediction_tampering_is_rejected(tmp_path, key, value):
    arrays = valid_predictions()
    arrays[key] = np.array(value)
    np.savez(tmp_path / 'test.npz', **arrays)
    with np.load(tmp_path / 'test.npz') as stored, pytest.raises(ValueError):
        artifacts.validate_predictions(stored, rows(), 'test')


def test_canonical_prediction_artifact_is_accepted(tmp_path):
    np.savez(tmp_path / 'test.npz', **valid_predictions())
    with np.load(tmp_path / 'test.npz') as stored:
        assert set(artifacts.validate_predictions(stored, rows(), 'test')) == {'model'}


def test_panel_refuses_to_overwrite_results_before_loading_data(tmp_path):
    (tmp_path / 'old.json').write_text('{}')
    with pytest.raises(ValueError, match='new or empty'):
        cli.cmd_panel(SimpleNamespace(cache=str(tmp_path), output=str(tmp_path)))


@pytest.mark.parametrize('argv', [
    ['panel', '--batch-size', '-1'], ['panel', '--threads', '0'],
    ['panel', '--tolerance', 'inf'], ['panel', '--tolerance', 'nan'],
    ['panel', '--tolerance', '-1'], ['predict', 'missing.fa', '--batch-size', '0'],
])
def test_cli_refuses_invalid_numbers_before_io(argv):
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 2


@pytest.mark.parametrize('metric', [metrics.mae, metrics.rmse, metrics.spearman, metrics.ndcg])
@pytest.mark.parametrize('bad', [[[1.], [2.]], [1.], [np.nan, 2.], []])
def test_metrics_cannot_broadcast_or_score_nonfinite(metric, bad):
    with pytest.raises(ValueError):
        metric(np.array([1., 2.]), np.array(bad))


def test_embedding_validation_happens_before_model_import():
    with pytest.raises(ValueError, match='positive'):
        features.esm2_embeddings([], Path('missing'), 'esm2_t6_8M_UR50D', batch_size=-1)


def test_bootstrap_with_no_usable_draw_is_explicitly_undefined():
    # Seed 0 draws the second singleton twice, giving a constant resampled predictor.
    out = posthoc.shortlist_bootstrap(np.array([500., 510.]), np.array([1., 2.]),
                                      ['a', 'b'], draws=1, seed=0, capacity=1)
    assert out['defined'] is False
    assert out['usable_draws'] == 0 and out['skipped_draws'] == 1


@pytest.mark.parametrize('corruption', ['legacy', 'device', 'values', 'shape', 'ids', 'encoder'])
def test_embedding_cache_refuses_corruption(tmp_path, corruption):
    name = 'esm2_t6_8M_UR50D'
    path = tmp_path / 'cache.npz'
    matrix = np.zeros((3, 320))
    features.save_embedding_cache(path, matrix, rows(), name, {'device': 'cpu'}, device='cpu')
    got, metadata = features.load_embedding_cache(path, rows(), name, device='cpu')
    assert np.array_equal(got, matrix)
    assert metadata['generation_receipt']['device'] == 'cpu'
    with np.load(path) as stored:
        arrays = {key: stored[key] for key in stored.files}
    if corruption == 'legacy':
        del arrays['metadata_json']
    elif corruption == 'device':
        with pytest.raises(ValueError, match='device'):
            features.load_embedding_cache(path, rows(), name, device='mps')
        return
    elif corruption == 'values':
        arrays['vectors'][0, 0] = 1.
    elif corruption == 'shape':
        arrays['vectors'] = np.zeros((3, 1))
    elif corruption == 'ids':
        arrays['seq_ids'] = np.array(['x', 'b', 'c'])
    else:
        metadata['checkpoint_sha256'] = 'wrong'
        arrays['metadata_json'] = np.asarray(json.dumps(metadata))
    np.savez(path, **arrays)
    with pytest.raises(ValueError):
        features.load_embedding_cache(path, rows(), name, device='cpu')


def test_nonfinite_dataset_targets_are_rejected_even_when_unverified(tmp_path):
    path = tmp_path / 'data.csv'
    path.write_text('sequence,target,set,validation\nAAAA,nan,train,False\n')
    with pytest.raises(ValueError, match='non-finite'):
        data.parse(path, allow_unverified=True)
