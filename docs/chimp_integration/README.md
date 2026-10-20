# Chimp 家族替换接入报告（2026-10-17）

已移除活动路径中的旧 Chimp / Chimp128 实现，接入冻结研究发布包的 **10 个 key**。状态为 **LOCAL_RESEARCH_BINDING_QUALIFIED**：本机 Bench 绑定、对象恢复和原生操作正确性通过；不改签独立包为 FULL_PARITY，也不宣称完成新的正式吞吐验收。

## 来源、删除与隔离

完整阅读 V3.0 移植标准、V4.0 实施计划，以及此次独立包 README、contract、FRAME_FORMAT 和完整验证报告后，先写 [接入计划](PLAN.md)，再实施。

消费发布包 SHA-256：`7161320b6df76d07dc397a1199ca6341012e088ffebb5d10173cbbc11caf46dc`；上游提交 `320d397157c7e0696b3c64dc1711fc17a3add3da`；实现 `chimp-family-cpp-scalar-v1`。从归档选择性读取 **62 个文件**，逐个核验 RELEASE_CONTENTS 哈希，写成独立普通文件；没有展开 133004 个条目的整个包，也没有修改发布包硬链接的源文件。[冻结清单](../../adapters/chimp_family/FROZEN_SOURCES.json)在每次构建前核验。源码与头文件保持原样；Bench 代码只在绑定／注册／执行层。

旧 vendor、共享 shim（包含接入前已有的未提交修改）、冻结清单和旧卡片，先保存到 [旧实现归档](legacy-chimp-before-family.tar.gz)。旧两个 source manifest 另存 [来源归档](legacy-source-manifests.tar.gz)。活动 vendor/chimp、共享 shim 中的 Chimp 分支、旧冻结入口和旧来源清单已移除。Elf / Elf+ / Elf* / SElf* 的核心没有替换，四者已重新构建并通过回归。既有 ALP、Gorilla 和其他工作区修改没有回退。历史报告和性能数据保留原身份。

## 注册与语义

| key | 输入 | 算法 / 历史窗口 | 源差分接入案例 |
| --- | --- | --- | ---: |
| chimp | f64 | Chimp | 655 |
| chimp32 | f32 | Chimp32 | 655 |
| chimp128 | f64 | ChimpN，固定 128 | 656 |
| chimpn | f64 | ChimpN，可配置 N | 667 |
| chimp128-no-index | f64 | ChimpNNoIndex，固定 128 | 656 |
| chimpn32 | f32 | ChimpN32，可配置 N | 667 |
| pmc-mr | f32 | PMC-MR | 1896 |
| swing-filter | f32 | Swing Filter | 1893 |
| swing-filter-disjoint | f32 | Disjoint Swing | 1896 |
| swing-filter-disjoint-quantized | f32 | Quantized Disjoint Swing | 1896 |

Chimp128 和 ChimpN(history=128) 字节完全一致，分别覆盖注册入口。N 必须为 1..65536 的二次幂。旧 chimp / chimp128 的 f32 配置应改为 chimp32 / chimpn32；不再隐式扩大到 f64。FPC 和 quantized.filter2 没有注册。

无损保留 `block_size`（默认 1000，范围 1..1048576），每块独立、尾块准确，空输入产生一份完整 CFP1 帧。保留正负零、子正规数、无穷和允许的 NaN payload；正规范 qNaN 是源码 EOF，明确拒绝，不做原始字节降级。

四个有损方法使用有限 f32，按列构造隐式 `t=0..N-1`，不冒充任意时间戳／稀疏网格接入。PMC 可空；Swing 至少两个点；Disjoint 和 Quantized 至少一个点。epsilon 转为有限 f32，正值下溢拒绝，Quantized 必须正数。输出质量元数据从实际 CFP1 头和 CRC 恢复 epsilon，明确它是源码阈值；quality_mode 来源是编码配置，不假称存于帧中。

默认 `quality_mode=strict_abs` 调用独立包的实际重构检查：非有限或 maxABS 超过 f32(epsilon) 就拒绝整次输出。`compatible` 保留已知源码行为，只准进入 `empirical_quality`。严格模式是逐输入验证／拒绝策略，不是普适误差定理；框架仍按任务独立检查实际质量，decimal 任务界与 f32 参数分别保留。相对误差任务不开放。Swing 的 41 个、Quantized 的 82 个已知误差失败案例（含单点非有限）均在本次严格重放中正确拒绝，未静默修复。

## 边界、冷恢复与计费

默认 native_core 直接消费物理连续输入，调用冻结 owning-vector API。输入 word / Point 暂存、独立对象构造、reset、完整帧、重构及严格检查均为操作内部工作；两个方向都返回独立 owned vector，结果在 context 销毁后仍有效，release 后释放，不虚称 caller-buffer 或无分配内核。

无损 core 按物理连续标量流处理 C/F 布局；有损 core 限 rank1／单列，避免跨列拟合。对象和辅助 native_api 支持独立列矩阵。C1 输入 CFI1 为 16 字节描述头加 SOA 数据；完整 CFS1 输出为同样几何头加每列 8 字节长度和完整 CFP1 分块流。core 的多个 CFP1 用其自身 payload length 分界。所有帧元数据、CRC、EOF、padding、块、CFS1 头和列长度都计费，没有隐藏模型或未收费索引。

