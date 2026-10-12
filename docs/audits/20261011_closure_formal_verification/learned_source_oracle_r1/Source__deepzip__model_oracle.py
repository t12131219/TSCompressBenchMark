"""Inventory every public source model and freeze weights/probability traces.

All model construction/inference uses unmodified upstream models.py. The
portable weight representation is a test bridge, never a deployed predictor.
"""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import struct
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'upstream/src'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(model, name, path):
    import numpy as np
    kinds = dict(Embedding=1, CuDNNGRU=2, CuDNNLSTM=3, Dense=4,
                 Flatten=5, BatchNormalization=6)
    activations = dict(linear=0, relu=1, elu=2, selu=3, softmax=4)
    layers = []
    with path.open('wb') as f:
        f.write(b'DZMODEL1')
        n = name.encode('ascii')
        f.write(struct.pack('<I', len(n)))
        f.write(n)
        f.write(struct.pack('<I', len(model.layers)))
        for layer in model.layers:
            base = layer.forward_layer if layer.__class__.__name__ == 'Bidirectional' else layer
            kind = kinds[base.__class__.__name__]
            flags = int(getattr(base, 'return_sequences', False))
            flags |= 2 * int(base is not layer)
            weights = layer.get_weights()
            flags |= 4 * int(any(w.dtype == np.float16 for w in weights))
            activation = getattr(base, 'activation', None)
            act_name = getattr(activation, '__name__', None)
            if activation is not None and activation.__class__.__name__ == 'ELU':
                act_name = 'elu'
            act = activations.get(act_name, 0)
            epsilon = float(getattr(base, 'epsilon', 0.001))
            f.write(struct.pack('<IIIIf', kind, flags, act, len(weights), epsilon))
            tensors = []
            for w in weights:
                data = np.asarray(w, dtype='<f4', order='C')
                f.write(struct.pack('<I', data.ndim))
                f.write(struct.pack('<' + 'I' * data.ndim, *data.shape))
                f.write(data.tobytes())
                tensors.append(dict(shape=list(w.shape), dtype=str(w.dtype),
                                    sha256=hashlib.sha256(w.tobytes()).hexdigest()))
            layers.append(dict(kind=kind, flags=flags, activation=act,
                               epsilon=epsilon, tensors=tensors))
    return layers


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--model-name')
    p.add_argument('--checkpoint', type=Path)
    p.add_argument('--alphabet', type=int, default=4)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    import tensorflow as tf
    import keras
    import numpy as np
    from keras import backend as K
    import models
    names = [a.model_name] if a.model_name else [n for n, v in vars(models).items()
                                               if inspect.isfunction(v) and v.__module__ == 'models']
    result = dict(schema_version=1, source_modified=False,
                  source_models_sha256=sha(ROOT / 'upstream/src/models.py'),
                  tensorflow=tf.__version__, keras=keras.__version__, numpy=np.__version__,
                  cases=[])
    for name in names:
        K.clear_session()
        K.set_floatx('float32')
        tf.set_random_seed(42)
        np.random.seed(0)
        config = tf.ConfigProto(intra_op_parallelism_threads=1, inter_op_parallelism_threads=1)
        config.gpu_options.allow_growth = True
        K.set_session(tf.Session(config=config))
        case = dict(name=name, alphabet=a.alphabet, batch=4, context=64)
        try:
            model = getattr(models, name)(4, 64, a.alphabet)
            if a.checkpoint:
                model.load_weights(str(a.checkpoint))
                case['checkpoint_sha256'] = sha(a.checkpoint)
            x = np.concatenate([np.zeros((1, 64), dtype='int32'),
                                np.full((1, 64), a.alphabet - 1, dtype='int32'),
                                (np.arange(64) % a.alphabet).reshape(1, 64),
                                np.random.randint(a.alphabet, size=(1, 64))], axis=0)
            prob = model.predict(x, batch_size=4)
            repeat = model.predict(x, batch_size=4)
            cumul = np.zeros((4, a.alphabet + 1), dtype=np.uint64)
            expression = prob * 10000000 + 1
            cumul[:, 1:] = np.cumsum(expression, axis=1)
            case.update(probability_dtype=str(prob.dtype), expression_dtype=str(expression.dtype),
                        probabilities=prob.tolist(), cumulative=cumul.tolist(),
                        finite=bool(np.isfinite(prob).all()),
                        deterministic=bool(np.array_equal(prob, repeat)))
            prefix = a.output / name
            x.astype('<i4').tofile(str(prefix) + '.contexts')
            prob.astype('<f4').tofile(str(prefix) + '.probabilities')
            cumul.astype('<u8').tofile(str(prefix) + '.cumulative')
            portable = Path(str(prefix) + '.dzm')
            case['layers'] = export(model, name, portable)
            case['model_sha256'] = sha(portable)
            case['model_bytes'] = portable.stat().st_size
            checkpoint = Path(str(prefix) + '.hdf5')
            if not a.checkpoint:
                model.save_weights(str(checkpoint))
                case['checkpoint_sha256'] = sha(checkpoint)
            # No substitute inference formula is used by this oracle.
            case['status'] = 'PASS' if case['finite'] and case['deterministic'] else 'FAIL'
        except Exception:
            case.update(status='FAIL', traceback=traceback.format_exc())
        result['cases'].append(case)
        (a.output / 'model_inventory.json').write_text(json.dumps(result, indent=2) + '\n')
        print(name, case['status'])
    (a.output / 'model_inventory.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if all(c['status'] == 'PASS' for c in result['cases']) else 1


if __name__ == '__main__':
    sys.exit(main())
