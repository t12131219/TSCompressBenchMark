"""Real-corpus FIRE query: compressed-only native reductions with a u16 bit oracle."""
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import time
from zlib import crc32

import numpy as np

from ..assets import ContractError, digest, local_file, require
from ..corpus_ingress import read_batches
from ..qualification.sprintz import check_sfb1

ROWS = 8192
LANES = 4
MESSAGE_BYTES = ROWS * LANES * 2
HEADER = struct.Struct('<4s4B6I')
BACKEND = 'repaired-reference-fix1'


class SprintzHardwarePending(ContractError):
    """The selected native implementation cannot run on the available CPU."""


def invoke(control, cwd, op, source, cols, rows, output):
    env = {k: v for k, v in os.environ.items() if k not in {'LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT'}}
    start = time.monotonic_ns()
    proc = subprocess.run([str(control), op, str(source), str(cols), str(rows), str(output)], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=240)
    elapsed = time.monotonic_ns() - start
    if proc.returncode == 77:
        raise SprintzHardwarePending(proc.stderr.strip())
    require(proc.returncode == 0, f'Sprintz {op} failed ({proc.returncode}): {proc.stderr.strip()}')
    record = json.loads(proc.stdout)
    require(record.get('backend') == BACKEND and type(record.get('workspace_bytes')) is int and
            record['workspace_bytes'] > 0 and isinstance(record.get('units'), list), 'Sprintz process observation differs')
    return record, elapsed


def _oracle(raw):
    lanes = np.frombuffer(raw, dtype='<u2').reshape(-1, LANES)
    return {'count': [len(lanes)] * LANES, 'sum': lanes.sum(axis=0, dtype=np.uint64).tolist(),
            'max': lanes.max(axis=0).tolist()}


def _observe(raw, wire, encoded, queried, decoded, column, start):
    size = len(wire)
    facts = {'column': column, 'row_start': start, 'raw_bytes': len(raw), 'frame_bytes': size}
    require(all(all(row.get(k) == v for k, v in facts.items()) for row in (encoded, queried, decoded)),
            'Sprintz framings or planned row span differ')
    require(HEADER.unpack_from(wire) == (b'SFB1', 1, 16, 0, 0, LANES, len(raw), size - HEADER.size,
                                         crc32(raw), crc32(wire[HEADER.size:]), 0), 'Sprintz SFB1 headers or CRCs differ')
    expected = _oracle(raw)
    for mode, backend in [('auto', 'upstream_simd'), ('scalar', 'scalar')]:
        actual = queried.get(mode)
        require(actual == {'backend': backend, **expected}, f'Sprintz {mode} unsigned count/sum/max differs')
    times = {label: obs.get(f'{label}_wall_ns') for label, obs in
             [('encode', encoded), ('auto', queried), ('scalar', queried), ('decode', decoded)]}
    require(all(type(ns) is int and ns > 0 for ns in times.values()), 'Sprintz native per-call latency missing')
    return {**facts, 'row_end': start + len(raw) // 8, 'frame_sha256': sha256(wire).hexdigest(),
            'restored_sha256': sha256(raw).hexdigest(), 'native_wall_ns': times,
            'payload_bytes': size - HEADER.size, 'auto': queried['auto'], 'scalar': queried['scalar']}


def _stage(root, entry, folder):
    """Transpose input as opaque 64-bit cells without evaluating f64 values."""
    cols = entry['value_count']
    folder.mkdir()
    paths = [folder / f'column-{i:04d}.bin' for i in range(cols)]
    actual = 0
    with ExitStack() as stack:
        handles = [stack.enter_context(path.open('wb')) for path in paths]
        for batch in read_batches(root, entry):
            block = np.frombuffer(batch.values, dtype='V8').reshape(batch.rows, cols)
            for i, out in enumerate(handles):
                out.write(block[:, i].tobytes())
            actual += batch.rows
    require(actual == entry['rows'], 'Sprintz ingested extent differs from planned extent')
    return paths


def _read_frame(archive):
    prefix = archive.read(HEADER.size)
    require(len(prefix) == HEADER.size, 'truncated Sprintz SFB1 header')
    n = HEADER.unpack(prefix)[7]
    require(8 <= n <= 4 * MESSAGE_BYTES, 'Sprintz SFB1 payload length outside bounds')
    payload = archive.read(n)
    require(len(payload) == n, 'truncated Sprintz SFB1 payload')
    return prefix + payload


