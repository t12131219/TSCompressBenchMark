"""Negative controls without deleting or modifying the positive run."""
from pathlib import Path
import json
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.api import report_batch_execution, run_batch_execution
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json
from tsbench.application.batch_execution import PCO_OP, TITCHY_OP, _files
from tsbench.planner.batch_execution import CROSS_SCHEMA
from tsbench.planner.linear_batch import EXTENDED_WRAPPED, PCODEC_SUITES, TYPED_SUITES, XZ_SUITES, SCHEMA as LINEAR_SCHEMA
from tsbench.planner.typed_batch import ZFP


def rejected(call, expected):
    try:
        call()
    except ContractError as exc:
        message = str(exc)
        if expected in message:
            return message
        raise AssertionError(message) from exc
    raise AssertionError('negative control accepted')


def _mutate_and_reseal(damaged, mutation, select=lambda r:r['control_payload'] and r['control_payload']['bytes'] > 2):
    ledger = damaged / 'ledger.jsonl'
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    row = next(r for r in rows if select(r))
    mutation(row)
    ledger.write_bytes(b''.join(canonical_bytes(r) + b'\n' for r in rows))
    seal_path = damaged / 'seal.json'
    seal = load_json(seal_path)
    seal['files'] = _files(damaged)
    seal['seal_id'] = content_id({k:v for k,v in seal.items() if k != 'seal_id'})
    seal_path.write_bytes(canonical_bytes(seal) + b'\n')


