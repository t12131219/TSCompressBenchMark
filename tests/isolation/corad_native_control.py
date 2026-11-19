#!/usr/bin/env python3
"""CORAD direct native diagnostics; no timing, formal qualification or worker adapter."""
import ctypes as ct
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import canonical_bytes, digest, load_json
from tsbench.planner.corad_training import STAGED_BRIDGE, VECTORS, plan_corad_training, ref, source_argv
from tsbench.qualification.corad_wire import interpret, quality
HEADER = struct.Struct('<4sIHHHHdQ')
CAP = 16384  # Development probe only, substantially below the native format's cap.
OK, CAPACITY, STREAM, CONVERGENCE = 0, 2, 4, 5


class Config(ct.Structure):
    _fields_ = [('rows', ct.c_uint32), *[(k, ct.c_uint16) for k in ('columns', 'tricklet', 'atoms', 'nonzero')],
                ('threshold', ct.c_double)]


class Options(ct.Structure):
    _fields_ = ([(k, ct.c_uint32) for k in ('size', 'version', 'max_iter', 'solver_max_iter', 'solver', 'normalize')]
                + [(k, ct.c_uint64) for k in ('seed', 'training_columns')] + [('max_training_samples', ct.c_size_t)]
                + [(k, ct.c_double) for k in ('alpha', 'tolerance', 'solver_tolerance')])


class Stats(ct.Structure):
    _fields_ = [('training_samples', ct.c_size_t), ('resampled_atoms', ct.c_size_t), ('iterations', ct.c_uint),
                ('converged', ct.c_int), ('objective', ct.c_double), ('max_kkt_violation', ct.c_double)]


def recorded(obj):
    return {k: getattr(obj, k) for k, _ in obj._fields_}


def doubles(vals):
    return (ct.c_double * len(vals))(*vals)


def api(path):
    lib = ct.CDLL(str(path.resolve()))
    ptr, sz, dp, cfg, opt, stat = ct.c_void_p, ct.c_size_t, ct.POINTER(ct.c_double), ct.POINTER(Config), ct.POINTER(Options), ct.POINTER(Stats)
    sp, pp = ct.POINTER(sz), ct.POINTER(ptr)
    for name, result, args in (
        ('decode', ct.c_int, (ptr, sz, dp, sz, sz, sp, cfg)),
        ('bound', sz, (cfg,)), ('model_load', ct.c_int, (ptr, sz, pp)), ('model_free', None, (ptr,)),
        ('model_save', ct.c_int, (ptr, ptr, sz, sp)), ('model_info', ct.c_int, (ptr, cfg)),
        ('model_config', ct.c_int, (ptr, ct.c_uint32, ct.c_uint16, ct.c_double, cfg)),
        ('model_encode', ct.c_int, (ptr, cfg, dp, ptr, sz, sp)),
        ('model_pack', ct.c_int, (cfg, dp, dp, dp, ptr, sz, sp)),
        ('model_train', ct.c_int, (cfg, dp, opt, pp, stat)), ('train_options_init', None, (opt,)),
        ('sparse_code', ct.c_int, (dp, sz, sz, dp, opt, dp, dp)),
        ('dictionary_fit', ct.c_int, (dp, sz, sz, sz, opt, dp, dp, stat)),
    ):
        function = getattr(lib, 'corad_' + name)
        function.restype, function.argtypes = result, args
    return lib


def blob(fn, *args):
    storage, written = ct.create_string_buffer(CAP), ct.c_size_t()
    assert fn(*args, storage, CAP, written) == OK and HEADER.size <= written.value <= CAP
    return storage.raw[:written.value]


def decode(lib, frame, limit):
    data, n, conf = (ct.c_double * limit)(), ct.c_size_t(123), Config()
    rc = lib.corad_decode(frame, len(frame), data, limit, limit, n, conf)
    return rc, n.value, bytes(data)[:n.value * 8], conf


