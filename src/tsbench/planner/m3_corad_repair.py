"""Bind the frozen CRD1 reference guard as a distinct native implementation."""
from ..assets import content_id, digest, load_json, local_file, require, verify_asset

IMPLEMENTATION = 'corad-c11-unique-v1+tsbench-reference-error-guard-v1'
METHOD = 'corad-frozen'


def _ref(root,relative):
    f = local_file(root,relative)
    return {'path':relative,'sha256':digest(f),'bytes':f.stat().st_size}


def bind(root, path, build_file, build, corpus, specialist):
    ref = _ref(root,path); proof = load_json(local_file(root,path))
    require(corpus and specialist and proof['schema']=='bmk.m3-corad-entry-guard/1' and
            proof['provenance_id']==content_id({k:v for k,v in proof.items() if k!='provenance_id'}) and
            proof['build']==_ref(root,build_file) and proof['implementation']==IMPLEMENTATION and proof['wire']=='CRD1' and
            proof['training_or_quality_gate_changed'] is proof['stage_accepted'] is proof['timing_admitted'] is False,
            'invalid M3 CORAD guard provenance')
    base=load_json(verify_asset(root,proof['base_build']))
    require(build['worker']==base['worker'] and {k:v for k,v in build['plugins'].items() if k!=METHOD}==
            {k:v for k,v in base['plugins'].items() if k!=METHOD},'CORAD guard changed an unrelated plugin')
    candidate=load_json(verify_asset(root,proof['candidate_build'])); profile=load_json(verify_asset(root,proof['candidate_profile']))
    require(candidate['candidate']==proof['candidate_profile'] and profile['selection']==80 and
            candidate['base_dependency']==base['plugins'][METHOD]['dependencies'][0] and
            candidate['guard']['library']['sha256']!=candidate['base_dependency']['sha256'],
            'CORAD guard is not the candidate derived from this original plugin')
    seal=load_json(verify_asset(root,proof['candidate_run']))
    require(seal['seal_id']==content_id({k:v for k,v in seal.items() if k!='seal_id'}), 'CORAD candidate full seal differs')
    lib='lib/libcorad_c.so'; tested=proof['closure']['files'][lib]
    require(tested['sha256']==candidate['guard']['library']['sha256'] and
            all(b['decoder']['files'][lib]==tested and all(proof['closure']['files'][f]==b['decoder']['files'][f]
                       for f in b['decoder']['tools'].values()) for b in (corpus,specialist)),
            'CORAD corpus and specialists are not bound to the exact guard closure')
    return {'provenance':ref,'implementation':IMPLEMENTATION,'wire':'CRD1'}
