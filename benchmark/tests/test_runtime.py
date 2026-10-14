"""Loader evidence comes from fresh processes, without native codec execution."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tsbench.config import resolve
from tsbench.records import read_jsonl
from tsbench.runtime import worker_environment


def _config(preload):
    return {
        "schema": "tsbench.experiment/1",
        "name": "runtime-contract",
        "datasets": [{"id": "values", "path": "values.npy", "format": "npy"}],
        "methods": [{"id": "raw", "codec": "raw-store"}],
        "profiles": [{"id": "single", "runtime_preload": preload}],
    }


@pytest.mark.parametrize("kind", ["relative", "missing", "directory", "space", "tab", "newline", "colon"])
def test_config_and_worker_reject_ambiguous_or_unavailable_preload_paths(tmp_path, monkeypatch, kind):
    # Separator cases exist on disk, so rejection cannot pass only due to absence.
    filenames = {
        "relative": "relative.so",
        "space": "space library.so",
        "tab": "tab\tlibrary.so",
        "newline": "newline\nlibrary.so",
        "colon": "colon:library.so",
    }
    monkeypatch.chdir(tmp_path)
    if kind == "missing":
        value = str(tmp_path / "absent.so")
    elif kind == "directory":
        value = str(tmp_path)
    else:
        path = tmp_path / filenames[kind]
        path.write_bytes(b"path-validation fixture; never loaded")
        value = path.name if kind == "relative" else str(path)
    base = {"LD_PRELOAD": "inherited.so", "UNCHANGED": "yes"}
    original_base = base.copy()
    with pytest.raises(ValueError, match="runtime_preload"):
        worker_environment(base, {"runtime_preload": [value]})
    assert base == original_base
    source = _config([value])
    original_source = copy.deepcopy(source)
    with pytest.raises(ValueError, match="runtime_preload"):
        resolve(source, tmp_path)
    assert source == original_source


@pytest.mark.parametrize("preload", ["/absolute/library.so", None, ("/absolute/library.so",), [1], [True]])
def test_config_requires_an_array_of_string_preload_paths(tmp_path, preload):
    with pytest.raises(ValueError, match="runtime_preload"):
        resolve(_config(preload), tmp_path)


@pytest.fixture
def system_libstdcpp():
    if not sys.platform.startswith("linux") or not Path("/proc/self/maps").is_file():
        pytest.skip("runtime mapping evidence requires Linux procfs")
    candidates = [
        Path("/usr/lib/x86_64-linux-gnu/libstdc++.so.6"),
        Path("/lib/x86_64-linux-gnu/libstdc++.so.6"),
        Path("/usr/lib64/libstdc++.so.6"),
        Path("/usr/lib/libstdc++.so.6"),
        Path("/lib64/libstdc++.so.6"),
        Path("/lib/libstdc++.so.6"),
        *sorted(Path("/usr/lib").glob("*/libstdc++.so.6")),
    ]
    for library in candidates:
        if library.is_file():
            return library
    pytest.skip("no installed system libstdc++.so.6")


@pytest.fixture
def system_libz():
    if not sys.platform.startswith("linux") or not Path("/proc/self/maps").is_file():
        pytest.skip("runtime mapping evidence requires Linux procfs")
    candidates = [
        Path("/usr/lib/x86_64-linux-gnu/libz.so.1"),
        Path("/lib/x86_64-linux-gnu/libz.so.1"),
        Path("/usr/lib64/libz.so.1"),
        Path("/usr/lib/libz.so.1"),
        Path("/lib64/libz.so.1"),
        Path("/lib/libz.so.1"),
        *sorted(Path("/usr/lib").glob("*/libz.so.1")),
    ]
    for library in candidates:
        if library.is_file():
            return library
    pytest.skip("no installed system libz.so.1")


def test_profile_prepends_preload_preserves_inherited_loader_syntax_and_base(system_libstdcpp, tmp_path):
    requested = [str(system_libstdcpp)]
    inherited = "libinherited.so:libother.so"
    base = {"LD_PRELOAD": inherited, "LD_LIBRARY_PATH": "/inherited/search", "UNCHANGED": "yes"}
    original = base.copy()
    profile = {"runtime_preload": requested.copy()}
    environment = worker_environment(base, profile)
    assert environment is not base
    assert environment["LD_PRELOAD"] == str(system_libstdcpp) + " " + inherited
    assert environment["LD_LIBRARY_PATH"] == base["LD_LIBRARY_PATH"]
    assert environment["UNCHANGED"] == "yes"
    assert base == original
    assert profile["runtime_preload"] == requested
    resolved = resolve(_config(requested), tmp_path)
    assert resolved["profiles"][0]["runtime_preload"] == requested


@pytest.mark.parametrize("profile", [{}, {"runtime_preload": []}])
def test_empty_preload_request_preserves_inherited_environment_without_mutation(profile):
    base = {"LD_PRELOAD": "existing.so:other.so", "UNCHANGED": "yes"}
    result = worker_environment(base, profile)
    assert result == base
    assert result is not base
    result["UNCHANGED"] = "child-only"
    assert base["UNCHANGED"] == "yes"


def _child_base_environment():
    environment = os.environ.copy()
    environment.pop("LD_PRELOAD", None)
    source = str(Path(__file__).resolve().parents[1] / "src")
    inherited_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source + (os.pathsep + inherited_pythonpath if inherited_pythonpath else "")
    return environment


def _assert_system_runtime(evidence, library_path):
    canonical = library_path.resolve(strict=True)
    assert evidence["implemented"] is True
    assert evidence["mechanism"] == "/proc/self/maps"
    matching = [library for library in evidence["libraries"] if library["path"] == str(canonical)]
    assert len(matching) == 1
    assert matching[0]["sha256"] == "sha256:" + hashlib.sha256(canonical.read_bytes()).hexdigest()


def test_fresh_loader_process_reports_canonical_mapped_system_library_and_hash(tmp_path, system_libstdcpp):
    # An alias tests canonical identity rather than just echoing LD_PRELOAD.
    alias = tmp_path / "libstdc++.so.6"
    alias.symlink_to(system_libstdcpp.resolve(strict=True))
    environment = worker_environment(_child_base_environment(), {"runtime_preload": [str(alias)]})
    code = """
