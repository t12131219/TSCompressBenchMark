# Dataset_Verify：V3 第一轮实施与验证

日期：2026-10-09。依据：V3 §3、§5.2、§6.2、§8.3、§9、§10、§14、§15.1。

本轮先修正式数据入口和基础正确性，再验证当前全部注册入口。验收对象是每个入口的合法输入完整流程，以及分层数据矩阵中的可审计终态；不要求算法接受其源合同之外的所有数据。后文数字只描述本轮明确的配置与数据范围。

## 1. 已完成的实现

### 1.1 无后缀 canonical 正式数据源

- 发布独立 `tscb.canonical-source-manifest.v1` 与 `tscb.dataset-content.v1` identity policy，保留旧 CSV/NPZ v2 身份规则。
- 新入口按 magic/version 读取，不依赖文件后缀。统一经过 Registry、loader、画像、准备快照、规划、Preflight、隔离执行、正确性、账本与报告。
- dataset 身份由验证后的逻辑内容、parser policy 与 split 确定；transport SHA 和内嵌历史 DatasetID 不参与，消除自引用循环。重新序列化、重新导入和 resume 已验证。
- Reader 在分配前核对 metadata/buffer 长度，限制 metadata 和 buffer 数量；验证 dtype、shape、载荷长度/hash、T/V 长度、validity bitmap 尾位，并独立重算 RawBits。导入后再次核对 transport SHA，防止登记后文件被替换。
- canonical arrays 保持只读。许可与 train/test split 明确登记，不从格式转换自动取得许可或 learned 资格。

相关实现：[canonical source](../src/tscompbench/datasets/canonical_source.py)、[Reader](../src/tscompbench/datasets/canonical.py)、[Schema](../schemas/canonical-source/v1/dataset-manifest.schema.json)、[CLI](../src/tscompbench/cli.py)。

### 1.2 版本化验证集

`Dataset_Verify` v1 的 1,356 份文件保持原样。UTS 生成新的 v3 文件，将逻辑形状从 `[N,1]` 修为 `[N]`，保留原始载荷；合法 rank=1 uint32 数据因此可以进入 StreamVByte/Simple9 等入口。原 MTS 文件可通过新源 manifest 登记，未私改其语义。

v3 共登记 1,409 份源：原矩阵的版本化视图、专用合同样本、40 份 N=2 边界数据。专用样本从现有资格输入生成，包括音频、Histogram record、受限符号模型以及 ND oracle，保留其实际合同和 split。普通矩阵没有被重新命名为音频或 Histogram。

生成与运行工具纳入代码管理，数据、manifest 和本地大输出仍不推送 Git：

- [生成/登记](../tools/prepare_dataset_verify_v3.py)
- [保留原 hash 的 v1 生成器](../tools/dataset_verify_v1/README.md)，四种模式/类型代表样本重新生成后与原完整容器 SHA 一致
- [全根入口三轨道协商矩阵](../tools/plan_dataset_verify_v3.py)
- [每入口三种计时范围的正向资格](../tools/verify_dataset_verify_v3.py)
- [分层完整输入资格矩阵](../tools/qualify_dataset_verify_v3_grid.py)
- [身份、执行产物与原始结果复核](../tools/summarize_dataset_verify_v3.py)

### 1.3 基础适配与数值正确性

- ND 通道数采用 `prod(shape[1:])`，扩宽大小按实际全部元素计算。当前 time_axis 仍按现有第一轴合同；这不是通用 ND 轴映射管线。
- 时间顺序用相邻整数比较，避免 `np.diff(int64)` 在 min→max 时溢出而误判。
- 每个适配 operation 保存实际前后 dtype/shape/有效字节、operation wall time、可观察输出 allocation/copy/padding，并保留计划估计。连续化 no-op 和转置 view 不再被计作真实拷贝。
- 这些内存字段标为 `OBSERVED_NUMPY_OUTPUT_BUFFERS`；不代表 allocator 内部全部分配、peak live bytes 或 RSS，也不代表硬件访问计数。
- IEEE 极大有限值的画像使用扩展精度。不能表示为有限 JSON float 的诊断量写 null，并保存数值政策；画像不修改原始位模式。
- Runner 按当前 task 载入 canonical payload，只保留当前数据集，避免整个验证语料同时驻留并被 worker 继承。

