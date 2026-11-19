"""Recheck retained native-access observations without reopening source data or DSOs."""
from pathlib import Path

from ..assets import canonical_bytes, content_id, load_json, local_file, require, verify_asset
from ..planner.titchy_access import logical_result_bits
from .probe_build import verify_probe_build_lock

PLUGIN = "titchy-batch"


def _read_budget(record, limit, backing_bytes, label, result_bits=None):
    fields = {"calls", "requested_bytes", "successful_bytes"}
    if result_bits is not None:
        fields.add("result_logical_bits")
    require(isinstance(record, dict) and record.keys() == fields, f"invalid Titchy logical ledger: {label}")
    calls = record["calls"]
    require(isinstance(calls, list) and calls and all(isinstance(c, list) and len(c) == 3 and
            type(c[0]) is int and type(c[1]) is int and 0 <= c[0] <= backing_bytes and
            0 < c[1] <= backing_bytes - c[0] and c[2] is True for c in calls), f"invalid Titchy read call: {label}")
    length = sum(c[1] for c in calls)
    require(all(type(record[k]) is int and record[k] == length for k in ("requested_bytes", "successful_bytes")) and
            0 < length <= limit and length < backing_bytes,
            f"Titchy logical-read budget or accounting differs: {label}")
    if result_bits is not None:
        require(type(record["result_logical_bits"]) is int and record["result_logical_bits"] == result_bits,
                f"Titchy result length differs: {label}")


def verify_titchy_access(bundle: dict, build: dict, driver_sha256: str, out: Path,
                          *, sealed_paths: set[str] | None = None) -> None:
    require(bundle["bundle_id"] == content_id({k: v for k, v in bundle.items() if k != "bundle_id"}),
            "Titchy access bundle identity differs")
    report_path, backing_path = bundle["evidence_path"], bundle["backing_path"]
    require(sealed_paths is None or {report_path, backing_path} <= sealed_paths, "Titchy access evidence is not sealed")
    doc = load_json(local_file(out, report_path))
    require(isinstance(doc, dict) and doc.get("schema") == "bmk.m0-titchy-control/2" and
            doc.get("formal_qualification") is False and doc.get("formal_performance") is False and
            doc.get("definitions") == driver_sha256 and doc.get("config_id") == bundle["config_id"] and
            doc.get("access_bundle_id") == bundle["bundle_id"] and
            doc.get("access_case_ids") == [c["case_id"] for c in bundle["cases"]],
            "Titchy report is not bound to frozen cases and driver")
    verify_probe_build_lock(doc.get("build"), build, PLUGIN, dependency_count=1)
    oracle, budget, stateless = bundle["cases"]
    criteria = budget["criteria"]
    limits, request = criteria["byte_limits"], criteria["request"]
    result = oracle["criteria"]["expected"]
    access = doc.get("access")
    require(isinstance(access, dict) and access.get("backing_path") == backing_path and
            access.get("counts_scope") == criteria["scope"], "Titchy access backing path or accounting scope differs")
    size, sha = access.get("backing_bytes"), access.get("backing_sha256")
    require(type(size) is int and 38 < size <= limits["max_backing_bytes"] and isinstance(sha, str),
            "invalid Titchy backing size or digest")
    file = verify_asset(out, {"path": backing_path, "sha256": sha})
    require(file.stat().st_size == size, "Titchy backing size differs")
    with file.open("rb") as stream:
        header = stream.read(38)
    splits = int.from_bytes(header[34:38], "little")
    require(header[:6] == b"TCHY\x02\x40" and int.from_bytes(header[22:30], "little") == oracle["window"]["count"] and
            splits == 2 and type(access.get("splits")) is int and access["splits"] == splits,
            "wrong Titchy backing format or sample/split count")
    batch = doc.get("batch")
    require(isinstance(batch, list), "missing Titchy batch input identity")
    input_rows = [r for r in batch if isinstance(r, dict) and r.get("case") == "traffic-split-and-tail"]
    expected_batch = {"window": oracle["window"], "transform": oracle["transform"], "input_sha256": oracle["input_sha256"],
                      "count": oracle["window"]["count"], "native_bytes": size, "native_sha256": sha, "bit_exact": True}
    require(len(input_rows) == 1 and all(canonical_bytes(input_rows[0].get(k)) == canonical_bytes(v)
            for k, v in expected_batch.items()), "Titchy backing is not bound to frozen batch input")
    require(canonical_bytes(access.get("read_at_results")) == canonical_bytes([result] * criteria["request_passes"]) and
            canonical_bytes(access.get("detached_file_results")) == canonical_bytes(result) and
            access.get("detached_file_queries_bit_exact") is True, "Titchy loaded reader results differ from frozen oracle")
    batch_range = access.get("stateless_range")
    require(isinstance(batch_range, dict) and batch_range.get("bit_exact") is True and
            canonical_bytes(batch_range.get("result")) == canonical_bytes(stateless["criteria"]["expected"]),
            "Titchy stateless range differs from frozen oracle")
    opened = access.get("open_read_at")
    _read_budget(opened, limits["open"], size, "open")
    require(opened["calls"] == [[0, 38, True], [38, 24 * splits, True]], "Titchy open reads differ from header and index")
    bits = logical_result_bits(request)
    first, second = (access.get(k) for k in ("query_read_at", "repeated_query_read_at"))
    for observed in (first, second):
        require(isinstance(observed, dict) and observed.keys() == bits.keys(), "Titchy query ledger closure differs")
        for label, result_bits in bits.items():
            _read_budget(observed[label], limits["bit" if label.startswith("bit-") else label], size, label, result_bits)
    require(first == second, "Titchy repeated logical-read accounting differs")
