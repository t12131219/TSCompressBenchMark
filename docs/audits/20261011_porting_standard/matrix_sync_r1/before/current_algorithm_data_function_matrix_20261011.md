# 当前算法 × 数据类型与功能支持矩阵

更新日期：2026-10-11。范围：TSDataCompressBenchMark 当前 **33 个活动算法入口**；后续新增算法沿用相同列定义增加行。

每个算法单独一行；新增“分类属性（CSV）”列，横向列出数据类型、数据结构、任务和功能。为便于阅读，拆为三张主矩阵，三表按 CSV 主记录顺序分类排列，算法顺序完全相同；限制条件表同步排序。算法名称可点击查看当前登记合同。

**本表记录当前接入能力及有限执行证据，不是“33 个算法 × 1409 个 Dataset_Verify 数据集全部编解码成功”的证明。** 类型、形状、Track、值域、长度、参数、布局、模型和 ISA 条件必须同时成立；不能把任一单元格的支持扩展为任意输入都能成功。


**证据时效：** 本表中的正式执行和限定资格标记保留原批次身份。2026-10-11 的移植规范审查修正了当前源码、Python 解码路径、补丁及构建登记；旧 FORMAL／completion 不自动适用于新闭包。当前修正和重验证结论另见 `docs/audits/20261011_porting_standard/`；能力声明、当前限定验证与历史性能须分别解释。

## 分类属性来源

“分类属性（CSV）”按 [algorithm_implementation_plan.csv](algorithm_implementation_plan.csv) 的 **一级分类＋二级分类** 填写。主矩阵使用去掉英文括注的紧凑名称，原始分类保留如下；时间戳表编号单独标明，避免与数值表的同编号分类混淆。分类表示 CSV 的方法组织属性，功能支持格仍以当前接入合同和执行证据为准。

| 分类属性（矩阵显示） | CSV 来源表 | 一级分类原文 | 二级分类原文 |
| --- | --- | --- | --- |
| 1. 字典压缩／通用字典压缩 | 时序数值/通用压缩 | 1. 字典压缩（Dictionary-based Compression） | 通用字典压缩（General Dictionary Coding） |
| 1. 字典压缩／时序模式字典 | 时序数值/通用压缩 | 1. 字典压缩（Dictionary-based Compression） | 时序模式字典（Time-series Dictionary） |
| 2. 函数逼近／学习型分段数学模型 | 时序数值/通用压缩 | 2. 函数逼近（Functional Approximation） | 学习型分段数学模型（Learned Mathematical Models） |
| 3. 预测编码／无损预测编码 | 时序数值/通用压缩 | 3. 预测编码（Predictive / Sequential Coding） | 无损预测编码（Lossless Predictive Coding） |
| 3. 预测编码／有损预测编码 | 时序数值/通用压缩 | 3. 预测编码（Predictive / Sequential Coding） | 有损预测编码（Lossy Predictive Coding） |
| 4. 神经网络压缩／深度自编码压缩 | 时序数值/通用压缩 | 4. 神经网络压缩（Neural Compression） | 深度自编码压缩（Deep Autoencoder Compression） |
| 5. 工程优化与部署技术／熵编码优化 | 时序数值/通用压缩 | 5. 工程优化与部署技术（Engineering & Deployment） | 熵编码优化（Entropy Coding） |
| 时间戳表：3. Bit-level Encoding／Bit Packing | 时间戳压缩 | 3. Bit-level Encoding | Bit Packing |

`deflate-zlib` 主分类采用 DEFLATE 的 V4，V1/LZ77 保留为机制/来源关联。`sprintz-fire-huff0` 同时关联 V43/Sprintz-FIRE 和 V77/Huff0，分类列保留两类属性，以 V43 主记录排序。其他多入口变体共享其 CSV 主记录分类，仍逐个入口列行。

分类映射使用当前 CSV 记录ID及 [候选版本映射台账](registry/candidate_integration_ledger.json)，不以旧 V/T 行号连接；不据 CSV 中的上游功能描述修改当前支持状态。

## 单元格图例

| 标记 | 含义 |
| --- | --- |
| 接 | 当前算法入口登记并实现了该能力；受完整合同条件限制，不表示该维度全部取值已执行通过。包括现有 wrapper 的扩宽、逐列、描述封装等，不能直接读成上游原生 API 支持。 |
| 字 | 通过现有字节序列化/描述封装接入，数值位模式和结构由框架保存；不表示算法理解浮点、整数或跨通道关系。 |
| 组·验 | 特定 P2 组合已有执行证据；只适用于本表明确列出的配方与对象，不授予子算法原生能力。 |
| 验·限定 | 当前冻结范围已有资格或正式执行证据；仍不证明全 dtype、全长度、全参数域。 |
| 条件 | 有值域、长度、模型或分支限制，须查本文条件表和对应 manifest。 |
| × | 当前入口未开放该能力或该类型/任务；不是对上游全部实现的永久否定。 |
| 未开放 | 当前登记未提供此实验路径；不据此断言编译器/依赖没有使用任何向量指令。 |
| ？ | 未取得所述范围的执行证明；不得按通过计数。 |
| — | 该列对当前对象层/任务不适用。 |

`f32/f64` 表示 float32/float64；`i8/i16/i32/i64` 和 `u8/u16/u32/u64` 的数字均为**位数**。`UTS` 为单变量，`MTS` 为同步多变量，`ND` 为多维数组。

## 对象层说明

P0、P1、P2 表示被评测对象的组成层级，不是性能或质量等级。