### 1.4 signaling NaN 的归属

普通数值扩宽 `float32 → float64 → float32` 可将 signaling NaN quiet 化，例如 `0x7f800001` 可能变成 `0x7fc00001`。因此，“数值扩大位宽”不能无条件声明 IEEE 位级无损。

框架先执行独立逆向位校验。**仅当存在 EXACT_WIDEN，且不一致的原始元素全部是 NaN 时**，返回 `UNSUPPORTED / ADAPTER_BIT_EXACT_DOMAIN_UNSUPPORTED`，不调用压缩器；有限值不一致仍作为适配错误处理。测试同时证明原输入未被修改，并检查有限值损坏不能被转换成 UNSUPPORTED。

这是输入适配域的限制，不能据此判定重写 codec 有异常。原生 codec 对其声明支持的 IEEE 域仍需位级验收；原版与重写的一致性另按 V3 §8 验证。若以后扩大此域，应登记保留 IEEE bits 或 exceptions/side information 的显式管线，并计费、冷解码；不能 silently canonicalize NaN。

### 1.5 并行资格验证与后续发现

按用户要求，分层 QUALIFICATION 采用 6 个独立入口进程，绑定 CPU 0/2/4/6/8/10，拓扑核对为 6 个不同物理核心；调度进程的线程仅负责启动和收集子进程，算法内部线程参数保持各入口的冻结配置。每入口保留配置、CPU affinity、日志、源码快照和独立结果；汇总在主进程串行写入。原串行批次的中断快照及失败记录保留，已完成任务不因此改写为新运行。此方式不用于正式独占性能排名。

新增定位并修复两个问题：Prometheus XOR 的包装层现接收合法行矩阵，并在现有 native 列序列化路径中保存、恢复原布局；矩阵与 SOA 输入的 native frame 字节一致测试通过。XOR2 明确登记 COMPOSITE_T_V，使 SYSTEM 角色不会触发错误的值矩阵逻辑转置；该合同声明产生新 AlgorithmID，旧记录保留。

有损适配的标准 cast 若无法满足声明误差界，且独立重算确认输出确实是指定 cast，现明确拒绝为 `ADAPTER_ERROR_BOUND_DOMAIN_UNSUPPORTED`。非有限值、有限值溢出及有限值舍入超出预算均有测试；若 prepared 内容偏离指定 cast，仍报适配错误。该检查发生于 codec 调用前，未放宽最终原始域误差验证。此修改与 signaling NaN 的位级扩宽拒绝使用不同原因码。

## 2. 资格证据与身份迁移

本轮修复 DeepZip 的有效合同索引为 `contract_v1.md`，未扩大模型字母表或 native 数据域。

共享框架源码改变会使真实消费闭包的旧 SDK/build 证据失效。保留这些拒绝；重新执行受影响 native 构建、安全测试、独立 SDK 测试，再通过原有严格 auditor 和 factory 更新登记。没有手改旧报告的 source hash、移植旧 PASS 或关闭 dependency 门禁。

SIMDComp、FastPFOR Simple、LittleIntPacker、Simple8b-RLE、MaskedVByte 的新 SDK 范围资格分别有 888、322、499、466、159 项测试，共 2,334 项；这些是直接 SDK 范围证据，不是全部源码能力或全数据集性能证据。StreamVByte 两家族重新构建并运行 native 测试。登记前保留原文档/build 备份，刷新工具拒绝覆盖已有批次。

`native_integration_plan.json` 更新当前 candidate 的 AlgorithmID 引用并保存前后映射；历史 source/FORMAL reviews 保留。RLE 最新 12 条资格、80 条正式观测与独立审计已取得，另存实际新证据；工作清单整行评审刷新被 workbook hash 门禁拒绝：当前 Excel 与该清单冻结的历史 Excel 不同。未关闭门禁或改写历史 workbook hash，整行映射评审留待明确版本迁移；见 [延期记录](../outputs/dataset-verify-v3-implementation-20261009/worklist-refresh-deferred.json)。别名不增加独立算法数，oracle 不进入真实算法榜。

## 3. 本轮验证范围

