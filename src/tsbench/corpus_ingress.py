"""Bounded, source-order decoding for declared full-file real-corpus inputs.

The older, selected-window corpus and the typed development loaders keep their
identities. This protocol binds an entire delimited source to separate dense
little-endian T and V streams, without writing canonical copies to disk.
"""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import csv
import math
from os import fstat
from pathlib import Path
import re
import struct

from .assets import ContractError, content_id, digest, load_json, local_file, require, verify_asset
from .contracts import load_contract

MANIFEST = 'datasets/manifests/first-batch-full-v1.json'
CONTRACT = 'full-corpus'
FIRST_BATCH_SCOPE = 'first_batch_unique_originals_v1'
ORIGINAL_INVENTORY = 'datasets/manifests/unique-intake-candidates.json'
CANONICAL = 'bmk.dense-axis-and-values-row-major/1'
MAX_LINE_BYTES = 128 * 1024
BATCH_ROWS = 128
PARTITIONS = ('train', 'development', 'test')
_EPOCH = datetime(1970, 1, 1)
_STAMP = {
    'civil_iso_seconds': re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}'),
    'civil_slash_minutes': re.compile(r'([0-9]{4})/([0-9]{1,2})/([0-9]{1,2}) ([0-9]{1,2}):([0-9]{2})'),
    'integer_label': re.compile(r'-?(?:0|[1-9][0-9]{0,18})'),
}
_NUMBER = {sep: re.compile(rf'[+-]?(?:[0-9]{{1,100}}(?:{re.escape(sep)}[0-9]{{0,100}})?|'
                           rf'{re.escape(sep)}[0-9]{{1,100}})(?:[eE][+-]?[0-9]{{1,4}})?')
           for sep in ('.', ',')}


@dataclass(frozen=True, slots=True)
class CorpusBatch:
    start: int
    rows: int
    axis: bytes
    values: bytes


def axis_contract(kind: str) -> dict:
    if kind == 'integer_label':
        return {'dtype': '<i8', 'unit': 'source_tick', 'interpretation': 'source_integer_label',
                'epoch': None, 'timezone': None}
    return {'dtype': '<i8', 'unit': 'second', 'interpretation': 'source_civil_label_coordinate_not_utc',
            'epoch': '1970-01-01 00:00:00', 'timezone': None}


def _timestamp(token: str, kind: str) -> int:
    match = _STAMP[kind].fullmatch(token)
    require(match is not None, 'timestamp differs from declared syntax')
    if kind == 'integer_label':
        value = int(token)
        require(-2**63 <= value < 2**63, 'integer timestamp outside i64')
        return value
    try:
        date = (datetime.fromisoformat(token) if kind == 'civil_iso_seconds'
                else datetime(*map(int, match.groups())))
    except ValueError as exc:
        raise ContractError('invalid civil timestamp') from exc
    offset = date - _EPOCH
    return offset.days * 86400 + offset.seconds


def _lines(stream, found):
    index = 0
    while raw := stream.readline(MAX_LINE_BYTES + 1):
        index += 1
        require(len(raw) <= MAX_LINE_BYTES, f'oversized physical line {index}')
        found.update(raw)
        body = raw[:-2] if raw.endswith(b'\r\n') else raw.removesuffix(b'\n')
        require(body and b'\r' not in body and b'\0' not in body, f'blank or invalid physical line {index}')
        yield body.decode('utf-8', 'strict')


def split_line(line, separator):
    # Quoted fields are allowed but multi-line CSV fields are not in this contract.
    return next(csv.reader((line,), delimiter=separator, strict=True))


