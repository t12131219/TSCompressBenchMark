"""Freeze native PeMS rank-3 values, provenance and declared eligibility; never run codecs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
import tomllib
import zipfile

import numpy as np

from tsbench.config import resolve
from tsbench.data import array_descriptor, fingerprint, load_dataset, project
from tsbench.registry import Registry, UnsupportedError


ROOT = Path(__file__).resolve().parents[2]
FILES = ("PEMS03.npz", "pems04.npz", "PEMS07.npz", "pems08.npz")
LENGTHS = (128, 512, 8192)
START = 1024
SEED = 20261013
SESSIONS = 3
ROUNDS = 7
LICENSE = "unknown; exact author-preprocessed NPZ has no established data license"
PRIOR_EXPOSURE = (
    "These local sources were observed in historical work and have now been hashed and parsed. "
    "This finite extension is not a blind holdout; windows and parameters are fixed before its timings."
)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_identities(path):
    """Hash actual local bytes once, including the Git blob framing used upstream."""
    size = path.stat().st_size
    full = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(size).encode("ascii") + b"\0")
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            full.update(block)
            blob.update(block)
    return {"bytes": size, "sha256": full.hexdigest(), "git_blob_sha1": blob.hexdigest()}


def native_header(path):
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ["data.npy"]:
            raise ValueError(f"{path}: expected only data.npy; do not infer timestamps")
        with archive.open("data.npy") as stream:
            version = np.lib.format.read_magic(stream)
            if version != (1, 0):
                raise ValueError(f"{path}: expected frozen NPY 1.0 header")
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        return {"members": ["data.npy"], "npy_version": list(version),
                "shape": list(shape), "dtype": dtype.str, "fortran_order": fortran}


def verified_sources(corpus, evidence):
    local = {entry["file"]: entry for entry in evidence["local_files"]}
    sources = []
    for filename in FILES:
        record = local[filename]
        path = (corpus / filename).resolve(strict=True)
        identity = file_identities(path)
        expected = {name: record[name] for name in identity}
        if identity != expected:
            raise ValueError(f"{path}: actual file identity differs from frozen source evidence")
        upstream = record["upstream_git_blob"]
        if identity["bytes"] != upstream["size"] or identity["git_blob_sha1"] != upstream["sha"]:
            raise ValueError(f"{path}: local Git blob does not match author tree entry")
        header = native_header(path)
        old = record["npy_header"]
        if any(header[name] != old[name] for name in ("shape", "dtype", "fortran_order")):
            raise ValueError(f"{path}: native array header changed")
        if header["dtype"] != "<f8" or len(header["shape"]) != 3 or header["fortran_order"]:
            raise ValueError(f"{path}: expected native rank-3 little-endian f64 in C order")
        if START + max(LENGTHS) > header["shape"][0]:
            raise ValueError(f"{path}: fixed window exceeds original time-axis rows")
        sources.append({
            "id": path.stem.lower(), "path": str(path), **identity, "native_header": header,
            "author_repository": "guoshnBJTU/ASTGNN", "author_ref": record["upstream_ref"],
            "author_tree_url": "https://api.github.com/repos/guoshnBJTU/ASTGNN/git/trees/"
                               + record["upstream_ref"] + "?recursive=1",
            "author_blob_url": upstream["url"], "author_path": upstream["path"],
            "author_raw_url": record["upstream_raw_url"],
            "upstream_match_scope": record["upstream_git_blob_match_scope"],
            "remote_npz_downloaded_by_preparation": False, "remote_sha256_recomputed": False,
            "original_local_acquisition_time": record["original_local_acquisition_time"],
            "license": LICENSE,
            "license_scope": "author tree has no LICENSE and GitHub license metadata is null; "
                             "Caltrans website policy does not establish this processed file's license",
            "units": record["values_unit"], "timestamp_semantics": record["timestamp_semantics"],
            "prior_exposure": PRIOR_EXPOSURE,
        })
    return sources


def toml_value(value):
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + " = " + toml_value(entry)
                                for key, entry in value.items()) + " }"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render_config(config):
    lines = ["# Frozen native rank-3 inputs; provenance and scope: preparation.json."]
    for key in ("schema", "name", "output"):
        lines.append(f"{key} = {toml_value(config[key])}")
    for group in ("datasets", "methods", "profiles"):
        for entry in config[group]:
            lines.extend(["", f"[[{group}]]"])
            lines.extend(f"{key} = {toml_value(value)}" for key, value in entry.items())
    for group in ("task", "execution", "analysis"):
        lines.extend(["", f"[{group}]"])
        lines.extend(f"{key} = {toml_value(value)}" for key, value in config[group].items())
    return "\n".join(lines) + "\n"


def configuration(sources, run_root):
    datasets = []
    for source in sources:
        for length in LENGTHS:
            datasets.append({
                "id": f'{source["id"]}-native-n{length}', "format": "npz", "path": source["path"],
                "key": "data", "component": "V", "start": START, "stop": START + length,
                "step": 1, "order": "C", "source": source["author_raw_url"], "license": LICENSE,
                "schema": {"axes": ["time", "sensor", "feature"], "topology": "NATIVE_ND_ARRAY",
                           "units": "unknown for exact author-preprocessed file",
                           "time_axis_semantics": "original row axis; timestamps and sampling interval absent"},
            })
    return {
        "schema": "tsbench.experiment/1", "name": "pems-values",
        "output": str((run_root / "pems-values-20261013").resolve()), "datasets": datasets,
        "methods": [
            {"id": "raw-store", "codec": "raw-store", "params": {}},
            {"id": "zstd-frame", "codec": "zstd-frame", "params": {
                "compression_level": 3, "native_timing": False}},
            {"id": "deflate-zlib", "codec": "deflate-zlib", "params": {
                "compression_level": 6, "native_timing": False}},
            {"id": "chimp128", "codec": "chimp128", "params": {"block_size": 1000, "isa": "SCALAR"}},
        ],
        "profiles": [{"id": "cpu-single", "device": "cpu", "native_threads": 1,
                      "object_workers": 1, "memory_limit_mb": 4096}],
        "task": {"kind": "values", "fidelity": "bitwise", "boundary": "object_memory",
                 "lifecycle": "independent_object", "cache_policy": "natural"},
        "execution": {"sessions": SESSIONS, "rounds": ROUNDS, "warmup_objects": 2,
                      "seed": SEED, "timeout_s": 120, "qualification_cache": True, "save_artifacts": True},
        "analysis": {"summary": "median_iqr", "inference": "none"},
    }


def cache_evidence(cache_root):
    result = []
    for index in sorted(cache_root.glob("index*")):
        attributes = {}
        for name in ("level", "type", "size", "coherency_line_size", "shared_cpu_list"):
            path = index / name
            data = path.read_bytes()
            attributes[name] = {"path": str(path), "text": data.decode("ascii"),
                                "sha256": hashlib.sha256(data).hexdigest()}
        size = attributes["size"]["text"].strip()
        suffix = size[-1:]
        capacity = int(size[:-1]) * {"K": 1024, "M": 1024**2}[suffix] if suffix in {"K", "M"} else int(size)
        result.append({"index_path": str(index), "level": int(attributes["level"]["text"]),
                       "type": attributes["type"]["text"].strip(), "capacity_bytes": capacity,
                       "line_size_bytes": int(attributes["coherency_line_size"]["text"]),
                       "shared_cpu_list": attributes["shared_cpu_list"]["text"].strip(),
                       "attributes": attributes})
    if not result or not any(entry["level"] == 3 and entry["type"] == "Unified" for entry in result):
        raise ValueError("cpu0 sysfs shared L3 evidence absent; do not infer a cache capacity")
    return {"cpu": 0, "root": str(cache_root), "caches": result,
            "scope": "readonly cpu0 sysfs capacity evidence; profile does not pin worker affinity; "
                     "logical input capacity comparison only, not an observed cache state or performance cause"}


def object_profile(obj, dataset, source):
    if set(obj.components) != {"V"}:
        raise ValueError("PeMS values preparation must contain only native V, without fabricated T or mask")
    array = obj.components["V"]
    expected = [dataset["stop"] - dataset["start"], *source["native_header"]["shape"][1:]]
    descriptor = array_descriptor(array)
    if descriptor != {"dtype": "<f8", "shape": expected, "order": "C"}:
        raise ValueError(f'{dataset["id"]}: dtype, native shape or order changed')
    finite = np.isfinite(array)
    values = array[finite]
    zeros = array == 0
    negative = np.signbit(array)
    return {
        "dataset_id": dataset["id"], "source_id": source["id"], "raw_object_id": fingerprint(obj),
        "schema": dict(obj.schema), "lineage": dict(obj.lineage),
        "component": {"name": "V", **descriptor, "rank": array.ndim,
                      "axes": ["time", "sensor", "feature"], "elements": int(array.size),
                      "logical_bytes": int(array.nbytes),
                      "typed_bytes_sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest(),
                      "finite_count": int(finite.sum()), "nan_count": int(np.isnan(array).sum()),
                      "positive_infinity_count": int(np.isposinf(array).sum()),
                      "negative_infinity_count": int(np.isneginf(array).sum()),
                      "positive_zero_count": int((zeros & ~negative).sum()),
                      "negative_zero_count": int((zeros & negative).sum()),
                      "finite_min": float(values.min()) if values.size else None,
                      "finite_max": float(values.max()) if values.size else None},
        "characterization_scope": "finite/special counts and extrema over all native elements only; "
                                  "no flattening into a time series and no lag/cross-sensor correlation",
    }


def declared_capability(registry, method, obj, profile):
    """Validate declarations only; do not bind installed artifacts or load a bridge."""
    spec = registry.get(method["codec"])
    params = registry.resolve_params(spec.key, method["params"])
    route = {**method, "params": params}
    evidence = {"declared_ranks": list(spec.ranks), "declared_dtypes": list(spec.dtypes),
                "declared_loss_mode": spec.loss_mode, "declared_threading": spec.threading,
                "resolved_method": route, "installed_artifacts_checked": False,
                "native_qualification_executed": False}
    try:
        if spec.loss_mode != "LOSSLESS":
            raise UnsupportedError("bitwise values requires lossless semantics")
        if spec.threading != "SINGLE_THREAD" or profile["native_threads"] != 1:
            raise UnsupportedError("fixed profile requires declared single-thread semantics")
        for array in obj.components.values():
            spec.validate_array(array)
            topology = obj.schema["topology"]
            declared_topologies = spec.document["input"].get("topologies")
            if declared_topologies is not None and topology not in declared_topologies:
                raise UnsupportedError(f"{spec.key}: topology {topology} outside declaration")
        return {**evidence, "declared_supported": True, "status": "declared_eligible", "reason": None,
                "native_qualification": "pending; native content/installed artifact/correctness checks required"}
    except UnsupportedError as error:
        return {**evidence, "declared_supported": False, "status": "unsupported", "reason": str(error),
                "native_qualification": "not requested for input outside declared capability"}


def readme_text():
    return """# PeMS 原生三维值对象实验

