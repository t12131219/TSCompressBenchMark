#!/usr/bin/env python3
"""Stage the verified native PBEP derivative for the standard M3 entry point."""
from argparse import ArgumentParser
from pathlib import Path
from shutil import copyfile, copymode

from m3_pbepla_candidate_corpus import PRODUCTS, ROOT, SCHEMA, checked, ref, signed
from tsbench.application.m3_pbepla_grouped_timing import TOOL as GROUPED_TOOL
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, require, verify_asset
from tsbench.planner.m3_gorilla_specialized import load_repair
from tsbench.planner.pbepla_execution import PLUG, TARGETS, DEFAULT_METHOD
from tsbench.recovery import plan_recovery
from tsbench.runtime import resolve_worker

BUILD_SCHEMA = 'bmk.m3-pbepla-entry-repair/1'
CORPUS_CONTROL = 'tsbench_pbepla_corpus_control'


def candidate_source(source_file, candidate_run):
    seal_file = local_file(candidate_run, 'completion.json')
    seal = load_json(seal_file)
    signed(seal, 'seal_id')
    require(seal['schema'] == SCHEMA+'-seal' and seal['run_id'] == candidate_run.name and set(seal['files']) == set(PRODUCTS),
            'expected a sealed full candidate run')
    for name, asset in seal['files'].items():
        require(checked(asset) == local_file(candidate_run, name), 'foreign candidate run file')
    plan = load_json(candidate_run/'plan.json')
    report = load_json(candidate_run/'report.json')
    signed(plan, 'plan_id')
    totals = report['totals']
    require(plan['schema'] == SCHEMA+'-plan' and report['schema'] == SCHEMA+'-report' and
            seal['plan_id'] == report['plan_id'] == plan['plan_id'] and report['run_id'] == candidate_run.name and
            plan['dataset_projection'] is report['dataset_projection'] is None and len(plan['datasets']) == 23 and
            plan['windows'] == totals['verified_windows'] == totals['windows'] == 20524 and
            all(totals[name+':verified'] == 20524 for name in ('pbepla-progressive', 'pbepla-replay')) and
            totals['baseline_native_failed_now_verified'] == 3 and totals['compatibility:legacy_rejected_v2'] == 9 and
            totals['compatibility:legacy_v1_frame_and_restore_unchanged'] == 61563 and
            all(report[k] is False for k in ('timing_admitted', 'stage_accepted', 'qualification_granted')),
            'candidate evidence does not close the full two-route population')
    lock_file = checked(plan['build'])
    lock = load_json(lock_file)
    signed(lock, 'build_id')
    require(checked(lock['source_plan']) == source_file, 'candidate refers to a different base M3 plan')
    profile = load_json(checked(lock['candidate']))
    signed(profile, 'candidate_id')
    require(profile['selection'] == 87 and profile['contract']['absolute_error_comparison'] ==
            'binary64_exact_boundary_for_native_batch_and_replay', 'expected the exact-bound PBEPLA repair')
    return lock_file, lock, seal_file


