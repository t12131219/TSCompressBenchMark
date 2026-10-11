# 用户指定算法退出记录（2026-10-10）

已从活动架构移除 27 个 Codec key，以及指向已退出实现的 3 个别名。删除覆盖 manifest、接入卡、独占 SourceArtifact、adapter、集成 vendor、构建路由、冻结/登记/资格工具与专属配置和测试；共享基础设施继续供保留算法使用。

## 退出入口与原 CSV 关系

| 已退出 Codec key | 原 CSV 记录与名称 | 对照说明 |
|---|---|---|
| `corad` | V11 · CORAD | 退出决定覆盖该入口；CSV 原文保留 |
| `delta-maskedvbyte-u32` | T4 · Delta + Masked VByte | 退出决定覆盖该入口；CSV 原文保留 |
| `delta-simdcomp-u32` | T1 · First-order Delta / D-gap；T53 · SIMDComp | 机制＋SIMDComp 的组合；**CSV 无此组合的同名单独行**，独立 simdcomp-u32 保留 |
| `delta-varint` | T2 · Delta + VarInt；T3 · Delta + ZigZag + VarInt | 退出决定覆盖该入口；CSV 原文保留 |
| `delta-zigzag-streamvbyte-modern64` | T5 · Delta + Stream VByte | 共享对应组合/算法行的实现版本；均退出 |
| `delta-zigzag-streamvbyte64` | T5 · Delta + Stream VByte | 共享对应组合/算法行的实现版本；均退出 |
| `fast-differential-u32` | T1 · First-order Delta / D-gap | 退出决定覆盖该入口；CSV 原文保留 |
| `fastpfor-simple8b-rle-u32` | T65 · FastPFOR Simple8b_RLE | 退出决定覆盖该入口；CSV 原文保留 |
| `for-simdcomp-u32` | T66 · Frame of Reference (FOR)；T53 · SIMDComp | 机制＋SIMDComp 的组合；**CSV 无此组合的同名单独行**，独立 simdcomp-u32 保留 |
| `influxdb-tsm-adaptive-timestamp` | T121 · TSM Adaptive Timestamp Encoder | 退出决定覆盖该入口；CSV 原文保留 |
| `littleintpacker-bmi2-u32` | T54 · LittleIntPacker；T50 · Fixed-width Bit Packing | T54 的实现/API 变体，T50 为机制关联；CSV 无此 key 的单独行 |
| `littleintpacker-horizontal-u32` | T54 · LittleIntPacker；T50 · Fixed-width Bit Packing | T54 的实现/API 变体，T50 为机制关联；CSV 无此 key 的单独行 |
| `littleintpacker-pack32-u32` | T54 · LittleIntPacker；T50 · Fixed-width Bit Packing | T54 的实现/API 变体，T50 为机制关联；CSV 无此 key 的单独行 |
| `littleintpacker-sc-u32` | T54 · LittleIntPacker；T50 · Fixed-width Bit Packing | T54 的实现/API 变体，T50 为机制关联；CSV 无此 key 的单独行 |
| `littleintpacker-turbo-u32` | T54 · LittleIntPacker；T50 · Fixed-width Bit Packing | T54 的实现/API 变体，T50 为机制关联；CSV 无此 key 的单独行 |
| `maskedvbyte-u32` | T28 · Masked VByte | 退出决定覆盖该入口；CSV 原文保留 |
| `prometheus-float-histogram-st` | T108 · Prometheus Histogram-ST / FloatHistogram-ST | 退出决定覆盖该入口；CSV 原文保留 |
| `prometheus-histogram-st` | T108 · Prometheus Histogram-ST / FloatHistogram-ST | 退出决定覆盖该入口；CSV 原文保留 |
| `prometheus-xor-chunk` | T105 · Prometheus XOR Chunk；T12 · Prometheus XOR Chunk Timestamp Codec | 退出决定覆盖该入口；CSV 原文保留 |
| `prometheus-xor2-chunk` | T106 · Prometheus XOR2 Chunk | 退出决定覆盖该入口；CSV 原文保留 |
| `simple16-u28` | T63 · Simple-16 | 退出决定覆盖该入口；CSV 原文保留 |
| `simple9-u28` | T62 · Simple-9 | 退出决定覆盖该入口；CSV 原文保留 |
| `simple9hacked-u28` | T62 · Simple-9 | 共享 T62；**hacked 变体无单独行** |
| `streamvbyte-modern-u32` | T27 · Stream VByte | 共享对应组合/算法行的实现版本；均退出 |
| `streamvbyte-u32` | T27 · Stream VByte | 共享对应组合/算法行的实现版本；均退出 |
| `tristan` | V10 · TRISTAN | 退出决定覆盖该入口；CSV 原文保留 |
| `walloc-1d` | V108 · WaLLoC (1D Codec) | 退出决定覆盖该入口；CSV 原文保留 |

