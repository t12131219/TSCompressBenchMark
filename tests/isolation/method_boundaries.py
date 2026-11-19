"""Exercise frozen method boundaries inside the single M0 native preflight."""
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from isolation.alp_control import analyze
from tsbench.assets import canonical_bytes, digest
from tsbench.planner.method_boundaries import plan_boundary_cases, sha


def exercise(folder, invoke, case, frame_limit):
    definition = case.definition
    row = definition["row"]
    name, rows = row["case"], row["rows"]
    types, columns, schema = definition["abi_types"], case.columns, case.schema
    tv = len(types) == 2
    dtype, values = types[-1], columns[-1]
    vectors = definition["expected_aln1_vectors"]
    inputs = [folder / f"input-{i}" for i in range(len(columns))]
    outputs = [folder / f"output-{i}" for i in range(len(columns))]
    meta, restored, frame = (folder / p for p in ("schema", "restored", f"{name}.bmk"))
    meta.write_bytes(schema)
    for path, raw in zip(inputs, columns, strict=True):
        path.write_bytes(raw)
    args = (meta, frame, types[0], inputs[0], types[1], inputs[1]) if tv else (dtype, inputs[0], meta, frame)
    enc = invoke("encode-columns" if tv else "encode", *args, check=False)
    record = {**row, "case_id": definition["case_id"], "encode_exit": enc.returncode}
    for path in [*inputs, meta]:
        path.unlink()
    if row["expected"] == "resource_limit_7":
        assert enc.returncode == 3 and b"plugin status 7:" in enc.stderr and not enc.stdout and not frame.exists(), enc
        return {**record, "actual": "resource_limit_7", "diagnostic": enc.stderr.decode().strip(), "artifact": None}
    assert enc.returncode == 0, enc
    e = json.loads(enc.stdout)
    assert e["operation"] == "encode" and e["threads"] == 1, e
    payload = frame.read_bytes()
    assert 0 < len(payload) <= frame_limit
    if vectors is not None:
        width = 32 if dtype == 9 else 64
        wrapper = struct.Struct("<8sIQIQ")
        magic, stored_dtype, stored_count, schema_len, data_len = wrapper.unpack_from(payload)
        assert (magic, stored_dtype, stored_count, schema_len, len(payload)) == (
            b"BMKALP\x01\0", dtype, rows, len(schema), wrapper.size + schema_len + data_len)
        native = analyze(payload[wrapper.size + schema_len:], values, width)
        assert native["coded_vectors"] + native["raw_vectors"] == vectors
        record["aln1"] = native
    decode_tail = (restored, *outputs) if tv else (outputs[0], restored)
    dec = invoke("decode-columns" if tv else "decode", frame, *decode_tail)
    descriptor, d = map(json.loads, dec.stdout.splitlines())
    expected_columns = [{"dtype": t, "count": rows} for t in types]
    assert descriptor == ({"columns": expected_columns} if tv else expected_columns[0]), descriptor
    assert d["operation"] == "decode" and d["threads"] == 1, d
    restored_schema = restored.read_bytes()
    assert restored_schema == schema
    restored_columns = []
    for path, raw in zip(outputs, columns, strict=True):
        decoded = path.read_bytes()
        assert decoded == raw
        restored_columns.append(sha(decoded))
        path.unlink()
    restored.unlink()
    return {**record, "actual": "verified", "encode_info": e, "decode_info": d,
            "restored": {"descriptor": descriptor, "schema_sha256": sha(restored_schema),
                         "columns_sha256": restored_columns},
            "artifact": {"path": frame.name, "bytes": len(payload), "sha256": sha(payload)}}


def main(worker, alp, aln, zstd, lzbench, gorilla, g, output):
    bundle, cases = plan_boundary_cases(ROOT)
    output.mkdir(exist_ok=True)
    assert not any(output.iterdir())
    results = []
    with tempfile.TemporaryDirectory(prefix="tsbench-boundary-") as tmp:
        folder = Path(tmp)
        for file in (worker, alp, aln, zstd, lzbench, gorilla, g):
            shutil.copy2(file, folder / file.name)
        modules = {"alp-auto": alp, "zstd": zstd, "gorilla-tv": gorilla}
        for case in cases:
            method = case.definition["row"]["method"]
            options = canonical_bytes(case.definition["options"]).decode()

            def invoke(op, *args, check=True):
                return run_worker(folder, [folder / worker.name, op, folder / modules[method].name, method,
                                            options, *map(str, args)], check=check)

            results.append(exercise(folder, invoke, case, bundle["case_policy"]["max_frame_bytes"]))
        for result in results:
            if artifact := result["artifact"]:
                path = output / artifact["path"]
                with path.open("xb") as f:
                    f.write((folder / path.name).read_bytes())
    body = {"schema":"bmk.m0-method-boundary-report/2", "config_id":bundle["config_id"], "bundle_id":bundle["bundle_id"],
            "build_sha256":{p.name:digest(p) for p in (worker, alp, aln, zstd, lzbench, gorilla, g)},
            "formal_qualification":False,"formal_performance":False,"rows":results}
    with (output / "report.json").open("xb") as f:
        f.write(canonical_bytes(body) + b"\n")


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
