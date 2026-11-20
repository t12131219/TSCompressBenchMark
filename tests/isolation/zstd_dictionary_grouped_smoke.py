"""Real file-isolated train/encode/decode under both frozen dictionary tiers."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_zstd_dictionary_timing as d
from tsbench.assets import ContractError, load_json, require
from tsbench.recovery import stage_recovery

FILES = {'etth1', 'dominick-dataset-1121'}


def smoke(plan_file):
    plan = load_json(plan_file)
    d._identity(plan, 'plan_content_id')
    require(plan['policy'] == d.POLICY and plan['launchers'] == d.launcher_lock(), 'dictionary smoke contract differs')
    for ref in plan['code']:
        d._file(ROOT, ref)
    entries = d._entry_map(ROOT, load_json(d._file(ROOT, plan['definition'])))
    cases = [c for c in plan['cases'] if c['dataset_id'] in FILES]
    require({c['dataset_id'] for c in cases} == FILES and {c['training'][0] for c in cases} == {256, 2048},
            'dictionary smoke did not select both verified tiers')
    with d.resource.reserve(), d._affinity([plan['environment']['cpu']]), TemporaryDirectory(prefix='tsbench-zdg-smoke-') as tmp:
        run = Path(tmp)
        stage_recovery(ROOT, run, plan['runtime'], directory='runtime')
        sessions = set()
        for c in cases:
            entry = entries[c['dataset_id']]
            fixed = d._fixed(ROOT, run, plan, c, entry)
            for slot in d._schedule(c):
                if slot['repeat']:
                    break
                row, product = d._trial(ROOT, run, plan, c, entry, fixed, slot)
                d._check_trial(run, c, fixed, slot, row, sessions)
                require(product.is_file(), 'expected isolated dictionary product absent')
    require(len(sessions) == 6, 'dictionary smoke did not verify all operations in both tiers')
    return {'isolated_operations': len(sessions), 'files': sorted(FILES), 'timing_admitted': False}


if __name__ == '__main__':
    try:
        print(json.dumps(smoke(Path(sys.argv[1])), sort_keys=True))
    except (ContractError, OSError) as exc:
        sys.exit(str(exc))