冻结 4 个作者 NPZ × 3 个窗口（128、512、8192），统一 `[1024,1024+n)`；保持原始 `<f8`、C order 和 `time/sensor/feature` 轴，只有 V，没有推定时间戳。raw-store、zstd-frame（level 3）、deflate-zlib（level 6）和 chimp128 各占一个请求；Chimp128 声明只支持 rank 1/2，本实验的 12 个 rank 3 请求应记为 unsupported，并保留在分母中。

正式协议为 bitwise、object_memory、independent_object、natural cache、CPU 单 native thread / 单 object worker、4096 MiB RLIMIT_AS、2 warmups、3 sessions × 7 rounds；共 48 请求 / 1008 名义轮次，其中 36 请求 / 756 轮次在声明能力内。生成器只读取原始数据、核验 hash、序列化/解析配置并检查声明能力；没有执行 codec、资格测试或计时。实际安装、内容资格、重建正确性和性能结果以独立正式运行目录为准。

`preparation.json` 保存本地 SHA-256、作者固定 ref/blob/raw URL、原生数组头、12 个 typed-byte hash、完整窗口 lineage、有限/特殊值计数、配置及解析依赖 hash、cpu0 sysfs 原文/hash。作者固定仓库文件的 Git blob SHA-1 和长度与本地相等；未下载远程 NPZ、未重算其 SHA-256。精确预处理文件许可证、单位及提取/插补历史未知；这些来源曾被历史工作观察，不是盲测 holdout。三个窗口嵌套，共用源观测；轮次只描述当前环境，analysis inference=none。

