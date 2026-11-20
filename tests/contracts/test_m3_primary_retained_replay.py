from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import audit_m3_primary_retained_replay as replay
from audit_m3_primary_retained_replay import FIXED, FLAGS, LZBENCH, PBEPLA, ZFP, ZFP_ISOLATED, ZFP_SCOPE, audit, reconcile
from tsbench.assets import ContractError, canonical_bytes, content_id, digest


@pytest.fixture
def objects():
    return {p: {'path': p, 'bytes': 4, 'sha256': s * 64} for p, s in
            [('fixed-batch-samples/b.bmk', 'b'), ('retained/item/seen', 'c'), ('retained/item/missing', 'd')]}


def proof(path, schema, **fields):
    doc = {'schema': schema, 'run_id': 'run', **dict.fromkeys(FLAGS, False), **fields}
    if schema in (LZBENCH, PBEPLA, ZFP, ZFP_ISOLATED):
        doc.update(plan_id='plan', run_seal_id=doc.pop('seal', 'seal'))
        doc['audit_id'] = content_id(doc)
    path.write_bytes(canonical_bytes(doc))
    return path


def test_counts_only_consumed_files_and_deduplicates_backend_replays(tmp_path, objects):
    batch, done, missing = objects.values()
    fixed = proof(tmp_path / 'fixed', FIXED, plan_content_id='plan', seal_id='seal',
                  replay_performed=True, partial_preflight=None, unique_retained_frames=1,
                  source_projection='complete_frozen_population_from_sealed_ledger',
                  replayed=[{'artifact': batch}, {'artifact': batch}])
    lz = proof(tmp_path / 'lz', LZBENCH, replayed_files=[done], specialized={'artifact': missing})
    a = reconcile(tmp_path, 'run', 'plan', 'seal', objects, [lz, fixed])
    assert a == reconcile(tmp_path, 'run', 'plan', 'seal', objects, [fixed, lz])
    assert a['replayed_physical_files'] == 2 and a['replayed_physical_bytes'] == 8
    assert a['unreplayed_physical_paths'] == [missing['path']]
    assert a['proofs'][0]['replay_reference_count'] == 2


@pytest.mark.parametrize('fault,message', [('foreign', 'foreign'), ('wrong_identity', 'changed'),
                                           ('duplicate', 'double counts'), ('not_replayed', 'inventory-only'),
                                           ('tampered', 'content identity')])
def test_rejects_bad_proofs(tmp_path, objects, fault, message):
    batch, done, _ = objects.values()
    fixed = proof(tmp_path / 'fixed', FIXED, plan_content_id='plan', seal_id='seal',
                  replay_performed=fault != 'not_replayed', partial_preflight=False,
                  replayed=[{'artifact': batch}], unique_retained_frames=1)
    obj = batch if fault == 'duplicate' else {**done, 'bytes': 17} if fault == 'wrong_identity' else done
    lz = proof(tmp_path / 'lz', LZBENCH, seal='different' if fault == 'foreign' else 'seal', replayed_files=[obj])
    if fault == 'tampered':
        lz.write_bytes(lz.read_bytes().replace(b'"bytes":4', b'"bytes":5'))
    with pytest.raises(ContractError, match=message):
        reconcile(tmp_path, 'run', 'plan', 'seal', objects, [fixed, lz])


def test_audit_recomputes_inventory_and_requires_real_seal(tmp_path):
    run = tmp_path / 'run'
    sample = run / 'retained/item/frame'
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b'frame')
    row = dict(work_item_id='item', dataset_id='d', selection=1, route='route', operation='decode',
               applicability='input_domain_matches', status='verified')
    plan = {'work_items': [row]}
    plan['plan_content_id'] = content_id(plan)
    ref = {'path': sample.relative_to(run).as_posix(), 'bytes': 5, 'sha256': digest(sample)}
    ledger = run / 'ledger.jsonl'
    ledger.write_bytes(canonical_bytes({**row, 'evidence': {'sample': ref}}) + b'\n')
    report = run / 'report.json'
    report.write_bytes(b'{}')
    with pytest.raises(ContractError, match='completion.json'):
        audit(tmp_path, plan, run, [])
    seal = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    (run / 'completion.json').write_bytes(canonical_bytes({**seal, 'seal_id': content_id(seal)}))
    coverage = audit(tmp_path, plan, run, [])
    assert coverage['unreplayed_physical_paths'] == [ref['path']]
    assert all(not coverage[key] for key in FLAGS)
    sample.write_bytes(b'alter')
    with pytest.raises(ContractError, match='SHA-256 mismatch'):
        audit(tmp_path, plan, run, [])


