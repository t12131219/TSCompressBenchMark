"""Real non-codec ELF counterexamples for loader selection and SONAME reuse."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
CHILD = """
import ctypes, hashlib, json, os, sys
from pathlib import Path
from tscompbench.adapters.build_evidence import verified_build_dependencies
from tscompbench.adapters.runtime_evidence import (
    capture_runtime_profile, verified_runtime_dependencies,
)
root, mode = Path(sys.argv[1]), sys.argv[2]
artifact = root / "artifacts/release/libtoy_wrapper.so"
adapter = {"factory": "TOY_NATIVE_CTYPES_V1"}
profile = root / "runtime-profile.json"
if mode == "capture":
    captured = capture_runtime_profile(root, artifact, capture_driver=root / "child.py")
    profile.write_text(json.dumps(captured))
    print(json.dumps({"status":"CAPTURE_PASS"}))
    sys.exit()
if mode != "legacy":
    adapter["runtime_profile"] = {
        "path": "runtime-profile.json",
        "sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
    }
if mode == "lazy-factory":
    from types import SimpleNamespace
    from tscompbench.adapters.factory import create_adapter, _ADMITTED_RUNTIME_HANDLES
    adapter["factory"] = "LZ4_FRAME_CTYPES_V1"
    adapter["artifact_path"] = str(artifact.relative_to(root))
    manifest = SimpleNamespace(key="toy-native", document={
        "identity":{"family":"TOY"}, "adapter":adapter,
    })
    result = create_adapter(root, manifest)
    print(json.dumps({"status":"PASS", "admitted_handle":artifact.resolve() in
        _ADMITTED_RUNTIME_HANDLES, "lazy_adapter_path":str(result.library_path)}))
    sys.exit()
if mode == "preloaded":
    other = ctypes.CDLL(str(root / "alternative/renamed-not-soname.bin"))
if mode in {"preload", "audit"}:
    variable = "LD_PRELOAD" if mode == "preload" else "LD_AUDIT"
    os.environ[variable] = str(root / "alternative/renamed-not-soname.bin")
if mode == "resolver":
    os.environ["PATH"] = str(root / "fake-tools") + os.pathsep + os.environ["PATH"]
try:
    paths = verified_build_dependencies(root, artifact, "toy-native", adapter)
    library = ctypes.CDLL(str(artifact))
    library.toy_entry.restype = ctypes.c_int
    if mode == "post-conflict":
        other = ctypes.CDLL(str(root / "alternative/renamed-not-soname.bin"))
    verified_runtime_dependencies(root, artifact, adapter, loaded=True)
    print(json.dumps({"status":"PASS", "value": library.toy_entry(),
        "paths": [str(path) for path in paths]}))