| 对象层 | 含义 | 当前例子 |
| --- | --- | --- |
| **P0：基础组件** | 完成编码中的一个环节，例如整数位打包。比较完整压缩方案时，还需要补齐长度、类型、尾部等恢复信息。 | `simdcomp-u32` |
| **P1：完整 Codec** | 在声明输入域内完成编码、输出结束和解码；按合同保存或计费必要的恢复描述与依赖。 | LZ4、Zstd、ALP、Chimp |
| **P2：组合管线** | 将多个编码、变换或模型步骤组成完整恢复方案，计入所有阶段与依赖的成本。 | `sprintz-fire-huff0`；框架组合的 T＋V＋validity 方案 |

## 1. 数值类型矩阵（VALUE 入口）

这里按当前入口登记 dtype 填写；IEEE 特殊值列包含 ±0、subnormal、±Inf 与 NaN payload，标记“条件”时必须逐种检查源域或 RAW 分支。可逆桥接可以另立组合任务，但不自动修改这些格子；例如 DeepZip 的 base4 桥接不等于直接接受任意 uint8，也不等于原生浮点压缩。

| 算法入口 | 分类属性（CSV） | 对象层 | f32 | f64 | i8 | i16 | i32 | i64 | u8 | u16 | u32 | u64 | IEEE 特殊值 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [lzss-raw](registry/codecs/lzss-raw.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [lzss-dipperstein-c](registry/codecs/lzss-dipperstein-c.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [deflate-zlib](registry/codecs/deflate-zlib.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [lz4-frame](registry/codecs/lz4-frame.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [snappy-raw](registry/codecs/snappy-raw.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [zstd-frame](registry/codecs/zstd-frame.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [brotli-stream](registry/codecs/brotli-stream.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [xz-stream](registry/codecs/xz-stream.json) | 1. 字典压缩／通用字典压缩 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [abba](registry/codecs/abba.json) | 1. 字典压缩／时序模式字典 | P2 | × | 接 | × | × | × | × | × | × | × | × | 条件 |
| [fabba](registry/codecs/fabba.json) | 1. 字典压缩／时序模式字典 | P2 | × | 接 | × | × | × | × | × | × | × | × | 条件 |
| [neats-lossless-i64](registry/codecs/neats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | P1 | × | × | 接 | 接 | 接 | 接 | × | × | × | × | — |
| [leats-lossless-i64](registry/codecs/leats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | P1 | × | × | 接 | 接 | 接 | 接 | × | × | × | × | — |
| [sprintz-delta](registry/codecs/sprintz-delta.json) | 3. 预测编码／无损预测编码 | P1 | × | × | 接 | 接 | × | × | 接 | 接 | × | × | — |
| [sprintz-delta-u8](registry/codecs/sprintz-delta-u8.json) | 3. 预测编码／无损预测编码 | P1 | × | × | × | × | × | × | 接 | × | × | × | — |
| [sprintz-fire](registry/codecs/sprintz-fire.json) | 3. 预测编码／无损预测编码 | P1 | × | × | 接 | 接 | × | × | 接 | 接 | × | × | — |
| [sprintz-fire-huff0](registry/codecs/sprintz-fire-huff0.json) | 3. 预测编码／无损预测编码＋5. 工程优化与部署技术／熵编码优化 | P2 | × | × | 接 | 接 | × | × | 接 | 接 | × | × | — |
| [sprintz-fire-u8](registry/codecs/sprintz-fire-u8.json) | 3. 预测编码／无损预测编码 | P1 | × | × | × | × | × | × | 接 | × | × | × | — |
| [chimp](registry/codecs/chimp.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [chimp128](registry/codecs/chimp128.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [elf](registry/codecs/elf.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [elf-plus](registry/codecs/elf-plus.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [elf-star](registry/codecs/elf-star.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [self-star](registry/codecs/self-star.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [alp](registry/codecs/alp.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [alp-rd](registry/codecs/alp-rd.json) | 3. 预测编码／无损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [serf-qt](registry/codecs/serf-qt.json) | 3. 预测编码／有损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [serf-xor](registry/codecs/serf-xor.json) | 3. 预测编码／有损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [zfp-accuracy-1d](registry/codecs/zfp-accuracy-1d.json) | 3. 预测编码／有损预测编码 | P1 | 接 | 接 | × | × | × | × | × | × | × | × | 条件 |
| [deepzip](registry/codecs/deepzip.json) | 4. 神经网络压缩／深度自编码压缩 | P2 | × | × | × | × | × | × | 条件·模型域 | × | × | × | — |
| [dzip](registry/codecs/dzip.json) | 4. 神经网络压缩／深度自编码压缩 | P2 | × | × | × | × | × | × | 条件·模型域 | × | × | × | — |
| [huff0](registry/codecs/huff0.json) | 5. 工程优化与部署技术／熵编码优化 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [fse](registry/codecs/fse.json) | 5. 工程优化与部署技术／熵编码优化 | P1 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 | 字 |
| [simdcomp-u32](registry/codecs/simdcomp-u32.json) | 时间戳表：3. Bit-level Encoding／Bit Packing | P0 | × | × | × | × | × | × | × | × | 接·P0 | × | — |

## 2. 数据结构与任务矩阵

“有 T 的 VALUE”只表示可对带时间戳数据集的 **V 部分**执行 VALUE；它不承诺一起保存 T。“T-only”才是 TIMESTAMP Track。“完整 T＋V＋mask”使用独立 P2 配方。

MTS 列的“列”表示各列独立；“联合”表示 Sprintz 的当前整体矩阵路径；“字”表示整体字节表示。三者的机制不同。ND 声明限当前 rank/layout/axis 合同；“时间轴映射组合”单列有证据的 P2 对象。混合列指不同字宽/类型并存的对象；同字宽子集仍须按每种 dtype、wrapper 和参数单独协商，不从此列推断。

| 算法入口 | 分类属性（CSV） | 单变量 UTS | 同步 MTS | 混合异构字宽 MTS | ND 数组 | 时间轴映射组合 | validity/null 组合 | async/ragged 组合 | 无 T 的 VALUE | 有 T 的 VALUE | T-only | 完整 T＋V＋mask | 空输入 N=0 | 短输入 N=1/2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [lzss-raw](registry/codecs/lzss-raw.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | 字 | × | 字 | 字 |
| [lzss-dipperstein-c](registry/codecs/lzss-dipperstein-c.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | 字 | × | 字 | 字 |
| [deflate-zlib](registry/codecs/deflate-zlib.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | 字 | × | 字 | 字 |
| [lz4-frame](registry/codecs/lz4-frame.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | 组·验 | 组·验 | 组·验 | 字 | 字 | 字 | 组·验 | 字 | 字 |
| [snappy-raw](registry/codecs/snappy-raw.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | 字 | × | 字 | 字 |
| [zstd-frame](registry/codecs/zstd-frame.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | 组·验 | 组·验 | 组·验 | 字 | 字 | 字 | 组·验 | 字 | 字 |
| [brotli-stream](registry/codecs/brotli-stream.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | 字 | × | 字 | 字 |
| [xz-stream](registry/codecs/xz-stream.json) | 1. 字典压缩／通用字典压缩 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | 字 | × | 字 | 字 |
| [abba](registry/codecs/abba.json) | 1. 字典压缩／时序模式字典 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | × | 条件·仅 N=2 |
| [fabba](registry/codecs/fabba.json) | 1. 字典压缩／时序模式字典 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | × | 条件·仅 N=2 |
| [neats-lossless-i64](registry/codecs/neats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | × | 接 |
| [leats-lossless-i64](registry/codecs/leats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | × | 接 |
| [sprintz-delta](registry/codecs/sprintz-delta.json) | 3. 预测编码／无损预测编码 | 接 | 接·联合 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [sprintz-delta-u8](registry/codecs/sprintz-delta-u8.json) | 3. 预测编码／无损预测编码 | 接 | × | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [sprintz-fire](registry/codecs/sprintz-fire.json) | 3. 预测编码／无损预测编码 | 接 | 接·联合 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [sprintz-fire-huff0](registry/codecs/sprintz-fire-huff0.json) | 3. 预测编码／无损预测编码＋5. 工程优化与部署技术／熵编码优化 | 接 | 接·联合 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [sprintz-fire-u8](registry/codecs/sprintz-fire-u8.json) | 3. 预测编码／无损预测编码 | 接 | × | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [chimp](registry/codecs/chimp.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [chimp128](registry/codecs/chimp128.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [elf](registry/codecs/elf.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [elf-plus](registry/codecs/elf-plus.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [elf-star](registry/codecs/elf-star.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [self-star](registry/codecs/self-star.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [alp](registry/codecs/alp.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [alp-rd](registry/codecs/alp-rd.json) | 3. 预测编码／无损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [serf-qt](registry/codecs/serf-qt.json) | 3. 预测编码／有损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [serf-xor](registry/codecs/serf-xor.json) | 3. 预测编码／有损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [zfp-accuracy-1d](registry/codecs/zfp-accuracy-1d.json) | 3. 预测编码／有损预测编码 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [deepzip](registry/codecs/deepzip.json) | 4. 神经网络压缩／深度自编码压缩 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [dzip](registry/codecs/dzip.json) | 4. 神经网络压缩／深度自编码压缩 | 接 | 接·列 | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |
| [huff0](registry/codecs/huff0.json) | 5. 工程优化与部署技术／熵编码优化 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | × | × | 字 | 字 |
| [fse](registry/codecs/fse.json) | 5. 工程优化与部署技术／熵编码优化 | 字 | 字 | 字 | 字 | × | × | × | 字 | 字 | × | × | 字 | 字 |
| [simdcomp-u32](registry/codecs/simdcomp-u32.json) | 时间戳表：3. Bit-level Encoding／Bit Packing | 接 | × | × | × | × | × | × | 接 | 接 | × | × | 接 | 接 |

空/短输入列按 manifest 的 `min_n` 声明填写；不表示每个值域或参数在短输入上均已执行。ABBA/fABBA 要求 N≥2，NeaTS/LeaTS 要求 N≥1。

这些组合格只对 LZ4/Zstd 标记“组·验”：正式 P2 使用两真实来源派生的 f32、mixed/ND/T/validity 对象，固定 256 行块及 RAW_TAIL；async/ragged 另有 12 个集合资格单元，覆盖独立通道时间轴、长度和掩码，不属于正式性能全集。混合类型“字”仍受每种 dtype、总大小、拓扑和布局约束。

全部 33 个**直接 codec 入口**当前 `validity_shapes` 仅为 `NONE`，未登记原生 ASYNCHRONOUS_MTS、SYSTEM Track、P3 或 GPU 能力。组合恢复 T/V/mask 不会改变这一事实。其他算法存在适配或管线组件时，也须有具体配方与资格才可将对应格改为“组·验”。

## 3. 功能与验证矩阵

编码、完成输出、解码、域检查、声明尾部行为、完整计费及独立恢复是完整方案的必需闭环。SIMD、可配置多线程、stream、query、随机访问和设备接口按实际声明验收；缺少它们不自动判定某算法不完整。

“内部 timer”只记录可选计时接口是否登记，不能替代 CORE/PIPELINE 的计时边界或正式资格。分块/尾部列描述现有对象处理方式，不表示所有算法都提供可配置 block/window sweep。

| 算法入口 | 分类属性（CSV） | 无损 | 固定误差有损 | 经验质量有损 | SIMD 路径 | codec 内部多线程 | 框架块/列并行 | stream | query | 随机访问 | 分块/尾部方式 | 独立恢复 | 内部 timer | GPU/设备 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [lzss-raw](registry/codecs/lzss-raw.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | × | × | × | 整对象＋精确尾 | 验·限定 | 接 | × |
| [lzss-dipperstein-c](registry/codecs/lzss-dipperstein-c.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | × | × | × | 整对象＋精确尾 | 验·限定 | 接 | × |
| [deflate-zlib](registry/codecs/deflate-zlib.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | 验·已知长² | × | × | codec 内部分块/尾 | 验·限定 | 接 | × |
| [lz4-frame](registry/codecs/lz4-frame.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | 验·已知长² | × | × | codec 内部分块/尾 | 验·限定 | 接 | × |
| [snappy-raw](registry/codecs/snappy-raw.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | × | × | × | 整对象＋精确尾 | 验·限定 | 接 | × |
| [zstd-frame](registry/codecs/zstd-frame.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | 验·已知长² | × | × | codec 内部分块/尾 | 验·限定 | 接 | × |
| [brotli-stream](registry/codecs/brotli-stream.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | 验·已知长² | × | × | codec 内部分块/尾 | 验·限定 | 接 | × |
| [xz-stream](registry/codecs/xz-stream.json) | 1. 字典压缩／通用字典压缩 | 接 | × | × | 未开放 | × | × | 验·已知长² | × | × | codec 内部分块/尾 | 验·限定 | 接 | × |
| [abba](registry/codecs/abba.json) | 1. 字典压缩／时序模式字典 | × | × | 接 | 未开放 | × | × | × | × | × | 整对象＋精确长度 | 验·限定 | × | × |
| [fabba](registry/codecs/fabba.json) | 1. 字典压缩／时序模式字典 | × | × | 接 | 未开放 | × | × | × | × | × | 整对象＋精确长度 | 验·限定 | × | × |
| [neats-lossless-i64](registry/codecs/neats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | 接 | × | × | 未开放 | × | × | × | 验·研究³ | 验·point/range³ | 逐列模型/索引 | 验·限定 | 接 | × |
| [leats-lossless-i64](registry/codecs/leats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | 接 | × | × | 未开放 | × | × | × | 验·研究³ | 验·point/range³ | 逐列模型/索引 | 验·限定 | 接 | × |
| [sprintz-delta](registry/codecs/sprintz-delta.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 接·AVX2＋BMI2＋LZCNT | × | × | × | × | × | 整对象 RLE＋尾 | 验·限定 | 接 | × |
| [sprintz-delta-u8](registry/codecs/sprintz-delta-u8.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 接·AVX2＋BMI2＋LZCNT | × | × | × | × | × | 整对象 RLE＋尾 | 验·限定 | 接 | × |
| [sprintz-fire](registry/codecs/sprintz-fire.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 接·AVX2＋BMI2＋LZCNT | × | × | × | × | × | 整对象 RLE＋尾 | 验·限定 | 接 | × |
| [sprintz-fire-huff0](registry/codecs/sprintz-fire-huff0.json) | 3. 预测编码／无损预测编码＋5. 工程优化与部署技术／熵编码优化 | 接 | × | × | 接·AVX2＋BMI2＋LZCNT | × | × | × | × | × | RLE→Huff0＋尾 | 验·限定 | 接 | × |
| [sprintz-fire-u8](registry/codecs/sprintz-fire-u8.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 接·AVX2＋BMI2＋LZCNT | × | × | × | × | × | 整对象 RLE＋尾 | 验·限定 | 接 | × |
| [chimp](registry/codecs/chimp.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 配置块＋精确尾 | 验·限定 | × | × |
| [chimp128](registry/codecs/chimp128.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 配置块＋精确尾 | 验·限定 | × | × |
| [elf](registry/codecs/elf.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 配置块＋精确尾 | 验·限定 | × | × |
| [elf-plus](registry/codecs/elf-plus.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 配置块＋精确尾 | 验·限定 | × | × |
| [elf-star](registry/codecs/elf-star.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 配置块＋精确尾 | 验·限定 | × | × |
| [self-star](registry/codecs/self-star.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 跨块状态＋精确尾 | 验·限定 | × | × |
| [alp](registry/codecs/alp.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 1024 向量/rowgroup | 验·限定 | 接 | × |
| [alp-rd](registry/codecs/alp-rd.json) | 3. 预测编码／无损预测编码 | 接 | × | × | 未开放 | × | × | × | × | × | 1024 向量/rowgroup | 验·限定 | 接 | × |
| [serf-qt](registry/codecs/serf-qt.json) | 3. 预测编码／有损预测编码 | × | 接 | × | 未开放 | × | × | × | × | × | 配置块＋精确尾 | 验·限定 | 接 | × |
| [serf-xor](registry/codecs/serf-xor.json) | 3. 预测编码／有损预测编码 | × | 接 | × | 未开放 | × | × | × | × | × | 跨块状态＋精确尾 | 验·限定 | 接 | × |
| [zfp-accuracy-1d](registry/codecs/zfp-accuracy-1d.json) | 3. 预测编码／有损预测编码 | × | 接 | × | 未开放 | × | × | × | × | × | 4 点块＋部分尾 | 验·限定 | 接 | × |
| [deepzip](registry/codecs/deepzip.json) | 4. 神经网络压缩／深度自编码压缩 | 接 | × | × | 未开放 | × | × | × | × | × | 整对象＋精确长度 | 验·限定 | × | × |
| [dzip](registry/codecs/dzip.json) | 4. 神经网络压缩／深度自编码压缩 | 接 | × | × | 接·AVX | 固定后台池¹ | × | × | × | × | 整对象＋精确长度 | 验·限定 | × | × |
| [huff0](registry/codecs/huff0.json) | 5. 工程优化与部署技术／熵编码优化 | 接 | × | × | 未开放 | × | × | × | × | × | 单 entropy 对象 | 验·限定 | 接 | × |
| [fse](registry/codecs/fse.json) | 5. 工程优化与部署技术／熵编码优化 | 接 | × | × | 未开放 | × | × | × | × | × | 单 entropy 对象 | 验·限定 | 接 | × |
| [simdcomp-u32](registry/codecs/simdcomp-u32.json) | 时间戳表：3. Bit-level Encoding／Bit Packing | 接·primitive | × | × | 验·SSE4.1/AVX2 | × | × | × | × | × | 128/256＋显式尾 | 验·组件对象 | 接 | × |

1. **DZip 固定后台池**：调用线程＋两个持久单 worker Eigen 池，全部计入线程预算；没有已开放的线程数 sweep，不能将此格解读为 T1/Tp 加速比已验证。其他入口当前登记 `SINGLE_THREAD`；上游可能提供的其他线程模式不自动成为当前接入能力。
2. **stream**：五个入口已完成独立 stream profile，范围为已知总长度、固定输入分块和 Finalize 后完整恢复。首 emitted byte 可能是 header；未知总长、严格常量内存、首可消费样本、实时背压和 checkpoint 随机恢复未由这些证据证明。
3. **query/随机访问**：NeaTS/LeaTS 的真实 point/range/column 请求已完成 warm/fresh 两种会话策略；它们属于相关实现变体研究，logical bytes 不等于硬件流量。不能据此宣称其他算法或任意请求组合支持查询。
4. **SIMD**：Sprintz 必须满足 AVX2/BMI2/LZCNT；SIMDComp 当前 plain uint32 的 SSE4.1/AVX2 有 SDK 资格。DZip 登记 AVX 与依赖 dispatch。其余 SCALAR 登记入口没有开放受控 SIMD 路径比较，不能据登记断言依赖/编译器绝无 SIMD，也不填造 scalar/SIMD 加速比。
5. **有损**：ZFP/Serf 检查原域固定误差；ABBA/fABBA 保留经验质量和全部预声明参数点，不具有通用逐点误差保证。RAW 异常分支或桥接必须单列实际 method，不能当作原算法原生成功。

## 4. 每算法的值域、规模与桥接条件

下面 N/M 区间来自当前 manifest，属于规划上限和下限；不是这些区间每个长度均已测试。实际还须满足总元素、总字节、块数、参数、布局、依赖及资源约束。`2^63−1` 是整数规划上限，不代表现实机器可以处理该规模。

| 算法入口 | 分类属性（CSV） | N 声明区间 | M 声明区间 | 主要条件 |
| --- | --- | --- | --- | --- |
| [lzss-raw](registry/codecs/lzss-raw.json) | 1. 字典压缩／通用字典压缩 | 0…4,294,967,295 | 1…1,048,576 | C++17 重写；兼容 alexkazik 0.9.1 EI10/EJ4/C32 原流；总 raw bytes ≤ 2^32−1；typed 对象通过字节封装，见[迁移验证](docs/lzss_cpp_rewrite_20261011/README.md)。 |
| [lzss-dipperstein-c](registry/codecs/lzss-dipperstein-c.json) | 1. 字典压缩／通用字典压缩 | 0…4,294,967,295 | 1…1,048,576 | C LZSS file API 边界；总 raw bytes ≤ 2^32−1；不等同 `lzss-raw` 的 EI10/EJ4/C32 格式。 |
| [deflate-zlib](registry/codecs/deflate-zlib.json) | 1. 字典压缩／通用字典压缩 | 0…2^63−1 | 1…1,048,576 | RFC1950/zlib stream；不是额外独立 LZ77 算法行。 |
| [lz4-frame](registry/codecs/lz4-frame.json) | 1. 字典压缩／通用字典压缩 | 0…2^63−1 | 1…1,048,576 | 字节封装；保存原 dtype/shape；stream 限已知长度。 |
| [snappy-raw](registry/codecs/snappy-raw.json) | 1. 字典压缩／通用字典压缩 | 0…4,294,967,295 | 1…1,048,576 | raw Snappy＋付费恢复描述；当前无 stream 接口。 |
| [zstd-frame](registry/codecs/zstd-frame.json) | 1. 字典压缩／通用字典压缩 | 0…2^63−1 | 1…1,048,576 | 字节封装；保存原 dtype/shape；当前线程模式固定为单线程。 |
| [brotli-stream](registry/codecs/brotli-stream.json) | 1. 字典压缩／通用字典压缩 | 0…2^63−1 | 1…1,048,576 | 字节封装；built-in 静态字典按当前合同；不据此宣称外部字典训练接口。 |
| [xz-stream](registry/codecs/xz-stream.json) | 1. 字典压缩／通用字典压缩 | 0…2^63−1 | 1…1,048,576 | XZ/LZMA2；当前单线程路径，stream 仍限已知长度。 |
| [abba](registry/codecs/abba.json) | 1. 字典压缩／时序模式字典 | 2…16,777,216 | 1…65,535 | 有限 f64、N≥2；endpoint 算术失败拒绝；无通用逐点误差界。 |
| [fabba](registry/codecs/fabba.json) | 1. 字典压缩／时序模式字典 | 2…16,777,216 | 1…65,535 | 有限 f64、N≥2；endpoint 算术失败拒绝；无通用逐点误差界。 |
| [neats-lossless-i64](registry/codecs/neats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | 1…65,536 | 1…64 | 仅有符号整数；内部 i64 归一化及 bias 计费；总 raw bytes ≤ 2097152；N≥1。 |
| [leats-lossless-i64](registry/codecs/leats-lossless-i64.json) | 2. 函数逼近／学习型分段数学模型 | 1…65,536 | 1…64 | 仅有符号整数；内部 i64 归一化及 bias 计费；总 raw bytes ≤ 2097152；N≥1。 |
| [sprintz-delta](registry/codecs/sprintz-delta.json) | 3. 预测编码／无损预测编码 | 0…131,072 | 1…128 | 仅 8/16 位 signed/unsigned；M≤128；必须满足 ISA。 |
| [sprintz-delta-u8](registry/codecs/sprintz-delta-u8.json) | 3. 预测编码／无损预测编码 | 0…131,072 | 1…1 | 仅 uint8 单变量；不同于支持 i8/i16/MTS 的通用 Sprintz 入口。 |
| [sprintz-fire](registry/codecs/sprintz-fire.json) | 3. 预测编码／无损预测编码 | 0…131,072 | 1…128 | 仅 8/16 位 signed/unsigned；M≤128；必须满足 ISA。 |
| [sprintz-fire-huff0](registry/codecs/sprintz-fire-huff0.json) | 3. 预测编码／无损预测编码＋5. 工程优化与部署技术／熵编码优化 | 0…122,880 | 1…128 | Sprintz FIRE→Huff0 完整组合；总 raw bytes ≤ 122880；Huff0 RAW 分支单列。 |
| [sprintz-fire-u8](registry/codecs/sprintz-fire-u8.json) | 3. 预测编码／无损预测编码 | 0…131,072 | 1…1 | 仅 uint8 单变量；不同于支持 i8/i16/MTS 的通用 Sprintz 入口。 |
| [chimp](registry/codecs/chimp.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | NaN/END 源域限制；f32/f64 登记不等于所有 IEEE 位模式均合法。 |
| [chimp128](registry/codecs/chimp128.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | NaN/END 源域限制；块和尾部按当前配方。 |
| [elf](registry/codecs/elf.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | NaN END、significance/scale 或源恢复不无损等情况明确拒绝。 |
| [elf-plus](registry/codecs/elf-plus.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | NaN END、负 decimal scale、significance/scale 或源恢复失败明确拒绝。 |
| [elf-star](registry/codecs/elf-star.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | NaN END、decimal scale/significance/beta 表或源恢复失败明确拒绝。 |
| [self-star](registry/codecs/self-star.json) | 3. 预测编码／无损预测编码 | 0…1,024,000 | 1…65,535 | NaN/decimal scale/significance/beta/源恢复限制；每列最多 1024 块，跨块状态保留。 |
| [alp](registry/codecs/alp.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | 强制 ALP，禁止静默 ALP-RD fallback；某 rowgroup 选择 RD 时明确拒绝或使用另立 RAW 组合。 |
| [alp-rd](registry/codecs/alp-rd.json) | 3. 预测编码／无损预测编码 | 0…16,777,216 | 1…65,535 | 强制 ALP-RD；f32/f64 经当前 typed wrapper；rowgroup 字典/元数据计费。 |
| [serf-qt](registry/codecs/serf-qt.json) | 3. 预测编码／有损预测编码 | 0…16,777,216 | 1…65,535 | 原域总误差；nonfinite/不可表示值按登记 RAW exception block 分支。 |
| [serf-xor](registry/codecs/serf-xor.json) | 3. 预测编码／有损预测编码 | 0…16,777,216 | 1…65,535 | 原域总误差；nonfinite/overflow 按登记 RAW exception block 分支。 |
| [zfp-accuracy-1d](registry/codecs/zfp-accuracy-1d.json) | 3. 预测编码／有损预测编码 | 0…16,777,216 | 1…65,535 | 原域总误差检查；NaN/Inf/−0/subnormal 按登记 RAW column 分支处理，不是 zfp kernel 原生成功。 |
| [deepzip](registry/codecs/deepzip.json) | 4. 神经网络压缩／深度自编码压缩 | 0…16,777,216 | 1…65,535 | uint8 受冻结模型 alphabet 限制；正式任务为 base4 符号，不能直接推断任意 0…255 输入可编码。 |
| [dzip](registry/codecs/dzip.json) | 4. 神经网络压缩／深度自编码压缩 | 0…16,777,216 | 1…65,535 | uint8 受冻结模型合同限制；正式任务为 base4 符号；AVX/依赖及固定后台池成本保留。 |
| [huff0](registry/codecs/huff0.json) | 5. 工程优化与部署技术／熵编码优化 | 0…8,192 | 1…64 | 总 raw bytes ≤ 131072；实际 Huff0/RAW 模式另报；未登记 T-only。 |
| [fse](registry/codecs/fse.json) | 5. 工程优化与部署技术／熵编码优化 | 0…8,192 | 1…64 | 总 raw bytes ≤ 131072；原生 entropy/RAW/RLE 等实际编码模式另报；未登记 T-only。 |
| [simdcomp-u32](registry/codecs/simdcomp-u32.json) | 时间戳表：3. Bit-level Encoding／Bit Packing | 0…16,777,216 | 1…1 | P0 plain uint32 单变量；总 raw bytes ≤ 67108864；差分/FOR 未恢复为活动入口。 |

另立组合的已实现例子包括：`BYTE_TO_RADIX4` 将原始 uint8 字节拆为 base4 符号并逆恢复；`SOURCE_REJECT_TO_RAW_BLOCK` 仅对 typed SourceDomainError 做事前声明的 RAW 逃逸，普通错误/OOM/配置失败不被吞掉。这些组合有独立身份、完整成本和恢复合同，**不改变主矩阵的直接 dtype/值域声明**。见 [桥接合同](docs/pipeline_bridges_v2_20261010.md)。

## 5. 当前验证覆盖：与支持声明分开

| 证据层 | 当前已证明 | 尚不能据此证明 |
| --- | --- | --- |
| 活动入口资格 | 33 个入口、41 个 Track/fixture/config 案例 SCOPED_PASS，含原任务恢复、拒绝、边界和成本检查 | 全部合法值域、所有 dtype/长度/参数或 33×1409 Dataset_Verify 全矩阵通过 |
| 完整 codec 共同任务 | 32 个完整 codec 在各自适用冻结任务中有至少两独立真实来源的正式覆盖；12 comparison＋3 workload＋1 P2 lane 完成 | 所有算法处理同一种数值输入；同一个算法处理全部真实数据或 Dataset_Verify 数据 |
| SIMDComp | 独立 P0 入口资格；plain uint32 SSE4.1/AVX2 的 504 项 SDK 测试通过 | 双方法完整整数方案比较或尚未开放的差分/FOR 资格 |
| 完整 P2 | LZ4/Zstd 的 4 个冻结派生对象×2 配方×4 外层，共 32 次正式试验 | 其他子 codec 自动具备 mixed/ND/validity/T＋V 组合资格 |
| async/ragged 集合 | LZ4/Zstd、6 个对象×2 方法，共 12 单元；19 拒绝反例 | 所有算法原生支持异步数据或全集正式性能覆盖 |
| 框架回归 | 全量 2362 PASS，测试定义和源码闭包绑定 | 每个支持格都已遍历该维度的所有组合 |
| Dataset_Verify v3 全集 | 登记 1409 份离散维度数据；用于资格覆盖设计 | 本文没有逐算法×逐数据集的当前完整执行表，全集执行状态为 **？** |

SOURCE_PARITY、standalone 完整重写资格、Benchmark correctness、功能声明和 FORMAL 性能资格分别记录。Benchmark PASS 不会将 SOURCE_PARITY UNKNOWN 改为通过；统计 INCONCLUSIVE 也不会因流程完成而消失。完整证据与限制见 [最终验收记录](docs/reviews/v32_current_scope_acceptance_20261011.md)。

## 6. 后续增加算法的填写规则

新增算法以稳定 `codec_key` 为行身份，先关联当前 CSV 快照中的记录ID，填写其一级/二级分类属性，再按以上三表同序增加行；组合入口保留各方法的分类关系。只增加登记而未执行时使用“接/条件/？”；取得具体配方和完整证据后再改成“验·限定/组·验”。未实现能力填“×”，未知能力填“？”，不留含义不明的空白，也不根据算法名称或论文宣传填写 SIMD/多线程。

每次更新需同步当前 manifest、源域/长度/参数限制、对象层和实际路径，并保存资格/正式工件路径及身份。新增组、桥接或 ISA/线程模式不能复用已失效的资格证据。未来全 Dataset_Verify 执行应另建 **算法×DatasetID×Track×配置** 的逐格结果表，保留预期拒绝、失败、超时及 NOT_RUN；不能用本能力矩阵代替。

可复用的新增行结构：

```text
codec_key / 当前版本
  分类属性：CSV来源表＋一级分类＋二级分类；当前记录ID/主记录/关联记录
  类型：f32 f64 i8 i16 i32 i64 u8 u16 u32 u64
  结构/任务：UTS MTS mixed ND axis validity async VALUE TIMESTAMP 完整T/V
  功能：loss SIMD codec线程 框架并行 stream query random_access block/tail recovery timer device
  条件：值域、N/M、总大小、参数、布局、ISA、模型与依赖
  证据：声明来源＋实际资格/正式范围＋未知/失败/拒绝状态
```

范围外残留登记 `bzip2-stream`、`lzsse2-raw`、`lzsse8-raw` 不计入这 33 行；4 个 framework oracle 是测试组件；`lz77` 是 `deflate-zlib` 来源别名，不增加独立算法。后续只有明确调整活动范围并完成相应接入时才增加算法行。

## 7. 权威来源与本页快照

本页为 2026-10-11 当前状态汇总，原 2026-10-10 能力矩阵仍保留其日期语义。本次仅生成文档，未运行压缩器、pytest 或性能测量。声明来源与执行证据分别读取以下文件：

| 声明/证据文件 | SHA-256 |
| --- | --- |
| [algorithm_implementation_plan.csv](algorithm_implementation_plan.csv) | `bd0ad832d0a97d939e04ef3eb44039bceb89439336864a1821eeee667c1304a2` |
| [candidate_integration_ledger.json](registry/candidate_integration_ledger.json) | `e31ac8f8780647f1ed449f345f3686205a1cbbbfcaf5f35e6a22d7a871997c26` |
| [registry/algorithm_scope.json](registry/algorithm_scope.json) | `c40bb555277662c5489564b67c8993f26624565e41aabedee19ea1f1b8b76f97` |
| [build/v32-evidence-20261010/current-r2/active33/plan.json](build/v32-evidence-20261010/current-r2/active33/plan.json) | `d3eb492a6d7cdcd777432efae067a8521d86c0d7de9f9bb81adff13437fe7313` |
| [build/v32-evidence-20261010/current-r2/active33/summary.json](build/v32-evidence-20261010/current-r2/active33/summary.json) | `d3c78795d3d9b507e270af7f7127d3020c599393f4747d9359b6ff1fa24274d5` |
| [build/v32-evidence-20261010/current-r2/active33/four_matrices.json](build/v32-evidence-20261010/current-r2/active33/four_matrices.json) | `4a45abbe99be9cb04b1b84431aaf064d57349ea8459d6703c2dde58872414640` |
| [build/v32-evidence-20261010/current-r2/completion-final.json](build/v32-evidence-20261010/current-r2/completion-final.json) | `27f0ec760111a9238c01f29b862649f60c899db4a3fbee1612a4ea1152e78ae2` |
| [build/v32-evidence-20261010/current-r2/requirement_acceptance-final.json](build/v32-evidence-20261010/current-r2/requirement_acceptance-final.json) | `f7f8b6a59f7a9d1397da06a1c6238cbd96e6d004f02eca0671f012cecbb3b0eb` |
| [build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/pipeline/plan.json](build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/pipeline/plan.json) | `281b8b00de5af1adf9c7aee27f9f2f83600bb56115b068da12f5f597edb6d33c` |
| [build/v32-evidence-20261010/current-r2/channel-collection/qualification.json](build/v32-evidence-20261010/current-r2/channel-collection/qualification.json) | `4b57d2ac8b727d8790b314277f4a2658b411535834456c86e2f878d05184b713` |
| [TimeSeries_Compression_Benchmark_V3_工程实施总计划.md](TimeSeries_Compression_Benchmark_V3_工程实施总计划.md) | `a1be53aca5204b0fefb6a88b2ba59ec6afeb3c3aa1ac51dd2a9b457539bbf33d` |
| [docs/reviews/independent_benchmark_review_20261010.md](docs/reviews/independent_benchmark_review_20261010.md) | `0c0cf4e6fa0d627074fd1834a7b9e008b5b3731e83469e73473d76f61a2f6f35` |
| [docs/algorithm_capability_support_matrix_20261010.md](docs/algorithm_capability_support_matrix_20261010.md) | `30db8ee42ba3f351c6384b1f368c300ddcb5b972bd709c2114948244ff04b822` |
| [build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/stream/workload_analysis.json](build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/stream/workload_analysis.json) | `5c2f8249e7dd89e7fa35a81ad22106092ab5e465def1d88d810a5abcd7c19738` |
| [build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/query-warm/workload_analysis.json](build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/query-warm/workload_analysis.json) | `7623de99e077196308e645c6afbcd647ffa7f337332170ee41a17e15ad9c84fa` |
| [build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/query-fresh/workload_analysis.json](build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/query-fresh/workload_analysis.json) | `858dcf1a96d2dc3dbbf87f8d4d16496d1306bf9da89df426977611c790d244b0` |

33 个活动 manifest 快照摘要：`711f249356b57b0f2d9d4c39bfa5a12adf1e6c880770b1e485fb89a4c3049059`。计算方法：按 key 排序的 `key/path/sha256` 列表，经 UTF-8、JSON sort_keys、无空格分隔序列化后取 SHA-256；各算法 manifest 链接见每行。


## 8. 算法入口与 CSV 分类记录对应

下表保存主分类记录及所有活动关联记录，便于后续增补与清单重编号时核对。当前覆盖全部 33 个活动入口；关联记录不增加算法或方法数量。

| 算法入口 | 主分类记录ID | CSV 算法名称 | 全部关联记录ID |
| --- | --- | --- | --- |
| [lzss-raw](registry/codecs/lzss-raw.json) | V2 | LZSS | V2 |
| [lzss-dipperstein-c](registry/codecs/lzss-dipperstein-c.json) | V2 | LZSS | V2 |
| [deflate-zlib](registry/codecs/deflate-zlib.json) | V4 | DEFLATE | V1、V4 |
| [lz4-frame](registry/codecs/lz4-frame.json) | V5 | LZ4 | V5 |
| [snappy-raw](registry/codecs/snappy-raw.json) | V6 | Snappy | V6 |
| [zstd-frame](registry/codecs/zstd-frame.json) | V7 | Zstandard (Zstd) | V7 |
| [brotli-stream](registry/codecs/brotli-stream.json) | V8 | Brotli | V8 |
| [xz-stream](registry/codecs/xz-stream.json) | V9 | LZMA / xz | V9 |
| [abba](registry/codecs/abba.json) | V16 | ABBA | V16 |
| [fabba](registry/codecs/fabba.json) | V17 | fABBA | V17 |
| [neats-lossless-i64](registry/codecs/neats-lossless-i64.json) | V39 | NeaTS / LeaTS | V39 |
| [leats-lossless-i64](registry/codecs/leats-lossless-i64.json) | V39 | NeaTS / LeaTS | V39 |
| [sprintz-delta](registry/codecs/sprintz-delta.json) | V42 | Sprintz-Delta | V42 |
| [sprintz-delta-u8](registry/codecs/sprintz-delta-u8.json) | V42 | Sprintz-Delta | V42 |
| [sprintz-fire](registry/codecs/sprintz-fire.json) | V43 | Sprintz-FIRE | V43 |
| [sprintz-fire-huff0](registry/codecs/sprintz-fire-huff0.json) | V43 | Sprintz-FIRE | V43、V77 |
| [sprintz-fire-u8](registry/codecs/sprintz-fire-u8.json) | V43 | Sprintz-FIRE | V43 |
| [chimp](registry/codecs/chimp.json) | V47 | Chimp | V47 |
| [chimp128](registry/codecs/chimp128.json) | V48 | Chimp128 | V48 |
| [elf](registry/codecs/elf.json) | V50 | Elf | V50 |
| [elf-plus](registry/codecs/elf-plus.json) | V51 | Elf+ | V51 |
| [elf-star](registry/codecs/elf-star.json) | V52 | Elf* / SElf* | V52 |
| [self-star](registry/codecs/self-star.json) | V52 | Elf* / SElf* | V52 |
| [alp](registry/codecs/alp.json) | V53 | ALP | V53 |
| [alp-rd](registry/codecs/alp-rd.json) | V54 | ALP_RD | V54 |
| [serf-qt](registry/codecs/serf-qt.json) | V65 | Serf-Qt | V65 |
| [serf-xor](registry/codecs/serf-xor.json) | V66 | Serf-XOR | V66 |
| [zfp-accuracy-1d](registry/codecs/zfp-accuracy-1d.json) | V67 | zfp | V67 |
| [deepzip](registry/codecs/deepzip.json) | V68 | DeepZip | V68 |
| [dzip](registry/codecs/dzip.json) | V69 | DZip | V69 |
| [huff0](registry/codecs/huff0.json) | V77 | Huff0 | V77 |
| [fse](registry/codecs/fse.json) | V78 | FSE | V78 |
| [simdcomp-u32](registry/codecs/simdcomp-u32.json) | T37 | SIMDComp | T37 |
