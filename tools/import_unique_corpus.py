#!/usr/bin/env python3
"""Rebuild the selected corpus from the local Unique mirror into an empty output tree."""
import argparse
import csv
from datetime import datetime
from decimal import Decimal
import gzip
import hashlib
import io
import re
from itertools import groupby, zip_longest
from pathlib import Path
import shutil
import sys
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import ContractError, canonical_bytes, digest, load_json, local_file, require, verify_asset
from tsbench.corpus import (EXCHANGE_COLUMNS, EXCHANGE_LABELS, MPI_COLUMNS, RELEASES, TRAFFIC_COLUMNS,
                            TRAFFIC_LABELS, UCI_CHANNELS, UCI_COLUMNS, audit_asset, intake_assets)
from tsbench.contracts import load_contract


def zip_member(directory, item):
    path = verify_asset(directory, {"path": item["archive"], "sha256": item["sha256"]})
    with ZipFile(path) as archive, archive.open(item["member"]) as member:
        require(hashlib.file_digest(member, "sha256").hexdigest() == item["member_sha256"], "upstream member mismatch")
    return path


def source_members(dataset_dir, spec):
    for ref in spec["unique_members"]:
        dirname, _, relative = ref["path"].partition("/")
        require(dirname == "datasets", "unexpected Unique source directory")
        path = verify_asset(dataset_dir, {**ref, "path": relative})
        require(path.stat().st_size == ref["bytes"], "Unique member length mismatch")
        yield path


def _audit_uci(upstream, spec, parts, header):
    item, = spec["upstream"]
    path = zip_member(upstream, item)
    expected = {p.stem[-4:].encode(): lock["sha256"] for p, lock in zip(parts, spec["unique_members"], strict=True)}
    verified = set()
    with ZipFile(path) as archive, archive.open(item["member"]) as member:
        require(member.readline() == header, "UCI release header differs from Unique")
        for year, rows in groupby(member, key=lambda row: row[1:5]):
            if year not in expected:
                continue  # the release includes the right-end row at 2015-01-01
            require(year not in verified, "unexpected non-contiguous UCI year")
            sha = hashlib.sha256(header)
            for row in rows:
                sha.update(row)
            require(sha.hexdigest() == expected[year], f"Unique UCI year is not a byte-exact partition: {year!r}")
            verified.add(year)
    require(verified == expected.keys(), "missing official UCI year")


def electricity(dataset_dir, upstream, spec, out):
    parts = list(source_members(dataset_dir, spec))
    with parts[0].open("rb") as src:
        header = src.readline()
    require(header.rstrip(b"\r\n").split(b";") == [b'""', *(f'"MT_{i:03}"'.encode() for i in range(1, 371))],
            "unexpected electricity timestamp label or column order")
    if upstream is not None:
        _audit_uci(upstream, spec, parts, header)
    cor_header = b';'.join([b'timestamp', *(col.encode() for col, _ in UCI_COLUMNS)]) + b'\n'
    out.write(cor_header)
    for local in parts:
        with local.open("rb") as src:
            require(src.readline() == header, "Unique electricity header mismatch")
            for row in src:
                fields = row.rstrip(b"\r\n").split(b";")
                require(len(fields) == 371 and fields[0].startswith(b'"') and fields[0].endswith(b'"'), "bad UCI row")
                out.write(b';'.join([fields[0][1:-1], *(fields[j] for j in UCI_CHANNELS)]) + b'\n')


def _mpi_rows(upstream, items):
    for item in items:
        path = zip_member(upstream, item)
        with ZipFile(path) as archive, archive.open(item["member"]) as raw:
            src = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            rows = csv.reader(src, strict=True)
            header = next(rows)
            require(len(header) == 22 and header[0] == "Date Time" and header[-1] == "CO2 (ppm)", "unexpected MPI rooftop header")
            for row in rows:
                require(len(row) == 22, "unexpected MPI rooftop row width")
                stamp = datetime.strptime(row[0].strip(), "%d.%m.%Y %H:%M:%S").isoformat(sep=" ")
                yield stamp, tuple(map(Decimal, row[1:]))


def weather(dataset_dir, upstream, spec, out):
    path, = source_members(dataset_dir, spec)
    out.write((",".join(["timestamp", *(col for col, _ in MPI_COLUMNS)]) + "\n").encode("ascii"))
    with path.open(encoding="utf-8", newline="") as src:
        rows = csv.reader(src, strict=True)
        header = next(rows)
        require(len(header) == 22 and header[0] == "date" and header[-1] == "OT", "unexpected Unique weather header")
        if upstream is None:
            for row in rows:
                require(len(row) == 22, "unexpected Unique weather row width")
                out.write((",".join(row) + "\n").encode("ascii"))
        else:
            official_rows = _mpi_rows(upstream, spec["upstream"])
            try:
                for i, (row, official) in enumerate(zip_longest(rows, official_rows), 1):
                    require(row is not None and official is not None and len(row) == 22 and
                            (row[0], tuple(map(Decimal, row[1:]))) == official,
                            f"Unique weather differs from official rooftop series at row {i}")
                    out.write((",".join(row) + "\n").encode("ascii"))
            finally:
                official_rows.close()


