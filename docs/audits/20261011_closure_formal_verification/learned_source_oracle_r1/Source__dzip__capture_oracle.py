"""Execute unmodified original model constructors and codec scripts.

Initialization fixtures are explicitly untrained source weights. They exercise
codec state and are not evidence of compression quality or bootstrap training.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'upstream/encode-decode'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_graph(model, path, tensor_values=None):
    import numpy as np
    kinds = {'InputLayer': 0, 'Embedding': 1, 'Bidirectional': 2, 'Lambda': 3,
             'Flatten': 4, 'Dense': 5, 'Add': 6, 'Concatenate': 7, 'Activation': 8}
    activations = {'linear': 0, 'relu': 1, 'softmax': 2}
    ids = {layer.name: i for i, layer in enumerate(model.layers)}
    details = []
    with path.open('wb') as output:
        output.write(b'DZIPNN01')
        output.write(struct.pack('<III', 64, int(model.output_shape[-1]), len(model.layers)))
        for index, layer in enumerate(model.layers):
            kind = kinds[layer.__class__.__name__]
            flags = activations.get(getattr(getattr(layer, 'activation', None), '__name__', None), 0)
            inputs = []
            if kind != 0:
                values = layer.input if isinstance(layer.input, list) else [layer.input]
                for tensor in values:
                    inputs.append(ids[tensor._keras_history[0].name])
                assert all(value < index for value in inputs)
            weights = layer.get_weights()
            if tensor_values is not None:
                weights = [tensor_values[id(weight)] for weight in layer.weights]
            if kind == 2 and layer.forward_layer.__class__.__name__ == 'CuDNNGRU':
                # Keras's own public-to-CPU conversion changes kernel layouts and
                # reshapes the two biases. Native training uses sigmoid gates.
                from keras.engine.saving import _convert_rnn_weights
                from keras.layers import GRU
                flags = 1
                units = layer.forward_layer.units
                target = GRU(units, reset_after=True, recurrent_activation='sigmoid')
                weights = (_convert_rnn_weights(target, weights[:3]) +
                           _convert_rnn_weights(target, weights[3:]))
            output.write(struct.pack('<III', kind, flags, len(inputs)))
            for value in inputs:
                output.write(struct.pack('<I', value))
            output.write(struct.pack('<I', len(weights)))
            for weight in weights:
                array = np.asarray(weight, dtype='<f4', order='C')
                output.write(struct.pack('<I', array.ndim))
                output.write(struct.pack('<' + 'I' * array.ndim, *array.shape))
                output.write(array.tobytes())
            details.append(dict(index=index, name=layer.name, kind=kind, flags=flags, inputs=inputs,
                                weights=[list(weight.shape) for weight in weights], trainable=layer.trainable))
    return details


def initialize(args):
    import numpy as np
    import tensorflow as tf
    import keras
    from keras import backend as K
    sys.path.insert(0, str(SOURCE))
    import models
    np.random.seed(0)
    random.seed(0)
    tf.set_random_seed(0)
    K.set_session(tf.Session(config=tf.ConfigProto(intra_op_parallelism_threads=1, inter_op_parallelism_threads=1)))
    combined, bootstrap = models.biGRU_big(128, 64, args.alphabet)
    bootstrap.save_weights(str(args.output / 'bootstrap.h5'))
    shared = len(set(id(weight) for weight in combined.trainable_weights) &
                 set(id(weight) for weight in bootstrap.trainable_weights))
    details = {}
    for name, model in [('combined', combined), ('bootstrap', bootstrap)]:
        details[name] = export_graph(model, args.output / (name + '.dzn'))
        contexts = np.array([[(i * 13 + row * 7) % args.alphabet for i in range(64)] for row in range(4)], dtype=np.int64)
        contexts.astype('<i4').tofile(str(args.output / 'contexts.i32'))
        model.predict(contexts, batch_size=1).astype('<f4').tofile(str(args.output / (name + '.probabilities.f32')))
    result = dict(status='PASS', source_modified=False, tensorflow=tf.__version__, keras=keras.__version__, numpy=np.__version__,
                  alphabet=args.alphabet, shared_trainable_tensor_count=shared,
                  fixture='untrained original constructor; not a bootstrap training or quality witness', graphs=details,
                  source_models_sha256=sha(SOURCE / 'models.py'), driver_sha256=sha(Path(__file__)))
    (args.output / 'initialization.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status='PASS', alphabet=args.alphabet, shared_trainable_tensor_count=shared)))


def suite(args):
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    def run(label, command, directory):
        command = list(map(str, command))
        process = subprocess.run(command, cwd=str(directory), env=dict(os.environ, PYTHONHASHSEED='0',
                                 PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='', TF_CPP_MIN_LOG_LEVEL='2'),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        log = directory / (label + '.log')
        log.write_bytes(process.stdout)
        record = dict(label=label, command=command, exit_code=process.returncode,
                      log=str(log.relative_to(args.output)), log_sha256=sha(log))
        records.append(record)
        print(label, process.returncode, flush=True)
        if process.returncode:
            raise RuntimeError(process.stdout.decode(errors='replace')[-2500:])
    try:
        for alphabet in args.alphabets:
            directory = args.output / ('alphabet-' + str(alphabet))
            directory.mkdir(exist_ok=True)
            run('initialize', [sys.executable, Path(__file__).resolve(), 'initialize', '--alphabet', alphabet, '--output', directory], directory)
            for length in [65, 191, 192, 193, 321]:
                case = directory / ('length-' + str(length))
                case.mkdir(exist_ok=True)
                symbols = ''.join(chr(65 + (i * 13 + i // 11) % alphabet) for i in range(length))
                (case / 'input.txt').write_text(symbols)
                run('preprocess', [sys.executable, SOURCE / 'run.py', '--file_name', case / 'input.txt'], case)
                for profile, suffix in [('bootstrap', '_bs'), ('combined', '')]:
                    output = case / profile
                    run('encode-' + profile, [sys.executable, SOURCE / ('compressor' + suffix + '.py'),
                        '-model', directory / 'bootstrap.h5', '-model_name', 'biGRU_big', '-batch_size', '128',
                        '-data', case / 'input', '-data_params', case / 'params_input', '-output', output], case)
                    run('decode-' + profile, [sys.executable, SOURCE / ('decompressor' + suffix + '.py'),
                        '-model', directory / 'bootstrap.h5', '-model_name', 'biGRU_big', '-batch_size', '128',
                        '-input', output, '-data_params', case / 'params_input', '-output', case / (profile + '.decoded')], case)
                    assert (case / (profile + '.decoded')).read_bytes() == (case / 'input.txt').read_bytes()
                    records[-1]['lossless_roundtrip'] = True
                    records[-1]['input_sha256'] = sha(case / 'input.txt')
                    records[-1]['raw_stream_sha256'] = sha(case / (profile + '.dzip'))
        result = dict(status='PASS', source_modified=False, commands=records)
    except Exception as error:
        result = dict(status='FAIL', error=str(error), source_modified=False, commands=records)
    result['driver_sha256'] = sha(Path(__file__))
    result['source_listing_sha256'] = sha(ROOT / 'SOURCE_FILES.sha256')
    (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    raise SystemExit(0 if result['status'] == 'PASS' else 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['initialize', 'suite'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--alphabet', type=int, default=2)
    parser.add_argument('--alphabets', type=int, nargs='+', default=[2, 4])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == 'initialize':
        initialize(args)
    else:
        suite(args)


if __name__ == '__main__':
    main()
