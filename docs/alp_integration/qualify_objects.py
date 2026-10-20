#!/usr/bin/env python3
"""Reproduce the ALP object/CLI qualification; never a performance run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from tsbench.data import TimeSeriesObject, array_order
from tsbench.schemes import ObjectScheme, decode_once

ROOT = Path(__file__).resolve().parents[2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_array(actual, original, order):
    assert actual.dtype == original.dtype and actual.shape == original.shape
    assert array_order(actual) == order
    assert actual.tobytes(order=order) == original.tobytes(order=order)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for key in ('alp', 'alp-rd'):
        for dtype in ('<f4', '<f8'):
            for order in ('C', 'F'):
                original = np.array(np.arange(771).reshape(257, 3) / 100,
                                    dtype=dtype, order=order)
                original[0, 0], original[1, 1] = -0.0, np.inf
                raw = original.tobytes(order=order)
                obj = TimeSeriesObject({'V': original},
                                       {'topology': 'SYNCHRONOUS_MTS', 'roles': {'V': 'V'}})
                for partition in ('whole', 'channel-chunks'):
                    name = f'{key}-{original.dtype.itemsize}-{order}-{partition}'
                    folder = output / name
                    folder.mkdir()
                    method = {'id': key, 'codec': key, 'params': {}}
                    if partition == 'channel-chunks':
                        method.update(channelwise=True, chunk_rows=127)
                    encoded = ObjectScheme(method, ROOT).encode_once(obj)
                    assert original.tobytes(order=order) == raw
                    check_array(decode_once(encoded, ROOT).components['V'], original, order)
                    wire = folder / 'object.tsb'
                    wire.write_bytes(encoded.wire)
                    command = [sys.executable, '-m', 'tsbench', 'decode', str(wire),
                               str(folder / 'decoded'), '--asset-root', str(ROOT),
                               '--build-root', str(ROOT / 'build/tsbench')]
                    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True,
                                            text=True, timeout=120)
                    metadata = json.loads((folder / 'decoded/object.json').read_text())
                    check_array(np.load(folder / 'decoded' / metadata['components']['V'],
                                        allow_pickle=False), original, order)
                    parts = len(encoded.descriptor['components'][0]['parts'])
                    assert parts == (9 if partition == 'channel-chunks' else 1)
                    cases.append({'case': name, 'status': 'PASS', 'dtype': dtype,
                                  'order': order, 'shape': list(original.shape),
                                  'partition': partition, 'parts': parts,
                                  'input_sha256': digest(raw),
                                  'wire_sha256': digest(encoded.wire),
                                  'wire_bytes': len(encoded.wire),
                                  'independent_cli_decode': True, 'command': command,
                                  'command_stdout': result.stdout})
                    print(name, 'PASS', flush=True)
    report = {'status': 'PASS', 'case_count': len(cases), 'cases': cases,
              'driver_sha256': digest(Path(__file__).read_bytes()),
              'scope': 'safe-v1 ObjectScheme and new-process CLI decoding; no performance claim'}
    (output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
