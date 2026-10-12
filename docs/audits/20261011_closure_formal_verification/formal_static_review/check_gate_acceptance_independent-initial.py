"""Independent report-only review; never import or execute production/oracle code."""
import collections
import hashlib
import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SUBJECT = ROOT / 'docs/audits/20261011_closure_formal_verification/gate_acceptance_review/acceptance_review_r1.json'


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def read(path):
    return json.loads(Path(path).read_text())


def save(path, doc):
    with Path(path).open('x') as output:
        json.dump(doc, output, indent=2, sort_keys=True, ensure_ascii=False)
        output.write('\n')


def main():
    review = read(SUBJECT)
    checks = []
    def check(key, predicate, details):
        checks.append(dict(check=key, status='PASS' if predicate else 'FAIL', details=details))
    subject_before = ref(SUBJECT)
    standard = ROOT / review['inputs']['standard']['path']
    standard_text = standard.read_text()
    authority = ref(standard)
    check('complete_standard_authority_identity', authority['sha256'] == review['inputs']['standard']['sha256']
          and authority['bytes'] == review['inputs']['standard']['bytes'],
          dict(authority=authority, lines=len(standard_text.splitlines()),
               interpretation='Complete current v3.0 document is the authority. This review checks gate acceptance logic, not core numerical compliance or new codec execution.'))
    scope_path = ROOT / 'registry/algorithm_scope.json'
    scope = read(scope_path)
    plan_path = ROOT / 'build/port-standard-v30-20261011/active33-r2/plan.json'
    plan = read(plan_path)
    entries = review['entries']
    active = set(scope['registered_codecs'])
    excluded = set(scope['retained_out_of_scope_registrations']) | set(scope['framework_oracles'])
    keys = [entry['codec_key'] for entry in entries]
    check('active_scope_independent_denominator', len(keys) == len(set(keys)) == len(active) == 33
          and set(keys) == active == set(plan['active_keys']) and not set(keys) & excluded,
          dict(active_keys=sorted(active), excluded_keys=sorted(excluded), scope=ref(scope_path), plan=ref(plan_path)))
    routes = read(ROOT / review['inputs']['routes']['path'])
    route_map = {entry['codec']: entry for entry in routes['entries']}
    ledger = read(ROOT / review['inputs']['ledger']['path'])
    original_rows = {(entry['codec_key'], row['gate']) for entry in ledger['entries'] for row in entry['gates']}
    rows = [row for entry in entries for row in entry['gates']]
    pairs = [(row['codec_key'], row['gate']) for row in rows]
    rewrite_keys = {entry['codec_key'] for entry in entries if entry['route'] == 'SOURCE_REWRITE'}
    native_keys = {entry['codec_key'] for entry in entries if entry['route'] in {'NATIVE_REUSE','NATIVE_PORT'}}
    expected_rows = {(key, gate) for key in rewrite_keys for gate in ['G0','G1','G2','G3','G4','G5','G6','CAP-GATE']}
    expected_rows |= {(key, gate) for key in native_keys for gate in ['N0','N1','N2','N3','N4','N5']}
    check('unique_complete_gate_denominator', len(rewrite_keys)==11 and len(native_keys)==22
          and len(rows)==len(set(pairs))==220 and set(pairs)==expected_rows==original_rows
          and review['entry_count']==33 and review['applicable_gate_row_count']==220,
          dict(rewrite_entries=len(rewrite_keys), native_entries=len(native_keys), arithmetic='11*8 + 22*6 = 220',
               duplicate_rows=len(pairs)-len(set(pairs)), missing=sorted(expected_rows-set(pairs)), extra=sorted(set(pairs)-expected_rows)))
    check('per_entry_gate_ownership_route_and_nonempty_evidence',
          all(entry['route']==route_map[entry['codec_key']]['implementation_route'] and
              all(row['codec_key']==entry['codec_key'] and row['subitems'] and row['criterion'] and row['status_reason']
                  and all(item['finding'] and item['evidence_keys'] and
                          all(key in review['inputs'] for key in item['evidence_keys']) for item in row['subitems'])
                  for row in entry['gates']) for entry in entries), 'Every original applicable row has an owner, route, criterion, findings and bound input references.')
    counts = dict(collections.Counter(row['status'] for row in rows))
    passes = {(row['codec_key'],row['gate']) for row in rows if row['status']=='PASS'}
    check('status_counts_and_only_three_G0_grants', counts==review['gate_status_counts']=={'PASS':3,'FAIL':32,'UNKNOWN':185}
          and passes=={('abba','G0'),('fabba','G0'),('deepzip','G0')}
          and all(row['status'] in {'PASS','FAIL','UNKNOWN','N/A'} and row['complete_acceptance_granted']==(row['status']=='PASS') for row in rows),
          dict(status_counts=counts, exact_pass_rows=sorted(passes)))
    identities=[]
    for codec, implementation in [('abba','abba-canonical-cpp'),('fabba','fabba-canonical-cpp'),('deepzip','deepzip-cpp')]:
        path=ROOT/review['inputs'][codec+'_manifest']['path']
        manifest=yaml.safe_load(path.read_text())
        identity=review['G0_current_logical_identity_reviews'][codec]
        expected=dict(algorithm_id=codec, implementation_id=implementation, object_level='P2_PIPELINE')
        evidence=manifest['gates']['G0'].get('evidence','')
        source=manifest['source']
        identities.append(dict(codec_key=codec, expected=expected,
                               actual={key:manifest.get(key) for key in expected},
                               source=dict(repository=source.get('repository'),commit=source.get('commit')),
                               current_G0_evidence=evidence, manifest=ref(path)))
        check('G0_real_identity_mapping_'+codec, all(manifest.get(key)==identity.get(key)==value for key,value in expected.items())
              and not implementation.startswith('v2:') and re.fullmatch('[a-z0-9-]+',implementation) is not None
              and source.get('repository','').startswith('https://github.com/')
              and re.fullmatch('[0-9a-f]{40}',source.get('commit','')) is not None
              and bool(evidence) and manifest['gates']['G0']['status']=='PASS', identities[-1])
    check('G0_actual_reused_core_and_duplicate_stage_decisions',
          'CKmeans' in identities[0]['current_G0_evidence'] and 'not the complete codec' in identities[0]['current_G0_evidence']
          and 'P0 duplicate/stage' in identities[1]['current_G0_evidence'] and 'does not receive a second AlgorithmID' in identities[1]['current_G0_evidence']
          and 'P0 stage duplicate' in identities[2]['current_G0_evidence'] and 'P2 pipeline' in identities[2]['current_G0_evidence'],
          'ABBA explicitly retains original CKmeans dependency; fABBA compression stage and DeepZip_RNN_Predictor are duplicate P0 stages, not additional codecs. Current G0 rereview does not inherit historical G1-G6/FULL_PARITY.')
    failures=[row for row in rows if row['status']=='FAIL']
    unmet={'NOT_TESTED','MISSING_CURRENT_COMPLETE_REVIEW','UNMET','FAIL_SCOPED_SOURCE_COMPARISON'}
    check('32_FAIL_acceptance_conditions_not_invented_codec_execution', len(failures)==32
          and all(row['failure_kind'].startswith('ACCEPTANCE_') and not row['recorded_execution_failure']
                  and not row['recorded_codec_roundtrip_failure'] and not row['new_codec_execution']
                  and any(item['review_status'] in unmet for item in row['subitems']) for row in failures)
          and review['recorded_codec_roundtrip_failure_count']==0 and review['acceptance_failure_is_not_execution_failure'],
          dict(fail_rows=[dict(codec_key=row['codec_key'],gate=row['gate'],failure_kind=row['failure_kind']) for row in failures],
               semantics='FAIL is denial of full gate acceptance. Only DeepZip has a measured scoped source-comparison difference, referred to by G3/G6/CAP from one original diagnostic.'))
    cap_records=[]
    legal={'REQUIRED_PARITY','OPTIONAL_OPTIMIZATION','UNAVAILABLE_WITH_WAIVER','NOT_APPLICABLE'}
    inventory=read(ROOT/review['inputs']['cap_inventory']['path'])
    inventory_map={(matrix['codec'],item['capability_id']):item['parity_class'] for matrix in inventory for item in matrix['capabilities']}
    current_map={}
    required_total=0
    for item in review['existing_frozen_capability_reviews']:
        codec=item['codec_key'];path=ROOT/item['current_matrix']['path'];matrix=yaml.safe_load(path.read_text())
        old={value['capability_id']:value for value in matrix['capabilities']}
        new={value['capability_id']:value for value in item['capabilities']}
        unchanged=(len(old)==len(matrix['capabilities']) and len(new)==len(item['capabilities']) and set(old)==set(new))
        for key,value in old.items():
            current_map[(codec,key)]=value['parity_class']
            compared=new.get(key,{})
            unchanged &= (compared.get('frozen_original_classification')==value['parity_class']
                          and compared.get('historical_recorded_validation')==value.get('validation',{}).get('status')
                          and compared.get('historical_PASS_rewritten_or_demoted') is False
                          and compared.get('required_obligation_retained')==(value['parity_class']=='REQUIRED_PARITY')
                          and compared.get('new_legal_four_state_classification_required')==(value['parity_class'] not in legal))
            if value['parity_class']=='REQUIRED_PARITY':
                required_total+=1
                unchanged &= compared.get('current_full_scope_validation')=='NOT_TESTED' and bool(compared.get('unmet_subitems'))
        actual_counts=dict(collections.Counter(value['parity_class'] for value in old.values()))
        unchanged &= item['original_class_counts']==actual_counts and item['current_full_scope_CAP_GATE_status']=='FAIL' and item['full_parity_granted'] is False
        record=dict(codec_key=codec,capability_count=len(old),class_counts=actual_counts,
                    capabilities=[dict(capability_id=key,classification=value['parity_class'],historical_validation=value.get('validation',{}).get('status')) for key,value in old.items()],
                    matrix=ref(path))
        cap_records.append(record)
        check('original_matrix_full_ID_classification_and_history_'+codec,unchanged,record)
    check('all42_required_obligations_and_51_original_capabilities_retained',len(cap_records)==4 and required_total==42 and len(current_map)==51 and current_map==inventory_map,
          dict(required_total=required_total,capability_total=len(current_map),invalid_historical_class=current_map.get(('dzip','reference.gpu_bpc_estimator')),
               invalid_class_policy='REFERENCE_ONLY is retained as historical evidence, not accepted as a legal four-state classification; DZip G2 remains FAIL.'))
    four=read(ROOT/review['inputs']['current_four_matrices']['path'])
    matrices=four['matrices']
    matrix_counts={name:len(values) for name,values in matrices.items()}
    four_ok=set(matrices)=={'SourceCapabilityMatrix','StandalonePortMatrix','BenchProfileMatrix','PipelineCoverageMatrix'} and not four['performance_claim']
    for name,values in matrices.items():
        four_ok &= {value['codec_key'] for value in values}==active
        if name in {'SourceCapabilityMatrix','StandalonePortMatrix'}:
            four_ok &= len(values)==len({value['codec_key'] for value in values})==33
            four_ok &= all(value['state'].startswith('UNKNOWN') for value in values)
        elif name=='BenchProfileMatrix':
            four_ok &= len(values)==len({value['case']['case_id'] for value in values})==41
            four_ok &= all(value['state']=='SCOPED_PASS' and value['formal_performance']=='NOT_GRANTED_BY_QUALIFICATION' for value in values)
        else:
            four_ok &= len(values)==len({value['case_id'] for value in values})==41
            four_ok &= all(value['state']=='SCOPED_PASS' for value in values)
    check('four_layer_Bench_matrices_retained_without_full_scope_transfer',four_ok
          and all(entry['full_upstream_scope_not_reduced_to_Bench_profile'] and not entry['all_required_gates_accepted'] for entry in entries),
          dict(matrix_counts=matrix_counts,performance_claim=four['performance_claim'], interpretation='Matrix names/finite Bench cases are not full upstream capability or N/G/CAP evidence; original 42 REQUIRED rows above remain independent.'))
    source_summary=read(ROOT/review['inputs']['fresh_fixed_weight_source_r2']['path'])
    actual_source=read(source_summary['result']['path'])
    external=review['external_fresh_source_diagnostic']
    native_difference=[(row['row'],index,difference) for row in actual_source['rows'] for index,difference in enumerate(row['cdf_integer_difference']) if difference]
    deepzip=next(entry for entry in entries if entry['codec_key']=='deepzip')
    deepzip_G3=next(row for row in deepzip['gates'] if row['gate']=='G3')
    comparison=next(item for item in deepzip_G3['subitems'] if item['id']=='independent_prediction_full_CDF')
    prob_count=sum(len(row['probabilities']) for row in actual_source['rows'])
    cdf_count=sum(len(row['source_cdf']) for row in actual_source['rows'])
    gpu=actual_source['source_actual_cudnn_gpu_nodes']
    check('DeepZip_real_full_probability_CDF_evidence_and_scope',external['checks']==source_summary['checks'] and external['scope']==source_summary['scope']
          and prob_count==12 and cdf_count==15 and native_difference==[(2,4,-1)]
          and actual_source['probability_max_absolute_error']==1.4901161193847656e-08
          and actual_source['probability_absolute_tolerance']==3e-5 and actual_source['all_12_probabilities_within_tolerance']
          and actual_source['source_numpy_to_current_cdf_identical_inputs_exact'] and not actual_source['independently_predicted_cdf_exact']
          and len(gpu)==4 and all(value['op']=='CudnnRNN' and 'GPU:0' in value['device'] for value in gpu)
          and comparison['review_status']=='FAIL_SCOPED_SOURCE_COMPARISON'
          and external['current_attempt_command_failures']==0 and external['scoped_independent_CDF_comparison_failures']==1
          and '-6' in external['preserved_first_attempt_execution_failure'] and not external['source_bitstream_full_pipeline_CAP_granted']
          and all(row['exit_code']==0 for row in actual_source['commands']),
          dict(summary=ref(ROOT/review['inputs']['fresh_fixed_weight_source_r2']['path']),original_result=ref(source_summary['result']['path']),
               probabilities=prob_count,CDF_integers=cdf_count,independent_prediction_CDF_mismatches=native_difference,source_total=10000004,native_total=10000003,
               max_probability_abs_error=actual_source['probability_max_absolute_error'],actual_CudnnRNN_GPU_nodes=gpu,
               original_r1_failure_retained=True,r2_difference_is_semantic_not_process_crash=True))
    pending={item['key']:item for item in review['pending_new_evidence']}
    check('pending_build_FORMAL_and_native_delivery_no_automatic_grants',
          pending['build_trace_v5']['status']=='PENDING_AT_REVIEW_FREEZE' and pending['formal_final_results']['status']=='PENDING_AT_REVIEW_FREEZE'
          and all(row['status']=='UNKNOWN' for row in rows if row['gate'] in {'N1','G1'})
          and not review['full_N_G_CAP_acceptance_granted'] and not review['FULL_PARITY_REWRITE_DONE_or_FORMAL_granted']
          and not review['new_codec_training_model_or_performance_execution']
          and all(next(item for item in row['subitems'] if item['id']=='FORMAL_prerequisite')['review_status']=='NOT_APPLICABLE'
                  for row in rows if row['gate']=='N5'),
          'The pending build may later satisfy affected closure subitems only. N5 independent consumer delivery has no FORMAL prerequisite. No existing/future measurement signs source semantics, full CAP, or independent delivery.')
    input_checks=[]
    for key,expected in review['inputs'].items():
        actual=ref(ROOT/expected['path'])
        input_checks.append(dict(key=key,status='MATCH' if actual['sha256']==expected['sha256'] and actual['bytes']==expected['bytes'] else 'FAIL',actual=actual))
    check('all24_document_JSON_inputs_current_SHA_size_match',len(input_checks)==24 and all(item['status']=='MATCH' for item in input_checks),input_checks)
    gate5=next(row for row in deepzip['gates'] if row['gate']=='G5')
    wording=next(item for item in gate5['subitems'] if item['id']=='complete_required_GPU_prediction_or_bootstrap_execution')
    clarification=dict(id='DEEPZIP_G5_NOT_EXECUTED_WORDING_SCOPE',severity='CLARIFICATION_NONBLOCKING_GATE_VERDICT_UNCHANGED',
                       subject_path='entries[deepzip].gates[G5].subitems[complete_required_GPU_prediction_or_bootstrap_execution].finding',
                       original_finding=wording['finding'],
                       finding='The complete required source/native GPU and codec/dataset set remains unclosed. The generic phrase not executed can incorrectly imply that no source GPU predictor ran, although the same frozen report correctly records actual biGRU source GPU execution in G3 and its external diagnostic.',
                       required_supplement='Clarify full required set not completed; source biGRU/alphabet4/three-context 4-CudnnRNN GPU execution and limited probability/CDF-conversion PASS are retained; native GPU, remaining model/checkpoint/pipeline/API paths stay unqualified. Keep G5 FAIL and preserve frozen original report.',
                       gate_verdict_affected=False,source_finite_GPU_PASS_retracted=False)
    check('frozen_subject_not_modified',ref(SUBJECT)==subject_before,subject_before)
    review_failures=[item for item in checks if item['status']=='FAIL']
    result=dict(schema_version='tscb.gate-acceptance-independent-review.v1',
                status='INDEPENDENT_STATIC_CHECKS_PASS_WITH_NONBLOCKING_WORDING_CLARIFICATION' if not review_failures else 'INDEPENDENT_STATIC_REVIEW_FOUND_ERRORS',
                subject=subject_before,driver=ref(Path(__file__)),standard=authority,checks=checks,
                check_counts=dict(collections.Counter(item['status'] for item in checks)),clarifications=[clarification],
                errors=review_failures,reviewed_gate_status_counts=counts,
                review_scope='Current acceptance report validity against the entire current v3.0 authority and its applicable gate/identity/evidence rules; original source/model/binary/runtime contents are not rehashed or reexecuted.',
                governing_clauses=['0.6','2.4','2.5','2.7','2.8','3 G0-G6/CAP-GATE','38.2.3-38.2.5','72.1','82 NATIVE/EVID/XFER/GEN rules','109','114.1-114.7','115.1-115.3','116.1-116.4','117.2','118-122','Appendix A'],
                codec_model_training_build_performance_executed=False,
                heavy_model_binary_archive_hashing_performed=False,
                full_N_G_CAP_PARITY_REWRITE_DONE_FORMAL_granted=False,
                original_review_production_matrices_modified=False)
    save(HERE/'gate-acceptance-independent-review-r1.json',result)
    print(json.dumps(dict(status=result['status'],checks=result['check_counts'],counts=counts,clarifications=len(result['clarifications']),subject_sha256=subject_before['sha256'],report=ref(HERE/'gate-acceptance-independent-review-r1.json'))))


if __name__=='__main__':
    main()