_DATE = re.compile(rb"([0-9]{4})/([0-9]{1,2})/([0-9]{1,2}) 0:00")


def _source_csv_rows(path, line_limit):
    """Read the locked, unquoted Forecast_TS CSV dialect with bounded lines."""
    with path.open("rb") as stream:
        while raw := stream.readline(line_limit + 1):
            require(len(raw) <= line_limit, "Forecast_TS line exceeds source bound")
            # The exchange file's last record is not newline-terminated.
            # A short readline without LF is the true EOF, not a discarded row.
            row = raw[:-1].removesuffix(b"\r") if raw.endswith(b"\n") else raw
            require(row and row.isascii() and b'"' not in row and b"\r" not in row,
                    "invalid Forecast_TS row dialect")
            yield row.split(b",")


def forecast(dataset_dir, upstream, spec, out):
    require(upstream is None, "Forecast_TS import is local-only")
    path, = source_members(dataset_dir, spec)
    traffic = spec["id"] == "unique-forecast-traffic"
    labels = [*(str(i) for i in range(861 if traffic else 7)), "OT"]
    columns, projection = (TRAFFIC_COLUMNS, TRAFFIC_LABELS) if traffic else (EXCHANGE_COLUMNS, EXCHANGE_LABELS)
    positions = tuple(labels.index(label) + 1 for label in projection)
    with_rows = _source_csv_rows(path, 16384 if traffic else 512)
    try:
        require(next(with_rows, None) == [b"date", *(label.encode("ascii") for label in labels)],
                "unexpected Forecast_TS header or column order")
        out.write((",".join(["timestamp", *(col for col, _ in columns)]) + "\n").encode("ascii"))
        for number, row in enumerate(with_rows, 1):
            require(len(row) == len(labels) + 1, f"Forecast_TS row {number}: incorrect width")
            stamp = row[0]
            if not traffic:
                match = _DATE.fullmatch(stamp)
                require(match is not None, f"Forecast_TS row {number}: incorrect exchange date label")
                year, month, day = match.groups()
                stamp = b"-".join((year, month.zfill(2), day.zfill(2))) + b" 00:00:00"
            # Canonical audit validates calendar, chronological partitions and
            # all selected numeric fields without modifying decimal spellings.
            out.write(b",".join([stamp, *(row[i] for i in positions)]) + b"\n")
    finally:
        with_rows.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    source = p.add_mutually_exclusive_group()
    source.add_argument("--from-unique", type=Path, help="a Unique checkout instead of the local mirror")
    source.add_argument("--from-datasets", type=Path, help="an alternative directory holding the raw corpus")
    p.add_argument("--version", type=int, choices=(1, 2), default=2, help="frozen Unique corpus version (default 2)")
    p.add_argument("--upstream-dir", type=Path, help="optional historical v1 comparison; not used for v2")
    p.add_argument("--out", type=Path, required=True, help="existing empty staging directory, never the live project")
    args = p.parse_args()
    dataset_dir = args.from_datasets or (args.from_unique / "datasets" if args.from_unique else ROOT / "datasets/raw/unique")
    try:
        out = args.out.resolve(strict=True)
        require(out.is_dir() and not any(out.iterdir()), "expected an empty output directory")
        require(args.version == 1 or args.upstream_dir is None, "upstream comparison applies to historical v1 only")
        manifest, intake = RELEASES[args.version]
        ref = {"path": intake, "sha256": digest(local_file(ROOT, intake))}
        entries, metadata = intake_assets(ROOT, ref)
        for rel in metadata:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_file(ROOT, rel), out / rel)
        result = {"schema": "bmk.real-corpus/1", "id": f"first_batch_real_v{args.version}", "state": "partial_scope",
                  "intake": ref, "datasets": []}
        methods = {"uci-electricity-pt": electricity, "mpi-beutenberg-weather": weather,
                   "unique-forecast-traffic": forecast, "unique-forecast-exchange": forecast}
        for entry in entries:
            path = out / entry["asset_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as dest, gzip.GzipFile(filename="", fileobj=dest, mode="wb", mtime=0, compresslevel=6) as stream:
                methods[entry["id"]](dataset_dir, args.upstream_dir, entry, stream)
            if relative := entry.get("original_copy"):
                original, = source_members(dataset_dir, entry)
                dest = out / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, dest)
            dataset = {key: entry[key] for key in ("id", "source_cluster", "domain", "split_at", "header_profile", "nominal_step_seconds")}
            dataset["asset"] = {"path": entry["asset_path"], "sha256": digest(path), "bytes": path.stat().st_size}
            dataset["audit"] = audit_asset(path, dataset)
            result["datasets"].append(dataset)
        load_contract(ROOT, "corpus").validate(result, manifest)
        with (out / manifest).open("xb") as stream:
            stream.write(canonical_bytes(result) + b"\n")
    except (ContractError, OSError, BadZipFile, KeyError, ValueError, ArithmeticError, csv.Error) as exc:
        print(f"corpus import rejected: {exc}", file=sys.stderr)
        return 2
    print(f"Staged {len(result['datasets'])} datasets from frozen local bytes at {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
