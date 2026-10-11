"""Verify the additive final regression receipt without running tests or tools."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BASE = ROOT / 'docs/audits/20261011_porting_standard/regression_test_expectation_repair_r1'
receipt_path = BASE / 'completion-receipt-r2.json'
receipt = json.loads(receipt_path.read_text())
errors, cache = [], {}


def sha(path):
    path = path.resolve()
    if path not in cache:
        cache[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return cache[path]


def check(condition, label):
    if not condition:
        errors.append(label)


def reference(item, label):
    path = ROOT / item['path']
    check(sha(path) == item['sha256'], label + ' SHA')
    check(path.stat().st_size == item['bytes'], label + ' bytes')
    return path


old_path = reference(receipt['prior_record_preserved'], 'retained original repair record')
old = json.loads(old_path.read_text())
check(receipt['prior_record_status'] == old['status']
      == 'SCOPED_REPAIRS_VERIFIED_FULL_REGRESSION_PENDING', 'original pending state retained')
check(receipt['schema_version'] == 'tscb.regression-repair-completion-receipt.v1'
      and receipt['status'] == 'SCOPED_REPAIRS_AND_DEFAULT_FULL_REGRESSION_COMPLETED',
      'additive completion status')
full = receipt['full_regression']
validation_path = reference(full['validation'], 'final validation')
log_path = reference(full['log'], 'final log')
reference(full['verification_driver'], 'final driver')
validation = json.loads(validation_path.read_text())
review_path = OUT / 'full_regression_file_review.json'
review = json.loads(review_path.read_text())
check(review['status'] == 'PASS_CURRENT_FULL_REGRESSION_FILE_LINKAGE'
      and review['errors'] == [] and review['current_file_drift'] == [], 'independent final review PASS')
check(review['reviewed_report']['sha256'] == sha(validation_path)
      and review['reviewed_report']['path'] == str(validation_path.relative_to(ROOT)),
      'independent final review exact validation')
check(sha(OUT / 'review_full_regression.py') == review['review_script_sha256'],
      'independent final review script bytes')
summary = [line for line in log_path.read_text().splitlines() if line.strip()][-1]
check(summary == full['pytest_summary'] == review['pytest_final_summary'], 'true final summary')
duration = re.search(r' in (\d+(?:\.\d+)?)s', summary)
check(duration is not None and float(duration[1]) == full['duration_seconds'], 'duration from actual log')
check(full['status'] == validation['status'] == 'PASS'
      and full['exit_code'] == validation['full_suite_exit_code'] == 0, 'actual invocation successful')
for field in ('input_snapshot_unchanged', 'configuration_snapshot_unchanged', 'driver_snapshot_unchanged'):
    check(full[field] is validation[field] is True, field)
check(full['pytest_addopts_environment'] == validation['pytest_addopts_environment'], 'environment linkage')
for label, key in [('passed', 'tests_passed'), ('failed', 'tests_failed'), ('errors', 'tests_errored'),
                   ('skipped', 'tests_skipped'), ('deselected', 'tests_deselected'), ('warnings', 'warnings')]:
    check(full[label] == review[key], label + ' independently parsed count')
check(full['passed'] == validation['tests_passed'] == 2798, '2798 actual passed tests')
for label, entries in [('source_files', validation['control_plane']['files']),
                       ('test_and_fixture_files', validation['test_source_manifest']),
                       ('project_configuration_files', validation['project_configuration_manifest'])]:
    check(full[label] == len(entries), label + ' exact manifest count')
check(full['verification_driver'] == validation['verification_driver'], 'same frozen driver')
expected = {(phase, item[phase]['path'], item[phase]['sha256'])
            for item in old['files'] for phase in ('before', 'current')}
observed = {(item['role'], item['path'], item['sha256']) for item in receipt['repaired_file_snapshots']}
check(observed == expected and len(receipt['repaired_file_snapshots']) == 14,
      'all seven exact before/current pairs retained')
for item in receipt['repaired_file_snapshots']:
    reference(item, 'repair snapshot ' + item['role'] + '/' + item['path'])
repair_review_path = OUT / 'regression_repair_file_review.json'
repair_review = json.loads(repair_review_path.read_text())
check(repair_review['status'] == 'PASS_STATIC_REPAIRS_AND_DECLARED_ROLE_FILE_REVIEW'
      and repair_review['errors'] == []
      and repair_review['repair_record']['sha256'] == sha(old_path), 'static repair review exact retained record')
old_validation = next(item for item in old['artifacts'] if item['path'].endswith('full-regression-r1/validation.json'))
check(sha(ROOT / old_validation['path']) == old_validation['sha256'], 'original failed validation retained')
check(receipt['old_failure_evidence_preserved'] is True
      and receipt['source_gate_weakened'] is False
      and receipt['scientific_decisions_changed'] is False, 'scope restrictions retained')
boundary = receipt['claim_boundary']
check(boundary['default_project_tests_pass'] is True
      and all(value is False for key, value in boundary.items() if key != 'default_project_tests_pass'),
      'no tool closure parity complete gates release or FORMAL promotion')
sha(receipt_path)
sha(review_path)
sha(repair_review_path)
sha(Path(__file__))
result = {
    'status': 'PASS_ADDITIVE_REGRESSION_COMPLETION_FILE_LINKAGE' if not errors else 'FAIL',
    'scope': 'PURE_FILE_REVIEW_NO_TEST_COLLECTION_OR_EXECUTION',
    'review_script_sha256': sha(Path(__file__)),
    'reviewed_receipt': {'path': str(receipt_path.relative_to(ROOT)), 'sha256': sha(receipt_path)},
    'prior_pending_record_preserved': {'path': str(old_path.relative_to(ROOT)), 'sha256': sha(old_path)},
    'independent_full_review_sha256': sha(review_path),
    'independent_static_repair_review_sha256': sha(repair_review_path),
    'unique_files_hashed': len(cache), 'before_current_snapshot_count': 14,
    'actual_pytest_summary': summary, 'claim_boundary': boundary, 'errors': errors,
}
(OUT / 'regression_completion_file_review.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
