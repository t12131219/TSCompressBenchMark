from hashlib import sha256
import struct

import pytest

from tsbench.application import m3_gorilla_corpus_clock as clock
from tsbench.application.m3_gorilla import HEADER, LENGTH, MAGIC, PAIR
from tsbench.assets import ContractError, digest
from tsbench.supervisor import gorilla_corpus_clock as launcher


def test_snapshot_log_spans_and_geometry():
    case = {'route': 'append-resume', 'columns': 1, 'rows': 513, 'units': 2, 'artifact_bytes': 53,
            'snapshot_bytes': 41}
    enc = {'rows': 513, 'cols': 1, 'units': [[0, 0, 512, 20, 256, 11, 84, 16, 1, 2, 3, 4, 5],
                                           [0, 512, 1, 5, 0, 2, 16, 16, 2, 3, 4, 5, 6]]}
    snap = {'rows': 513, 'cols': 1, 'units': [[0, 0, 256, 11, 10], [0, 512, 0, 2, 11]]}
    progress = sha256()
    for unit in enc['units']:
        clock._commit(progress, unit[:8])
    case['state_progress_sha256'] = progress.hexdigest()
    assert clock._metrics(case, 'encode', enc) == {'prefix_append': 3, 'snapshot': 5, 'resume': 7,
                                                    'tail_append': 9, 'finish': 11}
    assert clock._metrics(case, 'snapshot_decode', snap) == {'snapshot_decode': 21}
    enc['units'][0][7] += 1
    with pytest.raises(ContractError, match='state progress differs'):
        clock._metrics(case, 'encode', enc)
    snap['units'][1][2] = 1
    with pytest.raises(ContractError, match='block differs'):
        clock._metrics(case, 'snapshot_decode', snap)


def test_iter_product_binds_seek_and_bit_exact_recovery(tmp_path):
    source, archives, restored = (tmp_path / s for s in ('in', 'fixed', 'out'))
    for folder in (source, archives, restored):
        folder.mkdir()
    # Includes a repeated timestamp and distinct +/- zero payloads.
    samples = [(1000, 0), (2000, 1 << 63), (2000, 0)]
    raw = b''.join(PAIR.pack(*x) for x in samples)
    (source / 'axis.ms').write_bytes(struct.pack('<3q', *(x[0] for x in samples)))
    (source / 'column-0000.bin').write_bytes(struct.pack('<3Q', *(x[1] for x in samples)))
    out = restored / 'column-0000.tv'
    out.write_bytes(raw)
    frame = b'\x00\x03\x01'  # Shape-only fixture; native wire round-trip is separate.
    (archives / 'frame.gtv1').write_bytes(HEADER.pack(MAGIC, 1, 3) + LENGTH.pack(len(frame)) + frame)
    want = {'column': 0, 'row_range': [0, 3], 'native_frame_bytes': len(frame),
            'frame_sha256': sha256(frame).hexdigest(), 'restored_tv_sha256': sha256(raw).hexdigest(),
            'forward_seek': {'target_ms': 2000, 'first_at_or_after_index_within_chunk': 1,
                             'timestamp_ms': 2000, 'value_bits': 1 << 63}}
    proof = sha256()
    clock._commit(proof, want)
    case = {'columns': 1, 'rows': 3, 'units': 1, 'route': 'iterator', 'block_facts_sha256': proof.hexdigest()}
    enc = {'units': [[0, 0, 3, len(frame), 123]]}
    dec = {'units': [[0, 0, 3, len(frame), 1, 2, 3, 2000, 2000, 1 << 63]]}
    assert clock._verify_products(case, source, archives, enc, (restored, dec)) == proof.hexdigest()
    clock._verify_restored_direction(case, 'decode', source, archives / 'frame.gtv1', restored, dec)
    dec['units'][0][-1] = 0
    with pytest.raises(ContractError, match='seek differs'):
        clock._verify_products(case, source, archives, enc, (restored, dec))
    with pytest.raises(ContractError, match='seek differs'):
        clock._verify_restored_direction(case, 'decode', source, archives / 'frame.gtv1', restored, dec)
    dec['units'][0][-1] = 1 << 63
    out.write_bytes(raw[:-1] + b'\xff')
    with pytest.raises(ContractError, match='recovery differs'):
        clock._verify_products(case, source, archives, enc, (restored, dec))


