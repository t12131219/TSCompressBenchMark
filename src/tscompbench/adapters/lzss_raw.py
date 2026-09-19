from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

from .lzss_common import _PREFIX as _PREFIX
from .lzss_common import _buffer as _buffer
from .lzss_common import _LzssSession, _LzssVariant

_RUST_VARIANT = _LzssVariant(
    algorithm="lzss-raw",
    stream="LZSS_EI10_EJ4_C32",
    dictionary="NONE",
    magic=b"TSCBLZS\x00",
    schema_version="tscb.lzss-raw-container.v1",
    native_config={"ei": 10, "ej": 4, "initial_byte": 32},
    offset_bits=10,
    length_bits=4,
    minimum_match=2,
    accounting_method="EXACT_TSCB_LZSS_TOKEN_BITS_AND_ZERO_PADDING",
)


@dataclass(frozen=True)
class LzssRawAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> LzssRawSession:
        return LzssRawSession(self.library_path, parameters)


class LzssRawSession(_LzssSession):
    _VARIANT = _RUST_VARIANT