def run_sprintz_query(root: Path, plan: dict, item: dict, entry: dict, work: Path, run: Path) -> dict:
    control = local_file(root, plan['build']['sprintz_query']['executable']['path'])
    extent = item['input']
    cols, rows = entry['value_count'], entry['rows']
    require(extent['value_column_range'] == [0, cols] and len(extent['row_ranges']) == 1 and
            extent['row_ranges'][0]['start'] == 0 and extent['row_ranges'][0]['end'] == rows and
            extent['slice_extent']['max_per_unit'] == ROWS and extent['full_extent_of_file_rows_and_value_columns'],
            'Sprintz query requires all planned rows and four contiguous u16 lanes per V column')
    paths = _stage(root, entry, work / 'values')
    detached = work / 'detached'
    detached.mkdir()
    archive_path = detached / 'dataset.sfb1'
    (detached / 'restored').mkdir()
    encoded, enc_ns = invoke(control, work, 'encode', 'values', cols, rows, archive_path)
    queried, qry_ns = invoke(control, detached, 'query', archive_path.name, cols, rows, '-')
    decoded, dec_ns = invoke(control, detached, 'decode', archive_path.name, cols, rows, 'restored')
    workspace = encoded['workspace_bytes']
    unit_count = cols * ((rows + ROWS - 1) // ROWS)
    require(workspace == queried['workspace_bytes'] == decoded['workspace_bytes'] and
            unit_count == len(encoded['units']) == len(queried['units']) == len(decoded['units']),
            'Sprintz process geometry or workspace differs')
    observations, sample = [], None
    with archive_path.open('rb') as archive:
        records = iter(zip(encoded['units'], queried['units'], decoded['units'], strict=True))
        for column, path in enumerate(paths):
            with path.open('rb') as orig, (detached / 'restored' / path.name).open('rb') as recovered:
                for start in range(0, rows, ROWS):
                    length = min(rows - start, ROWS) * 8
                    raw = orig.read(length)
                    require(len(raw) == length and recovered.read(length) == raw, 'Sprintz restored bits differ from the f64 source')
                    wire = _read_frame(archive)
                    observation = _observe(raw, wire, *next(records), column, start)
                    observations.append(observation)
                    if sample is None:
                        spec = {'width': 16, 'dims': LANES, 'count': length // 2, 'message_limit_bytes': MESSAGE_BYTES,
                                'algorithm': 1, 'path': 0}
                        check_sfb1(wire, spec, raw)
                        sample = (wire, observation)
                require(not orig.read(1) and not recovered.read(1), 'Sprintz source or restoration has trailing values')
        require(not archive.read(1), 'Sprintz dataset archive has trailing bytes')
    logical = sum(r['raw_bytes'] for r in observations)
    artifact = sum(r['frame_bytes'] for r in observations)
    require(sample is not None and artifact == archive_path.stat().st_size and
            (logical, len(observations)) == (extent['size_estimate']['native_input_bytes_one_pass'],
                                             extent['size_estimate']['input_units']), 'Sprintz output does not close the planned extent')
    wire, first = sample
    relative = Path('retained') / item['work_item_id'] / 'query-sample.sfb1'
    (run / relative).parent.mkdir(parents=True)
    (run / relative).write_bytes(wire)
    return {'driver': 'sprintz-corpus-query/1', 'columns': cols, 'rows': rows, 'units': observations,
            'input_bytes': logical, 'artifact_bytes': artifact, 'frame_header_bytes': unit_count * HEADER.size,
            'payload_bytes': artifact - unit_count * HEADER.size, 'codec_workspace_bytes': workspace,
            'clock_scope': 'diagnostic_native_calls_exclude_framing_io_and_oracle; separate_process_wall_includes_io',
            'process_wall_ns': {'encode': enc_ns, 'query_including_scalar_control': qry_ns, 'decode': dec_ns},
            'query_scope': 'unsigned_u16_limbs_not_original_f64', 'native_threads': 1,
            'verification': 'original_u16_lane_oracle_and_detached_process_bit_exact_restore_each_frame',
            'retained_sample': {'path': relative.as_posix(), 'bytes': len(wire), 'sha256': digest(run / relative),
                                'observation': first}, 'timing_admitted': False}
