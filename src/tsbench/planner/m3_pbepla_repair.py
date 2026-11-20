"""Bind the explicit exact-bound PBEPLA derivative without touching legacy plans."""
from ..assets import content_id, digest, load_json, local_file, require, verify_asset
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock

IMPLEMENTATION = 'pbepla-rr-unique-v1+tsbench-wide-exact-v1'
TOOL = 'pbepla-corpus'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 30}
CODE = ('src/tsbench/qualification/pbep_wide.py', 'src/tsbench/planner/m3_pbepla_repair.py',
        'src/tsbench/application/m3_pbepla_repair.py', 'src/tsbench/application/m3_real_corpus_execution_v2.py',
        'src/tsbench/supervisor/isolated_worker.py',
        'src/tsbench/supervisor/process.py', 'src/tsbench/recovery.py')


def _ref(root,path):
    p = local_file(root,path)
    return {'path':path, 'bytes':p.stat().st_size, 'sha256':digest(p)}


def bind(root, path, build_file, build, corpus):
    ref = _ref(root,path)
    proof = load_json(verify_asset(root,ref))
    require(corpus and proof['schema']=='bmk.m3-pbepla-entry-repair/1' and
            proof['provenance_id']==content_id({k:v for k,v in proof.items() if k!='provenance_id'}) and
            proof['build']==_ref(root,build_file) and proof['build_id']==build['build_id'] and
            proof['build_id']==content_id({k:v for k,v in build.items() if k!='build_id'}) and
            proof['candidate_version_scope']=='pbepla-rr_only' and
            proof['stage_accepted'] is proof['timing_admitted'] is False, 'PBEPLA repair provenance differs')
    original = load_json(verify_asset(root,proof['base_build']))
    require(build['worker']==original['worker'] and
            {k:v for k,v in build['plugins'].items() if k!='pbepla-rr'}==
            {k:v for k,v in original['plugins'].items() if k!='pbepla-rr'}, 'PBEPLA repair changed an unrelated plugin')
    candidate = load_json(verify_asset(root,proof['candidate_build']))
    profile = load_json(verify_asset(root,proof['candidate_profile']))
    tested = candidate['closures']['candidate']
    grouped = tested['files'][tested['tools']['pbepla-grouped']]
    require(candidate['candidate']==proof['candidate_profile'] and profile['selection']==87 and
            profile['contract']['absolute_error_comparison']=='binary64_exact_boundary_for_native_batch_and_replay' and
            candidate['libraries']['candidate']['sha256']==corpus['dependency']['sha256'] and
            proof['closure']['files']['lib/libtba_native.so']['sha256']==corpus['dependency']['sha256'] and
            proof['verified_grouped_control']=={'path':grouped['source'],'sha256':grouped['sha256'],'bytes':grouped['bytes']} and
            all(proof['verified_grouped_control'][k]==corpus['executable'][k] for k in ('bytes','sha256')),
            'PBEPLA repair selected an unrelated native library')
    verify_asset(root,proof['candidate_corpus_seal'])
    tools = {TOOL:{k:corpus['executable'][k] for k in ('path','sha256')}}
    libraries = [{k:corpus['dependency'][k] for k in ('path','sha256')}]
    decoder = plan_recovery(root,{},(),tools=tools,libraries=libraries)
    require('libtba_native.so' in decoder['files'][decoder['tools'][TOOL]]['needed'], 'PBEPLA native library not linked')
    return {'provenance':ref, 'implementation':IMPLEMENTATION, 'decoder':decoder, 'launchers':launcher_lock(),
            'limits':dict(LIMITS), 'code':{n:digest(local_file(root,n)) for n in CODE}}
