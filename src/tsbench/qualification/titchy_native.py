"""Validate complete Titchy native-slot evidence from retained bytes and frozen oracles."""
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..planner.titchy_native import retained_paths, sha, words
from .probe_build import verify_probe_build_lock
from .titchy_wire import TSC1, TSTR, TSTR_RECORD, decode_tchy, decode_tstr, native_bound

HEADER = struct.Struct('<8sIQIQ')


def _exact(got, want, message):
    require(canonical_bytes(got) == canonical_bytes(want), message)


def _read(out, name, cap):
    file = local_file(out, name)
    require(file.stat().st_size <= cap, f'Titchy artifact exceeds frozen bound: {name}')
    return file.read_bytes()


def _batch(bundle, out, report):
    specs, policy = bundle['batch'], bundle['batch_policy']
    rows = report.get('batch')
    require(isinstance(rows, list) and len(rows) == len(specs), 'Titchy batch evidence closure differs')
    _exact(report.get('batch_input_statuses'), bundle['status_policy']['batch_input'], 'Titchy input rejection statuses differ')
    backing = None
    for spec, row in zip(specs, rows, strict=True):
        name, width, count = (spec[k] for k in ('case', 'bits_per_sample', 'count'))
        expected_bound = native_bound(count, width, policy['chunk'], policy['split'])
        schema = canonical_bytes({'dtype': f'u{width}', 'column': 'v'})
        dtype = {8: 2, 16: 4, 32: 6, 64: 8}[width]
        wire = _read(out, spec['artifact'], HEADER.size+len(schema)+expected_bound)
        require(len(wire) >= HEADER.size+len(schema), 'Titchy ABI envelope truncated')
        body = wire[HEADER.size+len(schema):]
        require(wire[:HEADER.size+len(schema)] == HEADER.pack(b'BMKTCH\1\0',dtype,count,len(schema),len(body))+schema,
                'Titchy ABI envelope does not match input shape')
        plain, splits = decode_tchy(body, width, count, policy)
        require(sha(plain) == spec['input_sha256'], f'Titchy batch wire does not restore frozen input: {name}')
        want = {**spec, 'detached_restored_sha256': sha(plain), 'descriptor': {'dtype': dtype, 'count': count},
                'native_bound': expected_bound, 'native_bytes': len(body), 'native_sha256': sha(body),
                'schema_bytes': len(schema), 'artifact_bytes': len(wire), 'artifact_sha256': sha(wire), 'bit_exact': True,
                'negative_artifacts': len(bundle['status_policy']['batch_frames']),
                'negative_statuses': bundle['status_policy']['batch_frames']}
        _exact(row, want, f'Titchy batch result or restored descriptor differs: {name}')
        if name == 'traffic-split-and-tail':
            backing = (body, plain, splits)
    require(backing is not None, 'Titchy original access fixture missing')
    return backing


def _stream(bundle, out, observed):
    spec, policy = bundle['stream'], bundle['batch_policy']
    archive = _read(out, spec['archive'], spec['max_artifact_bytes'])
    config = _read(out, spec['config'], TSC1.size)
    expected = stream_evidence(archive, config, spec, policy, bundle['status_policy']['stream'])
    _exact(observed, expected, 'Titchy stream emission, byte counts, reset or limits differ')


def stream_evidence(archive, config, spec, policy, statuses):
    """Derive stream accounting and the expected transcript independently of the native driver."""
    raw, packets = decode_tstr(archive, config, spec, policy)
    require(sha(raw) == spec['input_sha256'], 'Titchy packet stream does not restore frozen input')
    chunk, split, n, target = policy['chunk'], policy['split'], spec['count'], spec['chunks_per_packet']
    payload_bytes = sum(p['bytes'] for p in packets)
    padded = ((n+chunk-1)//chunk)*chunk
    events, chunks = [], 0
    for packet in packets:
        chunks += packet['chunks']
        # A short packet at a split is emitted when the next full chunk is
        # pushed. The final partial chunk is emitted only during finish.
        samples = chunks*chunk if packet['chunks'] == target else (chunks+1)*chunk
        if samples <= n:
            require(packet['chunks'] == target or chunks % split == 0, 'Titchy pre-finish partial packet is not split-bound')
            events.append(samples)
    require(events and len(events) < len(packets), 'Titchy case does not exercise pre-finish and final drains')
    return {'first_packet_after_samples': events[0], 'emitted_after_push': events,
                      'packets_before_finish': len(events), 'packet_count': len(packets), 'max_ready_packets_observed': 1,
                      'finished_samples': n, 'max_active_bases': spec['max_active_bytes']//(chunk*8+4),
                      'dictionary_bases': sum(p['new_bases'] for p in packets), 'target_chunks': target,
                      'active_lru_logical_bytes': spec['max_active_bytes'], 'true_values': n, 'padded_values': padded,
                      'pad_zeros': padded-n, 'archive_framing_bytes': TSTR.size + TSTR_RECORD.size*len(packets),
                      'packet_payload_bytes': payload_bytes, 'config_bytes': len(config),
                      'all_required_artifact_bytes': len(config)+len(archive), 'archive_sha256': sha(archive),
                      'config_sha256': sha(config), 'detached_restored_sha256': sha(raw), 'detached_bit_exact': True,
                      'backpressure_and_output_capacity_retry': True, 'encoder_and_decoder_reset_checked': True,
                      'decoder_padding_budget_rejected': True, 'reset_archive_sha256': sha(archive),
                      'statuses': statuses}


def _access(bundle, out, observed, backing):
    frame, raw, splits = backing
    require(len(splits) == 2 and _read(out, bundle['backing_path'], len(frame)) == frame,
            'Titchy access backing differs from independently decoded batch frame')
    bad_index = bytearray(frame)
    bad_index[38] ^= 1
    off = splits[1]['offset']
    corrupt = frame[:off]+b'\xff'+frame[off+1:]
    _exact({key: observed.get(key) for key in ('statuses', 'index_mutation_sha256', 'pair_mutation_sha256',
           'valid_prefix_on_bad_later_split', 'empty_range_at_eof_accepted')},
           {'statuses': bundle['status_policy']['access'], 'index_mutation_sha256': sha(bad_index),
            'pair_mutation_sha256': sha(corrupt), 'valid_prefix_on_bad_later_split': words(raw[:8])[0],
            'empty_range_at_eof_accepted': True},
           'Titchy access negative status, mutation or unaffected prefix differs')


def verify_titchy_native(bundle, build, driver, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k: v for k, v in bundle.items() if k != 'bundle_id'}),
            'Titchy native bundle identity differs')
    require(sealed_paths is None or retained_paths(bundle) | {bundle['evidence_path']} <= sealed_paths,
            'Titchy native evidence is not sealed')
    doc = load_json(local_file(out, bundle['evidence_path']))
    require(isinstance(doc, dict) and doc.get('native_bundle_id') == bundle['bundle_id'] and
            doc.get('access_bundle_id') == bundle['access_bundle_id'] and doc.get('definitions') == driver and
            doc.get('schema') == 'bmk.m0-titchy-control/2' and doc.get('formal_qualification') is False and
            doc.get('formal_performance') is False, 'Titchy native evidence binding differs')
    verify_probe_build_lock(doc.get('build'), build, 'titchy-batch', dependency_count=1)
    backing = _batch(bundle, out, doc)
    _stream(bundle, out, doc.get('stream'))
    _access(bundle, out, doc.get('access'), backing)
