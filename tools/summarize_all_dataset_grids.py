"""Verify and merge qualification shards while preserving actual execution identities."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from qualify_all_dataset_grids import ROOT, category, correctness_passed, policies, runtime_hash, write_json
from tscompbench.adapters import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.configuration import _load_profile
from tscompbench.datasets import DatasetRegistry
from tscompbench.datasets.registry import sha256_file
from tscompbench.ids import canonical_json_bytes, stable_id


def grid_identity(policy: dict) -> str:
    profile = {k: v for k, v in policy["profile"].items() if k != "cpu_affinity"}
    return stable_id("qualification-grid-point", {
        "algorithm": policy["algorithm"], "config_id": policy["config_id"],
        "track": policy["track"], "profile": profile,
    })


def insert_case(rows: dict, row: dict) -> None:
    identity = (row["dataset"], row["grid_point_id"])
    if identity in rows:
        raise ValueError(f"Duplicate executed grid point: {identity}")
    rows[identity] = row


def verify_record(row: dict, policy: dict, dataset_id: str, algorithm_id: str,
                  artifact_sha256: str) -> None:
    for field in ("algorithm", "config_id", "track", "parameters", "templates"):
        if row[field] != policy[field]:
            raise ValueError(f"Case differs from frozen policy: {field}")
    task = row.get("task")
    if task is None:
        if row["status"] != "DRIVER_ERROR":
            raise ValueError("Missing task receipt")
        return
    expected = {
        "dataset_id": dataset_id, "algorithm_id": algorithm_id,
        "config_id": policy["config_id"], "track": policy["track"],
        "profile_id": _load_profile(policy["profile"]).profile_id,
    }
    if any(task[k] != v for k, v in expected.items()):
        raise ValueError("Task identity differs from current dataset/codec/policy")
    execution = task["execution"]
    if (execution["cpu_affinity"] != policy["profile"]["cpu_affinity"] or
            execution["artifact_sha256"] != artifact_sha256):
        raise ValueError("Task execution affinity/artifact differs")
    records = row.get("records", [])
    for record in records:
        if record["eligibility"]:
            raise ValueError("Qualification entered formal performance ranking")
        if any(record[k] != task[k] for k in ("task_id", "dataset_id", "algorithm_id", "config_id", "track")):
            raise ValueError("Record identity differs from task")
        if record["execution_path_hash"] != execution["execution_path_hash"]:
            raise ValueError("Record execution path differs from task")
    if records and (records[0]["status"] != row["status"] or records[0]["reason_code"] != row["reason_code"]):
        raise ValueError("Summary status differs from raw record")
    if row["status"] == "PASS" or correctness_passed(row):
        if len(records) != 1 or not correctness_passed(row) or row["preflight"]["status"] != "PASS":
            raise ValueError("Claimed pass lacks preflight/repetition correctness")
        accounting = records[0]["accounting"]
        components = ("timestamp_bits", "value_bits", "shared_bits", "unallocated_shared_bits",
                      "metadata_bits", "validity_bits", "dictionary_bits", "model_bits", "index_bits",
                      "checkpoint_bits", "checksum_bits", "padding_bits", "container_bits")
        if (sum(accounting[k] for k in components) != accounting["serialized_bits"] or
                accounting["final_bits"] != accounting["serialized_bits"] + accounting["external_side_information_bits"] or
                accounting["final_physical_bytes"] != (accounting["serialized_bits"] + 7) // 8):
            raise ValueError("Final stream accounting does not close")
        digest = records[0]["bitstream_sha256"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Final stream digest missing")
        if row["status"] == "PASS" and row["bitstream_sha256"] != digest:
            raise ValueError("Final stream digest differs from raw record")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shards", nargs="+", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--authoritative-shard", action="append", nargs=2,
                        metavar=("ALGORITHM", "DIRECTORY"), default=[],
                        help="Explicitly select one repair rerun shard for an algorithm; preserve other evidence")
    args = parser.parse_args()
    output = args.output.resolve()
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    authoritative = {}
    available_shards = {p.resolve() for p in args.shards}
    for algorithm, directory in args.authoritative_shard:
        chosen = Path(directory).resolve()
        if algorithm in authoritative or chosen not in available_shards:
            raise ValueError("Authoritative algorithm shard must be unique and included in --shards")
        registry.get(algorithm)
        authoritative[algorithm] = chosen
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    frozen = policies(registry, 2)
    grid = {grid_identity(p): p for p in frozen}
    if len(grid) != len(frozen):
        raise ValueError("Affinity normalization collapsed distinct strategies")
    public_grid = []
    for point, policy in grid.items():
        public = {k: v for k, v in policy.items() if k not in {"config", "loaded_profile", "policy_id"}}
        public["profile"] = {k: v for k, v in public["profile"].items() if k != "cpu_affinity"}
        public["grid_point_id"] = point
        public_grid.append(public)
    dataset_manifests = {k: datasets.load(k) for k in datasets.keys()}
    dataset_keys = sorted(k for k, manifest in dataset_manifests.items()
                          if manifest.source_path.is_relative_to(ROOT / "datasets"))
    expected = {(key, point) for key in dataset_keys for point in grid}
    current_runtime = runtime_hash()
    binaries = {}
    receipts = []
    rows = {}
    ignored = Counter()
    for shard_arg in args.shards:
        shard = shard_arg.resolve()
        if not (shard / "policies.json").exists():
            continue
        shard_policies = json.loads((shard / "policies.json").read_text())
        active_datasets = set(json.loads((shard / "dataset_keys.json").read_text()))
        by_id = {p["policy_id"]: p for p in shard_policies if grid_identity(p) in grid}
        for p in shard_policies:
            point = grid_identity(p)
            if point not in grid:
                continue  # Historical codec contracts are retained, not credited.
            reference = grid[point]
            if any(p[k] != reference[k] for k in ("parameters", "templates", "config_status", "config_reason")):
                raise ValueError("Shard parameter/template provenance differs")
            if p["policy_id"] != stable_id("qualification-policy", {k: p[k] for k in ("algorithm", "config_id", "track", "profile")}):
                raise ValueError("Shard policy identity differs")
        receipts.append({"directory": os.path.relpath(shard, output),
                         "cpu_affinities": sorted({tuple(p["profile"]["cpu_affinity"]) for p in shard_policies}),
                         "policies_sha256": sha256_file(shard / "policies.json"),
                         "environment_sha256": sha256_file(shard / "environment.json")})
        for path in sorted((shard / "cases").glob("*.json")):
            row = json.loads(path.read_text())
            if row["algorithm"] in authoritative and authoritative[row["algorithm"]] != shard:
                ignored["explicitly_superseded_algorithm_shard"] += 1
                continue
            if row["policy_id"] not in by_id or row["dataset"] not in active_datasets:
                ignored["historical_policy_or_other_dataset"] += 1
                continue
            if row.get("runtime_sha256") != current_runtime:
                ignored["historical_runtime"] += 1
                continue
            policy = by_id[row["policy_id"]]
            point = grid_identity(policy)
            if (row["dataset"], point) not in expected:
                raise ValueError("Executed case outside requested universe")
            key = row["algorithm"]
            manifest = registry.get(key)
            if key not in binaries:
                primary, supporting = adapter_artifacts(ROOT, manifest)
                components = [{"role": "PRIMARY_ADAPTER", "sha256": sha256_file(primary)}]
                components.extend({"role": f"SUPPORTING_COMPONENT_{i}", "sha256": sha256_file(path)}
                                  for i, path in enumerate(supporting))
                binaries[key] = (hashlib.sha256(canonical_json_bytes(components)).hexdigest()
                                 if supporting else components[0]["sha256"])
            verify_record(row, policy, dataset_manifests[row["dataset"]].dataset_id,
                          manifest.algorithm_id, binaries[key])
            row.update(grid_point_id=point, category=category(row),
                       correctness_passed=correctness_passed(row),
                       cpu_affinity=policy["profile"]["cpu_affinity"],
                       evidence=os.path.relpath(path, output))
            insert_case(rows, row)
    missing = expected - rows.keys()
    if args.require_complete and missing:
        raise ValueError(f"Incomplete universe: {len(missing)} missing cases")
    counts = Counter(row["category"] for row in rows.values())
    status = {"state": "RUNNING" if missing else "COMPLETED_WITH_ERRORS" if counts["EXECUTION_ERROR"] else "COMPLETED",
              "expected_cases": len(expected), "completed_cases": len(rows), "missing_cases": len(missing),
              "algorithm_count": len({p["algorithm"] for p in grid.values()}),
              "grid_points_per_dataset": len(grid), "registered_dataset_count": len(dataset_keys),
              "categories": dict(counts), "statuses": dict(Counter(r["status"] for r in rows.values())),
              "correctness_passed_cases": sum(r["correctness_passed"] for r in rows.values()),
              "runtime_sha256": current_runtime, "performance_claim": False,
              "shards": receipts, "ignored_historical_cases": dict(ignored),
              "authoritative_algorithm_shards": {k: os.path.relpath(v, output) for k, v in authoritative.items()},
              "execution_affinity": "RECORDED_PER_CASE_NO_FORMAL_PERFORMANCE_COMPARISON"}
    prefix = "" if args.require_complete else "overall_"
    write_json(output / f"{prefix}status.json", status)
    write_json(output / "corpus_grid_points.json", public_grid)
    fields = ("case_id", "algorithm", "dataset", "track", "timing_scope", "status", "reason_code",
              "category", "correctness_passed", "grid_point_id", "policy_id", "config_id", "cpu_affinity",
              "elapsed_seconds", "evidence")
    selected = sorted(rows.values(), key=lambda r: (r["algorithm"], r["dataset"], r["grid_point_id"]))
    for name, items in (("qualification_matrix.csv", selected), ("errors.csv", [r for r in selected if r["status"] != "PASS"])):
        with (output / f"{prefix}{name}").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(items)
    grouped = defaultdict(Counter)
    for row in selected:
        grouped[row["algorithm"]][row["category"]] += 1
    lines = ["# 全算法、完整模板参数网格、全部已登记 datasets 正确性检查", "",
             f"状态：{status['state']}；{len(rows)}/{len(expected)} 项；{status['algorithm_count']} 个算法，"
             f"{len(grid)} 个策略 × {len(dataset_keys)} 个数据集。", "",
             f"扫描全部 {len(list((ROOT / 'configs/experiments').glob('*.toml')))} 个现有实验模板，"
             "真实算法参数点展开后去重并保留来源，覆盖 CORE、PIPELINE、E2E 及模板声明的"
             "streaming/query/switch/rejection 参数。实际 CPU、PolicyID、ProfileID、ExecutionPathHash "
             "分别保留在每项原始证据中；汇总仅按相同算法参数、轨道与工作负载合并网格覆盖，"
             "不把不同 CPU 的性能当作可比较结果。每个执行进程内部串行，零预热、一次 QUALIFICATION 重复，"
             "各隔离阶段 3600 秒/12 GiB 诊断预算；完整输入，不截断、降维、补窗口、构造时间戳或挑列。", "",
             "能力拒绝和非法参数拒绝保留但不计编解码通过。correctness.status=PASS 的资源事件单列；"
             "系统换页不能归因于单个 codec。所有资格记录均无正式排名资格。", "",
             "UCR 按用户决定仅检查文件、数值格式、缺失值标记及登记，不执行 codec。", "",
             f"分类：{dict(counts)}。", "",
             "| 算法 | PASS | 正确性通过/资源事件 | 能力/环境拒绝 | 参数拒绝 | 执行异常 | 总数 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, counter in sorted(grouped.items()):
        lines.append(f"| {key} | {counter['PASS']} | {counter['CORRECTNESS_PASS_RESOURCE_EVENT']} | "
                     f"{counter['CAPABILITY_OR_ENVIRONMENT_REJECTION']} | {counter['PARAMETER_REJECTION']} | "
                     f"{counter['EXECUTION_ERROR']} | {sum(counter.values())} |")
    lines += ["", "[完整逐参数矩阵](qualification_matrix.csv) · [全部非 PASS 明细](errors.csv) · "
              "[网格及模板来源](corpus_grid_points.json) · [数据文件检查](dataset_inventory.json) · "
              "[修复记录](repair_notes.md)", "", "## 执行异常", ""]
    for row in selected:
        if row["category"] == "EXECUTION_ERROR":
            lines.append(f"- {row['algorithm']} / {row['dataset']} / {row['track']} / {row['timing_scope']}: "
                         f"{row['status']} — {row['reason_code']} ([原始证据]({row['evidence']}))")
    (output / f"{prefix}qualification_report.md").write_text("\n".join(lines) + "\n")
    if args.require_complete:
        registry.verify_all()
        inventory = json.loads((output / "dataset_inventory.json").read_text())
        for item in inventory:
            if sha256_file(ROOT / item["path"]) != item["sha256"]:
                raise ValueError("Dataset bytes changed during qualification")
        verification = {**status, "verification_status": "PASS", "duplicates": 0,
                        "current_runtime_and_codec_ids": True, "dataset_files_unchanged": len(inventory),
                        "pass_requires_preflight_correctness_accounting": True, "all_eligibility_false": True,
                        "matrix_sha256": sha256_file(output / "qualification_matrix.csv"),
                        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        write_json(output / "final_verification.json", verification)
    print(json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
