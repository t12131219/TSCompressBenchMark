"""Strict quality and selection requests fail before accessing source files."""
import pytest

from tsbench.config import resolve


def experiment(task):
    return {'schema': 'tsbench.experiment/1', 'name': 'quality-request',
            'datasets': [{'id': 'source', 'path': 'unused.npy', 'format': 'npy'}],
            'methods': [{'id': 'raw', 'codec': 'raw-store'}], 'task': task}


@pytest.mark.parametrize('fidelity', ['bounded_abs', 'range_relative', 'point_relative', 'empirical_quality'])
@pytest.mark.parametrize('value', [True, False])
def test_quality_error_bound_rejects_booleans(fidelity, value):
    with pytest.raises(ValueError, match='boolean'):
        resolve(experiment({'fidelity': fidelity, 'error_bound': value}))


@pytest.mark.parametrize('value', [True, False])
def test_relative_floor_rejects_booleans(value):
    with pytest.raises(ValueError, match='boolean'):
        resolve(experiment({'fidelity': 'point_relative', 'error_bound': '0.01', 'relative_floor': value}))


@pytest.mark.parametrize('key,value', [('start', True), ('stop', -1), ('step', 0),
                                      ('columns_indices', [0, 0]), ('columns_indices', [False])])
def test_selection_request_is_validated_by_config(key, value):
    config = experiment({'fidelity': 'bitwise'})
    config['datasets'][0][key] = value
    with pytest.raises(ValueError):
        resolve(config)