except Exception as error:
    print(json.dumps({"status":"REJECTED", "error": str(error)}))
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def toy(tmp_path):
    if (
        shutil.which("cc") is None
        or shutil.which("readelf") is None
        or not Path("/proc/self/maps").exists()
    ):
        pytest.skip("real ELF test requires compiler, readelf and Linux process maps")
    for name in ("good", "alternative", "artifacts/release", "fake-tools"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "good.c").write_text("int toy_runtime_value(void) { return 11; }\n")
    (tmp_path / "alternative.c").write_text("int toy_runtime_value(void) { return 22; }\n")
    (tmp_path / "wrapper.c").write_text(
        "extern int toy_runtime_value(void); int toy_entry(void) { return toy_runtime_value(); }\n"
    )
    good = tmp_path / "good/libtoy_runtime.so"
    alternative = tmp_path / "alternative/libtoy_runtime.so"
    artifact = tmp_path / "artifacts/release/libtoy_wrapper.so"
    commands = [
        [
            "cc",
            "-shared",
            "-fPIC",
            "-Wl,-soname,libtoy_runtime.so",
            str(tmp_path / "good.c"),
            "-o",
            str(good),
        ],
        [
            "cc",
            "-shared",
            "-fPIC",
            "-Wl,-soname,libtoy_runtime.so",
            str(tmp_path / "alternative.c"),
            "-o",
            str(alternative),
        ],
        [
            "cc",
            "-shared",
            "-fPIC",
            str(tmp_path / "wrapper.c"),
            "-L",
            str(good.parent),
            "-ltoy_runtime",
            "-Wl,-rpath," + str(good.parent),
            "-o",
            str(artifact),
        ],
    ]
    for command in commands:
        subprocess.run(command, check=True, capture_output=True)
    shutil.copyfile(alternative, alternative.parent / "renamed-not-soname.bin")
    command = {
        "schema_version": "tscb.compile-command.v1",
        "profile": "release",
        "command": commands[-1],
    }
    (artifact.parent / "compile-command.json").write_text(json.dumps(command))
    (artifact.parent / "build-record.json").write_text(
        json.dumps(
            {
                "schema_version": "tscb.build-artifact.v1",
                "algorithm": "toy-native",
                "profile": "release",
                "artifact": str(artifact.relative_to(tmp_path)),
                "artifact_sha256": digest(artifact),
                "compile_commands_sha256": hashlib.sha256(
                    canonical_json_bytes(command)
                ).hexdigest(),
                "runtime_dependencies": [
                    {"path": str(good.relative_to(tmp_path)), "sha256": digest(good)}
                ],
            }
        )
    )
    (tmp_path / "child.py").write_text(CHILD)
    directory = tmp_path / "src/tscompbench/adapters"
    directory.parent.mkdir(parents=True)
    shutil.copytree(
        ROOT / "src/tscompbench/adapters",
        directory,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    fake = tmp_path / "fake-tools/ldd"
    fake.write_text("#!/bin/sh\ntouch " + str(tmp_path / "unregistered-resolver-executed") + "\n")
    fake.chmod(0o755)

    def run(mode, *, alternative_selected=False):
        environment = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "LD_LIBRARY_PATH": str(tmp_path / ("alternative" if alternative_selected else "good")),
        }
        environment.pop("LD_PRELOAD", None)
        environment.pop("LD_AUDIT", None)
        result = subprocess.run(
            [sys.executable, str(tmp_path / "child.py"), str(tmp_path), mode],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        return json.loads(result.stdout)

    assert run("capture")["status"] == "CAPTURE_PASS"
    return tmp_path, run


def test_pinned_profile_replays_actual_load_and_binds_runtime_files(toy):
    root, run = toy
    result = run("verify")
    assert result["status"] == "PASS"
    assert result["value"] == 11
    assert str(root / "runtime-profile.json") in result["paths"]
    assert str(root / "good/libtoy_runtime.so") in result["paths"]


def test_factory_admits_and_retains_real_load_before_lazy_session(toy):
    _, run = toy
    result = run("lazy-factory")
    assert result["status"] == "PASS"
    assert result["admitted_handle"] is True


@pytest.mark.parametrize("profile", ["legacy", "verify"])
def test_unchanged_record_cannot_admit_ld_library_path_alternative(toy, profile):
    root, run = toy
    watched = [
        root / "artifacts/release/libtoy_wrapper.so",
        root / "artifacts/release/build-record.json",
        root / "good/libtoy_runtime.so",
    ]
    before = [digest(path) for path in watched]
    result = run(profile, alternative_selected=True)
    assert result["status"] == "REJECTED"
    assert "unregistered runtime resolver" in result["error"]
    assert before == [digest(path) for path in watched]


@pytest.mark.parametrize("mode", ["preloaded", "post-conflict", "preload", "audit", "resolver"])
def test_actual_same_soname_or_interposition_is_rejected(toy, mode):
    root, run = toy
    result = run(mode)
    assert result["status"] == "REJECTED"
    assert "unregistered" in result["error"] or "ambiguous mapped runtime SONAME" in result["error"]
    assert not (root / "unregistered-resolver-executed").exists()


def test_profile_drift_is_rejected(toy):
    root, run = toy
    profile = root / "runtime-profile.json"
    document = json.loads(profile.read_text())
    document["effective_loaded_resolution"][0]["sha256"] = "0" * 64
    profile.write_text(json.dumps(document))
    result = run("verify")
    assert result["status"] == "REJECTED"
    assert "unregistered mapped runtime" in result["error"]
