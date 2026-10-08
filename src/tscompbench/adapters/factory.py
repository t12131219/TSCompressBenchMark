from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tscompbench.codecs import CodecManifest
from tscompbench.execution.protocol import CodecAdapter
from tscompbench.ids import canonical_json_bytes

from .alp import AlpAdapter
from .brotli_stream import BrotliStreamAdapter
from .bzip2_stream import Bzip2StreamAdapter
from .completed_rewrites import CompletedRewriteAdapter
from .deflate_zlib import DeflateZlibAdapter
from .delta_varint import DeltaVarintAdapter
from .entropy_fse import EntropyAdapter
from .fast_differential import FastDifferentialAdapter
from .fastpfor_simple import FastPFORSimpleAdapter
from .fastpfor_simple8b_rle import FastPFORSimple8bRLEAdapter
from .fastpfor_simple8b_rle import execution_artifacts as simple8b_rle_artifacts
from .littleintpacker import LittleIntPackerAdapter
from .littleintpacker import execution_artifacts as littleintpacker_artifacts
from .lz4_frame import Lz4FrameAdapter
from .lzss_dipperstein import LzssDippersteinAdapter
from .lzss_raw import LzssRawAdapter
from .lzsse2_raw import Lzsse2RawAdapter
from .lzsse8_raw import Lzsse8RawAdapter
from .maskedvbyte import MaskedVByteAdapter
from .neats import NeatsAdapter
from .oracles import OracleAdapter
from .rewrite_lossless import RewriteLosslessAdapter
from .serf import SerfAdapter
from .simdcomp import SIMDCompAdapter
from .snappy_raw import SnappyRawAdapter
from .sprintz import SprintzAdapter
from .sprintz8 import Sprintz8Adapter
from .streamvbyte import StreamVByteAdapter
from .streamvbyte_modern import ModernStreamVByteAdapter, ModernStreamVBytePipelineAdapter
from .streamvbyte_pipeline import StreamVBytePipelineAdapter
from .xz_stream import XzStreamAdapter
from .zfp import ZfpAdapter
from .zstd_frame import ZstdFrameAdapter


class AdapterFactoryError(RuntimeError):
    """A reviewed adapter factory or artifact declaration is missing."""


_STREAMVBYTE_FACTORIES = {
    "STREAMVBYTE_CTYPES_V1",
    "STREAMVBYTE_PIPELINE_CTYPES_V1",
    "STREAMVBYTE_MODERN_CTYPES_V1",
    "STREAMVBYTE_MODERN_PIPELINE_CTYPES_V1",
}
_FROZEN_SOURCE_FACTORIES = _STREAMVBYTE_FACTORIES | {
    "FAST_DIFFERENTIAL_CTYPES_V1",
    "MASKEDVBYTE_CTYPES_V1",
    "SIMDCOMP_CTYPES_V1",
    "FASTPFOR_SIMPLE_CTYPES_V1",
}


