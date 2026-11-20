from hashlib import sha256

import pytest

from tsbench.application import m3_zstd_dictionary_grouped as g
from tsbench.assets import ContractError
from tsbench.corpus_ingress import CorpusBatch


def test_zdg_counts_the_outer_header_and_dictionary_once(tmp_path):
    # One standard Zstd frame: one-byte dictionary ID and content size, final raw block.
    wire = bytes.fromhex('28b52ffd210903190000') + b'abc'
    body = g.HEAD.pack(g.MAGIC, 1) + g.FRAME.pack(3, len(wire)) + wire
    e = {'holdout': {'bytes': 3}, 'dictionary': {'id': 9, 'bytes': 512},
         'frames': [{'index': 0, 'status': 'verified', 'holdout_byte_range': [0, 3], 'logical_bytes': 3,
                     'bytes': len(wire), 'sha256': sha256(wire).hexdigest(), 'dictionary_id': 9}],
         'verified_frame_bytes': len(wire), 'verified_frame_bytes_plus_shared_dictionary_once': len(wire) + 512}
    path = tmp_path / 'input.zdg'
    path.write_bytes(body)
    assert g.inspect_archive(path, e) == {'bytes': len(body), 'sha256': sha256(body).hexdigest(), 'native_frames': 1,
                                           'native_frame_bytes': len(wire), 'wrapper_bytes': 16, 'dictionary_bytes': 512,
                                           'recovery_bytes': len(body) + 512}
    for changed, reason in ((body + b'\x00', 'trailing'), (body[:-1], 'truncated'),
                            (body[:-1] + b'd', 'differs from r40')):
        path.write_bytes(changed)
        with pytest.raises(ContractError, match=reason):
            g.inspect_archive(path, e)
    path.write_bytes(body)
    with pytest.raises(ContractError, match='accounting'):
        g.inspect_archive(path, {**e, 'verified_frame_bytes_plus_shared_dictionary_once': len(wire)})


def test_stage_selected_views_and_remove_unverified_output(tmp_path, monkeypatch):
    train, dev, holdout = b'T'*8, b'D'*8, b'H'*8
    test_hash = sha256(holdout).hexdigest()
    entry = {'value_count': 1, 'partitions': [{}, {}, {'canonical': {'values_sha256': test_hash}}]}
    e = {'train_prefix_sha256': sha256(train).hexdigest(), 'holdout': {'bytes': 8, 'sha256': test_hash}}
    monkeypatch.setattr(g, 'extents', lambda item, entry: (((0, 8), (16, 24)), 1, 8))
    monkeypatch.setattr(g, 'read_batches', lambda root, entry: iter((CorpusBatch(0, 3, b'', train+dev+holdout),)))
    staged = g.stage_inputs(tmp_path, {}, entry, tmp_path, e, roles=('train',))
    assert set(staged) == {'train'} and staged['train'].read_bytes() == train
    assert not (tmp_path / 'holdout.bin').exists()

    def interrupted(root, entry):
        yield CorpusBatch(2, 1, b'', holdout)
        raise ContractError('source digest changed')

    monkeypatch.setattr(g, 'read_batches', interrupted)
    with pytest.raises(ContractError, match='source digest changed'):
        g.stage_inputs(tmp_path, {}, entry, tmp_path, e, roles=('holdout',))
    assert not (tmp_path / 'holdout.bin').exists() and staged['train'].read_bytes() == train


def test_launcher_allows_only_phase_appropriate_mounts(tmp_path):
    from tsbench.supervisor import zstd_dictionary_grouped as launch

    prefix, held, shared, archive = (tmp_path / n for n in ('prefix', 'held', 'dict', 'archive'))
    for path, n in ((prefix, 8*32), (held, 3), (shared, 256), (archive, 19)):
        path.write_bytes(bytes(n))
    train, args, cap = launch._contract('train', prefix, training=(256, 32, 8))
    assert list(train) == ['prefix'] and args == ['/inputs/prefix', '/out/object', '256', '32', '8'] and cap == 256
    for op, source, role in (('encode', held, 'holdout'), ('decode', archive, 'archive')):
        paths, args, cap = launch._contract(op, source, dictionary=shared, logical=3)
        assert set(paths) == {role, 'dictionary'} and args == [f'/inputs/{role}', '/out/object', '/inputs/dictionary', '3']
        assert cap == (3 if op == 'decode' else 16+g.MAX_WIRE)
        with pytest.raises(ContractError, match='not training samples'):
            launch._contract(op, source, dictionary=shared, logical=3, training=(256, 32, 8))
    with pytest.raises(ContractError, match='prefix and geometry only'):
        launch._contract('train', prefix, training=(256, 32, 8), dictionary=shared)
    with pytest.raises(ContractError, match='held-out encode extent'):
        launch._contract('encode', prefix, dictionary=shared, logical=3)


def test_full_extent_needs_the_train_prefix_as_well_as_all_holdout():
    from tsbench.application.m3_measurement_inventory import _exact_extent
    from tsbench.application.m3_zstd_dictionary_timing import OPERATIONS, _schedule

    item = {'input': {'training': {'sample_geometry': {'count': 8, 'bytes_each': 32},
                                  'dictionary_capacity_bytes': 256, 'consumed_byte_range': [0, 256]},
                      'size_estimate': {'input_units': 2, 'native_input_bytes_one_pass': 259}}}
    case = {'case_id': 'test', 'item': item, 'training': [256, 32, 8],
            'anchor': {'frames': [None], 'holdout': {'bytes': 3}}, 'order': [OPERATIONS]*4}
    assert _exact_extent('zstd-dictionary', case, item)
    assert not _exact_extent('zstd-dictionary', {**case, 'training': [256, 32, 7]}, item)
    assert not _exact_extent('zstd-dictionary', {**case, 'anchor': {**case['anchor'], 'frames': []}}, item)
    slots = list(_schedule(case))
    assert len(slots) == 12 and len({r['path'] for r in slots}) == 12
    assert [r['phase'] for r in slots] == ['warmup']*3 + ['measure']*9
