"""Real Bubblewrap smoke for two ZFP files plus isolated full/tail observation."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_zfp_field_timing as z
from tsbench.assets import ContractError, load_json, require
from tsbench.recovery import stage_recovery

FILES = {'etth1', 'dominick-dataset-1121'}


def smoke(plan_path):
    plan = load_json(plan_path)
    z._identity(plan, 'plan_content_id')
    require(plan['policy'] == z.POLICY and plan['launchers'] == z.launcher_lock(), 'ZFP smoke contract differs')
    for ref in plan['code']:
        z._file(ROOT, ref)
    cases = [c for c in plan['cases'] if c['dataset_id'] in FILES]
    require({c['dataset_id'] for c in cases} == FILES and any(c['rows'] % 4 for c in cases), 'ZFP smoke needs a tail field')
    entries = z._entry_map(ROOT, load_json(z._file(ROOT, plan['definition'])))
    cpus = [ref['cpu'] for ref in plan['environment']]
    exercised = {}
    with z.resource.reserve(), z._affinity(cpus), TemporaryDirectory(prefix='tsbench-zfp-field-smoke-') as temp:
        run = Path(temp)
        stage_recovery(ROOT, run, plan['runtime'], directory='runtime')
        timed, observed = set(), set()
        for c in cases:
            entry = entries[c['dataset_id']]
            setup = z._prepare(ROOT, run, plan, c, entry)
            for lane in z.OBSERVED:
                for op in z.DIRECTIONS:
                    z._check(run, c, setup, setup['observations'][f'{lane}-{op}'], 'observer', observed, lane=lane, op=op)
            for slot in z._schedule(c):
                if slot['repeat']:
                    break
                row, product = z._trial(ROOT, run, plan, c, entry, setup, slot)
                z._check(run, c, setup, row, 'timing', timed, slot=slot)
                require(product.is_file(), 'ZFP smoke lost a verified product')
            exercised[c['dataset_id']] = {'rows': c['rows'], 'columns': c['columns'], 'omp2_encode_threads_per_column':
                setup['observations']['openmp-omp2-encode']['native']['whole_columns_by_participating_threads']}
        require(not timed.intersection(observed) and len(timed) == 20 and len(observed) == 12,
                'ZFP smoke did not cover distinct timing/observer processes')
    return {'files': exercised, 'verified_direction_operations': len(timed), 'separate_block_observations': len(observed),
            'timing_admitted': False}


if __name__ == '__main__':
    try:
        print(json.dumps(smoke(Path(sys.argv[1])), sort_keys=True))
    except (ContractError, OSError) as exc:
        sys.exit(str(exc))
