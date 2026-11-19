"""Asset identity and local path resolution shared by all control-layer entry points."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


class ContractError(ValueError):
    """A declared contract or a bound artifact failed validation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def relative_parts(relative: str) -> tuple[str, ...]:
    require(isinstance(relative, str) and bool(relative), "asset path must be a nonempty string")
    p = PurePosixPath(relative)
    parts = tuple(relative.split("/"))
    require(not p.is_absolute() and all(part not in {"", ".", ".."} for part in parts)
            and "\\" not in relative and "\0" not in relative, f"non-canonical asset path: {relative!r}")
    return parts


def local_file(root: Path, relative: str) -> Path:
    parts = relative_parts(relative)
    base = root.resolve(strict=True)
    try:
        result = base.joinpath(*parts).resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise ContractError(f"unavailable local asset: {relative}") from exc
    require(result.is_relative_to(base), f"asset path escaped project: {relative}")
    require(result.is_file(), f"local asset is not a regular file: {relative}")
    return result


def stream_digest(stream: BinaryIO) -> str:
    return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return stream_digest(file)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def content_id(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _finite(value: str) -> float:
    result = float(value)
    require(math.isfinite(result), f"non-finite number: {value}")
    return result


def _constant(value: str) -> None:
    raise ContractError(f"non-finite number: {value}")


def parse_json(text: str, location: str = "JSON") -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_float=_finite, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON: {location}: {exc}") from exc


def load_json(path: Path) -> Any:
    try:
        return parse_json(path.read_text(encoding="utf-8"), str(path))
    except UnicodeError as exc:
        raise ContractError(f"invalid JSON: {path}: {exc}") from exc


def verify_asset(root: Path, reference: dict) -> Path:
    path = local_file(root, reference["path"])
    expected = reference["sha256"]
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None,
            f"invalid digest for {reference['path']}")
    require(digest(path) == expected, f"local asset SHA-256 mismatch: {reference['path']}")
    return path