def test_files_only_launcher_accepts_large_fixed_frame_not_source_or_directory(tmp_path, monkeypatch):
    bundle, scratch = tmp_path / 'runtime', tmp_path / 'scratch'
    scratch.mkdir()
    loader = 'lib/ld-linux-x86-64.so.2'
    files = {}
    for name in (launcher.TOOL, launcher.LIBRARY, loader):
        file = bundle / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(name.encode())
        files[name] = {'bytes': file.stat().st_size, 'sha256': digest(file),
                       'needed': ['libgorilla_c.so'] if name == launcher.TOOL else []}
    spec = {'loader': loader, 'tools': {'gorilla': launcher.TOOL}, 'files': files}
    frame = tmp_path / 'big.gtv1'
    with frame.open('wb') as f:
        f.truncate((8 << 20) + 1)
    monkeypatch.setattr(launcher, 'invoke', lambda argv, *a, **kw: {
        'pid': 1, 'returncode': 0, 'status': 'completed', 'argv': argv})
    with pytest.raises(ContractError, match='inputs or tool'):
        launcher.run(bundle, spec, scratch, {'frame.gtv1': frame, 'axis.ms': frame}, 'iterator', 'decode', 1, 513, 4096)
    _, result = launcher.run(bundle, spec, scratch, {'frame.gtv1': frame}, 'iterator', 'decode', 1, 513, 8192)
    argv = result['argv']
    assert '--unshare-net' in argv and '--fsize=8192:8192' in argv
    assert argv[-4:] == ['decode', 'iterator', '/inputs/frame.gtv1', '/out']
    assert [argv[i+2] for i, a in enumerate(argv) if a == '--ro-bind' and argv[i+2].startswith('/inputs/')] == ['/inputs/frame.gtv1']
    assert result['input_mounts'] == {'frame.gtv1': {'bytes': (8 << 20) + 1, 'sha256': digest(frame)}}


def test_shared_time_byte_bills_and_snapshot_tail():
    case = {'columns': 3, 'rows': 513, 'units': 6, 'artifact_bytes': 250, 'snapshot_bytes': 150}
    final = clock._bill(case, 'encode')
    snap = clock._bill(case, 'snapshot_decode')
    assert final['logical_unique_tv_bytes'] == 513 * 4 * 8
    assert final['native_per_column_tv_bytes'] == 513 * 3 * 16
    assert snap['logical_unique_tv_bytes'] == 256 * 4 * 8
    assert snap['complete_gtv1_bytes'] == snap['native_xorchunk_bytes'] + snap['gtv1_envelope_bytes'] == 150


def test_trial_reopens_original_and_recovers_independently(tmp_path, monkeypatch):
    """Orchestration fixture only, not evidence of real child timing or compression."""
    run = tmp_path
    axis, values = struct.pack('<2q', 0, 1000), struct.pack('<2Q', 0, 1 << 63)
    recovery = PAIR.pack(0, 0) + PAIR.pack(1000, 1 << 63)
    native = b'\x00\x02\x01'
    archive = HEADER.pack(MAGIC, 1, 2) + LENGTH.pack(len(native)) + native
    case = {'case_id': 'case', 'route': 'tv-batch', 'columns': 1, 'rows': 2, 'units': 1,
            'artifact_bytes': len(archive), 'source_original': {'path': 'source.csv'}, 'input_identity': {'stage': 'fixed'},
            'block_facts_sha256': 'fixture'}
    entry = {'file': case['source_original']}
    path = run / 'cases' / 'case'
    fixed, setup_source = path / 'fixed', run / 'setup-source'
    fixed.mkdir(parents=True)
    setup_source.mkdir()
    (setup_source / 'axis.ms').write_bytes(axis)
    (setup_source / 'column-0000.bin').write_bytes(values)
    (fixed / 'frame.gtv1').write_bytes(archive)
    setup = {'canonical_files': {p.name: clock._facts(clock._ref(setup_source, p)) for p in setup_source.iterdir()},
             'fixed': clock._archive_refs(run, case, fixed)}
    stage_calls = []

    def stage(root, received, dest):
        assert root == run and received == entry and dest != setup_source
        stage_calls.append(dest)
        dest.mkdir()
        (dest / 'axis.ms').write_bytes(axis)
        (dest / 'column-0000.bin').write_bytes(values)
        return dest / 'axis.ms', [dest / 'column-0000.bin'], case['input_identity']

    def isolated(run, plan, case, source, anchors, scratch, direction):
        out = scratch / 'out'
        out.mkdir(parents=True)
        if direction == 'encode':
            assert source == stage_calls[-1]
            (out / 'frame.gtv1').write_bytes(archive)
            mounts = setup['canonical_files']
        else:
            assert source == setup_source and anchors == fixed
            (out / 'column-0000.tv').write_bytes(recovery)
            mounts = {'frame.gtv1': clock._facts(setup['fixed']['frame.gtv1'])}
        raw = {'cols': 1, 'rows': 2, 'units': [[0, 0, 2, len(native), 1]]}
        return out, raw, {'direction': direction, 'process': {'input_mounts': mounts}, 'durable_output_wall_ns': 1}

    monkeypatch.setattr(clock, 'stage', stage)
    monkeypatch.setattr(clock, '_invoke', isolated)
    for repeat in range(2):
        row, products = clock._trial(run, run, {}, case, entry, setup_source, fixed, setup, repeat)
        assert row['source_original'] == entry['file'] and len(products) == 2
        assert row['ingress']['wall_ns'] > 0
        enc, dec = row['operations']
        assert enc['verified_durable_wall_ns'] >= row['ingress']['wall_ns'] + enc['durable_output_wall_ns']
        assert dec['verified_durable_wall_ns'] > dec['durable_output_wall_ns']
    assert len(stage_calls) == 2 and stage_calls[0] != stage_calls[1] and not any(p.exists() for p in stage_calls)
