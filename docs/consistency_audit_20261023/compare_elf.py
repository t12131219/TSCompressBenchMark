"""Compare registered Bench ELF core frames with current standalone APIs.

Run with PYTHONPATH=benchmark/src:benchmark/tests and the Bench Python environment.
"""
from pathlib import Path
import json
import struct
import subprocess
import numpy as np
from test_core_floats import library, encode, decode

HERE = Path(__file__).resolve().parent
REWRITE = HERE.parents[1].parent / 'Compression_Rewrite/ReWrite'

def call(cli, mode, variant, array):
    data = struct.pack('<II', 1, len(array)) + array.tobytes()
    process = subprocess.run([str(cli), 'server'],
                             input=struct.pack('<IIII', mode, variant, array.itemsize * 8, len(data)) + data,
                             capture_output=True, timeout=10, check=True)
    status, count = struct.unpack_from('<II', process.stdout)
    payload = process.stdout[8:]
    assert count == len(payload)
    return status, payload

rows = []
for key, variant in [('elf', 1), ('elf-plus', 2), ('elf-star', 3), ('self-star', 5)]:
    cli = REWRITE / ('elf-original/build/elf_original_codec' if key == 'elf' else 'elf-family/build/elf_codec')
    for dtype in ['<f8', '<f4']:
        for values in [[.23], [1., 2., 3.], [0., .125, .25, 1., 1.]]:
            array = np.array(values, dtype=dtype)
            row = dict(key=key, dtype=dtype, values=values)
            stream = None
            try:
                lib = library(key)
                stream = encode(lib, key, array)
                row.update(bench_frame_magic=stream[:4].decode(), bench_frame_hex=stream.hex(),
                           bench_roundtrip=decode(lib, array, stream) == array.tobytes())
            except Exception as error:
                row['bench_error'] = str(error)
            status, frame = call(cli, 3, variant, array)
            row.update(current_status=status,
                       current_frame_hex=frame.hex() if not status else None,
                       current_frame_magic=frame[:8].decode(errors='replace') if not status else None,
                       current_error=frame.decode(errors='replace') if status else None)
            if stream is not None and not status:
                row['same_complete_frame'] = stream == frame
            status, raw = call(cli, 1, variant, array)
            if stream is not None and not status:
                # Current raw reply: u32 block count, u64 valid bits, u32 bytes, payload.
                count, bits, size = struct.unpack_from('<IQI', raw)
                assert count == 1 and len(raw) == 16 + size
                # Legacy self-star session has count/length before its block bytes.
                old = stream[40:] if key == 'self-star' else stream[32:]
                row.update(bench_raw_hex=old.hex(), current_raw_hex=raw[16:].hex(),
                           current_valid_bits=bits, same_raw_payload=old == raw[16:])
            rows.append(row)
(HERE / 'elf_bench_vs_current.json').write_text(json.dumps(rows, indent=2) + '\n')
print(json.dumps({key: dict(cases=sum(r['key'] == key for r in rows),
                            same_frames=sum(r['key'] == key and r.get('same_complete_frame', False) for r in rows),
                            same_raw=sum(r['key'] == key and r.get('same_raw_payload', False) for r in rows))
                  for key in ('elf', 'elf-plus', 'elf-star', 'self-star')}, indent=2))
