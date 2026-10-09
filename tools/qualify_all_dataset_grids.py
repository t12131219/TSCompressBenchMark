"""Full-input correctness qualification of every registered codec/template grid.

Uses the ordinary planner, preflight and repetition executor. Template FORMAL
profiles are explicitly converted to QUALIFICATION; no performance claim is made.
UCR files are inventoried only, as requested, without inventing a logical view.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import tomllib
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.adapters import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, negotiate
from tscompbench.codecs.negotiation import descriptor_from_dataset
from tscompbench.configuration import _load_profile
from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import read_canonical, write_canonical
from tscompbench.datasets.registry import sha256_file
from tscompbench.environment import capture_environment
from tscompbench.execution.orchestrator import execute_task
from tscompbench.ids import stable_id
from tscompbench.measurement import MeasurementPolicy
from tscompbench.planning import build_comparability_keys, create_task, expand_sweep, resolve_execution
from tscompbench.preprocess import build_preprocess_plan
from tscompbench.version import __version__

SCOPES = ("CORE", "PIPELINE", "E2E")
EXPECTED_REJECTIONS = {"UNSUPPORTED", "ISA_UNSUPPORTED", "BUILD_UNAVAILABLE"}
RESOURCE_EVENTS = {"RESOURCE_PRESSURE", "OVERSUBSCRIBED", "INCOMPARABLE"}


def correctness_passed(row):
    records = row.get("records", [])
    return bool(records and (records[0].get("correctness") or {}).get("status") == "PASS")


def category(row):
    if row["status"] == "PASS":
        return "PASS"
    if row["status"] in RESOURCE_EVENTS and correctness_passed(row):
        return "CORRECTNESS_PASS_RESOURCE_EVENT"
    if row["status"] in EXPECTED_REJECTIONS:
        return "CAPABILITY_OR_ENVIRONMENT_REJECTION"
    if row.get("task", {}).get("status") == "SCHEMA_ERROR":
        return "PARAMETER_REJECTION"
    return "EXECUTION_ERROR"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False,
                                    default=asdict))
    temporary.replace(path)


def runtime_hash():
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src/tscompbench").rglob("*.py")):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def policies(registry, cpu):
    """Deduplicate identical resolved points, retaining every supplying template."""
    found = {}
    for path in sorted((ROOT / "configs/experiments").glob("*.toml")):
        raw = tomllib.loads(path.read_text())
        for key in raw.get("algorithms", []):
            manifest = registry.get(key)
            if manifest.key.startswith("oracle-"):
                continue
            for config in expand_sweep(manifest, raw.get("sweep", {}),
                                       framework_parameters={"benchmark_seed": 20261008}):
                for track in raw["tracks"]:
                    for scope in SCOPES:
                        profile = dict(raw.get("profile", {}))
                        profile.pop("qualification_repetitions", None)
                        profile.update(
                            measurement_mode="QUALIFICATION", timing_scope=scope,
                            warmup_min_count=0, warmup_min_seconds="0", repetitions=1,
                            min_repetition_seconds="0", max_inner_iterations=1,
                            cpu_affinity=[cpu], threads=1, processes=1,
                            timeout_seconds=max(3600, profile.get("timeout_seconds", 0)),
                            memory_limit_bytes=max(12 * 1024**3, profile.get("memory_limit_bytes", 0)),
                        )
                        loaded = _load_profile(profile)
                        identity = {"algorithm": manifest.key, "config_id": config.config_id,
                                    "track": track, "profile": loaded.as_document()}
                        policy_id = stable_id("qualification-policy", identity)
                        if policy_id not in found:
                            found[policy_id] = {**identity, "policy_id": policy_id,
                                "parameters": config.parameters, "config_status": config.status,
                                "config_reason": config.reason_code, "templates": [],
                                "config": config, "loaded_profile": loaded}
                        found[policy_id]["templates"].append(str(path.relative_to(ROOT)))
    missing = set(registry.keys()) - {x["algorithm"] for x in found.values()}
    missing = {x for x in missing if not x.startswith("oracle-")}
    if missing:
        raise RuntimeError(f"Registered algorithms without a template: {sorted(missing)}")
    return sorted(found.values(), key=lambda p: (p["algorithm"], p["policy_id"]))


def inventory(dataset_registry, output):
    registered = {dataset_registry.load(k).source_path: k for k in dataset_registry.keys()}
    rows = []
    for path in sorted((ROOT / "datasets").rglob("*")):
        if not path.is_file():
            continue
        row = {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
               "sha256": sha256_file(path), "registered_key": registered.get(path.resolve()),
               "status": "REGISTERED" if path.resolve() in registered else "UNREGISTERED"}
        if path.suffix == ".tsv":
            widths = Counter()
            samples = missing = invalid = 0
            with path.open() as handle:
                for line in handle:
                    tokens = line.rstrip("\r\n").split("\t")
                    widths[len(tokens) - 1] += 1
                    samples += 1
                    for token in tokens:
                        if token in {"", "NaN", "nan", "?"}:
                            missing += 1
                        else:
                            try:
                                float(token)
                            except ValueError:
                                invalid += 1
            row.update(samples=samples, value_lengths=dict(widths), missing_tokens=missing,
                       invalid_numeric_tokens=invalid, codec_execution="NOT_REQUESTED_UCR")
        rows.append(row)
    write_json(output / "dataset_inventory.json", rows)
    return rows


def summarize(output, policies_count, dataset_count):
    current_policies = {p["policy_id"] for p in json.loads((output / "policies.json").read_text())}
    current_datasets = set(json.loads((output / "dataset_keys.json").read_text()))
    current_runtime = runtime_hash()
    results = []
    for path in sorted((output / "cases").glob("*.json")):
        row = json.loads(path.read_text())
        if (row["policy_id"] in current_policies and row["dataset"] in current_datasets
            and row.get("runtime_sha256") == current_runtime):
            row["category"] = category(row)
            row["correctness_passed"] = correctness_passed(row)
            results.append(row)
    fields = ["case_id", "algorithm", "dataset", "track", "timing_scope", "status",
              "reason_code", "category", "correctness_passed", "policy_id", "config_id", "elapsed_seconds", "evidence"]
    for filename, selected in (("qualification_matrix.csv", results),
                               ("errors.csv", [r for r in results if r["status"] != "PASS"])):
        with (output / filename).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(selected)
    counts = Counter(r["status"] for r in results)
    summary = {"expected_cases": policies_count * dataset_count, "completed_cases": len(results),
               "counts": dict(counts), "performance_claim": False, "full_input": True,
               "categories": dict(Counter(r["category"] for r in results)),
               "correctness_passed_cases": sum(r["correctness_passed"] for r in results),
               "runtime_sha256": current_runtime}
    summary["state"] = (
        "RUNNING" if len(results) != summary["expected_cases"]
        else "COMPLETED_WITH_ERRORS" if summary["categories"].get("EXECUTION_ERROR")
        else "COMPLETED"
    )
    write_json(output / "status.json", summary)
    groups = defaultdict(Counter)
    for r in results:
        groups[r["algorithm"]][r["category"]] += 1
    lines = ["# 全算法、全部已登记 datasets、完整模板参数网格正确性检查", "",
        f"预定 {summary['expected_cases']} 项，已完成 {len(results)} 项。状态：{dict(counts)}。", "",
        "所有实验模板（含 formal、streaming、query、switch、unsupported/rejection 模板）的笛卡尔参数点"
        "展开后去重，保留全部来源；每点实际执行 CORE、PIPELINE、E2E。原始输入完整，未截断、未降维、"
        "未构造时间戳。QUALIFICATION 为一次重复、零预热，无正式性能排名。统一 3600 秒/12 GiB"
        "资源预算，超出模板预算的部分仅用于正确性诊断。能力拒绝不算编解码通过。", "",
        "UCR 按用户选择仅检查文件、数值格式、缺失标记和登记状况，不执行 codec；"
        "详见 dataset_inventory.json。未登记的数据不自动猜测逻辑视图。", "",
        "RESOURCE_PRESSURE 等记录若 correctness.status=PASS，计入正确性通过，另列资源事件；"
        "SYSTEM_VMSTAT 的换页观测不能证明该 codec 自身换页。", "",
        "| 算法 | PASS | 正确性通过/资源事件 | 能力/环境拒绝 | 参数拒绝 | 执行异常 | 总数 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, counter in sorted(groups.items()):
        lines.append(f"| {key} | {counter['PASS']} | {counter['CORRECTNESS_PASS_RESOURCE_EVENT']} | "
                     f"{counter['CAPABILITY_OR_ENVIRONMENT_REJECTION']} | {counter['PARAMETER_REJECTION']} | "
                     f"{counter['EXECUTION_ERROR']} | {sum(counter.values())} |")
    lines += ["", "[完整逐参数矩阵](qualification_matrix.csv) · [非 PASS 明细](errors.csv) · "
              "[冻结策略及模板来源](policies.json) · [数据文件清单](dataset_inventory.json)", "",
              "## 异常明细", ""]
    for r in results:
        if r["category"] == "EXECUTION_ERROR":
            lines.append(f"- {r['algorithm']} / {r['dataset']} / {r['timing_scope']} / {r['track']}: "
                         f"{r['status']} — {r['reason_code']} ([证据]({r['evidence']}))")
    (output / "qualification_report.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--keys", nargs="+")
    parser.add_argument("--datasets", nargs="+")
    parser.add_argument("--scopes", nargs="+", choices=SCOPES)
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.sched_setaffinity(0, {args.cpu})
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    ds = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    all_policies = policies(registry, args.cpu)
    selected = [p for p in all_policies
                if (not args.keys or p["algorithm"] in args.keys)
                and (not args.scopes or p["profile"]["timing_scope"] in args.scopes)]
    public = [{k: v for k, v in p.items() if k not in {"config", "loaded_profile"}} for p in selected]
    write_json(output / "policies.json", public)
    environment = capture_environment()
    write_json(output / "environment.json", environment)
    write_json(output / "runtime.json", {"sha256": runtime_hash(), "executable": sys.executable})
    write_json(output / "aliases.json", list(registry.alias_documents()))
    files = inventory(ds, output)
    datasets = args.datasets or sorted({r["registered_key"] for r in files if r["registered_key"]})
    write_json(output / "dataset_keys.json", datasets)
    completed = 0
    total = len(selected) * len(datasets)
    runtime = runtime_hash()
    artifact_cache = {}
    for key in datasets:
        print(f"Load full dataset {key}", flush=True)
        dataset = load_dataset(ds.load(key))
        canonical_path = output / "prepared" / f"{key}.canonical.tscb"
        if not canonical_path.exists():
            write_canonical(dataset, canonical_path)
        artifact = read_canonical(canonical_path)
        descriptors = {track: descriptor_from_dataset(dataset, BenchmarkTrack(track))
                       for track in {p["track"] for p in selected}}
        for p in selected:
            config = p["config"]
            loaded = p["loaded_profile"]
            manifest = registry.get(p["algorithm"])
            descriptor = descriptors[p["track"]]
            case_id = hashlib.sha256((key + p["policy_id"]).encode()).hexdigest()[:24]
            path = output / "cases" / f"{case_id}.json"
            completed += 1
            if path.exists():
                previous = json.loads(path.read_text())
                if (previous.get("runtime_sha256") == runtime and
                    (not args.retry_errors or category(previous) != "EXECUTION_ERROR")):
                    continue
                write_json(output / "history" / f"{case_id}-{time.time_ns()}.json", previous)
            started = time.monotonic()
            row = {"case_id": case_id, "algorithm": manifest.key, "dataset": key,
                   "track": p["track"], "timing_scope": loaded.timing_scope,
                   "policy_id": p["policy_id"], "config_id": config.config_id,
                   "parameters": config.parameters, "templates": p["templates"],
                   "runtime_sha256": runtime, "evidence": f"cases/{case_id}.json"}
            try:
                compatibility = negotiate(manifest, descriptor, parameters=config.parameters)
                if manifest.key not in artifact_cache:
                    artifact_cache[manifest.key] = adapter_artifacts(ROOT, manifest)
                primary, support = artifact_cache[manifest.key]
                profile = {**loaded.as_document(), "runner_version": __version__}
                execution = resolve_execution(manifest, config, compatibility, environment,
                    artifact_path=primary, supporting_artifact_paths=support, profile=profile)
                task = create_task(descriptor=descriptor, manifest=manifest, config=config,
                    profile_id=loaded.profile_id, compatibility=compatibility,
                    preprocess=build_preprocess_plan(manifest.document, config.parameters),
                    execution=execution, comparability=build_comparability_keys(
                        manifest, descriptor, config, compatibility, execution, profile=profile),
                    resource_limits={"timeout_seconds": loaded.timeout_seconds,
                                     "memory_limit_bytes": loaded.memory_limit_bytes})
                row["task"] = task.to_document()
                write_json(output / "plans" / f"{case_id}.json", row)
                if task.status.value not in {"PLANNED", "ADAPTER_LOSSY_ROUTED"}:
                    row.update(status=task.status.value, reason_code=task.reason_code)
                else:
                    result = execute_task(run_set_id=output.name, task=task, manifest=manifest,
                        source=registry.sources.get(manifest.source_artifact_id), artifact=artifact,
                        adapter=create_adapter(ROOT, manifest), parameters=config.parameters,
                        measurement_policy=MeasurementPolicy.from_profile(loaded, seed=20261008))
                    row["preflight"] = result.preflight.to_document()
                    row["records"] = [r.to_document() for r in result.records]
                    record = row["records"][0]
                    row.update(status=record["status"], reason_code=record["reason_code"])
                    if result.records[0].eligibility:
                        raise AssertionError("qualification result must not enter performance ranking")
                    if row["status"] == "PASS":
                        if not result.bitstreams:
                            raise AssertionError("PASS must provide a finalized stream")
                        row["bitstream_sha256"] = hashlib.sha256(result.bitstreams[0][1]).hexdigest()
            except Exception as error:
                row.update(status="DRIVER_ERROR", reason_code=f"{type(error).__name__}: {error}",
                           traceback=traceback.format_exc())
            row["elapsed_seconds"] = time.monotonic() - started
            write_json(path, row)
            print(f"[{completed}/{total}] {manifest.key}/{key}/{p['track']}/{loaded.timing_scope}: "
                  f"{row['status']} {row['reason_code']} ({row['elapsed_seconds']:.2f}s)", flush=True)
            if completed % 200 == 0 or row["status"] not in EXPECTED_REJECTIONS | {"PASS"}:
                summarize(output, len(selected), len(datasets))
        del dataset, artifact
    summarize(output, len(selected), len(datasets))


if __name__ == "__main__":
    main()
