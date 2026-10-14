# 冻结输入画像

`real_objects.json` 保存全源 CSV 词法精度、binary64 数值画像、真实时间轴，以及 32 条任务/配置对象描述（26 个不同 canonical object ID）。文件只包含摘要、身份和来源记录，不捆绑原 CSV。`component_pairing.json` 是另行重读并逐个验证 raw_object_id/source hash 后冻结的布局无关组件 bitwise identities，用于证明 C/F 配对具有相同 dtype、shape、schema 和 C-order bits；它不会改写先前画像。

| 输入 | 全源行数 | Lossless MTS 通道 | ABS 温度通道 | 正式窗口 |
|---|---:|---:|---|---|
| ETTh1 | 17420 | 7 | OT | `[2048,2176)` / `[2048,2560)` |
| weather | 52696 | 21 | T (degC), Tdew (degC), Tlog (degC) | 同上 |

ETT 的全源 T 严格递增，间隔为 3600000000000 ns（一小时）。Weather 全源非递减，有一次重复时间戳，52693 个十分钟间隔和一个 6000000000000 ns（100 分钟）间隔；不排序、删除重复或插值。新窗口内两个来源都是规则时间轴，归一化后的 512 个时间戳恰为 0..511。因此本实验没有在真实不规则窗口测量时间戳算法；已有合成边界例仍须单独报告。

两份冻结全源的全部选定数值列均无 missing token、NaN、Inf、负零或 subnormal。实际缺失率为零，records 只包含 V/T，没有人为补造 all-valid mask。缺失、特殊值和其它时间轴边界支持仍由专门资格对象证明。

Decimal places 是冻结文本 token 的 Decimal exponent，保留 trailing zeros 和科学计数法的实际指数，不是传感器分辨率。ETT 导出文本最大小数位为 18；新 512-row OT 窗口中 237 个 token 有 14 位、266 个有 15 位，其余 9 个分布于 2/3/13 位。它体现已有浮点导出尾数，不能解释为 14/15 位实际温度精度。Weather 全源最多 2 位，新窗口 T/Tdew/Tlog 各为 1 或 2 位；这也只是包中 token 的词法属性。

数值统计只对 finite 原始值计算，std 使用 ddof=0，quantile 使用 NumPy 默认线性插值。每列保留 range、mean、std、unique numeric values、邻接重复、邻接绝对差中位数/均值和 lag-1 Pearson。NaN 缺口两侧不连接；无样本或常量时相关为 null。趋势是对 row index 的 OLS slope，residual RMSE 只是相对直线的偏差，不是已识别的测量噪声。signed zero 的 bit pattern 在原始组件 hash/raw_object_id 中保留；unique/equal 的数值统计会合并正负零。

原始字节分母按 task projection 定义：

| Task / source | n128 bytes | n512 bytes |
|---|---:|---:|
| ETT MTS V (7 channels) | 7168 | 28672 |
| weather MTS V (21 channels) | 21504 | 86016 |
| ETT records V+T | 8192 | 32768 |
| weather records V+T | 22528 | 90112 |
| T only，任一 source | 1024 | 4096 |
| ETT ABS OT | 1024 | 4096 |
| weather ABS 3 temperature channels | 3072 | 12288 |

C/F 对应相同分母和逻辑组件，但 order 是 canonical identity 的一部分。两个 ABS 界限复用输入，所以不能当作新增来源。完整存储成本必须使用最终 wire，不能将 codec payload 与此原始 task 分母混为完整存储结果。

来源与授权证据保留在每份 source 记录、`registry/datasets/catalog.json` 和 `docs/data_sources.md`：ETT 作者仓库固定 commit，声明 CC-BY-ND-4.0；weather 数值/T 与官方 MPI 2020 归档逐项比对，官方 CC-BY-4.0，预处理 CSV 包装的额外授权未知。数据由用户本地提供，仓库不再分发 CSV。新窗口不与先前已知性能窗口重叠，但全文件已经解析与画像，不是盲测；两份来源不能支持总体代表性结论。

准备、正式顺序执行和只读分析命令见 `benchmark/experiments/real-objects/README.md`。
