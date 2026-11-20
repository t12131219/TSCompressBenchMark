#!/usr/bin/env python3
"""Build an unregistered C11 CORAD development candidate and lock its closures."""
from argparse import ArgumentParser
from pathlib import Path
import subprocess

from m3_corad_sparse_development import ROOT, SCHEMA as BASE, TOOL, check, ref, seal
from prepare_plugin_source import prepare
from tsbench.application.m3_corad_guard_corpus import _seal
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.recovery import plan_recovery
from tsbench.supervisor.isolated_worker import launcher_lock

SCHEMA = 'bmk.corad-exact-basis-build/1'
SPEC = 'catalog/selections/corad-exact-basis-candidate-v1.json'
FLAGS = ['-O3','-DNDEBUG','-fno-fast-math','-ffp-contract=off']


def controller(text):
    # Retain the frozen development controller's extents and I/O protocol;
    # only change the encoder to take the train-derived column bitmask.
    for old,new in (
        ('uint16_t budget) {\n    uint8_t model_blob','uint16_t exact_columns) {\n    uint8_t model_blob'),
        ('corad_model_config(model, rows, budget, 0.9','corad_model_config(model, rows, 4, 0.9'),
        ('    if (rc == CORAD_OK && (cfg.rows != rows || cfg.columns != cols || corad_bound(&cfg) > sizeof(frame))) {',
         '''    if (rc == CORAD_OK) {
        corad_config wire = cfg;
        if (exact_columns) wire.atoms += 4;
        if (!corad_bound(&wire) || corad_bound(&wire) > sizeof(frame)) rc = CORAD_CAPACITY;
    }
    if (rc == CORAD_OK && (cfg.rows != rows || cfg.columns != cols)) {'''),
        ('corad_model_encode(model, &cfg, values, frame, sizeof(frame), &used)',
         'corad_model_encode_exact_basis(model, &cfg, values, exact_columns, frame, sizeof(frame), &used)'),
        ('dimension(argv[6], 2, 4)','dimension(argv[6], 0, (1u << MAX_COLUMNS) - 1)')):
        require(text.count(old)==1,'unexpected CORAD controller source')
        text = text.replace(old,new)
    return text


def apply_patch(directory, patch):
    with patch.open('rb') as f:
        subprocess.run(['/usr/bin/patch','--batch','--fuzz=0','--no-backup-if-mismatch','-p1'],
                       cwd=directory,stdin=f,check=True)


def build(development, output):
    require(output.is_relative_to(ROOT/'build'),'CORAD candidate output must be in project build')
    plan = load_json(local_file(development,'plan.json'))
    completion = local_file(development,'completion.json')
    require(plan['dataset_projection'] is None and seal(development,plan)==load_json(completion),
            'CORAD exact basis requires sealed full development provenance')
    base = load_json(check(ROOT,plan['build']))
    require(base['schema']==BASE+'-build' and base['build_id']==content_id({k:v for k,v in base.items() if k!='build_id'})
            and base['candidate_guard']==plan['source_guard'] and base['launchers']==launcher_lock(),
            'CORAD candidate base build changed')
    guard_run = check(ROOT,plan['source_guard']).parent
    guard_plan = load_json(local_file(guard_run,'plan.json'))
    require(load_json(local_file(guard_run,'completion.json'))==_seal(guard_run,guard_plan),'CORAD guard seal changed')
    guard_build = load_json(check(ROOT,guard_plan['build_lock']))
    spec_path = local_file(ROOT,SPEC)
    spec = load_json(spec_path)
    require(spec['candidate_id']==content_id({k:v for k,v in spec.items() if k!='candidate_id'}),'invalid exact basis identity')
    guard_path = verify_asset(ROOT,spec['guard'])
    require(ref(ROOT,guard_path)==guard_build['candidate'],'candidate does not extend the actual guard source')
    guard = load_json(guard_path)
    require(guard['source_id']==spec['source_id'] and guard['patch']==guard_build['patch'],'candidate guard patch differs')
    output.mkdir(parents=True,exist_ok=False)
    prepared = output/'source'
    prepare(spec['source_id'],prepared)
    source = prepared/spec['source_id']
    manifest = load_json(verify_asset(ROOT,load_json(local_file(ROOT,'third_party/sources.lock.json'))['sources'][spec['source_id']]['source_manifest']))
    expected = {m['path']:m['sha256'] for m in manifest['files']}
    require(expected[guard['member']]==guard['before_sha256'],'unexpected source archive for guard patch')
    apply_patch(source,verify_asset(ROOT,guard['patch']))
    expected[guard['member']] = guard['after_sha256']
    for name,identity in spec['members'].items():
        key = f'{spec["source_id"]}/{name}'
        require(expected[key]==digest(local_file(source,name))==identity['before_sha256'], 'unexpected source for exact basis patch')
        expected[key] = identity['after_sha256']
    apply_patch(source,verify_asset(ROOT,spec['patch']))
    require({p.relative_to(prepared).as_posix():digest(p) for p in prepared.rglob('*') if p.is_file()}==expected,
            'candidate changed unplanned source files')
    cc = '/usr/bin/cc'
    library = output/'libcorad_c.so'
    subprocess.run([cc,'-std=gnu11',*FLAGS,'-fPIC','-shared','-Wl,--no-undefined,-soname,libcorad_c.so',
                    '-I',str(source/'include'),*(str(source/'src'/p) for p in ('model.c','codec.c','corad_c.c','training.c')),
                    '-lm','-o',str(library)],check=True)
    derived = output/'corad_exact_basis_control.c'
    derived.write_text(controller(check(ROOT,base['derived']).read_text()))
    executable = output/'corad_exact_basis_control'
    subprocess.run([cc,'-std=c11','-O2','-fno-fast-math','-ffp-contract=off','-Wall','-Wextra','-Werror',
                    '-I',str(source/'include'),str(derived),str(library),'-Wl,-rpath,$ORIGIN','-o',str(executable)],check=True)
    def elf(p):
        return {k:v for k,v in ref(ROOT,p).items() if k!='bytes'}
    encode = plan_recovery(ROOT,{},(),tools={TOOL:elf(executable)},libraries=[elf(library)])
    restore = base['restore']
    require(encode['files']['lib/libcorad_c.so']['sha256']!=restore['files']['lib/libcorad_c.so']['sha256'],
            'candidate did not preserve a separate original decoder closure')
    body = {'schema':SCHEMA,'candidate':ref(ROOT,spec_path),'source_development':ref(ROOT,completion),
            'base_build':plan['build'],'base_guard':plan['source_guard'],'sources':expected,
            'controller':ref(ROOT,derived),'builder':ref(ROOT,Path(__file__).resolve()),'compile_flags':FLAGS,
            'compiler':subprocess.check_output([cc,'--version'],text=True).splitlines()[0],
            'encode':encode,'restore':restore,'launchers':launcher_lock(),
            'qualification_granted':False,'timing_admitted':False,'stage_accepted':False}
    lock = output/'build-lock.json'
    write_new(lock,{**body,'build_id':content_id(body)})
    print(lock)


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    p.add_argument('--development',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    try:
        build(a.development.resolve(strict=True),a.out.resolve())
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        p.exit(1,f'{exc}\n')