8192 行的逻辑输入逐个超过观测到的 cpu0 shared L3 容量。这里只比较输入字节数与 sysfs 容量；没有 cold/warm cache、内存带宽或缓存导致性能变化的结论。自然缓存策略和实际 worker 位置仍由正式 manifest 记录。

在项目根目录执行纯准备：

```bash
PYTHONPATH=benchmark/src python benchmark/tools/generate_pems.py
```

文件冻结后，重新生成若发现差异会停止并要求新输出目录；旧准备证据不会被覆盖。通过正式运行入口执行 `pems-values.toml`，或复制配置到新 replay 目录并显式设置新 `build_root` 和 `output` 后执行：

```bash
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/pems-values/pems-values.toml
```

正式运行不得与构建、测试或其他 codec 工作负载并发。复现时应保留配置内容、准备文件和 run manifest 的实际 build/source 绑定，不能把新的 build hash 写回历史 run。
"""


def generate(corpus, output, research, run_root, cache_root):
    output = output.resolve()
    evidence = json.loads(research.read_text())
    sources = verified_sources(corpus.resolve(), evidence)
    config = configuration(sources, run_root)
    text = render_config(config)
    # Parse the actual TOML text through the production resolver before freezing it.
    resolved = resolve(tomllib.loads(text), output)
    registry = Registry(ROOT)
    by_id = {source["id"]: source for source in sources}
    objects, cases = [], []
    for dataset in resolved["datasets"]:
        source_id = Path(dataset["path"]).stem.lower()
        source = by_id[source_id]
        obj = project(load_dataset(dataset, output), resolved["task"])
        if obj.lineage["source_hash"] != "sha256:" + source["sha256"]:
            raise ValueError(f"{dataset['id']}: loader source hash changed during preparation")
        objects.append(object_profile(obj, dataset, source))
        for method in resolved["methods"]:
            for profile in resolved["profiles"]:
                cases.append({"dataset_id": dataset["id"], "raw_object_id": objects[-1]["raw_object_id"],
                              "method_id": method["id"], "profile_id": profile["id"],
                              **declared_capability(registry, method, obj, profile)})
    caches = cache_evidence(cache_root)
    l3 = [entry for entry in caches["caches"] if entry["level"] == 3 and entry["type"] == "Unified"]
    capacity = max(entry["capacity_bytes"] for entry in l3)
    caches["logical_input_comparisons"] = [
        {"dataset_id": obj["dataset_id"], "logical_input_bytes": obj["component"]["logical_bytes"],
         "observed_cpu0_shared_l3_capacity_bytes": capacity,
         "input_exceeds_observed_l3_capacity": obj["component"]["logical_bytes"] > capacity}
        for obj in objects]
    n8192 = [entry for entry in caches["logical_input_comparisons"] if entry["dataset_id"].endswith("n8192")]
    if not all(entry["input_exceeds_observed_l3_capacity"] for entry in n8192):
        raise ValueError("fixed n8192 capacity comparison changed; preserve evidence and choose a new study")
    count = sum(case["declared_supported"] for case in cases)
    if len(objects) != 12 or len(cases) != 48 or count != 36:
        raise ValueError("fixed PeMS request/declared-support grid changed")
    dependency_paths = [Path(__file__).resolve(), research.resolve()]
    dependency_paths.extend(ROOT / "benchmark/src/tsbench" / (name + ".py")
                            for name in ("__init__", "config", "data", "registry", "errors", "runtime"))
    dependency_paths.extend(ROOT / "registry/codecs" / (name + ".json")
                            for name in ("zstd-frame", "deflate-zlib", "chimp128"))
    preparation = {
        "schema": "tsbench.pems-preparation/1", "experiment": config["name"],
        "measurement_executed": False, "qualification_executed": False, "codec_execution": False,
        "scope": "actual local hashes, native headers, production NPZ parse/projection, TOML parse, "
                 "fixed params and declared capability only; installed artifact/native content qualification pending",
        "configuration_path": str(output / "pems-values.toml"),
        "configuration_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_and_parse_dependency_hashes": {str(path): sha256(path) for path in dependency_paths},
        "preparation_runtime": {"python": platform.python_version(), "python_executable": sys.executable,
                                "numpy": np.__version__, "platform": platform.platform()},
        "sources": sources, "lengths": list(LENGTHS), "start": START, "exclusive_stop": "1024 + length",
        "prior_exposure": PRIOR_EXPOSURE,
        "dependence": "n128 is a prefix of n512 and n8192; windows share source observations. "
                      "Four packaged source files do not establish independent population samples; no inference.",
        "selection": "fixed grid and defaults before this extension; no content-derived tuning; no dtype/rank conversion",
        "task": resolved["task"], "profiles": resolved["profiles"], "execution": resolved["execution"],
        "analysis": resolved["analysis"], "objects": objects, "cases": cases,
        "requested_cases": len(cases), "declared_eligible_cases": count,
        "declared_status_counts": dict(Counter(case["status"] for case in cases)),
        "nominal_requested_trial_slots": len(cases) * SESSIONS * ROUNDS,
        "declared_eligible_trial_slots": count * SESSIONS * ROUNDS,
        "denominator_policy": "all 48 requests remain; chimp128 rank3 is unsupported, not silently reshaped, substituted or removed",
        "cache_evidence": caches,
        "timing_scope": "production object_memory boundary; source NPZ parse and these statistics outside clock; "
                        "finite/special summaries do not measure bandwidth or memory/cache performance",
    }
    artifacts = {output / "pems-values.toml": text, output / "preparation.json": json_text(preparation),
                 output / "generator_at_preparation.py": Path(__file__).read_text(),
                 output / "README.md": readme_text()}
    # Check all existing artifacts before any write. Replay must use a new output directory after drift.
    for path, value in artifacts.items():
        if path.exists() and path.read_text() != value:
            raise ValueError(f"fixed artifact differs: {path}; preserve it and use a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    for path, value in artifacts.items():
        path.write_text(value)
    return {"config": str(output / "pems-values.toml"), "preparation": str(output / "preparation.json"),
            "objects": len(objects), "requested_cases": len(cases), "declared_eligible_cases": count,
            "declared_status_counts": preparation["declared_status_counts"],
            "nominal_requested_trial_slots": preparation["nominal_requested_trial_slots"],
            "declared_eligible_trial_slots": preparation["declared_eligible_trial_slots"],
            "measurement_executed": False, "qualification_executed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("/home/fzg/PycharmProjects/材料/TSBench_Corpus"))
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark/experiments/pems-values")
    parser.add_argument("--research", type=Path, default=ROOT / "docs/research/additional_data_sources.json")
    parser.add_argument("--run-root", type=Path, default=ROOT / "runs")
    parser.add_argument("--cache-root", type=Path, default=Path("/sys/devices/system/cpu/cpu0/cache"))
    args = parser.parse_args()
    print(json_text(generate(args.corpus, args.output, args.research, args.run_root, args.cache_root)), end="")