### 3.1 每入口合法输入：213 个完整资格用例

当前 67 个根入口（63 个真实入口＋4 个 harness oracle），加 4 个可选别名，在 CORE、PIPELINE、E2E 各执行一例：**71 × 3 = 213 个用例完成**。

每例均经过正式五层 Runner、压缩/Finalize、独立 decoder、原始域正确性、真实码流账本和 report。分析器重新核对当前 AlgorithmID、完整 manifest、执行产物组合 hash、任务与原始观测、资格模式及报告计数。初始证据漂移失败保留，选定后续新执行作为当前范围证明。

全部为 QUALIFICATION、`eligibility=false`，summary_count=0。资源排除但 correctness=PASS 与正常 PASS 分列；不能将它们签成正式性能结果。SOURCE_PARITY 不由本轮回环推导。

当前身份与执行产物最终复核：[analysis.json](../outputs/dataset-verify-v3-implementation-20261009/final-analysis/analysis.json)。

### 3.2 分层实际执行与全量协商分开

实际执行矩阵包括十种 dtype、四类 T/UTS/MTS 组合的 4 KiB slow 样本、N=2、IEEE 特殊值及每入口专用正向样本；六个 byte/integer 基线另选 64 KiB、1 MiB、16 MiB 三档。完整输入参与编解码验证；sampled64 仅用于只读画像。

该矩阵与正式预定全笛卡尔执行不同。参数采用各入口现有资格模板的首个点；不宣称所有参数、随机模式或全部大模型/大对象均已运行。UNSUPPORTED 的观察原因会保存，但全矩阵的独立“应拒绝”期待规格尚未完备，不报告虚假的正确拒绝率。

最终选定当前批次覆盖 67 个根入口，共 **6,251 条终态记录**：

| 终态 | 条数 | 本轮解释 |
|---|---:|---|
| PASS | 2,739 | 原始域正确性通过，仍为资格记录 |
| RESOURCE_PRESSURE | 7 | 原始域正确性通过，资源门禁排除 |
| UNSUPPORTED | 3,505 | 保留具体合同、源域或适配域拒绝原因 |

共 2,746 条真实编解码与原始域正确性通过，当前选定结果无 SCHEMA_ERROR、CRASHED 或错误重建。UNSUPPORTED 包括能力合同 1,519、未声明有损转换 1,743、实际源域 215、位级扩宽域 24、误差预算适配域 4。未把拒绝记成成功压缩；共 2,186 条观测提供 native 编/解码计时，其余不补造计时。

按入口的计数和 native 可观测范围见 [algorithm_coverage.csv](../outputs/dataset-verify-v3-implementation-20261009/final-analysis/algorithm_coverage.csv)。分析器核对每份当前 manifest、DatasetID、组合 artifact hash、CPU affinity、任务完整性、原始观测及 report；所有批次都是 `eligibility=false`、summary_count=0。旧 reason 名称 `FORMAL_REPETITION_PASS` 不能覆盖冻结的 QUALIFICATION 模式，原因码治理仍待后续阶段。

全量协商是 **1,409 × 67 × 3 = 283,209 项**，其结果为：

| 协商态 | 项数 |
|---|---:|
| DIRECT_SUPPORTED | 36,484 |
| ADAPTER_LOSSLESS | 4,495 |
| ADAPTER_LOSSY | 8,660 |
| UNSUPPORTED | 233,570 |

每条明确 `execution_status=NOT_RUN`、`source_domain_checked=false`。这不是 283,209 次压缩，也不能直接作为源域成功/正确拒绝覆盖。

### 3.3 正式 CLI 与回归测试

无后缀 uint32 UTS 通过正式 CLI import、validate、report 和 resume；StreamVByte 的原始域 correctness=PASS。此例仍是资格模式。

首次 unit、contracts 与 runner integration 共 504 项全部通过；源码/SDK 证据专项另有 71 项通过。并行发现后的修复另有 227 项适配/包装回归及 219 项包装测试通过，包括 native frame 字节一致性。后续广泛回归和受影响证据刷新另存新 XML，不覆盖这些历史。signaling NaN cast 产生一条预期 RuntimeWarning，原始输入仍保持不可变。

