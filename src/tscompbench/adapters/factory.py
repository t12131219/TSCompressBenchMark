from __future__ import annotations

from pathlib import Path

from tscompbench.codecs import CodecManifest
from tscompbench.execution.protocol import CodecAdapter

from .brotli_stream import BrotliStreamAdapter
from .deflate_zlib import DeflateZlibAdapter
from .entropy_fse import EntropyAdapter
from .lz4_frame import Lz4FrameAdapter
from .lzss_raw import LzssRawAdapter
from .lzsse2_raw import Lzsse2RawAdapter
from .lzsse8_raw import Lzsse8RawAdapter
from .oracles import OracleAdapter
from .snappy_raw import SnappyRawAdapter
from .sprintz import SprintzAdapter
from .sprintz8 import Sprintz8Adapter
from .xz_stream import XzStreamAdapter
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
        "ENTROPY_FSE_CTYPES_V1": "entropy_fse.py",
        "SPRINTZ_CTYPES_V1": "sprintz.py",
        "SPRINTZ8_CTYPES_V1": "sprintz8.py",
        "BROTLI_STREAM_CTYPES_V1": "brotli_stream.py",
        "DEFLATE_ZLIB_CTYPES_V1": "deflate_zlib.py",
        "LZSS_RAW_CTYPES_V1": "lzss_raw.py",
        "XZ_STREAM_CTYPES_V1": "xz_stream.py",
        "LZ4_FRAME_CTYPES_V1": "lz4_frame.py",
        "LZSSE2_RAW_CTYPES_V1": "lzsse2_raw.py",
        "LZSSE8_RAW_CTYPES_V1": "lzsse8_raw.py",
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
    if adapter.get("factory") == "DEFLATE_ZLIB_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return DeflateZlibAdapter(artifact, manifest.document["adapter"])
    if adapter.get("factory") == "LZSS_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return LzssRawAdapter(artifact, manifest.document["adapter"])
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
    if adapter.get("factory") == "SNAPPY_RAW_CTYPES_V1":
        artifact, _ = adapter_artifacts(project_root, manifest)
        return SnappyRawAdapter(artifact, manifest.document["adapter"])
    raise AdapterFactoryError(f"no reviewed adapter factory for {manifest.key}")