def main(positive, out):
    plan = load_json(positive / 'plan.json')
    changed = {**plan, 'limits': {**plan['limits'], 'wall_seconds': 6}}
    changed['plan_content_id'] = content_id({k:v for k,v in changed.items() if k != 'plan_content_id'})
    require_change = rejected(lambda:run_batch_execution(ROOT, changed, out), 'differs from current frozen inputs or build')
    cancelled = run_batch_execution(ROOT, plan, out, cancelled=lambda: True)
    assert cancelled['terminal_counts'] == {'cancelled': len(plan['slots'])} and not cancelled['all_product_expectations_met']
    with tempfile.TemporaryDirectory(prefix='tsbench-batch-negative-') as tmp:
        damaged = Path(tmp) / 'run'
        shutil.copytree(positive, damaged)
        frame = next((damaged / 'products').glob('*.bmk'))
        data = frame.read_bytes()
        frame.write_bytes(data[:-1] + bytes([data[-1]^1]))
        corrupt = rejected(lambda:report_batch_execution(damaged), 'batch evidence seal differs')
    result = {'schema':'bmk.batch-execution-negative-controls/1', 'refused_policy_change':require_change,
              'refused_corrupt_artifact':corrupt, 'prelaunch_cancellation':cancelled}
    if plan['schema'] == CROSS_SCHEMA:
        with tempfile.TemporaryDirectory(prefix='tsbench-cross-negative-') as tmp:
            missing, wrong = Path(tmp) / 'missing', Path(tmp) / 'wrong'
            for dest in (missing, wrong):
                shutil.copytree(positive, dest)
            _mutate_and_reseal(missing, lambda row:row['operations'].pop())
            result['refused_cross_without_last_call'] = rejected(lambda:report_batch_execution(missing),
                                                                'verified batch did not complete its required operations')
            def wrong_payload(row):
                path = wrong / row['control_payload']['path']
                data = path.read_bytes()
                path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
                row['control_payload'] = _files(wrong)[row['control_payload']['path']]
            _mutate_and_reseal(wrong, wrong_payload)
            result['refused_resealed_wrong_native_payload'] = rejected(lambda:report_batch_execution(wrong),
                                                                      'retained direct C cross evidence differs')
    if plan['schema'] == LINEAR_SCHEMA:
        with tempfile.TemporaryDirectory(prefix='tsbench-linear-negative-') as tmp:
            fenv, malformed = Path(tmp) / 'fenv', Path(tmp) / 'malformed'
            for dest in (fenv,malformed):
                shutil.copytree(positive,dest)
            def alter_fenv(row):
                row['fenv_control']['observation']['after'] = 0x400
            _mutate_and_reseal(fenv,alter_fenv,lambda row:row.get('fenv_control'))
            result['refused_wrong_fenv_reset'] = rejected(lambda:report_batch_execution(fenv),'ALP fenv ledger differs')
            def alter_negative_digest(row):
                next(iter(row['decoder_rejections'].values()))['sha256'] = '0'*64
            _mutate_and_reseal(malformed,alter_negative_digest,lambda row:row['decoder_rejections'])
            result['refused_incorrect_rejection_input'] = rejected(lambda:report_batch_execution(malformed),
                                                                    'linear rejection evidence differs')
    if plan.get('suite') in TYPED_SUITES:
        with tempfile.TemporaryDirectory(prefix='tsbench-extended-negative-') as tmp:
            no_titchy, wrong_zfp = Path(tmp) / 'no-titchy', Path(tmp) / 'wrong-zfp'
            for dest in (no_titchy, wrong_zfp):
                shutil.copytree(positive, dest)

            def has_titchy(row):
                return any(op['operation'] == TITCHY_OP for op in row['operations'])

            def remove_direct_call(row):
                row['operations'] = [op for op in row['operations'] if op['operation'] != TITCHY_OP]

            _mutate_and_reseal(no_titchy, remove_direct_call, has_titchy)
            result['refused_missing_titchy_control'] = rejected(lambda:report_batch_execution(no_titchy),
                                                                 'batch operation order differs')

            zfp_ids = {slot['product_slot'] for slot in plan['slots'] if slot['method'] == ZFP}

            def has_limit_rejection(row):
                return row['product_slot'] in zfp_ids and any(
                    obs['plugin_status'] == 7 for obs in (row['decoder_rejections'] or {}).values())

            def relabel_limit(row):
                next(obs for obs in row['decoder_rejections'].values() if obs['plugin_status'] == 7)['plugin_status'] = 5

            _mutate_and_reseal(wrong_zfp, relabel_limit, has_limit_rejection)
            result['refused_zfp_resource_limit_mislabeled_corrupt'] = rejected(lambda:report_batch_execution(wrong_zfp),
                                                                              'linear rejection evidence differs')
    if plan.get('suite') in XZ_SUITES:
        with tempfile.TemporaryDirectory(prefix='tsbench-xz-negative-') as tmp:
            wrong_memory, wrong_worker = Path(tmp) / 'wrong-memory', Path(tmp) / 'wrong-worker'
            for dest in (wrong_memory, wrong_worker):
                shutil.copytree(positive, dest)

            def has_budget(row):
                return (row.get('xz_control') or {}).get('dictionary_guard_sha256') is not None

            def alter_guard(row):
                row['xz_control']['dictionary_guard_sha256'] = '0'*64

            def alter_worker(row):
                row['xz_control']['observation']['background_workers'] = 0

            _mutate_and_reseal(wrong_memory, alter_guard, has_budget)
            _mutate_and_reseal(wrong_worker, alter_worker, has_budget)
            result['refused_wrong_xz_budget_frame'] = rejected(lambda:report_batch_execution(wrong_memory),
                                                                'retained XZ direct evidence differs')
            result['refused_xz_background_job_relabeled_as_sync'] = rejected(lambda:report_batch_execution(wrong_worker),
                                                                            'retained XZ direct evidence differs')
    if plan.get('suite') in PCODEC_SUITES:
        with tempfile.TemporaryDirectory(prefix='tsbench-pcodec-negative-') as tmp:
            missing, wrong, wrong_rejection = (Path(tmp)/p for p in ('missing','wrong','wrong-rejection'))
            for dest in (missing, wrong, wrong_rejection):
                shutil.copytree(positive,dest)

            def is_f16_refusal(row):
                return row['status'] == 'expected_rejection' and bool(row.get('pcodec_control'))

            def drop_native_refusal(row):
                row['operations'] = [op for op in row['operations'] if op['operation'] != PCO_OP]

            def change_encoding_entry(row):
                row['pcodec_control']['observation']['direct_encode'] = 'pc_compress_native'

            def fabricate_refusal(row):
                row['pcodec_control']['observation']['output_pointer_null'] = False

            _mutate_and_reseal(missing,drop_native_refusal,is_f16_refusal)
            _mutate_and_reseal(wrong,change_encoding_entry,
                               lambda row:(row.get('pcodec_control') or {}).get('observation',{}).get('direct_encode') == 'pcs_compress')
            _mutate_and_reseal(wrong_rejection,fabricate_refusal,is_f16_refusal)
            result['refused_pcodec_f16_missing_native_refusal'] = rejected(lambda:report_batch_execution(missing),
                                                                          'rejection does not match required worker evidence')
            result['refused_pcodec_source_relabeled_as_c'] = rejected(lambda:report_batch_execution(wrong),
                                                                    'retained pcodec direct evidence differs')
            result['refused_pcodec_native_rejection_with_output'] = rejected(lambda:report_batch_execution(wrong_rejection),
                                                                            'retained pcodec f16 refusal differs')
    if plan.get('suite') == EXTENDED_WRAPPED:
        with tempfile.TemporaryDirectory(prefix='tsbench-wrapped-negative-') as tmp:
            missing, quota, finish = (Path(tmp)/p for p in ('missing','quota','finish'))
            for dest in (missing,quota,finish):
                shutil.copytree(positive,dest)
            slot_ids = {r['method']:r['product_slot'] for r in plan['slots'] if 'protocol' in r}
            def is_wrapped_native(row):
                return row['product_slot'] == slot_ids['pcodec-native-pages']

            def remove_meta(row):
                row['product_parts'].pop('meta')

            def edit_log(dest,row,operation,mutation):
                path = dest/'logs'/row['product_slot']/(operation+'.stdout')
                data = load_json(path)
                mutation(data)
                path.write_bytes(canonical_bytes(data)+b'\n')

            def change_quota(row):
                def set_quota(obs):
                    obs['after_first_with_second_quota'] = 0
                set_quota(row['wrapped_validation']['session_controls'])
                edit_log(quota,row,'wrapped-diagnose',set_quota)

            def claim_finish_on_first_read(row):
                def set_spans(obs):
                    obs['spans'] = [256]
                set_spans(row['wrapped_validation']['detached'][0])
                edit_log(finish,row,'detached-page-1',set_spans)

            _mutate_and_reseal(missing,remove_meta,is_wrapped_native)
            _mutate_and_reseal(quota,change_quota,is_wrapped_native)
            _mutate_and_reseal(finish,claim_finish_on_first_read,is_wrapped_native)
            result['refused_wrapped_product_without_meta'] = rejected(lambda:report_batch_execution(missing),
                                                                        'wrapped product is missing a required part')
            result['refused_cumulative_quota_as_per_page'] = rejected(lambda:report_batch_execution(quota),
                                                                        'wrapped page control or quota scope differs')
            result['refused_first_span_as_completed_page'] = rejected(lambda:report_batch_execution(finish),
                                                                        'wrapped detached decoder did not match geometry or drain terminal')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True))
