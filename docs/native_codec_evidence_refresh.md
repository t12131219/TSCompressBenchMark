# 原生整数入口的执行证据修复（2026-10-07）

此前被当前工厂拒绝的 13 个入口已恢复，并通过本轮的 SDK、五层与正式重复审计。
最终再次检查了全部 63 个原生入口及 4 个框架测试 oracle 的创建/关闭，会话全部通过。
本轮完成的是现有 C/C++ 实现的执行证据与 Benchmark 接入资格修复。
清单中仍保留 221 个逻辑条目，完整逻辑条目验收计数仍为 0。

## 原因及修复

已有构建与 SDK 记录冻结的 Python 执行依赖发生变化，包括 factory、preprocess runtime、
measurement contracts、repetition、registry 和 planning resolution。工厂拒绝旧哈希的行为正确。
本轮重新执行原生构建、release/debug/sanitizer 验证与直接 Python SDK 资格，再更新注册所消费的
构建哈希、已独立审计的测试报告哈希和实际 SDK source closure。

没有修改原始或 vendored C/C++ 算法，没有放宽工厂依赖校验，也没有手工替换旧 SDK 快照哈希。
13 项 SourceArtifactID 均保留。SIMDComp 与 Simple 的 6 个 AlgorithmID 随真实 Python SDK
closure 更新，其余 7 个 AlgorithmID 保留。独立核对确认输入范围、API、格式、语义、参数、
ISA 和能力合同未改变。

`tools/refresh_native_sdk_registration.py` 保留 before/candidate 注册文件。
只有已验证的 SDK 与原生报告可以进入刷新；若最终工厂检查失败，全部注册文件原字节回滚。
新增回归测试覆盖执行源码漂移、测试输出漂移和回滚，防止成功标签掩盖旧证据。

第一次刷新因 raw observation 状态不能直接作为 PASS 而停止，尚未写入注册。
随后保留原始观测状态，使用独立 SDK auditor 已验证的精确文件/状态映射完成刷新。
首次失败记录保留在 stage1.json，第二次刷新 PASS 见最终验证中的 stage1_recovery。

## 当前正式验收

正式测量在 CPU 0 串行执行，每配置固定 20 次重复，编码与解码的选定测量方向各至少 1 秒。
审计分别检查两个方向，不能仅凭总时长或 min_duration_satisfied 标签判定通过。
全部重复索引保留；资源压力记录不替换，排除出统计，每配置至少 10 次有效重复。
五层审计核对当前身份与源码、原始记录、独立 wire oracle、物理账本与计时、CSV/coverage，
并从有效原始重复重新计算统计结果。

| 入口 | 正式记录 | 有效记录 | 资源压力 | 独立审计 |
| --- | ---: | ---: | ---: | --- |
| `fast-differential-u32` | 320 | 310 | 10 | [审计](../build/source-audits/fast-differential-u32-five-layer-audit.json) |
| `maskedvbyte-u32` | 80 | 79 | 1 | [审计](../build/source-audits/maskedvbyte-u32-five-layer-audit.json) |
| `delta-maskedvbyte-u32` | 320 | 311 | 9 | [审计](../build/source-audits/delta-maskedvbyte-u32-five-layer-audit.json) |
| `simdcomp-u32` | 202 | 165 | 35 | [审计](../build/source-audits/simdcomp_u32_five_layer_audit.json) |
| `delta-simdcomp-u32` | 80 | 73 | 7 | [审计](../build/source-audits/delta_simdcomp_u32_five_layer_audit.json) |
| `for-simdcomp-u32` | 80 | 77 | 3 | [审计](../build/source-audits/for_simdcomp_u32_five_layer_audit.json) |
| `simple9-u28` | 80 | 73 | 7 | [审计](../build/source-audits/fastpfor_simple_formal_current_audit.json) |
| `simple9hacked-u28` | 80 | 74 | 6 | [审计](../build/source-audits/fastpfor_simple_formal_current_audit.json) |
| `simple16-u28` | 80 | 77 | 3 | [审计](../build/source-audits/fastpfor_simple_formal_current_audit.json) |
| `streamvbyte-u32` | 40 | 38 | 2 | [审计](../build/source-audits/streamvbyte-u32-five-layer-audit.json) |
| `delta-zigzag-streamvbyte64` | 240 | 231 | 9 | [审计](../build/source-audits/streamvbyte-pipeline-five-layer-audit.json) |
| `streamvbyte-modern-u32` | 40 | 39 | 1 | [审计](../build/source-audits/streamvbyte-modern-u32-five-layer-audit.json) |
| `delta-zigzag-streamvbyte-modern64` | 240 | 228 | 12 | [审计](../build/source-audits/streamvbyte-modern-pipeline-five-layer-audit.json) |

