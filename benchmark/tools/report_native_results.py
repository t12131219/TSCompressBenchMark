"""Audit and describe the fixed native-default runs without executing a codec.

Run after all timed work finishes. This is a descriptive, same-host report;
neither batches nor layouts are treated as independent dataset populations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
RUNS = (
    ("core", "native-core-real-20261015"),
    ("fresh", "native-core-fresh-20261015"),
    ("api_lossless", "native-api-lossless-20261015"),
    ("api_bounded", "native-api-bounded-20261015"),
    ("api_empirical", "native-api-empirical-20261015"),
    ("object", "object-reference-real-20261015"),
)
_HASHES = {}


def digest(path):
    path = Path(path).resolve()
    if path not in _HASHES:
        h = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                h.update(chunk)
        _HASHES[path] = "sha256:" + h.hexdigest()
    return _HASHES[path]


def identity(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": digest(path), "bytes": path.stat().st_size}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def key(row):
    return row["case_id"], row["session"], row["round"]


def audit(name):
    directory = ROOT / "runs" / name
    manifest = json.loads((directory / "manifest.json").read_text())
    summary = json.loads((directory / "report/summary.json").read_text())
    observations = [json.loads(line) for line in (directory / "observations.jsonl").open()]
    rows = [r for r in observations if r.get("phase") == "measurement" and r.get("event") == "terminal"]
    expected = [key(r) for r in manifest["schedule"]]
    actual = [key(r) for r in rows]
    check(len(set(expected)) == len(expected), f"duplicate schedule: {name}")
    check(Counter(actual) == Counter(expected), f"missing/extra/duplicate terminal slots: {name}")
    check(all(r["attempt"] == 0 and r["run_id"] == manifest["run_id"] for r in rows), f"foreign/retried rows: {name}")
    check(manifest["state"] == "complete" and manifest["execution_source_unchanged"], f"source/state: {name}")
    check(summary["manifest_hash"] == digest(directory / "manifest.json"), f"stale report manifest: {name}")
    check(summary["observations_hash"] == digest(directory / "observations.jsonl"), f"stale report observations: {name}")
    check(not summary["interrupted_jsonl_tail"], f"interrupted JSONL: {name}")
    for source in manifest["source_snapshot"]["files"]:
        check(digest(source["path"]) == source["sha256"], f"changed snapshot: {source['path']}")
    for source in manifest["execution_provenance"]["sources"]:
        check(digest(source["path"]) == source["sha256"], f"changed execution source: {source['path']}")
    check(all(r["status"] == "ok" for r in rows), f"failed formal trial: {name}")
    independent = [r for r in observations if r.get("qualification_kind") == "exact"
                   and r.get("event") == "terminal" and r.get("status") == "ok"]
    check(len(independent) == summary["executable_cases"], f"exact qualification coverage: {name}")
    for row in independent:
        recovery = row["independent_recovery"]
        check(recovery["passed"] and recovery["decoder_process"] and recovery["decoder_returncode"] == 0,
              f"independent recovery: {name}")
        if row.get("boundary", manifest["resolved_config"]["task"]["boundary"]).startswith("native_"):
            check(recovery["decoder_pid"] != row["native_batch"]["process_pid"], f"decoder process identity: {name}")
    native = [r for r in rows if r["boundary"].startswith("native_")]
    products = 0
    for row in native:
        batch = row["native_batch"]
        check(row["loops"] == batch["iterations"] == 8 and batch["warmup_iterations"] == 2, f"loop coverage: {name}")
        check(batch["clock"] == "CLOCK_MONOTONIC" and not batch["python_inside_batch_clock"], f"clock: {name}")
        check(batch["native_loop_batch"] and batch["reset_inside_batch_clock"], f"native/reset: {name}")
        check(row["verification"]["passed"] and row["verification"]["input_unchanged"], f"verification: {name}")
        check(row["verification"]["validated_operations"] == 10, f"operation coverage: {name}")
        check(Counter(p["phase"] for p in row["native_products"]) == {"warmup": 2, "measurement": 8}, f"product coverage: {name}")
        for operation in ("encode", "decode"):
            check(math.isclose(row[operation + "_ns"] * 8, row[operation + "_batch_ns"]), f"normalization: {name}")
        for product in row["native_products"]:
            check(product["verification"]["passed"] and product["verification"]["input_unchanged"], f"product validity: {name}")
            check(digest(product["payload_path"]) == product["payload_hash"], f"payload hash: {name}")
            check(Path(product["payload_path"]).stat().st_size == product["output_bytes"], f"payload size: {name}")
            products += 1
        check(digest(batch["runtime_maps_path"]) == batch["runtime_maps_hash"], f"maps hash: {name}")
        check(row["native_runtime"]["implemented"], f"runtime evidence: {name}")
        for library in row["native_runtime"]["libraries"]:
            check(digest(library["path"]) == library["sha256"], f"runtime library changed: {name}")
        check(row["framework_management_bytes_in_codec_size"] == 0, f"sidecar accounting: {name}")
        check(Path(row["experiment_record_path"]).is_file(), f"missing experiment record: {name}")
        if row["codec_complete_bytes"] is None:
            check(row["bits_per_value"] is None and row["stored_bytes"] is None and row["codec_complete_bytes_null_reason"], f"unknown-size fallback: {name}")
    input_ids = defaultdict(set)
    for row in rows:
        if row["boundary"] == "native_core":
            input_ids[row["case_id"].split("/")[0]].add(row["codec_input_id"])
            check(row["raw_bytes"] == row["codec_input_bytes"] == row["value_count"] * 8 and row["timestamp_count"] == 0, f"logical denominator: {name}")
    check(all(len(ids) == 1 for ids in input_ids.values()), f"cross-codec input differs: {name}")
    builds = {}
    for case in manifest["cases"]:
        for build in case.get("build_evidence", []):
            if build.get("build_id"):
                if build.get("binary"):
                    check(digest(build["binary"]) == build["binary_hash"], f"build binary changed: {name}")
                builds[build["build_id"]] = {k: build[k] for k in ("build_id", "binary", "binary_hash", "compiler", "command") if k in build}
    record = {
        "run": str(directory.relative_to(ROOT)), "run_id": manifest["run_id"],
        "source_id": manifest["execution_provenance"]["source_id"],
        "source_snapshot_id": manifest["source_snapshot"]["snapshot_id"],
        "state": manifest["state"], "execution_source_unchanged": True,
        "requested_cases": summary["requested_cases"], "admission_counts": summary["admission_counts"],
        "planned_trials": len(expected), "terminal_status_counts": dict(Counter(r["status"] for r in rows)),
        "complete_cases": sum(c["complete_case"] for c in summary["cases"]),
        "native_trials": len(native), "verified_product_pairs_in_formal_trials": products,
        "independent_exact_recoveries": len(independent),
        "unknown_complete_size_cases": sum(c["complete_case"] and c["codec_complete_bytes_median"] is None for c in summary["cases"]) if native else None,
        "qualification_counts": dict(Counter(q["kind"] + "/" + q["status"] for q in manifest["qualification"])),
        "schedule_integrity": {"complete": True, "duplicate_slots": 0, "missing_slots": 0, "extra_slots": 0, "retries": 0},
        "cross_codec_input_ids": {dataset: sorted(ids) for dataset, ids in input_ids.items()},
        "files": [identity(directory / p) for p in ("manifest.json", "observations.jsonl", "report/summary.json", "report/summary.csv", "report/README.md")],
        "builds": list(builds.values()),
    }
    return record, summary, manifest


def number(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def rate(case, operation):
    times = case[operation + "_ns"]
    if not times["median"]:
        return "—"
    scale = case["raw_bytes"] * 1e9 / 2**20
    return f"{scale/times['median']:.2f} [{scale/times['q3']:.2f}, {scale/times['q1']:.2f}]"


def table(cases, native=True):
    lines = ["| 对象／方法 | 完整输出 bytes | 压缩倍数 | bits/value | 编码 MiB/s [Q1, Q3] | 解码 MiB/s [Q1, Q3] |",
             "|---|---:|---:|---:|---:|---:|"]
    for c in cases:
        if not c["complete_case"]:
            continue
        size = c["codec_complete_bytes_median"] if native else c["stored_bytes"]["median"]
        lines.append(f"| {c['dataset_id']} / {c['codec']} | {number(size,0)} | {number(c['compression_ratio'])} | {number(c['bits_per_value_median'])} | {rate(c,'encode')} | {rate(c,'decode')} |")
    return "\n".join(lines)


def write_csv(path, summaries):
    columns = ["run", "case_id", "codec", "dataset_id", "profile_id", "boundary", "lifecycle", "cache_policy", "case_status", "reason", "raw_bytes", "ok_primary_trials", "planned_trials", "codec_complete_bytes_median", "native_output_bytes_median", "object_wire_bytes_median", "codec_complete_bytes_null_reason", "compression_ratio", "bits_per_value_median", "encode_MiB_s", "decode_MiB_s", "encode_ns_median", "encode_ns_q1", "encode_ns_q3", "decode_ns_median", "decode_ns_q1", "decode_ns_q3", "max_abs_worst", "rmse_worst", "nrmse_worst"]
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for label, summary in summaries:
            for case in summary["cases"]:
                row = {k: case.get(k) for k in columns}
                row["run"] = label
                row["object_wire_bytes_median"] = case["stored_bytes"]["median"] if case["boundary"] == "object_memory" else None
                for operation in ("encode", "decode"):
                    for stat in ("median", "q1", "q3"):
                        row[operation + "_ns_" + stat] = case[operation + "_ns"][stat]
                for quality in ("max_abs", "rmse", "nrmse"):
                    row[quality + "_worst"] = case["quality"][quality]["max"]
                writer.writerow(row)


def plot(directory, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    datasets = ["etth1-values-c", "etth1-values-f", "weather-values-c", "weather-values-f", "ili-values-c"]
    labels = ["ETTh1 C", "ETTh1 F", "Weather C", "Weather F", "ILI C"]
    codecs = ["raw-store", "lz4-frame", "snappy-raw", "zstd-frame"]
    colors = ["#8995a5", "#0072b2", "#e69f00", "#009e73"]
    lookup = {(c["dataset_id"], c["codec"]): c for c in summary["cases"]}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none",
                         "svg.hashsalt": "tsbench-native-results"})
    fig, axes = plt.subplots(1, 3, figsize=(13.8, 5.2), layout="constrained")
    x = np.arange(len(datasets)); width = .19
    for i, (codec, color) in enumerate(zip(codecs, colors)):
        cases = [lookup[d, codec] for d in datasets]
        at = x + (i - 1.5) * width
        axes[0].bar(at, [c["compression_ratio"] for c in cases], width=width, color=color, label=codec)
        for ax, operation in zip(axes[1:], ("encode", "decode")):
            scales = np.array([c["raw_bytes"] * 1e9 / 2**20 for c in cases])
            med = scales / np.array([c[operation + "_ns"]["median"] for c in cases])
            low = scales / np.array([c[operation + "_ns"]["q3"] for c in cases])
            high = scales / np.array([c[operation + "_ns"]["q1"] for c in cases])
            ax.bar(at, med, width=width, color=color, yerr=[med-low, high-med], capsize=2,
                   error_kw={"elinewidth": .8, "capthick": .8})
    for ax, title in zip(axes, ("Complete codec output", "Native encode", "Native decode")):
        ax.set_title(title, pad=10)
        ax.set_xticks(x, labels, rotation=28, ha="right")
        ax.grid(axis="y", alpha=.22); ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Compression ratio (raw / complete codec bytes)")
    for ax in axes[1:]:
        ax.set_yscale("log"); ax.set_ylabel("MiB/s (log scale)")
    fig.suptitle("Direct codec APIs · prepared contexts/buffers · natural cache", fontsize=14)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="outside lower center", ncols=4,
               title="14 batches per case · 8 operations per batch · whiskers: duration Q1–Q3 inverted", frameon=False)
    fig.savefig(directory / "native_core.png", dpi=180)
    fig.savefig(directory / "native_core.svg", metadata={"Date": None})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()
    directory = ROOT / "docs/native_results"; directory.mkdir(exist_ok=True)
    results = {label: audit(name) for label, name in RUNS}
    records = [value[0] for value in results.values()]
    check(len({r["source_id"] for r in records}) == 1, "mixed execution sources")
    totals = {"requested_cases": sum(r["requested_cases"] for r in records),
              "ready_cases": sum(r["complete_cases"] for r in records),
              "unsupported_cases": sum(r["admission_counts"].get("unsupported", 0) for r in records),
              "ok_trials": sum(r["terminal_status_counts"]["ok"] for r in records),
              "native_trials": sum(r["native_trials"] for r in records),
              "verified_product_pairs_in_formal_trials": sum(r["verified_product_pairs_in_formal_trials"] for r in records)}
    for label, native in (("core", True), ("fresh", True), ("object", False)):
        (directory / (label + "_table.md")).write_text(table(results[label][1]["cases"], native) + "\n")
    write_csv(directory / "primary.csv", [("core", results["core"][1])])
    write_csv(directory / "auxiliary.csv", [(label, data[1]) for label, data in results.items() if label != "core"])
    if not args.no_plot:
        plot(directory, results["core"][1])
    junit = ET.parse(ROOT / "build/verification/native-default/junit.xml").getroot()
    suites = [junit] if junit.tag == "testsuite" else list(junit)
    evidence = {
        "schema": "tsbench.native-evidence/1", "date": "2026-10-15",
        "scope": "Same-host descriptive native_core/prepared primary; fresh native_core, complete native_api and object_memory auxiliary. Unknown complete codec sizes remain null. No cross-boundary ranking or population inference.",
        "source_id": records[0]["source_id"], "totals": totals, "runs": records,
        "audit": {"schedule_and_terminal_identity": True, "all_snapshots_and_current_execution_sources_match": True,
                  "all_native_payload_hashes_and_sizes_match": True, "all_native_operations_validate": True,
                  "all_runtime_maps_hashes_match": True, "unknown_size_never_falls_back": True,
                  "core_cross_codec_input_identity_matches": True,
                  "independent_exact_recoveries_validate": True,
                  "scope": "Audits saved operation validation, artifacts and identities; does not execute codecs or reconstruct transient restored buffers."},
        "tests": [identity(ROOT / "build/verification/native-default" / p) for p in ("pytest.log", "junit.xml")],
        "test_totals": {field: sum(int(suite.get(field, "0")) for suite in suites)
                        for field in ("tests", "errors", "failures", "skipped")},
        "serial_measurements": identity(ROOT / "build/verification/native-default/serial_measurements.json"),
        "driver_build_record": identity(ROOT / "build/verification/native-default/build.json"),
        "analysis_source": identity(__file__),
        "experiment_design": [identity(ROOT / "benchmark/experiments/native" / p)
                              for p in ("design.json", "core.toml", "fresh.toml", "api_lossless.toml", "api_bounded.toml", "api_empirical.toml", "object.toml")],
        "design_documents": [identity(ROOT / p) for p in ("TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md", "README.md", "docs/implementation.md", "docs/diagrams/README.md", "docs/diagrams/architecture.svg", "docs/diagrams/architecture.png", "docs/diagrams/workflow.svg", "docs/diagrams/workflow.png", "docs/research/native_reference_notes.md")],
        "analysis_outputs": [identity(p) for p in sorted(directory.iterdir()) if p.name in {"README.md", "audit.md", "primary.csv", "auxiliary.csv", "core_table.md", "fresh_table.md", "object_table.md", "native_core.png", "native_core.svg"}],
    }
    (ROOT / "docs/native_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(totals, ensure_ascii=False))


if __name__ == "__main__":
    main()
