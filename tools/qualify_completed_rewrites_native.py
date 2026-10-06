"""Run current standalone tests and framework C ABI tests in both build profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from build_completed_rewrite import KINDS

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--algorithms", nargs="+", choices=KINDS, default=list(KINDS))
    args = parser.parse_args()
    results = []
    for name in args.algorithms:
        for profile in ("release", "sanitizer"):
            folder = ROOT / "build/adapters" / name.replace("-", "_") / profile
            build_record = json.loads((folder / "build-record.json").read_text())
            assert sha(ROOT / build_record["artifact"]) == build_record["artifact_sha256"]
            assert (
                sha(ROOT / "adapters/completed_rewrites/tests/qualification.cpp")
                == build_record["qualification_source_sha256"]
            )
            for entry in build_record["binding_sources"]:
                assert sha(ROOT / entry["path"]) == entry["sha256"]
            command = ["ctest", "--test-dir", str(folder / "cmake"), "--output-on-failure"]
            environment = dict(
                os.environ,
                ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
            )
            try:
                process = subprocess.run(command, env=environment, capture_output=True, timeout=900)
                output = process.stdout + process.stderr
                code = process.returncode
            except subprocess.TimeoutExpired as error:
                output = (error.stdout or b"") + (error.stderr or b"") + b"\nQUALIFICATION_TIMEOUT"
                code = 124
            log = folder / "qualification.log"
            log.write_bytes(output)
            record = {
                "algorithm": name,
                "profile": profile,
                "status": "PASS" if code == 0 else "FAIL",
                "exit_code": code,
                "command": command,
                "log": str(log.relative_to(ROOT)),
                "log_sha256": sha(log),
                "build_record_sha256": sha(folder / "build-record.json"),
                "artifact_sha256": build_record["artifact_sha256"],
                "qualification_source_sha256": build_record["qualification_source_sha256"],
                "scope": build_record["sanitizer_scope"],
            }
            (folder / "qualification.json").write_text(json.dumps(record, indent=2) + "\n")
            destination = ROOT / "docs/completed_rewrites" / f"{name}-native-{profile}.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(record, indent=2) + "\n")
            results.append(record)
            print(name, profile, record["status"], flush=True)
            if code:
                print(output.decode(errors="replace")[-3000:], flush=True)
    raise SystemExit(any(r["status"] != "PASS" for r in results))


if __name__ == "__main__":
    main()
