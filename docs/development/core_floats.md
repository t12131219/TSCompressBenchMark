# 浮点 codec 直接原生入口

实现范围为 ALP、ALP-RD、Chimp、Chimp128、Elf、Elf+、ElfStar、SElfStar、Serf-QT、Serf-XOR 和 ZFP fixed accuracy。C1／对象接口继续保留；ALP／ALP-RD于2026-10-17已替换为safe-v1，详见[接入报告](../alp_integration/README.md)。新增入口不调用 `tscb_compress`，也不创建其输入描述帧。

## 输入与计时

输入为任务原始 dtype、原始 C／F 物理连续布局的完整有效字节。上述算法采用 `physical-contiguous-stream` 方法，整个物理数组视为一条标量流；不会在 Python 中转置 SOA 或重复时间戳。原生内部的对齐复制、行组／块构造、padding、采样、建模、异常分支、编码、必要序列化及结束均发生在 `tsbench_core_encode` 内。

prepared context 保存任务几何和配置，不保存数据导出的模型。每次 encode 都重新执行该算法必需工作；这组实现的底层库多为单次返回 vector API，prepared 不能消除其内部必要分配。vector 产物移动所有权返回，生命周期独立于 context，release 由 driver 在批计时外执行。多帧集合和多块结果恢复所需拼接属于计时内工作。

## 完整输出格式

| 方法 | 返回并完整计费的输出 | 独立恢复信息 |
| --- | --- | --- |
| ALP／ALP-RD | safe-v1 `ALPRW001` 完整原生对象 | dtype、method、count、payload length、各组scheme／字典、参数、base、packed数据、exceptions、padding和CRC |
| Chimp／Chimp128 | 串联完整 `CMP1` intrinsic frames | width、variant、count、payload bits／length、END、checksum；每帧自身长度可取界 |
| Elf／Elf+／ElfStar | 串联完整 `ELF1`／`ELP1`／`ESF1` intrinsic frames | width、count、payload length、参数／Huffman 数据、END、checksum |
| SElfStar | 完整 `SST1` session | width、块数、块长度、完整自适应 session 编码、END、checksum |
| Serf-QT／Serf-XOR | `SQC1`／`SXC1` 完整 core 流 | width、count、block size、bound、adjustment、block reset、valid bits、异常原始块 |
| ZFP fixed accuracy | 原生 `ZFP_HEADER_FULL` 与完整压缩体 | 原生 header 内的 type、1D field geometry 和实际精度模式，无 `ZFA1` 外围帧 |

所有格式都无 C1 输入 envelope，也无实验管理 JSON、hash、来源信息。已有 codec 自身完整帧内的格式校验信息仍完整计费，不能通过估计扣减。Serf core 使用明确不同的 `SQC1`／`SXC1` 标识；其 encode 在构造时不计算可选的 FNV checksum，decode 不做整流 FNV 扫描，完整恢复参数与块记录照常序列化。旧 C1 的 `SRQ1`／`SRX1` checksum 格式和校验保持原行为；新 core 流不是事后裁剪旧产物或估计扣大小。ALP 的固定向量 padding 以及 ZFP 的四值块尾 padding 不改变有效原始字节分母。

`block_size` 在 rewrite 类算法中真正决定物理标量流的分块，不能忽略。连续的 intrinsic frame 自带 payload 长度，故不需要旧 RWF1 集合头与目录。SElfStar 保留同一 session 内跨块状态，没有在每块重置为独立算法。

## 验证与原源约束

Elf 和 Elf+ 的冻结 standalone `compress()` 包含 `decode_raw + memcmp` 回读。为把验证放在主计时外，新增可审查补丁 `adapters/rewrite_lossless/patches/direct_core_no_validation.patch`，仅添加 `compress_unchecked()`：其 `raw_encode(..., true)`、frame 和序列化与旧 `compress()` 完全相同，移除了额外回读。旧 API 行为及冻结 vendor 文件不变。构建应在复制的 adapter 根目录执行 `patch -p1`，仅编译该构建目录中派生源码，并把 patch 及派生源码纳入 provenance。core 层前向声明新符号，不改变冻结 public header。

原源数值域拒绝仍在算法内部保留；没有原始存储 fallback。对于原源回读才可发现的非无损值，core 可能返回产物，但主时钟结束后的框架逐产物验证必须使整行结果失效。`unchecked` 不是降低正确性要求。

ZFP 的原生 fixed-accuracy 入口明确不支持空 1D field、非有限值、subnormal 和负零。整流源域扫描通过可选 `tsbench_core_validate_input` 在主计时前执行一次；encode 不重复扫描这些验证条件，仅执行实际 field／mode 配置、完整 header 和原生压缩。它不会沿用对象层按列原始存储例外，因为那会改变被测方法。旧对象入口仍保留其原有例外表达。decoder 从完整 header 恢复实际精度，创建时配置为 `{}`，不使用 encoder bound。

2026-10-17起，ALP 使用冻结 safe-v1 的自适应十进制／RD选择，ALP-RD 强制RD。这是独立登记的新来源和绑定身份。旧forced decimal实现已退出当前构建，其源码和未提交修改已归档，历史运行身份不变。两方向均使用caller buffer；encode内部仍包含冻结API的临时分配、复制、采样、序列化和CRC，完整对象按实际used计费。Serf 原有显式 raw exception block 属于其公开完整算法组合格式，照实计费并记录在流中。

## 验证安排

新增 `benchmark/tests/test_core_floats.py`，对每种方法检验 float32／float64、C／F 物理布局、多块尾部、ALP／ZFP padding、有／无损恢复、decoder 无 encoder 参数、产物在 context 销毁后仍有效、空输入、原源 NaN 拒绝、ZFP 特殊值拒绝、截断帧拒绝。测试仅调用中央构建产物的单次函数，不构建，也不提供性能结果。

该实现由主任务统一构建、测试和正式测量；本日志不把尚未执行的验证声明为通过。
