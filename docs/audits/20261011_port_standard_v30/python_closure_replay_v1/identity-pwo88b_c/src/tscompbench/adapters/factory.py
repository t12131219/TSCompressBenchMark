from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tscompbench.codecs import CodecManifest
from tscompbench.execution.protocol import CodecAdapter
from tscompbench.ids import canonical_json_bytes

from .alp import AlpAdapter
from .brotli_stream import BrotliStreamAdapter
from .build_evidence import BuildEvidenceError, project_path, verified_build_dependencies
from .bzip2_stream import Bzip2StreamAdapter
from .completed_rewrites import CompletedRewriteAdapter
from .deflate_zlib import DeflateZlibAdapter
from .entropy_fse import EntropyAdapter
from .lz4_frame import Lz4FrameAdapter
from .lzss_dipperstein import LzssDippersteinAdapter
from .lzss_raw import LzssRawAdapter
from .lzsse2_raw import Lzsse2RawAdapter
from .lzsse8_raw import Lzsse8RawAdapter
from .neats import NeatsAdapter
from .oracles import OracleAdapter
from .rewrite_lossless import RewriteLosslessAdapter
from .runtime_evidence import RuntimeEvidenceError, load_verified_runtime
from .serf import SerfAdapter
from .simdcomp import SIMDCompAdapter
from .snappy_raw import SnappyRawAdapter
from .source_reject_fallback import SourceRejectCompositeAdapter
from .sprintz import SprintzAdapter
from .sprintz8 import Sprintz8Adapter
from .xz_stream import XzStreamAdapter
from .zfp import ZfpAdapter
from .zstd_frame import ZstdFrameAdapter


class AdapterFactoryError(RuntimeError):
    """A reviewed adapter factory or artifact declaration is missing."""


_FROZEN_SOURCE_FACTORIES = {"SIMDCOMP_CTYPES_V1"}
_ADMITTED_RUNTIME_HANDLES: dict[Path, object] = {}


