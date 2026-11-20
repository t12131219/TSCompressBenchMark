"""Bind a real-corpus window to the existing paired PBEPLA native executor.

Callers must first rederive the enclosing corpus definition. This single-window
reader is for probes; a full submission should reuse a bounded file session.
"""
import struct
from hashlib import sha256

from ..assets import content_id, require
from ..corpus_ingress import read_batches
from .pbepla_execution import CAP, PROGRESSIVE, REPLAY, _slot
from .pbepla_progressive import WORD_MAGIC, schema_bytes


def _extent(contract, column, window):
    geometry = next((x for x in contract['column_overrides'] if x['value_column_index'] == column),
                    contract['default_column'])
    for span in geometry['accepted_spans']:
        if window >= span['windows']:
            window -= span['windows']
            continue
        extra = span['first_windows_with_one_extra_row']
        start = span['rows'][0] + window * span['base_rows'] + min(window, extra)
        end = start + span['base_rows'] + int(window < extra)
        require(span['rows'][0] <= start < end <= span['rows'][1], 'invalid PBEPLA window extent')
        return start, end
    require(False, 'missing PBEPLA planned window ordinal')


def bind_native_pair(root, entry, progressive, replay, *, column: int, window: int):
    require(type(column) is int and 0 <= column < entry['value_count'] and type(window) is int and window >= 0,
            'invalid PBEPLA value column or window ordinal')
    for route, decision in ((PROGRESSIVE, progressive), (REPLAY, replay)):
        require((decision['dataset_id'], decision['canonical_object_id'], decision['route'], decision['state']) ==
                (entry['id'], entry['canonical']['object_id'], route, 'input_domain_matches'),
                'PBEPLA input identity or domain does not match the decision')
    contract = progressive['input']['pbepla_contract']
    other = replay['input']['pbepla_contract']
    require(contract == {**other, 'replay': None} and other['replay']['native_same_window_as_batch'],
            'PBEPLA paired input geometry differs')
    start, end = _extent(contract, column, window)
    layout = contract['layout']
    count = end - start
    require(0 <= start < end <= entry['rows'] and layout['min_rows'] <= count <= layout['max_rows'] and
            layout['max_prefix_frame_bytes'] == CAP, 'PBEPLA probe extent or retention differs')
    raw = bytearray()
    stride = 8 * entry['value_count']
    for batch in read_batches(root, entry):
        for row in range(max(start, batch.start), min(end, batch.start + batch.rows)):
            p = (row - batch.start) * stride + 8 * column
            raw.extend(batch.values[p:p+8])
    sentinel = struct.pack('<d', -9999)
    require(len(raw) == 8 * count and (entry['parser']['missing'] != 'retain_source_minus_9999' or
            all(raw[i:i+8] != sentinel for i in range(0, len(raw), 8))), 'PBEPLA source projection includes missing values')
    source = {'dataset': entry['id'], 'dataset_object_id': entry['canonical']['object_id'],
              'canonical_value_column': column, 'column_name': entry['columns'][column+1],
              'absolute_row_range': [start, end], 'window_ordinal': window,
              'decision_ids': [progressive['decision_id'], replay['decision_id']]}
    name = 'corpus-' + content_id(source)[:24]
    eps = layout['requested_eps']
    spec = {'name': name, 'source': source, 'count': count, 'input_sha256': sha256(raw).hexdigest(),
            'schema_sha256': sha256(schema_bytes(name)).hexdigest(), 'requested_eps': eps, 'geometry': None,
            'expected_flags': 1, 'expected_delay': layout['max_delay'], 'replay': True,
            'frame_paths': [f'pbepla-{name}-L{i}.bmk' for i in range(1, len(eps)+1)],
            'word_path': f'pbepla-{name}.f64le', 'word_bytes': len(WORD_MAGIC) + len(raw)*(1+len(eps))}
    spec['input_id'] = content_id(spec)
    # Candidate adapter uses the already validated non-retry path. Any other
    # observed behavior is retained as a nonpass, never reclassified as verified.
    replay_policy = {'scope': 'logical_callback_and_stdio_not_physical_io', 'empty_passes': 1,
                     'nonempty_passes_without_retry': 3, 'max_numerical_retries': 0,
                     'expect_batch_payload_identity': True}
    slots = (_slot(PROGRESSIVE, 'prefixes', spec),
             _slot(REPLAY, 'prefixes', spec, replay_policy=replay_policy))
    return slots, bytes(raw)
