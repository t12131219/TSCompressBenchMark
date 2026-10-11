"""Static test repair, saved JUnit, and declared-role metadata review; no tests run."""
import ast
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import unicodedata
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
repair = ROOT / 'docs/audits/20261011_porting_standard/regression_test_expectation_repair_r1'
errors = []
cache = {}

def sha(path):
    path = path.resolve()
    if path not in cache:
        cache[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return cache[path]

def check(condition, label):
    if not condition:
        errors.append(label)

def normalize(value):
    if isinstance(value, str):
        return unicodedata.normalize('NFC', value)
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {normalize(key): normalize(item) for key, item in value.items()}
    if value is None or type(value) in (int, bool):
        return value
    raise TypeError(type(value))

def canonical(value):
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()

def identity(domain, document, version='v3'):
    return version + ':' + domain + ':sha256:' + hashlib.sha256(canonical(document)).hexdigest()

def functions(path):
    return {node.name: node for node in ast.parse(path.read_text()).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

allowed = {
    'tests/adapters/test_neats.py': {'test_source_closure_patch_set_and_registry_identity_are_reproducible'},
    'tests/integration/test_simdcomp_qualification.py': {'test_factory_rejects_consumed_dependency_drift'},
    'tests/integration/test_v32_workload_runner.py': {
        'real_workload', 'test_native_api_rejects_different_actual_inputs_on_same_original_corpus',
        'test_missing_timestamp_expected_rejection_never_routes_an_absent_timestamp'},
    'tests/unit/test_comparison_source_rebind.py': {'test_cpp_source_label_changes_without_changing_lzss_method_semantics'},
    'tests/unit/test_v32_comparison_bundles.py': {'test_committed_bundle_freezes_every_promised_member_and_full_matrix'},
    'tests/unit/test_v32_quality_model_bundles.py': {'test_quality_three_point_grid_is_empirical_and_keeps_every_cell'},
}
diffs = []
rows = []
for relative, changed_names in allowed.items():
    before = repair / 'before' / relative
    current = ROOT / relative
    old_functions, new_functions = functions(before), functions(current)
    check({name for name in old_functions if name.startswith('test_')}
          == {name for name in new_functions if name.startswith('test_')}, relative + ' test name universe unchanged')
    actual_changed = []
    for name, old in old_functions.items():
        new = new_functions[name]
        check(ast.dump(old.args) == ast.dump(new.args)
              and [ast.dump(n) for n in old.decorator_list] == [ast.dump(n) for n in new.decorator_list],
              relative + '/' + name + ' signatures/decorator parameters unchanged')
        if ast.dump(old) != ast.dump(new):
            actual_changed.append(name)
            check(name in changed_names, relative + '/' + name + ' approved expectation/bundle repair only')
    if 'workload_runner' in relative:
        for name in changed_names:
            check([ast.dump(n) for n in ast.walk(old_functions[name]) if isinstance(n, ast.Assert)]
                  == [ast.dump(n) for n in ast.walk(new_functions[name]) if isinstance(n, ast.Assert)],
                  'workload correctness/input/timestamp assertions preserved ' + name)
    if relative in {'tests/unit/test_v32_comparison_bundles.py', 'tests/unit/test_v32_quality_model_bundles.py'}:
        for name in changed_names:
            old_asserts = Counter(ast.dump(n) for n in ast.walk(old_functions[name]) if isinstance(n, ast.Assert))
            new_asserts = Counter(ast.dump(n) for n in ast.walk(new_functions[name]) if isinstance(n, ast.Assert))
            check(not (old_asserts - new_asserts), 'unit comparison assertions retained ' + name)
    rows.append({'path': relative, 'before_sha256': sha(before), 'current_sha256': sha(current),
                 'changed_functions': actual_changed,
                 'test_function_count': sum(n.startswith('test_') for n in old_functions)})
    diffs.extend(difflib.unified_diff(before.read_text().splitlines(True), current.read_text().splitlines(True),
                                      fromfile='before/' + relative, tofile='current/' + relative))
(OUT / 'fixed/regression_test_repairs.diff').write_text(''.join(diffs))
neats_text = (ROOT / 'tests/adapters/test_neats.py').read_text()
check('== 172' in neats_text and 'RELATIVE_PATH_NUL_FILE_BYTES_V1' in neats_text
      and 'path.relative_to(patch_root).as_posix().encode() + b"\\0"' in neats_text,
      'NeaTS retains 172-source check and uses registered relative-name/raw-byte protocol')
simd_text = (ROOT / 'tests/integration/test_simdcomp_qualification.py').read_text()
check('pytest.raises(AdapterFactoryError, match=reason)' in simd_text
      and '"runtime profile artifact/build identity differs"' in simd_text
      and 'target in {"missing-objects", "wrong-isa"}' in simd_text,
      'SIMD retains precise exception and selects exact profile reason for two cases')
model_text = (ROOT / 'tests/unit/test_comparison_source_rebind.py').read_text()
check('changed["old_method_id"] == changed["current_method_id"]' in model_text
      and 'member["method"]["name"] == manifest["identity"]["display_name"]' in model_text,
      'MethodID preserved while display name matches registration')

original_report = json.loads((ROOT / 'build/port-standard-v30-20261011/full-regression-r1/validation.json').read_text())
repair_record_path = repair / 'repair-record.json'
repair_record = json.loads(repair_record_path.read_text())
original_hashes = {entry['path']: entry['sha256'] for entry in original_report['test_source_manifest']}
original_hashes['tools/verify_v32_regression.py'] = original_report['verification_driver']['sha256']
original_matches = 0
for item in repair_record['files']:
    for phase in ('before', 'current'):
        reference = item[phase]
        check(sha(ROOT / reference['path']) == reference['sha256'], 'repair record ' + phase + ' SHA')
    actual_matches = original_hashes.get(item['path']) == item['before']['sha256']
    check(actual_matches == item['old_full_r1_test_or_driver_sha_match'], 'accurate prior r1 association')
    original_matches += actual_matches
check(original_matches == 6 and len(repair_record['files']) == 7, 'six old full r1 records plus one new targeted test')
for reference in repair_record['artifacts']:
    check(sha(ROOT / reference['path']) == reference['sha256'], 'repair evidence artifact SHA')
check(repair_record['old_failures_retained'] is True and repair_record['source_gate_weakened'] is False
      and repair_record['scientific_decisions_changed'] is False
      and repair_record['formal_performance_granted'] is False, 'repair scope remains explicit')
sha(repair_record_path)
old_driver = repair / 'before/tools/verify_v32_regression.py'
check(sha(old_driver) == original_report['verification_driver']['sha256'],
      'retained original driver exactly matches failed r1 frozen driver')
driver_path = ROOT / 'tools/verify_v32_regression.py'
sha(driver_path)
driver_text = driver_path.read_text()
check('for directory in ("configs", "registry", "schemas")' in driver_text
      and 'and configuration_unchanged' in driver_text and 'and driver_unchanged' in driver_text,
      'v2 driver includes configuration and driver stability in acceptance')

junit_rows = []
base = ROOT / 'build/port-standard-v30-20261011'
for stem, expected in [('targeted-regression-repairs-r1', (56, 1, 0, 0)),
                       ('source-rebind-unit-final', (19, 0, 0, 0))]:
    xml_path, log_path = base / (stem + '.xml'), base / (stem + '.log')
    cases = list(ET.parse(xml_path).getroot().iter('testcase'))
    failures = [case.get('name') for case in cases if list(case.iter('failure'))]
    counts = (len(cases), len(failures), sum(bool(list(c.iter('error'))) for c in cases),
              sum(bool(list(c.iter('skipped'))) for c in cases))
    check(counts == expected, stem + ' actual JUnit count/status')
    junit_rows.append({'junit': str(xml_path.relative_to(ROOT)), 'junit_sha256': sha(xml_path),
                       'log': str(log_path.relative_to(ROOT)), 'log_sha256': sha(log_path),
                       'tests': counts[0], 'failures': failures, 'errors': counts[2], 'skipped': counts[3]})

ledger_path = base / 'current-port-role-ledger-r2.json'
ledger = json.loads(ledger_path.read_text())
check(identity('active-stage-role-ledger-v32', {k: v for k, v in ledger.items() if k != 'ledger_id'}, 'v2')
      == ledger['ledger_id'], 'new declared role ledger canonical identity')
for item in ledger['input_files']:
    check(sha(ROOT / item['path']) == item['sha256'], 'role ledger input ' + item['path'])
inventory = json.loads((ROOT / 'docs/audits/20261011_porting_standard/source_build_inventory_r1/inventory-final-r2.json').read_text())
source_ids = {row['codec_key']: row['source_artifact_id'] for row in inventory['rows']}
check({row['codec_key'] for row in ledger['entries']} == set(source_ids), 'ledger 33 active entry universe')
for entry in ledger['entries']:
    check(entry['source_artifact_id'] == source_ids[entry['codec_key']], 'role ledger source ID')
    check(entry['qualification_status'] == 'READ_SEPARATE_FRESH_EVIDENCE_NOT_GRANTED_BY_ROLE_LEDGER'
          and entry['stage_evidence_status'] == 'DECLARED_ROLES_NOT_AN_EXECUTION_TRACE', 'declaration scope preserved')
    check(sha(ROOT / entry['manifest']) == entry['manifest_sha256'], 'role entry manifest SHA')
for group in ledger['groups']:
    bundle_path = ROOT / group['bundle']
    bundle = json.loads(bundle_path.read_text())
    check(sha(bundle_path) == group['bundle_sha256'] and identity('group-spec', bundle['group']) == group['group_id'],
          'role group exact frozen identity')
    check(group['status'] == 'FROZEN_SPEC_ONLY_NOT_EXECUTION_PASS', 'role group not runtime promotion')
check(ledger['active_entry_count'] == 33 and ledger['entries_in_selected_groups'] == 28
      and len(ledger['entries_without_selected_group']) == 5 and len(ledger['groups']) == 10,
      'declared groups 33/28/5/10 scope')
sha(ledger_path)
role_driver_path = ROOT / 'tools/build_v32_active_role_ledger.py'
sha(role_driver_path)
script_sha256 = sha(Path(__file__))
result = {'status': 'PASS_STATIC_REPAIRS_AND_DECLARED_ROLE_FILE_REVIEW' if not errors else 'FAIL',
          'scope': 'PURE_FILE_AST_DIFF_JUNIT_AND_DECLARATION_REVIEW_NO_TESTS_OR_CODEC_EXECUTION',
          'review_script_sha256': script_sha256, 'unique_files_hashed': len(cache),
          'test_repairs': rows, 'saved_junit_results_kept_separate': junit_rows,
          'repair_record': {'path': str(repair_record_path.relative_to(ROOT)), 'sha256': sha(repair_record_path),
                            'status': repair_record['status'], 'before_current_pairs': 7,
                            'prior_r1_matches': original_matches},
          'old_regression_driver': {'path': str(old_driver.relative_to(ROOT)), 'sha256': sha(old_driver)},
          'current_regression_driver': {'path': str(driver_path.relative_to(ROOT)), 'sha256': sha(driver_path)},
          'declared_role_ledger': {'path': str(ledger_path.relative_to(ROOT)), 'sha256': sha(ledger_path),
                                 'entries': 33, 'selected_entries': 28, 'groups': 10,
                                 'qualification_granted': False, 'stage_traces_granted': False},
          'role_driver_read_current_only_not_run': {'path': str(role_driver_path.relative_to(ROOT)),
                                                  'sha256': sha(role_driver_path)},
          'errors': errors, 'full_regression_granted': False, 'full_parity_granted': False, 'formal_granted': False}
(OUT / 'regression_repair_file_review.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
