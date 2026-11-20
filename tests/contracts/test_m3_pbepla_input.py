import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

import pytest

from tsbench.application.m3_pbepla import staged_windows
from tsbench.assets import ContractError, load_json
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_pbepla import windows
from tsbench.planner.pbepla_execution import PROGRESSIVE, REPLAY

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def frozen():
    plan_path = ROOT/'results/m3-real-r24-20261119/plan.json'
    if not plan_path.is_file():
        pytest.skip('M3 real-corpus plan not present')
    plan = load_json(plan_path)
    definition = load_json(ROOT/plan['definition']['plan']['path'])
    manifest = load_full_manifest(ROOT, definition['bindings']['manifest'], parse=False)
    entries = {r['id']: r for r in manifest['datasets']}
    rows = {(r['dataset_id'],r['route']): r for r in plan['work_items'] if r['selection'] == 87}
    return entries, rows


def test_all_paired_windows_close_frozen_denominator(frozen):
    entries, rows = frozen
    totals = Counter()
    for name, entry in entries.items():
        geometry = windows(entry, rows[name,PROGRESSIVE], rows[name,REPLAY])
        totals.update(files=1, windows=len(geometry), values=sum(w.rows for w in geometry))
    assert totals['files'] == 23 and totals['windows'] == 20524
    from copy import deepcopy
    name = next(iter(entries))
    replay = deepcopy(rows[name,REPLAY]); replay['input']['pbepla_contract']['replay']['online_input'] = True
    with pytest.raises(ContractError, match='frozen window geometry'):
        windows(entries[name], rows[name,PROGRESSIVE], replay)


def test_single_pass_source_matches_prior_two_input_probe_as_bytes(frozen, tmp_path):
    entries, rows = frozen
    proof = json.loads((ROOT/'results/m0-pbepla-real-corpus-probe-20261119-r2/plan.json').read_text())
    for slot in [r for r in proof['slots'] if r['method'] == PROGRESSIVE]:
        spec = slot['spec']; source = spec['source']; name = source['dataset']
        work = tmp_path/name
        work.mkdir()
        with staged_windows(ROOT, entries[name], rows[name,PROGRESSIVE], rows[name,REPLAY], work) as units:
            sample, raw = next((w,b) for w,b in units if (w.column,w.ordinal) ==
                               (source['canonical_value_column'],source['window_ordinal']))
            assert [sample.start,sample.end] == source['absolute_row_range']
            assert sha256(raw).hexdigest() == spec['input_sha256']
