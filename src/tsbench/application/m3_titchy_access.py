"""Real-input Titchy indexed and stateless range checks, with detached recovery."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

from ..assets import ContractError, digest, local_file, require
from ..qualification.titchy_wire import TCHY, INDEX, decode_tchy

CHUNK_ROWS = 65536
WIRE_POLICY = {"chunk": 4, "endian": 0, "split": 1000, "threshold_ppm": 250000, "active_bytes": (1 << 64) - 1}


def invoke(control: Path, work: Path, *args: str) -> tuple[dict, int]:
    env = {k: v for k, v in os.environ.items() if k not in {"LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT"}}
    start = time.monotonic_ns()
    proc = subprocess.run([str(control), *args], cwd=work, env=env, capture_output=True, text=True, timeout=120)
    elapsed = time.monotonic_ns() - start
    if proc.returncode:
        raise ContractError(f"Titchy {args[0]} exited {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(proc.stdout), elapsed


def _oracle(raw: bytes) -> dict:
    require(len(raw) > 0 and len(raw) % 8 == 0, "unaligned Titchy corpus input")
    n = len(raw) // 8
    start = max(0, n // 2 - 4)
    count = min(n - start, 9)
    points = [0, n // 2, n - 1]
    bits = [0, (n // 2) * 64 + 31, n * 64 - 1]
    return {"point_indices": points, "bit_indices": bits, "range_start": start, "range_count": count,
            "points": [struct.unpack_from('<Q', raw, i * 8)[0] for i in points],
            "bits": [(raw[(i // 64) * 8 + 7 - (i % 64) // 8] >> (7 - i % 8)) & 1 for i in bits],
            "range": list(struct.unpack_from(f'<{count}Q', raw, start * 8))}


def validate_access(mode: str, raw: bytes, wire: bytes, restored: bytes, encoded: dict, observed: dict) -> dict:
    n = len(raw) // 8
    require(restored == raw and encoded["rows"] == observed["restore"]["rows"] == n and
            encoded["entry"] == "titchy_c_encode" and observed["restore"]["entry"] == "titchy_c_decode",
            "Titchy detached recovery differs from original f64 bits")
    header = TCHY.unpack_from(wire)
    require(encoded["bytes"] == len(wire) and header[:9] ==
            (b'TCHY', 2, 64, 4, 0, 1000, 250000, (1 << 64) - 1, n),
            "Titchy native artifact accounting, configuration or count differs")
    index_bytes = header[-1] * INDEX.size
    require(TCHY.size + index_bytes <= len(wire), "Titchy native index exceeds backing")
    expected = _oracle(raw)
    require(all(observed[k] == expected[k] for k in ("range_start", "range_count")), "Titchy range extent differs")
    if mode == "batch-range":
        require(observed["entry"] == "titchy_c_range" and observed["whole_container_validated"] is True and
                observed["range"] == expected["range"] and observed["requested_bytes"] is None,
                "Titchy stateless range or counter scope differs")
    else:
        require(mode == "loaded-file-access" and all(observed[k] == expected[k] for k in ("point_indices", "bit_indices")),
                "Titchy reader request indices differ")
        for armed in ("callback", "file"):
            query = observed[f"{armed}_queries"]
            require(all(query[k] == expected[k] for k in ("points", "bits", "range")),
                    f"Titchy {armed} responses differ from original f64 bits")
            points, bits = query["point_observations"], query["bit_observations"]
            require(len(points) == len(bits) == 3, "Titchy point and bit observations omitted")
            ops = [observed[f"{armed}_open"], *points, *bits, query["range_observation"]]
            if armed == "callback":
                require(ops[0]["requested_bytes"] == TCHY.size + index_bytes and
                        all(o["calls"] > 0 and o["requested_bytes"] > 0 for o in ops),
                        "Titchy callback open or query accounting differs")
            else:
                require(all(o["requested_bytes"] is None for o in ops), "Titchy file I/O was not instrumented")
    return {"artifact_bytes": len(wire), "header_bytes": TCHY.size, "index_bytes": index_bytes,
            "dictionary_and_payload_bytes": len(wire) - TCHY.size - index_bytes}


def run_titchy_access(root: Path, plan: dict, item: dict, staged: dict, work: Path, run: Path) -> dict:
    binding = plan["build"]["titchy_access"]
    control = local_file(root, binding["executable"]["path"])
    mode = item["route"]
    extent = item["input"]
    require(extent["full_extent_of_file_rows_and_value_columns"] and extent["slice_extent"]["max_per_unit"] == CHUNK_ROWS,
            "Titchy access requires the locked full-column extent")
    detached = work / "detached"
    detached.mkdir()
    raw_file, frame, restored = work / "input.u64", detached / "frame.tchy", detached / "restored.u64"
    units = []
    sample = None
    for column, path in enumerate(staged["paths"]):
        first = 0
        with path.open("rb") as stream:
            while raw := stream.read(8 * CHUNK_ROWS):
                raw_file.write_bytes(raw)
                n = len(raw) // 8
                encoded, encode_process_wall = invoke(control, work, "encode", raw_file.name, str(frame))
                raw_file.unlink()
                observed, access_process_wall = invoke(control, detached, mode, frame.name, str(n), restored.name)
                wire = frame.read_bytes()
                billing = validate_access(mode, raw, wire, restored.read_bytes(), encoded, observed)
                unit = {"column": column, "row_range": [first, first + n], "logical_input_bytes": len(raw), **billing,
                        "sha256": hashlib.sha256(wire).hexdigest(), "encode": encoded, "access": observed,
                        "process_wall_ns": {"encode": encode_process_wall, "access_and_validation": access_process_wall}}
                units.append(unit)
                if sample is None:
                    # Cross-check a retained wire product with the pure Python decoder, not the native query path.
                    independent, _ = decode_tchy(wire, 64, n, WIRE_POLICY)
                    require(independent == raw, "independent TCHY decoder disagrees with retained source bits")
                    shutil.copyfile(frame, work / "sample.tchy")
                    sample = {"column": column, "row_range": unit["row_range"], "sha256": unit["sha256"],
                              "bytes": billing["artifact_bytes"], "restored_sha256": hashlib.sha256(raw).hexdigest()}
                frame.unlink()
                restored.unlink()
                first += n
        require(first == staged["rows"], "Titchy access did not consume all planned rows")
    estimate = extent["size_estimate"]
    total = sum(u["logical_input_bytes"] for u in units)
    require(sample is not None and total == estimate["native_input_bytes_one_pass"] and
            len(units) == estimate["input_units"], "Titchy access did not consume its planned input extent")
    relative = Path("retained") / item["work_item_id"] / "sample.tchy"
    (run / relative).parent.mkdir(parents=True)
    shutil.copyfile(work / "sample.tchy", run / relative)
    return {"driver": "titchy-access-control/1", "columns": len(staged["paths"]), "input_bytes": total,
            "artifact_bytes": sum(u["artifact_bytes"] for u in units), "units": units,
            "retained_sample": {**sample, "path": relative.as_posix()},
            "read_counter_scope": "memory_callback_requested_bytes_not_file_io" if mode == "loaded-file-access" else None,
            "independent_recovery": "detached_native_process_each_and_python_wire_sample",
            "timing_admitted": False}
