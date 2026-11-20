import pytest

from tsbench.application import m3_whole_durable as durable
from tsbench.assets import ContractError


def test_direction_requires_separate_sync_and_inherited_output_scope(monkeypatch):
    seen = []
    monkeypatch.setattr(durable.abi, 'validate', lambda plan, case, t, row, mounts, outputs, sessions:
                        seen.append((mounts, outputs)))
    case = {'driver': 'abi'}
    for op in ('encode', 'decode'):
        t = {'operation': op}
        row = {'durable_wall_ns': 69, 'staged_supervision_and_verification_wall_ns': 39, 'fsync_wall_ns': 30}
        durable._validate({}, case, t, row, 'raw', 'wire', set())
        for update in ({'fsync_wall_ns': 0}, {'durable_wall_ns': 68}):
            with pytest.raises(ContractError, match='disjoint fsync'):
                durable._validate({}, case, t, row | update, 'raw', 'wire', set())
    assert seen == [('raw', 'wire')] * 3 + [('wire', 'raw')] * 3


def test_each_direction_only_summarizes_measured_repeats(monkeypatch):
    basis = lambda: {'directions': {'encode': {}, 'decode': {}}}
    monkeypatch.setattr(durable.abi, 'summarize', lambda *_: {'logical_bytes': 1 << 20, **basis()})
    monkeypatch.setattr(durable.selfstar, 'summarize', lambda *_: {'counts': {'input_bytes': 1 << 20}, **basis()})
    rows = [{'operation': op, 'phase': phase, 'durable_wall_ns': ns, 'fsync_wall_ns': 5} for op in ('encode', 'decode')
            for phase, ns in (('warmup', 1), ('measured', 100), ('measured', 200), ('measured', 300))]
    for driver in durable.DRIVERS:
        d = durable._summarize({'driver': driver}, rows)['directions']
        for op in ('encode', 'decode'):
            assert d[op]['verified_durable']['wall_ns'] == {'count': 3, 'min': 100, 'max': 300, 'median': 200,
                                                           'sample_basis': 'independent_file_direction_rounds'}
            assert d[op]['verified_durable']['logical_mib_per_second']['median'] == 5_000_000
