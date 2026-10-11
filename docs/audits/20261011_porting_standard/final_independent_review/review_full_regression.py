"""Review saved full pytest evidence without collecting or executing tests."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('validation')
parser.add_argument('--historical-failure', action='store_true')
parser.add_argument('--output', default='full_regression_file_review.json')
args = parser.parse_args()
report_path = ROOT / args.validation
document = json.loads(report_path.read_text())
errors = []
cache = {}
current_file_drift = []

def local(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path

def sha(path):
    path = path.resolve()
    if path not in cache:
        cache[path] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return cache[path]

def check(condition, label):
    if not condition:
        errors.append(label)

def entries(items, label, historical_source=False):
    for entry in items:
        path = local(entry['path'])
        if sha(path) != entry['sha256']:
            current_file_drift.append({'path': str(path), 'expected_sha256': entry['sha256'],
                                       'current_sha256': sha(path), 'label': label})
            check(args.historical_failure and historical_source,
                  label + ' SHA ' + str(path))
        if 'bytes' in entry:
            check(path.is_file() and (path.stat().st_size == entry['bytes']
                  or args.historical_failure and historical_source), label + ' size ' + str(path))
    paths = [local(entry['path']).resolve() for entry in items]
    check(len(set(paths)) == len(paths), label + ' duplicate-free')
    return set(paths)

if args.historical_failure:
    check(document['status'] == 'FAIL' and document['full_suite_exit_code'] != 0
          and document['input_snapshot_unchanged'] is True, 'preserved stable failed invocation')
else:
    check(document['status'] == 'PASS' and document['full_suite_exit_code'] == 0
          and document['input_snapshot_unchanged'] is True, 'successful stable invocation')
check(document['full_suite_command'][1:] == ['-m', 'pytest', '-q', '--tb=short'],
      'command has no selector or test filter')
check(document['full_suite_command'][0] == document['python_executable']['path'],
      'command interpreter matches frozen executable')
entries([document['python_executable']], 'Python executable')
entries([document['verification_driver']], 'verification driver')
source = document['control_plane']
actual_sources = {p.resolve() for p in (ROOT / 'src/tscompbench').rglob('*.py')}
source_universe_matches = entries(source['files'], 'control plane', historical_source=True) == actual_sources
check(source_universe_matches or args.historical_failure, 'complete control-plane universe')
canonical_files = json.dumps(source['files'], ensure_ascii=False, sort_keys=True,
                            separators=(',', ':')).encode()
check(hashlib.sha256(canonical_files).hexdigest() == source['sha256'], 'control-plane list identity')
actual_tests = {p.resolve() for p in (ROOT / 'tests').rglob('*') if p.is_file()
                and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts
                and p.suffix not in ('.pyc', '.pyo')}
test_universe_matches = entries(document['test_source_manifest'], 'test definitions',
                                historical_source=True) == actual_tests
check(test_universe_matches or args.historical_failure, 'complete test and fixture file universe')
configuration_universe_matches = None
project_configuration_count = 0
if document['schema_version'] == 'tscb.full-regression-verification.v2':
    actual_configuration = {p.resolve() for directory in ('configs', 'registry', 'schemas')
                            for p in (ROOT / directory).rglob('*') if p.is_file()
                            and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts
                            and p.suffix not in ('.pyc', '.pyo')}
    observed_configuration = entries(document['project_configuration_manifest'],
                                     'project configuration', historical_source=True)
    project_configuration_count = len(observed_configuration)
    configuration_universe_matches = actual_configuration == observed_configuration
    check(configuration_universe_matches or args.historical_failure,
          'complete configs registry schemas universe')
    check(document['configuration_snapshot_unchanged'] is True
          and document['driver_snapshot_unchanged'] is True,
          'configuration and regression driver stable during execution')
else:
    check(args.historical_failure and document['schema_version']
          == 'tscb.full-regression-verification.v1', 'current regression requires v2 config binding')
check(entries(document['test_configuration'], 'test configuration') == {ROOT / 'pyproject.toml'},
      'test configuration bound')
config = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['pytest']['ini_options']
check(config['testpaths'] == ['tests'] and config['addopts'] == '-ra --strict-markers',
      'configured collection has no implicit subset')
check(document['pytest_addopts_environment'] == 'REMOVED_TO_PREVENT_IMPLICIT_FILTERING',
      'PYTEST_ADDOPTS removal recorded')
check(document['execution_environment_overrides'] == {
    'PYTHONPATH': str(ROOT / 'src'), 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
    'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1'}, 'frozen environment overrides')
entries(document['artifacts'], 'full regression artifacts')
logs = [entry for entry in document['artifacts'] if entry['role'] == 'FULL_SUITE_LOG']
check(len(logs) == 1, 'one saved complete output log')
log = local(logs[0]['path']).read_text()
nonempty_lines = [line for line in log.splitlines() if line.strip()]
summary = nonempty_lines[-1] if nonempty_lines else ''
status_word = r'(?:passed|failed|errors?|skipped|deselected|warnings?|xfailed|xpassed)'
final_summary = re.fullmatch(
    r'\s*(?:=+\s*)?\d+ ' + status_word
    + r'(?:,\s*\d+ ' + status_word + r')* in \d+(?:\.\d+)?s'
    + r'(?: \([^)]+\))?(?:\s*=+)?\s*', summary)
check(final_summary is not None, 'actual pytest summary is the last nonempty output line')
passed = re.findall(r'(\d+) passed', summary)
failed = re.findall(r'(\d+) failed', summary)
test_errors = re.findall(r'(\d+) errors?', summary)
skipped = re.findall(r'(\d+) skipped', summary)
deselected = re.findall(r'(\d+) deselected', summary)
warnings = re.findall(r'(\d+) warnings?', summary)
check(bool(passed) and int(passed[0]) == document['tests_passed'] > 0, 'passed count matches log')
check(not deselected or int(deselected[0]) == 0, 'no tests deselected in complete invocation')
if args.historical_failure:
    check(bool(failed) or bool(test_errors), 'failed pytest summary preserved')
else:
    check(not failed and not test_errors, 'no failures/errors in final pytest summary')
report_sha256 = sha(report_path)
script_sha256 = sha(Path(__file__))
result = {
    'status': ('PASS_HISTORICAL_FAILED_REGRESSION_BOUNDARY' if args.historical_failure
               else 'PASS_CURRENT_FULL_REGRESSION_FILE_LINKAGE') if not errors else 'FAIL',
    'scope': 'PURE_FILE_REVIEW_NO_PYTEST_COLLECTION_OR_EXECUTION',
    'review_script_sha256': script_sha256,
    'reviewed_report': {'path': str(report_path.relative_to(ROOT)), 'sha256': report_sha256},
    'unique_files_hashed': len(cache), 'source_file_count': len(actual_sources),
    'test_and_fixture_file_count': len(actual_tests), 'tests_passed': document['tests_passed'],
    'historical_failure': args.historical_failure,
    'current_source_binding_granted': not args.historical_failure and not current_file_drift,
    'current_file_drift': current_file_drift,
    'current_source_universe_matches': source_universe_matches,
    'current_test_universe_matches': test_universe_matches,
    'project_configuration_file_count': project_configuration_count,
    'current_project_configuration_universe_matches': configuration_universe_matches,
    'tests_failed': int(failed[0]) if failed else 0,
    'tests_errored': int(test_errors[0]) if test_errors else 0,
    'tests_skipped': int(skipped[0]) if skipped else 0,
    'tests_deselected': int(deselected[0]) if deselected else 0,
    'warnings': int(warnings[0]) if warnings else 0,
    'final_summary_is_last_nonempty_line': final_summary is not None,
    'pytest_final_summary': summary,
    'actual_command': document['full_suite_command'], 'errors': errors,
    'complete_tools_module_closure_granted': False,
    'complete_n1_granted': False, 'full_parity_granted': False, 'new_formal_granted': False,
}
(OUT / args.output).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