@pytest.mark.parametrize('failure,message', [(None, None), ('duplicate-session', 'session or frame'),
    ('mount', 'mount, shape or aligned rate'), ('rate', 'mount, shape or aligned rate'),
    ('missing-frame', 'omitted a retained frame'), ('old-and-new', 'duplicate M3 replay evidence family'),
    ('wrong-launchers', 'runtime or launchers differ')])
def test_isolated_zfp_reconciles_each_frame_without_counting_metadata_as_a_process(tmp_path, monkeypatch, failure, message):
    parts = {n: {'path': f'retained/item/{n}', 'bytes': 32, 'sha256': s * 64}
             for n, s in [('before', 'a'), ('after', 'b'), ('metadata.json', 'c')]}
    inventory = {ref['path']: ref for ref in parts.values()}
    sample = {'route': 'fixed-rate-array', 'sample': {'parts': parts, 'row_range': [10, 18]}, 'processes': []}
    for name in ('before', 'after'):
        proc = {'part': name, 'operation': 'array-reopen', 'session_id': name,
                'input_mounts': {'frame': {k: parts[name][k] for k in ('bytes', 'sha256')}},
                'logs': {'stderr': {'bytes': 0}}, 'restored': {'bytes': 64},
                'observed': {'rows': 8, 'frame_bytes': 32, 'requested_rate': 18, 'effective_rate': 32}}
        sample['processes'].append(proc)
    if failure == 'duplicate-session':
        sample['processes'][1]['session_id'] = 'before'
    if failure == 'mount':
        sample['processes'][1]['input_mounts']['original'] = parts['before']
    if failure == 'rate':
        sample['processes'][1]['observed']['effective_rate'] = 18
    if failure == 'missing-frame':
        sample['processes'].pop()
    runtime = {'recovery_id': 'runtime'}
    native = {'executable': {'path': 'exe', 'sha256': 'a' * 64},
              'dependency': {'path': 'libzfp_native_c.so', 'sha256': 'b' * 64}, 'launchers': {'bwrap': 'locked'}}

    def check_recovery(spec, build, methods, *, tools, libraries):
        assert spec == runtime and not build and not methods
        assert tools == {'zfp-corpus-reopen': native['executable']} and libraries == [native['dependency']]

    monkeypatch.setattr(replay, 'check_recovery', check_recovery)
    new = proof(tmp_path / 'zfp', ZFP_ISOLATED, replayed_samples=[sample], replayed_physical_files=3,
                isolated_corpus_processes=2, corpus_replay_scope=ZFP_SCOPE, corpus_replay_runtime_id='runtime',
                corpus_replay_runtime=runtime, corpus_replay_launchers={} if failure == 'wrong-launchers' else native['launchers'])
    proofs = [new]
    if failure == 'old-and-new':
        proofs.append(proof(tmp_path / 'legacy-zfp', ZFP, replayed_samples=[sample], replayed_physical_files=3))
    args = (tmp_path, 'run', 'plan', 'seal', inventory, proofs)
    if message:
        with pytest.raises(ContractError, match=message):
            reconcile(*args, zfp_binding=native)
    else:
        result = reconcile(*args, zfp_binding=native)
        assert result['replayed_physical_files'] == 3 and not result['unreplayed_physical_paths']
        assert result['proofs'][0]['zfp_frame_isolation'] == {'scope': ZFP_SCOPE, 'frame_only_processes': 2,
            'isolated_frames': 2, 'validated_metadata_files_not_mounted': 1}


def test_pbepla_sample_without_restoration_remains_unreplayed(tmp_path, objects):
    _, restored, missing = objects.values()
    report = proof(tmp_path / 'pbepla', PBEPLA, replayed_physical_files=1, replayed_samples=[
        {'decoded': True, 'sample': {'parts': [restored]}}, {'decoded': False, 'sample': {'parts': [missing]}}])
    result = reconcile(tmp_path, 'run', 'plan', 'seal', objects, [report])
    assert result['replayed_physical_files'] == 1 and missing['path'] in result['unreplayed_physical_paths']
