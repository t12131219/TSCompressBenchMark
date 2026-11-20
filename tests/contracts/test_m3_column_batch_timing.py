"""Frame windows are grouped for I/O, not for scope or statistical replication."""
from struct import pack

import pytest

from tsbench.application import m3_column_batch as batch, m3_column_batch_timing as timing
from tsbench.assets import ContractError


def test_schedule_balances_backends_and_excludes_setup():
    c = {'case_id':'61'*32, 'decode_backends':[batch.SCALAR, batch.AUTO]}
    schedule = list(timing._schedule(c))
    assert schedule == list(timing._schedule(c))
    for round_no in range(4):
        rows = [t for t in schedule if t['round'] == round_no]
        assert {t['slot'] for t in rows} == {'encode', batch.SCALAR, batch.AUTO}
        assert {t['phase'] for t in rows} == {'warmup' if round_no == 0 else 'measured'}
    assert timing.distribution([0.5, 1.1, 1.5]) == {'count':3,'min':0.5,'median':1.1,'max':1.5,
                                                         'sample_basis':'independent_file_direction_rounds'}


def test_replay_verifies_staged_type_schema_and_raw_bits(tmp_path):
    typed = batch.schema('titchy-batch', 1)
    raw = b'\x00'*7 + b'\x80'
    c = {'units':[{'original':batch.br(raw), 'schema':batch.br(typed), 'artifact':{'bytes':100}}]}
    group = tmp_path/'g00000.bin'
    header = pack('<II', len(raw), len(typed))
    group.write_bytes(header+typed+raw)
    timing._verify_staged({group.name:group},c)
    group.write_bytes(header+typed+b'\x00'*8)
    with pytest.raises(ContractError, match='original/schema differs'):
        timing._verify_staged({group.name:group},c)
    group.write_bytes(header+typed+raw+b'\x00')
    with pytest.raises(ContractError, match='trailing bytes'):
        timing._verify_staged({group.name:group},c)
