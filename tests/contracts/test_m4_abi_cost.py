"""The size, pairing and observed-work policy is not a comparison of unlike clocks."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tsbench.application import m4_abi_cost as c
from tsbench.assets import ContractError


def test_runtime_schedule_pairs_directions_lifecycles_and_never_uses_counted_clock():
    config = {'seed': 4, 'measured_rounds': 5}
    rows = list(c._schedule(config, [{'id': 'x', 'plugins': ['zstd', 'alp-auto']}]))
    assert len(rows) == 2 * 2 * 2 * 2 * 7
    assert rows == list(c._schedule(config, [{'id': 'x', 'plugins': ['zstd', 'alp-auto']}]))
    for a, b in zip(rows[0::2], rows[1::2], strict=True):
        assert {a['arm'], b['arm']} == set(c.ARMS)
        assert all(a[k] == b[k] for k in a.keys() - {'arm', 'slot'})
        assert (a['mode'] == 'counted') == (a['phase'] == 'counted')


def test_size_policy_rejects_unsupported_codec_and_does_not_invent_cache_regime():
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / c.CONFIG).read_text())
    canonical = {'object_id': 'v'}
    entries = {name: {'rows': rows, 'canonical': canonical, 'file': {}, 'value_count': width} for name, rows, width in
               [('etth1', 17420, 7), ('ettm2', 69680, 7), ('ld2011', 35039, 370)]}
    env = {'cache_topology': [{'kind': 'Unified', 'level': k, 'bytes': n} for k, n in [(2, 2 << 20), (3, 20 << 20)]]}
    cases = {x['id']: x for x in c._geometry(config, entries, env)}
    assert [cases['alp-' + k + '-vector']['count'] for k in ('before', 'at', 'after')] == [1023, 1024, 1025]
    assert cases['raw-llc-size']['logical_bytes'] > 20 << 20 and cases['raw-llc-size']['dtype'] == 2
    wrong = deepcopy(config)
    next(x for x in wrong['cases'] if x['id'] == 'ett-after-64k')['plugins'].append('zstd')
    with pytest.raises(ContractError, match='batch ABI rejection'):
        c._geometry(wrong, entries, env)
    env['cache_topology'][1]['bytes'] = 32 << 20
    with pytest.raises(ContractError, match='does not exceed'):
        c._geometry(config, entries, env)


def test_signed_difference_is_paired_not_difference_of_marginal_medians():
    def row(round_id, arm, ns):
        return {'round': round_id, 'arm': arm, 'process': {'process_wall_ns': ns},
                'native': {s: {'wall_ns': ns} for s in c.STAGES}}
    rows = [row(i, arm, n) for i, vals in enumerate([(1, 9), (10, 5), (100, 60)], 1) for arm, n in zip(c.ARMS, vals)]
    stats = c._pair_summary({('a', 'zstd', 'cold', 'encode', 'measured'): rows})['a/zstd/cold/encode']['measured']['result_ready']
    assert stats['paired_framework_minus_direct_ns'] == {'n_independent_pairs': 3, 'min': -40, 'median': -5, 'max': 8}
    with pytest.raises(ContractError, match='unpaired'):
        c._pair_summary({('a', 'zstd', 'cold', 'encode', 'measured'): rows[:-1]})
