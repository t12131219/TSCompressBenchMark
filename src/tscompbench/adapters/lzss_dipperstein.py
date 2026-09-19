from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

from .lzss_common import _buffer as _buffer
from .lzss_common import _LzssSession, _LzssVariant

_DIPPERSTEIN_VARIANT = _LzssVariant(
    algorithm="lzss-dipperstein-c",
    stream="LZSS_OFFSET12_LE_NUMERIC_LENGTH4_MSB_BIT_IO",
    dictionary="FIXED_SPACE_FILLED_4096B",
    magic=b"TSCBLZD\x00",
    schema_version="tscb.lzss-dipperstein-c-container.v1",
    native_config={
        "initial_byte": 32,
        "length_bits": 4,
        "match_finder": "BINARY_TREE",
        "offset_bits": 12,
    },
    offset_bits=12,
    length_bits=4,
    minimum_match=3,
    accounting_method="EXACT_TSCB_LZSS_DIPPERSTEIN_TOKEN_BITS_AND_ZERO_PADDING",
)


@dataclass(frozen=True)
class LzssDippersteinAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> LzssDippersteinSession:
        return LzssDippersteinSession(self.library_path, parameters)


class LzssDippersteinSession(_LzssSession):
    _VARIANT = _DIPPERSTEIN_VARIANT
