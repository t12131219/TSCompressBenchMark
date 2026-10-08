"""A registry refresh must retain provenance checks and recover from failure."""
from pathlib import Path
import hashlib
import json
import runpy
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def updater(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'tools'))
    return runpy.run_path(str(ROOT/'tools/refresh_native_sdk_registration.py'))


@pytest.fixture
def sdk_evidence(updater,tmp_path,monkeypatch):
    import audit_fast_differential_native
    context = updater['checked_sdk_report'].__globals__
    monkeypatch.setitem(context,'ROOT',tmp_path)
    native = {'status':'PASS','native_observation_identity':'test-only'}
    monkeypatch.setattr(audit_fast_differential_native,'audit',lambda:native)
    implementation = tmp_path/'src/implementation.py'
    implementation.parent.mkdir();implementation.write_text('VERSION = 1\n')
    junit = tmp_path/'build/source-audits/fast-differential-sdk/pytest.xml'
    junit.parent.mkdir(parents=True)
    junit.write_text('<testsuites><testsuite tests="103" failures="0" errors="0" skipped="0"/></testsuites>')
    digest = lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    snapshot = [{'path':'src/implementation.py','sha256':digest(implementation)}]
    report = {'status':'PASS','native_current_audit':native,'source_snapshot':snapshot,
              'source_snapshot_sha256':hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest(),
              'junit_sha256':digest(junit),'test_totals':{'tests':103,'failures':0,'errors':0,'skipped':0}}
    (junit.parent.parent/'fast-differential-sdk-tests.json').write_text(json.dumps(report))
    assert updater['checked_sdk_report']('fast-differential') == report
    return implementation,junit


def test_pass_report_cannot_refresh_modified_execution_source(updater,sdk_evidence):
    implementation,_ = sdk_evidence
    implementation.write_text('VERSION = 2\n')
    with pytest.raises(RuntimeError,match='source dependency drift'):
        updater['checked_sdk_report']('fast-differential')


def test_pass_report_cannot_refresh_modified_test_results(updater,sdk_evidence):
    _,junit = sdk_evidence
    junit.write_text(junit.read_text()+'\n')
    with pytest.raises(RuntimeError,match='test output absent or stale'):
        updater['checked_sdk_report']('fast-differential')


def test_factory_failure_restores_all_registry_bytes(updater,tmp_path,monkeypatch):
    context = updater['main'].__globals__
    monkeypatch.setitem(context,'ROOT',tmp_path)
    monkeypatch.setitem(context,'checked_sdk_report',lambda family:{'status':'PASS'})
    key = 'fast-differential-u32'
    originals = {}
    for kind in ('codecs','onboarding'):
        relative = f'registry/{kind}/{key}.json'
        destination = tmp_path/relative;destination.parent.mkdir(parents=True)
        destination.write_bytes((ROOT/relative).read_bytes())
        originals[destination] = destination.read_bytes()
    document = json.loads((ROOT/f'registry/codecs/{key}.json').read_text())
    for source in (ROOT/'registry/sources').glob('*.json'):
        # Registry metadata is copied, not the upstream source tree.
        destination = tmp_path/'registry/sources'/source.name
        destination.parent.mkdir(exist_ok=True);shutil.copy2(source,destination)
    artifact = Path(document['adapter']['artifact_path'])
    for profile in ('release','debug','sanitizer'):
        directory = artifact.parent.parent/profile
        destination = tmp_path/directory;destination.mkdir(parents=True)
        for name in ('build-record.json',artifact.name):
            shutil.copy2(ROOT/directory/name,destination/name)
    card = json.loads((ROOT/f'registry/onboarding/{key}.json').read_text())
    for test in card['upstream_tests']:
        destination = tmp_path/test['evidence'];destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/test['evidence'],destination)
    import tscompbench.adapters.factory
    def rejected(*args):
        raise RuntimeError('intentional dependency drift')
    monkeypatch.setattr(tscompbench.adapters.factory,'create_adapter',rejected)
    monkeypatch.setattr('sys.argv',['refresh_native_sdk_registration.py','--family',
                                  'fast-differential','--suffix','rollback-test'])
    with pytest.raises(RuntimeError,match='intentional dependency drift'):
        updater['main']()
    assert all(path.read_bytes() == content for path,content in originals.items())
    report = json.loads((tmp_path/'build/source-audits/native-sdk-registry-refresh-rollback-test/report.json').read_text())
    assert report['status'] == 'FAIL' and report['rolled_back'] is True
