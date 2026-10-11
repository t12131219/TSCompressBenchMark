"""Verify the native scalar patch series against the retained upstream checkout.

This proves source-to-vendor provenance only. It does not execute a codec, prove
upstream equivalence, or grant standalone/Benchmark qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "2d804ff492e45222e841dc1a50904476fa64f4a0"
PRE_HASHES = {
    "include/NeaTS.hpp": "ac298426389b6e4ebd9c390d1709d87ad84924badf392d21667c5919a4489556",
    "include/LeaTS.hpp": "9fe6bc00453c64f6b7bd935f2137dd7af69c40ede37db314ecd831a369f0ae45",
}
PATCH_NAMES = (
    "0001-gcc11-scalar-compatibility.patch",
    "0002-leats-serialization.patch",
    "0003-leats-predictor-precision.patch",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{command!r}: {result.stdout}{result.stderr}")
    return result.stdout.strip()


def audit(upstream: Path) -> dict[str, object]:
    vendor = ROOT / "adapters/neats/vendor/neats"
    patches = ROOT / "adapters/neats/patches"
    if run(["git", "rev-parse", "HEAD"], upstream) != COMMIT:
        raise ValueError("retained upstream checkout is not the frozen revision")
    if run(["git", "status", "--porcelain"], upstream):
        raise ValueError("retained upstream checkout has local changes")
    for relative, expected in PRE_HASHES.items():
        if sha(upstream / relative) != expected:
            raise ValueError(f"frozen upstream header drift: {relative}")
    files = sorted(path for path in vendor.rglob("*") if path.is_file())
    if len(files) != 172 or any(path.is_symlink() for path in files):
        raise ValueError("unexpected vendor closure or symbolic link")
    mapping = {"README.upstream.md": "README.md", "neats_lossless.cpp": "benchmark/neats_lossless.cpp"}
    steps: list[dict[str, object]] = []
    closure: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="tscb-neats-replay-") as temporary:
        replay = Path(temporary)
        for path in files:
            relative = path.relative_to(vendor).as_posix()
            origin = upstream / mapping.get(relative, relative)
            destination = replay / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, destination)
            closure.append({
                "path": relative,
                "upstream_relative_path": mapping.get(relative, relative),
                "upstream_sha256": sha(origin),
                "vendor_sha256": sha(path),
            })
        for name in PATCH_NAMES:
            patch = patches / name
            before = {relative: sha(replay / relative) for relative in PRE_HASHES}
            run(["git", "apply", "--check", str(patch)], replay)
            run(["git", "apply", str(patch)], replay)
            steps.append({
                "path": str(patch.relative_to(ROOT)),
                "sha256": sha(patch),
                "pre_sha256": before,
                "post_sha256": {relative: sha(replay / relative) for relative in PRE_HASHES},
                "apply_check": "PASS",
            })
        digest = hashlib.sha256()
        for record in closure:
            relative = record["path"]
            restored = replay / relative
            if restored.read_bytes() != (vendor / relative).read_bytes():
                raise ValueError(f"patch replay differs from compiled vendor: {relative}")
            record["replayed_sha256"] = sha(restored)
            record["status"] = "BYTE_IDENTICAL"
            digest.update(relative.encode() + b"\0" + restored.read_bytes())
    return {
        "schema_version": "tscb.neats-native-patch-replay.v1",
        "status": "PASS_SOURCE_PLUS_PATCH_EQUALS_CURRENT_VENDOR",
        "evidence_kind": "CURRENT_PATCH_REPLAY_AND_CONTENT_VERIFICATION",
        "upstream_revision": COMMIT,
        "upstream_path": str(upstream),
        "upstream_clean": True,
        "vendor_path": str(vendor.relative_to(ROOT)),
        "patch_application_location": "TEMPORARY_REPLAY_TREE_ONLY",
        "compiled_vendor_policy": "ALREADY_PATCHED_NATIVE_SCALAR_VARIANT",
        "hash_protocol": "RELATIVE_PATH_NUL_FILE_BYTES_V1",
        "replayed_vendor_sha256": digest.hexdigest(),
        "file_count": len(closure),
        "patches": steps,
        "files": closure,
        "claims": {
            "patch_replay": True,
            "source_codec_execution": False,
            "unmodified_upstream_byte_equivalence": False,
            "standalone_full_parity": False,
            "benchmark_qualification": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT.parent / "Compression_Source_Code/Source_Code/_repos/and-gue_NeaTS")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = audit(arguments.upstream.resolve())
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload)
    print(json.dumps({key: result[key] for key in ("status", "file_count", "replayed_vendor_sha256", "claims")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
