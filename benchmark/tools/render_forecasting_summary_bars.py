#!/usr/bin/env python3
"""Render mean and median summaries as reference-style horizontal bar charts."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.patches import Patch

from effective_support_matrix import render as render_support_matrix


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "docs/all_core_results/forecasting_transpose_20261023_1158"
DEFAULT_SUMMARY = SOURCE_DIR / "effective_by_type_20261023_124601/summary.csv"
GROUP = ["dtype", "fidelity", "kind", "profile_id"]
METRICS = [
    ("compression_ratio", "Compression ratio (x)"),
    ("encode_MiB_s", "Encode (MiB/s)"),
    ("decode_MiB_s", "Decode (MiB/s)"),
]
PALETTE = [
    "#147d92", "#df9a39", "#009e73", "#cc79a7", "#0072b2", "#d55e00",
    "#56b4e9", "#e69f00", "#6b7f35", "#8172b3", "#8c564b", "#17becf",
    "#bcbd22", "#e377c2", "#4c78a8", "#f58518", "#54a24b", "#b279a2",
    "#ff9da6", "#9d755d", "#bab0ac",
]
CJK_FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


def fmt(value: float) -> str:
    return f"{value:.4g}"


def chart(chunk: pd.DataFrame, title: str, png: Path) -> None:
    codecs = chunk["codec"].tolist()
    labels = [f"{row.codec}（{row.loss_class}）" for row in chunk.itertuples()]
    y = np.arange(len(codecs))
    colors = [PALETTE[index % len(PALETTE)] for index in range(len(codecs))]
    fig, axes = plt.subplots(1, 3, figsize=(18, max(4.4, 0.37 * len(codecs) + 1.7)), sharey=True)

    for axis, (metric, label) in zip(axes, METRICS):
        for index, (codec, color) in enumerate(zip(codecs, colors)):
            mean = float(chunk.iloc[index][f"{metric}_mean"])
            median = float(chunk.iloc[index][f"{metric}_median"])
            axis.barh(y[index] - 0.19, mean, height=0.32, color=color, edgecolor=color, linewidth=0.5)
            axis.barh(y[index] + 0.19, median, height=0.32, color="white", edgecolor=color,
                      hatch="///", linewidth=0.75)
            for value, ypos, color_text in ((mean, y[index] - 0.19, "#3b4653"),
                                             (median, y[index] + 0.19, "#3b4653")):
                axis.annotate(fmt(value), (value, ypos), xytext=(3, 0), textcoords="offset points",
                              va="center", ha="left", fontsize=7.2, color=color_text, clip_on=False)
        if metric == "compression_ratio":
            axis.axvline(1, color="#919aa6", linestyle="--", linewidth=0.8)
        else:
            axis.set_xscale("log")
        axis.set_xlabel(label)
        axis.grid(axis="x", color="#dce2e7", alpha=0.8, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines["left"].set_color("#aeb8c2")
        axis.spines["bottom"].set_color("#aeb8c2")
        for row in range(len(codecs)):
            if row % 2 == 0:
                axis.axhspan(row - 0.5, row + 0.5, color="#f3f6f8", zorder=-2)
        axis.set_ylim(len(codecs) - 0.5, -0.5)

    axes[0].set_yticks(y, labels, fontsize=8)
    fig.suptitle(title, fontsize=12, color="#354252")
    fig.legend(handles=[
        Patch(facecolor="#687f91", edgecolor="#687f91", label="Mean"),
        Patch(facecolor="white", edgecolor="#687f91", hatch="///", label="Median"),
    ], loc="upper right", ncols=2, frameon=False, bbox_to_anchor=(0.99, 0.98))
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(png, dpi=150, bbox_inches="tight")
    fig.savefig(png.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--stamp", help="Override the generated timestamp")
    args = parser.parse_args()
    stamp = args.stamp or dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    out = SOURCE_DIR / f"effective_by_type_bars_{stamp}"
    figures = out / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    if CJK_FONT.is_file():
        font_manager.fontManager.addfont(str(CJK_FONT))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(CJK_FONT)).get_name()

    data = pd.read_csv(args.summary)
    sections = []
    keys = list(data[GROUP].drop_duplicates().itertuples(index=False, name=None))
    for index, key in enumerate(keys, 1):
        mask = pd.Series(True, index=data.index)
        for column, value in zip(GROUP, key):
            mask &= data[column].eq(value)
        chunk = data[mask].sort_values("codec").reset_index(drop=True)
        title = " · ".join(map(str, key))
        image_stem = f"type-{index:02d}"
        chart(chunk, f"{title} / {len(chunk)} effective codecs", figures / f"{image_stem}.png")

        rows = []
        for _, row in chunk.iterrows():
            cells = [str(row["codec"]), str(row["loss_class"]), str(int(row["valid_datasets"]))]
            for metric, _ in METRICS:
                cells.extend([fmt(row[f"{metric}_mean"]), fmt(row[f"{metric}_median"])])
            rows.append("| " + " | ".join(cells) + " |")
        table = "\n".join([
            "| 算法 | 性质 | 有效数据集数 | 压缩倍数均值 | 压缩倍数中位数 | 编码均值 MiB/s | 编码中位数 MiB/s | 解码均值 MiB/s | 解码中位数 MiB/s |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
        ])
        sections.append(
            f"## {title}\n\n![{title} 均值与中位数柱状图](figures/{image_stem}.png)\n\n"
            f"[SVG](figures/{image_stem}.svg)\n\n{table}\n"
        )

    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report = (
        "# 同类型数据的有效算法均值与中位数柱状图\n\n"
        f"生成时间：{generated}\n\n"
        "类型按 dtype、保真条件、数据组织方式和 profile 划分；统计沿用汇总报告口径，仅包含 prepared 生命周期的完整有效案例。"
        "性质按任务保真要求标记：bitwise 为无损；bounded_abs 与 empirical_quality 为有损。"
        "每种类型分别显示压缩倍数、编码吞吐和解码吞吐；实心柱表示均值，斜线空心柱表示中位数。"
        "吞吐轴为对数刻度，压缩倍数图中的虚线为 1× 膨胀分界。\n\n"
        + "\n".join(sections)
        + render_support_matrix(args.summary, out)
    )
    report_path = out / f"effective_by_type_bars_{stamp}.md"
    report_path.write_text(report, encoding="utf-8")
    print(report_path)
    print(f"types={len(keys)} codec_type_rows={len(data)}")


if __name__ == "__main__":
    main()
