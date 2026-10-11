"""Bind the selected ELF runtime to an explicitly admitted execution profile.

This checks DT_NEEDED resolution and the process's actual mapped ELF objects.
It is not a static-link closure, arbitrary dlopen trace, or full N1 attestation.
"""

from __future__ import annotations

import ctypes
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class RuntimeEvidenceError(RuntimeError):
    """The effective dynamic loader selection is not admitted."""


def _digest(path: Path) -> str:
    if not path.is_file():
        raise RuntimeEvidenceError(f"runtime dependency missing: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _safe_project_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise RuntimeEvidenceError("invalid runtime profile path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeEvidenceError("unsafe runtime profile path")
    path = root / path
    if not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeEvidenceError("runtime profile escapes project")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise RuntimeEvidenceError(f"invalid runtime evidence: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeEvidenceError(f"invalid runtime evidence object: {path}")
    return value


def _reject_interposition() -> None:
    for name in ("LD_PRELOAD", "LD_AUDIT"):
        if os.environ.get(name, "").strip():
            raise RuntimeEvidenceError(f"unregistered runtime interposition: {name}")
    global_preload = Path("/etc/ld.so.preload")
    if global_preload.exists():
        try:
            values = [
                line.split("#", 1)[0].strip() for line in global_preload.read_text().splitlines()
            ]
        except OSError as error:
            raise RuntimeEvidenceError("cannot inspect /etc/ld.so.preload") from error
        if any(values):
            raise RuntimeEvidenceError("unregistered runtime interposition: /etc/ld.so.preload")


def _program(name: str) -> Path:
    path = shutil.which(name)
    if not path:
        raise RuntimeEvidenceError(f"runtime resolver unavailable: {name}")
    return Path(path).resolve()


def _run(program: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            [str(program), *args], check=True, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeEvidenceError(f"runtime resolver failed: {program}") from error
    return result.stdout


@functools.lru_cache(maxsize=1024)
def _cached_elf_info(
    path: str, stamp: tuple[int, int, int, int], program: str
) -> tuple[str, tuple[str, ...]]:
    del stamp
    output = _run(Path(program), ["-d", path])
    soname = re.findall(r"\(SONAME\).*?\[(.*?)\]", output)
    needed = tuple(re.findall(r"\(NEEDED\).*?\[(.*?)\]", output))
    return (soname[0] if soname else Path(path).name), needed


def _elf_info(path: Path) -> tuple[str, tuple[str, ...]]:
    path = path.resolve()
    info = path.stat()
    return _cached_elf_info(
        str(path),
        (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
        str(_program("readelf")),
    )


def _entry(path: Path) -> dict[str, str]:
    path = path.resolve()
    return {"path": str(path), "sha256": _digest(path), "soname": _elf_info(path)[0]}


def _standalone(artifact: Path) -> list[dict[str, str]]:
    output = _run(_program("ldd"), [str(artifact.resolve())])
    if "not found" in output:
        raise RuntimeEvidenceError("runtime dependency cannot be resolved")
    paths = {
        Path(match).resolve()
        for match in re.findall(r"(?m)^\s*(?:\S+\s+=>\s+)?(/.+?)\s+\(", output)
    }
    return [_entry(path) for path in sorted(paths)]


def _mapped_objects() -> dict[str, set[Path]]:
    try:
        lines = Path("/proc/self/maps").read_text().splitlines()
    except OSError as error:
        raise RuntimeEvidenceError("actual ELF maps unavailable") from error
    paths: set[Path] = set()
    for line in lines:
        fields = line.split(maxsplit=5)
        if len(fields) != 6 or not fields[5].startswith("/"):
            continue
        if fields[5].endswith(" (deleted)"):
            raise RuntimeEvidenceError("deleted mapped runtime cannot be verified")
        path = Path(fields[5]).resolve()
        try:
            with path.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    paths.add(path)
        except OSError as error:
            raise RuntimeEvidenceError(f"mapped runtime unavailable: {path}") from error
    by_soname: dict[str, set[Path]] = {}
    for path in paths:
        by_soname.setdefault(_elf_info(path)[0], set()).add(path)
    return by_soname


def _effective(
    artifact: Path, standalone: list[dict[str, str]], *, loaded: bool
) -> list[dict[str, str]]:
    mappings = _mapped_objects()
    choices = {entry["soname"]: Path(entry["path"]) for entry in standalone}
    if len(choices) != len(standalone):
        raise RuntimeEvidenceError("ambiguous standalone runtime SONAME")
    queue = list(_elf_info(artifact)[1])
    selected: dict[Path, dict[str, str]] = {}
    while queue:
        name = queue.pop()
        if "/" in name:
            candidate = Path(name).resolve()
            soname = _elf_info(candidate)[0]
            matches = mappings.get(soname, set())
            if matches and matches != {candidate}:
                raise RuntimeEvidenceError(f"unregistered absolute runtime replacement: {name}")
        else:
            matches = mappings.get(name, set())
            if len(matches) > 1:
                raise RuntimeEvidenceError(f"ambiguous mapped runtime SONAME: {name}")
            candidate = next(iter(matches)) if matches else choices.get(name)
            if candidate is None:
                raise RuntimeEvidenceError(f"runtime dependency not resolved: {name}")
        if loaded and candidate not in mappings.get(_elf_info(candidate)[0], set()):
            raise RuntimeEvidenceError(f"expected runtime is not actually mapped: {candidate}")
        if candidate in selected:
            continue
        selected[candidate] = _entry(candidate)
        _, dependencies = _elf_info(candidate)
        # A replacement already loaded by Python can have additional needed
        # libraries. Resolve those against its own ldd plus the actual maps.
        unresolved = [
            dep
            for dep in dependencies
            if "/" not in dep and dep not in choices and dep not in mappings
        ]
        if unresolved:
            for entry in _standalone(candidate):
                choices.setdefault(entry["soname"], Path(entry["path"]))
        queue.extend(dependencies)
    if loaded:
        mapped_paths = set().union(*mappings.values()) if mappings else set()
        if artifact.resolve() not in mapped_paths:
            raise RuntimeEvidenceError("native artifact is not actually mapped")
    return [selected[path] for path in sorted(selected)]


def capture_runtime_profile(root: Path, artifact: Path, *, capture_driver: Path) -> dict[str, Any]:
    """Capture in a fresh production Python process, then observe actual load."""
    _reject_interposition()
    record_path = artifact.parent / "build-record.json"
    record = _read_json(record_path)
    if _digest(artifact) != record.get("artifact_sha256"):
        raise RuntimeEvidenceError("runtime capture artifact drift")
    if _safe_project_path(root, record.get("artifact")).resolve() != artifact.resolve():
        raise RuntimeEvidenceError("runtime capture build artifact identity differs")
    standalone = _standalone(artifact)
    library = ctypes.CDLL(str(artifact.resolve()))
    effective = _effective(artifact, standalone, loaded=True)
    del library
    return {
        "schema_version": "tscb.runtime-profile.v1",
        "scope": "ARTIFACT_TRANSITIVE_DT_NEEDED_ACTUAL_PROCESS_ELF_MAPS",
        "qualification": "ACTUAL_CDLL_LOAD_ONLY_NOT_FULL_N1_OR_CODEC_PARITY",
        "artifact": {"path": str(artifact.relative_to(root)), "sha256": _digest(artifact)},
        "build_record": {
            "path": str(record_path.relative_to(root)),
            "sha256": _digest(record_path),
        },
        "build_linkage_declared": record.get("runtime_dependencies", []),
        "standalone_resolution": standalone,
        "effective_loaded_resolution": effective,
        "resolver_programs": [
            {"role": name, "path": str(_program(name)), "sha256": _digest(_program(name))}
            for name in ("ldd", "readelf")
        ],
        "capture_driver": {
            "path": str(capture_driver.relative_to(root)),
            "sha256": _digest(capture_driver),
        },
        "loader_environment": {
            name: os.environ.get(name) for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT")
        },
    }


def verified_runtime_dependencies(
    root: Path, artifact: Path, adapter: dict[str, Any], *, loaded: bool = False
) -> tuple[Path, ...]:
    record_path = artifact.parent / "build-record.json"
    record = _read_json(record_path)
    registration = adapter.get("runtime_profile")
    declared = record.get("runtime_dependencies", [])
    if registration is None and not declared:
        return ()
    _reject_interposition()
    profile: dict[str, Any] | None = None
    profile_path: Path | None = None
    driver_path: Path | None = None
    if registration is not None:
        if not isinstance(registration, dict):
            raise RuntimeEvidenceError("invalid runtime profile registration")
        profile_path = _safe_project_path(root, registration.get("path"))
        if _digest(profile_path) != registration.get("sha256"):
            raise RuntimeEvidenceError("runtime profile drift")
        profile = _read_json(profile_path)
        if profile.get("schema_version") != "tscb.runtime-profile.v1":
            raise RuntimeEvidenceError("unsupported runtime profile schema")
        programs = profile.get("resolver_programs", [])
        expected_programs = [
            {"role": name, "path": str(_program(name)), "sha256": _digest(_program(name))}
            for name in ("ldd", "readelf")
        ]
        if programs != expected_programs:
            raise RuntimeEvidenceError("unregistered runtime resolver program")
        driver = profile.get("capture_driver", {})
        driver_path = _safe_project_path(root, driver.get("path"))
        if _digest(driver_path) != driver.get("sha256"):
            raise RuntimeEvidenceError("runtime capture driver drift")
    standalone = _standalone(artifact)
    effective = _effective(artifact, standalone, loaded=loaded)
    paths: list[Path] = []
    if registration is None:
        # Legacy/no-profile evidence may admit only the recorded actual files;
        # a saved executable/test dependency union is not an exact DSO closure.
        admitted = {
            str(
                (
                    Path(entry["path"])
                    if Path(entry["path"]).is_absolute()
                    else root / entry["path"]
                ).resolve()
            ): entry["sha256"]
            for entry in declared
        }
        if any(admitted.get(entry["path"]) != entry["sha256"] for entry in standalone + effective):
            raise RuntimeEvidenceError("unregistered runtime resolver or mapped SONAME replacement")
    else:
        assert profile is not None and profile_path is not None and driver_path is not None
        expected_artifact = {"path": str(artifact.relative_to(root)), "sha256": _digest(artifact)}
        expected_record = {
            "path": str(record_path.relative_to(root)),
            "sha256": _digest(record_path),
        }
        if (
            profile.get("artifact") != expected_artifact
            or profile.get("build_record") != expected_record
        ):
            raise RuntimeEvidenceError("runtime profile artifact/build identity differs")
        if profile.get("build_linkage_declared") != declared:
            raise RuntimeEvidenceError("runtime profile build linkage differs")
        if profile.get("standalone_resolution") != standalone:
            raise RuntimeEvidenceError("unregistered runtime resolver selection")
        if profile.get("effective_loaded_resolution") != effective:
            raise RuntimeEvidenceError("unregistered mapped runtime SONAME selection")
        paths += [profile_path, driver_path, *(_program(name) for name in ("ldd", "readelf"))]
    paths += [Path(entry["path"]) for entry in standalone + effective]
    return tuple(dict.fromkeys(paths))


def verify_loaded_runtime(root: Path, artifact: Path, adapter: dict[str, Any]) -> None:
    verified_runtime_dependencies(root, artifact, adapter, loaded=True)


def load_verified_runtime(
    root: Path, artifact: Path, adapter: dict[str, Any]
) -> ctypes.CDLL | None:
    """Load and observe before a lazy adapter can create its first session."""
    record = _read_json(artifact.parent / "build-record.json")
    if not record.get("runtime_dependencies") and not adapter.get("runtime_profile"):
        return None
    verified_runtime_dependencies(root, artifact, adapter)
    try:
        library = ctypes.CDLL(str(artifact.resolve()))
    except OSError as error:
        raise RuntimeEvidenceError(f"native loader failed: {artifact}") from error
    verify_loaded_runtime(root, artifact, adapter)
    return library
