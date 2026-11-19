"""One capacity-checked submission of the complete native candidate, never stage acceptance."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sys

from ..assets import ContractError, canonical_bytes, content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..planner.batch_execution import check_batch_execution
from ..supervisor import resource, timing_resource
from .batch_execution import run_batch_execution

SCHEMA = 'bmk.native-submission/1'
POLICY = 'configs/profiles/native_submission_v1.json'
RETENTION_KEYS = ('serialized_products_bytes', 'control_payload_bytes', 'operation_logs_bytes', 'shared_decoder_bytes')


def _estimate(plan, policy):
    view = plan['execution_binding']
    coverage = plan['admission_coverage']
    denominator = {'selections': coverage['selections'], 'routes': view['total_routes'],
                   'required': coverage['required_checks'], 'conditional': coverage['conditional_checks']}
    require(denominator == policy['required_denominator'] and view['bound_routes'] == view['total_routes'] and
            not view['unbound_obligations'] and not plan['unbound_controls'] and
            len(view['bound_obligations']) == sum(denominator[k] for k in ('required', 'conditional')),
            'native submission requires the complete first-batch denominator')
    drivers = view['drivers']
    require(drivers.keys() == {slot['product_slot'] for slot in plan['slots']} and len(drivers) == len(plan['slots']),
            'native submission driver coverage mismatch')
    operations = 0
    child_seconds = 0
    peak = dict.fromkeys(policy['process'], 0)
    for driver in drivers.values():
        steps = driver['operations']
        overrides = driver['configuration'].get('step_limits', {})
        require(overrides.keys() <= {step['label'] for step in steps}, 'native submission has an unused limit override')
        for step in steps:
            limits = overrides.get(step['label'], driver['process_limits'])
            operations += 1
            child_seconds += limits['wall_seconds']
            for key in peak:
                peak[key] = max(peak[key], limits[key])
    work = {'slots': len(drivers), 'operations': operations, 'sum_child_deadlines_seconds': child_seconds}
    require(all(value <= policy['work']['max_' + key] for key, value in work.items()),
            'native submission exceeds the declared work budget')
    require(all(value <= policy['process'][key] for key, value in peak.items()),
            'native submission exceeds the declared per-operation limit')
    retained = {key: plan['retention_bounds'][key] for key in RETENTION_KEYS}
    require(all(type(value) is int and value >= 0 for value in retained.values()), 'invalid native retention estimates')
    total = sum(retained.values())
    reservation = policy['retention']
    require(total <= reservation['max_planned_retained_bytes'], 'native submission exceeds the planned retention ceiling')
    return {'denominator': denominator, 'work': work, 'peak_declared_process_limits': peak,
            'retained_payload_ceiling_bytes': retained, 'planned_retained_bytes': total,
            'minimum_capacity': {'available_bytes': total + reservation['workspace_and_metadata_reserve_bytes'],
                                 'available_inodes': reservation['free_inodes_floor'],
                                 'host_memavailable_bytes': peak['address_space_bytes'] + reservation['host_memory_reserve_bytes']}}


def _predecessor(root, execution, relative):
    path = local_file(root, relative)
    audit = load_json(path)
    require(audit.get('schema') == 'bmk.native-qualification-audit/1' and
            audit.get('scope') == 'candidate_evidence_only' and audit.get('definition_stage') == 'M0' and
            audit.get('qualification_granted') is False and audit.get('stage_accepted') is False and
            audit.get('timing_admitted') is False, 'predecessor is not an unaccepted M0 candidate audit')
    blockers = set(audit.get('formal_blockers', []))
    require({'candidate_submission_not_formal', 'predecessor_acceptance_not_bound',
             'formal_work_limits_and_retention_policy_not_bound'} <= blockers,
            'predecessor audit does not expose the required formal blockers')
    previous = audit.get('run', {})
    require(previous.get('plan_content_id') == execution.get('plan_content_id') and
            previous.get('build_id') == execution.get('build', {}).get('build_id'),
            'predecessor audit is for a different candidate build or plan')
    coverage = audit.get('coverage', {})
    require(coverage.get('routes') == 36 and coverage.get('obligations') == 186 and
            coverage.get('product_slots') == 200 and coverage.get('recovery', {}).get('restored') == 174,
            'predecessor audit coverage is incomplete')
    audit_id = audit.get('audit_id')
    require(isinstance(audit_id, str) and audit_id == content_id({k:v for k,v in audit.items() if k != 'audit_id'}),
            'predecessor audit identity is invalid')
    return {'path': relative, 'sha256': digest(path), 'audit_id': audit_id,
            'run_id': previous['run_id'], 'run_plan_id': previous['plan_content_id'],
            'build_id': previous['build_id'], 'formal_blockers': sorted(blockers)}

def plan_native_submission(root: Path, execution: dict, predecessor: str) -> dict:
    contract = load_contract(root, 'native-submission-policy')
    policy = load_json(local_file(root, POLICY))
    contract.validate(policy, POLICY)
    require(isinstance(execution, dict) and execution.get('suite') == policy['suite'],
            'native submission requires the complete extended-v20 native execution plan')
    check_batch_execution(execution)
    require(isinstance(predecessor, str) and predecessor, 'native submission requires a predecessor audit')
    predecessor_ref = _predecessor(root, execution, predecessor)
    require(execution['purpose'] == 'native_admission_execution_candidate', 'not a native admission execution candidate')
    body = {'schema': SCHEMA, 'purpose': policy['scope'], 'stage_accepted': False, 'qualification_granted': False,
            'policy': policy, 'policy_schema_id': contract.document_id,
            'gate_code': {path: digest(local_file(root, path)) for path in (
                'src/tsbench/application/native_submission.py', 'src/tsbench/supervisor/resource.py',
                'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/contracts.py')},
            'estimate': _estimate(execution, policy), 'predecessor': predecessor_ref, 'execution': execution}
    return {**body, 'plan_content_id': content_id(body)}


def _capacity_gate(reading, minimum):
    disk = reading['disk']
    require(disk is not None and disk['available_inodes'] is not None,
            'native submission cannot measure results filesystem capacity')
    require(disk['available_bytes'] >= minimum['available_bytes'], 'native submission results filesystem bytes below reserve')
    require(disk['available_inodes'] >= minimum['available_inodes'], 'native submission results filesystem inodes below reserve')
    ram = reading['host_memavailable_bytes']
    require(ram is not None and ram >= minimum['host_memavailable_bytes'],
            'native submission host MemAvailable below reserve or unobservable')


@contextmanager
def _reserve_results(results):
    # Lock the directory inode rather than writing a per-run lock/receipt. This
    # also coordinates submitters in different mount namespaces sharing this directory.
    fd = os.open(results, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError('native submission results directory already reserved') from exc
        yield os.fstat(fd).st_dev
    finally:
        os.close(fd)


def run_native_submission(root: Path, submission: dict, results: Path, *, cancelled=lambda: False) -> dict:
    """Admission holds the cooperative lock across the real executor, without changing sealed historical runs."""
    require(sys.platform == 'linux', 'native submission needs Linux resource checks and isolated workers')
    require(isinstance(submission, dict) and submission.get('schema') == SCHEMA and 'execution' in submission,
            'not a native submission plan')
    expected = plan_native_submission(root, submission['execution'], submission.get('predecessor', {}).get('path'))
    require(canonical_bytes(expected) == canonical_bytes(submission), 'native submission plan or resource policy drift')
    require(results.is_dir() and not results.is_symlink(), 'native submission results directory must already exist and not be a symlink')
    results = results.resolve(strict=True)
    with timing_resource.reserve(), _reserve_results(results) as device:
        require(not cancelled(), 'native submission cancelled before run creation')
        reading = resource.sample(results)
        _capacity_gate(reading, expected['estimate']['minimum_capacity'])
        require(reading['disk']['device'] == device, 'native submission output mount changed during preflight')
        # The native executor re-resolves the local source/config/build and compares the whole
        # plan before staging its ELF closures. It alone creates the run ID and the main ledger.
        report = run_batch_execution(root, expected['execution'], results, cancelled=cancelled)
    require(report['plan_content_id'] == expected['execution']['plan_content_id'], 'native run plan differs from submission')
    return {'schema': 'bmk.native-submission-report/1', 'submission_plan_id': expected['plan_content_id'],
            'run_id': report['run_id'], 'run_plan_id': expected['execution']['plan_content_id'],
            'prelaunch_capacity': reading, 'estimate': expected['estimate'], 'capacity_scope': 'advisory_prelaunch_not_a_quota',
            'reservation': [timing_resource.RESERVATION, 'exclusive_cooperative_results_directory_flock'],
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False,
            'all_product_expectations_met': report['all_product_expectations_met'], 'execution_report': report}
