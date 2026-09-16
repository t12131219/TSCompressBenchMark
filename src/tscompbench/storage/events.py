from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EventLogError(ValueError):
    pass


def append_event(path: Path, event_type: str, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }
    encoded = (
        json.dumps(
            event,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("short append-only event write")
        os.fsync(descriptor)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def validate_event_log(path: Path) -> int:
    if not path.is_file():
        raise EventLogError("event log is missing")
    count = 0
    with path.open("rb") as handle:
        for line_number, encoded in enumerate(handle, start=1):
            if not encoded.endswith(b"\n"):
                raise EventLogError(f"event log line {line_number} is not newline terminated")
            try:
                event = json.loads(encoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise EventLogError(f"event log line {line_number} is invalid JSON") from error
            if set(event) != {"timestamp_utc", "event_type", "payload"}:
                raise EventLogError(f"event log line {line_number} has an invalid schema")
            if not isinstance(event["event_type"], str) or not isinstance(event["payload"], dict):
                raise EventLogError(f"event log line {line_number} has invalid field types")
            count += 1
    if count == 0:
        raise EventLogError("event log is empty")
    return count
