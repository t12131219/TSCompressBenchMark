from copy import deepcopy
from pathlib import Path
import struct

import pytest

from tsbench.assets import ContractError, load_json
from tsbench.corpus_ingress import CorpusBatch, MANIFEST
from tsbench.planner import corad_corpus_execution as baseline
from tsbench.planner import m3_corad_ingress as m3
from tsbench.planner.corad_corpus import plan_cohorts
from tsbench.planner.native_corpus import POLICY

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    entry = {'id': 'synthetic', 'value_count': 4, 'columns': ['time', 'a', 'b', 'c', 'd'],
             'axis_observations': {'decreases': 0}, 'canonical': {'object_id': 'full'},
             'partitions': [{'start': lo, 'end': hi, 'canonical': {'object_id': name}}
                            for lo, hi, name in ((0, 4, 'train'), (4, 5, 'dev'), (5, 10, 'test'))],
             'retained_sentinel_values': 1, 'parser': {'missing': 'retain_source_minus_9999'}}
    values = [[-0.0 if r == 0 and c == 1 else -9999.0 if (r, c) == (7, 2) else r*4+c+0.25
               for c in range(4)] for r in range(10)]
    layout = {'max_columns': 2, 'train_rows': 3, 'tricklet': 2, 'max_test_rows_per_frame': 3, 'max_values_per_frame': 6}
    cohorts = plan_cohorts(entry, layout, {2: [(7, 8)]})
    assert [c['state'] for c in cohorts] == ['eligible', 'eligible']

    def batches(*_):
        for lo, hi in ((0, 1), (1, 6), (6, 8), (8, 10)):
            yield CorpusBatch(lo, hi-lo, b''.join(struct.pack('<q', r) for r in range(lo, hi)),
                              b''.join(struct.pack('<4d', *row) for row in values[lo:hi]))
    return entry, layout, cohorts, batches


def test_reads_once_without_changing_training_or_heldout_bytes(monkeypatch):
    entry, layout, cohorts, batches = fixture()
    count = 0

    def once(*args):
        nonlocal count
        count += 1
        yield from batches(*args)

    monkeypatch.setattr(m3, 'read_batches', once)
    monkeypatch.setattr(baseline, 'read_batches', batches)
    actual = m3.bind_cohorts(ROOT, entry, cohorts, layout)
    expected = [baseline.bind_cohort(ROOT, entry, c, layout) for c in cohorts]
    assert actual == expected and count == 1
    assert actual[0][1][3*8:4*8] == struct.pack('<d', -0.0)
    assert [r['absolute_rows'] for r in actual[1][0]['test_frames']] == [[5, 7], [8, 10]]


def test_rejects_included_sentinel_and_overlapping_columns(monkeypatch):
    entry, layout, cohorts, batches = fixture()
    monkeypatch.setattr(m3, 'read_batches', batches)
    with pytest.raises(ContractError, match='overlap or are unordered'):
        m3.bind_cohorts(ROOT, entry, list(reversed(cohorts)), layout)
    bad = deepcopy(cohorts)
    bad[1]['test']['eligible_row_spans'] = [[5, 10]]
    with pytest.raises(ContractError, match='retained missing value'):
        m3.bind_cohorts(ROOT, entry, bad, layout)


def test_matches_prior_real_cohort_probe():
    probe = ROOT / 'results/m0-corad-real-corpus-20261119-r1/run/plan.json'
    if not probe.is_file():
        pytest.skip('requires local r6 CORAD probe bindings')
    layout = next(r['corad_layout'] for r in load_json(ROOT / POLICY)['routes'] if r['route'] == 'corad-inference')
    entries = {e['id']: e for e in load_json(ROOT / MANIFEST)['datasets']}
    for expected in load_json(probe)['bindings']:
        entry = entries[expected['source']]
        cohort = next(c for c in plan_cohorts(entry, layout, {}) if c['cohort_id'] == expected['cohort_id'])
        (bound, _, _), = m3.bind_cohorts(ROOT, entry, [cohort], layout)
        assert bound == expected