def train_controls(lib, opts):
    # Orthonormal signed soft threshold: exact coefficients, KKT and one
    # dictionary update at a fixed point; solver outputs are not fitted or tuned.
    initial, sample, expected = [1.,0.,0.,1.], [2.,-1.], [1.75,-0.75]
    results = []
    for solver in (0,1):
        opts.solver = solver
        z, violation = doubles([0.,0.]), ct.c_double()
        assert lib.corad_sparse_code(doubles(initial), 2, 2, doubles(sample), opts, z, violation) == OK
        kkt = max(abs(x - y + opts.alpha * math.copysign(1, x)) for x,y in zip(z,sample,strict=True))
        assert list(z) == expected and kkt == violation.value == 0
        # Axis-aligned samples leave the unit dictionary unchanged. Compute
        # objective after update independently using the known soft thresholds.
        stats, updated = Stats(), doubles([0.]*4)
        assert lib.corad_dictionary_fit(doubles([2.,0.,0.,-1.]),2,2,2,opts,doubles(initial),updated,stats) == OK
        expected_objective = opts.alpha**2 + opts.alpha*sum(abs(x) for x in expected)
        assert list(updated) == initial and abs(stats.objective - expected_objective) < 1e-14
        results.append({'solver':solver, 'coefficients':list(z),'kkt':kkt,'fixed_dictionary':list(updated),
                        'expected_objective':expected_objective,'stats':recorded(stats)})
    opts.solver_max_iter = 1
    rc = lib.corad_sparse_code(doubles([1.,0.,0.8,0.6]),2,2,doubles([2.,2.]),opts,doubles([0.,0.]),ct.c_double())
    assert rc == CONVERGENCE
    return results,rc


