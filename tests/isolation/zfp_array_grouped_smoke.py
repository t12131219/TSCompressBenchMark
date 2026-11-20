"""Run all three grouped array operations on a passing and a rejected real file."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application import m3_zfp_array_timing as z
from tsbench.assets import ContractError, load_json, require
from tsbench.recovery import stage_recovery

EXPECTED = {'etth1': 'verified', 'bitcoin-dataset-without-missing-values-1': 'quality_rejected'}


def smoke(path):
    plan = load_json(path)
    z._identity(plan,'plan_content_id')
    require(plan['policy'] == z.POLICY and plan['launchers'] == z.launcher_lock(), 'ZFP array smoke contract differs')
    for ref in plan['code']:
        z._file(ROOT,ref)
    entries = z._entry_map(ROOT,load_json(z._file(ROOT, plan['definition'])))
    cases = [c for c in plan['cases'] if c['dataset_id'] in EXPECTED]
    require({c['dataset_id']:c['status'] for c in cases} == EXPECTED,'array smoke must include both quality outcomes')
    proof = {}
    with z.resource.reserve(), z._affinity([plan['environment']['cpu']]), TemporaryDirectory(prefix='tsbench-zfp-array-smoke-') as tmp:
        run = Path(tmp)
        stage_recovery(ROOT,run,plan['runtime'],directory='runtime')
        sessions = set()
        for c in cases:
            ds = c['dataset_id']
            with TemporaryDirectory(prefix='reference-',dir=run) as ref:
                source,setup = z._prepare(ROOT,run,plan,c,entries[ds],Path(ref))
                for slot in z._schedule(c):
                    if slot['repeat']:
                        break
                    row,artifacts = z._trial(ROOT,run,plan,c,entries[ds],source,setup,slot)
                    z._check_trial(run,c,setup,slot,row,sessions)
                    require(all(p.is_file() for p in artifacts.values()), 'array smoke output absent')
                proof[ds] = {'status':c['status'], 'windows':len(c['units']), 'rejected_windows':c['rejected_windows'],
                             'quality_by_state': {k: v['quality']['rejected_windows'] for k,v in setup['recovery'].items()}}
        require(len(sessions) == 6, 'array smoke did not exercise all six operations')
    return {'files':proof, 'verified_diagnostic_operations':len(sessions), 'timing_admitted':False}


if __name__ == '__main__':
    try:
        print(json.dumps(smoke(Path(sys.argv[1])),sort_keys=True))
    except (ContractError, OSError) as exc:
        sys.exit(str(exc))
