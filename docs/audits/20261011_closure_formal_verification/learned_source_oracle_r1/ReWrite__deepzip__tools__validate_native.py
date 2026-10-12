"""Validate the standalone binary against frozen source evidence, not itself."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import struct
import numpy as np

PORT = Path(__file__).resolve().parents[1]
SOURCE = PORT.parent.parent / 'Source/deepzip'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command):
    started = time.perf_counter()
    p = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=600)
    if p.returncode:
        raise RuntimeError('command failed: {}\n{}'.format(command, p.stderr))
    return p.stdout, time.perf_counter() - started


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cli', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--kind', choices=['models', 'datasets', 'pipelines', 'traces'], required=True)
    p.add_argument('--backend', choices=['scalar', 'cuda'], default='scalar')
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    result = dict(schema_version=1, backend=a.backend, cli_sha256=sha(a.cli), cases=[])
    inventory = json.loads((SOURCE / 'golden/locked/model_inventory.json').read_text())
    if a.kind == 'models':
        records = [c for c in inventory['cases'] if c['status'] == 'PASS']
        for record in records:
            name = record['name']
            source = SOURCE / 'golden/locked' / name
            folder = a.work / name
            folder.mkdir(exist_ok=True)
            case = dict(name=name, source_model_sha256=sha(source / (name + '.hdf5')))
            try:
                portable = folder / 'imported.dzm'
                run([str(a.cli), 'import', str(source / (name + '.hdf5')), name, str(portable)])
                case['import_byte_identical'] = portable.read_bytes() == (source / (name + '.dzm')).read_bytes()
                output = folder / 'probabilities.f32'
                _, elapsed = run([str(a.cli), 'predict', str(portable), str(source / (name + '.contexts')),
                                  str(output), a.backend])
                actual = np.fromfile(str(output), dtype='<f4')
                reference = np.fromfile(str(source / (name + '.probabilities')), dtype='<f4')
                error = float(np.max(np.abs(actual.astype('float64') - reference.astype('float64'))))
                tolerance = 0.003 if '16bit' in name else 0.00003
                case.update(probability_max_absolute_error=error, tolerance=tolerance,
                            prediction_seconds=elapsed, probability_sha256=sha(output))
                case['status'] = 'PASS' if case['import_byte_identical'] and error <= tolerance else 'FAIL'
            except Exception as e:
                case.update(status='FAIL', error=str(e))
            result['cases'].append(case)
            a.output.write_text(json.dumps(result, indent=2) + '\n')
            print(name, case['status'], case.get('probability_max_absolute_error', case.get('error')), flush=True)
    else:
        cases = json.loads((SOURCE / ('golden/pipelines/source_cases.json' if a.kind == 'pipelines'
                                      else 'golden/datasets/source_cases.json')).read_text())
        for record in cases:
            name = record['case']
            folder = a.work / name
            folder.mkdir(exist_ok=True)
            source = Path(record['folder'])
            case = dict(name=name, input_sha256=record['canonical_sha256'], source_file_sha256=record.get('source_file_sha256'),
                        source_model_sha256=record['model_sha256'], source_roundtrip=record['source_result']['roundtrip'])
            try:
                params = json.loads((source / 'pipeline/encoded.params').read_text())
                alphabet = bytes(params['id2char_dict'][str(i)] for i in range(len(params['id2char_dict'])))
                alphabet_file = folder / 'alphabet.bin'
                alphabet_file.write_bytes(alphabet)
                portable = folder / 'imported.dzm'
                run([str(a.cli), 'import', record['model'], record['model_name'], str(portable)])
                if a.kind == 'traces':
                    raw = (source / 'pipeline/encode.trace').read_bytes()
                    assert raw[:8] == b'DZTRACE1'
                    offset = 8
                    errors = []
                    call = 0
                    while offset < len(raw):
                        batch, context, width = struct.unpack_from('<III', raw, offset)
                        offset += 12
                        inputs = raw[offset:offset + batch * context * 4]
                        offset += len(inputs)
                        reference = np.frombuffer(raw, dtype='<f4', count=batch * width, offset=offset).copy()
                        offset += batch * width * 4
                        offset += batch * (width + 1) * 8
                        contexts, predicted = folder / 'contexts.i32', folder / 'predicted.f32'
                        contexts.write_bytes(inputs)
                        run([str(a.cli), 'predict', str(portable), str(contexts), str(predicted), a.backend])
                        actual = np.fromfile(str(predicted), dtype='<f4')
                        errors.append(float(np.max(np.abs(actual.astype('float64') - reference.astype('float64')))))
                        call += 1
                    case.update(trace_calls=call, probability_max_absolute_error=max(errors),
                                tolerance=0.00003, source_trace_sha256=sha(source / 'pipeline/encode.trace'))
                    replay = a.cli.parent / 'deepzip_entropy_replay'
                    input_bytes = Path(record['input']).read_bytes()
                    dictionary = {value: i for i, value in enumerate(alphabet)}
                    ids = bytes(dictionary[value] for value in input_bytes)
                    symbols, combined, decoded = folder / 'symbols.bin', folder / 'combined', folder / 'decoded.symbols'
                    symbols.write_bytes(ids)
                    run([str(replay), str(symbols), str(source / 'pipeline/encode.trace'),
                         str(record['batch']), str(len(alphabet)), str(combined), str(decoded)])
                    case['source_table_replay_byte_identical'] = combined.read_bytes() == (source / 'pipeline/encoded.combined').read_bytes()
                    case['replay_decoded_identical'] = decoded.read_bytes() == ids
                    case['status'] = 'PASS' if max(errors) <= case['tolerance'] and case['source_table_replay_byte_identical'] and case['replay_decoded_identical'] else 'FAIL'
                    result['cases'].append(case)
                    a.output.write_text(json.dumps(result, indent=2) + '\n')
                    print(name, case['status'], max(errors), flush=True)
                    continue
                stream, decoded = folder / 'stream.dzc', folder / 'decoded.bin'
                stdout, encoding = run([str(a.cli), 'encode', str(portable), record['input'], str(stream),
                                        str(record['batch']), str(alphabet_file), a.backend])
                _, decoding = run([str(a.cli), 'decode', str(stream), str(decoded)])
                ledger = json.loads(stdout)
                case.update(ledger=ledger, encode_seconds=encoding, decode_seconds=decoding,
                            native_roundtrip=decoded.read_bytes() == Path(record['input']).read_bytes(),
                            decoded_sha256=sha(decoded), stream_sha256=sha(stream),
                            model_bytes=portable.stat().st_size, container_bytes=stream.stat().st_size)
                case['status'] = 'PASS' if case['native_roundtrip'] and ledger['final_bits'] == stream.stat().st_size * 8 else 'FAIL'
            except Exception as e:
                case.update(status='FAIL', error=str(e))
            result['cases'].append(case)
            a.output.write_text(json.dumps(result, indent=2) + '\n')
            print(name, case['status'], case.get('encode_seconds', case.get('error')), flush=True)
    result['status'] = 'PASS' if result['cases'] and all(c['status'] == 'PASS' for c in result['cases']) else 'FAIL'
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
