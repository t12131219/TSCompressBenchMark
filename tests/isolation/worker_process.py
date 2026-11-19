"""Recovery with relocated binaries and original inputs absent from decode."""
from pathlib import Path
import argparse
import json
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker  # noqa: E402
from tsbench.assets import ContractError, canonical_bytes, digest  # noqa: E402
from tsbench.planner.sprintz import plain, plan_sprintz, ref, retained_paths  # noqa: E402
from tsbench.runtime import create_build_lock, resolve_worker  # noqa: E402


def examples(plugin):
    f64 = struct.pack("<5Q", 0, 1 << 63, 1, 0xFFF0000000000000, 0x7FF80000000000EF)
    if plugin == "raw-store":
        return [(10, 8, b""), (10, 8, f64)]
    if plugin == "zstd":
        return [(2, 1, b""), (2, 1, bytes(range(256)) * 256)]
    f32 = struct.pack("<5I", 0, 1 << 31, 1, 0xFF800000, 0x7FC000EF)
    decimal_tail = b"".join(struct.pack("<d", (i % 53) / 10.0) for i in range(1025))
    return [(10, 8, b""), (9, 4, f32), (10, 8, f64), (10, 8, decimal_tail)]


def probe_native(root, control, bundle):
    def invoke(*args):
        result = run_worker(root, [control, *args], check=False, library_dir=root)
        if result.returncode == 77:
            print(result.stdout.decode().strip())
            raise SystemExit(77)
        assert result.returncode == 0, result
        return result

    rows = {}
    for spec in bundle["shapes"]:
        name, width, dims, count, limit = (spec[k] for k in
            ("name", "width", "dims", "count", "message_limit_bytes"))
        original = plain(name, width, dims, count)
        src, frame, decoded = root / "native-input", root / spec["native_frame"], root / "native-restored"
        src.write_bytes(original)
        reduced = json.loads(invoke("probe", str(width), str(dims), str(limit), src, frame).stdout)
        src.unlink()
        invoke("decode", str(width), str(dims), str(limit), frame, decoded)
        restored = decoded.read_bytes()
        decoded.unlink()
        assert restored == original
        rows[name] = {"native_frame": ref(frame.name, frame.read_bytes()),
                      "restored": ref(spec["original"]["path"], restored), "reductions": reduced}
    return rows, json.loads(invoke("reject").stdout)


def smoke(root, plugin, command, bundle=None):
    if bundle is None:
        fixtures = [(None, dtype, width, data) for dtype, width, data in examples(plugin)]
    else:
        fixtures = [(spec, 4, 2, plain(spec["name"], spec["width"], spec["dims"], spec["count"]))
                    for spec in bundle["shapes"] if spec["worker_frame"]]
    observed = {}
    for spec, dtype, width, original in fixtures:
        count = len(original) // width
        schema = canonical_bytes(bundle["worker_schema"] if bundle else
                                 {"dtype": dtype, "rank": 1, "role": "bytes" if dtype == 2 else "value"})
        src, meta, frame = (root / name for name in ("values.bin", "schema.json", "frame.bmk"))
        src.write_bytes(original)
        meta.write_bytes(schema)
        encode = command("encode", str(dtype), src, meta, frame)
        encode_info = json.loads(run_worker(root, encode).stdout)
        assert encode_info["threads"] == 1 and encode_info["operation"] == "encode", encode_info
        payload = frame.read_bytes()
        assert run_worker(root, encode, check=False).returncode != 0
        assert frame.read_bytes() == payload
        if plugin == "raw-store":
            assert payload == struct.pack("<8sIQI", b"BMKRAW\x01\x00", dtype, count, len(schema)) + schema + original
        else:
            magic, stored_dtype, stored_count, schema_len, data_len = struct.unpack_from("<8sIQIQ", payload)
            assert (stored_dtype, stored_count, schema_len) == (dtype, count, len(schema))
            assert (magic, payload[32+schema_len:36+schema_len]) == (
                {"zstd": (b"BMKZST\x01\x00", b"\x28\xb5\x2f\xfd"),
                 "alp-auto": (b"BMKALP\x01\x00", b"ALN1"),
                 "sprintz-fire": (b"BMKSPR\x01\x00", b"SFB1")}[plugin])
            assert len(payload) == 32 + schema_len + data_len
            assert payload[32:32+schema_len] == schema
        if spec:
            assert payload[32+len(schema):] == (root / spec["native_frame"]).read_bytes()
        src.unlink()
        meta.unlink()
        out, restored_schema = root / "decoded.bin", root / "decoded.json"
        decode = command("decode", frame, out, restored_schema)
        result = run_worker(root, decode)
        descriptor, info = map(json.loads, result.stdout.splitlines())
        assert descriptor == {"dtype": dtype, "count": count} and info["operation"] == "decode"
        restored, schema_wire = out.read_bytes(), restored_schema.read_bytes()
        assert restored == original and schema_wire == schema
        out.unlink()
        restored_schema.unlink()
        frame.write_bytes(payload + b"trailing")
        result = run_worker(root, decode, check=False)
        assert result.returncode == 3 and b"plugin status 5" in result.stderr, result
        assert not out.exists() and not restored_schema.exists()
        if spec:
            # Mutate dtype, declared original length, the SFB1 raw CRC, or the
            # payload CRC input without implicitly changing the outer lengths.
            sfb1 = 32 + len(schema)
            for offset in (8, sfb1 + 12, sfb1 + 20, len(payload) - 1):
                bad = bytearray(payload)
                bad[offset] = 3 if offset == 8 else bad[offset] ^ 1
                frame.write_bytes(bad)
                result = run_worker(root, decode, check=False)
                assert result.returncode == 3 and b"plugin status 5" in result.stderr, (offset, result)
                assert not out.exists() and not restored_schema.exists()
            saved = root / spec["worker_frame"]
            saved.write_bytes(payload)
            observed[spec["name"]] = {"frame": ref(saved.name, payload),
                                      "restored": ref(spec["original"]["path"], restored),
                                      "schema": ref("schema.json", schema_wire),
                                      "encode": encode_info, "decode": info,
                                      "rejected": bundle["decode_rejections"]}
        frame.unlink()
    rejected = {}
    if bundle:
        # Do not silently reinterpret input bits as u16 or exceed the method cap.
        for name, dtype, data in (("f64", 10, bytes(8)), ("above_worker_limit", 4, bytes(65538))):
            src.write_bytes(data)
            meta.write_bytes(b"{}")
            result = run_worker(root, command("encode", str(dtype), src, meta, frame), check=False)
            status = bundle["worker_rejections"][name]
            assert result.returncode == 3 and f"plugin status {status}:".encode() in result.stderr, result
            assert not frame.exists()
            rejected[name] = status
    return observed, rejected


