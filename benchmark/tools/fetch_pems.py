#!/usr/bin/env python3
"""Fetch or verify exact frozen PeMS NPZ bytes, with a new append-only JSONL ledger.

Standard library only. No NPZ parsing, codecs, URL/hash substitution, data bundle,
or replacement of existing files. A verified temporary file is atomically linked
into the caller's directory only after its length and SHA-256 match.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
PREPARATION = ROOT / "benchmark/experiments/pems-values/preparation.json"
PREPARATION_SHA256 = "25382f5ef6de5e91a97e05f720b1b4c1043a38e31622e09e4ecd17d07131178b"
FILENAMES = {"pems03": "PEMS03.npz", "pems04": "pems04.npz", "pems07": "PEMS07.npz", "pems08": "pems08.npz"}
CHUNK = 65536


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Ledger:
    """Reserve a fresh path once; append durable events without truncation or replacement."""
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self.stream = os.fdopen(descriptor, "a", encoding="utf-8")
        self.sequence = 0

    def append(self, event, **values):
        record = {**values, "event": event, "sequence": self.sequence, "at_utc": now()}
        self.stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.sequence += 1

    def close(self):
        self.stream.close()


def frozen_sources(path, binding):
    # This is a small metadata file. Relocation is allowed; changing its bytes is not.
    with path.open("rb") as stream:
        content = stream.read(1024 * 1024 + 1)
    binding.update(preparation_path=str(path.resolve()), preparation_bytes=len(content),
                   preparation_expected_sha256=PREPARATION_SHA256,
                   preparation_observed_sha256=hashlib.sha256(content).hexdigest())
    if len(content) > 1024 * 1024 or binding["preparation_observed_sha256"] != PREPARATION_SHA256:
        raise ValueError("frozen preparation SHA-256 differs; expected identities cannot be replaced")
    preparation = json.loads(content)
    if preparation["schema"] != "tsbench.pems-preparation/1":
        raise ValueError("unknown preparation schema")
    sources = {}
    for source in preparation["sources"]:
        key = source["id"]
        name = Path(source["path"]).name
        if key not in FILENAMES or name != FILENAMES[key] or key in sources:
            raise ValueError("frozen sources must contain the four exact PeMS ids and basenames")
        if type(source["bytes"]) is not int or source["bytes"] <= 0 or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
            raise ValueError("invalid frozen file size/SHA-256")
        if urllib.parse.urlsplit(source["author_raw_url"]).scheme != "https":
            raise ValueError("frozen source must use HTTPS")
        sources[key] = {"id": key, "filename": name, "bytes": source["bytes"], "sha256": source["sha256"],
                        "url": source["author_raw_url"], "author_ref": source["author_ref"],
                        "author_blob_url": source["author_blob_url"], "license": source["license"]}
    if set(sources) != set(FILENAMES):
        raise ValueError("frozen source grid is incomplete")
    return sources


def bounded_identity(stream, source, record, sink=None, progress=None):
    """Read at most expected length + one byte; preserve observed prefix evidence on failure."""
    expected = source["bytes"]
    checksum = hashlib.sha256()
    count, reported = 0, 0
    record.update(streamed_bytes=0, byte_identity_verified=False)
    try:
        while True:
            block = stream.read(min(CHUNK, expected + 1 - count))
            if not block:
                break
            count += len(block)
            checksum.update(block)
            record["streamed_bytes"] = count
            if count > expected:
                raise ValueError("stream exceeds frozen byte length")
            if sink is not None:
                sink.write(block)
            if progress is not None and count - reported >= 8 * 1024 * 1024:
                record["streamed_sha256"] = checksum.hexdigest()
                progress(dict(record))
                reported = count
        if count != expected:
            raise ValueError("stream is shorter than frozen byte length")
        if checksum.hexdigest() != source["sha256"]:
            raise ValueError("stream SHA-256 differs from frozen source")
        record["byte_identity_verified"] = True
    finally:
        record.update(streamed_bytes=count, streamed_sha256=checksum.hexdigest())


def verify_existing(path, source, record):
    info = path.lstat()
    record.update(path=str(path), existing_stat_bytes=info.st_size, path_identity_verified=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("existing source must be a regular file, not a directory or symlink")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("source changed between inspection and open")
        bounded_identity(stream, source, record)
        def identity(value):
            return {"device": value.st_dev, "inode": value.st_ino, "bytes": value.st_size,
                    "mtime_ns": value.st_mtime_ns, "ctime_ns": value.st_ctime_ns}
        record["file_stat_before_read"] = identity(opened)
        try:
            after = os.fstat(stream.fileno())
            record["file_stat_after_read"] = identity(after)
            current = path.lstat()
            record["path_stat_after_read"] = identity(current)
            if (not stat.S_ISREG(current.st_mode) or identity(opened) != identity(after)
                    or identity(opened) != identity(current)):
                raise ValueError("source content or path identity changed during verification")
        except BaseException:
            record["byte_identity_verified"] = False
            raise
        record["path_identity_verified"] = True
    record["verification_scope"] = "exact file bytes and unchanged fd/path metadata through final check; no NPZ parsing or qualification"


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme != "https":
            raise ValueError("HTTPS source redirected outside HTTPS")
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch_exact(path, source, record, timeout, progress=None):
    temporary = None
    record.update(path=str(path), requested_url=source["url"], transfer_started_at_utc=now(),
                  streamed_bytes=0, streamed_sha256=hashlib.sha256(b"").hexdigest(),
                  byte_identity_verified=False, download_installed=False)
    try:
        if urllib.parse.urlsplit(source["url"]).scheme != "https":
            raise ValueError("frozen source must use HTTPS")
        request = urllib.request.Request(source["url"], headers={
            "User-Agent": "tsbench-frozen-pems/1", "Accept-Encoding": "identity"})
        opener = urllib.request.build_opener(HTTPSRedirect())
        with opener.open(request, timeout=timeout) as response:
            record.update(http_status=response.status, final_url=response.url,
                          content_type=response.headers.get("Content-Type"),
                          content_length=response.headers.get("Content-Length"),
                          etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified"))
            if response.status != 200 or urllib.parse.urlsplit(response.url).scheme != "https":
                raise ValueError("download requires HTTP 200 over HTTPS")
            # Same-directory staging makes publication a same-filesystem atomic operation.
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pems-", delete=False) as stream:
                temporary = Path(stream.name)
                bounded_identity(response, source, record, sink=stream, progress=progress)
                stream.flush()
                os.fsync(stream.fileno())
        # Atomic, no-replace publication: a concurrent target creation also fails.
        os.link(temporary, path, follow_symlinks=False)
        record["download_installed"] = True
    except urllib.error.HTTPError as error:
        record.update(http_status=error.code, final_url=error.url,
                      response_body_prefix=error.read(1024).decode("utf-8", errors="replace"))
        raise
    finally:
        record["transfer_finished_at_utc"] = now()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fetch", "verify"))
    parser.add_argument("--directory", type=Path, required=True, help="Caller-selected raw NPZ directory")
    parser.add_argument("--dataset", action="append", choices=tuple(FILENAMES), help="Repeat; default is all four")
    parser.add_argument("--preparation", type=Path, default=PREPARATION, help="Relocated identical frozen preparation only")
    parser.add_argument("--manifest", type=Path, required=True, help="New JSONL path; existing files are never overwritten")
    parser.add_argument("--timeout", type=float, default=30, help="Per-blocking-network-operation timeout in seconds")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    selected = args.dataset or list(FILENAMES)
    if len(set(selected)) != len(selected):
        parser.error("--dataset must not contain duplicates")
    directory = args.directory.expanduser().resolve()
    manifest_path = args.manifest.expanduser().absolute()
    # Resolve only the parent: preserve a final symlink for O_EXCL to reject.
    manifest_path = manifest_path.parent.resolve() / manifest_path.name
    if manifest_path in {directory / name for name in FILENAMES.values()}:
        parser.error("--manifest cannot occupy a source NPZ path")
    try:
        ledger = Ledger(manifest_path)
    except FileExistsError:
        parser.error("--manifest already exists; choose a fresh path to preserve prior evidence")
    status, results, binding = "failed", [], {}
    try:
        ledger.append("acquisition_started", schema="tsbench.pems-acquisition/1", action=args.action,
                      directory=str(directory), selected_dataset_ids=selected, timeout_s=args.timeout,
                      preparation_expected_sha256=PREPARATION_SHA256,
                      script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), python=sys.version,
                      data_parsed=False, codecs_executed=False)
        try:
            sources = frozen_sources(args.preparation.expanduser(), binding)
        except BaseException as error:
            ledger.append("preparation_rejected", **binding, error_type=type(error).__name__, reason=str(error))
            raise
        ledger.append("preparation_verified", **binding)
        if args.action == "fetch":
            directory.mkdir(parents=True, exist_ok=True)
        for key in selected:
            source = sources[key]
            path = directory / source["filename"]
            record = {"dataset_id": key, "status": "running", "path": str(path),
                      "expected_bytes": source["bytes"], "expected_sha256": source["sha256"],
                      "fixed_url": source["url"], "author_ref": source["author_ref"],
                      "author_blob_url": source["author_blob_url"], "license": source["license"],
                      "download_installed": False, "started_at_utc": now()}
            ledger.append("source_started", **record)
            try:
                if args.action == "verify" or os.path.lexists(path):
                    record["stage"] = "verify_existing"
                    verify_existing(path, source, record)
                else:
                    record["stage"] = "download"
                    fetch_exact(path, source, record, args.timeout,
                                progress=lambda snapshot: ledger.append("source_progress", **snapshot))
                record.update(status="ok", stage="complete")
            except BaseException as error:
                record.update(status="error" if isinstance(error, Exception) else "interrupted",
                              error_type=type(error).__name__, reason=str(error))
                if not isinstance(error, Exception):
                    raise
            finally:
                record["finished_at_utc"] = now()
                results.append(dict(record))
                ledger.append("source_finished", **record)
        status = "complete" if all(record["status"] == "ok" for record in results) else "failed"
    except BaseException as error:
        status = "failed" if isinstance(error, Exception) else "interrupted"
        ledger.append("acquisition_error", error_type=type(error).__name__, reason=str(error))
    finally:
        ledger.append("acquisition_finished", status=status, requested_sources=len(selected),
                      completed_sources=sum(record["status"] == "ok" for record in results),
                      failed_sources=sum(record["status"] != "ok" for record in results))
        ledger.close()
    print(json.dumps({"manifest": str(manifest_path), "status": status,
                      "records": [{"dataset_id": record["dataset_id"], "status": record["status"],
                                   "reason": record.get("reason")} for record in results]}))
    return 0 if status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
