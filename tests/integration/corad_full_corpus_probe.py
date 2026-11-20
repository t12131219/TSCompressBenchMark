"""Exercise the same-run CORAD training and held-out products on r6 corpus cohorts."""
import argparse
from copy import deepcopy
from pathlib import Path

from tsbench.application.corad_corpus_execution import TOOL, LIMITS, SOURCE_LIMITS, execute_cohort, summarize, verify_cohort_ledger
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json, parse_json, require
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.corad_corpus_execution import bind_cohort
from tsbench.planner.corad_training import plan_corad_training
from tsbench.planner.corad_training_execution import bridge_bytes, source_runtime
from tsbench.planner.native_corpus import verify_native_corpus_plan
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.runtime import create_build_lock

ROOT = Path(__file__).resolve().parents[2]


def _write(path, data):
    with path.open('xb') as f:
        f.write(canonical_bytes(data)+b'\n')


def _materialize(definition, keys=None, *, bindings=None):
    corpus = load_full_manifest(ROOT,definition['bindings']['manifest'])
    by_dataset = {e['id']:e for e in corpus['datasets']}
    decisions = {d['dataset_id']:d for d in definition['decisions'] if d['route']=='corad-inference' and
                 d['state']=='input_domain_matches'}
    if bindings is not None:
        keys = [f'{b["source"]}:' + str(next(i for i,c in enumerate(decisions[b['source']]['input']['corad_contract']['cohorts'])
                   if c['cohort_id']==b['cohort_id'])) for b in bindings]
    require(0 < len(keys) <= 8, 'bounded development probe accepts at most eight cohorts')
    lanes = []
    for key in keys:
        dataset, ordinal = key.split(':')
        require(ordinal.isascii() and ordinal.isdigit(), 'invalid CORAD cohort ordinal')
        d = decisions[dataset]['input']['corad_contract']
        lanes.append(bind_cohort(ROOT,by_dataset[dataset],d['cohorts'][int(ordinal)],d['layout']))
    return lanes


def _report(out, plan, lanes, *, negatives=None):
    rows = [parse_json(line,'CORAD cohort ledger') for line in (out/'ledger.jsonl').read_text().splitlines()]
    required = 2*sum(1+len(b['test_frames']) for b in plan['bindings'])
    require(len(rows)==required,'CORAD cohort ledger is incomplete')
    cursor = 0
    for b, train, test in lanes:
        end = cursor+2*(1+len(test))
        group = rows[cursor:end]
        verify_cohort_ledger(out,b,train,test,group)
        if negatives is not None and not negatives:
            for label in ('false_quality_verified','substitute_other_trainer_model','mount_source_for_restore'):
                forged = deepcopy(group)
                if label=='false_quality_verified':
                    forged[1]['status'] = 'verified' if group[1]['status']=='quality_rejected' else 'quality_rejected'
                elif label=='substitute_other_trainer_model':
                    forged[1]['deployment_id'] = group[len(test)+1]['deployment']['deployment_id']
                else:
                    forged[1]['processes']['restore-0']['input_mounts']['original'] = b['test_frames'][0]['values']
                try:
                    verify_cohort_ledger(out,b,train,test,forged)
                except ContractError as exc:
                    negatives[label] = str(exc)
                else:
                    raise ContractError(f'CORAD verifier accepted {label}')
        cursor = end
    require(cursor==len(rows), 'CORAD ledger has unconsumed terminal rows')
    return {'plan_content_id':plan['plan_content_id'], 'terminal_rows':required,
            'summary':summarize(rows), 'ledger_recomputed':True, 'stage_accepted':False, 'qualification_granted':False}, rows


def run(args, definition):
    require(args.build and args.input and args.out, 'CORAD execution requires build, input and output')
    lanes = _materialize(definition,args.input)
    bindings = [lane[0] for lane in lanes]
    require(len({b['input_binding_id'] for b in bindings})==len(bindings), 'duplicate CORAD input cohort')
    plugin = f'{args.build}/plugins/codecs/corad-frozen'
    binary = f'{plugin}/tsbench_corad_corpus_control'
    build = create_build_lock(ROOT,args.build+'/tsbench_cpu_worker',{'corad-frozen':f'{plugin}/libbmk_corad_frozen.so'})
    runtime = plan_recovery(ROOT,build,{'corad-frozen':{}},tools={TOOL:{'path':binary,'sha256':digest(ROOT/binary)}})
    source, _ = plan_corad_training(ROOT)
    source_env = source_runtime(ROOT,source)
    bridge = bridge_bytes(ROOT,source)
    plan = {'scope':'r6_cohort_probe_not_acceptance', 'corpus_plan_content_id':definition['plan_content_id'],
            'bindings':bindings,'build':build,'decoder':runtime,'source_runtime':source_env,
            'source_bridge_sha256':source['bridge_sha256'],'native_limits':LIMITS,'source_limits':SOURCE_LIMITS,
            'code':{k:digest(ROOT/k) for k in ('plugins/codecs/corad-frozen/corpus_control.c',
                     'src/tsbench/planner/corad_corpus_execution.py','src/tsbench/application/corad_corpus_execution.py',
                     'src/tsbench/qualification/corad_wire.py','tests/integration/corad_full_corpus_probe.py')},
            'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    plan['plan_content_id'] = content_id(plan)
    out = args.out.resolve()
    out.mkdir(parents=True)
    stage_recovery(ROOT,out,plan['decoder'])
    _write(out/'plan.json',plan)
    with (out/'ledger.jsonl').open('xb') as ledger:
        for binding, train, tests in lanes:
            for row in execute_cohort(out,plan,binding,train,tests,bridge):
                ledger.write(canonical_bytes(row)+b'\n')
                ledger.flush()
    report, rows = _report(out,plan,lanes)
    _write(out/'report.json',report)
    require(all(r['status'] in ('verified','quality_rejected') for r in rows), 'CORAD cohort execution nonpass')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition',type=Path,required=True)
    parser.add_argument('--build')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--input',action='append',metavar='DATASET:COHORT_ORDINAL')
    parser.add_argument('--recompute',type=Path,help='existing CORAD probe run directory')
    args = parser.parse_args()
    definition = load_json(args.definition)
    verify_native_corpus_plan(ROOT,definition)
    if args.recompute is None:
        run(args,definition)
    else:
        require(args.build is None and args.input is None, 'recomputation cannot override existing inputs/build')
        plan = load_json(args.recompute/'plan.json')
        require(plan['corpus_plan_content_id']==definition['plan_content_id'] and
                plan['plan_content_id']==content_id({k:v for k,v in plan.items() if k!='plan_content_id'}),
                'CORAD recomputation plan identity differs')
        materials = _materialize(definition,bindings=plan['bindings'])
        require([b for b,_,_ in materials]==plan['bindings'], 'CORAD recomputation bindings changed')
        negatives = {}
        report, _ = _report(args.recompute,plan,materials,negatives=negatives)
        original = args.recompute/'report.json'
        require(canonical_bytes(report)+b'\n'==original.read_bytes(), 'CORAD recomputed report bytes differ')
        _write(args.out,{'report_byte_identical':True,'report_sha256':digest(original),'negative_controls':negatives,
                         'native_calls':False,'plan_content_id':plan['plan_content_id']})
