#!/usr/bin/env python3
"""Fetch or verify frozen CSV inputs, always writing an acquisition manifest.

Uses only the Python standard library. It never imports codecs or the runner,
rewrites a CSV, accepts a different file hash, or silently replaces an existing
file. Public download failures remain structured evidence in the manifest.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_manifest(path: Path, document: dict) -> None:
    content = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".acquisition-", delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_csv(data: bytes, dataset: dict) -> dict:
    parser = dataset["parser"]
    if parser["value_dtype"] != "<f8" or parser["timestamp_dtype"] != "<i8" or parser["time_unit"] != "ns":
        raise ValueError("unsupported frozen parse contract")
    reader = csv.reader(io.StringIO(data.decode("utf-8", errors="strict"), newline=""), strict=True)
    header = next(reader)
    if header != dataset["file"]["columns"] or len(set(header)) != len(header):
        raise ValueError("CSV header differs from frozen exact columns")
    value_indices = [header.index(name) for name in parser["value_columns"]]
    time_index = header.index(parser["timestamp_column"])
    values, timestamps = [], []
    epoch = dt.datetime(1970, 1, 1)
    previous = None
    duplicate_times = 0
    for row_number, row in enumerate(reader, 2):
        if len(row) != len(header):
            raise ValueError(f"row {row_number}: wrong column count")
        parsed_values = [float(row[index]) for index in value_indices]
        if not all(math.isfinite(value) for value in parsed_values):
            raise ValueError(f"row {row_number}: selected values must be finite")
        instant = dt.datetime.strptime(row[time_index], parser["timestamp_format"])
        difference = instant - epoch
        timestamp = (difference.days * 86400 + difference.seconds) * 10**9 + difference.microseconds * 1000
        if not -(2**63) <= timestamp < 2**63:
            raise ValueError(f"row {row_number}: timestamp overflows i64 ns")
        if previous is not None:
            if timestamp < previous:
                raise ValueError(f"row {row_number}: decreasing timestamps violate preserve-order contract")
            duplicate_times += timestamp == previous
        previous = timestamp
        values.append(b"".join(struct.pack("<d", value) for value in parsed_values))
        timestamps.append(struct.pack("<q", timestamp))
    if len(values) != dataset["file"]["rows"]:
        raise ValueError("CSV row count differs from frozen catalog")
    def identity(start: int, stop: int) -> dict:
        if not 0 <= start <= stop <= len(values):
            raise ValueError("frozen window exceeds source row count")
        v, t = b"".join(values[start:stop]), b"".join(timestamps[start:stop])
        return {"start": start, "stop": stop, "rows": stop-start,
                "value_shape": [stop-start] if len(value_indices) == 1 else [stop-start, len(value_indices)],
                "value_bytes": len(v), "timestamp_bytes": len(t),
                "value_logical_bytes_sha256": digest(v), "timestamp_logical_bytes_sha256": digest(t)}
    split = dataset["study_split"]
    development = identity(*split["development"])
    evaluation = identity(*split["evaluation"])
    if split["development"][1] > split["evaluation"][0]:
        raise ValueError("development and evaluation intervals overlap")
    windows = []
    for length in split["nested_lengths"]:
        start = split["evaluation"][0]
        if start + length > split["evaluation"][1]:
            raise ValueError("nested evaluation window exceeds evaluation interval")
        windows.append(identity(start, start+length))
    result = {"rows": len(values), "columns": header, "selected_columns": parser["value_columns"],
              "duplicate_adjacent_timestamps": duplicate_times, "full_source": identity(0, len(values)),
              "development": development, "evaluation": evaluation, "nested_evaluation_windows": windows,
              "hash_scope": "Little-endian C-order component bytes; these are not tsbench raw_object_id hashes"}
    expected = dataset.get("frozen_parse")
    if expected is not None and result != expected:
        raise ValueError("parsed component/window identities differ from frozen catalog")
    return result


def verify(path: Path, dataset: dict, evidence: dict) -> None:
    size = path.stat().st_size
    evidence.update(path=str(path.resolve()), actual_bytes=size)
    if size != dataset["file"]["bytes"]:
        raise ValueError("file byte length differs from frozen catalog")
    data = path.read_bytes()
    evidence["actual_sha256"] = digest(data)
    if len(data) != dataset["file"]["bytes"] or evidence["actual_sha256"] != dataset["file"]["sha256"]:
        raise ValueError("file SHA-256 differs from frozen catalog")
    evidence["parse"] = parse_csv(data, dataset)


def fetch(path: Path, dataset: dict, evidence: dict, url: str, timeout: float) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("download URL must use HTTPS")
    expected_size = dataset["file"]["bytes"]
    temporary = None
    evidence.update(requested_url=url, transfer_started_at_utc=now(), received_bytes=0)
    checksum = hashlib.sha256()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "tsbench-frozen-data/1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            evidence.update(http_status=response.status, final_url=response.url,
                            content_type=response.headers.get("Content-Type"),
                            content_length=response.headers.get("Content-Length"),
                            etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified"))
            if urllib.parse.urlsplit(response.url).scheme != "https":
                raise ValueError("download redirected outside HTTPS")
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".dataset-", delete=False) as handle:
                temporary = Path(handle.name)
                while True:
                    block = response.read(min(65536, expected_size+1-evidence["received_bytes"]))
                    if not block:
                        break
                    handle.write(block)
                    checksum.update(block)
                    evidence["received_bytes"] += len(block)
                    if evidence["received_bytes"] > expected_size:
                        raise ValueError("download exceeds frozen byte length")
                handle.flush()
                os.fsync(handle.fileno())
        evidence["received_sha256"] = checksum.hexdigest()
        verify(temporary, dataset, evidence)
        # Hard link publication is atomic and fails if another writer installed
        # a file meanwhile. Never overwrite an existing source file.
        os.link(temporary, path)
        evidence["path"] = str(path.resolve())
        evidence["download_installed"] = True
    except urllib.error.HTTPError as error:
        evidence.update(http_status=error.code, final_url=error.url,
                        response_body_prefix=error.read(1024).decode("utf-8", errors="replace"))
        raise
    finally:
        evidence["received_sha256"] = checksum.hexdigest()
        evidence["transfer_finished_at_utc"] = now()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "fetch"))
    parser.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parents[2] / "registry/datasets/catalog.json")
    parser.add_argument("--directory", type=Path, required=True, help="Local CSV directory; raw CSVs are never rewritten")
    parser.add_argument("--dataset", action="append", help="Repeat to select source ids; default: all")
    parser.add_argument("--url", action="append", default=[], help="Override a download route as dataset_id=https://...; exact frozen hash still required")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--manifest", type=Path, required=True, help="New manifest path; existing manifests are never overwritten")
    args = parser.parse_args(argv)
    manifest_path = args.manifest.resolve()
    directory = args.directory.resolve()
    if manifest_path.exists():
        parser.error("--manifest already exists; use a new path to preserve prior evidence")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the destination before any download. Later snapshots use atomic
    # replacement only on the manifest created by this invocation.
    manifest_path.touch(exist_ok=False)
    manifest = {"schema": "tsbench.data-acquisition/1", "started_at_utc": now(), "status": "running",
                "action": args.action, "directory": str(directory), "catalog_path": str(args.catalog.resolve()),
                "script_sha256": digest(Path(__file__).read_bytes()), "python_version": sys.version,
                "selected_dataset_ids": args.dataset, "timeout_s": args.timeout, "records": []}
    try:
        catalog_bytes = args.catalog.read_bytes()
        manifest["catalog_sha256"] = digest(catalog_bytes)
        catalog = json.loads(catalog_bytes)
        if catalog["schema"] != "tsbench.dataset-catalog/1":
            raise ValueError("unknown dataset catalog schema")
        frozen_identity = "sha256:" + digest(json.dumps(catalog["datasets"], sort_keys=True, separators=(",", ":"),
                                                       ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if catalog["freeze_id"] != frozen_identity:
            raise ValueError("dataset catalog freeze_id mismatch")
        manifest["freeze_id"] = catalog["freeze_id"]
        datasets = {item["id"]: item for item in catalog["datasets"]}
        selected = args.dataset or list(datasets)
        if len(set(selected)) != len(selected) or set(selected)-set(datasets):
            raise ValueError("duplicate or unknown dataset id")
        overrides = {}
        for item in args.url:
            key, url = item.split("=", 1)
            if key in overrides or key not in selected:
                raise ValueError("duplicate URL override or source not selected")
            overrides[key] = url
        if args.action == "fetch":
            directory.mkdir(parents=True, exist_ok=True)
        save_manifest(manifest_path, manifest)
        for key in selected:
            dataset = datasets[key]
            name = dataset["file"]["name"]
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("catalog filename must be a basename")
            path = directory / name
            if path.resolve() == manifest_path:
                raise ValueError("manifest cannot replace a source CSV")
            record = {"dataset_id": key, "status": "running", "started_at_utc": now(),
                      "expected_bytes": dataset["file"]["bytes"], "expected_sha256": dataset["file"]["sha256"],
                      "license": dataset["license"], "download_installed": False}
            manifest["records"].append(record)
            save_manifest(manifest_path, manifest)
            try:
                if args.action == "verify" or path.exists():
                    record["stage"] = "verify_existing"
                    verify(path, dataset, record)
                else:
                    record["stage"] = "download"
                    url = overrides.get(key) or dataset["acquisition"].get("download_url")
                    if url is None:
                        record["instructions"] = dataset["acquisition"]["manual_instructions"]
                        raise ValueError("MANUAL_ACQUISITION_REQUIRED: no verified direct URL")
                    fetch(path, dataset, record, url, args.timeout)
                record.update(status="ok", stage="complete")
            except Exception as error:
                record.update(status="error", error_type=type(error).__name__, reason=str(error))
            record["finished_at_utc"] = now()
            save_manifest(manifest_path, manifest)
        manifest["status"] = "complete" if all(item["status"] == "ok" for item in manifest["records"]) else "failed"
    except BaseException as error:
        manifest.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                        error_type=type(error).__name__, reason=str(error))
    finally:
        manifest["finished_at_utc"] = now()
        save_manifest(manifest_path, manifest)
    print(json.dumps({"manifest": str(manifest_path), "status": manifest["status"],
                      "records": [{"dataset_id": row["dataset_id"], "status": row["status"], "reason": row.get("reason")} for row in manifest["records"]]}))
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