def adapter_artifacts(project_root: Path, manifest: CodecManifest) -> tuple[Path, tuple[Path, ...]]:
    adapter = manifest.document["adapter"]
    if adapter.get("factory") == "FASTPFOR_SIMPLE8B_RLE_CTYPES_V1":
        try:
            return simple8b_rle_artifacts(project_root, manifest)
        except (RuntimeError, OSError, ValueError, KeyError) as error:
            raise AdapterFactoryError(f"{manifest.key}: {error}") from error
    if adapter.get("factory") == "LITTLEINTPACKER_CTYPES_V1":
        try:
            return littleintpacker_artifacts(project_root, manifest)
        except (RuntimeError, OSError, ValueError, KeyError) as error:
            raise AdapterFactoryError(f"{manifest.key}: {error}") from error
    if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
        return project_root / "src" / "tscompbench" / "adapters" / "oracles.py", (
            project_root / "src" / "tscompbench" / "adapters" / "compatibility.py",
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
        "DELTA_VARINT_CTYPES_V1": "delta_varint.py",
        "STREAMVBYTE_CTYPES_V1": "streamvbyte.py",
        "STREAMVBYTE_PIPELINE_CTYPES_V1": "streamvbyte_pipeline.py",
        "STREAMVBYTE_MODERN_CTYPES_V1": "streamvbyte_modern.py",
        "STREAMVBYTE_MODERN_PIPELINE_CTYPES_V1": "streamvbyte_modern.py",
        "FAST_DIFFERENTIAL_CTYPES_V1": "fast_differential.py",
        "MASKEDVBYTE_CTYPES_V1": "maskedvbyte.py",
        "SIMDCOMP_CTYPES_V1": "simdcomp.py",
        "FASTPFOR_SIMPLE_CTYPES_V1": "fastpfor_simple.py",
    }
    support_module = support_modules.get(factory)
    if support_module is None:
        raise AdapterFactoryError(f"no reviewed adapter factory for {manifest.key}")
    support = project_root / "src" / "tscompbench" / "adapters" / support_module
    if factory == "COMPLETED_REWRITE_CTYPES_V1" or factory in _FROZEN_SOURCE_FACTORIES:
        artifact = project_root / relative
        record_path = artifact.parent / "build-record.json"
        support_paths = [support, record_path]
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
            if factory in {
                "FAST_DIFFERENTIAL_CTYPES_V1",
                "MASKEDVBYTE_CTYPES_V1",
                "SIMDCOMP_CTYPES_V1",
                "FASTPFOR_SIMPLE_CTYPES_V1",
            }:
                if record.get("status") != "PASS" or not record.get("objects"):
                    raise AdapterFactoryError(f"{manifest.key}: completed build evidence missing")
                entries += record["objects"]
            if factory == "FASTPFOR_SIMPLE_CTYPES_V1":
                if (
                    manifest.key not in {"simple9-u28", "simple9hacked-u28", "simple16-u28"}
                    or record.get("algorithm") != "fastpfor-simple-source"
                    or record.get("source_isa") != "BASELINE_X86_64_NO_AUTOVECTORIZATION"
                    or record.get("upstream_commit") != "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
                    or record.get("patches") != []
                    or record.get("runtime_fallback") is not False
                    or len(record["objects"]) != 1
                ):
                    raise AdapterFactoryError(
                        f"{manifest.key}: Simple source build identity differs"
                    )
                python_closure = adapter.get("python_source_closure", [])
                if not {
                    "src/tscompbench/adapters/factory.py",
                    "src/tscompbench/adapters/fastpfor_simple.py",
                    "src/tscompbench/adapters/deflate_zlib.py",
                    "src/tscompbench/adapters/native_timing.py",
                    "src/tscompbench/execution/protocol.py",
                    "src/tscompbench/execution/repetition.py",
                } <= {p.get("path") for p in python_closure}:
                    raise AdapterFactoryError(f"{manifest.key}: Simple Python closure missing")
                entries += python_closure
            if factory == "MASKEDVBYTE_CTYPES_V1":
                if (
                    record.get("codec_keys") != ["maskedvbyte-u32", "delta-maskedvbyte-u32"]
                    or manifest.key not in record["codec_keys"]
                    or not record.get("patches")
                    or not record.get("generated_source_files")
                ):
                    raise AdapterFactoryError(f"{manifest.key}: patched build evidence missing")
                entries += record["patches"] + record["generated_source_files"]
            if factory == "SIMDCOMP_CTYPES_V1":
                if (
                    manifest.key not in {"simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32"}
                    or len(record.get("objects", [])) != 9
                    or len(record.get("patches", [])) != 4
                    or not record.get("generated_source_files")
                    or record.get("shim_isa") != "BASELINE_X86_64_NO_AUTOVECTORIZATION"
                    or record.get("source_isa") != "SSE4_1_AND_SEPARATE_AVX2_OBJECTS_NO_AVX512"
                    or record.get("runtime_fallback") is not False
                    or not adapter.get("python_source_closure")
                ):
                    raise AdapterFactoryError(f"{manifest.key}: patched ISA build evidence missing")
                entries += record["patches"] + record["generated_source_files"]
                entries += adapter["python_source_closure"]
                support_paths += [
                    project_root / p
                    for p in (
                        "src/tscompbench/adapters/deflate_zlib.py",
                        "src/tscompbench/adapters/maskedvbyte.py",
                        "src/tscompbench/adapters/native_timing.py",
                        "src/tscompbench/preprocess/simdcomp.py",
                    )
                ]
            if factory in _FROZEN_SOURCE_FACTORIES:
                if (
                    record.get("algorithm")
                    != (
                        "maskedvbyte-source-u32"
                        if factory == "MASKEDVBYTE_CTYPES_V1"
                        else "simdcomp-source-u32"
                        if factory == "SIMDCOMP_CTYPES_V1"
                        else "fastpfor-simple-source"
                        if factory == "FASTPFOR_SIMPLE_CTYPES_V1"
                        else manifest.key
                    )
                    or not record.get("source_files")
                    or not record.get("binding_sources")
                    or not record.get("compiled_source_closure")
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
        return artifact, tuple(dict.fromkeys(support_paths))
    if factory in {"LZSS_RAW_CTYPES_V1", "LZSS_DIPPERSTEIN_CTYPES_V1"}:
        common = project_root / "src" / "tscompbench" / "adapters" / "lzss_common.py"
        return project_root / relative, (support, common)
    return project_root / relative, (support,)


def create_adapter(project_root: Path, manifest: CodecManifest) -> CodecAdapter:
    if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
        return OracleAdapter(manifest_adapter=manifest.document["adapter"])
    adapter = manifest.document["adapter"]
    if adapter.get("factory") == "FASTPFOR_SIMPLE8B_RLE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return FastPFORSimple8bRLEAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "LITTLEINTPACKER_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return LittleIntPackerAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "COMPLETED_REWRITE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return CompletedRewriteAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "REWRITE_LOSSLESS_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return RewriteLosslessAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "ALP_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return AlpAdapter(artifact, adapter, manifest.key)
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
    if adapter.get("factory") == "DELTA_VARINT_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return DeltaVarintAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "FAST_DIFFERENTIAL_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return FastDifferentialAdapter(artifact, adapter)
    if adapter.get("factory") == "MASKEDVBYTE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return MaskedVByteAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "SIMDCOMP_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SIMDCompAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "FASTPFOR_SIMPLE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return FastPFORSimpleAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "STREAMVBYTE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return StreamVByteAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") == "STREAMVBYTE_PIPELINE_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return StreamVBytePipelineAdapter(artifact, adapter, manifest.key)
    if adapter.get("factory") in {
        "STREAMVBYTE_MODERN_CTYPES_V1",
        "STREAMVBYTE_MODERN_PIPELINE_CTYPES_V1",
    }:
        artifact, _ = adapter_artifacts(project_root, manifest)
        driver = (
            ModernStreamVBytePipelineAdapter
            if "PIPELINE" in adapter["factory"]
            else ModernStreamVByteAdapter
        )
        return driver(artifact, adapter, manifest.key)
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
