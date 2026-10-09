"""Refresh qualified execution evidence without changing codec/source contracts.

Run the existing native and direct SDK qualifications first. This tool never
relaxes the factory's dependency checks or updates a stale SDK snapshot by hand.
Prior registry documents are retained alongside the refresh report.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {
    'fast-differential': ('fast-differential-u32',),
    'maskedvbyte': ('maskedvbyte-u32', 'delta-maskedvbyte-u32'),
    'simdcomp': ('simdcomp-u32', 'delta-simdcomp-u32', 'for-simdcomp-u32'),
    'fastpfor-simple': ('simple9-u28', 'simple9hacked-u28', 'simple16-u28'),
    'streamvbyte': ('streamvbyte-u32', 'delta-zigzag-streamvbyte64'),
    'streamvbyte-modern': ('streamvbyte-modern-u32', 'delta-zigzag-streamvbyte-modern64'),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_sdk_report(family: str, report_path: Path | None = None) -> dict | None:
    if family == 'fast-differential':
        from audit_fast_differential_native import audit
        native = audit()
        path = ROOT/'build/source-audits/fast-differential-sdk-tests.json'
        report = json.loads(path.read_text())
        require(report['native_current_audit'] == native, 'SDK native evidence stale')
        require(report['test_totals']['tests'] >= 103 and
                all(report['test_totals'][k] == 0 for k in ('failures','errors','skipped')),
                'direct SDK qualification incomplete')
        junit = ROOT/'build/source-audits/fast-differential-sdk/pytest.xml'
        totals = {field:sum(int(s.get(field,'0')) for s in ET.parse(junit).getroot().findall('testsuite'))
                  for field in ('tests','failures','errors','skipped')}
        require(sha(junit) == report['junit_sha256'] and totals == report['test_totals'],
                'SDK test output absent or stale')
    elif family in ('maskedvbyte', 'simdcomp', 'fastpfor-simple'):
        import importlib
        module = importlib.import_module({
            'maskedvbyte': 'audit_maskedvbyte_sdk',
            'simdcomp': 'audit_simdcomp_sdk',
            'fastpfor-simple': 'audit_fastpfor_simple_sdk',
        }[family])
        if report_path is not None:
            require(family in ('simdcomp', 'fastpfor-simple', 'maskedvbyte'), 'report override unsupported')
            module.audit(ROOT, report_path)
        else:
            module.audit()
        name = {'maskedvbyte':'maskedvbyte-sdk-tests.json',
                'simdcomp':'simdcomp_sdk_tests.json',
                'fastpfor-simple':'fastpfor_simple_sdk_tests.json'}[family]
        if report_path is None:
            key = FAMILIES[family][0]
            card = json.loads((ROOT / f'registry/onboarding/{key}.json').read_text())
            tests = [item for item in card['upstream_tests'] if item['name'] == 'direct_sdk']
            path = ROOT / tests[0]['evidence'] if len(tests) == 1 else ROOT/'build/source-audits'/name
        else:
            path = report_path
        report = json.loads(path.read_text())
    else:
        return None
    require(report['status'] == 'PASS', 'direct SDK qualification failed')
    require(hashlib.sha256(json.dumps(report['source_snapshot'],sort_keys=True).encode()).hexdigest()
            == report['source_snapshot_sha256'], 'SDK snapshot digest differs')
    for item in report['source_snapshot']:
        require(sha(ROOT/item['path']) == item['sha256'], 'SDK source dependency drift')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family', choices=(*FAMILIES, 'all'), default='all')
    parser.add_argument('--suffix', required=True)
    parser.add_argument('--sdk-report', type=Path)
    args = parser.parse_args()
    require(args.suffix and Path(args.suffix).name == args.suffix and args.suffix not in ('.','..'),
            'unsafe refresh suffix')
    output = ROOT/'build/source-audits'/f'native-sdk-registry-refresh-{args.suffix}'
    require(not output.exists(), 'preserve previous registry refresh')
    families = FAMILIES if args.family == 'all' else {args.family:FAMILIES[args.family]}
    require(args.sdk_report is None or args.family in ('simdcomp', 'fastpfor-simple', 'maskedvbyte'),
            'SDK report override requires one supported family')
    report_path = args.sdk_report.resolve() if args.sdk_report else None
    if report_path is not None:
        report_path.relative_to(ROOT)
    sdk = {family:(checked_sdk_report(family, report_path) if report_path is not None
                   else checked_sdk_report(family)) for family in families}
    registry = CodecRegistry(ROOT/'registry/codecs', SourceRegistry(ROOT/'registry/sources'))
    staged = []
    identities = []
    for family, keys in families.items():
        for key in keys:
            manifest_path = ROOT/f'registry/codecs/{key}.json'
            card_path = ROOT/f'registry/onboarding/{key}.json'
            document = json.loads(manifest_path.read_text())
            previous = copy.deepcopy(document)
            if family in ('simdcomp','fastpfor-simple'):
                document['adapter']['python_source_closure'] = sdk[family]['source_snapshot']
            # Only the existing Python consumption snapshot may change.
            expected = copy.deepcopy(document)
            if family in ('simdcomp','fastpfor-simple'):
                expected['adapter']['python_source_closure'] = previous['adapter']['python_source_closure']
            require(expected == previous, 'codec contract changed during evidence refresh')
            card = json.loads(card_path.read_text())
            card.pop('source_onboarding_id', None)
            artifact = ROOT/document['adapter']['artifact_path']
            for build in card['builds']:
                directory = artifact.parent.parent/build['kind']
                record = json.loads((directory/'build-record.json').read_text())
                require(record.get('status','PASS') == 'PASS' and
                        sha(directory/artifact.name) == record['artifact_sha256'],
                        'native build failed or binary drifted')
                build['artifact_sha256'] = record['artifact_sha256']
                build['compile_commands_sha256'] = record['compile_commands_sha256']
            for test in card['upstream_tests']:
                if report_path is not None and test['name'] == 'direct_sdk':
                    test['evidence'] = str(report_path.relative_to(ROOT))
                evidence_path = ROOT/test['evidence']
                evidence = json.loads(evidence_path.read_text())
                # These raw observations are qualified by the independent SDK
                # auditors above; their original diagnostic status is retained.
                observation_states = {
                    'simdcomp_avx2_source_tests.json':'OBSERVATIONS_COMPLETE',
                    'fastpfor_simple_upstream_tests.json':'ORIGINAL_FULL_UPSTREAM_UNIT_RELEASE_ASSERTIONS_ENABLED_PASS',
                    'fastpfor_simple_source_tests.json':'SOURCE_PROBES_COMPLETED_KNOWN_UNSAFE_API_PENDING_BOUNDED_SHIM',
                    'fastpfor_simple_native_tests.json':'BOUNDED_ABI_MATRIX_AND_FAULT_TESTS_EXECUTED_INDEPENDENT_AUDIT_PENDING',
                }
                expected_status = observation_states.get(evidence_path.name,'PASS')
                require(test['status'] == 'PASS' and evidence['status'] == expected_status,
                        'qualification evidence failed: '+test['evidence'])
                test['log_sha256'] = sha(evidence_path)
            card = validate_onboarding_card(card)
            identities.append({'key':key,'previous_algorithm_id':registry.get(key).algorithm_id,
                               'source_artifact_id':registry.get(key).source_artifact_id})
            staged.extend(((manifest_path,document),(card_path,card)))
    output.mkdir(parents=True)
    for target, document in staged:
        for kind, content in [('before',target.read_bytes()),
                              ('candidate',(json.dumps(document,indent=2)+'\n').encode())]:
            destination = output/kind/target.relative_to(ROOT)
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(content)
    proposed = CodecRegistry(output/'candidate/registry/codecs', SourceRegistry(ROOT/'registry/sources'))
    for identity in identities:
        current = proposed.get(identity['key'])
        require(current.source_artifact_id == identity['source_artifact_id'], 'source identity changed')
        identity['current_algorithm_id'] = current.algorithm_id
    for target, _ in staged:
        target.write_bytes((output/'candidate'/target.relative_to(ROOT)).read_bytes())
    try:
        registry = CodecRegistry(ROOT/'registry/codecs', SourceRegistry(ROOT/'registry/sources'))
        registry.verify_all()
        from tscompbench.adapters.factory import create_adapter
        from streamvbyte_audit_common import audit_source
        for identity in identities:
            manifest = registry.get(identity['key'])
            if 'streamvbyte' in identity['key']:
                audit_source(ROOT,registry,manifest)
            session = create_adapter(ROOT,manifest).create_session({})
            session.close()
    except Exception as error:
        for target, _ in staged:
            target.write_bytes((output/'before'/target.relative_to(ROOT)).read_bytes())
        (output/'report.json').write_text(json.dumps({'status':'FAIL','rolled_back':True,
                                                     'error':str(error)},indent=2)+'\n')
        raise
    report = {'status':'PASS','identities':identities,'source_ids_preserved':True,
              'scope':'QUALIFIED_EXECUTION_EVIDENCE_REFRESH_NOT_FORMAL_BENCHMARK',
              'factory_dependency_checks_preserved':True}
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
