"""Real f64 corpus driver for the two distinct native pcodec page routes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from ..assets import ContractError, digest, local_file, require

CHUNK_ROWS = 65536
PAGE_ROWS = 4096


def _invoke(command: list[str], cwd: Path) -> tuple[dict, int]:
    env = {k: v for k, v in os.environ.items() if k not in {"LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT"}}
    start = time.monotonic_ns()
    proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    elapsed = time.monotonic_ns() - start
    if proc.returncode:
        raise ContractError(f"pcodec {command[1]} {command[2]} exited {proc.returncode}: {proc.stderr.strip()}")
    return json.loads(proc.stdout), elapsed


def _verify_chunk(raw: bytes, restored: bytes, frame_bytes: int, encode: dict, decode: dict) -> None:
    rows = len(raw) // 8
    pages = (rows + PAGE_ROWS - 1) // PAGE_ROWS
    require(restored == raw and encode["rows"] == decode["rows"] == rows,
            "pcodec detached recovery differs from f64 input bits")
    require(encode["pages"] == decode["pages"] == pages and
            decode["read_calls"] == (rows + 255) // 256 and decode["request_values"] == 257 and
            decode["unaligned_request_status"] == 1 and decode["effective_read_capacity"] == 256,
            "pcodec native page/drain geometry differs")
    require(encode["container_bytes"] == 16 + 8 * pages and
            encode["meta_bytes"] > 0 and encode["payload_bytes"] >= 0 and
            0 <= encode["zero_payload_pages"] == decode["zero_payload_pages"] <= pages and
            (encode["payload_bytes"] == 0) == (encode["zero_payload_pages"] == pages) and
            frame_bytes == encode["meta_bytes"] + encode["payload_bytes"] + encode["container_bytes"],
            "pcodec page artifact byte accounting differs")


def run_pcodec_pages(root: Path, plan: dict, item: dict, staged: dict, work: Path, run: Path) -> dict:
    binding = plan["build"]["pcodec_pages"]
    control = str(local_file(root, binding["executable"]["path"]))
    lane = {"source-pages": "source", "native-pages": "native"}[item["route"]]
    require(item["input"]["full_extent_of_file_rows_and_value_columns"] and
            item["input"]["slice_extent"]["max_per_unit"] == CHUNK_ROWS,
            "pcodec pages require the locked full-column extent")
    sealed = work / "detached"
    sealed.mkdir()
    raw_path, frame, out = work / "chunk.f64", sealed / "chunk.pm3page", sealed / "restored.f64"
    units = []
    samples = None
    for column, path in enumerate(staged["paths"]):
        start = 0
        with path.open("rb") as stream:
            while raw := stream.read(CHUNK_ROWS * 8):
                require(len(raw) % 8 == 0, "unaligned pcodec corpus input")
                raw_path.write_bytes(raw)
                encoded, encode_wall = _invoke([control, "corpus-encode", lane, str(raw_path), str(frame)], work)
                raw_path.unlink()
                decoded, decode_wall = _invoke([control, "corpus-decode", lane, frame.name, out.name], sealed)
                size = frame.stat().st_size
                _verify_chunk(raw, out.read_bytes(), size, encoded, decoded)
                end = start + len(raw) // 8
                units.append({"column": column, "row_range": [start, end], "input_bytes": len(raw),
                              "artifact_bytes": size, "artifact_sha256": digest(frame),
                              "encode": encoded, "decode": decoded,
                              "process_wall_ns": {"encode": encode_wall, "decode": decode_wall}})
                if samples is None:
                    sample = work / "sample.pm3page"
                    shutil.copyfile(frame, sample)
                    samples = {"column": column, "row_range": [start, end], "sha256": units[-1]["artifact_sha256"], "bytes": size}
                out.unlink()
                frame.unlink()
                start = end
        require(start == staged["rows"], "pcodec page route did not consume all planned rows")
    input_bytes = sum(u["input_bytes"] for u in units)
    require(samples is not None and len(units) == item["input"]["size_estimate"]["input_units"] and
            input_bytes == item["input"]["size_estimate"]["native_input_bytes_one_pass"],
            "pcodec page route did not consume its planned input extent")
    relative = Path("retained") / item["work_item_id"] / "sample.pm3page"
    (run / relative).parent.mkdir(parents=True)
    shutil.copyfile(work / "sample.pm3page", run / relative)
    return {"driver": "pcodec-pages-control/1", "lane": lane, "columns": len(staged["paths"]),
            "input_bytes": input_bytes, "artifact_bytes": sum(u["artifact_bytes"] for u in units),
            "units": units, "independent_recovery": "detached_process_pm3page_only",
            "retained_sample": {**samples, "path": relative.as_posix()},
            "timing_scope": "single_native_page_group_with_buffer_copies_excludes_file_io",
            "timing_admitted": False}
