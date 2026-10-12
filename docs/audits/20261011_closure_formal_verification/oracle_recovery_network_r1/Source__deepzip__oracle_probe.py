"""Run unmodified DeepZip entrypoints with a bounded TF GPU session."""
from __future__ import print_function
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'upstream/src'))


def sha(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--length', type=int, default=70065)
    p.add_argument('--batch-size', type=int, default=1000)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model-name', default='biGRU')
    p.add_argument('--model', type=Path,
                   default=ROOT / 'upstream/data/trained_models/xor20/biGRU.hdf5')
    p.add_argument('--artifacts', type=Path)
    a = p.parse_args()
    a.work.mkdir(parents=True, exist_ok=True)
    result = dict(status='RUNNING', source_modified=False, batch_size=a.batch_size,
                  length=a.length, started_unix=time.time())
    try:
        import tensorflow as tf
        import keras
        import numpy as np
        from keras import backend as K
        config = tf.ConfigProto(intra_op_parallelism_threads=1,
                               inter_op_parallelism_threads=1)
        config.gpu_options.allow_growth = True
        sess = tf.Session(config=config)
        K.set_session(sess)
        result['tensorflow'] = tf.__version__
        result['keras'] = keras.__version__
        result['numpy'] = np.__version__
        result['devices'] = [d.name for d in sess.list_devices()]
        result['model_name'] = a.model_name
        result['model_sha256'] = sha(a.model)
        result['fp16_rnn_use_fp32_compute'] = os.environ.get('TF_FP16_RNN_USE_FP32_COMPUTE', 'default')
        # Observation only: forward all arguments and return the original result.
        phase = ['encode']
        counts = dict(encode=0, decode=0)
        streams = {}
        if a.artifacts:
            a.artifacts.mkdir(parents=True, exist_ok=True)
            for name in counts:
                streams[name] = (a.artifacts / (name + '.trace')).open('wb')
                streams[name].write(b'DZTRACE1')
            predict = keras.models.Model.predict
            def observed(model_self, inputs, *args, **kwargs):
                prob = predict(model_self, inputs, *args, **kwargs)
                x = np.asarray(inputs, dtype='<i4', order='C')
                c = np.zeros((len(prob), prob.shape[1] + 1), dtype='<u8')
                c[:, 1:] = np.cumsum(prob * 10000000 + 1, axis=1)
                f = streams[phase[0]]
                f.write(struct.pack('<III', x.shape[0], x.shape[1], prob.shape[1]))
                f.write(x.tobytes())
                f.write(prob.astype('<f4').tobytes())
                f.write(c.tobytes())
                counts[phase[0]] += 1
                return prob
            keras.models.Model.predict = observed
        raw = a.input.read_bytes()[:a.length]
        if len(raw) != a.length:
            raise ValueError('source file is shorter than the requested case')
        raw_path = a.work / 'input.bin'
        raw_path.write_bytes(raw)
        npy = a.work / 'symbols.npy'
        params = a.work / 'symbols.params.json'
        # Use the frozen upstream parser, preserving its byte-to-ID mapping.
        sys.argv = ['parse_new.py', '-input', str(raw_path), '-output', str(npy),
                    '-param_file', str(params)]
        runpy.run_path(str(ROOT / 'upstream/data/parse_new.py'), run_name='__main__')
        model = a.model
        prefix = a.work / 'encoded'
        sys.argv = ['compressor.py', '-data', str(npy), '-data_params', str(params),
                    '-model', str(model), '-model_name', a.model_name,
                    '-output', str(prefix), '-batch_size', str(a.batch_size)]
        runpy.run_path(str(ROOT / 'upstream/src/compressor.py'), run_name='__main__')
        phase[0] = 'decode'
        decoded = a.work / 'decoded.bin'
        sys.argv = ['decompressor.py', '-model', str(model), '-model_name', a.model_name,
                    '-output', str(decoded), '-input_file_prefix', str(prefix),
                    '-batch_size', str(a.batch_size)]
        runpy.run_path(str(ROOT / 'upstream/src/decompressor.py'), run_name='__main__')
        result['input_sha256'] = sha(raw_path)
        result['decoded_sha256'] = sha(decoded)
        result['roundtrip'] = raw == decoded.read_bytes()
        result['combined_sha256'] = sha(Path(str(prefix) + '.combined'))
        result['combined_bytes'] = Path(str(prefix) + '.combined').stat().st_size
        result['params_sha256'] = sha(Path(str(prefix) + '.params'))
        result['status'] = 'PASS' if result['roundtrip'] else 'FAIL_ROUNDTRIP'
        if a.artifacts:
            keras.models.Model.predict = predict
            for stream in streams.values():
                stream.close()
            for name, path in [('input.bin', raw_path), ('symbols.npy', npy),
                               ('encoded.combined', Path(str(prefix) + '.combined')),
                               ('encoded.params', Path(str(prefix) + '.params')),
                               ('decoded.bin', decoded)]:
                shutil.copyfile(str(path), str(a.artifacts / name))
            result['trace_calls'] = counts
            result['artifacts'] = {p.name: dict(sha256=sha(p), size_bytes=p.stat().st_size)
                                   for p in sorted(a.artifacts.iterdir()) if p.is_file()}
    except Exception:
        result['status'] = 'FAIL'
        result['traceback'] = traceback.format_exc()
    result['elapsed_seconds'] = time.time() - result['started_unix']
    a.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
