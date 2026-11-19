"""Recompute and sign the M0 freeze/skeleton receipt, never native qualification."""
from pathlib import Path
import re

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..planner.service_scope import verify_service_plan
from ..qualification.native_evidence import audit_native_qualification
from .batch_execution import audit_batch_execution

SCHEMA = 'bmk.m0-stage-receipt/1'
RECEIPT_CONTRACT = 'stage-receipt'


def _dir(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            'M0 evidence directory must be project-relative')
    path = (root / relative).resolve(strict=True)
    require(path.is_relative_to(root.resolve()) and path.is_dir() and not path.is_symlink(),
            f'invalid M0 evidence directory: {relative}')
    return path


def _file_ref(root, relative):
    path = local_file(root, relative)
    return {'path': relative, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def _run_dir(root, result_dir, run_id):
    require(isinstance(run_id, str) and re.fullmatch(r'[0-9a-f]{32}', run_id), 'invalid candidate run ID')
    matches = [p.parent for p in result_dir.rglob('seal.json') if p.parent.name == run_id]
    require(len(matches) == 1, 'M0 result must contain exactly one sealed candidate run')
    return matches[0]


def _check_native(root, relative):
    report = load_json(local_file(root, relative))
    require(report.get('schema') == 'bmk.native-submission-report/1' and
            report.get('stage_accepted') is False and report.get('qualification_granted') is False and
            report.get('timing_admitted') is False and report.get('all_product_expectations_met') is True,
            'native submission is not a complete unaccepted candidate')
    execution = report.get('execution_report', {})
    require(execution.get('planned_products') == 200 and execution.get('terminal_counts') ==
            {'verified': 174, 'expected_rejection': 26} and execution.get('stage_accepted') is False and
            execution.get('qualification_granted') is False and execution.get('timing_admitted') is False,
            'native candidate denominator or status differs from M0 freeze')
    return report


def audit_m0(root: Path, *, native_submission: str, service_plan: str, corpus_check: str,
             feature_report: str, source_check: str, build_result: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    source = load_json(local_file(root, source_check))
    require(source.get('sources_lock_id') and source.get('sources') == 11 and source.get('selections') == 12 and
            source.get('verified_assets') >= 35, 'M0 source closure is incomplete')
    corpus = load_json(local_file(root, corpus_check))
    require(corpus.get('corpus_id') and corpus.get('datasets') == 6 and corpus.get('source_clusters') == 6 and
            corpus.get('partitions') == 18 and corpus.get('rows') == 222574 and
            corpus.get('missing_domains') == [] and corpus.get('canonical_audit_performed') is True,
            'M0 corpus closure is incomplete')
    features = load_json(local_file(root, feature_report))
    require(features.get('schema') == 'bmk.corpus-feature-report/3' and
            features.get('evidence_scope') == 'descriptive_not_qualification' and
            len(features.get('datasets', [])) == 6, 'M0 feature report is not the frozen descriptive report')
    verification = verify_service_plan(root, load_json(local_file(root, service_plan)))
    coverage = verification['coverage']
    require(verification['verified_definition'] is True and verification['runnable'] is False and
            verification['stage_accepted'] is False and verification['qualification_granted'] is False and
            coverage == {'selections': 12, 'groups': 17, 'atomic_requirements': 22, 'display_cells': 204,
                         'atomic_relations': 264, 'cases': 47, 'case_obligations': 564,
                         'rejection_obligations': 132, 'executed': 0, 'qualified': 0, 'unrun': 564},
            'M0 service definition or denominator differs')
    native = _check_native(root, native_submission)
    result_dir_relative = build_result
    result_dir = _dir(root, result_dir_relative)
    run = _run_dir(root, result_dir, native['run_id'])
    candidate_report = audit_batch_execution(run)
    require(candidate_report['run_id'] == native['run_id'] and candidate_report['restored_products'] == 174,
            'M0 sealed candidate audit failed')
    # Check the two independent derived reports are byte-identical to their sealed run.
    recomputed = local_file(root, f'{build_result}/recomputed.json')
    reported = local_file(root, f'{build_result}/report.json')
    require(recomputed.read_bytes() == reported.read_bytes(), 'M0 candidate report does not replay byte-for-byte')
    build = load_json(local_file(root, f'{build_result}/build/build-lock.json'))
    require(isinstance(build.get('build_id'), str) and re.fullmatch(r'[0-9a-f]{64}', build['build_id']),
            'M0 build lock is missing')
    env = load_json(local_file(root, 'environment/tsbench-linux-64.lock.json'))
    require(env.get('schema') == 'bmk.conda-environment/1' and env.get('environment') == 'tsbench',
            'M0 environment lock is not tsbench')
    evidence = {
        'sources': _file_ref(root, source_check), 'corpus': _file_ref(root, corpus_check),
        'features': _file_ref(root, feature_report), 'service_definition': _file_ref(root, service_plan),
        'native_submission': _file_ref(root, native_submission),
        'build_lock': _file_ref(root, f'{build_result}/build/build-lock.json'),
        'ctest_log': _file_ref(root, f'{build_result}/ctest.log'),
        'python_log': _file_ref(root, f'{build_result}/python.log'),
        'candidate_run': {'run_id': native['run_id'], 'path': f'{build_result}/runs/{native["run_id"]}',
                          'run_plan_id': native['run_plan_id']},
        'environment': _file_ref(root, 'environment/tsbench-linux-64.lock.json')}
    open_items = [
        '首批 36 条原生路线仍是候选证据，M3 原生资格尚未签发',
        'ALP AVX512BW 仍需在兼容宿主完成条件执行',
        'CORAD 冻结质量合同的当前部署结果保持拒绝，不得改写为通过',
        'block_boundary/cache_inside/cache_outside/resource_refusal 等特征由后续正式方法合同绑定',
        '204 展示格和 264 原子关系属于 M5 服务执行范围，当前 564 项保持未运行',
        'M1–M4 仍须按本收据之后的顺序分别冻结和验收'
    ]
    body = {'schema': SCHEMA, 'stage': 'M0', 'stage_accepted': True,
            'qualification_granted': False, 'timing_admitted': False,
            'scope': 'freeze_contracts_and_independent_engineering_skeleton',
            'evidence': evidence, 'open_items': open_items}
    document = {**body, 'receipt_id': content_id(body)}
    contract.validate(document, 'M0 stage receipt')
    return document
