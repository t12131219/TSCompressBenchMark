from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


class CanonicalJSONError(ValueError):
    """Raised when a value has no cross-language canonical representation."""


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Enum):
        return _normalize(value.value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalJSONError("non-finite Decimal values are forbidden")
        return {"$decimal": format(value.normalize(), "f")}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJSONError("non-finite float values are forbidden")
        raise CanonicalJSONError(
            "binary floats are forbidden in identity payloads; use a decimal string"
        )
    if isinstance(value, Path):
        raise CanonicalJSONError("paths are forbidden in identity payloads; use a content ID")
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError("canonical JSON object keys must be strings")
            normalized[unicodedata.normalize("NFC", key)] = _normalize(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    raise CanonicalJSONError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON shared by Python and future native runners."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_id(domain: str, value: Any, *, version: str = "v2") -> str:
    if not domain or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in domain
    ):
        raise CanonicalJSONError(f"invalid ID domain: {domain!r}")
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"{version}:{domain}:sha256:{digest}"