import json, os
from pathlib import Path
from tsbench.runtime import loaded_runtime
runtime = loaded_runtime()
print(json.dumps({"pid": os.getpid(), "runtime": runtime,
                  "proc_maps": Path("/proc/self/maps").read_text()}))
"""
    completed = subprocess.run([sys.executable, "-c", code], env=environment,
                               capture_output=True, text=True, check=True, timeout=15)
    result = json.loads(completed.stdout)
    assert result["pid"] != os.getpid()
    assert result["runtime"]["ld_preload"] == str(alias)
    _assert_system_runtime(result["runtime"], system_libstdcpp)
    mapped_paths = {
        Path(fields[5]).resolve()
        for line in result["proc_maps"].splitlines()
        if len(fields := line.split(maxsplit=5)) == 6 and fields[5].startswith("/")
    }
    assert system_libstdcpp.resolve(strict=True) in mapped_paths
    assert alias != system_libstdcpp.resolve(strict=True)


def test_fresh_loader_process_accepts_an_arbitrary_alias_for_system_libz(tmp_path, system_libz):
    alias = tmp_path / "arbitrary-preload-name.so"
    canonical = system_libz.resolve(strict=True)
    alias.symlink_to(canonical)
    environment = worker_environment(_child_base_environment(), {"runtime_preload": [str(alias)]})
    code = """
import json, os
from pathlib import Path
from tsbench.runtime import loaded_runtime
print(json.dumps({"pid": os.getpid(), "runtime": loaded_runtime(),
                  "proc_maps": Path("/proc/self/maps").read_text()}))
"""
    completed = subprocess.run([sys.executable, "-c", code], env=environment,
                               capture_output=True, text=True, check=True, timeout=15)
    result = json.loads(completed.stdout)
    assert result["pid"] != os.getpid()
    assert result["runtime"]["ld_preload"] == str(alias)
    assert alias.name.split(".so")[0] != canonical.name.split(".so")[0]
    _assert_system_runtime(result["runtime"], system_libz)
    mapped_paths = {
        Path(fields[5]).resolve()
        for line in result["proc_maps"].splitlines()
        if len(fields := line.split(maxsplit=5)) == 6 and fields[5].startswith("/")
    }
    assert canonical in mapped_paths


def test_environment_string_without_a_real_mapping_is_not_runtime_evidence(tmp_path, system_libstdcpp):
    unmapped = tmp_path / "unmapped-runtime.so"
    unmapped.write_bytes(b"not a library; never passed to the loader")
    code = """