解码从帧恢复参数，检查方法、固定 N、类型、计数、长度、CRC、单位网格及 trailing bytes；core 冷解码器不接收编码器参数。C1 还核对请求 shape/dtype。失败不修改 caller 输出；容量不足可重试，reset 保留配置，finalize 必须恰好一次且输出零字节。边界错误消息使用固定缓冲区，避免错误处理时再次分配。

## 实际验证

[机器证据与最终构建身份](evidence.json)、[逐 key 源差分报告](source-qualification.json)、[压缩案例日志](source-cases.jsonl.gz)、[对象／原生产物报告](object-native-qualification.json)、[sanitizer 结果](sanitizer-result.json)、[完整测试日志](pytest.log)。

- 独立 CMake 构建的契约和分配失败测试：2/2 通过。
- **11537 个接入案例、5679407 个输入值**：完整帧比较、存档原始 Java 证据重放、**本次新编译 Java 源码差分**、独立 C++ CLI 冷解码以及 Bench 冷解码通过。无损还做 Java→Bench、Bench 原始码流→Java 的双向交叉解码；有损核对 Java segment／重构语义，保留有限值及正负零的位模式，只规范化 Java 未指定的算术 NaN payload/sign。该计数含 Chimp128 别名重复验证，不代表独立新数据集规模。
- 选择明示：排除未请求 FPC/filter2 的 2557 个条目、固定 no-index=128 之外的 11 个条目、非单位索引时间轴的 24 个条目，以及独立验证中的 8 个非 PASS 条目；没有悄悄计入成功。案例索引及 verification 文件与发布包逐哈希绑定，见 [来源核对](baseline-release-binding.json)。独立包完整 13473 案例资格与本次 Bench 子域分开。
- **40 个对象案例**：全部 10 key，C/F 矩阵、完整列／channel+chunk，输入不变、外层 wire、独立新进程 CLI 解码及质量参数解析通过。
- **40 组 native 检查、120 份产物**：全部 key × core/API × prepared/fresh_request；2 次操作+1 次 warmup 的每份产物均校验，独立进程恢复通过。完整输出长度与 bits/value 核对，保留实际 runtime maps。仅为小规模资格操作，不进入正式性能表。
- **64 个 sanitizer 案例、全部 10 key**：实际最终绑定在 ASan+UBSan+LeakSanitizer 下通过，detect_leaks=1、halt_on_error=1，stderr 为空。覆盖未对齐输入、容量／重试、首尾 canary、截断／CRC、原子失败、EOF、上下文与 owned 结果生命周期及严格误差拒绝。
- **10 项资源上限检查**：每个 key 实际编码／冷解码 1048576 个常量值、逐位恢复，并明确拒绝 1048577；单独记录于 [上限证据](resource-profile.json)，不并入源差分数据规模或性能结论。
- **962 项完整 Python 回归通过**，涵盖新绑定以及原有算法／配置／记录／测量／报告。新 key 总数为 45 个原生 codec（另有 raw-store 参考）。示例的真实 f32/f64 数据域和原生 admission 已核验。

## 复现入口

```bash
PYTHONPATH=benchmark/src python3 -m tsbench build chimp chimp32 chimp128 chimpn chimp128-no-index chimpn32 pmc-mr swing-filter swing-filter-disjoint swing-filter-disjoint-quantized
cmake -S adapters/chimp_family/vendor/chimp_family -B build/chimp-family-integration/reference -DCMAKE_BUILD_TYPE=Release
cmake --build build/chimp-family-integration/reference --parallel 2
ctest --test-dir build/chimp-family-integration/reference --output-on-failure
PYTHONPATH=benchmark/src python3 benchmark/tools/qualify_chimp_family.py \
  --baseline /home/fzg/PycharmProjects/Compression_Rewrite/ReWrite/chimp-family/validation/qualified-v2 \
  --cli "$PWD/build/chimp-family-integration/reference/chimp_cli" \
  --out build/chimp-family-integration/replay-new --fresh-java
PYTHONPATH=benchmark/src python3 docs/chimp_integration/qualify_objects.py --out build/chimp-family-integration/objects-new
PYTHONPATH=benchmark/src python3 -m pytest -q benchmark/tests
```

示例：[f64 无损](../../benchmark/examples/chimp-family-lossless64.toml)、[f32 无损](../../benchmark/examples/chimp-family-lossless32.toml)、[有损经验质量](../../benchmark/examples/chimp-family-filters.toml)。有损例子显式兼容模式；需要严格检查时改为 strict_abs，并按任务设置独立质量界。全 core 设计生成器已分开 dtype 和质量分组，使用新输出目录，避免覆盖旧冻结设计。

## 资格限制

本轮是 Linux x86_64、本机工具链、SCALAR、单线程 Bench 接入验证。独立包的 AArch64/QEMU、Clang、50000 fuzz、TSan 或可复现构建结果没有继承为新绑定的结果。本轮没有重跑 FORMAL 吞吐、跨真实语料排名或签署 REWRITE_DONE / FULL_PARITY；历史运行不能回填为本实现。源码 add() 每值调用 reserve(raw_bound)，大块可能有频繁分配成本；本次未修改该冻结行为，性能另行测量。

许可事实和已有 `CHIMP-LOCAL-RESEARCH-20261017` 限定保留在冻结包中：本地实验研究范围，到期 2026-11-17，不推断外部分发授权。核心、绑定、编译选项、ISA、工具链或 runtime 改变时按受影响依赖重新资格与测量。
