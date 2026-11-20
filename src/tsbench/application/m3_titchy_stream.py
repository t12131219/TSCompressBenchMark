"""Native packet stream over the whole planned V column (development preflight)."""
from pathlib import Path
import shutil

from ..assets import digest, local_file, require
from ..qualification.titchy_wire import TSC1, TSTR, TSTR_RECORD, decode_tstr
from .m3_titchy_access import invoke

POLICY = {"chunk": 4, "split": 1000, "endian": 0, "threshold_ppm": 250000}
SPEC = {"chunks_per_packet": 7, "max_active_bytes": 72}


def validate_stream(n: int, wire: bytes, config: bytes, encode: dict, decode: dict) -> dict:
    chunk, target = POLICY["chunk"], SPEC["chunks_per_packet"]
    chunks = (n + chunk - 1) // chunk
    padding = chunks * chunk - n
    require(config == TSC1.pack(b"TSC1", 64, chunk, POLICY["split"], POLICY["endian"], target,
                               POLICY["threshold_ppm"] / 1_000_000, SPEC["max_active_bytes"]),
            "Titchy stream config differs from the frozen policy")
    require(n > 0 and len(wire) >= TSTR.size, "missing Titchy stream extent")
    magic, width, ch, split, rows, packets = TSTR.unpack_from(wire)
    require((magic, width, ch, split, rows) == (b"TSTR\1", 64, chunk, POLICY["split"], n) and
            0 < packets <= chunks, "Titchy stream archive header differs")
    (enc_n, enc_packets, enc_chunks, enc_payload, first_push, first_ns, finish, wall, capacity, enc_reset) = (
        encode.get(k) for k in ("logical_samples", "packets", "chunks", "payload_bytes", "first_packet_after_push",
                                "first_packet_ns", "packets_emitted_on_finish", "wall_ns", "backpressure_replay_checks",
                                "reset_replay_bit_exact"))
    require(all(type(x) is int for x in (enc_n, enc_packets, enc_chunks, enc_payload, first_push, first_ns, finish,
                                        wall, capacity, decode.get("wall_ns"))) and
            (enc_n, enc_packets, enc_chunks) == (n, packets, chunks) and
            (decode.get("logical_samples"), decode.get("packets"), decode.get("padding_samples")) == (n, packets, padding)
            and enc_reset is True and decode.get("reset_replay_bit_exact") is True and
            decode.get("decoder_capacity_retry_verified") is True and decode["wall_ns"] > 0 and
            0 <= finish <= packets and (finish > 0 or padding == 0) and 0 < first_ns <= wall,
            "Titchy stream counters or replay controls differ")
    before_finish = packets - finish
    expected_first_push = min(n, chunk * target)
    require(first_push == expected_first_push and bool(before_finish) == (n >= chunk * target) and
            capacity == (3 if before_finish else 0), "Titchy first-packet or backpressure boundary differs")
    pos = TSTR.size
    chunk_sum = finish_chunks = payload = 0
    for index in range(packets):
        require(len(wire) - pos >= TSTR_RECORD.size, "truncated Titchy stream packet header")
        extent, length = TSTR_RECORD.unpack_from(wire, pos)
        pos += TSTR_RECORD.size
        require(1 <= extent <= target and 0 < length <= len(wire) - pos, "invalid Titchy stream packet extent")
        chunk_sum += extent
        finish_chunks += extent if index >= before_finish else 0
        payload += length
        pos += length
    require(pos == len(wire) and (chunk_sum, payload) == (chunks, enc_payload), "Titchy stream accounting differs")
    return {"artifact_bytes": len(wire) + len(config), "payload_bytes": payload, "config_bytes": len(config),
            "archive_framing_bytes": TSTR.size + packets * TSTR_RECORD.size, "packets_before_finish": before_finish,
            "first_packet_phase": "push" if before_finish else "finish", "finish_chunks": finish_chunks,
            "finish_logical_samples": finish_chunks * chunk - padding, "padding_samples": padding}


def run_titchy_stream(root: Path, plan: dict, item: dict, staged: dict, work: Path, run: Path) -> dict:
    control = local_file(root, plan["build"]["titchy_stream"]["executable"]["path"])
    extent = item["input"]
    paths, rows = staged["paths"], staged["rows"]
    require(extent["full_extent_of_file_rows_and_value_columns"] and extent["slice_extent"]["max_per_unit"] is None and
            extent["value_column_range"] == [0, len(paths)] and len(extent["row_ranges"]) == 1 and
            (extent["row_ranges"][0]["start"], extent["row_ranges"][0]["end"]) == (0, rows),
            "Titchy stream requires one unbroken session per complete V column")
    detached = work / "detached"
    detached.mkdir()
    frame, config, restored = detached / "archive.tstr", detached / "policy.tsc1", detached / "restored.u64"
    sample = None
    units = []
    for column, source in enumerate(paths):
        require(source.stat().st_size == rows * 8, "Titchy stream input does not span all planned rows")
        encoded, encode_ns = invoke(control, work, "encode", str(source), str(frame), str(config))
        decoded, decode_ns = invoke(control, detached, "decode", frame.name, config.name, restored.name)
        raw, wire, conf = source.read_bytes(), frame.read_bytes(), config.read_bytes()
        require(raw == restored.read_bytes(), "Titchy detached stream decode changed source f64 bits")
        billing = validate_stream(rows, wire, conf, encoded, decoded)
        unit = {"column": column, "row_range": [0, rows], "logical_input_bytes": len(raw), **billing,
                "archive_sha256": digest(frame), "config_sha256": digest(config), "restored_sha256": digest(restored),
                "encode": encoded, "decode": decoded, "process_wall_ns": {"encode": encode_ns, "decode": decode_ns}}
        units.append(unit)
        if not column:
            independent, packets = decode_tstr(wire, conf, {**SPEC, "count": rows}, POLICY)
            require(independent == raw and len(packets) == encoded["packets"], "independent TSTR decoder differs")
            shutil.copyfile(frame, work / frame.name)
            shutil.copyfile(config, work / config.name)
            sample = {"column": column, "row_range": unit["row_range"], "restored_sha256": unit["restored_sha256"],
                      "parts": {}}
        for path in (frame, config, restored):
            path.unlink()
    total = sum(u["logical_input_bytes"] for u in units)
    estimate = extent["size_estimate"]
    require(sample is not None and (total, len(units)) == (estimate["native_input_bytes_one_pass"],
                                                            estimate["input_units"]), "Titchy stream input extent differs")
    relative = Path("retained") / item["work_item_id"]
    (run / relative).mkdir(parents=True)
    for path in (work / frame.name, work / config.name):
        dst = relative / path.name
        shutil.copyfile(path, run / dst)
        sample["parts"][path.suffix[1:]] = {"path": dst.as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}
    return {"driver": "titchy-stream-control/1", "columns": len(units), "input_bytes": total,
            "artifact_bytes": sum(u["artifact_bytes"] for u in units), "units": units, "retained_sample": sample,
            "independent_recovery": "detached_native_process_each_and_python_wire_sample",
            "clock_scope": "diagnostic_in_memory_push_pop_finish_and_archive_decode_excluding_replays_and_file_io",
            "timing_admitted": False}