def _adapter_python_closure(root: Path, seeds: list[Path]) -> list[Path]:
    """Follow adapter-local imports, including imports inside conditional paths.

    Factory dispatch imports are intentionally not traversal seeds: they select
    other codecs. This scope does not claim the closure of external packages.
    """
    directory = root / "src/tscompbench/adapters"
    seen: set[Path] = set()
    pending = list(seeds)
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise AdapterFactoryError(f"execution dependency missing or unsafe: {path}")
        seen.add(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as error:
            raise AdapterFactoryError(f"invalid adapter Python dependency: {path}") from error
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level == 1:
                    modules.append(node.module)
                elif node.level == 0 and node.module.startswith("tscompbench.adapters."):
                    modules.append(node.module.removeprefix("tscompbench.adapters."))
            elif isinstance(node, ast.Import):
                modules += [
                    alias.name.removeprefix("tscompbench.adapters.")
                    for alias in node.names
                    if alias.name.startswith("tscompbench.adapters.")
                ]
            for module in modules:
                pending.append(directory / (module.replace(".", "/") + ".py"))
    return sorted(seen)


def adapter_artifacts(project_root: Path, manifest: CodecManifest) -> tuple[Path, tuple[Path, ...]]:
    adapter = manifest.document["adapter"]
    if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
        return (
            project_root / "src" / "tscompbench" / "adapters" / "oracles.py",
            (project_root / "src" / "tscompbench" / "adapters" / "compatibility.py",),
        )
    relative = adapter.get("artifact_path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise AdapterFactoryError(f"{manifest.key} has no safe relative adapter artifact path")
    factory = adapter.get("factory")
    support_modules = {
        "COMPLETED_REWRITE_CTYPES_V1": "completed_rewrites.py",
        "REWRITE_LOSSLESS_CTYPES_V1": "rewrite_lossless.py",
        "ALP_CTYPES_V1": "alp.py",
        "SERF_CTYPES_V1": "serf.py",
        "ENTROPY_FSE_CTYPES_V1": "entropy_fse.py",
        "SPRINTZ_CTYPES_V1": "sprintz.py",
        "SPRINTZ8_CTYPES_V1": "sprintz8.py",
        "BROTLI_STREAM_CTYPES_V1": "brotli_stream.py",
        "BZIP2_STREAM_CTYPES_V1": "bzip2_stream.py",
        "DEFLATE_ZLIB_CTYPES_V1": "deflate_zlib.py",
        "LZSS_RAW_CTYPES_V1": "lzss_raw.py",
        "LZSS_DIPPERSTEIN_CTYPES_V1": "lzss_dipperstein.py",
        "XZ_STREAM_CTYPES_V1": "xz_stream.py",
        "LZ4_FRAME_CTYPES_V1": "lz4_frame.py",
        "LZSSE2_RAW_CTYPES_V1": "lzsse2_raw.py",
        "LZSSE8_RAW_CTYPES_V1": "lzsse8_raw.py",
        "SNAPPY_RAW_CTYPES_V1": "snappy_raw.py",
        "ZSTD_FRAME_CTYPES_V1": "zstd_frame.py",
        "ZFP_CTYPES_V1": "zfp.py",
        "NEATS_CTYPES_V1": "neats.py",
        "SIMDCOMP_CTYPES_V1": "simdcomp.py",
    }
    support_module = support_modules.get(factory)
    if support_module is None:
        raise AdapterFactoryError(f"no reviewed adapter factory for {manifest.key}")
    support = project_root / "src" / "tscompbench" / "adapters" / support_module
    try:
        artifact = project_path(project_root, relative)
        verified_dependencies = verified_build_dependencies(
            project_root, artifact, manifest.key, adapter
        )
    except BuildEvidenceError as error:
        raise AdapterFactoryError(f"{manifest.key}: {error}") from error
    shared_support = [
        project_root / "src/tscompbench/adapters/factory.py",
        project_root / "src/tscompbench/adapters/build_evidence.py",
        project_root / "src/tscompbench/adapters/runtime_evidence.py",
    ]
    # These modules participate in the real native call and recovery path.
    # Returning them binds their contents to the execution artifact identity.
    if factory not in {"COMPLETED_REWRITE_CTYPES_V1"}:
        shared_support.append(project_root / "src/tscompbench/adapters/native_timing.py")
    if factory in {
        "BROTLI_STREAM_CTYPES_V1",
        "BZIP2_STREAM_CTYPES_V1",
        "DEFLATE_ZLIB_CTYPES_V1",
        "XZ_STREAM_CTYPES_V1",
        "LZ4_FRAME_CTYPES_V1",
        "ZSTD_FRAME_CTYPES_V1",
    }:
        shared_support.append(project_root / "src/tscompbench/adapters/native_streaming.py")
        shared_support.append(project_root / "src/tscompbench/adapters/byte_container.py")
    elif factory in {
        "SNAPPY_RAW_CTYPES_V1",
        "ENTROPY_FSE_CTYPES_V1",
        "LZSS_RAW_CTYPES_V1",
        "LZSS_DIPPERSTEIN_CTYPES_V1",
    }:
        shared_support.append(project_root / "src/tscompbench/adapters/byte_container.py")
    for path in (support, *shared_support):
        if not path.is_file() or not path.resolve().is_relative_to(project_root.resolve()):
            raise AdapterFactoryError(
                f"{manifest.key}: execution dependency missing or unsafe: {path}"
            )
    closure_seeds = [support]
    # Both ALP routes bind the optional composition code before the execution
    # planner decides whether to enable source-domain RAW recovery.
    if factory == "ALP_CTYPES_V1":
        closure_seeds.append(project_root / "src/tscompbench/adapters/source_reject_fallback.py")
    shared_support += _adapter_python_closure(project_root, closure_seeds)
    if factory == "COMPLETED_REWRITE_CTYPES_V1" or factory in _FROZEN_SOURCE_FACTORIES:
        artifact = project_root / relative
        record_path = artifact.parent / "build-record.json"
        support_paths = [support, record_path, *shared_support, *verified_dependencies]
        if factory in _FROZEN_SOURCE_FACTORIES:
            support_paths.append(artifact.parent / "compile-command.json")
        support_paths.extend(
            project_root / entry["path"] for entry in adapter.get("models", {}).values()
        )
        if record_path.is_file():
            record = json.loads(record_path.read_text())
            entries = (
                record.get("runtime_dependencies", [])
                + record.get("binding_sources", [])
                + record.get("source_files", [])
                + record.get("compiled_source_closure", [])
            )
            if factory in {"SIMDCOMP_CTYPES_V1"}:
                if record.get("status") != "PASS" or not record.get("objects"):
                    raise AdapterFactoryError(f"{manifest.key}: completed build evidence missing")
                entries += record["objects"]
            if factory == "SIMDCOMP_CTYPES_V1":
                if (
                    manifest.key not in {"simdcomp-u32"}
                    or len(record.get("objects", [])) != 9
                    or len(record.get("patches", [])) != 4
                    or (not record.get("generated_source_files"))
                    or (record.get("shim_isa") != "BASELINE_X86_64_NO_AUTOVECTORIZATION")
                    or (record.get("source_isa") != "SSE4_1_AND_SEPARATE_AVX2_OBJECTS_NO_AVX512")
                    or (record.get("runtime_fallback") is not False)
                    or (not adapter.get("python_source_closure"))
                ):
                    raise AdapterFactoryError(f"{manifest.key}: patched ISA build evidence missing")
                entries += record["patches"] + record["generated_source_files"]
                entries += adapter["python_source_closure"]
                support_paths += [
                    project_root / p
                    for p in (
                        "src/tscompbench/adapters/native_buffers.py",
                        "src/tscompbench/adapters/native_timing.py",
                    )
                ]
            if factory in _FROZEN_SOURCE_FACTORIES:
                if (
                    record.get("algorithm")
                    != ("simdcomp-source-u32" if factory == "SIMDCOMP_CTYPES_V1" else manifest.key)
                    or not record.get("source_files")
                    or (not record.get("binding_sources"))
                    or (not record.get("compiled_source_closure"))
                ):
                    raise AdapterFactoryError(
                        f"{manifest.key}: source/binding build evidence missing"
                    )
                command_path = artifact.parent / "compile-command.json"
                if not command_path.is_file():
                    raise AdapterFactoryError(f"{manifest.key}: compile command missing")
                if command_path.is_file():
                    command = json.loads(command_path.read_text())
                    actual = hashlib.sha256(canonical_json_bytes(command)).hexdigest()
                    if actual != record["compile_commands_sha256"]:
                        raise AdapterFactoryError(f"{manifest.key}: compile command drift")
            for entry in entries:
                path = Path(entry["path"])
                if not path.is_absolute():
                    path = project_root / path
                if path.is_file():
                    with path.open("rb") as stream:
                        actual = hashlib.file_digest(stream, "sha256").hexdigest()
                    if actual != entry["sha256"]:
                        raise AdapterFactoryError(
                            f"{manifest.key}: execution dependency drift: {path}"
                        )
                elif factory in _FROZEN_SOURCE_FACTORIES:
                    raise AdapterFactoryError(
                        f"{manifest.key}: execution dependency missing: {path}"
                    )
                support_paths.append(path)
            if artifact.is_file():
                with artifact.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != record["artifact_sha256"]:
                    raise AdapterFactoryError(f"{manifest.key}: build artifact drift")
        elif factory in _FROZEN_SOURCE_FACTORIES:
            raise AdapterFactoryError(f"{manifest.key}: build record missing")
        return (artifact, tuple(dict.fromkeys(support_paths)))
    if factory in {"LZSS_RAW_CTYPES_V1", "LZSS_DIPPERSTEIN_CTYPES_V1"}:
        common = project_root / "src" / "tscompbench" / "adapters" / "lzss_common.py"
        if not common.is_file() or not common.resolve().is_relative_to(project_root.resolve()):
            raise AdapterFactoryError(
                f"{manifest.key}: execution dependency missing or unsafe: {common}"
            )
        return (
            artifact,
            tuple(dict.fromkeys((support, common, *shared_support, *verified_dependencies))),
        )
    return (artifact, tuple(dict.fromkeys((support, *shared_support, *verified_dependencies))))


def _create_adapter(
    project_root: Path,
    manifest: CodecManifest,
    *,
    source_reject_fallback: bool = False,
) -> CodecAdapter:
    if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
        return OracleAdapter(manifest_adapter=manifest.document["adapter"])
    adapter = manifest.document["adapter"]
    if adapter.get("factory") == "COMPLETED_REWRITE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return CompletedRewriteAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "REWRITE_LOSSLESS_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return RewriteLosslessAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "ALP_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        child = AlpAdapter(artifact, adapter, manifest.key)
        # ALP's forced decimal scheme may reject a rowgroup that selects ALP-RD.
        # Preserve the registered ALP identity while using an explicit v2
        # composite recipe that stores only typed source-domain rejects as RAW.
        if manifest.key == "alp" and source_reject_fallback:
            return SourceRejectCompositeAdapter(child, manifest.key)
        return child
    if adapter.get("factory") == "SERF_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SerfAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "ENTROPY_FSE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return EntropyAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "SPRINTZ8_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return Sprintz8Adapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "SPRINTZ_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SprintzAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "BROTLI_STREAM_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return BrotliStreamAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "BZIP2_STREAM_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return Bzip2StreamAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "DEFLATE_ZLIB_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return DeflateZlibAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "SIMDCOMP_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SIMDCompAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "LZSS_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return LzssRawAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "LZSS_DIPPERSTEIN_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return LzssDippersteinAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "XZ_STREAM_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return XzStreamAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "LZ4_FRAME_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return Lz4FrameAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "LZSSE8_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return Lzsse8RawAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "LZSSE2_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return Lzsse2RawAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "ZSTD_FRAME_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return ZstdFrameAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "ZFP_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return ZfpAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "NEATS_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return NeatsAdapter(artifact, manifest.document["adapter"], manifest.key)
    if adapter.get("factory") == "SNAPPY_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SnappyRawAdapter(artifact, manifest.document["adapter"])
    raise AdapterFactoryError(f"no reviewed adapter factory for {manifest.key}")


def create_adapter(
    project_root: Path,
    manifest: CodecManifest,
    *,
    source_reject_fallback: bool = False,
) -> CodecAdapter:
    result = _create_adapter(project_root, manifest, source_reject_fallback=source_reject_fallback)
    if manifest.document["identity"]["family"] != "HARNESS_ORACLE":
        adapter = manifest.document["adapter"]
        artifact = project_path(project_root, adapter["artifact_path"])
        try:
            handle = load_verified_runtime(project_root, artifact, adapter)
            if handle is not None:
                # Keep the admitted load alive for adapters whose native symbol
                # binding is delayed until create_session().
                _ADMITTED_RUNTIME_HANDLES[artifact.resolve()] = handle
        except RuntimeEvidenceError as error:
            raise AdapterFactoryError(f"{manifest.key}: {error}") from error
    return result
