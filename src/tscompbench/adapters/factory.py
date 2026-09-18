from __future__ import annotations

from pathlib import Path

from tscompbench.codecs import CodecManifest
from tscompbench.execution.protocol import CodecAdapter

from .brotli_stream import BrotliStreamAdapter
from .lz4_frame import Lz4FrameAdapter
from .oracles import OracleAdapter
from .snappy_raw import SnappyRawAdapter
from .zstd_frame import ZstdFrameAdapter


class AdapterFactoryError(RuntimeError):
    """A reviewed adapter factory or artifact declaration is missing."""


def adapter_artifacts(project_root: Path, manifest: CodecManifest) -> tuple[Path, tuple[Path, ...]]:
    adapter = manifest.document["adapter"]
    if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
        return project_root / "src" / "tscompbench" / "adapters" / "oracles.py", (
            project_root / "src" / "tscompbench" / "adapters" / "compatibility.py",
        )
    relative = adapter.get("artifact_path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise AdapterFactoryError(f"{manifest.key} has no safe relative adapter artifact path")
    factory = adapter.get("factory")
    support_modules = {
        "BROTLI_STREAM_CTYPES_V1": "brotli_stream.py",
        "LZ4_FRAME_CTYPES_V1": "lz4_frame.py",
        "SNAPPY_RAW_CTYPES_V1": "snappy_raw.py",
        "ZSTD_FRAME_CTYPES_V1": "zstd_frame.py",
    }
    support_module = support_modules.get(factory)
    if support_module is None:
        raise AdapterFactoryError(f"no reviewed adapter factory for {manifest.key}")
    support = project_root / "src" / "tscompbench" / "adapters" / support_module
    return project_root / relative, (support,)


def create_adapter(project_root: Path, manifest: CodecManifest) -> CodecAdapter:
    if manifest.document["identity"]["family"] == "HARNESS_ORACLE":
        return OracleAdapter(manifest_adapter=manifest.document["adapter"])
    adapter = manifest.document["adapter"]
    if adapter.get("factory") == "BROTLI_STREAM_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return BrotliStreamAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "LZ4_FRAME_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return Lz4FrameAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "ZSTD_FRAME_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return ZstdFrameAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "SNAPPY_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SnappyRawAdapter(artifact, manifest.document["adapter"])
    raise AdapterFactoryError(f"no reviewed adapter factory for {manifest.key}")
