"""Read-only active-entry receipt review; no qualifier, codec, or worker execution."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('folder')
parser.add_argument('--historical', action='store_true')
parser.add_argument('--output', required=True)
args = parser.parse_args()
folder = ROOT / args.folder
errors = []
drift = []
cache = {}
references = 0

def check(condition, label):
    if not condition:
        errors.append(label)

def local(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path

def sha(path):
    path = path.resolve()
    if path not in cache:
        cache[path] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return cache[path]

def normalize(value):
    if isinstance(value, str):
        return unicodedata.normalize('NFC', value)
    if isinstance(value, dict):
        return {normalize(k): normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if value is None or type(value) in (bool, int):
        return value
    raise ValueError('Unexpected identity type: ' + str(type(value)))

def identity(domain, document, omitted):
    payload = {k: v for k, v in document.items() if k != omitted}
    data = json.dumps(normalize(payload), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode()
    return 'v2:' + domain + ':sha256:' + hashlib.sha256(data).hexdigest()

def walk(value, label):
    global references
    if isinstance(value, list):
        for n, item in enumerate(value):
            walk(item, label + '/' + str(n))
    elif isinstance(value, dict):
        expected = value.get('actual_sha256') or value.get('sha256')
        if isinstance(value.get('path'), str) and isinstance(expected, str):
            references += 1
            path = local(value['path'])
            if sha(path) != expected:
                drift.append({'label': label, 'path': str(path), 'expected': expected,
                              'actual': sha(path)})
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                walk(item, label + '/' + key)

plan_path = folder / 'plan.json'
summary_path = folder / 'summary.json'
matrix_path = folder / 'four_matrices.json'
plan = json.loads(plan_path.read_text())
summary = json.loads(summary_path.read_text())
matrices = json.loads(matrix_path.read_text())
check(identity('active-entry-qualification-plan-v32', plan, 'plan_id') == plan['plan_id'],
      'plan canonical identity')
check(summary['plan_id'] == matrices['plan_id'] == plan['plan_id'], 'shared plan identity')
check(summary['active_entry_count'] == summary['selected_entry_count'] == 33,
      '33 selected active entries')
check(summary['entire_active_scope_selected'] is True, 'entire active selection')
check(plan['active_keys'] == plan['selected_keys'] and len(plan['entries']) == 33,
      'plan full current selection')
check(summary['performance_claim'] is False and summary['full_source_domain_claim'] is False
      and matrices['performance_claim'] is False, 'no full domain or performance promotion')
walk(plan, 'plan')
walk(summary, 'summary')
walk(matrices, 'matrices')

cases = []
retained_stream_count = 0
for entry in plan['entries']:
    for frozen in entry['cases']:
        check(identity('active-entry-qualification-case-v32', frozen, 'case_id') == frozen['case_id'],
              'frozen case identity ' + entry['codec_key'])
        case_path = folder / 'cases' / (frozen['case_id'].rsplit(':', 1)[-1] + '.json')
        case = json.loads(case_path.read_text())
        check(identity('active-entry-qualification-evidence-v32', case, 'evidence_id')
              == case['evidence_id'], 'case canonical evidence identity')
        check(case['case_id'] == frozen['case_id'] and case['plan_id'] == plan['plan_id'],
              'case slot and plan binding')
        walk(case, 'case/' + frozen['case_id'])
        acceptance = case['acceptance']
        if acceptance['status'] == 'SCOPED_PASS':
            check(set(acceptance['checks']) == {
                'boundary_safety_pass', 'complete_cost_ledger', 'context_cost_bound',
                'correctness_pass', 'independent_recovery', 'independent_worker_exit',
                'preflight_pass', 'stream_hash_bound'}
                and all(v is True for v in acceptance['checks'].values()),
                  'all eight scoped acceptance checks')
            observed = case['preflight']
            check(observed['correctness']['status'] == 'PASS' and observed['boundary']['passed'] is True,
                  'correctness and boundary observation')
            diagnostics = observed['diagnostics']
            captured = diagnostics['qualification_artifacts']
            capture_path = folder / 'qualification_artifacts' / frozen['case_id'].rsplit(':', 1)[-1]
            check(json.loads((capture_path / 'binding.json').read_text()) == captured,
                  'retained capture manifest equality')
            stream, context = captured['stream'], captured['context']
            check(local(stream['path']).resolve() == (capture_path / 'stream.bin').resolve()
                  and local(context['path']).resolve() == (capture_path / 'context.json').resolve(),
                  'retained artifacts belong to the exact case directory')
            check(local(stream['path']).stat().st_size == stream['bytes']
                  and local(context['path']).stat().st_size == context['bytes'],
                  'capture byte lengths')
            check(stream['sha256'] == observed['bitstream_sha256'], 'observed stream hash')
            ledger = observed['accounting']
            check(ledger['serialized_bits'] == stream['bytes'] * 8
                  and ledger['final_physical_bytes'] == stream['bytes']
                  and ledger['external_side_information_bits'] == context['bytes'] * 8
                  and ledger['final_bits'] == (stream['bytes'] + context['bytes']) * 8,
                  'actual stream and context cost ledger')
            recovery = diagnostics['independent_recovery']
            lifecycle = diagnostics['independent_recovery_worker_lifecycle']
            check(recovery['stream_sha256'] == stream['sha256']
                  and recovery['decode_context_sha256'] == context['sha256']
                  and recovery['required_external_bits'] == context['bytes'] * 8,
                  'independent recovery stream/context identity')
            check(recovery['encoder_session_available'] is False
                  and recovery['original_input_available'] is False
                  and recovery['output_owned_in_worker'] is True
                  and lifecycle['worker_exit_confirmed'] is True
                  and lifecycle['exit_code'] == 0, 'separate worker recovery evidence')
            binding = captured['binding']
            task = case['task']
            context_document = json.loads(local(context['path']).read_bytes())
            check(context_document == observed['run_record']['decode_context']
                  and context_document['adapter_id'] == binding['adapter_id']
                  and context_document['parameters'] == frozen['parameters']
                  and context_document['track'] == frozen['track']
                  and context_document['canonical_raw_bits'] == binding['canonical_raw_bits'],
                  'actual paid context content and declared configuration agree')
            check(task['algorithm_id'] == entry['algorithm_id'], 'task matches frozen algorithm entry')
            check(all(binding[k] == task[k] for k in
                      ('task_id', 'algorithm_id', 'config_id', 'dataset_id', 'track')),
                  'capture task identity binding')
            check(binding['execution_path_hash'] == task['execution']['execution_path_hash']
                  and binding['adapter_id'] == task['execution']['adapter_id']
                  and binding['parameters'] == frozen['parameters'], 'capture execution/config binding')
            retained_stream_count += 1
        cases.append({'codec': entry['codec_key'], 'track': frozen['track'],
                      'status': acceptance['status'], 'case': str(case_path.relative_to(ROOT)),
                      'sha256': sha(case_path), 'preflight_status': case.get('preflight', {}).get('status'),
                      'preflight_reason': case.get('preflight', {}).get('reason_code')})

counts = dict(Counter(case['status'] for case in cases))
check(summary['status_counts'] == counts, 'summary agrees with independent case counts')
check(summary['expected_track_cases'] == summary['observed_track_cases'] == len(cases) == 41,
      '41 planned and observed cases')
check({k: len(v) for k, v in matrices['matrices'].items()} == {
    'BenchProfileMatrix': 41, 'PipelineCoverageMatrix': 41,
    'SourceCapabilityMatrix': 33, 'StandalonePortMatrix': 33}, 'four matrix universes')
if args.historical:
    check(summary['status'] == 'INCOMPLETE_OR_FAILED' and counts == {
        'SCOPED_PASS': 40, 'NOT_ACCEPTED': 1}, 'preserved r1 result boundary')
    check(all(local(item['path']).is_relative_to(ROOT / 'src')
              or local(item['path']).is_relative_to(ROOT / 'tools')
              or local(item['path']).is_relative_to(ROOT / 'registry') for item in drift),
          'historical drift is confined to changed production or registration files')
else:
    check(summary['status'] == 'SCOPED_QUALIFICATION_COMPLETE'
          and counts == {'SCOPED_PASS': 41}, 'final scoped qualification complete')
    check(not drift, 'current file binding has no hash drift')

reviewed_reports = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p)}
                    for p in (plan_path, summary_path, matrix_path)]
review_script_sha256 = sha(Path(__file__))
result = {
    'status': ('PASS_HISTORICAL_FAILED_RESULT_BOUNDARY' if args.historical
               else 'PASS_CURRENT_SCOPED_ACTIVE_FILE_LINKAGE') if not errors else 'FAIL',
    'scope': 'PURE_FILE_REVIEW_NO_CODEC_QUALIFIER_OR_WORKER_EXECUTION',
    'review_script_sha256': review_script_sha256, 'historical': args.historical,
    'current_hash_binding_granted': not args.historical and not drift,
    'hash_reference_count': references, 'unique_files_hashed': len(cache),
    'cases': cases, 'status_counts': counts, 'retained_stream_context_pairs': retained_stream_count,
    'current_file_drift': drift, 'errors': errors,
    'complete_n1_granted': False, 'full_source_domain_granted': False,
    'full_parity_granted': False, 'new_formal_granted': False,
    'reviewed_reports': reviewed_reports,
}
(OUT / args.output).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k not in ('cases', 'current_file_drift')}, indent=2))
print('current_file_drift_count=' + str(len(drift)))
raise SystemExit(1 if errors else 0)
