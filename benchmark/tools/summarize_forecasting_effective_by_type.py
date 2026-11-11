#!/usr/bin/env python3
"""Summarize complete prepared forecasting results by task type."""

from __future__ import annotations

import datetime as dt
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

from effective_support_matrix import render as render_support_matrix


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "docs/all_core_results/forecasting_transpose_20261023_1158"
SOURCE = SOURCE_DIR / "primary.csv"
GROUP = ["dtype", "fidelity", "kind", "profile_id"]
METRICS = [
    ("compression_ratio", "Compression ratio", "x"),
    ("encode_MiB_s", "Encode throughput", "MiB/s"),
    ("decode_MiB_s", "Decode throughput", "MiB/s"),
]
CJK_FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


def fmt(value: float) -> str:
    return f"{value:.4g}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stamp", help="Reuse a previously generated timestamped output directory")
    args = parser.parse_args()
    stamp = args.stamp or dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    out = SOURCE_DIR / f"effective_by_type_{stamp}"
    figures = out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    if CJK_FONT.is_file():
        font_manager.fontManager.addfont(str(CJK_FONT))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(CJK_FONT)).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    data = pd.read_csv(SOURCE)
    valid = data[
        (data["lifecycle"] == "prepared")
        & (data["case_status"] == "ready")
        & (data["complete_case"].astype(str).str.lower() == "true")
    ].copy()
    for metric, _, _ in METRICS:
        valid[metric] = pd.to_numeric(valid[metric], errors="coerce")
    valid = valid.dropna(subset=[metric for metric, _, _ in METRICS])

    summaries = (
        valid.groupby(GROUP + ["codec"], dropna=False)
        .agg(
            valid_datasets=("dataset_id", "nunique"),
            compression_ratio_mean=("compression_ratio", "mean"),
            compression_ratio_median=("compression_ratio", "median"),
            encode_MiB_s_mean=("encode_MiB_s", "mean"),
            encode_MiB_s_median=("encode_MiB_s", "median"),
            decode_MiB_s_mean=("decode_MiB_s", "mean"),
            decode_MiB_s_median=("decode_MiB_s", "median"),
        )
        .reset_index()
        .sort_values(GROUP + ["codec"])
    )
    summaries["loss_class"] = summaries["fidelity"].map(
        {"bitwise": "无损", "bounded_abs": "有损", "empirical_quality": "有损"}
    )
    summaries.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")

    sections = []
    group_values = list(summaries[GROUP].drop_duplicates().itertuples(index=False, name=None))
    for index, key in enumerate(group_values, 1):
        mask = pd.Series(True, index=summaries.index)
        for column, value in zip(GROUP, key):
            mask &= summaries[column].eq(value)
        chunk = summaries[mask].sort_values("codec")
        title = " · ".join(map(str, key))
        image_name = f"type-{index:02d}.png"
        fig, axes = plt.subplots(1, 3, figsize=(16, max(4.2, len(chunk) * 0.26)), constrained_layout=True)
        y = list(range(len(chunk)))
        for ax, (metric, label, unit) in zip(axes, METRICS):
            mean = chunk[f"{metric}_mean"].to_numpy()
            median = chunk[f"{metric}_median"].to_numpy()
            ax.scatter(mean, y, marker="o", label="Mean", color="#176b87", s=27, zorder=3)
            ax.scatter(median, y, marker="D", label="Median", color="#d27a25", s=24, zorder=3)
            ax.set_title(f"{label} ({unit})")
            labels = [f"{row.codec}（{row.loss_class}）" for row in chunk.itertuples()]
            ax.set_yticks(y, labels)
            ax.invert_yaxis()
            ax.grid(axis="x", color="#d9dfe3", linewidth=0.7)
            ax.set_axisbelow(True)
            if len(chunk) and min(mean.min(), median.min()) > 0:
                ax.set_xscale("log")
        axes[0].legend(frameon=False, loc="best")
        fig.suptitle(f"{title} · {len(chunk)} effective codecs", fontsize=13)
        fig.savefig(figures / image_name, dpi=150, bbox_inches="tight")
        plt.close(fig)

        rows = []
        for _, row in chunk.iterrows():
            cells = [str(row["codec"]), str(row["loss_class"]), str(int(row["valid_datasets"]))]
            for metric, _, _ in METRICS:
                cells.extend([fmt(row[f"{metric}_mean"]), fmt(row[f"{metric}_median"])])
            rows.append("| " + " | ".join(cells) + " |")
        table = "\n".join([
            "| 算法 | 性质 | 有效数据集数 | 压缩倍数均值 | 压缩倍数中位数 | 编码均值 MiB/s | 编码中位数 MiB/s | 解码均值 MiB/s | 解码中位数 MiB/s |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
        ])
        sections.append(
            f"## {title}\n\n![{title} 有效算法对比](figures/{image_name})\n\n"
            f"{table}\n"
        )

    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report = (
        "# 同类型数据的有效算法汇总\n\n"
        f"生成时间：{now}\n\n"
        "类型按 dtype、保真条件、数据组织方式和 profile 划分；统计采用 prepared 生命周期中完整有效的案例，"
        "每个算法在该类型下按数据集计算算术平均数与中位数。fresh_request 不重复计入。\n\n"
        "性质按任务保真要求标记：bitwise 为无损；bounded_abs 与 empirical_quality 为有损。\n\n"
        "吞吐分别统计编码与解码，压缩倍数单独呈现；每个类型仅列出至少有一条有效记录的算法。"
        "散点图横轴为对数刻度，圆点表示均值，菱形表示中位数。\n\n"
        + "\n".join(sections)
        + render_support_matrix(out / "summary.csv", out)
    )
    report_path = out / f"effective_by_type_{stamp}.md"
    report_path.write_text(report, encoding="utf-8")
    print(report_path)
    print(f"types={len(group_values)} algorithms={len(summaries)} valid_records={len(valid)}")


if __name__ == "__main__":
    main()
