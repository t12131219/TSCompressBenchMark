#!/usr/bin/env python3
"""Render effective dataset coverage matrices for grouped summary reports."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, Normalize


CJK_FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
GROUP = ["dtype", "fidelity", "kind", "profile_id"]


def render(summary_path: Path, output_dir: Path) -> str:
    """Create three coverage panels and return their Markdown section."""
    if CJK_FONT.is_file():
        font_manager.fontManager.addfont(str(CJK_FONT))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(CJK_FONT)).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    data = pd.read_csv(summary_path)
    data["valid_datasets"] = pd.to_numeric(data["valid_datasets"], errors="coerce").fillna(0).astype(int)
    panels = [
        ("无损浮点", data[(data["fidelity"] == "bitwise") & data["dtype"].isin(["<f4", "<f8"])]),
        ("无损整数", data[(data["fidelity"] == "bitwise") & ~data["dtype"].isin(["<f4", "<f8"])]),
        ("有损", data[data["fidelity"].isin(["bounded_abs", "empirical_quality"])]),
    ]
    lines = [
        "## 有效数据集支持矩阵", "",
        "矩阵按无损浮点、无损整数和有损任务分组；每格数字为该类型下有完整有效结果的数据集数量。",
        "空白（—）表示该算法在对应类型没有有效记录，不表示零压缩率或零吞吐。", "",
    ]
    for index, (title, chunk) in enumerate(panels, 1):
        if chunk.empty:
            continue
        codecs = sorted(chunk["codec"].unique())
        types = list(chunk[GROUP].drop_duplicates().itertuples(index=False, name=None))
        matrix = np.full((len(types), len(codecs)), np.nan)
        labels = []
        for row_index, key in enumerate(types):
            row = chunk
            for column, value in zip(GROUP, key):
                row = row[row[column] == value]
            labels.append(" · ".join(map(str, key)))
            for _, record in row.iterrows():
                matrix[row_index, codecs.index(record["codec"])] = int(record["valid_datasets"])

        width = max(9.5, 0.48 * len(codecs) + 3.5)
        height = max(2.7, 0.68 * len(types) + 1.5)
        fig, ax = plt.subplots(figsize=(width, height), constrained_layout=True)
        cmap = LinearSegmentedColormap.from_list("coverage", ["#dcefe9", "#16836f"])
        values = matrix[~np.isnan(matrix)]
        maximum = max(1, int(values.max()))
        masked = np.ma.masked_invalid(matrix)
        image = ax.imshow(masked, cmap=cmap, norm=Normalize(vmin=1, vmax=max(2, maximum)), aspect="auto")
        ax.set_xticks(np.arange(len(codecs)), codecs, rotation=55, ha="right", rotation_mode="anchor", fontsize=8)
        ax.set_yticks(np.arange(len(labels)), labels, fontsize=8)
        ax.set_xticks(np.arange(-0.5, len(codecs), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(labels), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=1.3)
        ax.tick_params(which="minor", bottom=False, left=False)
        for row in range(len(types)):
            for col in range(len(codecs)):
                value = matrix[row, col]
                text = str(int(value)) if not np.isnan(value) else "—"
                color = "white" if not np.isnan(value) and value >= max(2, maximum * 0.55) else "#33434a"
                ax.text(col, row, text, ha="center", va="center", fontsize=8, color=color)
        ax.set_title(f"{title} · 有效数据集数", loc="left", fontsize=11, color="#354252")
        ax.set_xlabel("算法")
        ax.set_ylabel("数据类型")
        fig.colorbar(image, ax=ax, label="有效数据集数", shrink=0.82)
        stem = f"support-matrix-{index:02d}"
        figure_dir = output_dir / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(figure_dir / f"{stem}.png", dpi=160, bbox_inches="tight")
        fig.savefig(figure_dir / f"{stem}.svg", bbox_inches="tight")
        plt.close(fig)
        lines.extend([f"### {title}", "", f"![{title}有效数据集支持矩阵](figures/{stem}.png)", "",
                      f"[SVG](figures/{stem}.svg)", ""])

    lines.extend([
        "### 缩写与标注", "",
        "- dtype：`<f4` = 32 位浮点，`<f8` = 64 位浮点，`<i2` = 16 位有符号整数，`<i8` = 64 位有符号整数，`<u4` = 32 位无符号整数。",
        "- 保真：`bitwise` = 逐位无损；`bounded_abs` = 绝对误差有界的有损任务；`empirical_quality` = 按经验质量阈值验证的有损任务。",
        "- `values` 表示仅压缩数值数组；`records` 表示带时间和值的记录；`cpu-single` 表示单线程 CPU profile。",
        "- 数字统计 prepared 生命周期下完整有效的不同数据集数；颜色越深，覆盖的数据集越多。", "",
    ])
    return "\n".join(lines)
