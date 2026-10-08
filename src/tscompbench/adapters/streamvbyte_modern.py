"""Frozen modern 1234 Stream VByte, with explicit count and separate P0/P2 IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tscompbench.execution.protocol import ExecutionContractError
from tscompbench.preprocess.streamvbyte_modern import EXECUTOR_ID

from .streamvbyte import StreamVByteAdapter, StreamVByteSession
from .streamvbyte_pipeline import StreamVBytePipelineAdapter, StreamVBytePipelineSession


class ModernStreamVByteSession(StreamVByteSession):
    backend_stage_name = "MODERN_STREAM_VBYTE_1234_SSE41"
    primitive_key = "streamvbyte-modern-u32"
    pipeline_key = "delta-zigzag-streamvbyte-modern64"
    expected_encoder = "UPSTREAM_SSE4_1_WITH_SCALAR_TAIL"


class ModernStreamVBytePipelineSession(StreamVBytePipelineSession):
    backend_stage_name = "MODERN_STREAM_VBYTE_1234_SSE41"
    primitive_key = "streamvbyte-modern-u32"
    pipeline_key = "delta-zigzag-streamvbyte-modern64"
    pipeline_executor_id = EXECUTOR_ID
    expected_encoder = "UPSTREAM_SSE4_1_WITH_SCALAR_TAIL"


@dataclass(frozen=True)
class ModernStreamVByteAdapter(StreamVByteAdapter):
    def create_session(self, parameters: dict[str, Any]) -> ModernStreamVByteSession:
        if parameters.get("isa", "SSE4_1") != "SSE4_1":
            raise ExecutionContractError("modern Stream VByte requires fixed SSE4_1")
        return ModernStreamVByteSession(self.library_path, self.algorithm, parameters)


@dataclass(frozen=True)
class ModernStreamVBytePipelineAdapter(StreamVBytePipelineAdapter):
    pipeline_executor_id = EXECUTOR_ID

    def create_session(self, parameters: dict[str, Any]) -> ModernStreamVBytePipelineSession:
        if parameters.get("isa", "SSE4_1") != "SSE4_1":
            raise ExecutionContractError("modern Stream VByte requires fixed SSE4_1")
        return ModernStreamVBytePipelineSession(self.library_path, self.algorithm, parameters)
