#!/usr/bin/env python3
"""Compose a wire-compatible CORAD guard with the previously checked PBEPLA repair."""
from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2

from stage_m3_pbepla_repair import ROOT, checked, ref, signed
from tsbench.application.m3_corad_guard_corpus import _seal
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, require, verify_asset
from tsbench.planner.m3_gorilla_specialized import load_repair
from tsbench.planner.pbepla_execution import DEFAULT_METHOD
from tsbench.recovery import plan_recovery

METHOD = 'corad-frozen'


def _rebind(lock, name, plugin):
    body = {**{k:v for k,v in lock.items() if k!='build_id'}, 'plugins':{**lock['plugins'],name:plugin}}
    return {**body,'build_id':content_id(body)}


def identity(path):
    return {k:v for k,v in ref(path).items() if k!='bytes'}


def stage(source_file, corpus_run, output):
    src = load_json(source_file)
    signed(src,'plan_content_id')
    current_file = checked(src['build']['lock']); current=load_json(current_file)
    pbepla = load_json(checked(src['build']['pbepla_repair']['provenance']))
    signed(pbepla,'provenance_id')
    original_file = checked(pbepla['base_build']); original=load_json(original_file)
    require(pbepla['build']==ref(current_file) and
            all(current['plugins'][k]==v for k,v in original['plugins'].items() if k!='pbepla-rr'),
            'CORAD guard staging expects the original plus only the PBEP repair')
    corpus = load_json(local_file(corpus_run,'plan.json'))
    seal_file = local_file(corpus_run,'completion.json')
    require(_seal(corpus_run,corpus)==load_json(seal_file) and corpus['dataset_projection'] is None and
            corpus['frame_count']==1174 and len(corpus['cases'])==13 and corpus['source_plan']==pbepla['base_plan'],
            'CORAD guard did not verify the complete original population')
    guard_file = checked(corpus['build_lock']); guard=load_json(guard_file)
    signed(guard,'build_id')
    profile=load_json(checked(guard['candidate'])); signed(profile,'candidate_id')
    lib,=original['plugins'][METHOD]['dependencies']
    selected = checked(guard['guard']['library'])
    require(guard['base_build_id']==original['build_id'] and guard['base_dependency']==lib and
            corpus['closures']['candidate']['files']['lib/libcorad_c.so']['sha256']==ref(selected)['sha256'],
            'guard library was not used by the sealed candidate run')
    require(output.is_relative_to(ROOT/'build'),'CORAD guard derivative escaped build root')
    modules = output/'corad-frozen'; modules.mkdir(parents=True,exist_ok=False)
    baseline = verify_asset(ROOT,original['plugins'][METHOD]['library']); copy2(baseline,modules/baseline.name)
    copy2(selected,modules/selected.name)
    binaries = {}
    for area in (src['build']['corad_corpus'],src['specialized']['corad']):
        closure=area['decoder']
        for name,rel in closure['tools'].items():
            item=closure['files'][rel]
            tool=checked({'path':item['source'],'sha256':item['sha256'],'bytes':item['bytes']})
            copy2(tool,modules/tool.name)
            binaries[name]=identity(modules/tool.name)
    plugin={**original['plugins'][METHOD],'library':identity(modules/baseline.name),'dependencies':[identity(modules/selected.name)]}
    independent=_rebind(original,METHOD,plugin); new=_rebind(current,METHOD,plugin)
    require(independent['worker']==new['worker'],'derivative changed the worker')
    closure=plan_recovery(ROOT,new,[METHOD],tools=binaries)
    require(closure['files']['lib/libcorad_c.so']['sha256']==guard['guard']['library']['sha256'] and
            all('libcorad_c.so' in closure['files'][t]['needed'] for t in closure['tools'].values()),'CORAD tools did not bind the chosen guard')
    base_lock, new_lock = output/'corad-only-base-lock.json',output/'build-lock.json'
    write_new(base_lock,independent); write_new(new_lock,new)
    gorilla=load_repair(ROOT,current,src['build']['gorilla_state_repair']['lock']['path'])['repair_build']
    g={**{k:v for k,v in gorilla.items() if k!='repair_build_id'},'base_build_id':new['build_id']}
    g_path=output/'gorilla-repair-lock.json'; write_new(g_path,{**g,'repair_build_id':content_id(g)})
    load_repair(ROOT,new,ref(g_path)['path'])
    old_tools=pbepla['closure']['tools']; fs=pbepla['closure']['files']
    pb={**{k:v for k,v in pbepla.items() if k!='provenance_id'}, 'base_build':ref(base_lock),'build':ref(new_lock),
        'build_id':new['build_id'],'gorilla_new_lock':ref(g_path),
        'closure':plan_recovery(ROOT,new,{'pbepla-rr':DEFAULT_METHOD},tools={k:{'path':fs[v]['source'],'sha256':fs[v]['sha256']}
                                                                             for k,v in old_tools.items()})}
    write_new(output/'pbepla-repair-provenance.json',{**pb,'provenance_id':content_id(pb)})
    body={'schema':'bmk.m3-corad-entry-guard/1','base_build':ref(current_file),'build':ref(new_lock),
          'candidate_build':ref(guard_file),'candidate_profile':guard['candidate'],'candidate_run':ref(seal_file),
          'closure':closure,'implementation':'corad-c11-unique-v1+tsbench-reference-error-guard-v1',
          'wire':'CRD1','training_or_quality_gate_changed':False,'timing_admitted':False,'stage_accepted':False}
    write_new(output/'corad-repair-provenance.json',{**body,'provenance_id':content_id(body)})


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    for name in ('source-plan','corpus-run','out'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    try:
        stage(a.source_plan.resolve(strict=True),a.corpus_run.resolve(strict=True),a.out.resolve())
    except (OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
