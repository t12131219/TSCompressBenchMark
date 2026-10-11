"""Read-only checks of the build evidence actually declared by an adapter.

Legacy records do not all contain a compiler dependency closure. Verifying
their declared hashes must not be reported as proof of an undeclared closure.
Nothing in this module builds an artifact or refreshes a recorded digest.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Any

from tscompbench.ids import canonical_json_bytes

from .runtime_evidence import RuntimeEvidenceError, verified_runtime_dependencies


class BuildEvidenceError(RuntimeError):
    """A consumed build dependency is missing, unsafe, or changed."""


def project_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise BuildEvidenceError("unsafe project dependency path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise BuildEvidenceError(f"unsafe project dependency path: {value}")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise BuildEvidenceError(f"project dependency escapes checkout: {value}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BuildEvidenceError(f"execution dependency missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise BuildEvidenceError(f"invalid build evidence: {path}") from error
    if not isinstance(value, dict):
        raise BuildEvidenceError(f"invalid build evidence object: {path}")
    return value


def _verify(path: Path, expected: Any) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise BuildEvidenceError(f"invalid dependency digest: {path}")
    if not path.is_file():
        raise BuildEvidenceError(f"execution dependency missing: {path}")
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise BuildEvidenceError(f"execution dependency drift: {path}")


def _entries(root: Path, values: Any, *, external: bool = False) -> list[Path]:
    if not isinstance(values, list):
        raise BuildEvidenceError("invalid dependency list")
    paths = []
    for entry in values:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise BuildEvidenceError("invalid dependency entry")
        value = entry["path"]
        raw_path = Path(value)
        if raw_path.is_absolute() and external:
            if "\0" in value or ".." in raw_path.parts:
                raise BuildEvidenceError(f"unsafe external dependency path: {value}")
            path = raw_path
        else:
            path = project_path(root, value)
        _verify(path, entry.get("sha256"))
        paths.append(path)
    return paths


def _legacy_dependencies(
    root: Path, artifact: Path, key: str, command: dict[str, Any]
) -> list[Path]:
    """Resolve the anonymous hash fields of existing build recipe schemas.

    The correspondence is the file order used by tools/build_codec.py. Hash
    validation of a patch does not assert that it is applicable or equivalent.
    """
    mappings: dict[str, list[Path]] = {}
    directory = artifact.parent
    if key in {"alp", "alp-rd"}:
        base = root / "adapters/alp"
        mappings = {
            "patch_sha256": [
                base / "patches" / name
                for name in (
                    "0001-float-factor-array-bound.patch",
                    "0002-decoder-multiply-domain.patch",
                    "0003-encoded-integer-range.patch",
                )
            ],
            "patched_encoder_sha256": [directory / "alp/include/alp/encoder.hpp"],
            "source_encoder_sha256": [base / "vendor/alp/include/alp/encoder.hpp"],
        }
    elif key in {"serf-qt", "serf-xor"}:
        mappings = {
            "patch_sha256": [
                root / "adapters/serf/patches" / name
                for name in (
                    "0001-defined-bit-operations.patch",
                    "0002-prefix-mask-bounds.patch",
                    "0003-input-bit-stream-guard.patch",
                )
            ],
            "patched_translation_unit_sha256": [
                directory / "serf/src/utils" / name
                for name in (
                    "double.h",
                    "float.h",
                    "zig_zag_codec.h",
                    "output_bit_stream.cc",
                    "input_bit_stream.cc",
                    "serf_utils_32.cc",
                    "serf_utils_64.cc",
                )
            ],
        }
    elif key in {"neats-lossless-i64", "leats-lossless-i64"}:
        mappings["patch_sha256"] = [
            root / "adapters/neats/patches" / name
            for name in (
                "0001-gcc11-scalar-compatibility.patch",
                "0002-leats-serialization.patch",
                "0003-leats-predictor-precision.patch",
            )
        ]
    elif key.startswith("sprintz-"):
        patch_names = ["0001-lowdim-byte-safety.patch"]
        names = ["sprintz_delta_lowdim.cpp", "sprintz_xff_lowdim.cpp"]
        if not key.endswith("-u8"):
            patch_names.append("0002-generic-allocation-safety.patch")
            names = [
                "sprintz.cpp",
                *names,
                "sprintz_delta_rle.cpp",
                "sprintz_xff_rle.cpp",
                "format.cpp",
            ]
        if key == "sprintz-fire-huff0":
            patch_names.append("0003-fire-prediction-overflow.patch")
        mappings = {
            "patch_sha256": [root / "adapters/sprintz/patches" / name for name in patch_names],
            "patched_translation_unit_sha256": [directory / "sprintz" / name for name in names],
        }
    elif key in {"lzsse2-raw", "lzsse8-raw"}:
        name = "lzsse2" if key == "lzsse2-raw" else "lzsse8"
        base = root / "adapters" / (name + "_raw")
        mappings = {
            "patch_sha256": [base / "patches/0001-allocation-unaligned-pointer-safety.patch"],
            "patched_translation_unit_sha256": [directory / (name + ".cpp")],
            "source_translation_unit_sha256": [base / "vendor/lzsse" / name / (name + ".cpp")],
        }
    elif key == "lzss-dipperstein-c":
        base = root / "adapters/lzss_dipperstein"
        mappings = {
            "patch_sha256": [base / "patches/0001-binary-tree-sentinel-bounds.patch"],
            "patched_tree_sha256": [directory / "tree.c"],
            "source_tree_sha256": [base / "vendor/lzss/tree.c"],
            "unmodified_source_sha256": [
                base / "vendor/lzss" / name
                for name in (
                    "lzss.c",
                    "tree.c",
                    "bitfile/bitfile.c",
                )
            ],
        }
    elif key == "xz-stream":
        mappings["dependency_archive_sha256"] = [directory / "vendor-build/liblzma.a"]
        if "dependency_compile_commands" in command:
            path = directory / "vendor-build/compile_commands.json"
            if not path.is_file():
                raise BuildEvidenceError(f"execution dependency missing: {path}")
            try:
                saved = json.loads(path.read_text())
            except (OSError, UnicodeError, ValueError) as error:
                raise BuildEvidenceError(f"invalid build evidence: {path}") from error
            if saved != command["dependency_compile_commands"]:
                raise BuildEvidenceError(f"execution dependency drift: {path}")
            mappings["_compile_commands"] = [path]
    paths = []
    for field, files in mappings.items():
        if field == "_compile_commands":
            paths += files
            continue
        if field not in command:
            continue
        expected = command[field]
        expected = expected if isinstance(expected, list) else [expected]
        if len(files) != len(expected):
            raise BuildEvidenceError(f"invalid {field} dependency count: {key}")
        for path, digest in zip(files, expected, strict=True):
            safe_path = project_path(root, str(path.relative_to(root)))
            _verify(safe_path, digest)
            paths.append(safe_path)
    return paths


def verified_build_dependencies(
    root: Path,
    artifact: Path,
    key: str,
    adapter: dict[str, Any],
    *,
    verify_runtime_selection: bool = True,
) -> tuple[Path, ...]:
    """Verify existing record/lock schemas and return their consumed files."""
    record_path = artifact.parent / "build-record.json"
    record = _read_json(record_path)
    if record.get("schema_version") != "tscb.build-artifact.v1":
        raise BuildEvidenceError("unsupported build evidence schema")
    expected_algorithm = "simdcomp-source-u32" if key == "simdcomp-u32" else key
    if record.get("algorithm") != expected_algorithm:
        raise BuildEvidenceError(f"build algorithm identity differs: {key}")
    if record.get("profile") != artifact.parent.name:
        raise BuildEvidenceError(f"build profile identity differs: {key}")
    if record.get("status", "PASS") != "PASS":
        raise BuildEvidenceError(f"completed build evidence missing: {key}")
    if project_path(root, record.get("artifact")).resolve() != artifact.resolve():
        raise BuildEvidenceError(f"build artifact identity differs: {key}")
    _verify(artifact, record.get("artifact_sha256"))
    paths = [record_path]
    for field in (
        "source_files",
        "binding_sources",
        "objects",
        "patches",
        "generated_source_files",
        "runtime_dependencies",
        "pinned_native_dependencies",
        "compiled_source_closure",
        "compiler_dependency_files",
        "toolchain_files",
        "toolchain_programs",
        "runtime_dependency_listing",
        "build_driver_files",
    ):
        if field in record:
            paths += _entries(
                root,
                record[field],
                external=field
                in {
                    "runtime_dependencies",
                    "pinned_native_dependencies",
                    "compiled_source_closure",
                    "toolchain_files",
                    "toolchain_programs",
                },
            )
    if "license" in record and isinstance(record["license"], dict):
        paths += _entries(root, record["license"].get("files", []))
    models = adapter.get("models", {})
    if not isinstance(models, dict):
        raise BuildEvidenceError("invalid model dependency map")
    paths += _entries(root, list(models.values()))
    if "python_source_closure" in adapter:
        paths += _entries(root, adapter["python_source_closure"])

    factory = adapter.get("factory")
    command_path = artifact.parent / "compile-command.json"
    command: dict[str, Any] | None = None
    if factory == "COMPLETED_REWRITE_CTYPES_V1":
        compile_commands = artifact.parent / "cmake/compile_commands.json"
        _verify(compile_commands, record.get("compile_commands_sha256"))
        paths.append(compile_commands)
    elif command_path.is_file():
        command = _read_json(command_path)
        if (
            command.get("schema_version") != "tscb.compile-command.v1"
            or command.get("profile") != record["profile"]
            or hashlib.sha256(canonical_json_bytes(command)).hexdigest()
            != record.get("compile_commands_sha256")
        ):
            raise BuildEvidenceError(f"compile command drift: {command_path}")
        paths.append(command_path)
        # source_artifact_dependencies is a list of logical source keys in
        # existing Sprintz commands, not a list of filesystem hash entries.
        for field in ("source_closure", "compiled_source_closure"):
            if field in command:
                paths += _entries(root, command[field], external=field == "compiled_source_closure")
        if "license" in command and isinstance(command["license"], dict):
            paths += _entries(root, command["license"].get("files", []))
        paths += _legacy_dependencies(root, artifact, key, command)
    elif factory == "SIMDCOMP_CTYPES_V1" or factory == "REWRITE_LOSSLESS_CTYPES_V1":
        raise BuildEvidenceError(f"compile command missing: {command_path}")
    else:
        # Older one-command builds saved only shlex.join(command). Reconstruct
        # that recorded JSON projection; never execute its shell text.
        display = record.get("command_display")
        if not isinstance(display, str):
            raise BuildEvidenceError(f"compile command missing: {command_path}")
        try:
            argv = shlex.split(display)
        except ValueError as error:
            raise BuildEvidenceError("invalid recorded compile command") from error
        projection = {
            "schema_version": "tscb.compile-command.v1",
            "profile": record["profile"],
            "command": argv,
        }
        if hashlib.sha256(canonical_json_bytes(projection)).hexdigest() != record.get(
            "compile_commands_sha256"
        ):
            raise BuildEvidenceError(f"compile command missing or drift: {key}")

    if factory == "COMPLETED_REWRITE_CTYPES_V1":
        lock_path = project_path(root, "adapters/completed_rewrites/FROZEN_SOURCES.json")
        _verify(lock_path, record.get("frozen_sources_sha256"))
        lock = _read_json(lock_path)
        package = lock.get("packages", {}).get(key)
        if not isinstance(package, dict):
            raise BuildEvidenceError(f"frozen package missing: {key}")
        paths += [lock_path, *_entries(root, package.get("files"))]
        for field, relative in (
            (
                "build_recipe_sha256",
                str((artifact.parent / "recipe/CMakeLists.txt").relative_to(root)),
            ),
            ("build_driver_sha256", "tools/build_completed_rewrite.py"),
            ("qualification_source_sha256", "adapters/completed_rewrites/tests/qualification.cpp"),
        ):
            path = project_path(root, relative)
            _verify(path, record.get(field))
            paths.append(path)
    elif factory == "REWRITE_LOSSLESS_CTYPES_V1":
        lock_path = project_path(root, "adapters/rewrite_lossless/FROZEN_APIS.json")
        assert command is not None
        _verify(lock_path, command.get("frozen_api_lock_sha256"))
        lock = _read_json(lock_path)
        package = lock.get("algorithms", {}).get(key)
        if not isinstance(package, dict):
            raise BuildEvidenceError(f"frozen package missing: {key}")
        paths += [lock_path, *_entries(root, package.get("files"))]
    if verify_runtime_selection:
        try:
            paths += verified_runtime_dependencies(root, artifact, adapter)
        except RuntimeEvidenceError as error:
            raise BuildEvidenceError(str(error)) from error
    return tuple(dict.fromkeys(paths))
