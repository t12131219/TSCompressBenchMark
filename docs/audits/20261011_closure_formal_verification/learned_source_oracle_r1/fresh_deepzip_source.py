"""Diagnostic only: exact fixed portable weights in the unchanged source graph.

No training, native expected generation, initializer-equivalence claim or
source-container test. Run under the restored pinned original environment.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')


def portable(path, np):
    raw = path.read_bytes()
    if raw[:8] != b'DZMODEL1':
        raise ValueError('portable magic')
    offset = 8
    def u32():
        nonlocal offset
        value, = struct.unpack_from('<I', raw, offset)
        offset += 4
        return value
    length = u32()
    name = raw[offset:offset+length].decode('ascii')
    offset += length
    layers = []
    for unused in range(u32()):
        kind, flags, activation, count, epsilon = struct.unpack_from('<IIIIf', raw, offset)
        offset += 20
        weights = []
        for unused in range(count):
            rank = u32()
            shape = tuple(u32() for unused in range(rank))
            size = 1
            for dimension in shape:
                size *= dimension
            values = np.frombuffer(raw, dtype='<f4', count=size, offset=offset).copy().reshape(shape)
            offset += size * 4
            if not np.isfinite(values).all():
                raise ValueError('nonfinite portable weights')
            weights.append(values)
        layers.append((kind, flags, activation, epsilon, weights))
    if offset != len(raw):
        raise ValueError('portable trailing bytes')
    return name, layers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    out = Path(plan['output']) / 'source'
    out.mkdir(exist_ok=False)
    import numpy as np
    import tensorflow as tf
    import keras
    from keras import backend as K
    if (tf.__version__, keras.__version__, np.__version__) != ('1.8.0', '2.2.2', '1.16.4'):
        raise ValueError('restored source environment version mismatch')
    sys.path.insert(0, str(Path(plan['source_models']['path']).parent))
    import models
    if sha(Path(models.__file__)) != plan['source_models']['sha256']:
        raise ValueError('actual imported models differs from pinned source')
    model_path = Path(plan['model_snapshot']['path'])
    if sha(model_path) != plan['model_snapshot']['sha256']:
        raise ValueError('model snapshot changed')
    contexts_path = Path(plan['contexts']['path'])
    if sha(contexts_path) != plan['contexts']['sha256']:
        raise ValueError('contexts changed')
    K.clear_session()
    K.set_floatx('float32')
    tf.set_random_seed(42)
    np.random.seed(0)
    config = tf.ConfigProto(intra_op_parallelism_threads=1, inter_op_parallelism_threads=1,
                           allow_soft_placement=False)
    config.gpu_options.allow_growth = True
    session = tf.Session(config=config)
    K.set_session(session)
    name, layers = portable(model_path, np)
    if name != 'biGRU':
        raise ValueError('frozen case model name changed')
    model = models.biGRU(3, 64, 4)
    if len(model.layers) != len(layers):
        raise ValueError('source topology layer count mismatch')
    tensor_records = []
    for index, (layer, record) in enumerate(zip(model.layers, layers)):
        weights = record[-1]
        actual = layer.get_weights()
        if [w.shape for w in actual] != [w.shape for w in weights]:
            raise ValueError('source tensor shapes mismatch at layer {}'.format(index))
        if any(w.dtype != np.float32 for w in actual):
            raise ValueError('f32 fixture required')
        layer.set_weights(weights)
        assigned = layer.get_weights()
        if any(not np.array_equal(left, right) for left, right in zip(weights, assigned)):
            raise ValueError('weights not assigned bit-exactly')
        tensor_records.append(dict(layer=index, name=layer.name,
                                   tensors=[dict(shape=list(w.shape), sha256=hashlib.sha256(w.tobytes()).hexdigest())
                                            for w in assigned]))
    spec = importlib.util.spec_from_file_location('historical_deepzip_model_oracle', plan['original_export_script']['path'])
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    exported = out / 'source-reexport.dzm'
    export_layers = exporter.export(model, name, exported)
    if exported.read_bytes() != model_path.read_bytes():
        raise ValueError('source-export roundtrip does not match current deployed model')
    contexts = np.fromfile(str(contexts_path), dtype='<i4').reshape(3, 64)
    probabilities = model.predict(contexts, batch_size=3)
    repeat = model.predict(contexts, batch_size=3)
    if probabilities.shape != (3, 4) or probabilities.dtype != np.float32:
        raise ValueError('source prediction shape/dtype mismatch')
    if not np.isfinite(probabilities).all():
        raise ValueError('nonfinite source probabilities')
    probabilities.astype('<f4').tofile(str(out / 'probabilities.f32'))
    expression = probabilities * 10000000 + 1
    if expression.dtype != np.float64:
        raise ValueError('original NumPy expression promotion changed')
    cumul = np.zeros((3, 5), dtype='<u8')
    cumul[:, 1:] = np.cumsum(expression, axis=1)
    cumul.tofile(str(out / 'cumulative.u64'))
    # Independent execution tracing of the very same unchanged source graph;
    # actual CudnnRNN operations must execute on GPU, not just enumerate one.
    metadata = tf.RunMetadata()
    feed = {model.input: contexts}
    learning_phase = K.learning_phase()
    if not isinstance(learning_phase, (int, bool)):
        feed[learning_phase] = 0
    traced = session.run(model.output, feed_dict=feed,
                         options=tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE),
                         run_metadata=metadata)
    (out / 'execution-metadata.pb').write_bytes(metadata.SerializeToString())
    operations = {op.name: op.type for op in session.graph.get_operations()}
    devices = []
    cudnn_gpu = []
    for device in metadata.step_stats.dev_stats:
        nodes = []
        for node in device.node_stats:
            op = operations.get(node.node_name)
            item = dict(name=node.node_name, op=op)
            nodes.append(item)
            if 'GPU' in device.device.upper() and op and 'CudnnRNN' in op:
                cudnn_gpu.append(dict(device=device.device, **item))
        devices.append(dict(device=device.device, nodes=nodes))
    report = dict(schema_version='tscb.fresh-deepzip-fixed-weight-source.v1',
                  versions=dict(tensorflow=tf.__version__, keras=keras.__version__, numpy=np.__version__),
                  imported_source=dict(path=models.__file__, sha256=sha(Path(models.__file__))),
                  model_sha256=sha(model_path), source_reexport_sha256=sha(exported),
                  source_reexport_exact=True, tensor_assignment_exact=True, tensors=tensor_records,
                  export_layers=export_layers, contexts=contexts.tolist(), probabilities=probabilities.tolist(),
                  cumulative=cumul.tolist(), expression_dtype=str(expression.dtype),
                  repeated_predict_bit_exact=bool(np.array_equal(probabilities, repeat)),
                  traced_predict_bit_exact=bool(np.array_equal(probabilities, traced)),
                  actual_cudnn_gpu_nodes=cudnn_gpu, execution_devices=devices,
                  trained=False, source_modified=False, all_models_or_pipeline_qualified=False)
    report['status'] = 'FIXED_WEIGHT_SOURCE_DIAGNOSTIC_PASS' if (
        report['repeated_predict_bit_exact'] and report['traced_predict_bit_exact'] and cudnn_gpu) else 'FAIL'
    save(out / 'report.json', report)
    print(json.dumps({key: report[key] for key in ['status', 'model_sha256', 'probabilities', 'cumulative', 'actual_cudnn_gpu_nodes']}))
    session.close()
    return 0 if report['status'] == 'FIXED_WEIGHT_SOURCE_DIAGNOSTIC_PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
