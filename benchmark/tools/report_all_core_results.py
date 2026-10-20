"""Audit the frozen all-codec native design and describe its saved results.

Run only after native measurements finish. This tool never builds, qualifies,
decodes, or times a codec. Every metric is recomputed from saved batch records;
an audit failure leaves existing reports untouched, including native_results.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUPPLEMENT = ROOT / "benchmark/experiments/native-neural/design.json"
sys.path.insert(0, str(ROOT / "benchmark/src"))

from tsbench.config import load as load_config
from tsbench.records import read_jsonl, stable_hash
from tsbench.registry import Registry
from tsbench.trial_analysis import scheduled_rows


def check(condition, message):
    if not condition:
        raise ValueError(message)


def absolute(path):
    path = Path(path).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def prefixed(value):
    return value if value.startswith("sha256:") else "sha256:" + value


class Auditor:
    def __init__(self):
        self.hashes = {}
        self.builds = {}
        self.files = {}
        self.cohorts = defaultdict(set)
        self.products = Counter()
        self.qualification_cache = {}
        self.neural_sources = {}

    def digest(self, path):
        path = absolute(path)
        if path not in self.hashes:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            self.hashes[path] = "sha256:" + digest.hexdigest()
        return self.hashes[path]

    def identity(self, path):
        path = absolute(path)
        label = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        record = {"path": label, "sha256": self.digest(path), "bytes": path.stat().st_size}
        self.files[label] = record
        return record

    def hashed_file(self, path, expected):
        check(self.digest(path) == prefixed(expected), f"file changed: {path}")
        return self.identity(path)

    def source_files(self, records):
        for record in records:
            self.hashed_file(record["path"], record["sha256"])

    def build(self, build):
        identity = build["build_id"]
        fingerprint = stable_hash(build)
        if identity in self.builds:
            check(self.builds[identity]["evidence_id"] == fingerprint,
                  f"conflicting build evidence: {identity}")
            return
        if build.get("kind") == "native_driver":
            self.hashed_file(build["binary"], build["binary_hash"])
            self.source_files(build["sources"])
            self.source_files(build["compiled_dependencies"])
            self.hashed_file(build["recipe"]["compiler"], build["recipe"]["compiler_hash"])
            check(stable_hash({"recipe": build["recipe"], "compiled_dependencies": build["compiled_dependencies"]}) == identity,
                  f"driver build identity: {identity}")
            if build.get("record_path"):
                self.hashed_file(build["record_path"], build["record_hash"])
                saved = json.loads(absolute(build["record_path"]).read_bytes())
                check(all(saved.get(k) == v for k, v in build.items()
                          if k not in {"kind", "record_path", "record_hash"}),
                      f"driver build record differs: {identity}")
            record = {k: build[k] for k in ("kind", "build_id", "binary", "binary_hash",
                                           "record_path", "record_hash", "recipe") if k in build}
        else:
            self.hashed_file(build["path"], build["hash"])
            saved = json.loads(absolute(build["path"]).read_bytes())
            check(saved.get("status") == "ok", f"codec build failed: {identity}")
            for field in ("build_id", "artifact_sha256", "compilers", "commands", "profile"):
                check(saved.get(field) == build.get(field), f"codec build {field}: {identity}")
            check(saved.get("identity_sha256") == build["source_identity"],
                  f"codec source identity: {identity}")
            self.hashed_file(saved["artifact"], saved["artifact_sha256"])
            for field in ("sources", "compiled_source_closure", "toolchain_files", "runtime_dependencies"):
                self.source_files(saved.get(field, []))
            record = dict(build)
        self.builds[identity] = {**record, "evidence_id": fingerprint}

    def runtime(self, runtime):
        check(runtime.get("implemented") is True and runtime.get("libraries"),
              "missing actual native runtime evidence")
        self.source_files(runtime["libraries"])

    def neural_path(self, case, request):
        """Describe deterministic source branches; these are not runtime counters."""
        codec = case["codec"]
        if codec not in {"deepzip", "dzip"}:
            return None
        count = request["value_count"]
        check(request["kind"] == "values" and request["dtype"] == "|u1"
              and request["shape"] == [count], f"neural symbol geometry: {case['case_id']}")
        base = ROOT / "adapters/completed_rewrites"
        if codec not in self.neural_sources:
            source = base / "vendor" / codec / "src" / ("deepzip.cpp" if codec == "deepzip" else "codec.cpp")
            compact = "".join(source.read_text().split())
            anchors = (("for(std::size_tj=64;j<length;++j)", "model.predict(contexts,backend)",
                        "length=input.size()/config.lanes") if codec == "deepzip" else
                       ("for(std::size_ti=64;i<symbols.size();++i)", "for(std::size_ti=64;i<length;++i)",
                        "predicted%128==0", "row=offset-128;row<offset;++row", "network.train(contexts,labels)"))
            check(all(anchor in compact for anchor in anchors), f"neural branch formula requires source review: {source}")
            sources = [source, base / "native/binding.cpp"]
            if codec == "dzip":
                optimizer = base / "vendor/dzip/src/nn.cpp"
                check("++impl_->optimizer_steps;" in optimizer.read_text(), "DZip Adam-step formula requires source review")
                sources.append(optimizer)
            self.neural_sources[codec] = [self.identity(p) for p in sources]
        parameters = case["method"]["params"]
        if codec == "deepzip":
            lanes = parameters["lanes"]
            length, tail = divmod(count, lanes)
            uniform = lanes * min(64, length) + min(64, tail)
            predict = max(0, length - 64) + max(0, tail - 64)
            train = 0
            mode = parameters["model_key"]
            formula = "lanes*min(64,N//lanes)+min(64,N%lanes) uniform symbols; max(N//lanes-64,0)+max(N%lanes-64,0) batched predict calls"
        else:
            mode = parameters["mode"]
            uniform, predict = min(64, count), max(0, count - 64)
            train = predict // 128 if mode == "COMBINED" else 0
            formula = "min(N,64) uniform symbols; max(N-64,0) predict calls; COMBINED trains after each 128 predictions on 128 windows and advances Adam once"
        counts = {"uniform_symbols": uniform, "predict_calls": predict,
                  "online_train_batches": train, "online_train_batch_windows": train * 128,
                  "adam_steps": train, "post_update_predict_calls": max(0, predict - 128) if train else 0}
        if "mode" in request:
            check(request["mode"] == mode, f"frozen neural mode: {case['case_id']}")
        if "source_derived_operation_counts" in request:
            declared = request["source_derived_operation_counts"]
            check(all(declared.get(k) == v for k, v in counts.items()), f"frozen neural path counts: {case['case_id']}")
            check(declared.get("scope"), f"missing static neural-count scope: {case['case_id']}")
        return {"mode": mode, "input_symbols": count, "counts": counts,
                "scope": "per encode and per decode; derived from source, not runtime counters",
                "formula": formula, "post_update_scope": "predictions after the first online update",
                "sources": self.neural_sources[codec],
                "path": "uniform short-stream contract only" if not predict else "prediction and online update" if train else "prediction without online update"}

    def native(self, row, case, request, execution, *, independent=False):
        label = case["case_id"]
        check(row.get("boundary") == "native_core" and row.get("lifecycle") == request["lifecycle"]
              and row.get("cache_policy") == "natural", f"native scope: {label}")
        check(row.get("measurement_scope") == "direct codec API", f"indirect measurement: {label}")
        check(row.get("implementation_id") == case["implementation_id"], f"implementation changed: {label}")
        loops, warmup = execution["native_loops"], execution["native_warmup_loops"]
        batch = row["native_batch"]
        check(row["loops"] == batch["iterations"] == loops
              and batch["warmup_iterations"] == warmup, f"batch iteration coverage: {label}")
        check(batch.get("schema") == "tsbench.native-batch/1" and batch.get("status") == "ok"
              and batch.get("native_status") == 0 and batch.get("stage") == "complete",
              f"driver batch status: {label}")
        check(batch.get("measurement_boundary") == "native_core" and batch.get("mode") == request["lifecycle"]
              and not batch.get("probe_only") and not batch.get("decode_only"), f"driver boundary: {label}")
        check(batch.get("clock") == "CLOCK_MONOTONIC" and batch.get("clock_resolution_ns", 0) > 0
              and batch.get("python_inside_batch_clock") is False and batch.get("native_loop_batch") is True,
              f"native clocks: {label}")
        check(batch.get("reset_inside_batch_clock") is True
              and batch.get("encode_batch_clock_count") == batch.get("decode_batch_clock_count") == 1
              and batch.get("batch_clock_count_per_operation") == 1,
              f"native batch/reset clock coverage: {label}")
        check(batch.get("source_and_stream_admission_outside_main_clocks") is True
              and batch.get("quality_checked_by_driver") is False
              and batch.get("retained_output_release_outside_timing") is True,
              f"validation/release timing boundary: {label}")
        check(batch.get("caller_pages_pretouched") is (request["lifecycle"] == "prepared"),
              f"caller lifecycle: {label}")
        check(batch.get("native_api_internal_work_included") is False
              and batch.get("abi") in {"raw", "zstd", "lz4", "snappy", "core"}, f"ABI envelope: {label}")
        check(batch.get("codec") == case["codec"], f"driver codec: {label}")
        check(row.get("raw_bytes") == row.get("codec_input_bytes") == batch.get("input_bytes") == request["raw_bytes"],
              f"effective byte denominator: {label}")
        check(row.get("value_count") == request["value_count"]
              and row.get("timestamp_count") == request["timestamp_count"], f"logical count denominator: {label}")
        check(row.get("transform_id") == "identity", f"undeclared transform: {label}")
        native_input = row["native_input"]
        expected_components = {case["object_schema"].get("roles", {}).get(n, n): item
                               for n, item in case["components"].items()}
        check(native_input.get("logical_components") == expected_components
              and native_input.get("nbytes") == request["raw_bytes"]
              and native_input.get("logical_layout") == request["order"], f"typed physical input: {label}")
        input_id = stable_hash({k: native_input[k] for k in ("content_sha256", "nbytes", "logical_dtype",
                                                            "logical_shape", "logical_layout", "logical_components")})
        check(input_id == row.get("codec_input_id"), f"native input identity: {label}")
        cohort = stable_hash({"object_id": request["object_id"], "kind": request["kind"],
                              "dtype": request["dtype"], "shape": request["shape"],
                              "order": request["order"], "components": expected_components})
        self.cohorts[cohort].add(input_id)
        check(row.get("framework_management_bytes_in_codec_size") == 0
              and row.get("codec_complete_bytes_null_reason") is None
              and case["capability"].get("codec_complete_output_reviewed") is True,
              f"complete output accounting: {label}")
        verification = row["verification"]
        check(verification.get("passed") is True and verification.get("input_unchanged") is True
              and verification.get("validated_operations") == loops + warmup, f"whole-batch verification: {label}")
        products = row["native_products"]
        expected = {(phase, i) for phase, count in (("warmup", warmup), ("measurement", loops)) for i in range(count)}
        check(len(products) == len(expected) and {(p["phase"], p["index"]) for p in products} == expected,
              f"retained product coverage: {label}")
        grouped = {}
        for phase, count in (("warmup", warmup), ("measurement", loops)):
            members = sorted((p for p in products if p["phase"] == phase), key=lambda p: p["index"])
            grouped[phase] = members
            for product in members:
                check(product["verification"].get("passed") is True
                      and product["verification"].get("input_unchanged") is True, f"invalid product: {label}")
                payload = self.hashed_file(product["payload_path"], product["payload_hash"])
                check(payload["bytes"] == product["output_bytes"], f"complete payload size: {label}")
                check(isinstance(product.get("restored_hash"), str) and product["restored_hash"].startswith("sha256:"),
                      f"missing restored digest: {label}")
                self.products["qualification" if independent else "formal"] += 1
            prefix = "warmup_" if phase == "warmup" else ""
            check(batch[prefix + "output_sizes"] == [p["output_bytes"] for p in members], f"driver output sizes: {label}")
            check(batch[prefix + "restored_sizes"] == [request["raw_bytes"]] * count, f"driver restored sizes: {label}")
        size = statistics.mean(p["output_bytes"] for p in grouped["measurement"])
        for field in ("codec_complete_bytes", "native_output_bytes", "stored_bytes", "payload_bytes"):
            close(row.get(field), size, f"{field}: {label}")
        first = grouped["measurement"][0]
        check(row.get("artifact_path") == first["payload_path"] and row.get("artifact_hash") == first["payload_hash"],
              f"first measured artifact: {label}")
        for metric, count in (("bits_per_value", request["value_count"]), ("bits_per_timestamp", request["timestamp_count"])):
            close(row.get(metric), 8 * size / count if count else None, f"{metric}: {label}")
        for operation in ("encode", "decode"):
            duration = row.get(operation + "_batch_ns")
            check(isinstance(duration, (int, float)) and math.isfinite(duration) and duration > 0,
                  f"nonpositive native duration: {label}")
            close(batch[operation + "_batch_ns"], duration, f"driver {operation} duration: {label}")
            close(row[operation + "_ns"], duration / loops, f"{operation} normalization: {label}")
        check(row.get("sampling_unit") == "one native batch per scheduled round; inner operations are not independent samples",
              f"sampling unit: {label}")
        self.hashed_file(batch["runtime_maps_path"], batch["runtime_maps_hash"])
        self.runtime(row["native_runtime"])
        driver = next(b for b in case["build_evidence"] if b.get("kind") == "native_driver")
        check(row["driver_build_id"] == driver["build_id"] and row["driver_binary_hash"] == driver["binary_hash"],
              f"driver identity: {label}")
        sidecar_path = row["experiment_record_path"]
        self.identity(sidecar_path)
        sidecar = json.loads(absolute(sidecar_path).read_bytes())
        check(sidecar.get("schema") == "tsbench.native-experiment/1"
              and sidecar.get("typed_schema") == case["object_schema"]
              and sidecar.get("components") == case["components"]
              and sidecar.get("method") == case["method"]
              and sidecar.get("task", {}).get("kind") == request["kind"]
              and sidecar.get("task", {}).get("fidelity") == request["fidelity"]
              and sidecar.get("task", {}).get("boundary") == "native_core"
              and sidecar.get("task", {}).get("lifecycle") == request["lifecycle"],
              f"experiment sidecar identity: {label}")
        check(sidecar["row"]["native_products"] == products and sidecar["row"]["native_batch"] == batch,
              f"experiment sidecar product/batch evidence: {label}")
        check(absolute(sidecar_path).stat().st_size == row["framework_management_bytes"], f"sidecar size: {label}")
        if independent:
            recovery = row["independent_recovery"]
            check(recovery.get("passed") is True and recovery.get("decoder_process") is True
                  and recovery.get("decoder_returncode") == 0 and recovery["verification"].get("passed") is True,
                  f"independent recovery: {label}")
            check(isinstance(recovery.get("decoder_pid"), int) and recovery["decoder_pid"] > 0
                  and recovery["decoder_pid"] not in {batch["process_pid"], batch["parent_pid"]},
                  f"independent decoder process: {label}")
            check(recovery.get("artifact_hash") == first["payload_hash"], f"independent decoder artifact: {label}")
            self.runtime(recovery["decoder_runtime"])
        return input_id


def close(actual, expected, message):
    if expected is None:
        check(actual is None, message)
    else:
        check(isinstance(actual, (int, float)) and not isinstance(actual, bool)
              and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10), message)


def distribution(values):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    empty = {"n": 0, "median": None, "q1": None, "q3": None, "iqr": None,
             "mean": None, "std": None, "min": None, "max": None}
    if not values:
        return empty
    ordered = sorted(values)
    def quantile(fraction):
        position = (len(ordered) - 1) * fraction
        index = int(position)
        weight = position - index
        return ordered[index] * (1 - weight) + ordered[min(index + 1, len(ordered) - 1)] * weight
    q1, q3 = quantile(.25), quantile(.75)
    return {"n": len(values), "median": statistics.median(values), "q1": q1, "q3": q3,
            "iqr": q3 - q1, "mean": statistics.mean(values),
            "std": statistics.stdev(values) if len(values) > 1 else None,
            "min": min(values), "max": max(values)}


def audit_distribution(summary, name, values, label):
    result = distribution(values)
    check(summary[name]["n"] == result["n"], f"summary sample count {name}: {label}")
    for statistic, expected in result.items():
        close(summary[name].get(statistic), expected, f"summary {name}/{statistic}: {label}")
    return result


def geometry(case, request):
    import numpy as np
    components = case.get("components", {})
    roles = case.get("object_schema", {}).get("roles", {})
    check(components, f"missing input geometry: {case['case_id']}")
    count = defaultdict(int)
    size = 0
    for name, item in components.items():
        elements = math.prod(item["shape"])
        check(item["order"] in {"C", "F"} and all(type(x) is int and x >= 0 for x in item["shape"]),
              f"invalid input geometry: {case['case_id']}")
        count[roles.get(name, name)] += elements
        size += np.dtype(item["dtype"]).itemsize * elements
    check(size == case["raw_bytes"] == request["raw_bytes"]
          and count.get("V", 0) == request["value_count"] and count.get("T", 0) == request["timestamp_count"],
          f"component denominator: {case['case_id']}")
    values = [v for n, v in components.items() if roles.get(n, n) == "V"]
    check(len(values) == 1 and values[0] == {"dtype": request["dtype"], "shape": request["shape"], "order": request["order"]},
          f"frozen value geometry: {case['case_id']}")
    check(set(count) == ({"T", "V"} if request["kind"] == "records" else {"V"}),
          f"unexpected denominator components: {case['case_id']}")


def request_key(request):
    return request["dataset"] + "/" + request["method"] + "/" + request["profile"]


def resolve_config(path, registry):
    config = load_config(path)
    for method in config["methods"]:
        method["codec"] = registry.get(method["codec"]).key
        method["params"] = registry.resolve_params(method["codec"], method.get("params", {}))
        for route in method.get("components", {}).values():
            route["codec"] = registry.get(route["codec"]).key
            route["params"] = registry.resolve_params(route["codec"], route.get("params", {}))
    return config


def audit_run(auditor, frozen, requests, registry, design_role):
    path = absolute(frozen["path"])
    auditor.hashed_file(path, frozen["sha256"])
    config = resolve_config(path, registry)
    execution, task = config["execution"], config["task"]
    check(task["boundary"] == "native_core" and task["lifecycle"] in {"prepared", "fresh_request"}, f"config scope: {path}")
    check(execution["save_artifacts"] is True, f"missing saved-product protocol: {path}")
    for name in ("sessions", "rounds", "native_loops", "native_warmup_loops", "timeout_s"):
        check(execution[name] == frozen[name], f"frozen config {name}: {path}")
    run = absolute(config["output"])
    manifest = json.loads((run / "manifest.json").read_bytes())
    summary = json.loads((run / "report/summary.json").read_bytes())
    events, tail = read_jsonl(run / "observations.jsonl")
    check(tail is None and summary.get("interrupted_jsonl_tail") is None, f"interrupted observations: {run}")
    check(manifest.get("state") == "complete" and manifest.get("execution_source_unchanged") is True,
          f"incomplete run or execution source changed: {run}")
    expected_config_id = stable_hash({k: v for k, v in config.items() if k not in {"output", "_pass_kind", "_config_path"}})
    check(manifest["configuration_id"] == expected_config_id, f"configuration identity: {run}")
    check(all(manifest["resolved_config"].get(k) == v for k, v in config.items() if k != "_pass_kind"), f"resolved configuration differs: {run}")
    provenance = manifest["execution_provenance"]
    check(provenance["source_id"] == stable_hash(provenance["sources"]), f"execution source identity: {run}")
    auditor.source_files(provenance["sources"])
    snapshot = manifest["source_snapshot"]
    check(snapshot["snapshot_id"] == stable_hash(snapshot["files"]), f"source snapshot identity: {run}")
    auditor.source_files(snapshot["files"])
    snapshot_modules = {item["module"]: item["sha256"] for item in snapshot["files"]}
    check(all(snapshot_modules.get(item["module"]) == item["sha256"] for item in provenance["sources"]),
          f"execution source differs from saved snapshot: {run}")
    for name, filename in (("manifest_hash", "manifest.json"), ("observations_hash", "observations.jsonl")):
        auditor.hashed_file(run / filename, summary[name])
    for name, filename in (("analysis_code_hash", "report.py"), ("trial_analysis_hash", "trial_analysis.py")):
        auditor.hashed_file(ROOT / "benchmark/src/tsbench" / filename, summary[name])
    expected_analysis = stable_hash({"schema": "describe/2", "code_hash": summary["analysis_code_hash"],
                                    "trial_analysis_hash": summary["trial_analysis_hash"], "retry": "earliest-executed-attempt",
                                    "quantiles": "linear", "cases": summary["cases"]})
    check(summary["analysis_id"] == expected_analysis and summary["run_id"] == manifest["run_id"], f"analysis identity: {run}")
    selected, planned = scheduled_rows(manifest, events)
    expected = {request_key(r): r for r in requests}
    cases = {c["case_id"]: c for c in manifest["cases"]}
    summaries = {c["case_id"]: c for c in summary["cases"]}
    check(len(expected) == len(requests) == frozen["requests"] and set(cases) == set(summaries) == set(expected)
          and len(summaries) == len(summary["cases"]), f"requested case denominator: {run}")
    all_schedule = set().union(set(), *planned.values())
    check(set(selected) == all_schedule, f"missing scheduled terminal records: {run}")
    terminal = [r for r in events if r.get("phase") == "measurement" and r.get("event") == "terminal"]
    check(all(r.get("run_id") == manifest["run_id"] for r in terminal), f"foreign measurement run: {run}")
    qualifications = defaultdict(list)
    admissions = defaultdict(list)
    for event in events:
        if event.get("event") == "terminal" and event.get("phase") in {"qualification", "admission"}:
            check(event.get("case_id") in cases and event.get("run_id") == manifest["run_id"], f"foreign admission/qualification: {run}")
            (qualifications if event["phase"] == "qualification" else admissions)[event["case_id"]].append(event)
    recorded_qualifications = [{"case_id": event["case_id"], "kind": event["qualification_kind"],
                                "cache_key": event["cache_key"], "status": event["status"],
                                "cache_hit": event["cache_hit"]}
                               for event in events if event.get("phase") == "qualification" and event.get("event") == "terminal"]
    check(manifest["qualification"] == recorded_qualifications, f"qualification manifest/event disagreement: {run}")
    datasets = {d["id"]: d for d in config["datasets"]}
    methods = {m["id"]: m for m in config["methods"]}
    profiles = {p["id"]: p for p in config["profiles"]}
    rows = []
    for label, case in cases.items():
        request, saved = expected[label], summaries[label]
        check(case["codec"] == request["codec"] and case["task"] == request["kind"]
              and case["lifecycle"] == request["lifecycle"] and case["boundary"] == "native_core"
              and case["cache_policy"] == "natural", f"frozen request identity: {label}")
        check(case["dataset"] == datasets[request["dataset"]] and case["method"] == methods[request["method"]]
              and case["profile"] == profiles[request["profile"]], f"case configuration differs: {label}")
        check(case["block_id"] == stable_hash({"raw_object_id": case["raw_object_id"], "task": task,
                                               "profile": case["profile"]}), f"case block identity: {label}")
        input_loaded = case.get("raw_object_id") is not None
        if input_loaded:
            check(case["raw_object_id"] == request["object_id"], f"frozen raw input identity: {label}")
            geometry(case, request)
        else:
            check(case["status"] == "unavailable" and case.get("stage") == "data"
                  and case.get("raw_bytes") is None, f"lost loaded input identity: {label}")
        ready = case["status"] == "ready"
        schedule = {(label, s, r) for s in range(execution["sessions"]) for r in range(execution["rounds"])} if ready else set()
        check(planned.get(label, set()) == schedule, f"session/round schedule: {label}")
        if not ready:
            check(case.get("reason") and len(admissions[label]) == 1
                  and admissions[label][0]["status"] == case["status"]
                  and admissions[label][0].get("reason") == case["reason"], f"lost admission reason: {label}")
        else:
            check(not admissions[label], f"ready case has rejection: {label}")
            check(case.get("build_evidence") and case.get("implementation_id"), f"missing implementation evidence: {label}")
            for build in case["build_evidence"]:
                auditor.build(build)
            exact = [r for r in qualifications[label] if r.get("qualification_kind") == "exact"]
            check(len(exact) == 1 and exact[0]["status"] == "ok", f"exact qualification coverage: {label}")
            scope = {name: {"dtype": item["dtype"], "rank": len(item["shape"]), "trailing_shape": item["shape"][1:]}
                     for name, item in case["components"].items()}
            impl_key = stable_hash({"implementation_id": case["implementation_id"], "scope": scope, "task": task})
            exact_key = stable_hash({"implementation_key": impl_key, "raw_object_id": case["raw_object_id"], "task": task})
            original_qualifications = {}
            for kind, cache_key in (("implementation", impl_key), ("exact", exact_key)):
                found = [r for r in qualifications[label] if r.get("qualification_kind") == kind]
                check(len(found) == 1 and found[0]["status"] == "ok" and found[0].get("cache_key") == cache_key,
                      f"qualification identity {kind}: {label}")
                qualification = found[0]
                if qualification.get("cache_hit"):
                    cache_path = qualification["cache_path"]
                    auditor.qualification_cache[cache_key] = auditor.identity(cache_path)
                    qualification = json.loads(absolute(cache_path).read_bytes())
                    check(qualification.get("status") == "ok" and qualification.get("cache_key") == cache_key,
                          f"invalid {kind} qualification cache: {label}")
                original_qualifications[kind] = qualification
            auditor.native(original_qualifications["exact"], case, request, execution, independent=True)
        primary = [selected[key] for key in sorted(schedule)]
        case_terminals = [r for r in terminal if r["case_id"] == label]
        for row in case_terminals:
            if row["status"] == "ok":
                auditor.native(row, case, request, execution)
            else:
                check(row.get("reason"), f"missing failed-trial reason: {label}")
        statuses = dict(Counter(r["status"] for r in primary))
        successes = [r for r in primary if r["status"] == "ok"]
        complete = ready and bool(schedule) and len(successes) == len(schedule)
        check(saved["case_status"] == case["status"] and saved.get("reason") == case.get("reason")
              and saved["raw_bytes"] == case["raw_bytes"] and saved["planned_trials"] == len(schedule)
              and saved["ok_primary_trials"] == len(successes) and saved["primary_trial_status_counts"] == statuses
              and saved["complete_case"] is complete and saved["missing_trials"] == 0,
              f"summary coverage: {label}")
        check(saved["primary_trace"] == [{k: row[k] for k in ("session", "round", "attempt", "observation_line", "status")} for row in primary],
              f"summary primary trial selection: {label}")
        metrics = {}
        for field in ("codec_complete_bytes", "native_output_bytes", "encode_ns", "decode_ns", "encode_batch_ns", "decode_batch_ns", "bits_per_value", "bits_per_timestamp"):
            metrics[field] = audit_distribution(saved, field, [r.get(field) for r in successes], label)
        for field in ("codec_complete_bytes", "native_output_bytes", "bits_per_value", "bits_per_timestamp"):
            close(saved[field + "_median"], metrics[field]["median"], f"summary scalar {field}: {label}")
        for quality in ("max_abs", "rmse", "nrmse", "psnr_db"):
            audit_distribution(saved["quality"], quality,
                               [r.get("verification", {}).get(quality) for r in successes], label)
        check(saved["quality_target"] == {name: task.get(name) for name in
              ("fidelity", "error_bound", "relative_floor", "special_values", "invalid_values")},
              f"summary quality target: {label}")
        check(saved["primary_reasons"] == dict(Counter(str(r["reason"]) for r in primary if r.get("reason"))),
              f"summary lost trial reason: {label}")
        for operation in ("encode", "decode"):
            duration = metrics[operation + "_ns"]["median"]
            close(saved[operation + "_MiB_s"], request["raw_bytes"] * 1e9 / 2**20 / duration if duration else None,
                  f"summary throughput: {label}")
        size = metrics["codec_complete_bytes"]["median"]
        close(saved["compression_ratio"], request["raw_bytes"] / size if size else None, f"summary compression ratio: {label}")
        row = {"run": str(run.relative_to(ROOT)) if run.is_relative_to(ROOT) else str(run),
               "run_id": manifest["run_id"], "configuration": path.name, "case_id": label,
               "codec": case["codec"], "method_id": case["method_id"], "dataset_id": case["dataset_id"],
               "method_params": case["method"]["params"], "design_role": design_role,
               "profile_id": case["profile_id"], "profile": case["profile"], "task": task,
               "boundary": "native_core", "lifecycle": task["lifecycle"], "report_role": "primary" if task["lifecycle"] == "prepared" else "auxiliary",
               "fidelity": request["fidelity"], "kind": request["kind"], "raw_object_id": request["object_id"],
               "dtype": request["dtype"], "shape": request["shape"], "layout": request["order"],
               "components": case.get("components"), "raw_bytes": request["raw_bytes"], "value_count": request["value_count"],
               "actual_raw_object_id": case.get("raw_object_id"), "actual_raw_bytes": case.get("raw_bytes"),
               "input_geometry_verified": input_loaded,
               "timestamp_count": request["timestamp_count"], "case_status": case["status"], "reason": case.get("reason"),
               "admission_stage": case.get("stage"),
               "planned_trials": len(schedule), "nominal_trials": execution["sessions"] * execution["rounds"],
               "ok_primary_trials": len(successes), "primary_status_counts": statuses,
               "all_attempt_status_counts": dict(Counter(r["status"] for r in case_terminals)),
               "trial_reasons": dict(Counter(r["reason"] for r in primary if r.get("reason"))),
               "attempt_trace": [{k: r.get(k) for k in ("session", "round", "attempt", "status", "stage", "reason",
                                                        "artifact_path", "artifact_hash")} for r in case_terminals],
               "qualification_trace": [{k: r.get(k) for k in ("qualification_kind", "status", "stage", "reason",
                                                              "cache_key", "cache_hit", "cache_path")} for r in qualifications[label]],
               "complete_case": complete, "native_loops": execution["native_loops"], "native_warmup_loops": execution["native_warmup_loops"],
               "codec_input_ids": sorted({r["codec_input_id"] for r in successes}),
               "metrics": metrics if complete else None, "quality": saved["quality"], "quality_target": saved["quality_target"],
               "quality_parameters": saved["codec_quality_parameters"], "real_data": not str(case["dataset"].get("source", "")).startswith("development-fixture:")}
        row["neural_path"] = auditor.neural_path(case, request)
        rows.append(row)
    check(summary["requested_cases"] == len(rows) and summary["planned_trials"] == len(all_schedule)
          and summary["executable_cases"] == sum(r["case_status"] == "ready" for r in rows)
          and summary["status_counts"] == dict(Counter(r["status"] for r in terminal)), f"summary run denominators: {run}")
    record = {"configuration": auditor.identity(path), "run": str(run), "run_id": manifest["run_id"],
              "design_role": design_role,
              "source_id": provenance["source_id"], "snapshot_id": snapshot["snapshot_id"], "analysis_id": summary["analysis_id"],
              "requested_cases": len(rows), "admission_status_counts": dict(Counter(r["case_status"] for r in rows)),
              "planned_trials": len(all_schedule), "primary_status_counts": dict(Counter(r["status"] for r in selected.values())),
              "all_attempt_status_counts": dict(Counter(r["status"] for r in terminal)), "complete_cases": sum(r["complete_case"] for r in rows),
              "extra_attempts": len(terminal) - len(selected),
              "files": [auditor.identity(run / filename) for filename in ("manifest.json", "observations.jsonl", "report/summary.json", "report/summary.csv", "report/README.md")]}
    return record, rows


def number(value, precision=3):
    if value is None:
        return "—"
    if value != 0 and abs(value) < 10 ** -precision:
        return f"{value:.{precision}e}"
    return f"{value:.{precision}f}"


def md(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def rate(row, operation):
    if not row["complete_case"]:
        return "—"
    duration = row["metrics"][operation + "_ns"]
    scale = row["raw_bytes"] * 1e9 / 2**20
    return f"{number(scale/duration['median'], 2)} [{number(scale/duration['q3'], 2)}, {number(scale/duration['q1'], 2)}]"


def metric(row, name):
    return row["metrics"][name]["median"] if row["metrics"] else None


def performance_table(rows):
    lines = ["| codec | 完整输出 bytes | 原始/压缩 | bits/value | 编码 MiB/s [Q1,Q3] | 解码 MiB/s [Q1,Q3] | 完成批次／计划 | 状态／原因 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for row in rows:
        size = metric(row, "codec_complete_bytes")
        reasons = row["reason"] or canonical(row["trial_reasons"]) if not row["complete_case"] else "完整有效"
        lines.append("| " + " | ".join((md(row["codec"]), number(size, 1), number(row["raw_bytes"] / size if size else None),
                                       number(metric(row, "bits_per_value")), rate(row, "encode"), rate(row, "decode"),
                                       f"{row['ok_primary_trials']}/{row['planned_trials']}", md(reasons))) + " |")
    return "\n".join(lines)


def csv_text(rows):
    columns = ["configuration", "run", "run_id", "case_id", "codec", "method_id", "dataset_id", "profile_id", "profile", "boundary", "lifecycle", "report_role", "fidelity", "kind", "task", "raw_object_id", "codec_input_ids", "dtype", "shape", "layout", "components", "raw_bytes", "value_count", "timestamp_count", "case_status", "reason", "complete_case", "nominal_trials", "planned_trials", "ok_primary_trials", "primary_status_counts", "all_attempt_status_counts", "trial_reasons", "native_loops", "native_warmup_loops", "codec_complete_bytes_median", "compression_ratio", "bits_per_value_median", "bits_per_timestamp_median", "encode_MiB_s", "decode_MiB_s", "encode_ns_median", "encode_ns_q1", "encode_ns_q3", "decode_ns_median", "decode_ns_q1", "decode_ns_q3", "max_abs_worst", "rmse_worst", "nrmse_worst", "quality_target", "quality_parameters"]
    columns += ["actual_raw_object_id", "actual_raw_bytes", "input_geometry_verified", "admission_stage",
                "attempt_trace", "qualification_trace", "method_params", "design_role", "neural_path"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        record = {k: row.get(k) for k in columns}
        for field in ("codec_complete_bytes", "bits_per_value", "bits_per_timestamp"):
            record[field + "_median"] = metric(row, field)
        size = record["codec_complete_bytes_median"]
        record["compression_ratio"] = row["raw_bytes"] / size if size else None
        for operation in ("encode", "decode"):
            for statistic in ("median", "q1", "q3"):
                record[operation + "_ns_" + statistic] = row["metrics"][operation + "_ns"][statistic] if row["metrics"] else None
            duration = record[operation + "_ns_median"]
            record[operation + "_MiB_s"] = row["raw_bytes"] * 1e9 / 2**20 / duration if duration else None
        for quality in ("max_abs", "rmse", "nrmse"):
            record[quality + "_worst"] = row["quality"][quality]["max"]
        for name, value in record.items():
            if isinstance(value, (list, dict)):
                record[name] = canonical(value)
        writer.writerow(record)
    return output.getvalue()


def coverage_text(rows, coverage):
    lines = ["# 全注册表原生覆盖", "", "每个请求始终计入请求分母；资格失败与未执行请求不产生吞吐数字。一个完整案例要求其所有计划批次成功且执行源未改变。CSV 的 raw_object_id、raw_bytes、dtype、shape 和 layout 描述冻结请求；actual_raw_object_id、actual_raw_bytes 与 input_geometry_verified 区分实际加载证据，数据缺失时不冒充已验证输入。", "",
             "| codec | prepared 请求／ready／完整／成功批次 | fresh_request 请求／ready／完整／成功批次 |",
             "|---|---:|---:|"]
    for codec, modes in sorted(coverage.items()):
        cells = [codec]
        for lifecycle in ("prepared", "fresh_request"):
            c = modes[lifecycle]
            cells.append(f"{c['requested_cases']} / {c['ready_cases']} / {c['complete_cases']} / {c['ok_primary_trials']}")
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## 每个请求的状态", "", "| 配置／案例 | dtype／shape／布局 | 任务／生命周期 | admission | 成功批次／计划 | 状态计数 | 原因 |", "|---|---|---|---|---:|---|---|"]
    for row in rows:
        cells = (row["configuration"] + " / " + row["case_id"], f"{row['dtype']} / {row['shape']} / {row['layout']}",
                 row["kind"] + "/" + row["fidelity"] + "/" + row["lifecycle"], row["case_status"],
                 f"{row['ok_primary_trials']}/{row['planned_trials']}", canonical(row["primary_status_counts"]),
                 row["reason"] or canonical(row["trial_reasons"]))
        lines.append("| " + " | ".join(md(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def neural_table(rows, supplemented):
    members = [r for r in rows if r["neural_path"] is not None]
    if not members:
        return []
    lines = ["", "## 神经预测与在线更新路径", "",
             "以下次数均为每次完整 encode 与每次完整 decode 各自的源码推导值，非动态 counter，也非将次数作为独立性能样本。完整操作吞吐包含模型／帧恢复、必要初始化、算术编码及 finalize；它不是单独 predict 或 train 内核速度。", "",
             "原冻结 64 symbols 短流属于安全契约扩展：只使用均匀概率编码及完整模型／容器，predict=0、train=0，不能代表神经预测或训练表现。补充设计使用完整原始 fixture 257 symbols；前 64 symbols 使用均匀概率，随后 193 次 predict。COMBINED 在第 128 次预测后执行一次 128 windows 的训练与一次 Adam 更新，之后继续 65 次使用更新权重的预测。N=192 的训练发生在末尾，不能展示更新后的后续预测。", "",
             "DeepZip biGRU 使用固定随库 fixture 模型，现有证据未溯源其训练过程，不能称为已验证的预训练 checkpoint；训练属于独立模型制作，prepared 可预载该固定模型。DZip BOOTSTRAP／COMBINED 使用输入 alphabet 对应的原生 seed 初始化权重，非导入预训练 checkpoint；初始化仍包含于每次编码。COMBINED 的在线训练与解码重放更新均在各自完整操作内。", "",
             "| 设计／codec／mode | symbols | profile／线程 | 生命周期 | uniform／predict | train batches／windows／Adam | 更新后 predict | 完整输出 bytes | 编码 MiB/s [Q1,Q3] | 解码 MiB/s [Q1,Q3] | 成功批次／计划 |",
             "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    if not supplemented:
        lines.insert(3, "本次显式仅审计基础设计，未审计神经路径补充运行；以下短流结果不能赋予完整神经路径实测身份。")
    for row in members:
        path, counts = row["neural_path"], row["neural_path"]["counts"]
        cells = (f"{row['design_role']} / {row['codec']} / {path['mode']}", path["input_symbols"],
                 f"{row['profile_id']} / {row['profile']['native_threads']}", row["lifecycle"],
                 f"{counts['uniform_symbols']} / {counts['predict_calls']}",
                 f"{counts['online_train_batches']} / {counts['online_train_batch_windows']} / {counts['adam_steps']}",
                 counts["post_update_predict_calls"], number(metric(row, "codec_complete_bytes"), 1),
                 rate(row, "encode"), rate(row, "decode"), f"{row['ok_primary_trials']}/{row['planned_trials']}")
        lines.append("| " + " | ".join(md(c) for c in cells) + " |")
    lines += ["", "循环条件、分段长度、训练触发与 Adam 更新的源码 hash、公式及 mode 参数逐案例保存在证据索引和 CSV 的 neural_path 字段；正式批次与 warmup 的每份完整产物仍分别验证。两个生命周期、两个 DZip mode 及 64/257 输入分别保留，不合并统计。"]
    return lines


def readme_text(rows, coverage, evidence):
    totals = evidence["totals"]
    lines = ["# 全量 codec 原生结果", "", f"审计通过：{len(coverage)} 个注册表 key、{len(evidence['runs'])} 份冻结配置、{totals['requested_cases']} 个请求，{totals['complete_cases']} 个完整有效案例；主执行源 `{evidence['source_id']}`。", "",
             "冻结请求分母：" + " + ".join(f"{design['role']} {design['requested_cases']}" for design in evidence["designs"]) + "，每份设计及配置独立保留。", "",
             "主指标使用 native_core/prepared。fresh_request 独立展示创建与分配成本。压缩倍数为有效输入 bytes／完整 codec 输出 bytes；bits/value 使用完整输出，原生批次内完成采样、建模、编码、finalize 或恢复。管理 JSON、hash 与来源记录不计入 codec 大小。", "",
             "一个计划 session/round 对应一个原生批次，批次时长除以配置内循环次数后作为一次描述性样本。表中吞吐由时长中位数反算，区间由时长 Q3/Q1 反算；内循环、C/F 布局及重叠源窗口不作为独立数据集，不进行跨任务总排名。正确性、输入不变性及质量检查均在主计时外逐次验证。", "",
             "[全部请求与原因](coverage.md) · [逐案例 CSV](primary.csv) · [审计边界](audit.md) · [完整证据索引](../all_core_evidence.json)。历史 `docs/native_results` 保留。", "",
             "## 每个 codec 的合法案例", "", "按冻结配置顺序选择首个在两个生命周期均完整有效的输入；DeepZip／DZip 在启用补充设计时优先展示完整神经路径案例，短流与两个 DZip mode 均另表完整列出。不同输入、dtype、布局、质量任务或线程配置之间不作横向排名；具体参数与完整身份见 CSV。", "",
             "| codec | 输入／dtype／shape／布局 | 任务／线程 | 完整输出 bytes (prepared / fresh) | prepared 编码／解码 MiB/s | fresh 编码／解码 MiB/s |", "|---|---|---|---:|---:|---:|"]
    pairs = defaultdict(dict)
    for row in rows:
        key = (row["codec"], canonical(row["method_params"]), row["raw_object_id"],
               canonical(row["task"] | {"lifecycle": ""}), canonical(row["profile"]))
        pairs[key][row["lifecycle"]] = row
    for codec in sorted(coverage):
        eligible = [pair for key, pair in pairs.items() if key[0] == codec and set(pair) == {"prepared", "fresh_request"}
                    and all(r["complete_case"] for r in pair.values())]
        check(eligible, f"no common complete legal case in both lifecycles: {codec}")
        if codec in {"deepzip", "dzip"} and evidence["neural_supplement_audited"]:
            eligible = [pair for pair in eligible if pair["prepared"]["design_role"] == "supplemental_neural_paths"]
            check(eligible, f"neural display cannot fall back to the uniform short stream: {codec}")
        pair = eligible[0]
        prepared, fresh = pair["prepared"], pair["fresh_request"]
        def median_rate(row, operation):
            return row["raw_bytes"] * 1e9 / 2**20 / metric(row, operation + "_ns")
        cells = (codec + (" / " + prepared["neural_path"]["mode"] if prepared["neural_path"] else ""),
                 f"{prepared['dataset_id']} / {prepared['dtype']} / {prepared['shape']} / {prepared['layout']}",
                 f"{prepared['kind']} / {prepared['fidelity']} / {prepared['profile']['native_threads']}",
                 f"{number(metric(prepared,'codec_complete_bytes'),1)} / {number(metric(fresh,'codec_complete_bytes'),1)}",
                 f"{number(median_rate(prepared,'encode'),2)} / {number(median_rate(prepared,'decode'),2)}",
                 f"{number(median_rate(fresh,'encode'),2)} / {number(median_rate(fresh,'decode'),2)}")
        lines.append("| " + " | ".join(md(c) for c in cells) + " |")
    lines += neural_table(rows, evidence["neural_supplement_audited"])
    lines += ["", "## 相同真实输入的主表", "", "以下只包含 prepared、bitwise、values 的真实输入请求；每组固定输入身份、有效 bytes、dtype、布局、任务与 profile。失败请求保留在原位置，主性能字段为空。"]
    groups = defaultdict(list)
    for row in rows:
        if row["real_data"] and row["lifecycle"] == "prepared" and row["fidelity"] == "bitwise" and row["kind"] == "values":
            groups[(row["raw_object_id"], row["dtype"], canonical(row["shape"]), row["layout"], canonical(row["task"]), canonical(row["profile"]))].append(row)
    for members in groups.values():
        row = members[0]
        ids = sorted({identity for member in members for identity in member["codec_input_ids"]})
        lines += ["", f"### {row['dataset_id']} · {row['dtype']} · {row['shape']} · {row['layout']}", "",
                  f"原始对象 `{row['raw_object_id']}`；原生输入 `{', '.join(ids)}`；有效输入 {row['raw_bytes']} bytes，{row['value_count']} values；profile `{row['profile_id']}`。", "", performance_table(members)]
    lines += ["", "开发 fixture、records、bounded_abs、empirical_quality 与 fresh_request 的所有结果位于 CSV 和覆盖表；其任务与质量边界独立。records 分母仅包含一次原始 T 和一次 V；bits/value 对应完整 T+V 输出，另提供 bits/timestamp。", ""]
    return "\n".join(lines)


def audit_text(evidence):
    counts = evidence["totals"]
    return f"""# 全量原生结果审计