def control(stage, lib_file, original):
    sys.path.insert(0,str(ROOT/'tools'))
    from probe_corad_training import check_training_environment

    versions = check_training_environment()
    import numpy as np
    bundle, data = plan_corad_training(ROOT)
    policy = bundle['policy']
    assert digest(original) == bundle['bridge_sha256']
    assert versions == policy['source']['versions']
    stage.mkdir()
    lib = api(lib_file)
    cols = bundle['columns']
    train, held = (np.frombuffer(data[k][1],dtype='<f8').reshape((len(cols),-1)) for k in ('train','evaluation'))
    spec = bundle['model']
    width, atoms, nonzero, threshold = (spec[k] for k in ('tricklet','atoms','nonzero','threshold'))
    conf = Config(train.shape[1],len(cols),width,atoms,nonzero,threshold)
    raw_train = doubles(train.ravel())

    def options():
        opts = Options()
        lib.corad_train_options_init(opts)
        assert opts.size == ct.sizeof(Options)
        for key, value in bundle['c_options'].items():
            setattr(opts,key,value)
        assert recorded(opts) == bundle['c_options']
        return opts

    def fit(opts, expected):
        stats, owned = Stats(), ct.c_void_p()
        rc = lib.corad_model_train(conf,raw_train,opts,owned,stats)
        assert rc == expected and bool(owned.value) == (rc == OK)
        if rc != OK:
            return rc
        try:
            return blob(lib.corad_model_save,owned), recorded(stats)
        finally:
            lib.corad_model_free(owned)

    sparse, convergence_failure = train_controls(lib,options())
    opts = options()
    samples = (train.shape[1]//width)*opts.training_columns.bit_count()
    opts.max_training_samples = samples-1
    capacity_status = fit(opts,CAPACITY)
    opts.max_training_samples = samples
    opts.training_columns = 1 << len(cols)
    invalid_mask_status = fit(opts,1)
    opts = options()
    c_results = [fit(opts,OK) for _ in range(policy['c']['seeded_repetitions'])]
    c_model, c_stats = c_results[0]
    assert all(r == c_results[0] for r in c_results)
    # This frozen case reaches the configured outer limit and returns a usable
    # model without claiming outer convergence. Sparse failure is a separate status.
    assert c_stats['training_samples']==samples and c_stats['iterations']==opts.max_iter and c_stats['converged']==0
    _, c_meta, _ = interpret(c_model)
    mean, scale = train.mean(axis=1), train.std(axis=1)
    scale[scale==0] = 1.
    np.testing.assert_allclose(c_meta['mean'],mean,atol=policy['statistics_absolute_tolerance'],rtol=0)
    np.testing.assert_allclose(c_meta['scale'],scale,atol=policy['statistics_absolute_tolerance'],rtol=0)

    # Run unchanged Source Python code in separate processes. Only the
    # ordered training matrix (not held-out values) is staged for these fits.
    chosen = [j for j in range(len(cols)) if (opts.training_columns >> j)&1]
    cut = train.shape[1]//width*width
    vectors = ((train-mean[:,None])/scale[:,None])[chosen,:cut].reshape((-1,width))
    shutil.copyfile(original,stage/STAGED_BRIDGE)
    np.save(stage/VECTORS,vectors,allow_pickle=False)
    source_runs, models = [], {'c-lars':c_model}
    env = {**os.environ,**policy['source']['thread_environment']}
    for label in bundle['source_labels']:
        argv = source_argv(bundle,label)
        proc = subprocess.run([sys.executable,*argv],cwd=stage,env=env,capture_output=True,
                              timeout=policy['source']['timeout_seconds'],check=False)
        proc.check_returncode()
        src_json = stage/(label+'.json')
        parsed = load_json(src_json)
        dictionary = np.asarray(parsed['dictionary'])
        assert parsed['backend']=='upstream-CORAD-sklearn-DictionaryLearning' and parsed['max_iter']==policy['source']['max_iter']
        assert parsed['alpha']==opts.alpha and parsed['rows']==samples and parsed['features']==width
        assert dictionary.shape==(atoms,width) and np.isfinite(dictionary).all()
        assert len(proc.stdout)+len(proc.stderr)<=policy['capacity_bytes_per_artifact']
        models[label] = blob(lib.corad_model_pack,conf,doubles(dictionary.ravel()),doubles(mean),doubles(scale))
        source_runs.append({'origin':label,'argv':argv,'returncode':proc.returncode,
                            'dictionary':ref(src_json.name,src_json.read_bytes()),
                            'stdout':proc.stdout.decode(errors='replace'),'stderr':proc.stderr.decode(errors='replace')})

    inference = []
    for label,model in models.items():
        model_file = stage/(label+'.model.crd1')
        model_file.write_bytes(model)
        ptr, observed, actual = ct.c_void_p(),Config(),Config()
        assert lib.corad_model_load(model,len(model),ptr)==OK and ptr.value
        try:
            assert lib.corad_model_info(ptr,observed)==OK and observed.rows==0 and observed.columns==len(cols)
            assert blob(lib.corad_model_save,ptr)==model
            assert lib.corad_model_config(ptr,held.shape[1],nonzero,threshold,actual)==OK
            frame = blob(lib.corad_model_encode,ptr,actual,doubles(held.ravel()))
        finally:
            lib.corad_model_free(ptr)
        assert lib.corad_model_load(frame,len(frame),ptr)==CAPACITY and not ptr.value
        reference, counts, embedded = interpret(frame)
        assert embedded == interpret(model)[2] and counts['tail_bytes']==held.shape[1]%width*len(cols)*8
        with tempfile.TemporaryDirectory(prefix='corad-recovery-') as directory:
            child = Path(directory)
            shutil.copyfile(lib_file,child/'libcorad_c.so')
            (child/'frame.crd1').write_bytes(frame)
            subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--decode-only'],cwd=child,timeout=15,check=True)
            restored = (child/'decoded.f64le').read_bytes()
        assert restored == reference
        result = np.frombuffer(restored,dtype='<f8').reshape(held.shape)
        tail = held.shape[1]%width
        assert result[:,-tail:].tobytes()==held[:,-tail:].tobytes()
        invalid = bytearray(frame)
        struct.pack_into('<d',invalid,HEADER.size,float('nan'))
        damaged = {'nan_atom':bytes(invalid),'trailing_byte':frame+b'\0','truncated':frame[:-1]}
        if counts['first_reference'] is not None:
            off, own_column = counts['first_reference']
            bad_link = bytearray(frame)
            struct.pack_into('<H',bad_link,off,own_column)
            damaged['self_reference'] = bytes(bad_link)
        for case,bad in damaged.items():
            assert decode(lib,bad,held.size)[:2]==(STREAM,0),case
        assert decode(lib,frame,held.size-1)[:2]==(CAPACITY,0)
        frame_path, restored_path = label+'.heldout.crd1',label+'.restored.f64le'
        (stage/frame_path).write_bytes(frame)
        (stage/restored_path).write_bytes(restored)
        inference.append({'origin':label,'model':ref(model_file.name,model),'frame':ref(frame_path,frame),
                          'restored':ref(restored_path,restored),'sections':counts,'quality':quality(
                              [r.tobytes() for r in held],[r.tobytes() for r in result],cols),
                          'rejections':{**{k:STREAM for k in damaged},'max_values':CAPACITY,'model_load_data_frame':CAPACITY},
                          'config':recorded(actual)})
    assert inference[0]['sections']['references']>0
    for kind,(timestamps,values) in data.items():
        (stage/bundle['data'][kind]['timestamps']['path']).write_bytes(timestamps)
        (stage/bundle['data'][kind]['values']['path']).write_bytes(values)
    summary = {'schema':'bmk.corad-native-control/2','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],
               'bundle_id':bundle['bundle_id'],'formal_qualification':False,'formal_performance':False,
               'corad_library_sha256':digest(lib_file),'probe_sha256':digest(Path(__file__)),
               'archive_sha256':bundle['archive_sha256'],'data':bundle['data'],
               'c_training':{'options':recorded(opts),'fits':[{'model':ref('c-lars.model.crd1',m),'stats':r} for m,r in c_results],
                             'analytical_controls':sparse,'rejections':{'insufficient_training_samples':capacity_status,
                             'out_of_range_mask':invalid_mask_status,'sparse_nonconvergence':convergence_failure}},
               'source_training':{'policy':policy['source'],'environment_lock_sha256':bundle['environment_lock_sha256'],
                                  'python_sha256':digest(Path(sys.executable)),
                                  'bridge':ref(STAGED_BRIDGE,(stage/STAGED_BRIDGE).read_bytes()),
                                  'train_vectors':ref(VECTORS,(stage/VECTORS).read_bytes()),'runs':source_runs},'inference':inference}
    (stage/'audit.json').write_bytes(canonical_bytes(summary)+b'\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['--decode-only']:
        lib = api(Path('libcorad_c.so'))
        frame = Path('frame.crd1').read_bytes()
        _, rows, cols, *_ = HEADER.unpack_from(frame)
        assert 0 < rows * cols <= CAP
        rc, n, raw, _ = decode(lib,frame,rows * cols)
        assert rc == OK and n == rows * cols
        Path('decoded.f64le').write_bytes(raw)
    elif len(sys.argv) == 5 and sys.argv[1] == '--build-inputs':
        lib, bridge, stage = (Path(arg).resolve() for arg in sys.argv[2:])
        control(stage, lib, bridge)
    elif len(sys.argv) == 2:
        out = Path(sys.argv[1]).resolve()
        project = out/'release-builds/corad-native'
        control(out/'corad-native-control', project/'cmake/libcorad_c.so',
                project/'source/corad-native/source_backend/train.py')
    else:
        raise SystemExit('usage: corad_native_control.py AUDIT_ROOT | --build-inputs LIB BRIDGE OUTPUT')