import json, os, sys
from tsbench.runtime import loaded_runtime
os.environ["LD_PRELOAD"] = sys.argv[1]
try:
    loaded_runtime()
except RuntimeError as error:
    print(json.dumps({"type": type(error).__name__, "reason": str(error)}))
else:
    raise SystemExit("an environment-only preload declaration was accepted")
"""
    completed = subprocess.run([sys.executable, "-c", code, str(unmapped)],
                               env=_child_base_environment(), capture_output=True,
                               text=True, check=True, timeout=15)
    error = json.loads(completed.stdout)
    assert error["type"] == "RuntimeError"
    assert "not mapped" in error["reason"]
    assert str(unmapped) in error["reason"]


def _raw_run_config(tmp_path, preload):
    import numpy as np

    np.save(tmp_path / "values.npy", np.array([0.0, 1.0, 2.5], dtype="<f8"))
    source = _config(preload)
    source.update({"asset_root": str(Path(__file__).resolve().parents[2]),
                   "build_root": str(tmp_path / "cache"), "output": str(tmp_path / "run"),
                   "execution": {"sessions": 1, "rounds": 1, "warmup_objects": 0,
                                 "timeout_s": 30, "qualification_cache": False}})
    return resolve(source, tmp_path)


def test_raw_runner_and_independent_decoder_record_the_real_preloaded_runtime(tmp_path, monkeypatch, system_libstdcpp):
    from tsbench.runner import run

    monkeypatch.delenv("LD_PRELOAD", raising=False)
    result = run(_raw_run_config(tmp_path, [str(system_libstdcpp)]))
    manifest = json.loads((result / "manifest.json").read_bytes())
    assert len(manifest["cases"]) == 1
    case = manifest["cases"][0]
    assert case["status"] == "ready", case
    effective = case["effective_profile"]
    assert effective["requested_runtime_preload"] == [str(system_libstdcpp)]
    assert effective["runtime"]["ld_preload"] == str(system_libstdcpp)
    _assert_system_runtime(effective["runtime"], system_libstdcpp)
    observations, tail = read_jsonl(result / "observations.jsonl")
    assert tail is None
    exact = [row for row in observations if row.get("phase") == "qualification"
             and row.get("event") == "terminal" and row.get("qualification_kind") == "exact"]
    assert len(exact) == 1
    assert exact[0]["status"] == "ok", exact[0]
    assert exact[0]["cache_hit"] is False
    recovery = exact[0]["independent_recovery"]
    assert recovery["passed"] is True and recovery["decoder_process"] is True
    assert recovery["decoder_returncode"] == 0
    assert recovery["decoder_runtime"]["ld_preload"] == str(system_libstdcpp)
    _assert_system_runtime(recovery["decoder_runtime"], system_libstdcpp)
    primary = [row for row in observations if row.get("phase") == "measurement"
               and row.get("event") == "terminal"]
    assert len(primary) == 1 and primary[0]["status"] == "ok"


def test_completed_run_resume_rejects_retargeted_preload_alias_without_changing_observations(
        tmp_path, monkeypatch, system_libstdcpp, system_libz):
    from tsbench.runner import run

    monkeypatch.delenv("LD_PRELOAD", raising=False)
    original_target = system_libstdcpp.resolve(strict=True)
    original_hash = hashlib.sha256(original_target.read_bytes()).hexdigest()
    alias = tmp_path / "selected-runtime.so"
    alias.symlink_to(original_target)
    configuration = _raw_run_config(tmp_path, [str(alias)])
    result = run(configuration)
    manifest = json.loads((result / "manifest.json").read_bytes())
    assert manifest["state"] == "complete"
    assert manifest["cases"][0]["status"] == "ready"
    _assert_system_runtime(manifest["cases"][0]["effective_profile"]["runtime"], system_libstdcpp)
    observations = result / "observations.jsonl"
    before = observations.read_bytes()
    rows, tail = read_jsonl(observations)
    assert tail is None
    primary = [row for row in rows if row.get("phase") == "measurement"
               and row.get("event") == "terminal"]
    assert len(primary) == 1 and primary[0]["status"] == "ok"
    alias.unlink()
    alias.symlink_to(system_libz.resolve(strict=True))
    assert alias.resolve(strict=True) != original_target
    assert original_target.is_file()
    assert hashlib.sha256(original_target.read_bytes()).hexdigest() == original_hash
    with pytest.raises(ValueError, match="implementation changed"):
        run(configuration, result, resume=True)
    assert observations.read_bytes() == before
