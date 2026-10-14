"""Small, append-only records with recoverable interrupted JSONL tails."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)


def append(path: str | Path, row: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as handle:
        handle.write(canonical_json(row) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Accept only a valid prefix; malformed complete lines are never ignored."""
    target = Path(path)
    if not target.exists():
        return [], None
    rows = []
    offset = 0
    with target.open("rb") as handle:
        while line := handle.readline():
            start = offset
            offset += len(line)
            if not line.endswith(b"\n"):
                return rows, {"offset": start, "length": len(line),
                              "sha256": hashlib.sha256(line).hexdigest()}
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError) as error:
                raise ValueError(f"invalid complete JSONL line at byte {start}") from error
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row at byte {start} is not an object")
            rows.append(row)
    return rows, None


def preserve_tail(path: str | Path, tail: dict[str, Any]) -> Path:
    """Save interrupted bytes before restoring the valid append boundary."""
    target = Path(path)
    recovered = target.with_name(target.name + ".interrupted-" + tail["sha256"][:12])
    with target.open("r+b") as handle:
        handle.seek(tail["offset"])
        recovered.write_bytes(handle.read())
        handle.truncate(tail["offset"])
        handle.flush()
        os.fsync(handle.fileno())
    return recovered
