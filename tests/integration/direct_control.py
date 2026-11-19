"""Functional comparison: matching whole-work lanes, plus an independent native check.

No elapsed time is collected here. The native differential uses caller buffers
and deliberately excludes the worker's format, I/O and owned results.
"""
import argparse
import ctypes as c
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest, load_json
from tsbench.runtime import create_build_lock, resolve_worker

PLAN = ROOT / "configs/experiments/measurement_controls/direct_routes_v1.json"
SIZE, PTR, SIZE_OUT = c.c_size_t, c.c_void_p, c.POINTER(c.c_size_t)
TYPES = {2: 1, 9: 4, 10: 8}
ALP_BACKENDS = {"scalar-unfused": 0, "falp-scalar": 1, "falp-avx2": 2,
                "falp-auto": 3, "falp-avx512bw": 4}
ALP_ENCODE_FIELDS = "alp_groups rd_groups raw_groups coded_vectors raw_vectors".split()
ALP_DECODE_FIELDS = "scalar_vectors falp_scalar_vectors native_falp_simd_counter rd_vectors raw_vectors".split()


class EncodeStats(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ALP_ENCODE_FIELDS]


class DecodeStats(c.Structure):
    _fields_ = [("effective_backend", c.c_int)] + [(name, c.c_uint64) for name in ALP_DECODE_FIELDS]


def fn(lib, name, returns, *args):
    routine = getattr(lib, name)
    routine.restype, routine.argtypes = returns, args
    return routine