合计 1882 条正式批次记录，包含 1880 次测量尝试和 2 条预期拒绝诊断。
其中 1775 次有效。SIMDComp 原始入口的 AVX2 + LENGTH 原版不支持，
对应诊断未执行编解码，不纳入性能重复或统计。
具体 run ID、原始记录/报告 SHA、最小方向时长、当前算法身份见
[最终验证](../build/rejected-native-requalification-20261007-1/final-verification.json)。

Simple 家族首个完整固定批次保留了 240 条记录。Simple16 的至少一个配置
有效重复少于 10 次，首批审计失败，未纳入当前验收统计。随后用新 run ID 重跑整个 Simple
家族的固定批次，仍每配置 20 次、各方向至少 1 秒，再由同一个独立 auditor 验证。没有
补写、覆盖或替换首批重复索引。详见[保留的失败批次](../build/rejected-native-requalification-20261007-1/simple-first-formal-batch/observations.json)。


## 验证与范围

8 个代表构建覆盖本轮的共享库，6 个 native 验证驱动通过。
4 组直接 SDK 资格分别通过 103、159、888、322 项。
框架/接入测试及源码、原生、SDK、运行审计的回归测试合计 683 项通过，失败、错误、跳过均为 0。
审计回归测试读取当前 PASS 报告指定的 run ID，不再依赖写死的旧日期。
测试与辅助审计在 CPU 2 执行，正式批次期间 src 的冻结哈希未变化。

uint32 primitives、modular uint32 pipelines 和 FastDifferential 只签署本轮合成完整 uint32 UTS
及其配置矩阵。Simple9、Simple9hacked、Simple16 只签署合成 uint28 UTS 的 marked/unmarked
范围，包含能力与来源数据域的拒绝验证。两个 checked int64 StreamVByte pipelines 覆盖
ETTH1、Exchange Rate、Weather 的时间戳及 stage/native-timing 开关矩阵。
其他数据集、数据域或未声明原版 API 变体未自动获得资格。

原版 modern StreamVByte signed ZigZag 的已知 UB 保留为原版源实现缺陷观测，不能据此宣称
原版全部变体通过。LeakSanitizer 受沙箱限制，本轮未宣称泄漏检查通过。
DCT、DWT、PCA 按用户决定继续跳过。本轮不提交、不推送。

## 复核入口

- [注册证据刷新报告](../build/source-audits/native-sdk-registry-refresh-20261007-rejected-1/report.json)
- [串行批次与审计结果](../build/rejected-native-requalification-20261007-1/recovered-five-layers.json)
- [最终逐入口验证](../build/rejected-native-requalification-20261007-1/final-verification.json)
- [更新后的清单](../Compression_Rewrite_Algorithm_List_v1.0.xlsx)

未来修改共享执行依赖后，应先运行对应构建、native 与直接 SDK 资格，使用新的刷新 suffix，
再创建全新的正式 run set 并独立审计。保留旧记录；不要重签旧 SDK 快照或覆盖旧正式批次。
