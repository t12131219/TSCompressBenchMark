"""Untimed, same-library payload comparisons with the APIs used by lzbench.

This checks bytes and restoration only. It neither runs lzbench nor measures
throughput. Existing codec builds and benchmark results are never changed.
Run with PYTHONPATH=benchmark/src and an unused --output-dir.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

from tsbench.artifact import read_bundle_prefix
from tsbench.bridges import create_bridge
from tsbench.build import artifact_path
from tsbench.data import load_dataset, project
from tsbench.registry import Registry
from tsbench.schemes import ObjectScheme, decode_once


ROOT = Path(__file__).resolve().parents[2]
KEYS = ("snappy-raw", "zstd-frame", "lz4-frame")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_record(path):
    path = path.resolve()
    return {"path": str(path), "nbytes": path.stat().st_size,
            "sha256": sha(path.read_bytes())}


def function(lib, name, arguments, result):
    fn = getattr(lib, name)
    fn.argtypes = arguments
    fn.restype = result
    return fn


def storage(raw):
    return ct.create_string_buffer(raw, max(1, len(raw)))


def snappy(lib, raw):
    bound = function(lib, "_ZN6snappy19MaxCompressedLengthEm", [ct.c_size_t], ct.c_size_t)
    compress = function(lib, "_ZN6snappy11RawCompressEPKcmPcPm",
                        [ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.POINTER(ct.c_size_t)], None)
    decompress = function(lib, "_ZN6snappy13RawUncompressEPKcmPc",
                          [ct.c_void_p, ct.c_size_t, ct.c_void_p], ct.c_bool)
    src, dst = storage(raw), ct.create_string_buffer(bound(len(raw)))
    length = ct.c_size_t()
    compress(src, len(raw), dst, ct.byref(length))
    payload = dst.raw[:length.value]
    restored = ct.create_string_buffer(max(1, len(raw)))
    assert decompress(storage(payload), len(payload), restored), "Snappy decode failed"
    assert restored.raw[:len(raw)] == raw, "Snappy roundtrip differs"
    return {"snappy_RawCompress": payload}


def zstd(lib, raw, level):
    bound = function(lib, "ZSTD_compressBound", [ct.c_size_t], ct.c_size_t)
    create_c = function(lib, "ZSTD_createCCtx", [], ct.c_void_p)
    create_d = function(lib, "ZSTD_createDCtx", [], ct.c_void_p)
    free_c = function(lib, "ZSTD_freeCCtx", [ct.c_void_p], ct.c_size_t)
    free_d = function(lib, "ZSTD_freeDCtx", [ct.c_void_p], ct.c_size_t)
    param = function(lib, "ZSTD_CCtx_setParameter", [ct.c_void_p, ct.c_int, ct.c_int], ct.c_size_t)
    compress = function(lib, "ZSTD_compress2",
                        [ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_size_t], ct.c_size_t)
    decompress = function(lib, "ZSTD_decompressDCtx",
                          [ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_size_t], ct.c_size_t)
    is_error = function(lib, "ZSTD_isError", [ct.c_size_t], ct.c_uint)

    def checked(code):
        assert not is_error(code), f"Zstd returned error code {code}"
        return code

    outputs = {}
    for checksum in (False, True):
        cctx, dctx = create_c(), create_d()
        assert cctx and dctx, "Zstd context allocation failed"
        try:
            # Stable ZSTD_cParameter values from the vendored zstd.h.
            checked(param(cctx, 100, level))  # ZSTD_c_compressionLevel
            checked(param(cctx, 200, 1))      # ZSTD_c_contentSizeFlag
            checked(param(cctx, 201, int(checksum)))  # ZSTD_c_checksumFlag
            src, dst = storage(raw), ct.create_string_buffer(bound(len(raw)))
            length = checked(compress(cctx, dst, len(dst), src, len(raw)))
            payload = dst.raw[:length]
            restored = ct.create_string_buffer(max(1, len(raw)))
            length = checked(decompress(dctx, restored, len(raw), storage(payload), len(payload)))
            assert length == len(raw) and restored.raw[:length] == raw, "Zstd roundtrip differs"
            outputs[f"ZSTD_compress2_checksum_{'on' if checksum else 'off'}"] = payload
        finally:
            checked(free_c(cctx))
            checked(free_d(dctx))
    return outputs


def lz4(lib, raw):
    bound = function(lib, "LZ4_compressBound", [ct.c_int], ct.c_int)
    compress = function(lib, "LZ4_compress_default",
                        [ct.c_void_p, ct.c_void_p, ct.c_int, ct.c_int], ct.c_int)
    decompress = function(lib, "LZ4_decompress_safe",
                          [ct.c_void_p, ct.c_void_p, ct.c_int, ct.c_int], ct.c_int)
    assert len(raw) <= 0x7E000000, "input exceeds LZ4 block limit"
    dst = ct.create_string_buffer(bound(len(raw)))
    length = compress(storage(raw), dst, len(raw), len(dst))
    assert length > 0, "LZ4 compression failed"
    payload = dst.raw[:length]
    restored = ct.create_string_buffer(max(1, len(raw)))
    length = decompress(storage(payload), restored, len(payload), len(raw))
    assert length == len(raw) and restored.raw[:length] == raw, "LZ4 roundtrip differs"
    return {"LZ4_compress_default_raw_block": payload}


def source_comparison(upstream):
    comparisons = []
    for local, remote in (("adapters/zstd_frame/vendor/zstd/lib", "lz/zstd/lib"),
                          ("adapters/snappy_raw/vendor/snappy", "lz/snappy"),
                          ("adapters/lz4_frame/vendor/lz4/lib", "lz/lz4/lib")):
        entries = []
        for path in sorted((ROOT / local).rglob("*")):
            if not path.is_file():
                continue
            target = upstream / remote / path.relative_to(ROOT / local)
            entries.append({"relative_path": str(path.relative_to(ROOT / local)),
                            "local": file_record(path),
                            "upstream": file_record(target) if target.is_file() else None,
                            "identical": target.is_file() and path.read_bytes() == target.read_bytes()})
        comparisons.append({"local": local, "upstream": remote, "files": entries})
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "benchmark/experiments/gorilla/records.toml")
    parser.add_argument("--lzbench-source", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    artifacts = out / "artifacts"
    artifacts.mkdir()

    def preserve(raw):
        path = artifacts / (sha(raw) + ".bin")
        if not path.exists():
            path.write_bytes(raw)
        assert path.read_bytes() == raw
        return {"path": str(path.relative_to(out)), "nbytes": len(raw), "sha256": sha(raw)}

    upstream = args.lzbench_source.resolve()
    registry = Registry(ROOT)
    bridges = {key: create_bridge(ROOT, key) for key in KEYS}
    config = tomllib.loads(args.config.read_text())
    result = {"schema": "tsbench.lzbench-payload-diagnosis/1", "performance_measurement": False,
              "scope": "six real value matrices, no timestamps/mask, one contiguous part, same shared libraries",
              "tool": file_record(Path(__file__)), "config": file_record(args.config),
              "lzbench_source_commit": subprocess.check_output(
                  ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip(),
              "source_comparisons": source_comparison(upstream), "builds": {}, "cases": []}
    source_paths = [ROOT / "benchmark/src/tsbench" / name for name in
                    ("_native_recipes.py", "bridges/c_abi_v1.py", "bridges/__init__.py",
                     "schemes.py", "data.py", "artifact.py", "report.py", "executors/cpu.py")]
    source_paths += [ROOT / f"adapters/{name}/native/{file}" for name, file in
                     (("lz4_frame", "tscb_lz4_frame.c"), ("zstd_frame", "tscb_zstd_frame.c"),
                      ("snappy_raw", "tscb_snappy_raw.cc"), ("lzss_raw", "lzss_raw_codec.cc"))]
    source_paths += [upstream / name for name in ("Makefile", "bench/lz_codecs.cpp", "bench/lzbench.cpp", "bench/lzbench.h")]
    result["sources"] = [file_record(path) for path in source_paths]
    for key in KEYS:
        path = artifact_path(ROOT, key)
        result["builds"][key] = {"binary": file_record(path), "record": file_record(path.parent / "build.json"),
                                   "commands": json.loads((path.parent / "build.json").read_text())["commands"],
                                   "params": registry.resolve_params(key, {})}
    for spec in config["datasets"]:
        obj = project(load_dataset(spec, args.config.parent), "values")
        assert set(obj.components) == {"V"}, "diagnostic expects only a value matrix"
        array = obj.components["V"]
        raw = array.tobytes(order="C")
        case = {"dataset": spec, "source": file_record(Path(spec["path"])),
                "dtype": array.dtype.str, "shape": list(array.shape), "order": "C",
                "input": preserve(raw), "codecs": {}}
        for key, bridge in bridges.items():
            params = result["builds"][key]["params"]
            method = {"id": key, "codec": key, "params": params}
            scheme = ObjectScheme(method, asset_root=ROOT)
            scheme.prepare(obj)
            encoded = scheme.encode_once(obj)
            desc, payload = read_bundle_prefix(encoded.wire)
            assert desc["codec_input_bytes"] == len(raw)
            assert len(desc["components"]) == len(desc["components"][0]["parts"]) == 1
            assert bridge.encode(array, params) == payload, "bridge/object native payload differs"
            assert bridge.last_input_identity["content_sha256"] == sha(raw)
            restored = decode_once(encoded, asset_root=ROOT).components["V"]
            assert restored.tobytes(order="C") == raw and restored.dtype == array.dtype and restored.shape == array.shape
            core = (snappy(bridge.lib, raw) if key == "snappy-raw" else
                    zstd(bridge.lib, raw, params["compression_level"]) if key == "zstd-frame" else lz4(bridge.lib, raw))
            row = {"adapter_payload": preserve(payload), "header_bytes": len(encoded.wire) - len(payload),
                   "wire": preserve(encoded.wire), "core": {}, "bitwise_object_roundtrip": True,
                   "input_unchanged": array.tobytes(order="C") == raw}
            for name, output in core.items():
                if key != "lz4-frame":
                    assert bridge.decode(output, array.dtype, array.shape, params).tobytes(order="C") == raw
                row["core"][name] = {**preserve(output), "equals_adapter_payload": output == payload,
                                      "bitwise_roundtrip": True,
                                      "bridge_cross_decode": key != "lz4-frame"}
            if key == "snappy-raw":
                assert core["snappy_RawCompress"] == payload, "Snappy raw outputs differ"
            case["codecs"][key] = row
        result["cases"].append(case)
    for path in artifacts.iterdir():
        assert path.stem == sha(path.read_bytes()), "retained artifact hash differs"
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(result["cases"]), "codecs": list(KEYS),
                      "untimed": True, "results": str(out / "results.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
