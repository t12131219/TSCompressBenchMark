"""Render the audited native results as a new Markdown report and PNG/SVG plots.

Read-only with respect to measurements and existing reports. No codec is loaded
or executed. Run after timed work has finished; uses the optional matplotlib
analysis dependency. Raw-store is omitted from every chart and exported table.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs/all_core_results"
REAL_VALUES = ("etth1-values-c", "etth1-values-f", "weather-values-c", "weather-values-f", "ili-values-c")
LABELS = {
    "etth1-values-c": "ETTh1 C", "etth1-values-f": "ETTh1 F",
    "weather-values-c": "Weather C", "weather-values-f": "Weather F",
    "ili-values-c": "ILI C", "float64-c": "Float64 fixture C", "float64-f": "Float64 fixture F",
    "float32-c": "Float32 fixture C", "float32-f": "Float32 fixture F",
    "uint8-c": "UInt8 fixture C", "int16-c": "Int16 fixture C", "int16-f": "Int16 fixture F",
    "uint32-c": "UInt32 fixture C", "symbols4-c-n64": "Symbols4 C / 64 symbols",
    "symbols4-c": "Symbols4 C / 257 symbols", "etth1-records-c": "ETTh1 T+V C",
    "weather-records-c": "Weather T+V C",
}
FIDELITIES = {"bitwise": "无损", "bounded_abs": "绝对误差 ≤ 0.01", "empirical_quality": "经验质量（无点误差保证）"}
LIFECYCLES = ("prepared", "fresh_request")
METRICS = ("compression_ratio", "encode_MiB_s", "decode_MiB_s")
COLORS = {"lz4-frame": "#0072b2", "snappy-raw": "#e69f00", "zstd-frame": "#009e73"}
NOTES = {
    "alp": "强制 ALP；ETTh1 两布局选择 ALP-RD 时明确拒绝，不自动替换算法",
    "alp-rd": "强制 ALP-RD，与 ALP 分开计量",
    "fse": "单块 ≤128 KiB；未对本轮大真实对象自动切块",
    "huff0": "单块 ≤128 KiB；未对本轮大真实对象自动切块",
    "gorilla-prometheus-xor": "本轮 optimized；一组 int64 T[N]+f64 V[N]，N≤65535，无 mask",
    "deepzip": "native_core 为 rank1 u8；固定 biGRU fixture 模型／alphabet；64符号无预测，257符号有预测",
    "dzip": "native_core 为 rank1 u8；caller+2 Eigen workers；BOOTSTRAP／COMBINED 分开，alphabet 受限",
    "abba": "native_core 为 rank1 f64；经验质量，不提供最大点误差承诺",
    "fabba": "native_core 为 rank1 f64；经验质量，不提供最大点误差承诺",
    "sprintz-delta": "direct core 仅 C、rank1/2、1–128通道、8/16位整数；本轮 int16 F 被拒绝",
    "sprintz-fire": "direct core 仅 C、rank1/2、1–128通道、8/16位整数；本轮 int16 F 被拒绝",
    "sprintz-fire-huff0": "同矩阵 Sprintz；原始输入另限120 KiB及Huff0阶段大小；本轮 int16 F 被拒绝",
    "sprintz-delta-u8": "rank1 u8，≤131072值；AVX2/BMI2/LZCNT",
    "sprintz-fire-u8": "rank1 u8，≤131072值；AVX2/BMI2/LZCNT",
    "simdcomp-u32": "rank1 u32；本轮 SSE4.1 LENGTH；注册的 AVX2 不支持 LENGTH",
    "neats-lossless-i64": "signed整数；物理流1–65536值及归一化跨度约束；查询/随机访问仅登记能力",
    "leats-lossless-i64": "signed整数；物理流1–65536值及归一化跨度约束；查询/随机访问仅登记能力",
    "zstd-frame": "本轮 level3、内容checksum开；既有构建禁动态BMI2/ASM；流式能力未在本轮计时",
    "snappy-raw": "RawCompress/RawUncompress；既有构建显式关闭SSSE3/BMI2等路径",
    "lz4-frame": "LZ4 frame、独立64 KiB blocks、内容checksum开；不是lzbench raw block",
    "zfp-accuracy-1d": "fixed accuracy；拒绝空输入、非有限值、subnormal和负零；质量逐产物检查",
    "serf-qt": "ABS任务；必要异常原始块计入完整输出",
    "serf-xor": "ABS任务；必要异常原始块计入完整输出",
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def identity(path):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha256": digest(path), "bytes": path.stat().st_size}


def read_verified(record):
    path = ROOT / record["path"]
    check(path.is_file() and digest(path) == record["sha256"], f"stale source: {path}")
    check(path.stat().st_size == record["bytes"], f"source size: {path}")
    return path


def close(actual, expected, label):
    check(math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), label)


def method_key(row):
    # The supplemental design has different method IDs for the same BOOTSTRAP
    # parameters, so use real algorithm parameters rather than display names.
    if row["codec"] == "deepzip":
        return "deepzip / " + row["method_params"]["model_key"]
    if row["codec"] == "dzip":
        return "dzip / " + row["method_params"]["mode"]
    return row["codec"]


def group_key(row):
    return row["dataset_id"], row["fidelity"], row["kind"], row["profile_id"]


def row_ref(row):
    return {key: row[key] for key in ("configuration", "run", "run_id", "case_id", "codec", "method_id",
                                     "dataset_id", "fidelity", "profile_id", "lifecycle", "raw_object_id")}


def metrics(row):
    if not row["complete_case"]:
        return None
    values = row["metrics"]
    size = values["codec_complete_bytes"]["median"]
    result = {"compression_ratio": row["raw_bytes"] / size, "codec_complete_bytes": size,
              "bits_per_value": values["bits_per_value"]["median"]}
    for op in ("encode", "decode"):
        scale = row["raw_bytes"] * 1e9 / 2**20
        times = values[op + "_ns"]
        result[op + "_MiB_s"] = scale / times["median"]
        result[op + "_MiB_s_low"] = scale / times["q3"]
        result[op + "_MiB_s_high"] = scale / times["q1"]
    return result


def load_sources():
    path = ROOT / "docs/all_core_evidence.json"
    evidence = json.loads(path.read_text())
    check(evidence["audit_passed"], "all-core audit did not pass")
    records = [identity(path)]
    for record in evidence["generated_reports"]:
        records.append(identity(read_verified(record)))
    # Confirm the saved manifest/raw/report files are still the ones audited.
    # This only hashes files; it never imports a bridge or runs a codec.
    for run in evidence["runs"]:
        check(run["source_id"] == evidence["source_id"], "mixed execution source")
        for record in run["files"]:
            records.append(identity(read_verified(record)))
    csv_path = ROOT / "docs/all_core_results/primary.csv"
    csv_rows = list(csv.DictReader(csv_path.open()))
    check(len(csv_rows) == len(evidence["cases"]), "CSV/evidence row count")
    for saved, row in zip(csv_rows, evidence["cases"]):
        for key in ("run_id", "case_id", "configuration", "codec", "dataset_id", "lifecycle", "fidelity"):
            check(saved[key] == row[key], f"CSV/evidence {key}")
        if row["complete_case"]:
            for key in METRICS:
                close(float(saved[key]), metrics(row)[key], f"CSV/evidence metric: {key}")
    cards = {}
    audited = {r["path"]: r for r in evidence["audited_files"]}
    for codec in evidence["coverage"]:
        if codec == "raw-store":
            continue
        card = ROOT / "registry/codecs" / (codec + ".json")
        record = identity(card)
        check(record["path"] in audited and record["sha256"] == audited[record["path"]]["sha256"],
              f"codec capability changed since measurement: {codec}")
        cards[codec] = json.loads(card.read_text())
        records.append(record)
    records.extend(identity(ROOT / p) for p in ("benchmark/src/tsbench/native.py", "benchmark/native/core.hpp"))
    gpu = ROOT / "registry/gpu/cuszp-fixed-1d.json"
    records.append(identity(gpu))
    rows = [r for r in evidence["cases"] if r["codec"] != "raw-store"]
    check(set(cards) == {r["codec"] for r in rows}, "capability/result codec set")
    seen = set()
    for row in rows:
        check(row["boundary"] == "native_core" and row["lifecycle"] in LIFECYCLES, "unexpected boundary")
        key = (*group_key(row), method_key(row), row["lifecycle"])
        check(key not in seen, f"duplicate visual case: {key}")
        seen.add(key)
        if row["complete_case"]:
            check(row["ok_primary_trials"] == row["planned_trials"] == row["nominal_trials"], "incomplete trials")
            check(row["input_geometry_verified"] and len(row["codec_input_ids"]) == 1, "input identity")
            for op in ("encode", "decode"):
                t = row["metrics"][op + "_ns"]
                check(0 < t["q1"] <= t["median"] <= t["q3"], "invalid duration quantiles")
        else:
            check(row["case_status"] == "unsupported", "new failure must be handled explicitly")
    return evidence, rows, cards, records


def groups_and_pairs(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[group_key(row)].append(row)
    result = []
    for key, members in grouped.items():
        pairs = {}
        for row in members:
            pairs.setdefault(method_key(row), {})[row["lifecycle"]] = row
        check(all(set(pair) == set(LIFECYCLES) for pair in pairs.values()), f"missing lifecycle: {key}")
        for pair in pairs.values():
            a, b = (pair[mode] for mode in LIFECYCLES)
            for field in ("raw_object_id", "raw_bytes", "dtype", "shape", "layout", "method_params", "complete_case"):
                check(a[field] == b[field], f"unmatched lifecycle {field}: {key}")
        first = members[0]
        check(len({r["raw_object_id"] for r in members}) == 1, f"mixed object: {key}")
        check(len({r["codec_input_ids"][0] for r in members if r["complete_case"]}) == 1, f"mixed codec input: {key}")
        slug = key[0] + "--" + key[1] + "--" + key[3]
        result.append({"key": list(key), "slug": slug, "pairs": pairs, "example": first})
    return result


def average_specs():
    return [
        {"id": "real-values", "title": "真实 values：三来源等权平均", "en": "Real values / source-balanced mean",
         "datasets": list(REAL_VALUES), "fidelity": "bitwise", "source_balanced": True},
        {"id": "fixture-f64-lossless", "title": "float64 fixture：C/F 平均", "en": "Float64 fixture / C-F mean",
         "datasets": ["float64-c", "float64-f"], "fidelity": "bitwise"},
        {"id": "fixture-f32-lossless", "title": "float32 fixture：C/F 平均", "en": "Float32 fixture / C-F mean",
         "datasets": ["float32-c", "float32-f"], "fidelity": "bitwise"},
        {"id": "fixture-i16-lossless", "title": "int16 fixture：C/F 平均", "en": "Int16 fixture / C-F mean",
         "datasets": ["int16-c", "int16-f"], "fidelity": "bitwise"},
        {"id": "fixture-f64-abs", "title": "float64 ABS≤0.01：C/F 平均", "en": "Float64 ABS <= 0.01 / C-F mean",
         "datasets": ["float64-c", "float64-f"], "fidelity": "bounded_abs"},
        {"id": "fixture-f32-abs", "title": "float32 ABS≤0.01：C/F 平均", "en": "Float32 ABS <= 0.01 / C-F mean",
         "datasets": ["float32-c", "float32-f"], "fidelity": "bounded_abs"},
        {"id": "real-records", "title": "真实 T+V：两来源平均", "en": "Joint T+V / two-source mean",
         "datasets": ["etth1-records-c", "weather-records-c"], "fidelity": "bitwise"},
    ]


def aggregate(rows, spec):
    selected = [r for r in rows if r["dataset_id"] in spec["datasets"] and r["fidelity"] == spec["fidelity"]]
    check(selected, "empty average cohort")
    check(len({r["profile_id"] for r in selected}) == 1, "average mixes thread profiles")
    check(len({r["kind"] for r in selected}) == len({r["dtype"] for r in selected}) == 1, "average mixes kind/dtype")
    methods = list(dict.fromkeys(method_key(r) for r in selected))
    output = {}
    for name in methods:
        output[name] = {}
        for lifecycle in LIFECYCLES:
            members = [r for r in selected if method_key(r) == name and r["lifecycle"] == lifecycle]
            check(len(members) == len(spec["datasets"]), "inconsistent requested average denominator")
            check(len({json.dumps(r["method_params"], sort_keys=True) for r in members}) == 1, "average mixes parameters")
            valid = [r for r in members if r["complete_case"]]
            entry = {"requested": len(members), "complete": len(valid), "members": [row_ref(r) for r in members],
                     "metrics": None, "reason": None}
            if len(valid) != len(members):
                entry["reason"] = "incomplete fixed cohort; no successful-subset average"
            else:
                weighted = defaultdict(list)
                for row in valid:
                    # C/F are repeated layouts of the same source, not extra sources.
                    source = row["dataset_id"].split("-", 1)[0] if spec.get("source_balanced") else row["dataset_id"]
                    weighted[source].append(row)
                entry["metrics"] = {key: statistics.mean(statistics.mean(metrics(r)[key] for r in source_rows)
                                                          for source_rows in weighted.values()) for key in METRICS}
                entry["weight_units"] = {source: len(v) for source, v in weighted.items()}
            output[name][lifecycle] = entry
    return {**spec, "methods": output}


def number(value, digits=3):
    if value is None:
        return "—"
    return f"{value:.{digits}g}" if value and (abs(value) < .01 or abs(value) >= 10000) else f"{value:.{digits}f}"


def escaped(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def plot_style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.titlesize": 12, "axes.labelsize": 10,
                         "svg.fonttype": "none", "svg.hashsalt": "tsbench-all-core-visual-report",
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#9ba5af", "text.color": "#24323f",
                         "axes.labelcolor": "#24323f", "xtick.color": "#4e5e6d", "ytick.color": "#24323f"})
    return plt


def save_figure(fig, directory, slug, plt):
    directory.mkdir(parents=True, exist_ok=True)
    fig.savefig(directory / (slug + ".png"), dpi=160, facecolor="white")
    fig.savefig(directory / (slug + ".svg"), metadata={"Date": None}, facecolor="white")
    plt.close(fig)


def paired_plot(pairs, title, subtitle, directory, slug, colors, plt, *, average=False):
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
    names = list(pairs)
    height = max(5.5, 2.4 + len(names) * .48)
    fig, axes = plt.subplots(1, 3, figsize=(15.6, height), sharey=True)
    # Reserve physical space for headings and footers, including short plots.
    fig.subplots_adjust(left=.19, right=.975, top=1 - 1.2 / height, bottom=1.25 / height, wspace=.25)
    fig.suptitle(title, y=1 - .18 / height, fontsize=16, weight="medium")
    fig.text(.19, 1 - .65 / height, subtitle, fontsize=10, color="#637282")
    for column, (ax, metric, heading) in enumerate(zip(axes, METRICS,
                                                    ("Compression ratio (×)", "Native encode", "Native decode"))):
        values = []
        extents = []
        for pair in pairs.values():
            for mode in LIFECYCLES:
                value = pair[mode]["metrics"] if average else metrics(pair[mode])
                if value is not None:
                    values.append(value[metric])
                    extents.extend((value[metric + "_low"], value[metric + "_high"])
                                   if column and not average else (value[metric],))
        logarithmic = column != 0 or (values and min(values) < .01)
        if logarithmic:
            ax.set_xscale("log")
        for i, name in enumerate(names):
            if i % 2 == 0:
                ax.axhspan(i - .48, i + .48, facecolor="#f4f7f9", zorder=0)
            for j, mode in enumerate(LIFECYCLES):
                row = pairs[name][mode]
                data = row["metrics"] if average else metrics(row)
                y = i + (-.17 if j == 0 else .17)
                color = colors[name.split(" / ")[0]]
                if data is None:
                    ax.text(.02, y, "N/A" if average else "N/S", transform=ax.get_yaxis_transform(), ha="left", va="center",
                            fontsize=8, color="#b26a23")
                    continue
                value = data[metric]
                label_x = value
                # Positive left edge is required for bars on a log axis.
                baseline = min(values) * .42 if logarithmic else 0
                ax.barh(y, value - baseline, left=baseline, height=.29,
                        color=color if j == 0 else "white", edgecolor=color,
                        linewidth=.9, hatch=None if j == 0 else "////", zorder=2)
                if column and not average:
                    low, high = data[metric + "_low"], data[metric + "_high"]
                    ax.errorbar(value, y, xerr=[[max(0, value-low)], [max(0, high-value)]], fmt="none",
                                ecolor="#2b3540", elinewidth=.75, capsize=2, capthick=.75, zorder=3)
                    label_x = high
                ax.annotate(number(value, 2), (label_x, y), xytext=(5, 0), textcoords="offset points",
                            ha="left", va="center", fontsize=7.6, color="#24323f", zorder=4)
        if values:
            if logarithmic:
                # Leave room for labels without adding an arbitrary 1x baseline
                # to neural frames whose compression ratios are all very small.
                ax.set_xlim(min(extents) * .4, max(extents) * 3.1)
            else:
                ax.set_xlim(0, max(1, max(values)) * 1.22)
        if logarithmic:
            low, high = ax.get_xlim()
            if high / low < 100:
                ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5), numticks=6))
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
            ax.xaxis.set_minor_formatter(NullFormatter())
        if column == 0 and ax.get_xlim()[0] < 1 < ax.get_xlim()[1]:
            ax.axvline(1, color="#8f9ba6", linewidth=.8, linestyle=(0, (3, 3)), zorder=1)
        ax.set_title(heading, pad=12)
        ax.set_xlabel("Input bytes / complete codec bytes" + (" (log)" if logarithmic else "") if column == 0 else "MiB/s (log scale)")
        ax.set_yticks(range(len(names)))
        if column == 0:
            labels = []
            for name in names:
                pair = pairs[name]
                labels.append(name + (f"  [{pair['prepared']['complete']}/{pair['prepared']['requested']}]" if average else ""))
            ax.set_yticklabels(labels, fontsize=9)
        ax.tick_params(axis="y", length=0, pad=8)
        ax.grid(axis="x", which="major", color="#dce3e8", linewidth=.7, alpha=.8)
        ax.set_axisbelow(True)
    axes[0].set_ylim(len(names) - .48, -.48)
    legend = [Patch(facecolor="#637d94", edgecolor="#637d94", label="prepared"),
              Patch(facecolor="white", edgecolor="#637d94", hatch="////", label="fresh_request")]
    fig.legend(handles=legend, loc="lower center", bbox_to_anchor=(.59, .35 / height), ncols=2, frameon=False)
    caption = ("Mean of case medians; [valid/requested inputs]; N/A = incomplete cohort; no confidence intervals"
               if average else "Case median; whiskers = duration Q3/Q1 inverted; N/S = unsupported, never zero performance")
    fig.text(.59, .12 / height, caption, ha="center", fontsize=8.5, color="#637282")
    save_figure(fig, directory, slug, plt)


def overview_plot(rows, directory, plt):
    import numpy as np
    selected = { (r["dataset_id"], r["codec"]): r for r in rows
                if r["dataset_id"] in REAL_VALUES and r["lifecycle"] == "prepared" and r["fidelity"] == "bitwise" }
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.3))
    fig.subplots_adjust(left=.06, right=.985, bottom=.26, top=.83, wspace=.32)
    x = np.arange(5)
    for i, codec in enumerate(("lz4-frame", "snappy-raw", "zstd-frame")):
        values = [metrics(selected[d, codec]) for d in REAL_VALUES]
        at = x + (i - 1) * .24
        for column, (ax, metric) in enumerate(zip(axes, METRICS)):
            med = np.array([v[metric] for v in values])
            errors = None if column == 0 else [med - [v[metric + "_low"] for v in values],
                                               np.array([v[metric + "_high"] for v in values]) - med]
            ax.bar(at, med, width=.24, color=COLORS[codec], label=codec, yerr=errors,
                   capsize=2, error_kw={"elinewidth": .8, "capthick": .8})
    for i, (ax, heading) in enumerate(zip(axes, ("Compression ratio (×)", "Native encode", "Native decode"))):
        ax.set_title(heading, pad=10)
        ax.set_xticks(x, [LABELS[d] for d in REAL_VALUES], rotation=25, ha="right")
        ax.grid(axis="y", color="#dce3e8", alpha=.7)
        ax.set_axisbelow(True)
        if i:
            ax.set_yscale("log")
            ax.set_ylabel("MiB/s (log scale)")
        else:
            ax.set_ylabel("Input bytes / complete codec bytes")
    fig.suptitle("Direct codec APIs / prepared / natural cache", fontsize=15, y=.96)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(.5, .015), ncols=3,
               title="Five real value objects / 14 batches per case / duration Q1-Q3 inverted", frameon=False)
    save_figure(fig, directory, "fast-codecs-overview", plt)


def capability_data(rows, cards):
    data = []
    for codec, card in sorted(cards.items()):
        members = [r for r in rows if r["codec"] == codec]
        good = [r for r in members if r["complete_case"]]
        counts = {mode: {"complete": sum(r["complete_case"] for r in members if r["lifecycle"] == mode),
                         "requested": sum(r["lifecycle"] == mode for r in members)} for mode in LIFECYCLES}
        data.append({"codec": codec, "dtypes": card["input"]["dtypes"], "ranks": card["input"]["ranks"],
                     "registered_layouts": card["input"].get("layouts", []),
                     "tested_layouts": sorted({r["layout"] for r in good}),
                     "loss_modes": card["semantics"]["loss_modes"], "features": card["features"],
                     "isa_registered": card["execution"]["isa"],
                     "isa_parameters": sorted({r["method_params"].get("isa", "未单列") for r in good}),
                     "threads_measured": sorted({r["profile"]["native_threads"] for r in good}),
                     "native_core": all(counts[m]["complete"] > 0 for m in LIFECYCLES),
                     "joint_records_measured": any(r["kind"] == "records" for r in good),
                     "lifecycles": counts, "notes": NOTES.get(codec, "独立完整流；具体参数、源域和长度上限见登记卡片"),
                     "registry": "registry/codecs/" + codec + ".json"})
    return data


def capability_plot(capabilities, directory, plt):
    import numpy as np
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    columns = ["Float32\nregistered", "Float64\nregistered", "Signed int\nregistered", "Unsigned int\nregistered",
               "Lossless\nregistered", "ABS bound\nregistered", "Empirical\nregistered", "Core P+F\nmeasured",
               "Joint T+V\nmeasured", "Stream\nregistered", "Query / RA\nregistered"]
    matrix = []
    for c in capabilities:
        dtypes = c["dtypes"]
        f = c["features"]
        matrix.append([int("<f4" in dtypes), int("<f8" in dtypes), int(any("i" in d for d in dtypes)),
                       int(any("u" in d for d in dtypes)), int("LOSSLESS" in c["loss_modes"]),
                       int("ERROR_BOUNDED_LOSSY" in c["loss_modes"]), int("UNBOUNDED_LOSSY" in c["loss_modes"]),
                       2 if c["native_core"] else -1, 2 if c["joint_records_measured"] else -1,
                       int(f["streaming"]), int(f["query"] and f["random_access"])])
    values = np.array(matrix)
    fig, ax = plt.subplots(figsize=(14, 14))
    fig.subplots_adjust(left=.24, right=.97, top=.87, bottom=.09)
    cmap = ListedColormap(["#f6f7f9", "#e1e5e9", "#91cfbf", "#087f70"])
    ax.imshow(values, cmap=cmap, norm=BoundaryNorm([-1.5, -.5, .5, 1.5, 2.5], cmap.N), aspect="auto")
    ax.set_xticks(range(len(columns)), columns, fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(capabilities)), [c["codec"] for c in capabilities], fontsize=9)
    ax.tick_params(length=0, pad=8)
    ax.set_xticks(np.arange(-.5, len(columns), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(capabilities), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.1)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v = values[i, j]
            ax.text(j, i, {2: "Y", 1: "Y", 0: "-", -1: "n/t"}[v], ha="center", va="center",
                    fontsize=8, color="white" if v == 2 else "#46606a")
    fig.suptitle("Current CPU codec capability matrix / 37 codecs", fontsize=16, y=.97)
    fig.text(.24, .93, "Registered capability and measured support are distinct. Domain restrictions still apply.", fontsize=10)
    legend = [Patch(facecolor=cmap(i), label=label) for i, label in enumerate(
        ("Not tested in this workload", "Not registered", "Registered support", "Measured in this report"))]
    fig.legend(handles=legend, loc="lower center", bbox_to_anchor=(.58, .025), ncols=2, frameon=False)
    save_figure(fig, directory, "capability-matrix", plt)


def workload_matrix(rows, capabilities, directory, plt):
    import numpy as np
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    datasets = list(dict.fromkeys(r["dataset_id"] for r in rows))
    data = []
    for capability in capabilities:
        cells = []
        for dataset in datasets:
            members = [r for r in rows if r["codec"] == capability["codec"] and r["dataset_id"] == dataset
                       and r["lifecycle"] == "prepared"]
            count = sum(r["complete_case"] for r in members)
            cells.append({"requested": len(members), "complete": count,
                          "status": "not_requested" if not members else "complete" if count == len(members) else "unsupported",
                          "members": [row_ref(r) for r in members]})
        data.append({"codec": capability["codec"], "cells": cells})
    values = np.array([[{"not_requested": 0, "unsupported": 1, "complete": 2}[c["status"]]
                        for c in item["cells"]] for item in data])
    fig, ax = plt.subplots(figsize=(16, 14.2))
    fig.subplots_adjust(left=.22, right=.98, bottom=.17, top=.90)
    cmap = ListedColormap(["#f1f3f6", "#e7b47a", "#087f70"])
    ax.imshow(values, cmap=cmap, norm=BoundaryNorm([-.5, .5, 1.5, 2.5], 3), aspect="auto")
    ax.set_xticks(range(len(datasets)), [LABELS[d] for d in datasets], rotation=60, ha="right", fontsize=9)
    ax.set_yticks(range(len(capabilities)), [c["codec"] for c in capabilities], fontsize=9)
    ax.tick_params(length=0, pad=8)
    ax.set_xticks(np.arange(-.5, len(datasets), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(capabilities), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1)
    for i, item in enumerate(data):
        for j, cell in enumerate(item["cells"]):
            if cell["requested"]:
                ax.text(j, i, f"{cell['complete']}/{cell['requested']}", ha="center", va="center", fontsize=7.8,
                        color="white" if cell["status"] == "complete" else "#6c3f12")
    fig.suptitle("Observed dataset support / prepared / fixed request matrix", fontsize=16, y=.97)
    fig.text(.22, .935, "Cells = valid / requested cases. Blank = not requested, not a claim of unsupported capability.", fontsize=10)
    fig.legend(handles=[Patch(facecolor=cmap(i), label=t) for i, t in enumerate(
        ("Not requested", "Requested but unsupported", "All requested cases valid"))],
        loc="lower center", bbox_to_anchor=(.57, .015), ncols=3, frameon=False)
    save_figure(fig, directory, "dataset-support-matrix", plt)
    return {"datasets": datasets, "rows": data}


def image_block(slug, alt):
    return [f"![{alt}](figures/{slug}.png)", "", f"[下载 SVG](figures/{slug}.svg)", ""]


def average_table(average):
    lines = ["| codec | 有效／固定输入数 | 平均压缩倍数 P / F | 平均编码 MiB/s P / F | 平均解码 MiB/s P / F |",
             "|---|---:|---:|---:|---:|"]
    for name, pair in average["methods"].items():
        a = pair["prepared"]
        values = []
        for metric in METRICS:
            values.append(" / ".join(number(pair[m]["metrics"][metric]) if pair[m]["metrics"] else "—" for m in LIFECYCLES))
        lines.append(f"| {name} | {a['complete']}/{a['requested']} | " + " | ".join(values) + " |")
    return lines + [""]


def case_table(group):
    lines = ["| codec | 完整输出 bytes | 压缩倍数 | 编码 MiB/s P / F | 解码 MiB/s P / F | P/F有效批次数 |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, pair in group["pairs"].items():
        p, f = (pair[mode] for mode in LIFECYCLES)
        mp, mf = metrics(p), metrics(f)
        values = [f"{mp['codec_complete_bytes']:,.0f}" if mp else "—", number(mp["compression_ratio"]) if mp else "—"]
        for op in ("encode", "decode"):
            values.append(" / ".join(number(m[op + "_MiB_s"]) if m else "—" for m in (mp, mf)))
        trials = " / ".join(f"{r['ok_primary_trials']}/{r['planned_trials']}" for r in (p, f))
        lines.append(f"| {escaped(name)} | " + " | ".join(values) + f" | {trials} |")
    lines.append("")
    rejected = [pair["prepared"] for pair in group["pairs"].values() if not pair["prepared"]["complete_case"]]
    for row in rejected:
        lines.append(f"- `{row['codec']}`：unsupported，{row['reason'].strip()}。两个生命周期均保留该拒绝，图中 N/S 不代表零性能。")
    if rejected:
        lines.append("")
    first = group["example"]
    if first["fidelity"] != "bitwise":
        lines += ["| codec | 最大绝对误差（P/F 最坏值） | RMSE（P/F 最坏值） |", "|---|---:|---:|"]
        for name, pair in group["pairs"].items():
            worst = [max(pair[m]["quality"][metric]["max"] for m in LIFECYCLES) for metric in ("max_abs", "rmse")]
            lines.append(f"| {name} | {number(worst[0], 6)} | {number(worst[1], 6)} |")
        lines += [""]
    if first["codec"] in {"deepzip", "dzip"}:
        for name, pair in group["pairs"].items():
            counts = pair["prepared"]["neural_path"]["counts"]
            lines.append(f"- {name}：每次 encode/decode 各 {counts['uniform_symbols']} 个 uniform symbols、{counts['predict_calls']} 次 predict、"
                         f"{counts['online_train_batches']} 次训练批、{counts['adam_steps']} 次 Adam 更新、更新后 {counts['post_update_predict_calls']} 次 predict"
                         "（源码推导，非动态计数）。")
        lines.append("")
    return lines


def dtype_label(types):
    return ", ".join(t[1] + str(int(t[2:]) * 8) for t in sorted(types))


def report_text(rows, groups, averages, capabilities):
    complete = sum(r["complete_case"] for r in rows)
    planned = sum(r["planned_trials"] for r in rows)
    lines = ["# 全量 codec 原生结果可视化报告", "", "生成日期：2026-10-16。",
             "", "基于[完整结果](README.md)、[逐案例原始汇总](primary.csv)和[审计证据](../all_core_evidence.json)绘制，沿用[原生结果报告](../native_results/README.md)的压缩倍数／编码吞吐／解码吞吐三联图。",
             "", f"本页覆盖 **37 个 CPU codec、17 个输入对象、{len(groups)} 个同条件任务组**。已移除 raw-store 的全部图柱、表格行和平均值成员；剩余 **{len(rows)} 个请求、{complete} 个完整有效案例、{len(rows)-complete} 个 unsupported 请求，{planned}/{planned} 个正式批次成功**。两种生命周期各174个请求，其中169个有效、5个拒绝。未执行新的 codec 测量。",
             "", "[快速概览](#quick-view) · [平均结果](#averages) · [逐数据集结果](#datasets) · [能力支持矩阵](#capabilities) · [统计口径与复现](#methodology)",
             "", "压缩倍数 = 有效输入 bytes / 完整 codec 输出 bytes，越大越好；编码／解码均以有效原始 bytes 归一化，单位 MiB/s。必要 codec header、模型与结束数据已计入；实验管理 JSON/hash 不计入。图中没有 raw 基线柱；1×虚线仅表示膨胀分界。",
             "", "实心柱为 **prepared**，斜线空心柱为 **fresh_request**。两种生命周期并列，不混合统计；吞吐轴使用对数刻度。单案例柱取14批次时长的中位数反算，误差线按时长Q3/Q1反算；这是描述范围，不是置信区间。", "",
             '<a id="quick-view"></a>', "", "## 通用快速编码器概览", "",
             "下面保留示例图的五个真实输入和三种通用快速编码器，使用本轮全量结果中的 prepared 数值。其余算法及 fresh_request 在后面的完整图中展示。", ""]
    lines += image_block("fast-codecs-overview", "五个真实输入上的 LZ4、Snappy、Zstd；无 raw 基线")
    lines += ['<a id="averages"></a>', "", "## 平均结果", "",
              "平均值对每个案例先取正式批次中位数，再对同任务输入求算术平均。真实 values 先对同来源的 C/F 布局平均，再对 ETTh1、weather、ILI 三个来源等权平均；其权重为各ETTh1布局1/6、各weather布局1/6、ILI为1/3。fixture 的C/F平均仅描述布局，不增加独立来源数。这里平均的是各案例的压缩倍数和吞吐量，不是合并文件后的总字节比或总吞吐；平均压缩倍数的倒数也不等于平均存储占比。", "",
              "每组固定输入集合；某算法缺少任一输入时，平均指标留空（图中N/A），并保留有效／请求数。ALP 在真实 values 仅3/5有效，三个矩阵Sprintz方法在int16仅1/2有效，均不以成功子集替代固定集合平均。平均图不绘制批次IQR或推断区间。P/F分别表示prepared/fresh_request。", ""]
    for average in averages:
        lines += [f"### {average['title']}", ""]
        lines += image_block("mean-" + average["id"], average["title"])
        lines += ["<details>", "<summary>平均数值表</summary>", ""] + average_table(average) + ["</details>", ""]
    singleton = ["uint8-c", "uint32-c", "ili-values-c（empirical_quality）", "symbols4-c-n64", "symbols4-c"]
    lines += ["其余组（" + "、".join(singleton) + "）只有一个输入对象／模型路径，不额外制造跨数据集均值；它们的全部数值见对应单独图。DeepZip/DZip 的64/257符号、不同mode和线程profile始终分开。", "",
              '<a id="datasets"></a>', "", "## 逐数据集结果", "",
              "每个输入对象独立展示。无损、ABS有损、经验质量及不同线程profile分别成图。图内顺序沿用冻结配置，不按最有利指标重排。所有算法和模型路径均可在下表或能力矩阵定位。", "",
              "| 输入对象 | 数据类别 | dtype／shape／布局 | 同条件图数 |", "|---|---|---|---:|"]
    datasets = list(dict.fromkeys(r["dataset_id"] for r in rows))
    for dataset in datasets:
        sample = next(r for r in rows if r["dataset_id"] == dataset)
        lines.append(f"| [{dataset}](#dataset-{dataset}) | {'真实来源' if sample['real_data'] else '开发 fixture'} | "
                     f"{escaped(sample['dtype'])} / {'×'.join(map(str,sample['shape']))} / {sample['layout']} | "
                     f"{sum(g['key'][0]==dataset for g in groups)} |")
    lines.append("")
    for dataset in datasets:
        members = [g for g in groups if g["key"][0] == dataset]
        sample = members[0]["example"]
        lines += [f'<a id="dataset-{dataset}"></a>', "", f"### {dataset}", "",
                  f"输入：`{sample['dtype']}`、`{sample['shape']}`、{sample['layout']}布局；有效原始数据 **{sample['raw_bytes']:,} bytes**，"
                  f"{sample['value_count']:,} values、{sample['timestamp_count']:,} timestamps。", ""]
        if sample["kind"] == "records":
            lines += ["联合 T+V 任务：分母各包含一次原始 T 和 V；压缩输出为完整 EncXOR。它与 V-only 图属于不同任务。", ""]
        for group in members:
            first = group["example"]
            threads = first["profile"]["native_threads"]
            lines += [f"**{FIDELITIES[first['fidelity']]} · {first['kind']} · {first['profile_id']}（{threads}线程）**", ""]
            lines += image_block(group["slug"], f"{dataset} {first['fidelity']} prepared与fresh结果")
            lines += ["<details>", "<summary>完整数值、质量及拒绝原因</summary>", ""] + case_table(group) + ["</details>", ""]
    lines += ['<a id="capabilities"></a>', "", "## 当前算法能力支持矩阵", "",
              "范围为当前接入实现及其约束，不代表上游算法的全部可能能力。浅绿色表示登记支持，深绿色表示本轮实际完成，未请求的能力不推断为不支持。dtype登记支持仍需满足源域、长度、布局、模型alphabet等限制。", ""]
    lines += image_block("capability-matrix", "37个CPU算法的登记能力与实测能力矩阵")
    lines += ["### 数据类型、运行路径与有效覆盖", "",
              "rank列来自登记；C/F列仅列本轮通过的布局；P/F覆盖为有效案例数／请求数（包含有损组和神经补充路径）。dtype数字以bit为单位。ISA列先列登记项，再列本轮方法参数；未单列的参数不推断为SCALAR，也不代表动态指令追踪或峰值性能。", "",
              "| codec | 登记dtype | 登记rank | 实测布局 | 保真模式 | 实测线程 | ISA（登记 → 参数） | P覆盖 / F覆盖 |", "|---|---|---|---|---|---|---|---|"]
    loss_labels = {"LOSSLESS": "无损", "ERROR_BOUNDED_LOSSY": "ABS有损", "UNBOUNDED_LOSSY": "经验质量"}
    for c in capabilities:
        counts = " / ".join(f"{c['lifecycles'][m]['complete']}/{c['lifecycles'][m]['requested']}" for m in LIFECYCLES)
        isa = ",".join(c["isa_registered"]) + " → " + ",".join(c["isa_parameters"])
        lines.append(f"| [{c['codec']}](../../{c['registry']}) | {dtype_label(c['dtypes'])} | "
                     f"{','.join(map(str,c['ranks']))} | {','.join(c['tested_layouts'])} | "
                     f"{','.join(loss_labels[v] for v in c['loss_modes'])} | {','.join(map(str,c['threads_measured']))} | "
                     f"{isa} | {counts} |")
    lines += ["", "### 功能支持与实现限制", "",
              "流式／查询／随机访问列为登记能力。当前native批次executor明确不测stream/query/GPU，因此这些勾选不表示本轮已有相应性能结果；NeaTS/LeaTS的query/RA也未在这里实测。除Gorilla联合T/V外，当前native批次要求单一投影组件、identity路由，不接受外部分列／chunk／transform方案。", "",
              "| codec | 流式（登记） | 查询（登记） | 随机访问（登记） | 当前路径的重要限制 |", "|---|---|---|---|---|"]
    for c in capabilities:
        f = c["features"]
        lines.append(f"| {c['codec']} | {'✓' if f['streaming'] else '—'} | {'✓' if f['query'] else '—'} | "
                     f"{'✓' if f['random_access'] else '—'} | {c['notes']} |")
    lines += ["", "CPU矩阵中的37个codec均有native_core的prepared和fresh_request有效案例；其余36个为单线程，本轮DZip使用3线程profile。GPU另有已登记的[cuSZp fixed-1d](../../registry/gpu/cuszp-fixed-1d.json)：CUDA、rank1 C连续f32/f64、ABS任务，输入限制有限normal或正零、量化范围及逐产物质量检查；它未纳入本轮CPU全量native_core结果，故不填入这些平均图。既有GPU结果见[独立报告](../gpu_results/README.md)。", "",
              "### 本轮数据集上的实际支持", "",
              "矩阵使用prepared案例，格内为有效／请求数；fresh的状态与之逐项一致。空格表示没有请求。DeepZip/DZip的短流、神经预测和DZip模式按冻结请求分别计数；橙色为明确unsupported，未绘成零吞吐。", ""]
    lines += image_block("dataset-support-matrix", "全部算法在17个输入对象上的实际请求支持矩阵")
    lines += ['<a id="methodology"></a>', "", "## 统计口径与复现", "",
              "- 单案例：每个生命周期2 sessions×7 rounds，14个正式原生批次；批次时间除以内循环次数后汇总。普通／DeepZip为8次测量操作/批，DZip为2次；各批另有2次warmup。内循环不增加独立数据集或独立session数。",
              "- prepared：预建context和调用方buffer；每次必需reset、采样、建模、编码／finalize仍计时。fresh_request另外计创建、配置、bound和调用方分配；保留产物buffer的最终释放在计时外，也不是冷进程启动时间。",
              "- 所有图均为本机、已冻结构建、natural cache的描述结果。保真类型、dtype、线程、模型路径不同的组分别展示，不合并成全算法总排名。ABS/经验质量图必须连同实际误差阅读。",
              "- 本工具核对完整结果文件与全部28个run的manifest/raw/report哈希、CSV与证据中的指标、生命周期配对及输入身份；只读取既有测量。现有raw、原完整结果、历史native_results及其证据索引均未改写。", "",
              "图像均同时提供PNG/SVG。[可视化数值CSV](visual_cases.csv)、[分组平均CSV](visual_averages.csv)、[绘图数据与源身份](visual_data.json)保存每个图值的案例引用及输入hash。", "",
              "在项目根目录重新生成本页（不运行codec）：", "", "```bash",
              "MPLCONFIGDIR=/tmp/tsbench-matplotlib python benchmark/tools/visualize_all_core_results.py", "```", ""]
    return "\n".join(lines)


def csv_content(rows, columns):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def case_csv(rows):
    fields = ["dataset_id", "codec", "method", "fidelity", "profile_id", "lifecycle", "dtype", "shape", "layout",
              "raw_bytes", "codec_complete_bytes", *METRICS, "encode_MiB_s_low", "encode_MiB_s_high",
              "decode_MiB_s_low", "decode_MiB_s_high", "complete_case", "reason", "configuration", "run", "case_id"]
    exported = []
    for row in rows:
        output = {key: row[key] for key in fields if key in row}
        output["shape"] = json.dumps(row["shape"])
        output["method"] = method_key(row)
        output.update(metrics(row) or {})
        output.pop("bits_per_value", None)
        exported.append(output)
    return csv_content(exported, fields)


def average_csv(averages):
    fields = ["cohort", "method", "lifecycle", "valid_inputs", "requested_inputs", *METRICS, "reason", "weight_units"]
    output = []
    for average in averages:
        for name, pair in average["methods"].items():
            for mode, entry in pair.items():
                output.append({"cohort": average["id"], "method": name, "lifecycle": mode,
                               "valid_inputs": entry["complete"], "requested_inputs": entry["requested"],
                               **(entry["metrics"] or {}), "reason": entry["reason"],
                               "weight_units": json.dumps(entry.get("weight_units"), sort_keys=True)})
    return csv_content(output, fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    evidence, rows, cards, sources = load_sources()
    groups = groups_and_pairs(rows)
    averages = [aggregate(rows, spec) for spec in average_specs()]
    capabilities = capability_data(rows, cards)
    report = report_text(rows, groups, averages, capabilities)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/tsbench-matplotlib")
    plt = plot_style()
    palette = list(plt.get_cmap("tab20").colors) + list(plt.get_cmap("tab20b").colors)
    colors = {codec: COLORS.get(codec, palette[i]) for i, codec in enumerate(sorted(cards))}
    output.parent.mkdir(parents=True, exist_ok=True)
    before = {r["path"]: r["sha256"] for r in sources}
    with tempfile.TemporaryDirectory(prefix="all-core-visual-", dir=output.parent) as temporary:
        staging = Path(temporary)
        figures = staging / "figures"
        overview_plot(rows, figures, plt)
        for group in groups:
            first = group["example"]
            subtitle = (f"{first['kind']} / {first['fidelity']} / {first['dtype']} / shape {first['shape']} / "
                        f"{first['raw_bytes']:,} input bytes / {first['profile']['native_threads']} thread(s)")
            paired_plot(group["pairs"], LABELS[first["dataset_id"]], subtitle, figures, group["slug"], colors, plt)
        for average in averages:
            paired_plot(average["methods"], average["en"], "native_core / natural cache / prepared and fresh kept separate",
                        figures, "mean-" + average["id"], colors, plt, average=True)
        capability_plot(capabilities, figures, plt)
        matrix = workload_matrix(rows, capabilities, figures, plt)
        (staging / "visual_report.md").write_text(report, encoding="utf-8")
        (staging / "visual_cases.csv").write_text(case_csv(rows), encoding="utf-8", newline="")
        (staging / "visual_averages.csv").write_text(average_csv(averages), encoding="utf-8", newline="")
        trace = {"schema": "tsbench.all-core-visual-report/1", "date": "2026-10-16",
                 "source_id": evidence["source_id"], "generator": identity(Path(__file__)), "sources": sources,
                 "scope": {"raw_store_excluded": True, "new_codec_measurements": 0, "codecs": len(cards),
                           "dataset_objects": len({r['dataset_id'] for r in rows}), "task_groups": len(groups),
                           "requested_cases": len(rows), "complete_cases": sum(r['complete_case'] for r in rows),
                           "nominal_trials": sum(r['nominal_trials'] for r in rows),
                           "ok_trials": sum(r['ok_primary_trials'] for r in rows)},
                 "case_metrics": [{**row_ref(r), "plot_group": list(group_key(r)), "method": method_key(r),
                                   "codec_input_ids": r["codec_input_ids"], "raw_bytes": r["raw_bytes"],
                                   "complete": r["complete_case"], "reason": r["reason"], "metrics": metrics(r)} for r in rows],
                 "averages": averages, "capabilities": capabilities, "dataset_support": matrix,
                 "average_policy": "arithmetic mean of case medians; real-values source-balanced over C/F; fixed complete cohorts only; no CI",
                 "figure_uncertainty": "per-case throughput whiskers invert duration Q3/Q1; averages have no uncertainty bars",
                 "matplotlib_version": __import__("matplotlib").__version__}
        files = sorted(p for p in staging.rglob("*") if p.is_file())
        trace["outputs"] = [{"path": str(p.relative_to(staging)), "sha256": digest(p), "bytes": p.stat().st_size} for p in files]
        (staging / "visual_data.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        # Complete all checks/rendering before publishing the new presentation.
        for relative, expected in before.items():
            check(digest(ROOT / relative) == expected, f"source changed while plotting: {relative}")
        output.mkdir(parents=True, exist_ok=True)
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                destination = output / path.relative_to(staging)
                destination.parent.mkdir(parents=True, exist_ok=True)
                path.replace(destination)
    print(json.dumps({"report": str(output / "visual_report.md"), **trace["scope"],
                      "png_figures": len([f for f in trace['outputs'] if f['path'].endswith('.png')])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