def read_batches(root: Path, entry: dict):
    """Yield bounded batches; exhaustion is required to certify raw SHA and extent.

    Callers must stage work until the final check (or first verify the manifest
    asset) and must not publish success for a partially consumed generator.
    """
    ref, spec = entry['file'], entry['parser']
    path = local_file(root, ref['path'])
    raw_digest = sha256()
    axes, values = bytearray(), bytearray()
    row_count = start = 0
    header = entry['columns']
    dot = spec['decimal']
    pattern = _NUMBER[dot]
    zero = re.compile(r'[+-]?(?:0+[.,]?0*|[.,]0+)(?:[eE][+-]?[0-9]+)?')
    pack_values = struct.Struct('<' + 'd' * (len(header) - 1)).pack
    line_no = 1
    try:
        with path.open('rb') as stream:
            require(fstat(stream.fileno()).st_size == ref['bytes'], 'source size differs from declaration')
            lines = _lines(stream, raw_digest)
            line = next(lines, None)
            require(line is not None and split_line(line, spec['separator']) == header,
                    'source header differs from ordered column binding')
            for line_no, line in enumerate(lines, 2):
                row = split_line(line, spec['separator'])
                require(len(row) == len(header), 'row width differs from source header')
                require(row_count < entry['rows'], 'more rows than declared')
                axes.extend(struct.pack('<q', _timestamp(row[0], spec['timestamp'])))
                numbers = []
                for token in row[1:]:
                    if pattern.fullmatch(token) is None:
                        raise ContractError('missing, nonfinite or malformed f64 field')
                    value = float(token if dot == '.' else token.replace(',', '.'))
                    if not math.isfinite(value) or (value == 0.0 and zero.fullmatch(token) is None):
                        raise ContractError('f64 overflow or nonzero underflow')
                    numbers.append(value)
                values.extend(pack_values(*numbers))
                row_count += 1
                if row_count - start == BATCH_ROWS:
                    yield CorpusBatch(start, row_count - start, bytes(axes), bytes(values))
                    start = row_count
                    axes.clear()
                    values.clear()
            require(row_count == entry['rows'], 'source row count differs from declaration')
            require(raw_digest.hexdigest() == ref['sha256'], 'source SHA-256 differs from declaration')
            if row_count != start:
                yield CorpusBatch(start, row_count - start, bytes(axes), bytes(values))
    except (csv.Error, UnicodeError, ContractError) as exc:
        raise ContractError(f"{ref['path']}:{line_no}: {exc}") from exc


def _canonical_id(entry, count, axis_sha256, values_sha256):
    return content_id({'schema': CANONICAL, 'axis': axis_contract(entry['parser']['timestamp']),
                       'time_column': entry['columns'][0], 'value_columns': entry['columns'][1:],
                       'missing_policy': entry['parser']['missing'], 'values_dtype': '<f8',
                       'rows': count, 'axis_sha256': axis_sha256, 'values_sha256': values_sha256})


def _identity(entry, count, ha, hv):
    a, v = ha.hexdigest(), hv.hexdigest()
    return {'axis_sha256': a, 'values_sha256': v, 'object_id': _canonical_id(entry, count, a, v)}


