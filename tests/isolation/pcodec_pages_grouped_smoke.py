"""Exercise both grouped pcodec lanes with files-only isolation on ETTh1.

This checks real frozen work and does not publish trial measurements or a receipt.
"""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_pcodec_grouped_timing as g
from tsbench.assets import ContractError, load_json, require
from tsbench.recovery import stage_recovery


def smoke(plan_file):
    plan = load_json(plan_file)
    g._identity(plan, 'plan_content_id')
    require(plan['policy'] == g.POLICY and plan['launchers'] == g.launcher_lock(), 'pcodec smoke contract differs')
    for ref in plan['code']:
        g._file(ROOT, ref)
    c, = (x for x in plan['cases'] if x['dataset_id'] == 'etth1')
    entry = g._entry_map(ROOT, load_json(g._file(ROOT, plan['definition'])))['etth1']
    with g.resource.reserve(), g._affinity([plan['environment']['cpu']]), TemporaryDirectory(prefix='tsbench-pcodec-pgf-smoke-') as temp:
        run = Path(temp)
        stage_recovery(ROOT, run, plan['runtime'], directory='runtime')
        fixed = run / 'cases' / c['case_id'] / 'fixed'
        fixed.mkdir(parents=True)
        raw = g._stage(ROOT, c, entry, run)
        setup = {'raw': g._amounts(raw), 'fixed': {}}
        for lane in g.LANES:
            pgf, proc = g._call(run, plan, c, lane, 'encode', run / lane, raw)
            require(proc['process']['input_mounts'] == {'object': setup['raw']}, 'pcodec smoke used different input')
            proof = g._inspect_frames(c, lane, pgf)
            out = fixed / f'{lane}.pgf'
            pgf.rename(out)
            setup['fixed'][lane] = {'path': out.relative_to(run).as_posix(), **proof}
        sessions = set()
        for item in g._schedule(c):
            if item['repeat']:
                break
            row, product = g._trial(ROOT, run, plan, c, entry, setup, item)
            g._check_trial(run, c, setup, item, row, sessions)
            require(product.is_file(), 'pcodec smoke did not create a product')
    require(len(sessions) == 4, 'pcodec smoke did not test both directions and lanes')
    return {'dataset': 'etth1', 'groups_per_lane': c['group_count'], 'isolated_trial_operations': len(sessions),
            'timing_admitted': False}


if __name__ == '__main__':
    try:
        print(json.dumps(smoke(Path(sys.argv[1])), sort_keys=True))
    except (ContractError, OSError) as exc:
        sys.exit(str(exc))