最新广泛回归覆盖 505 项：首轮 493 项通过，12 项因历史证据未刷新或新异常类型的旧期待而失败；取得新资格/正式审计、刷新当前引用并更新指定 cast 的异常期待后，这 12 项均通过。两轮 XML 的失败用例与复测用例集合逐一核对相同，当前失败为零，见 [回归汇总](../outputs/dataset-verify-v3-implementation-20261009/regression-current-summary.json)。

单独重跑 Simple8b-RLE 的 80 条 FORMAL 观测，是受影响既有审计的更新：correctness 全部通过，73 条合格、7 条资源排除、4 个摘要；不能代表其他入口已完成 FORMAL，也不作为本轮算法间原生性能比较。该正式执行与全机其他资格/测试活动存在重叠，因此不将它签为 V3 资源独占的受控比较；资源门禁如实保留。

并行发现后的最新闭包另以 `v3-20261009-05` 执行 RLE 12 条专用资格，并在本轮其他测试结束后串行执行 80 条 FORMAL 观测：80 条正确性通过，73 条合格、7 条资源排除、4 个摘要，独立 auditor 通过。该批次绑定 CPU0，记录实际冻结的 native 开关及 marked/unmarked 配置；全项目正式性能、全机资源租约和源域扩展资格不由此推导。其早期历史批次与换页排除仍保留。

## 4. 仍需按 V3 推进的内容

1. 自包含 RecoveryDescriptor，以及不借原 dtype/shape 的冷解码逆恢复。当前基本逆验证仍使用原描述，是过渡基础。
2. COLUMNWISE/任意 time_axis/ND 重组、分块与 raw-tail、T-codec＋V-codec P2。当前 ND 大小修复不是这些完整管线的实现。
3. 18 个重写入口的内部 native timer 与逐 API 边界审计、正式 native profile。CORE 时间继续包含适配器内部操作，不改称 kernel 时间。
4. 独立期待矩阵、failure origin/stage 正交状态、版本化 ComparisonContract 和适配成本完整报告。
5. canonical 内容身份的完整语义字段白名单。当前 v1 排除已知 value-column strides、所有 physical descriptors、内嵌 ID 和 transport SHA；其余 logical 字段保守进入身份。未来额外物理字段的白名单治理应发新 policy，不能原地重标本轮身份。
6. 更多 validity/async/ragged/strided 布局、模型域和窗口边界，以及全体积/全模式的按合同执行；目前的 dataset importer validity 测试不意味着所有 codec 都支持 null。
7. 新源 oracle/fresh source differential、全部参数的源码逻辑对照、FORMAL 大矩阵和资源独占/进程树审计。这些不能由自回环或工厂创建替代。
8. 可审计的重复边界资格复用。当前 `run_boundary_suite(adapter, manifest, track, parameters)` 不使用待测数据，仍在每个合法 task 重跑；LZSS 的该步骤在本轮约占每个 task 12 秒。后续可设计版本化证书，绑定 suite/spec、完整实际 source/build/runtime closure、manifest/参数/Track、平台与资源合同，明确重用来源及失效规则；每份实际输入的适配域、源域、回环与 correctness 仍须真实执行。当前未启用缓存、跳过边界或把历史 PASS 当新运行。

本轮保证当前入口在明确合法样本上能够走完整资格流程，修复基础框架的误拒绝和错误归属；V3 的其余阶段按上述依赖继续实施。

## 5. 复现命令

使用项目 Python，不覆盖已有输出批次：

```bash
PYTHONPATH=src:tools /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/prepare_dataset_verify_v3.py --help
PYTHONPATH=src:tools /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/verify_dataset_verify_v3.py \
  --output outputs/dataset-verify-v3-next/entries
PYTHONPATH=src:tools /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/qualify_dataset_verify_v3_grid.py \
  --output outputs/dataset-verify-v3-next/grid --jobs 6 --cpus 0 2 4 6 8 10
PYTHONPATH=src:tools /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/plan_dataset_verify_v3.py \
  --output outputs/dataset-verify-v3-next/universe
```

Dataset_Verify v1 缺失时先用上述归档生成器重新生成，再运行 v3 登记。新建环境还需按现有 source/SDK/build 规程取得当前资格，不能仅复制旧 PASS JSON。
