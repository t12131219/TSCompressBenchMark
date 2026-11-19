"""Cross-check one unified execution and reject re-signed plan/binding edits."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import plan_batch_execution, report_batch_execution
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.batch_execution import check_batch_execution
from tsbench.planner.linear_batch import ACCESS_SUITES, STREAM_SUITES, INTMULT_SUITES, GORILLA_STATE_SUITES, LZBENCH_SESSION_SUITES, LZBENCH_PROFILE_SUITES, ALP_DECODE_SUITES, ZFP_NATIVE_SUITES, PBEPLA_NATIVE_SUITES, CORAD_INFERENCE_SUITES, CORAD_TRAINING_SUITES, ENTROPY_SUITES, ORDERED_SUITES, SPRINTZ_SUITES
from tsbench.planner import huff0_execution as hf
from tsbench.planner import huff0_bmi2 as bmi2
from tsbench.planner import selfstar_execution as ss
from tsbench.planner import sprintz_execution as sp
from tsbench.planner import titchy_execution as ta
from tsbench.planner import titchy_stream as ts
from tsbench.planner import pcodec_intmult as im
from tsbench.planner import gorilla_state as gs
from tsbench.planner import lzbench_session as ls
from tsbench.planner import lzbench_profiles as lp
from tsbench.planner import alp_decode as ad
from tsbench.planner import zfp_execution as zf
from tsbench.planner import pbepla_execution as pb
from tsbench.planner import corad_execution as cr
from tsbench.planner import corad_training_execution as ct
from tsbench.application.corad_training_execution import execution_labels
from tsbench.application.smoke import _rows


def rejected(plan, mutate, reason):
    copy = deepcopy(plan)
    mutate(copy)
    copy['plan_content_id'] = content_id({k:v for k,v in copy.items() if k!='plan_content_id'})
    try:
        check_batch_execution(copy)
    except ContractError as exc:
        require(reason in str(exc), f'unexpected rejection: {exc}')
        return str(exc)
    raise AssertionError('modified binding passed after resealing')


def main(root, run, plan_path=None):
    plan = load_json(run/'plan.json')
    tool = {name:ref['path'] for name,ref in plan['direct_control']['tool_refs'].items()}
    from tsbench.planner import batch_binding as b
    kwargs = {'direct_control':tool[b.ZSTD_TOOL],'fenv_control':tool[b.FENV_TOOL],'titchy_control':tool[b.TITCHY_TOOL],
              'xz_control':tool[b.XZ_TOOL],'pcodec_control':tool[b.PCO_TOOL], 'wrapped_driver':tool[b.WRAPPED_TOOL],
              'gorilla_control':tool[b.DIRECT_TOOL]}
    entropy = plan['suite'] in ENTROPY_SUITES
    reader = plan['suite'] in ACCESS_SUITES
    stream = plan['suite'] in STREAM_SUITES
    multiples = plan['suite'] in INTMULT_SUITES
    lifecycle = plan['suite'] in GORILLA_STATE_SUITES
    byte_sessions = plan['suite'] in LZBENCH_SESSION_SUITES
    native_profiles = plan['suite'] in LZBENCH_PROFILE_SUITES
    alp_backends = plan['suite'] in ALP_DECODE_SUITES
    zfp_native = plan['suite'] in ZFP_NATIVE_SUITES
    pbepla_native = plan['suite'] in PBEPLA_NATIVE_SUITES
    corad = plan['suite'] in CORAD_INFERENCE_SUITES
    training = plan['suite'] in CORAD_TRAINING_SUITES
    compare = plan['suite']==bmi2.SUITE
    if compare:
        kwargs['huff0_portable_build'] = plan[bmi2.KEY]['build_dir']
    if stream:
        kwargs['titchy_stream_control'] = tool[ts.TOOL]
    fire = plan['suite'] in SPRINTZ_SUITES
    if reader:
        kwargs['titchy_access_control'] = tool[ta.TOOL]
    if fire:
        kwargs['sprintz_control'] = tool[sp.TOOL]
    ordered = plan['suite'] in ORDERED_SUITES
    if entropy:
        kwargs['huff0_control'] = tool[hf.TOOL]
    if ordered:
        kwargs['selfstar_control'] = tool[ss.TOOL]
    require(plan_batch_execution(root,plan['build'],suite=plan['suite'],**kwargs)==plan==load_json(plan_path or root/'build/batch-plan.json'),
            'CLI/API execution plan differs')
    report, view = report_batch_execution(run), plan['execution_binding']
    verified, denied, bound = ((174,26,186) if compare else (174,26,185) if training else (172,26,174) if corad else (171,26,168) if pbepla_native else (160,24,159) if zfp_native else (154,24,143) if alp_backends else (145,24,137) if native_profiles else (142,24,124) if byte_sessions else (140,24,114) if lifecycle else (136,24,106) if multiples else (133,21,102) if stream else (132,21,96) if reader else (130,21,85) if fire else (112,19,75) if entropy else
                               (103,17,64) if ordered else (85,10,55))
    require(report['terminal_counts']=={'verified':verified,'expected_rejection':denied} and
            report['all_candidate_required_obligations_evidenced' if alp_backends else 'all_candidate_obligations_evidenced'] is (not corad) and
            len(view['bound_obligations'])==bound and
            len(view['unbound_obligations'])==186-bound and not report['qualification_granted'], 'unexpected unified coverage')
    by_method = {}
    cross = []
    session_ids = set()
    stateful = {}
    tables, fec, sprintz_batch, queries, access_slots = [], [], [], [], []
    for slot,row in zip(plan['slots'],_rows(run/'ledger.jsonl'),strict=True):
        sid, method = slot['product_slot'],slot['method']
        by_method.setdefault(method,[]).append(sid)
        expected = ([o['label'] for o in view['drivers'][sid]['operations']] if not ct.is_training(slot) else
                    execution_labels(slot,{k:(run/r['path']).read_bytes() for k,r in row['parts'].items()}))
        require(sid==row['product_slot'] and expected==[o['operation'] for o in row['operations']],
                'executed sequence differs from binding')
        for op in row['operations']:
            require(op['session_id'] not in session_ids, 'reused execution session')
            session_ids.add(op['session_id'])
        if ss.is_selfstar(slot):
            body = view['drivers'][sid]
            if row['status']=='verified':
                stateful.setdefault(method,[]).append(row)
                carried_state = row['selfstar_validation'].get('state')
                require(f'tool/{ss.TOOL}' in body['primary_restore_programs'] and
                        bool(carried_state)==(slot['count']>512),'SElf* restore/state binding differs')
                require((f'abi/{ss.PLUGIN}' in body['primary_restore_programs'])==(method==ss.PLUGIN), 'SElf* direct live mounted the batch ABI')
        elif hf.is_huff0(slot) and row['status']=='verified':
            d = view['drivers'][sid]
            v = row['huff0_validation']
            portable = [f'tool/{bmi2.TOOL}'] if compare else []
            if method==hf.SHARED:
                tables.append((slot,row))
                require(d['primary_restore_programs']==[f'tool/{hf.TOOL}']+portable and
                        v['model_and_blocks_and_binding_bytes']==sum(r['bytes'] for r in row['parts'].values()) and
                        v['alternate_control_bytes']==row['controls']['alternate']['bytes'] and
                        v['alternate_rejected_by_model_binding'], 'ETB1 closure, model identity or ledger differs')
            else:
                fec.append((slot,row))
                require(d['primary_restore_programs']==[f'tool/{hf.TOOL}',f'abi/{hf.PLUGIN}']+portable and
                        v['envelope_bytes']+v['schema_bytes']+v['fec_bytes']==row['parts']['frame']['bytes'], 'FEC1 closure or ledger differs')
        elif sp.is_sprintz(slot):
            if row['status']=='verified':
                v = row['sprintz_validation']
                bundle = view['drivers'][sid]['primary_restore_programs']
                require(bundle==[f'tool/{sp.TOOL}']+([f'abi/{sp.PLUGIN}'] if slot['abi'] else []),
                        'Sprintz recovery accidentally mounted the ABI')
                if method==sp.QUERY:
                    queries.append((slot,row))
                    op, = [o for o in row['operations'] if o['operation']=='sfb1-query']
                    require(op['input_mounts']=={'input':{k:row['parts']['frame'][k] for k in ('sha256','bytes')}} and
                            v['query'] and row['parts']['reductions']['bytes']>0,'Sprintz query inputs or result not sealed')
                else:
                    sprintz_batch.append((slot,row))
        elif ta.is_access(slot):
            if row['status']=='verified':
                access_slots.append((slot,row))
                d = view['drivers'][sid]
                require(d['primary_restore_programs']==[f'tool/{ta.TOOL}'] and d['process_limits']['file_bytes']==ta.FILE_LIMIT,
                        'Titchy access restore closure or file limit differs')
        elif ts.is_stream(slot):
            d = view['drivers'][sid]
            require(d['primary_restore_programs']==[f'tool/{ts.TOOL}'] and d['process_limits']['file_bytes']==ts.FILE_LIMIT,
                    'Titchy stream restore closure or file limit differs')
        elif im.is_intmult(slot):
            d = view['drivers'][sid]
            require(d['primary_restore_programs']==([] if slot['expected_status'] else [f'tool/{im.TOOL}']) and
                    d['process_limits']['file_bytes']==im.FILE_LIMIT and (row['status']=='verified')==bool(slot['parts']),
                    'pcodec IntMult restore closure, terminal or file limit differs')
        elif gs.is_state(slot):
            d = view['drivers'][sid]
            require(row['status']=='verified' and d['process_limits']['file_bytes']==gs.CAP and
                    d['primary_restore_programs']==[f'tool/{b.DIRECT_TOOL}',f'tool/{gs.TOOL}'],
                    'Gorilla lifecycle restore closure or file limit differs')
        elif ls.is_session(slot):
            d = view['drivers'][sid]
            require(row['status']=='verified' and d['primary_restore_programs']==[f'tool/{ls.TOOL}'] and
                    set(row['parts'])==set(ls.PARTS),'lzbench session restore closure differs')
        elif lp.is_profile(slot):
            d = view['drivers'][sid]
            require(row['status']=='verified' and d['primary_restore_programs']==[f'tool/{lp.TOOL}']+
                    ([f'tool/{lp.SYNC}'] if method==lp.XZ else []), 'lzbench profile restore closure differs')
        elif ad.is_decode(slot):
            d = view['drivers'][sid]
            require(row['status']=='verified' and d['primary_restore_programs']==[f'tool/{ad.TOOL}'] and
                    d['configuration']['decode_inputs']==['frame'],'ALP detached restore closure differs')
        elif ct.is_training(slot):
            d=view['drivers'][sid]
            require(row['training']['deployment_overwritten'] is False and d['configuration']['steps']==ct.steps(slot) and
                    d['primary_restore_programs']==[f'tool/{ct.TOOL}'] and
                    all(set(x['input_mounts'])=={'frame'} for x in row['operations'] if x['operation'].startswith('restore-')),
                    'CORAD trained model artifact-only restoration differs')
            if method==ct.SOURCE:
                require(all({ct.STAGED_BRIDGE,ct.VECTORS}==set(x['input_mounts']) for x in row['operations'] if x['operation'].startswith('train-')),
                        'CORAD Source received nontraining input')
        elif cr.is_corad(slot):
            d = view['drivers'][sid]
            require(d['process_limits']==cr.limit(plan) and d['configuration']['steps']==cr.steps(slot) and
                    d['primary_restore_programs']==['abi/corad-frozen'],'CORAD scope or mounts differ')
            require(row['corad']['functional_restoration'] and not row['corad']['quality_comparable'] and
                    {x['decision'] for x in row['corad']['quality_gate']['heldout'].values()}=={'quality_rejected'} and
                    {k for k,v in report['obligation_evidence'].items() if v['state']=='quality_rejected'}==
                    {f'80/corad-inference/{cr.QUALITY_CHECK}'}, 'CORAD recovery must not admit a rejected model')
        elif pb.is_pbepla(slot):
            d = view['drivers'][sid]
            require(d['process_limits']==pb.limit(slot,plan['limits']) and
                    d['configuration']['steps']==pb.steps(slot),'PBEPLA process limits or mounts differ')
            for op in d['operations']:
                if op['label'].startswith('restore-'):
                    require(op['program']=='abi/pbepla-rr' and
                            set(d['configuration']['steps'][op['label']]['mounts'])=={'frame'},
                            'PBEPLA prefix recovery must not mount the original')
        elif zf.is_zfp(slot):
            d = view['drivers'][sid]
            require(row['status']=='verified' and d['primary_restore_programs']==[f'tool/{zf.TOOL}'],
                    'ZFP fresh restore must use the native tool only')
        elif 'protocol' in slot and not hf.is_huff0(slot):
            require(view['drivers'][sid]['primary_restore_programs']==[f'tool/{b.WRAPPED_TOOL}'], 'page restore uses the wrong tool')
        if method=='gorilla-tv':
            require(view['drivers'][sid]['process_limits']['file_bytes']==16384,'lost the Gorilla file limit')
            if row.get('cross_restored'):
                cross.append(sid)
                require(view['drivers'][sid]['primary_restore_programs']==['abi/gorilla-tv',f'tool/{b.DIRECT_TOOL}'],
                        'Gorilla cross closure is missing')
        elif method=='xz-baseline':
            require(view['drivers'][sid]['process_limits']['address_space_bytes']==268435456,'lost the XZ address limit')
    require(len(cross)==6 and set(cross)==set(plan['obligation_bindings']['7/tv-batch/native_payload_cross_decode']['product_slots']),
            'Gorilla cross-decode coverage differs')
    gorilla_case = next(iter(view['bound_obligations'][plan['obligation_bindings']['7/tv-batch/native_payload_cross_decode']['obligation_id']]['cases']))
    def alias(p): p['case_products'][gorilla_case]['product_slots'] = by_method['pcodec-source-auto'][:1]
    def lose_condition(p):
        admission = p['admission_definition']
        admission['obligations'].remove(next(o for o in admission['obligations'] if o['kind']=='conditional'))
        admission['plan_content_id'] = content_id({k:v for k,v in admission.items() if k!='plan_content_id'})
        p['admission_plan_id'] = admission['plan_content_id']
    def omit_cross_slot(p): p['obligation_bindings']['7/tv-batch/native_payload_cross_decode']['product_slots'].pop()
    rejections = {
        'wrong_case_route':rejected(plan,alias,'case product belongs to another route'),
        'drop_conditional':rejected(plan,lose_condition,'incomplete binding partition'),
        'omit_cross_slot':rejected(plan,omit_cross_slot,'obligation binding differs'),
        'misstate_per_slot_limit':rejected(plan,lambda p:p['execution_binding']['drivers'][cross[0]]['process_limits'].update(file_bytes=1048576), 'execution binding changed'),
        'omit_native_dependency':rejected(plan,lambda p:p['execution_binding']['programs'][f'tool/{b.DIRECT_TOOL}']['mount_files'].remove('lib/libgorilla_c.so'), 'execution binding changed'),
    }
    if ordered:
        require({m:len(slots) for m,slots in stateful.items()}=={ss.PLUGIN:9,ss.LIVE:9} and
                all(a['artifact']['sha256']==b['artifact']['sha256'] for a,b in zip(stateful[ss.PLUGIN],stateful[ss.LIVE],strict=True)),
                'SElf* independent batch and live executions must match')
        live_slot = stateful[ss.LIVE][0]['product_slot']
        rejections['replace_live_driver_with_batch'] = rejected(plan,lambda p:p['execution_binding']['drivers'][live_slot]['operations'][0].update(program=f'abi/{ss.PLUGIN}'),'execution binding changed')
    if entropy:
        require(len(fec)==5 and len(tables)==4 and sum(len(slot['blocks']) for slot,_ in tables)==14,
                'Huff0 route coverage differs')
        sid = tables[0][0]['product_slot']
        rejections['replace_table_driver_with_abi'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][0].update(program=f'abi/{hf.PLUGIN}'),'execution binding changed')
        rejections['omit_model_binding_byte_budget'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['artifact_byte_ceilings'].pop('binding'),'execution binding changed')
    if fire:
        require(len(sprintz_batch)==len(queries)==9 and sum(s['abi'] for s,_ in sprintz_batch)==4 and
                {s['name']:r['sprintz_validation']['native_frame']['sha256'] for s,r in queries}==
                {s['name']:r['sprintz_validation']['native_frame']['sha256'] for s,r in sprintz_batch},
                'Sprintz separate batch and query source equivalence differs')
        width_slot, = (s for s,_ in queries if s['name']=='u16-wide-sum')
        require(width_slot['oracle']['sum'][0]>2**32-1 and len(set(width_slot['oracle']['count']))>1,
                'missing wide unsigned accumulation or partial-tail case')
        sid = width_slot['product_slot']
        rejections['query_as_abi_decode'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][1].update(program=f'abi/{sp.PLUGIN}'),'execution binding changed')
        rejections['drop_query_result_cap'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['artifact_byte_ceilings'].pop('reductions'),'execution binding changed')
    if reader:
        require(len(access_slots)==2 and access_slots[0][1]['parts']['backing']['sha256']==access_slots[1][1]['parts']['backing']['sha256'],
                'independent Titchy backings differ')
        loaded, = [r for s,r in access_slots if s['method']==ta.LOADED]
        stateless, = [r for s,r in access_slots if s['method']==ta.RANGE]
        require(loaded['titchy_access']['pair_mutation_sha256']==stateless['titchy_access']['pair_mutation_sha256'] and
                stateless['titchy_access']['read_at_bytes'] is None, 'one split mutation must distinguish the access protocols')
        sid = loaded['product_slot']
        rejections['strip_titchy_access_limit'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration'].pop('callback_limits'),'execution binding changed')
        rejections['use_batch_driver_for_indexed_read'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][1].update(program=f'tool/{ta.TITCHY_TOOL}'),'execution binding changed')
    if stream:
        s, = [s for s in plan['slots'] if ts.is_stream(s)]
        sid = s['product_slot']
        r, = [r for r in _rows(run/'ledger.jsonl') if r['product_slot']==sid]
        v = r['titchy_stream']
        require(v['first_packet_after_samples']==28 and v['pad_zeros']==3 and
                v['all_required_artifact_bytes']==sum(p['bytes'] for p in r['parts'].values()) and
                set(r['operations'][1]['input_mounts'])=={'archive','config'},'Titchy stream lifecycle or closure differs')
        rejections['stream_without_config_charge'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['artifact_byte_ceilings'].pop('config'),'execution binding changed')
        rejections['stream_as_batch_abi'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][1].update(program='abi/titchy-batch'),'execution binding changed')
    if multiples:
        slots = {s['name']:s for s in plan['slots'] if im.is_intmult(s)}
        sid = slots['wide-base']['product_slot']
        require(len(slots)==6 and slots['wide-base']['base']==2**53+1 and
                slots['high-entropy']['wire']=={'mode':0,'base':None},'IntMult fallback or exact uint64 base lost')
        rejections['round_uint64_intmult_base'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration'].update(requested_base=2**53),'execution binding changed')
        rejections['intmult_as_source_auto'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][0].update(program='abi/pcodec-source-auto'),'execution binding changed')
    if lifecycle:
        resume, = [s for s in plan['slots'] if gs.is_state(s) and 'snapshot' in s['parts']]
        iterator = next(s for s in plan['slots'] if gs.is_state(s) and s['method']==gs.ITER)
        sid,rid = resume['product_slot'],iterator['product_slot']
        rejections['skip_gorilla_resume_scan'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'].pop(-1),'execution binding changed')
        rejections['replace_gorilla_iterator_observer'] = rejected(plan,lambda p:p['execution_binding']['drivers'][rid]['operations'][-1].update(program=f'tool/{b.DIRECT_TOOL}'),'execution binding changed')
    if byte_sessions:
        xz, = [s for s in plan['slots'] if ls.is_session(s) and s['method']=='xz-session']
        sid = xz['product_slot']
        rejections['xz_session_drop_native_budget'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['parameters'].pop('memory_limit'),'execution binding changed')
        rejections['substitute_xz_batch_for_session'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][1].update(program='abi/xz-baseline'),'execution binding changed')
    if native_profiles:
        require(report['execution_scope']['bound_required_obligations']==(180 if training else 169 if corad else 163 if pbepla_native else 154 if zfp_native else 139 if alp_backends else 135) and
                report['execution_scope']['bound_conditional_obligations']==(6 if compare else 5 if zfp_native else 4 if alp_backends else 2),'lzbench condition partition differs')
        dictionary, = [s for s in plan['slots'] if lp.is_profile(s) and s['method']==lp.DICT]
        sid = dictionary['product_slot']
        rejections['omit_dictionary_charge'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['artifact_byte_ceilings'].pop('trained.zdict'),'execution binding changed')
        xz_profile, = [s for s in plan['slots'] if lp.is_profile(s) and s['method']==lp.XZ]
        sid = xz_profile['product_slot']
        rejections['replace_xz_caller_sync_with_mt'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['steps']['decode-sync-shared'].update(tool=lp.TOOL),'execution binding changed')
    if alp_backends:
        mixed, = [s for s in plan['slots'] if ad.is_decode(s) and s['fixture']['name']=='f64-mixed-decimal-raw']
        sid = mixed['product_slot']
        rejections['alp_decode_mount_original'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['decode_inputs'].append('raw'),'execution binding changed')
        rejections['alp_decode_drop_avx512_request'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['requests'].remove('falp-avx512bw'),'execution binding changed')
    if zfp_native:
        omp, = [s for s in plan['slots'] if zf.is_zfp(s) and s['method']==zf.OMP]
        sid = omp['product_slot']
        rejections['zfp_decode_with_original'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['steps']['restore-2']['mounts'].update(input='input'),'execution binding changed')
        rejections['zfp_replace_observer_with_serial_driver'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['operations'][2].update(program=f'tool/{zf.TOOL}'),'execution binding changed')
    if pbepla_native:
        prefix = next(s for s in plan['slots'] if pb.is_pbepla(s) and s['variant']=='prefixes')
        sid = prefix['product_slot']
        rejections['pbepla_decode_with_original'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['steps']['restore-1']['mounts'].update(input='input'),'execution binding changed')
    if corad:
        target, = [s for s in plan['slots'] if cr.is_corad(s)]
        sid = target['product_slot']
        rejections['corad_restore_with_calibration'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['steps']['restore-0']['inputs'].append('calibration'),'execution binding changed')
    if training:
        src, = [s for s in plan['slots'] if ct.is_training(s) and s['method']==ct.SOURCE]
        sid=src['product_slot']
        rejections['corad_source_fit_with_heldout'] = rejected(plan,lambda p:p['execution_binding']['drivers'][sid]['configuration']['steps']['train-source-sklearn']['inputs'].append('heldout'),'execution binding changed')
    if compare:
        sid = fec[0][0]['product_slot']
        def replace_decoder(p):
            slot = next(o for o in p['execution_binding']['drivers'][sid]['operations'] if o['label']==bmi2.OPERATION)
            slot['program'] = f'tool/{hf.TOOL}'
        rejections['huff0_primary_substituted_for_portable'] = rejected(plan,replace_decoder,'execution binding changed')
    counts = Counter(x['reason'] for x in view['unbound_obligations'].values())
    result = {'schema':'bmk.unified-batch-controls/1','run_id':report['run_id'],'seal_id':report['seal_id'],
            'cli_api_parity':True,'distinct_operation_sessions':len(session_ids),'gorilla_bidirectional_products':len(cross),
            'unbound_reasons':dict(counts), 'selfstar_products':sum(map(len,stateful.values())),'rejections':rejections,'qualification_granted':False}
    if entropy:
        result['huff0_fec1_products'] = len(fec)
        result['huff0_etb1_profiles'] = len(tables)
        result['huff0_etb1_blocks'] = sum(len(s['blocks']) for s,_ in tables)
    if fire:
        result['sprintz_batch_products'] = len(sprintz_batch)
        result['sprintz_query_products'] = len(queries)
        result['sprintz_query_backend_counts'] = dict(Counter(r['sprintz_validation']['query']['auto']['backend'] for _,r in queries))
    if reader:
        result['titchy_access_products'] = len(access_slots)
        result['titchy_shared_corruption_case'] = True
    if stream:
        result['titchy_stream_products'] = 1
    if multiples:
        result['pcodec_intmult_products'] = 3
        result['pcodec_intmult_expected_rejections'] = 3
    if lifecycle:
        result['gorilla_state_products'] = 4
    if byte_sessions:
        result['lzbench_sessions'] = 2
    if native_profiles:
        result['lzbench_native_profiles'] = 3
    return result


if __name__=='__main__':
    submitted_plan = Path(sys.argv[3]) if len(sys.argv)==4 else None
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True),Path(sys.argv[2]).resolve(strict=True),submitted_plan))+b'\n')
