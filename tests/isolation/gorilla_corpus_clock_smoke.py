"""Check all three Gorilla files-only lanes on the original ETTh1 file.

Run with the tsbench Python and a frozen Gorilla corpus-clock plan.
Uses the same cooperative lock as timing runs and leaves no timing evidence.
"""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_gorilla_corpus_clock as clock
from tsbench.assets import ContractError, load_json, require
from tsbench.recovery import stage_recovery


def smoke(plan_path):
    plan = load_json(plan_path)
    clock._identity(plan, 'plan_content_id')
    require(plan['schema'] == clock.SCHEMA and plan['policy'] == clock.POLICY and
            plan['launchers'] == clock.launcher_lock(), 'Gorilla smoke plan or launcher differs')
    for ref in plan['code']:
        clock._file(ROOT, ref)
    dataset = 'etth1'
    cases = {c['route']: c for c in plan['cases'] if c['dataset_id'] == dataset}
    require(set(cases) == set(clock.ROUTES), 'Gorilla smoke lacks full route coverage')
    entry = clock._entry_map(ROOT, load_json(clock._file(ROOT, plan['definition'])))[dataset]
    seen, sessions = [], set()
    with clock.resource.reserve(), clock._affinity([plan['environment']['cpu']]), \
         TemporaryDirectory(prefix='tsbench-gorilla-corpus-smoke-') as temp:
        run = Path(temp)
        for lane, binding in plan['bindings'].items():
            stage_recovery(ROOT, run, binding['runtime'], directory=f'runtime-{lane}')
        source = run / 'values'
        axis, values, identity = clock.stage(ROOT, entry, source)
        mounts = {p.name: clock._facts(clock._ref(source, p)) for p in (axis, *values)}
        for mode in clock.ROUTES:
            case = cases[mode]
            clock._identity(case, 'case_id')
            require(case['input_identity'] == identity, 'Gorilla smoke canonical TV identity differs')
            case_dir = run / 'cases' / case['case_id']
            case_dir.mkdir(parents=True)
            fixed, refs = clock._stash_anchors(run, plan, case, source, case_dir)
            setup = {'fixed': refs, 'canonical_files': mounts}
            row, products = clock._trial(ROOT, run, plan, case, entry, source, fixed, setup, 0)
            clock._check_trial(run, case, setup, 0, row, sessions)
            seen.append({'route': mode, 'units': case['units'], 'operations': list(clock.CLOCKS[mode]),
                         'durable_outputs': len(products)})
    require(len(sessions) == 7, 'Gorilla smoke lacks expected isolated operation coverage')
    return {'dataset': dataset, 'verified': seen, 'isolated_operations': len(sessions), 'timing_admitted': False}


if __name__ == '__main__':
    import argparse
    import json
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('plan', type=Path)
    try:
        print(json.dumps(smoke(cli.parse_args().plan)))
    except (ContractError, OSError) as exc:
        cli.exit(1, f'{exc}\n')