def fingerprint(root: Path, entry: dict, *, sentinel_spans: dict | None = None) -> dict:
    """One-pass canonical identities for the full object and ordered disjoint splits."""
    bounds = [p['end'] for p in entry['partitions']]
    parts = [(sha256(), sha256()) for _ in bounds]
    ha, hv = sha256(), sha256()
    width = 8 * (len(entry['columns']) - 1)
    previous = first = minimum = maximum = None
    same = decreases = sentinels = 0
    sentinel = struct.pack('<d', -9999) if entry['parser']['missing'] == 'retain_source_minus_9999' else None
    for batch in read_batches(root, entry):
        ha.update(batch.axis)
        hv.update(batch.values)
        for (tick,) in struct.iter_unpack('<q', batch.axis):
            if previous is None:
                minimum = maximum = first = tick
            else:
                minimum, maximum = min(minimum, tick), max(maximum, tick)
                same += tick == previous
                decreases += tick < previous
            previous = tick
        if sentinel is not None:
            count = entry['value_count']
            for i in range(0, len(batch.values), 8):
                if batch.values[i:i+8] != sentinel:
                    continue
                sentinels += 1
                if sentinel_spans is not None:
                    require(sentinels <= entry['retained_sentinel_values'], 'more sentinels than locked')
                    row, col = divmod(i // 8, count)
                    row += batch.start
                    spans = sentinel_spans.setdefault(col, [])
                    if spans and spans[-1][1] == row:
                        spans[-1][1] = row + 1
                    else:
                        spans.append([row, row + 1])
        for p, (a, v) in zip(entry['partitions'], parts, strict=True):
            lo = max(p['start'], batch.start) - batch.start
            hi = min(p['end'], batch.start + batch.rows) - batch.start
            if lo < hi:
                a.update(batch.axis[lo*8:hi*8])
                v.update(batch.values[lo*width:hi*width])
    return {'canonical': _identity(entry, entry['rows'], ha, hv),
            'axis_observations': {'first': first, 'last': previous, 'min': minimum, 'max': maximum,
                                  'adjacent_equal': same, 'decreases': decreases},
            'retained_sentinel_values': sentinels,
            'partitions': [{**p, 'canonical': _identity(entry, p['end'] - p['start'], a, v)}
                           for p, (a, v) in zip(entry['partitions'], parts, strict=True)]}


def _check_first_batch_closure(root: Path, entries: list[dict]) -> None:
    inventory = load_json(local_file(root, ORIGINAL_INVENTORY))
    require(inventory.get('schema') == 'bmk.dataset-intake-inventory/1', 'invalid historical intake inventory')
    originals = []
    for row in inventory['files']:
        path = row['origin_relative_path']
        require(path.startswith('datasets/'), 'invalid historical intake path')
        originals.append((f"datasets/raw/unique/{path.removeprefix('datasets/')}",
                          row['source_bytes'], row['source_sha256']))
    actual = [(e['file']['path'], e['file']['bytes'], e['file']['sha256']) for e in entries]
    require(len(originals) == len(actual) == 23 and len(set(originals)) == 23 and
            sum(size for _, size, _ in originals) == 976500895 and sorted(actual) == sorted(originals),
            'first-batch full corpus must bind the exact 23 original file identities')


def load_full_manifest(root: Path, manifest: str = MANIFEST, *, parse: bool = False,
                       sentinel_index: dict | None = None) -> dict:
    contract = load_contract(root, CONTRACT)
    document = load_json(local_file(root, manifest))
    contract.validate(document, manifest)
    if manifest == MANIFEST or document['scope'] == FIRST_BATCH_SCOPE:
        require(document['scope'] == FIRST_BATCH_SCOPE, 'incorrect first-batch corpus scope')
        _check_first_batch_closure(root, document['datasets'])
    require(sentinel_index is None or (parse and not sentinel_index),
            'sentinel positions require a full canonical audit and an empty index')
    audited_spans = {}
    seen = {key: set() for key in ('id', 'path')}
    for entry in document['datasets']:
        ref, cols, partitions = entry['file'], entry['columns'], entry['partitions']
        for key, value in (('id', entry['id']), ('path', ref['path'])):
            require(value not in seen[key], f'duplicate corpus {key}: {value}')
            seen[key].add(value)
        require(len(cols) == len(set(cols)) and all(cols[1:]), 'empty or duplicate value columns')
        require(entry['axis'] == axis_contract(entry['parser']['timestamp']), 'inconsistent corpus axis metadata')
        require(entry['value_count'] == len(cols) - 1, 'inconsistent corpus value shape')
        observed = entry['axis_observations']
        require(observed['min'] <= min(observed['first'], observed['last']) and
                max(observed['first'], observed['last']) <= observed['max'] and
                observed['adjacent_equal'] + observed['decreases'] < entry['rows'], 'invalid corpus axis observations')
        sentinels = entry['retained_sentinel_values']
        require(sentinels <= entry['rows'] * entry['value_count'] and
                (not sentinels or entry['parser']['missing'] == 'retain_source_minus_9999'), 'invalid missing sentinel count')
        require([p['name'] for p in partitions] == list(PARTITIONS), 'incorrect corpus partition order')
        start = 0
        for p in partitions:
            require(p['start'] == start and start < p['end'] <= entry['rows'], 'noncontiguous/empty corpus partition')
            start = p['end']
        require(start == entry['rows'], 'corpus partitions do not cover the full file')
        for owner, rows in [(entry, entry['rows']), *((p, p['end'] - p['start']) for p in partitions)]:
            identity = owner['canonical']
            require(identity['object_id'] == _canonical_id(entry, rows, identity['axis_sha256'], identity['values_sha256']),
                    'invalid canonical object identity')
        if parse:
            spans = {} if sentinel_index is not None and sentinels else None
            found = fingerprint(root, entry, sentinel_spans=spans)
            require(all(entry[key] == value for key, value in found.items()),
                    f"canonical assets differ from frozen declarations: {entry['id']}")
            if spans:
                audited_spans[entry['id']] = spans
        else:
            path = verify_asset(root, ref)
            require(path.stat().st_size == ref['bytes'], f"source size differs: {entry['id']}")
    if sentinel_index is not None:
        sentinel_index.update(audited_spans)
    return document


def check_full_corpus(root: Path, manifest: str = MANIFEST, *, parse: bool = False) -> dict:
    document = load_full_manifest(root, manifest, parse=parse)
    entries = document['datasets']
    return {'schema': 'bmk.full-corpus-check/1', 'manifest': manifest, 'manifest_id': content_id(document),
            'loader_sha256': digest(Path(__file__)),
            'manifest_schema_id': load_contract(root, CONTRACT).document_id,
            'datasets': len(entries), 'source_clusters': len({r['source_cluster'] for r in entries}),
            'raw_bytes': sum(r['file']['bytes'] for r in entries), 'rows': sum(r['rows'] for r in entries),
            'value_elements': sum(r['rows'] * r['value_count'] for r in entries),
            'partitions': sum(len(r['partitions']) for r in entries), 'raw_hashes_verified': True,
            'logical_axis_bytes': 8 * sum(r['rows'] for r in entries),
            'logical_value_bytes': 8 * sum(r['rows'] * r['value_count'] for r in entries),
            'canonical_audit_performed': parse, 'execution_performed': False, 'stage_accepted': False}
