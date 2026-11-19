# 完整对象：固定 T，直接 f64 与 Sprintz-FIRE16 位片

本合同补实设计 §7.3–7.4 中 M0 需冻结的角色、分组和比较身份，并提供 M3 的完整对象**开发诊断**。
它不授予正式比较或阶段资格，不新增 Unique selection，不改变首批 12 项或 36 组原生分母。

## 冻结对象和方法

[套件](../../configs/suites/dev_tv_limb_comparison_v1/suite.json)固定 `TVVVVV`、515 行、512+3 对齐块：
一组是交通 held-out 分区的五个同轴原值列，另一组含负零、subnormal、带 payload 的 NaN、Inf、最大有限 f64，
以及重复、逆序和 i64 极端时间戳。真实交通时间从 civil 秒精确换为毫秒，恢复按原单位逐位核对；
没有改称 UTC。这里没有替代 CSV/NPY/TXT 三入口一致性、数值 cast 或有损量化的专项检查。

| 方法 | T（两方法构建、配置、重置均相同） | V |
|---|---|---|
| `gorilla-t-alp-f64` | Gorilla T，块内只存一次 | 各 f64 列分别走 ALP Auto，解码配置 `scalar-unfused` |
| `gorilla-t-fire-u16` | Gorilla T，块内只存一次 | 五列合并成一条 row-major u16 流，`algorithm=1`、`width=16`、`path=0`、`ndims=20` |

位片是按位转置，不执行浮点运算。每行按 `[V1_limb0..3, …, V5_limb0..3]` 交错；每个 f64 从最低 16 位到最高
16 位，存储为 little-endian u16。编解码各自实际进行内存分配和 pack/unpack，均计入 worker 进程墙钟。
验证方独立用整数移位和 u16 序列化预计算每块原始位片的 CRC，只用于证据核对，不供执行器作为输入。
`512×20×2=20,480`、`3×20×2=120` 为两个 V 物理块的原始字节；完整对象分母始终为 `48×515=24,720 B`。

[分组插件](../../plugins/codecs/sprintz-fire/group-plugin.json)载入同一锁定 `repaired_codec`，采用有独立 ID/格式的
`BMKSPG` 外层，保存完整 SFB1。保留原 `sprintz-fire` 的固定四通道 ID、`BMKSPR` 格式和尾部语义。
分组插件接收 3–128 个显式 u16 lanes、完整行、最多 65,536 B；TV 层仅接受 1–5 个普通 f64 V 列，要求
`lanes=4×V`，不静默拆组，不把 T 混入 V。格式专属核验在 qualification 层，不决定 worker 如何路由。

方法 ID 绑定 V 分组、转换顺序、物理 schema、逻辑列数、通道数、codec 格式、构建和配置。沿用 bundle v1
的列区间目录：分组块中 `(first_column=0, columns=1)` 指向单 T 流，`(1,5)` 指向覆盖全部 V 的 U16 流。
默认的原生双列和单列分离方法不变，旧封存格式仍可独立复算。账本分别记录逻辑 V 数、编码通道数和实际原生
批调用的 `threads=1`，以及所选 `generic_rle` 路线的 ISA 前提（AVX2/BMI1/BMI2/LZCNT/POPCNT）。
审计再区分实际 packed blocks 和 literal 尾；不把短尾的字面拷贝标成独立的 SIMD 样本，也不推断每条指令的计数。

比较为 O 轨完整对象 `development_diagnostic`；保留各自编码/解码进程与完整码流，不从另一方法取得 T 流。
字节账为完整 bundle，计入目录、schema、每条 T/V 帧以及 SFB1 内外封装。当前为进程墙钟与子进程观测，
无正式 CPU 独占、内存资源预算、稳态重复样本或排名。

## 复现和独立审计

```sh
# 在 tsbench 环境；Linux x86-64 / glibc / Bubblewrap / 兼容 ISA
tools/probe_offline_tv_composition.sh "$CONDA_PREFIX" <空结果目录> --limbs
```

一次冻结计划一次运行，封存真实产物与逐 slot 终态。控制检查验证两个方法各自执行、固定 T 的实际字节一致、
全对象位级恢复、有效值和尾块分组、完整字节账，并拒绝 lane 数量/选项/域/目录不匹配。报告独立解析
SFB1 的配置、长度、RLE 结构、位片原始 CRC 与 payload CRC。`tv-restore-audit` 另在每方法仅挂载其
传递运行闭包与 bundle 的隔离进程里真实解码，复核原始对象摘要；不依赖原构建、原语料或另一条 V 路线。

### 2026-11-19 开发记录

同一封存运行 `3819701a69b843e5bb893a17d127b562` 的[报告](../../results/m3-tv-limbs-20261119-r2/report.json)、
[控制检查](../../results/m3-tv-limbs-20261119-r2/controls.json)与[独立解码](../../results/m3-tv-limbs-20261119-r2/restore.json)：
4/4 对象验证并恢复，12 项负测通过；两组固定 T 的两块实际帧哈希各自一致。两个 Sprintz 头块各包含 64 个
非零位宽 packed blocks，两个三行尾块各含 60 个 literal u16。两方法分别用自己的依赖闭包恢复。

| 输入 | 原始对象（B） | 直接 ALP 完整 bundle（B） | Sprintz 位片完整 bundle（B） |
|---|---:|---:|---:|
| 特殊 f64 位和时间戳 | 24,720 | 26,162 | 26,005 |
| 交通五列 | 24,720 | 10,518 | 19,760 |

这些是两个固定对象的实际字节数，不是总体压缩率或速度排名。旧 `dev_tv_composition_v1` 报告在新代码下仍逐字节复算。
