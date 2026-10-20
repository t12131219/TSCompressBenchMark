# forecasting_transpose 小数据集筛选（2026-10-19）

已从活动目录 `forecasting_transpose/` 移除 3,967 个 CSV，保留 4,126 个；筛选前为 8,093 个。移除的原文件共 6,801,658 字节，全部保存在 `removed_csv.tar.gz`，归档逐文件 SHA-256 已在删除前核验，保留文件也已逐个核验未变。

## 规则与依据

移除条件为 **采样行数 < 128，或数值部分按 float64 计算的大小 < 1,024 字节**。`date` 列和 CSV 文本格式不计入数值体积。128 行恰好保留，未按压缩结果逐文件挑选，也未截断或改写保留文件。此次所有被移除文件均为单变量序列。

依据为 Sprintz 当前默认 lowdim RLE 路径的 128 元素直存分界，以及已冻结 forecasting 结果：按 prepared 生命周期，各算法已有结果中低于 1 的案例均不足 128 行。此阈值是结合现有结果确定的规模筛选规则，不保证新数据压缩倍数大于 1；ABBA/fABBA 的有损误差仍须独立报告。

| 参考算法 | 原成功样本数 | 原压缩倍数 < 1 数量 | 其中满足保留规模的样本数 | 保留规模样本中 < 1 数量 |
|---|---:|---:|---:|---:|
| ABBA | 28 | 12 | 14 | 0 |
| fABBA | 28 | 8 | 14 | 0 |
| Sprintz Delta | 13 | 8 | 5 | 0 |
| Sprintz FIRE | 13 | 8 | 5 | 0 |
| Sprintz Delta + Huffman | 13 | 6 | 5 | 0 |
| Sprintz FIRE + Huffman | 13 | 6 | 5 | 0 |

冻结清单的 8,093 个源文件在筛选前均核验大小和 SHA-256；本次没有重新解析或重新跑性能测试。原始清单为 `benchmark/experiments/forecasting-20261018-1614/inventory.json`，参考性能表为 `docs/forecasting_results_20261018_1614/primary.csv`，两者身份记录在 `manifest.json`。

## 清单及恢复

- `removed.csv`：移除文件的名称、行数、列数、数值体积、CSV 体积、哈希及具体原因。
- `retained.csv`：全部保留文件的对应资料。
- `manifest.json`：阈值、输入及归档身份、数量和执行后校验状态。
- `filter.py`：实际执行脚本，默认只预览；拒绝覆盖已有归档，拒绝在源文件集合变化后重复删除。

历史配置和结果保留原实验身份。原 53 份代表样本中有 14 份的源 CSV 被移除，因此重跑这些旧配置或重新验证旧报告的源文件时，需要先恢复归档。后续性能实验应对筛选后的目录新建清单和设计，并披露本次筛选。

恢复所有已移除 CSV（在仓库根目录运行；已有同名文件会被拒绝覆盖）：

```bash
cd /home/fzg/PycharmProjects/TSDataCompressBenchMark
tar --extract --gzip --keep-old-files --file docs/forecasting_size_filter_20261019/removed_csv.tar.gz
```

恢复会把源目录恢复到筛选前的集合，历史 `manifest.json` 仍保留本次执行完成时的审计状态。
