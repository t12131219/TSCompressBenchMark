"""ETB1 publication, binding, and clocks are independently checkable."""
from copy import deepcopy

import pytest

from tsbench.application import m3_etb1_pipeline_timing as pipeline
from tsbench.assets import ContractError


def test_publication_needs_exact_file_set_and_fresh_target(tmp_path):
    draft, target = (tmp_path / n for n in ('draft', 'published'))
    draft.mkdir()
    (draft / 'model').write_bytes(b'model')
    (draft / 'block').write_bytes(b'block')
    with pytest.raises(ContractError, match='exact files'):
        pipeline.publish(draft, target, ['model'])
    assert draft.is_dir() and not target.exists()
    pipeline.publish(draft, target, ['model', 'block'])
    assert not draft.exists() and sorted(p.name for p in target.iterdir()) == ['block', 'model']
    draft.mkdir()
    with pytest.raises(ContractError, match='fresh sibling'):
        pipeline.publish(draft, target, [])


def test_model_and_sequence_binding_rejects_substitution(tmp_path):
    etb1 = pipeline.etb1
    model = tmp_path / 'model'
    model.write_bytes(b'original model')
    case = {'streams': 4, 'model': pipeline.ref(model), 'wire': etb1.binary_ref(b'locked blocks')}
    sidecar = etb1.binding(case['streams'], case['model'], case['wire'])
    case['binding'] = etb1.binary_ref(sidecar)
    p = tmp_path / 'binding.json'
    p.write_bytes(sidecar)
    pipeline.check_binding(case, tmp_path)
    p.write_bytes(etb1.binding(case['streams'], case['model'], etb1.binary_ref(b'other blocks')))
    with pytest.raises(ContractError, match='binding differs'):
        pipeline.check_binding(case, tmp_path)
    p.write_bytes(sidecar)
    model.write_bytes(b'replaced model')
    with pytest.raises(ContractError, match='binding differs'):
        pipeline.check_binding(case, tmp_path)


def test_decode_validation_rejects_raw_mount_or_inconsistent_clock():
    plan, trial = {'environment': {'cpu': 6}}, {'direction': 'decode', 'phase': 'measured', 'round': 1}
    case = {'case_id': 'case', 'model': {'bytes': 9}, 'native': {'decode': {'context_count': 1}}}
    refs = {'wire': {'blocks': {'bytes': 20}}, 'raw': {'blocks': {'bytes': 48}}}
    row = {'case_id': 'case', **trial, 'products': refs['raw'], 'wall_ns': 151,
           'phases_ns': {'check_binding_ns': 10, 'decode_and_check_ns': 120, 'publish_ns': 21},
           'children': {'decode': {'operation': 'decode', 'input_mounts': {**refs['wire'], 'model': case['model']},
                                   'status': 'completed', 'returncode': 0, 'reason': '', 'session_id': 'child',
                                   'child_usage': {'maxrss_bytes': 1024}, 'process_wall_ns': 100}},
           'native': {'decode': {'context_count': 1, 'cpu_endpoints': [6, 6],
                                 'table_wall_ns': 10, 'block_calls_wall_ns': 12}}}
    seen = set()
    pipeline.validate(plan, case, trial, row, refs, seen)
    assert seen == {'child'}
    with pytest.raises(ContractError, match='nested clock'):
        pipeline.validate(plan, case, trial, row, refs, seen)
    for change in ('mount', 'process', 'native'):
        altered = deepcopy(row)
        if change == 'mount':
            altered['children']['decode']['input_mounts']['original'] = refs['raw']['blocks']
        elif change == 'process':
            altered['children']['decode']['process_wall_ns'] = 121
        else:
            altered['native']['decode']['block_calls_wall_ns'] = 91
        with pytest.raises(ContractError, match='nested clock'):
            pipeline.validate(plan, case, trial, altered, refs, set())
