"""Source-only legacy C ABI probe in a new directory, never current admission.

Current library admission uses verify_general_native_builds.py and independent
fresh source evidence. This probe compiles a separate executable from sources.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-directory", type=Path, required=True)
args = parser.parse_args()
output = args.output_directory.resolve()
output.mkdir(parents=True, exist_ok=False)
lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
results = []
for name, entry in lock["algorithms"].items():
    out = output / name
    out.mkdir(parents=True, exist_ok=False)
    vendor = ROOT / "adapters/rewrite_lossless/vendor" / entry["package"]
    exe = out / "qualification"
    cmd = [
        "clang++",
        "-std=c++17",
        "-O1",
        "-g",
        "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer",
        "-no-pie",
        "-fno-fast-math",
        "-ffp-contract=off",
        "-pthread",
        f"-DTSCB_REWRITE_KIND={entry['kind']}",
        f'-DTSCB_REWRITE_KEY="{name}"',
        "-I",
        str(ROOT / "native/include"),
        "-I",
        str(vendor / "include"),
        str(ROOT / "adapters/rewrite_lossless/tests/qualification.cc"),
        str(ROOT / "adapters/rewrite_lossless/native/tscb_rewrite_lossless.cc"),
        *[str(vendor / p) for p in entry["translation_units"]],
        "-o",
        str(exe),
    ]
    r = {"algorithm": name, "commands": []}
    try:
        for label, command in [("compile", cmd), ("run", [str(exe)])]:
            env = dict(
                os.environ,
                ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
            )
            start = time.monotonic()
            proc = subprocess.run(command, capture_output=True, env=env, timeout=300)
            log = out / (label + ".log")
            log.write_bytes(proc.stdout + proc.stderr)
            r["commands"].append(
                {
                    "command": command,
                    "exit_code": proc.returncode,
                    "seconds": time.monotonic() - start,
                    "log": str(log),
                    "log_sha256": sha(log),
                }
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="replace")[-2000:])
        r.update(status="PASS", binary_sha256=sha(exe))
    except Exception as error:
        r.update(status="FAIL", error=str(error))
    print(name, r["status"], r.get("error", ""), flush=True)
    results.append(r)
report = {
    "status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
    "cases": results,
    "frozen_lock_sha256": sha(ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json"),
    "driver_sha256": sha(Path(__file__)),
    "scope": "SEPARATELY_COMPILED_SOURCE_ONLY_ABI_PROBE_NOT_CURRENT_REGISTERED_LIBRARY",
    "current_registered_library_admission": "NOT_GRANTED",
    "source_language_parity": "NOT_GRANTED",
    "historical_evidence_rewritten": False,
    "security_scope": (
        "ASan/UBSan; no leak-clean claim; detect_leaks=0 under ptrace-limited sandbox"
    ),
}
with (output / "report.json").open("x", encoding="utf-8") as stream:
    json.dump(report, stream, indent=2)
    stream.write("\n")
raise SystemExit(report["status"] != "PASS")
