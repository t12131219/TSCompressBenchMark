"""Reject counterfeited timing semantics even if the JSON still parses."""
from copy import deepcopy
from hashlib import sha256
import struct

import pytest

from tsbench.application import m3_sprintz_timing as sprintz
from tsbench.assets import ContractError
from tools import m3_huff0_corpus_repeats as huff0


def metrics():
    return {'user_cpu_ns': 7, 'system_cpu_ns': 8, 'maxrss_bytes': 4096}


def session(operation, mounts):
    return {'operation': operation, 'input_mounts': mounts, 'status': 'completed', 'returncode': 0,
            'reason': '', 'session_id': operation, 'pid': 12, 'process_wall_ns': 100, 'child_usage': metrics()}


def test_sprintz_reductions_from_exact_bits_and_no_undeclared_output(tmp_path):
    bits = struct.pack('<4H', 0x8000, 0x7ff8, 0xffff, 1)
    oracle = {'count': [1] * 4, 'sum': [0x8000, 0x7ff8, 0xffff, 1], 'max': [0x8000, 0x7ff8, 0xffff, 1]}
    unit = {'raw_bytes': len(bits), 'restored_sha256': sha256(bits).hexdigest(),
            'auto': {'backend': 'upstream_simd', **oracle}, 'scalar': {'backend': 'scalar', **oracle}}
    case = {'rows': 1, 'columns': 1, 'units': [unit]}
    (tmp_path / 'column-0000.bin').write_bytes(bits)
    assert sprintz._verify_columns(case, tmp_path, oracle=True)['column-0000.bin']['bytes'] == len(bits)
    unit['scalar']['max'] = [0] * 4
    with pytest.raises(ContractError, match='independent u16 oracle'):
        sprintz._verify_columns(case, tmp_path, oracle=True)
    (tmp_path / 'other').touch()
    with pytest.raises(ContractError, match='column set differs'):
        sprintz._verify_columns(case, tmp_path, oracle=False)


def test_sprintz_query_rejects_mode_changes_extra_mounts_and_overlapping_clocks():
    geom = {'column': 0, 'row_start': 0, 'raw_bytes': 8, 'frame_bytes': 40}
    reducers = {'auto': {'backend': 'upstream_simd'}, 'scalar': {'backend': 'scalar'}}
    case = {'case_id': 'case', 'workspace_bytes': 1024, 'units': [{**geom, **reducers}]}
    doc = {'backend': sprintz.BACKEND, 'workspace_bytes': 1024,
           'units': [{**geom, **reducers, 'auto_wall_ns': 23, 'scalar_wall_ns': 42}]}
    prep = {'columns': {'orig': {'bytes': 8}}, 'archive': {'bytes': 40}}
    t = {'phase': 'measured', 'operation': 'query', 'round': 1}
    row = {**t, 'case_id': 'case', 'native': doc, 'native_totals_ns': {'auto': 23, 'scalar': 42},
           'process': session('query', {'archive.sfb1': prep['archive']}),
           'verified_output': None, 'supervision_and_verification_wall_ns': 200}
    seen = set()
    sprintz._validate(case, t, row, prep, seen)
    with pytest.raises(ContractError, match='process identity differ'):
        sprintz._validate(case, t, row, prep, seen)
    bad = deepcopy(row)
    bad['process']['input_mounts']['original'] = {'bytes': 8}
    with pytest.raises(ContractError, match='mounts, outputs'):
        sprintz._validate(case, t, bad, prep, set())
    bad = deepcopy(row)
    bad['native']['units'][0]['scalar']['backend'] = 'upstream_simd'
    with pytest.raises(ContractError, match='reduction differs'):
        sprintz._validate(case, t, bad, prep, set())
    bad = deepcopy(row)
    bad['process']['process_wall_ns'] = 45
    with pytest.raises(ContractError, match='clocks'):
        sprintz._validate(case, t, bad, prep, set())


def test_shared_table_train_and_decode_mount_disjoint_inputs():
    obj = {'format': 'ETB1', 'streams': 4, 'case_id': 'x', 'training': {'bytes': 9}, 'original': {'bytes': 23},
           'artifact': {'model.etb1': {'bytes': 12}, 'test.blocks': {'bytes': 20}, 'binding.json': {'bytes': 54}},
           'native': {'train': {'context_count': 1}, 'encode': {'context_count': 1}, 'decode': {'context_count': 1}}}
    assert huff0.protocol(obj, 'train')[0] == ('train',)
    assert huff0.protocol(obj, 'encode')[0] == ('model', 'holdout')
    assert huff0.protocol(obj, 'decode')[0] == ('model', 'blocks')
    t = {'operation': 'decode', 'phase': 'untimed_recovery', 'round': -1}
    mounts, out, native = huff0.expected(obj, 'decode')
    row = {**t, 'case_id': 'x', 'process': session('decode', mounts), 'native_observation': native,
           'output': out, 'staged_supervision_wall_ns': 201}
    huff0.validate(obj, row, t, set())
    row['process']['input_mounts']['train'] = obj['training']
    with pytest.raises(ContractError, match='frozen mount'):
        huff0.validate(obj, row, t, set())


def test_fec1_report_bills_complete_abi_frame_and_does_not_invent_native_clock():
    case = {'format': 'FEC1', 'case_id': 'x', 'dataset_id': 'test', 'route': 'huff0-reference', 'work_item_id': 'y',
            'artifact': {'bytes': 80}, 'original': {'bytes': 131}, 'schema': {'bytes': 7},
            'canonical_value_byte_range': [0, 131], 'cost': {'abi_header': 32, 'fec_header': 24, 'other': 24}}
    rows = [{**t, 'process': session(t['operation'], {}), 'staged_supervision_wall_ns': 200}
            for t in huff0.schedule('FEC1')]
    summary = huff0.summarize(case, rows)
    assert summary['artifact_bytes'] == 80
    assert summary['ratio'] == 131 / 80
    for op in ('encode', 'decode'):
        assert summary['directions'][op]['native_wall_ns'] is None
        dist = summary['directions'][op]['repeat_distributions']['isolated_process_wall_ns']
        assert (dist['count'], dist['sum'], dist['sample_basis']) == (3, 300, huff0.LIFECYCLE)
