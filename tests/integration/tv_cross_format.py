"""Verify actual cross-format native TV products, not just parser hashes."""
from pathlib import Path
import shutil
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))

from tsbench.api import plan_tv, report_tv
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json, require
from tsbench.planner.tv import load_case
from tsbench.planner.recipe import plan_recipe


def main(root, run, build_lock, cli_plan):
    plan = load_json(run/'plan.json')
    binding = plan.get('recipe_binding')
    expected = (plan_recipe(root,build_lock,binding['path']) if binding else plan_tv(root,build_lock,plan['suite_path']))
    require(expected==load_json(cli_plan)==plan,'CLI and Python plans differ')
    report = report_tv(run)
    require(report['statuses']=={'verified':12} and report['verified'] and not report['qualification_granted'],
            'unexpected cross-format terminals')
    setup = report['ingress_setup']['cases']
    require(len(setup)==6 and all(entry['wall_ns']>0 for entry in setup.values()), 'source setup not observed separately')
    eq = report['format_equivalence']
    require(eq['logical_dataset_weights']==2,'format replicas must not add logical weight')
    old = load_json(root/'configs/suites/dev_tv_limb_comparison_v1/suite.json')
    old_name = {'traffic-tail':'traffic-five-value-tail','exact-bits-tail':'five-value-edge-bits'}
    rows = {(r['case'],r['method']):r for r in report['slots']}
    cmp = report['comparisons']['fixed-t-direct-vs-limbs']
    audit = {}
    sessions = set()
    for group, facts in eq['groups'].items():
        original, packed = load_case(root,old,old['cases'][old_name[group]])
        require(facts['logical_weight']==1 and facts['logical_bytes']==24720 and len(facts['methods'])==2,'wrong group weights')
        copies = [v['case'] for v in facts['formats'].values()]
        require(all(cmp[n]==cmp[copies[0]] for n in copies),'source labels leaked into codec comparison identity')
        for case in copies:
            info, parsed = load_case(root,plan['suite'],plan['suite']['cases'][case])
            require(info==plan['cases'][case] and parsed==packed and
                    info['original_timestamp_sha256']==original['original_timestamp_sha256'], 'fixture differs from its source object')
            direct = rows[case,'gorilla-t-alp-f64']
            grouped = rows[case,'gorilla-t-fire-u16']
            for row in (direct,grouped):
                sessions.update(o['session_id'] for o in row['operations'])
                require(row['restored']['canonical_dataset_hash']==facts['canonical_dataset_hash'],'typed restoration differs')
            require(direct['restored']==grouped['restored'], 'method changed restored object')
            streams = grouped['accounting']['streams']
            require([(s['row'],s['rows'],s['column_count']) for s in streams]==[(0,512,1),(0,512,5),(512,3,1),(512,3,5)],
                    'did not exercise aligned 512+3 blocks')
            require(streams[1]['packed_value']['packed_blocks']>0 and streams[3]['packed_value']['literal_values']==60,
                    'FIRE body and literal tail not both exercised')
            require([s['sha256'] for s in streams if s['first_column']==0]==
                    [s['sha256'] for s in direct['accounting']['streams'] if s['first_column']==0], 'fixed T differs')
        for method in facts['methods']:
            bundles = [(run/rows[c,method]['artifact']['path']).read_bytes() for c in copies]
            require(bundles[0]==bundles[1]==bundles[2],'bundle bytes depend on source format')
        audit[group] = {'source_object_matches':True,'distinct_format_files':3,'same_bundle_per_method':True,'fixed_t_matches':True}
    require(len(sessions)==24, 'development operations were reused across slots')
    with tempfile.TemporaryDirectory(prefix='ingress-reseal-') as tmp:
        copy = Path(tmp)/'run'
        shutil.copytree(run,copy)
        setup_file = copy/'ingress-setup.json'
        doc = load_json(setup_file)
        next(iter(doc['cases'].values()))['ingestion_id'] = '0'*64
        setup_file.write_bytes(canonical_bytes(doc)+b'\n')
        seal_file = copy/'completion.json'
        seal = load_json(seal_file)
        [ref] = [entry for entry in seal['files'] if entry['path']=='ingress-setup.json']
        ref.update(bytes=setup_file.stat().st_size,sha256=digest(setup_file))
        seal['seal_id'] = content_id({k:v for k,v in seal.items() if k!='seal_id'})
        seal_file.write_bytes(canonical_bytes(seal)+b'\n')
        try:
            report_tv(copy)
        except ContractError as exc:
            require('unbound ingress setup observation' in str(exc), f'wrong rejection: {exc}')
        else:
            raise AssertionError('report accepted misbound ingress setup after resealing')
    recipe_audit = {}
    if binding:
        require(report['recipe_binding_id']==binding['recipe_binding_id'],'report lost recipe identity')
        with tempfile.TemporaryDirectory(prefix='recipe-reseal-') as tmp:
            copy = Path(tmp)/'run'
            shutil.copytree(run,copy)
            path = copy/'plan.json'
            changed = load_json(path)
            forged = changed['recipe_binding']
            forged['methods']['gorilla-t-fire-u16']['codec_routes']['v-codec'] = '0'*64
            forged['recipe_binding_id'] = content_id({k:v for k,v in forged.items() if k!='recipe_binding_id'})
            changed['plan_content_id'] = content_id({k:v for k,v in changed.items() if k!='plan_content_id'})
            path.write_bytes(canonical_bytes(changed)+b'\n')
            seal_file = copy/'completion.json'
            seal = load_json(seal_file)
            [ref] = [entry for entry in seal['files'] if entry['path']=='plan.json']
            ref.update(bytes=path.stat().st_size,sha256=digest(path))
            seal['plan_content_id'] = changed['plan_content_id']
            seal['seal_id'] = content_id({k:v for k,v in seal.items() if k!='seal_id'})
            seal_file.write_bytes(canonical_bytes(seal)+b'\n')
            try:
                report_tv(copy)
            except ContractError as exc:
                require('sealed recipe binding differs from TV lowering' in str(exc),f'wrong recipe rejection: {exc}')
            else:
                raise AssertionError('report accepted misbound recipe after resealing')
        recipe_audit = {'recipe_binding_id':binding['recipe_binding_id'],'resealed_wrong_codec_route_rejected':True}
    return {'schema':'bmk.dev-tv-ingress-controls/1','run_id':report['run_id'],'seal_id':report['seal_id'],
            'groups':audit,'distinct_operation_sessions':len(sessions),'setup_outside_worker_clock_cases':len(setup),
            'resealed_misbound_setup_rejected':True,**recipe_audit,'cli_api_parity':True,'qualification_granted':False}


if __name__=='__main__':
    _, root, run, lock, cli = sys.argv
    sys.stdout.buffer.write(canonical_bytes(main(Path(root).resolve(strict=True),Path(run).resolve(strict=True),lock,Path(cli)))+b'\n')
