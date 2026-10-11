"""Read stored original bitstreams and replay current standalone C++ CLIs.

Does not overwrite historical evidence, adapters, registries or implementations.
Java cross-decode is validated from stored bytes only; no fresh Java run is claimed.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent / "lossless_replay.json"
NAMES = ["chimp", "elf", "elf-plus", "elf-star", "self-star"]
TARGETS = {"chimp": "chimp", "elf": "elf_vldb", "elf-plus": "elf_plus", "elf-star": "elf_star", "self-star": "self_star"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, target):
    result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == 0, (command, result.returncode, result.stderr.decode(errors="replace"))
    assert target.exists(), target
    return result.stdout


def main():
    results = []
    for name in NAMES:
        package = ROOT / "Compression_Rewrite/ReWrite" / name
        diff_path = package / "validation/differential/report.json"
        diff = json.loads(diff_path.read_text())
        current = json.loads((package / "validation/current/report.json").read_text())
        cli = ROOT / "build/rewrite_review" / name / "release" / (TARGETS[name] + "_cli")
        row = {"package": name, "cli": str(cli.relative_to(ROOT)), "cli_sha256": sha(cli), "cases": [], "source_hash_mismatches": []}
        assert sha(cli) == diff["cli_sha256"] == current["artifacts"][cli.name]
        assert sha(diff_path) == current["differential_report_sha256"]
        for kind, record in [("current", current.get("source_files", {})), ("differential", diff.get("source_files", {}))]:
            for relative, digest in record.items():
                actual = sha(package / relative)
                if actual != digest:
                    row["source_hash_mismatches"].append({"report": kind, "path": relative, "recorded": digest, "actual": actual})
        with tempfile.TemporaryDirectory(prefix=f"lossless-{name}-audit-", dir="/tmp") as tmp:
            scratch = Path(tmp)
            for index, case in enumerate(diff["cases"]):
                evidence = {"name": case["name"], "width": case["width"], "variant": case.get("variant"), "historical_status": case["status"]}
                try:
                    if case["status"] != "PASS":
                        evidence["replay_status"] = "OUTSIDE_LOSSLESS_DOMAIN"
                        row["cases"].append(evidence)
                        continue
                    if name == "self-star":
                        inp = package / case["input"]
                        directory = inp.parent
                        source = directory / "source.bin"
                        native = directory / "native.bin"
                        frame = directory / "frame.bin"
                        recorded_java = directory / "source-from-native.bin"
                        encode_mode = ["encode" + str(case["width"])]
                        decode_mode = ["decode" + str(case["width"])]
                        pack_mode = ["pack" + str(case["width"])]
                        unpack_mode = ["unpack"]
                    else:
                        commands = [entry["command"] for entry in case["commands"]]
                        native_encode = next(cmd for cmd in commands if "encode-raw" in cmd)
                        native_decode = next(cmd for cmd in commands if "decode-raw" in cmd)
                        inp = Path(native_encode[-2])
                        native = Path(native_encode[-1])
                        directory = native.parent
                        source = directory / ("source.bin.trimmed" if name in {"elf", "elf-plus"} else "source.bin")
                        frame = directory / "frame.bin"
                        recorded_java = directory / "cross.bin"
                        encode_mode = native_encode[1:-2]
                        decode_mode = native_decode[1:-2]
                        pack_mode = ["encode", str(case["width"])] + ([str(case["variant"])] if name == "chimp" else [])
                        unpack_mode = ["decode", str(case["width"])] + ([str(case["variant"])] if name == "chimp" else [])
                    assert sha(inp) == case["input_sha256"], "stored input hash"
                    assert sha(native) == case["raw_sha256"], "stored raw hash"
                    assert sha(frame) == case["frame_sha256"], "stored frame hash"
                    assert frame.stat().st_size * 8 == case["final_bits"], "FinalBits"
                    assert source.read_bytes() == native.read_bytes(), "stored original/native raw mismatch"
                    assert recorded_java.read_bytes() == inp.read_bytes(), "stored Java cross-decode mismatch"
                    fresh_raw, fresh_decoded = scratch / f"{index}.raw", scratch / f"{index}.decoded"
                    fresh_frame, fresh_unpacked = scratch / f"{index}.frame", scratch / f"{index}.unpacked"
                    run([cli, *encode_mode, inp, fresh_raw], fresh_raw)
                    assert fresh_raw.read_bytes() == source.read_bytes(), "current C++ encoding differs from original bitstream"
                    run([cli, *decode_mode, source, fresh_decoded], fresh_decoded)
                    assert fresh_decoded.read_bytes() == inp.read_bytes(), "current C++ decoding original differs"
                    run([cli, *pack_mode, inp, fresh_frame], fresh_frame)
                    assert fresh_frame.read_bytes() == frame.read_bytes(), "current checked frame differs"
                    run([cli, *unpack_mode, fresh_frame, fresh_unpacked], fresh_unpacked)
                    assert fresh_unpacked.read_bytes() == inp.read_bytes(), "current checked frame roundtrip differs"
                    evidence.update(replay_status="PASS", input_sha256=sha(inp), raw_sha256=sha(source), frame_sha256=sha(frame))
                except Exception as error:
                    evidence.update(replay_status="FAIL", error=str(error))
                row["cases"].append(evidence)
        row["passed"] = sum(c["replay_status"] == "PASS" for c in row["cases"])
        row["failed"] = sum(c["replay_status"] == "FAIL" for c in row["cases"])
        results.append(row)
        print(name, row["passed"], "passed", row["failed"], "failed", flush=True)
    report = {"status": "PASS" if not any(r["failed"] for r in results) else "FAIL", "scope": "Current C++ CLI replay of stored original bitstreams; historical Java cross-decode output byte-checked, no fresh Java oracle claimed", "driver_sha256": sha(Path(__file__)), "packages": results}
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