def main():
    p = argparse.ArgumentParser()
    p.add_argument("plugin")
    p.add_argument("worker")
    p.add_argument("module")
    p.add_argument("dependencies", nargs="*")
    p.add_argument("--native-control", type=Path)
    p.add_argument("--evidence", type=Path)
    args = p.parse_args()
    plugin, worker, module, dependencies = args.plugin, args.worker, args.module, args.dependencies
    assert (plugin == "sprintz-fire") == bool(args.native_control) == bool(args.evidence)
    bundle = plan_sprintz() if args.native_control else None
    with tempfile.TemporaryDirectory(prefix="tsbench-moved-worker-") as folder:
        root = Path(folder)
        for name in ("catalog", "schemas", "plugins", "include", "cmake", "tools", "third_party"):
            shutil.copytree(ROOT / name, root / name)
        shutil.copy2(worker, root / "worker")
        module_name = Path(module).name
        shutil.copy2(module, root / module_name)
        for dependency in dependencies:
            shutil.copy2(dependency, root / Path(dependency).name)
        lock = create_build_lock(root, "worker", {plugin: module_name})
        binding = resolve_worker(root, lock, plugin, {})
        options = canonical_bytes(binding["options"]).decode("utf-8")

        def command(operation, *args):
            return [binding["worker"], operation, binding["library"], plugin, options, *args]

        if bundle:
            control = root / args.native_control.name
            shutil.copy2(args.native_control, control)
            native, native_rejected = probe_native(root, control, bundle)
        observed, worker_rejected = smoke(root, plugin, command, bundle)
        if dependencies:
            # Keep a different file at a valid DSO path; the build lock rejects
            # it before another worker is launched.
            dep = root / Path(dependencies[0]).name
            dep.write_bytes(dep.read_bytes() + b"different")
            try:
                resolve_worker(root, lock, plugin, {})
            except ContractError as exc:
                assert "SHA-256 mismatch" in str(exc), str(exc)
            else:
                raise AssertionError("silently accepted a replaced dependency")
        if bundle:
            for name in retained_paths(bundle):
                shutil.copyfile(root / name, args.evidence.parent / name)
            files = [Path(worker), Path(module), *map(Path, dependencies), args.native_control]
            report = {"schema": "bmk.m0-sprintz-control/2", "bundle_id": bundle["bundle_id"],
                      "formal_qualification": False, "formal_performance": False,
                      "build_sha256": {file.name: digest(file) for file in files},
                      "driver_sha256": digest(Path(__file__)), "native": native, "worker": observed,
                      "native_rejected": native_rejected, "worker_rejected": worker_rejected}
            args.evidence.write_bytes(canonical_bytes(report) + b"\n")


if __name__ == "__main__":
    main()