`gorilla`、`delta-of-delta`、`second-order-difference` 原指向 `prometheus-xor-chunk`，同时退出。

## 范围与恢复

[活动算法对照](registered_algorithms_20261010.md)列出保留的 33 个范围内真实入口、3 个范围外残留登记、4 个 oracle 和 1 个别名。`bzip2-stream`、`lzsse2-raw`、`lzsse8-raw` 不在本次删除请求中，保留原登记并明确记录本地构建产物缺失。

原始 `Compression_Source_Code` 与独立 `Compression_Rewrite` 源码保留。历史 runs/outputs 和旧资格报告保留用于追溯；旧 PASS 不自动取得新执行闭包的资格。Dataset_Verify 数据及通用测试 fixture 保留，继续排除 Git。

删除/修改前的可恢复副本位于 `/tmp/tsbench-requested-algorithm-removal-20261010/`。该临时归档不作为长期唯一备份；已跟踪文件可通过 Git 历史恢复。相关接入提交 `cda83c9`、`185fdbc`、`74c1e59` 混合了算法接入和保留框架功能，因此未整笔 revert；本次按文件与活动路由清理，未修改分支提交历史。

原 CSV SHA-256：`536dda0cdb068da2014b1a0638d6cca7e7f1cb92a750d4528ead272d5e1b665c`，内容未修改。

`registry/algorithm_scope.json` 的退出 key 与计划记录决定过滤范围；源码审计、工作清单生成和重写登记只消费活动范围。T50 的通用 bit packing、T53 的独立 SIMDComp、T66 的通用 FOR 方法记录可继续作为未来候选材料，不能据此自动恢复已退出实现。重新接入须明确变更范围并按 V3 完成新验收。

## 验证

- CLI 登记检查 PASS：40 个根项、102 个 SourceArtifact、1 个别名。
- 扩大回归：**795 passed / 3 failed**；三个失败分别来自 `bzip2-stream`、`lzsse2-raw`、`lzsse8-raw` 的既有本地构建产物缺失。本次没有删掉这些测试或扩大删除范围。
- 33 个范围内入口的主工件与支持闭包存在性/哈希门禁全部通过。
- SIMDComp：504 个直接 SDK 用例通过，原生证据独立审核通过；新资格矩阵 12 条观测、24 条拒绝诊断通过独立五层审计。Python 闭包重签使用真实新执行；旧失败和旧 FORMAL 均保留。
- 六个保留无损重写入口的 ASan/UBSan C ABI 资格通过；ABBA、fABBA、DeepZip、DZip 的 **8 项 release/sanitizer CTest 资格全部通过**。四包接入卡依据这些新构建和资格证据刷新。
- 受影响运行与范围模块 Ruff 通过，`git diff --check` 通过；全仓旧工具的其他格式问题没有被冒称通过。
- Dataset_Verify 仍由 Git 忽略。

机器记录：[退出审计 JSON](algorithm_retirement_20261010.json)。原始日志复制到 `build/algorithm-retirement-20261010/` 并记录 SHA-256。此处不签署全数据域、全参数、源码全域一致性或新 FORMAL 性能资格。
