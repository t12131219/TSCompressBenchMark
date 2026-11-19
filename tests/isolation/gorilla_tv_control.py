"""Developer-only Gorilla TV differential, relocated recovery and native mechanism probes."""
import ctypes as c
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest
from tsbench.planner.gorilla import (DIR, HEADER, LIMIT, PLUGIN, PREFIX, RESUMED, SCHEMA, SNAPSHOT, TRAFFIC,
                                    UNINTERRUPTED, columns, oracle, plan_gorilla, sha)
from tsbench.qualification.gorilla import frame_ref, verify_gorilla
from tsbench.runtime import create_build_lock, resolve_worker


class Sample(c.Structure):
    _fields_ = [("timestamp", c.c_int64), ("bits", c.c_uint64)]

    def pair(self):
        return self.timestamp, self.bits


class Buffer(c.Structure):
    _fields_ = [("data", c.c_void_p), ("size", c.c_size_t)]


class Array(c.Structure):
    _fields_ = [("data", c.POINTER(Sample)), ("count", c.c_size_t)]


class Native:
    def __init__(self, library):
        self.lib = c.CDLL(str(library))
        ptr, size, sizep, ptrp = c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t), c.POINTER(c.c_void_p)
        bp, sp, present = c.POINTER(Buffer), c.POINTER(Sample), c.POINTER(c.c_int)
        signatures = {
            "g_compress": (sp, size, bp), "g_decompress": (c.c_char_p, size, size, c.POINTER(Array)),
            "g_encoder_create": (size, ptrp),
            "g_encoder_append": (ptr, sp, size), "g_encoder_snapshot": (ptr, bp),
            "g_encoder_finish": (ptr, bp), "g_encoder_reset": (ptr,),
            "g_encoder_resume": (ptr, c.c_char_p, size), "g_encoder_progress": (ptr, sizep, sizep, sizep),
            "g_iterator_create": (c.c_char_p, size, size, ptrp), "g_iterator_reset": (ptr, c.c_char_p, size, size),
            "g_iterator_next": (ptr, sp, present), "g_iterator_seek": (ptr, c.c_int64, sp, present),
        }
        for name, signature in signatures.items():
            f = getattr(self.lib, name)
            f.argtypes, f.restype = signature, c.c_int
        for name in ("g_free", "g_encoder_destroy", "g_iterator_destroy"):
            f = getattr(self.lib, name)
            f.argtypes, f.restype = (ptr,), None

    def frame(self, call, *args):
        out = Buffer()
        try:
            assert call(*args, c.byref(out)) == 0
            return c.string_at(out.data, out.size)
        finally:
            self.lib.g_free(out.data)

    def compress(self, pairs):
        return self.frame(self.lib.g_compress, samples(pairs), len(pairs))

    @contextmanager
    def encoder(self):
        out = c.c_void_p()
        assert self.lib.g_encoder_create(LIMIT, c.byref(out)) == 0
        try:
            yield out
        finally:
            self.lib.g_encoder_destroy(out)

    def progress(self, encoder):
        count, bits, workspace = (c.c_size_t() for _ in range(3))
        assert self.lib.g_encoder_progress(encoder, c.byref(count), c.byref(bits), c.byref(workspace)) == 0
        return {"rows": count.value, "chunk_bits": bits.value, "workspace_bytes": workspace.value}

    def decompress(self, data):
        out = Array()
        try:
            assert self.lib.g_decompress(data, len(data), LIMIT, c.byref(out)) == 0
            assert out.count <= LIMIT
            return [out.data[i].pair() for i in range(out.count)]
        finally:
            self.lib.g_free(out.data)

    def mechanisms(self, pairs, batch, work, evidence, lib_path):
        """Exercise the actual append/snapshot/reset/resume API against untouched batch."""
        lib = self.lib
        statuses = {}
        first, rest = pairs[:PREFIX], pairs[PREFIX:]
        with self.encoder() as enc:
            assert lib.g_encoder_append(enc, samples(first), len(first)) == 0
            progress = self.progress(enc)
            snapshot = self.frame(lib.g_encoder_snapshot, enc)
            assert snapshot == self.compress(first)
            statuses['invalid_span'] = lib.g_encoder_append(enc, None, LIMIT)
            statuses['overflow'] = lib.g_encoder_append(enc, samples(pairs), LIMIT)
            unchanged = self.progress(enc)
            assert unchanged == progress
            assert lib.g_encoder_append(enc, samples(rest), len(rest)) == 0
            uninterrupted = self.frame(lib.g_encoder_finish, enc)
            again = self.frame(lib.g_encoder_finish, enc)
            statuses['closed_append'] = lib.g_encoder_append(enc, None, 0)
            assert lib.g_encoder_reset(enc) == 0
            reset = self.frame(lib.g_encoder_snapshot, enc)
        with self.encoder() as enc:
            statuses['bad_snapshot'] = lib.g_encoder_resume(enc, snapshot + b"\0", len(snapshot) + 1)
            assert lib.g_encoder_reset(enc) == 0  # only resume after the documented reset
            assert lib.g_encoder_resume(enc, snapshot, len(snapshot)) == 0
            resumed_prefix = self.progress(enc)
            assert lib.g_encoder_append(enc, samples(rest), len(rest)) == 0
            resumed = self.frame(lib.g_encoder_finish, enc)
        assert resumed == uninterrupted == again == batch
        artifacts = [(SNAPSHOT, snapshot), (UNINTERRUPTED, uninterrupted), (RESUMED, resumed)]
        for name, raw in artifacts:
            (evidence / name).write_bytes(raw)
        child = run_worker(work, [sys.executable, '-I', '-B', Path(__file__).resolve(),
                                   '--restore-native', lib_path, evidence / SNAPSHOT])
        return {'files': [frame_ref(name, raw) for name, raw in artifacts], 'prefix_before': progress,
                'no_progress_after_overflow': unchanged, 'resumed_prefix': resumed_prefix, 'invalid_statuses': statuses,
                'finish_again_sha256': sha(again), 'reset_snapshot_hex': reset.hex(), 'snapshot_child': json.loads(child.stdout)}

    def iterator(self, pairs, batch, script):
        lib = self.lib
        iterator, value, present = c.c_void_p(), Sample(), c.c_int()
        assert lib.g_iterator_create(batch, len(batch), LIMIT, c.byref(iterator)) == 0
        try:
            def step(call, *args):
                status = call(iterator, *args, c.byref(value), c.byref(present))
                return [status, list(value.pair()) if present.value else None]
            drained = []
            for pair in pairs:
                status, observed = step(lib.g_iterator_next)
                assert [status, observed] == [0, list(pair)]
                drained.append(observed)
            eof = step(lib.g_iterator_next)
            assert lib.g_iterator_reset(iterator, batch, len(batch), LIMIT) == 0
            seeks = [[op, query, *(step(lib.g_iterator_seek, query) if op == 'seek' else step(lib.g_iterator_next))]
                     for op, query, *_ in script]
            trailing = batch + b"\0"
            assert lib.g_iterator_reset(iterator, trailing, len(trailing), LIMIT) == 0
            for pair in pairs:
                assert step(lib.g_iterator_next) == [0, list(pair)]
            rejected = [step(lib.g_iterator_next), step(lib.g_iterator_next)]
            return {'drained': oracle(drained), 'eof': eof, 'seeks': seeks, 'bad_trailer': rejected}
        finally:
            lib.g_iterator_destroy(iterator)