def stage(source_file, candidate_run, output):
    source = load_json(source_file)
    signed(source, 'plan_content_id')
    lock_file, lock, seal_file = candidate_source(source_file, candidate_run)
    base_file = checked(source['build']['lock'])
    base = load_json(base_file)
    binding = resolve_worker(ROOT, base, PLUG, DEFAULT_METHOD['options'])
    require(source['build']['build_id'] == base['build_id'] and len(binding['dependencies']) == 1 and
            checked(lock['libraries']['legacy']) == binding['dependencies'][0], 'PBEPLA base dependency differs')
    old_dir = binding['library'].parent
    corpus = checked(source['build']['pbepla_corpus']['executable'])
    decoder = source['specialized']['pbepla']['decoder']
    tools = decoder['tools']
    require(corpus == old_dir/CORPUS_CONTROL and set(tools) == set(TARGETS), 'unexpected PBEPLA control set')
    candidate_closure = lock['closures']['candidate']
    grouped = candidate_closure['files'][candidate_closure['tools'][GROUPED_TOOL]]
    grouped_control = checked({'path':grouped['source'],'bytes':grouped['bytes'],'sha256':grouped['sha256']})
    artifacts = {p.name: p for p in (binding['library'], checked(lock['libraries']['candidate']))}
    artifacts[CORPUS_CONTROL] = grouped_control
    for label, name in TARGETS.items():
        item = decoder['files'][tools[label]]
        tool = checked({'path':item['source'], 'bytes':item['bytes'], 'sha256':item['sha256']})
        require(tool == old_dir/name, 'specialized PBEPLA control is not the original public ABI harness')
        artifacts[name] = tool
    require(output.is_relative_to(ROOT/'build') and output != old_dir, 'repair must use a separate build directory')
    output.mkdir(parents=True, exist_ok=False)
    modules = output/'pbepla-rr'; modules.mkdir()
    for name, src in artifacts.items():
        copyfile(src, modules/name)
        copymode(src, modules/name)
        require(ref(modules/name)['sha256'] == ref(src)['sha256'], 'staged PBEPLA file changed')
    def identity(path):
        return {k:v for k,v in ref(path).items() if k!='bytes'}
    plugin = {**base['plugins'][PLUG], 'library':identity(modules/binding['library'].name),
              'dependencies':[identity(modules/'libtba_native.so')]}
    body = {**{k:v for k,v in base.items() if k!='build_id'}, 'plugins':{**base['plugins'], PLUG:plugin}}
    new = {**body,'build_id':content_id(body)}
    new_tools = {label:identity(modules/name) for label,name in {**TARGETS,'pbepla-corpus':CORPUS_CONTROL}.items()}
    closure = plan_recovery(ROOT, new, {PLUG:DEFAULT_METHOD}, tools=new_tools)
    require(all('libtba_native.so' in closure['files'][rel]['needed'] for rel in closure['tools'].values()) and
            closure['files']['lib/libtba_native.so']['sha256'] == lock['libraries']['candidate']['sha256'],
            'PBEPLA worker and controls must use the same native derivative')
    # The Gorilla derivative stays byte-identical; only reissue its parent-build reference.
    gorilla_ref = source['build']['gorilla_state_repair']['lock']
    gorilla = load_repair(ROOT, base, gorilla_ref['path'])['repair_build']
    new_gorilla = {**{k:v for k,v in gorilla.items() if k!='repair_build_id'}, 'base_build_id':new['build_id']}
    write_new(output/'gorilla-repair-lock.json', {**new_gorilla,'repair_build_id':content_id(new_gorilla)})
    load_repair(ROOT, new, (output/'gorilla-repair-lock.json').relative_to(ROOT).as_posix())
    write_new(output/'build-lock.json', new)
    trace = {'schema':BUILD_SCHEMA, 'base_plan':ref(source_file), 'base_build':ref(base_file),
             'build':ref(output/'build-lock.json'), 'build_id':new['build_id'], 'candidate_build':ref(lock_file),
             'candidate_profile':lock['candidate'], 'candidate_corpus_seal':ref(seal_file),
             'original_corpus_control':ref(corpus),'verified_grouped_control':ref(grouped_control),
             'gorilla_old_lock':gorilla_ref, 'gorilla_new_lock':ref(output/'gorilla-repair-lock.json'),
             'closure':closure, 'candidate_version_scope':'pbepla-rr_only', 'stage_accepted':False, 'timing_admitted':False}
    write_new(output/'pbepla-repair-provenance.json', {**trace,'provenance_id':content_id(trace)})


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__)
    for name in ('source-plan', 'candidate-run', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    try:
        stage(a.source_plan.resolve(strict=True), a.candidate_run.resolve(strict=True), a.out.resolve())
    except (ValueError, OSError) as exc:
        p.exit(1,f'{exc}\n')