审计器读取冻结设计、配置、manifest、append-only observations 与可重算 summary，不执行 codec。仅在全部结构审计通过、每个注册表 key 在 prepared 和 fresh_request 均具有完整合法案例后写出本报告。测量失败或不支持可存在，仍完整保留其请求、状态与原因；不完整案例的主性能字段为空。

- 请求 {counts['requested_cases']}，ready {counts['ready_cases']}，完整有效 {counts['complete_cases']}。
- 计划批次 {counts['planned_trials']}，成功主批次 {counts['ok_primary_trials']}；额外尝试 {counts['extra_attempts']}。重试采用最早已执行尝试，成功重试不覆盖已执行失败。
- 正式阶段逐次产物验证记录 {counts['formal_products']}；精确资格阶段逐次产物验证记录 {counts['qualification_products']}。包含 warmup，warmup 不进入正式性能统计。
- 所有运行使用同一 execution source_id；逐个复核当前执行源、保存的源码快照、driver/codec 构建记录、编译源闭包、工具链、实际加载库及 maps 的哈希。
- 每个成功批次均核对配置内循环数、warmup 数、批次时钟、逐次输出大小、恢复大小、输入不变性和验证结论；完整大小由实际保存的完整 .codec 文件重新核对。原生输入仅包含任务有效组件，禁止 ABI envelope 或额外时间戳扩大分母。
- exact qualification 核对独立 decoder 进程、返回码、完整输出 hash 和质量验证。缓存命中时读取原始资格缓存，核对由 implementation、task 与原始对象构成的资格 key，并将缓存文件加入证据索引。
- 每个 session/round 批次只贡献一个描述性样本；吞吐用有效 bytes／原生每次操作平均时间计算，不把内循环扩展为样本，不扣除估计调度成本。
- 神经路径次数根据冻结 mode、输入长度及实际源码循环推导，非运行时 counter；基础短流的零预测／零训练结论与完整 fixture 的预测／更新路径分别呈现。默认同时审计基础与补充设计，并要求所有运行具有同一 source_id；COMBINED 补充案例必须在在线更新后仍有后续预测。