def array_bytes(case):
    dtype, count = case["dtype"], case["count"]
    if case["kind"] == "byte_ramp" and dtype == 2:
        return (bytes(range(256)) * ((count + 255) // 256))[:count]
    if case["kind"] == "special_bits" and count == 5:
        if dtype == 9:
            return struct.pack("<5I", 0, 1 << 31, 1, 0xff800000, 0x7fc000ef)
        if dtype == 10:
            return struct.pack("<5Q", 0, 1 << 63, 1, 0xfff0000000000000, 0x7ff80000000000ef)
    if case["kind"] == "decimal" and dtype in {9, 10}:
        width = TYPES[dtype]
        work = bytearray(count * width)
        packer = struct.Struct("<f" if dtype == 9 else "<d")
        for i in range(count):
            packer.pack_into(work, i * width, (i % 53) / 10)
        return bytes(work)
    raise AssertionError(f"unrecognized fixture declaration: {case}")


class LzbenchDirect:
    def __init__(self, path):
        lib = c.CDLL(str(path))
        self.create = fn(lib, "ln_create", c.c_int, c.c_int, c.c_int, c.POINTER(PTR))
        self.destroy = fn(lib, "ln_destroy", None, PTR)
        self.bound = fn(lib, "ln_compress_bound", SIZE, c.c_int, SIZE)
        self.compress = fn(lib, "ln_compress", c.c_int, PTR, PTR, SIZE, PTR, SIZE, SIZE_OUT)
        self.decompress = fn(lib, "ln_decompress", c.c_int, PTR, PTR, SIZE, PTR, SIZE, SIZE, SIZE_OUT)
        self.zstd = 8  # LN_ZSTD in the locked lzbench_native.h enum.

    def check(self, original, payload):
        capacity = self.bound(self.zstd, len(original))
        # Over-block path: the source contract rejects the size in bound, and
        # the adapter rejects before invoking ln_compress.
        if payload is None:
            assert capacity == 0
            return {"native_bound": capacity}
        assert capacity
        ctx = PTR()
        assert self.create(self.zstd, 3, c.byref(ctx)) == 0
        try:
            written, buffer = SIZE(), c.create_string_buffer(capacity)
            assert self.compress(ctx, original, len(original), buffer, capacity, c.byref(written)) == 0
            assert buffer.raw[:written.value] == payload
        finally:
            self.destroy(ctx)
        ctx = PTR()
        assert self.create(self.zstd, 3, c.byref(ctx)) == 0
        try:
            written, decoded = SIZE(), c.create_string_buffer(max(1, len(original)))
            assert self.decompress(ctx, payload, len(payload), decoded, len(original), len(original), c.byref(written)) == 0
            assert written.value == len(original) and decoded.raw[:written.value] == original
        finally:
            self.destroy(ctx)
        return {"native_bound": capacity, "native_payload_bytes": len(payload), "level": 3}


class AlpDirect:
    def __init__(self, path):
        lib = c.CDLL(str(path))
        self.bound = fn(lib, "alpn_compress_bound", SIZE, SIZE, c.c_uint)
        self.compress = fn(lib, "alpn_compress", c.c_int, PTR, SIZE, c.c_uint, c.c_int, PTR, SIZE,
                           SIZE_OUT, c.POINTER(EncodeStats))
        self.inspect = fn(lib, "alpn_inspect", c.c_int, PTR, SIZE, c.POINTER(c.c_uint), SIZE_OUT)
        self.available = fn(lib, "alpn_backend_available", c.c_int, c.c_int, c.c_uint)
        self.decode = fn(lib, "alpn_decompress_ex", c.c_int, PTR, SIZE, SIZE, PTR, SIZE,
                         SIZE_OUT, c.c_int, c.POINTER(DecodeStats))
        self.backend = fn(lib, "alpn_backend_name", c.c_char_p, c.c_int)

    def check(self, original, payload, case, options, encode_info, decode_info):
        count, width = case["count"], TYPES[case["dtype"]] * 8
        capacity = self.bound(count, width)
        assert capacity
        written, buffer, es = SIZE(), c.create_string_buffer(capacity), EncodeStats()
        assert self.compress(original, count, width, 0, buffer, capacity, c.byref(written), c.byref(es)) == 0
        assert buffer.raw[:written.value] == payload
        encode = {key: getattr(es, key) for key in ALP_ENCODE_FIELDS}
        assert {key: encode_info[key] for key in encode} == encode
        n, w = SIZE(), c.c_uint()
        assert self.inspect(payload, len(payload), c.byref(w), c.byref(n)) == 0
        assert (n.value, w.value) == (count, width)
        requested = ALP_BACKENDS[options["decode_backend"]]
        decoded, ds = c.create_string_buffer(max(1, len(original))), DecodeStats()
        rc = self.decode(payload, len(payload), count, decoded, count, c.byref(written), requested, c.byref(ds))
        common = {"native_payload_bytes": len(payload), "native_encode_counters": encode}
        if decode_info is None:
            assert not self.available(requested, width) and rc == 1  # ALPN_INVALID, not silent fallback
            return {**common, "native_decode_status": rc, "available": False}
        assert rc == 0 and written.value == count and decoded.raw[:len(original)] == original
        decode = {key: getattr(ds, key) for key in ALP_DECODE_FIELDS}
        assert self.backend(ds.effective_backend).decode() == decode_info["backend"]
        assert {key: decode_info[key] for key in decode} == decode
        return {**common, "native_decode_counters": decode, "effective_backend": decode_info["backend"]}


def assert_status(result, status, *outputs):
    assert result.returncode == 3 and result.stderr.startswith(f"plugin status {status}:".encode()), result
    assert not any(output.exists() for output in outputs)


def pair(root, plugin, binding, executables, case, native):
    original = array_bytes(case)
    count, dtype = case["count"], case["dtype"]
    schema = canonical_bytes({"dtype": dtype, "rank": 1, "role": "bytes" if dtype == 2 else "value"})
    options = canonical_bytes(binding["options"]).decode()
    src, meta = root / "source.bin", root / "source.json"
    src.write_bytes(original)
    meta.write_bytes(schema)
    observed = {"case": case["id"], "count": count, "dtype": dtype, "options": binding["options"],
                "input_bytes": len(original), "input_sha256": digest(src), "schema_sha256": digest(meta)}
    encodings = []
    for lane, executable in enumerate(executables):
        frame = root / f"frame-{lane}"
        cmd = [executable, "encode", binding["library"], plugin, options, str(dtype), src, meta, frame]
        result = run_worker(root, cmd, check="expected_status" not in case)
        if "expected_status" in case:
            assert_status(result, case["expected_status"], frame)
        else:
            encodings.append((frame, json.loads(result.stdout)))
    src.unlink()
    meta.unlink()
    if "expected_status" in case:
        return {**observed, "status": "expected_encode_rejection", "plugin_status": case["expected_status"],
                "native": native.check(original, None)}
    (a, a_info), (b, b_info) = encodings
    wire = a.read_bytes()
    assert a_info == b_info and wire == b.read_bytes(), case["id"]
    decoded_evidence = []
    for lane, (executable, frame) in enumerate(zip(executables, (a, b))):
        out, restored = root / f"out-{lane}", root / f"schema-{lane}"
        result = run_worker(root, [executable, "decode", binding["library"], plugin, options, frame, out, restored],
                     check="expected_decode_status" not in case)
        if "expected_decode_status" in case:
            assert_status(result, case["expected_decode_status"], out, restored)
            decoded_evidence.append(None)
        else:
            descriptor, info = map(json.loads, result.stdout.splitlines())
            assert descriptor == {"dtype": dtype, "count": count}
            assert out.read_bytes() == original and restored.read_bytes() == schema
            decoded_evidence.append(info)
            out.unlink()
            restored.unlink()
    assert decoded_evidence[0] == decoded_evidence[1]
    decode_info = decoded_evidence[0]
    if plugin == "raw-store":
        expected = struct.pack("<8sIQI", b"BMKRAW\x01\x00", dtype, count, len(schema)) + schema + original
        assert wire == expected
        difference = {"independent_wire_reference_equal": True}
    else:
        payload = wire[32 + len(schema):]
        assert struct.unpack_from("<IQIQ", wire, 8) == (dtype, count, len(schema), len(payload))
        assert wire[32:32 + len(schema)] == schema
        difference = native.check(original, payload) if plugin == "zstd" else native.check(
            original, payload, case, binding["options"], a_info, decode_info)
    observed.update(status="matched" if decode_info is not None else "expected_decode_rejection",
                    frame_bytes=len(wire), frame_sha256=digest(a), encode=a_info, decode=decode_info,
                    native=difference)
    a.unlink()
    b.unlink()
    return observed


def method_cases(plugin, worker, linked, module, deps, cases):
    with tempfile.TemporaryDirectory(prefix="tsbench-direct-controls-") as folder:
        root = Path(folder)
        for name in ("catalog", "schemas", "plugins", "include", "cmake", "tools", "third_party"):
            shutil.copytree(ROOT / name, root / name)
        module_name = Path(module).name
        for path in (worker, linked, module, *deps):
            shutil.copy2(path, root / Path(path).name)
        worker_name, linked_name = Path(worker).name, Path(linked).name
        lock = create_build_lock(root, worker_name, {plugin: module_name})
        binding = resolve_worker(root, lock, plugin, {})
        deps_bound = binding["dependencies"]
        native = None if plugin == "raw-store" else (LzbenchDirect if plugin == "zstd" else AlpDirect)(deps_bound[0])
        results = [pair(root, plugin, resolve_worker(root, lock, plugin, case.get("options", {})),
                        (binding["worker"], root / linked_name), case, native) for case in cases]
        return {"method": plugin, "build_id": lock["build_id"], "linked_worker_sha256": digest(root / linked_name),
                "artifacts": lock, "cases": results}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("worker")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--method", action="append", required=True, nargs="+")
    args = parser.parse_args()
    plan = load_json(PLAN)
    assert plan["schema"] == "bmk.direct-control/1" and plan["state"] == "development_functional_only"
    assert [row[0] for row in args.method] == list(plan["cases"]), "the full diagnostic plan must run in one process"
    methods = [method_cases(plugin, args.worker, linked, module, deps, plan["cases"][plugin])
               for plugin, linked, module, *deps in args.method]
    evidence = {"schema": "bmk.direct-control-evidence/1", "plan_sha256": digest(PLAN),
                "boundary": plan["same_work"], "qualification_granted": False,
                "methods": methods, "not_run": plan["not_run"]}
    # CTest deliberately truncates long passing stdout. Publish one complete
    # developer diagnostic file, only after all cases finish.
    with tempfile.TemporaryDirectory(prefix=".direct-control-", dir=args.evidence.parent) as folder:
        staged = Path(folder) / args.evidence.name
        staged.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staged.replace(args.evidence)
    print(f"verified {sum(len(method['cases']) for method in methods)} control cases: {args.evidence}")


if __name__ == "__main__":
    main()
