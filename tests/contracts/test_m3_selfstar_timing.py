"""Whole-file SElf* diagnostic checks per-column lifecycle and detached mounts."""
from copy import deepcopy
from hashlib import sha256

import pytest

from tsbench.application import m3_selfstar_timing as timing
from tsbench.assets import ContractError


def test_incremental_trial_checks_finalized_read_and_exact_wire_mounts():
    rows = 2000
    unit = {'column': 0, 'blocks': 2, 'native_bits': 91, 'native_payload_bytes': 12, 'input_bytes': rows * 8,
            'restored_sha256': 'raw', 'artifact_bytes': 128, 'frame_sha256': 'wire',
            'schema_sha256': sha256(timing.schema(rows, 0)).hexdigest(),
            'lifecycle': {'add_calls': timing._live_adds(rows), 'prefinish_bits': 50}}
    plan = {'environment': {'cpu': 6}}
    case = {'rows': rows, 'cols': 1, 'case_id': 'case', 'units': [unit], 'variant': 'incremental'}
    raw, wire = timing.refs(case)
    trial = {'operation': 'decode', 'round': 1, 'phase': 'measured'}
    row = {'case_id': 'case', **trial, 'output': raw, 'staged_supervision_and_verification_wall_ns': 100,
           'process': {'input_mounts': wire, 'operation': 'decode', 'status': 'completed', 'returncode': 0,
                       'reason': '', 'pid': 101, 'session_id': 'child', 'child_usage': {'maxrss_bytes': 2048},
                       'process_wall_ns': 90},
           'native': {'route': 'incremental', 'cpu_endpoints': [6, 6],
                      'columns': [{'column': 0, 'context_create_wall_ns': 5, 'direction_call_wall_ns': 20,
                                   'execution': {'blocks': 2, 'native_bits': 91, 'native_payload_bytes': 12,
                                                 'mode': 'read-finalized', 'rows': rows, 'add_calls': 0,
                                                 'prefinish_bits': 0}}]},
           'native_totals_ns': {'context_create_wall_ns': 5, 'direction_call_wall_ns': 20}}
    seen = set()
    timing.validate(plan, case, trial, row, seen)
    assert seen == {'child'}
    altered = deepcopy(row)
    altered['process']['input_mounts'].update(raw)
    with pytest.raises(ContractError, match='mounts/resources/timing'):
        timing.validate(plan, case, trial, altered, set())
    altered = deepcopy(row)
    altered['native']['columns'][0]['execution']['mode'] = 'live'
    with pytest.raises(ContractError, match='ordered native profile'):
        timing.validate(plan, case, trial, altered, set())
    altered = deepcopy(row)
    altered['process']['process_wall_ns'] = 101
    with pytest.raises(ContractError, match='mounts/resources/timing'):
        timing.validate(plan, case, trial, altered, set())