本审计复核保存的验证记录及压缩产物，不重新执行解码。逐次 restored 文件已按测量协议删除，保留其 digest 和计时外验证记录，因此报告不声称本次重新验证恢复内容。独立 decoder 的 typed schema 属于共同任务信息；恢复所需参数、字典与模型均由完整 codec 输出承载，具体方法格式由源码审阅及构建证据限定。CSV 同时保存冻结请求身份与实际加载身份，数据不可用的请求不会冒充已验证输入。

prepared 反映已准备 context／调用方 buffer 的吞吐；fresh_request 包含每次创建与分配，二者均按源码协议将产物释放放在主计时外。内部临时内存未知时保持未知。经验有损案例仅报告实测质量，不承诺误差上界。结果限于当前固定输入、机器、线程及参数，不支持跨任务总体优劣结论。

完整文件哈希、运行身份、每个请求记录、覆盖状态与统计结果保存在 [all_core_evidence.json](../all_core_evidence.json)。历史 docs/native_results 未改写。
"""


def load_design(auditor, design_path, registry_keys, *, supplemental=False):
    design_path = absolute(design_path)
    design = json.loads(design_path.read_bytes())
    check(design.get("schema") == "tsbench.native-all-design/1", "unexpected frozen design schema")
    auditor.hashed_file(design["generated_from"], design["generator_sha256"])
    auditor.source_files(design.get("source_references", []))
    if supplemental:
        check(design.get("design_role") == "supplemental_neural_paths"
              and set(design["expected_codec_coverage"]) == {"deepzip", "dzip"}, "unexpected neural supplement scope")
        check(all("source_derived_operation_counts" in r and "mode" in r for r in design["requests"]),
              "neural supplement lacks source-derived path metadata")
    else:
        check(set(design["expected_codec_coverage"]) == registry_keys, "base design does not cover current registry")
    frozen_configs = design["configurations"]
    names = [absolute(c["path"]).name for c in frozen_configs]
    check(len(names) == len(set(names)), "duplicate frozen configuration")
    requests_by_config = defaultdict(list)
    expected_coverage = defaultdict(Counter)
    for request in design["requests"]:
        check(request["configuration"] in names and request["codec"] in registry_keys, "foreign frozen request")
        requests_by_config[request["configuration"]].append(request)
        expected_coverage[request["codec"]][request["lifecycle"]] += 1
    check(len(design["requests"]) == design["request_count"]
          and {k: dict(v) for k, v in expected_coverage.items()} == design["expected_codec_coverage"], "frozen request denominator")
    nominal_trials = sum(c["requests"] * c["sessions"] * c["rounds"] for c in frozen_configs)
    nominal_operations = sum(c["requests"] * c["sessions"] * c["rounds"] * c["native_loops"] for c in frozen_configs)
    check(design["nominal_trial_count"] == nominal_trials
          and design["nominal_measured_operations"] == nominal_operations, "frozen nominal trial/operation denominator")
    return design, requests_by_config


def generate(design_path, supplement_path=DEFAULT_SUPPLEMENT):
    auditor = Auditor()
    registry = Registry(ROOT)
    registry_keys = {spec.key for spec in registry.list()}
    base_design, base_requests = load_design(auditor, design_path, registry_keys)
    designs = [("all_registry_keys", absolute(design_path), base_design, base_requests)]
    if supplement_path is not None:
        supplement, supplement_requests = load_design(auditor, supplement_path, registry_keys, supplemental=True)
        designs.append(("supplemental_neural_paths", absolute(supplement_path), supplement, supplement_requests))
    all_configuration_names = [absolute(c["path"]).name for _, _, design, _ in designs for c in design["configurations"]]
    check(len(all_configuration_names) == len(set(all_configuration_names)), "configuration names collide between designs")
    records, rows, design_records = [], [], []
    expected_coverage = defaultdict(Counter)
    for role, path, design, requests_by_config in designs:
        for codec, counts in design["expected_codec_coverage"].items():
            expected_coverage[codec].update(counts)
        for frozen in design["configurations"]:
            record, members = audit_run(auditor, frozen, requests_by_config[absolute(frozen["path"]).name], registry, role)
            records.append(record)
            rows.extend(members)
        design_records.append({"role": role, "file": auditor.identity(path),
                               "requested_cases": design["request_count"], "configurations": len(design["configurations"]),
                               "nominal_trial_count": design["nominal_trial_count"],
                               "nominal_measured_operations": design["nominal_measured_operations"]})
    check(len({r["run_id"] for r in records}) == len(records), "a run was reused for different configurations")
    neural_rows = [r for r in rows if r["design_role"] == "supplemental_neural_paths"]
    if supplement_path is not None:
        expected_modes = {("deepzip", "biGRU"), ("dzip", "BOOTSTRAP"), ("dzip", "COMBINED")}
        check({(r["codec"], r["neural_path"]["mode"]) for r in neural_rows} == expected_modes,
              "missing declared neural mode")
        for codec, mode in expected_modes:
            for lifecycle in ("prepared", "fresh_request"):
                members = [r for r in neural_rows if r["codec"] == codec and r["neural_path"]["mode"] == mode
                           and r["lifecycle"] == lifecycle]
                check(members and all(r["complete_case"] for r in members), f"incomplete neural-path case: {codec}/{mode}/{lifecycle}")
                check(all(r["neural_path"]["counts"]["predict_calls"] > 0 for r in members),
                      f"short uniform stream cannot prove neural prediction: {codec}/{mode}/{lifecycle}")
                if mode == "COMBINED":
                    check(all(r["neural_path"]["counts"]["online_train_batches"] > 0
                              and r["neural_path"]["counts"]["post_update_predict_calls"] > 0 for r in members),
                          f"online update has no subsequent prediction: {codec}/{mode}/{lifecycle}")
    source_ids = {r["source_id"] for r in records}
    check(len(source_ids) == 1, "mixed execution sources across all-codec runs")
    check(all(len(ids) == 1 for ids in auditor.cohorts.values()), "same task input differs across codec/lifecycle")
    coverage = {}
    for codec in sorted(registry_keys):
        coverage[codec] = {}
        for lifecycle in ("prepared", "fresh_request"):
            members = [r for r in rows if r["codec"] == codec and r["lifecycle"] == lifecycle]
            complete = [r for r in members if r["complete_case"]]
            check(len(members) == expected_coverage[codec][lifecycle], f"lost request denominator: {codec}/{lifecycle}")
            check(complete, f"no complete legal native case: {codec}/{lifecycle}")
            coverage[codec][lifecycle] = {"requested_cases": len(members), "ready_cases": sum(r["case_status"] == "ready" for r in members),
                                         "complete_cases": len(complete), "planned_trials": sum(r["planned_trials"] for r in members),
                                         "ok_primary_trials": sum(r["ok_primary_trials"] for r in members),
                                         "admission_status_counts": dict(Counter(r["case_status"] for r in members)),
                                         "complete_case_ids": [{"configuration": r["configuration"], "case_id": r["case_id"]} for r in complete]}
    totals = {"requested_cases": len(rows), "ready_cases": sum(r["case_status"] == "ready" for r in rows),
              "complete_cases": sum(r["complete_case"] for r in rows), "planned_trials": sum(r["planned_trials"] for r in rows),
              "ok_primary_trials": sum(r["ok_primary_trials"] for r in rows), "extra_attempts": sum(r["extra_attempts"] for r in records),
              "formal_products": auditor.products["formal"], "qualification_products": auditor.products["qualification"]}
    evidence = {"schema": "tsbench.all-core-evidence/1", "audit_passed": True,
                "source_id": next(iter(source_ids)), "design": auditor.identity(design_path), "designs": design_records,
                "generator": auditor.identity(__file__), "runs": records, "totals": totals, "coverage": coverage,
                "cases": rows, "builds": list(auditor.builds.values()), "qualification_cache": auditor.qualification_cache,
                "cross_codec_input_cohorts": {k: sorted(v) for k, v in auditor.cohorts.items()},
                "sampling_unit": "one scheduled native round batch, never an individual inner operation",
                "validation_limit": "saved product hash/size and recorded per-operation validation audited; decoder not re-executed",
                "neural_supplement_audited": supplement_path is not None,
                "neural_count_scope": "deterministic source-derived calls per encode and per decode, not dynamic counters",
                "neural_model_scope": "DeepZip biGRU uses the fixed bundled fixture model; its training history is not established by current evidence. DZip uses native seeded, untrained input-alphabet weights; COMBINED updates them online.",
                "historical_reports_preserved": "docs/native_results"}
    documents = {"README.md": readme_text(rows, coverage, evidence), "primary.csv": csv_text(rows),
                 "coverage.md": coverage_text(rows, coverage), "audit.md": audit_text(evidence)}
    directory = ROOT / "docs/all_core_results"
    evidence["generated_reports"] = [{"path": str((directory / name).relative_to(ROOT)),
                                       "sha256": "sha256:" + hashlib.sha256(content.encode()).hexdigest(),
                                       "bytes": len(content.encode())} for name, content in documents.items()]
    evidence["audited_files"] = sorted(auditor.files.values(), key=lambda r: r["path"])
    # No output is changed before all audit checks and all renderers succeed.
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="all-core-report-", dir=directory.parent) as temporary:
        staging = Path(temporary)
        for name, content in documents.items():
            (staging / name).write_text(content, encoding="utf-8", newline="")
        (staging / "all_core_evidence.json").write_text(canonical(evidence) + "\n", encoding="utf-8")
        for name in documents:
            (staging / name).replace(directory / name)
        (staging / "all_core_evidence.json").replace(ROOT / "docs/all_core_evidence.json")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, default=ROOT / "benchmark/experiments/native-all/design.json")
    parser.add_argument("--supplement", type=Path, default=DEFAULT_SUPPLEMENT,
                        help="neural path design; audited together with the base by default")
    parser.add_argument("--no-supplement", action="store_true", help="audit the base alone, without claiming neural-path evidence")
    options = parser.parse_args()
    result = generate(options.design, None if options.no_supplement else options.supplement)
    print(canonical({"audit_passed": result["audit_passed"], "source_id": result["source_id"], "totals": result["totals"]}))