def samples(pairs):
    return (Sample * len(pairs))(*(Sample(*pair) for pair in pairs))


def work_control(executable, library, cwd, evidence, bundle):
    policy = bundle['work']
    def run(mode, name, *args):
        if name == SNAPSHOT:
            source = evidence / SNAPSHOT
            data = source.read_bytes()
        else:
            case = next(x for x in bundle['fixtures'] if x['name'] == name)
            wire = (evidence / case['frame']).read_bytes()
            data = wire[HEADER.size + len(case['schema']):]
            source = cwd / 'work.xor'
            source.write_bytes(data)
        obs = run_worker(cwd, [executable, library, mode, source, *args], library_dir=cwd)
        return {'source_sha256': sha(data), 'observed': json.loads(obs.stdout)}

    return {'observer': policy['observer'], 'executable_sha256': digest(executable),
            'resume': {x['name']: run('resume',x['source'],x['mode']) for x in policy['resume']},
            'iterator': {name: run('iterate',name,*('n' if op=='next' else f's:{q}'
                                                      for op,q,*_ in bundle['seeks'][name]))
                         for name in policy['iterator']}}


def test_worker(root, exec_worker, native, fixture, pairs, evidence):
    name = fixture['name']
    t, v = columns(pairs)
    ti, vi, schema, frame, td, vd, sd = (root / p for p in ("t.in", "v.in", "schema.in", "frame", "t.out", "v.out", "schema.out"))
    input_schema = fixture["schema"].encode("ascii")
    ti.write_bytes(t); vi.write_bytes(v); schema.write_bytes(input_schema)
    encoded = exec_worker("encode-columns", schema, frame, 7, ti, 10, vi)
    assert json.loads(encoded.stdout)["operation"] == "encode"
    full = frame.read_bytes()
    payload = native.compress(pairs)
    assert full == HEADER.pack(b"BMKGTV\x01\0", len(input_schema), len(pairs), len(payload)) + input_schema + payload
    ti.unlink(); vi.unlink(); schema.unlink()
    result = exec_worker("decode-columns", frame, sd, td, vd)
    desc, info = map(json.loads, result.stdout.splitlines())
    assert desc == {"columns": [{"dtype": 7, "count": len(pairs)}, {"dtype": 10, "count": len(pairs)}]}
    assert info["operation"] == "decode" and info["backend"] == "gorilla-c11"
    assert td.read_bytes() == t and vd.read_bytes() == v and sd.read_bytes() == input_schema
    td.unlink(); vd.unlink(); sd.unlink()
    malformed = [full + b"\0", full[:-1], full[:HEADER.size] + input_schema.replace(b'"ms"', b'" s"') + payload,
                 full[:HEADER.size + len(input_schema)] + bytes([payload[0] ^ 1]) + payload[1:]]
    for bad in malformed:
        frame.write_bytes(bad)
        r = exec_worker("decode-columns", frame, sd, td, vd, check=False)
        assert r.returncode == 3 and b"plugin status 5:" in r.stderr, r
        assert not td.exists() and not vd.exists() and not sd.exists()
    frame.unlink()
    (evidence / fixture["frame"]).write_bytes(full)
    return {"case": name, "rows": len(pairs), "milliseconds_sha256": sha(t), "value_sha256": sha(v),
            "logical_tv_bytes": len(t) + len(v), "full_frame_bytes": len(full), "full_frame_sha256": sha(full),
            "native_bytes": len(payload), "native_sha256": sha(payload), "independent_tv_verified": True,
            "rejected_frames": len(malformed), **fixture["lineage"]}


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--restore-native':
        lib, snapshot = map(Path, sys.argv[2:])
        print(canonical_bytes(oracle(Native(lib).decompress(snapshot.read_bytes()))).decode('ascii'))
        return
    worker, module, lib, control, out = [Path(p).resolve() for p in sys.argv[1:]]
    assert out.name == DIR
    bundle, pairs = plan_gorilla(ROOT)
    with tempfile.TemporaryDirectory(prefix='tsbench-gorilla-moved-', dir=out.parent) as temp:
        stage = Path(temp)
        evidence = stage / DIR
        evidence.mkdir()
        root = stage / 'work'
        root.mkdir()
        for directory in ('catalog', 'schemas', 'plugins', 'include', 'cmake', 'tools', 'third_party'):
            shutil.copytree(ROOT / directory, root / directory)
        build = {p.name: digest(p) for p in (worker, module, lib, control)}
        for p in (worker, module, lib, control):
            shutil.copy2(p, root / p.name)
        lock = create_build_lock(root, worker.name, {PLUGIN: module.name})
        binding = resolve_worker(root, lock, PLUGIN, {})

        def invoke(op, *args, check=True):
            return run_worker(root, [binding['worker'], op, binding['library'], PLUGIN, '{}', *map(str, args)], check=check)

        native = Native(root / lib.name)
        observations = [test_worker(root, invoke, native, case, pairs[case['name']], evidence) for case in bundle['fixtures']]
        traffic = pairs[TRAFFIC]
        mechanisms = native.mechanisms(traffic, native.compress(traffic), root, evidence, root / lib.name)
        mechanisms['iterators'] = {name: native.iterator(pairs[name], native.compress(pairs[name]), script)
                                   for name, script in bundle['seeks'].items()}
        mechanisms['work'] = work_control(root / control.name, root / lib.name, root, evidence, bundle)
        t, v, schema, frame = (root / p for p in ('t.in', 'v.in', 'schema.in', 'frame'))
        rejected = []
        for ts, vs, time_schema, dtype in (
            (bytes(8 * 513), bytes(8 * 513), SCHEMA, 7),
            (bytes(8), b'', SCHEMA, 7),
            (bytes(8), bytes(8), b'{"time_unit":"s"}', 7),
            (bytes(8), bytes(8), SCHEMA, 8),
        ):
            t.write_bytes(ts); v.write_bytes(vs); schema.write_bytes(time_schema)
            outcome = invoke('encode-columns', schema, frame, dtype, t, 10, v, check=False)
            assert outcome.returncode == 3 and outcome.stderr.startswith(b'plugin status ') and not frame.exists(), outcome
            rejected.append(int(outcome.stderr.partition(b':')[0].split()[-1]))
        driver = digest(Path(__file__))
        doc = {'schema': 'bmk.m0-gorilla-control/3', 'config_id': bundle['config_id'], 'definitions': driver, 'build': lock,
               'bundle_id': bundle['bundle_id'], 'case_ids': [case['case_id'] for case in bundle['cases']],
               'formal_performance': False, 'formal_qualification': False, 'rejected_inputs': rejected,
               'cases': observations, 'direct_native_mechanisms': mechanisms}
        (stage / bundle['evidence_path']).write_bytes(canonical_bytes(doc) + b'\n')
        verify_gorilla(bundle, build, driver, stage)
        out.mkdir(exist_ok=True)
        for name in bundle['binary'] + ['report.json']:
            (evidence / name).replace(out / name)


if __name__ == '__main__':
    main()
