# 现代来源接入自省（2026-10-07）

对照计划 7.2、7.6、7.7、8.3、8.5、9.2、16、20.3 和 ODT，现代来源单独固定为
`fast-pack/streamvbyte@7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce`。本地 Benchmark
旧版本继续保留独立身份。现代 P0 为 uint32 primitive，P2 为 checked int64
Delta/ZigZag/limb32 组合；未把上游 uint32 modular delta 当作 int64 时间戳编码。

现代 SourceArtifactID：
`v2:source-artifact:sha256:84d899b8be4348656bcca306d2b543d8acde7e1865f762698ee8ed3dbc33859b`。
主 Apache-2.0 和 ISA header BSD-3-Clause notices 完整保留。

| 门禁 | 本轮证据 | 状态 |
| --- | --- | --- |
| 来源准入 | 本地 Benchmark 对照、clean commit/submodule 复查、逐文件内容 hash、独立安全补丁、原 vendor 不改 | 已检查 |
| 原始上游自测 | release/debug 通过；sanitizer 捕获 ZigZag delta signed overflow，原始失败报告保留 | 失败如实保留 |
| 补丁后上游自测 | 全部 7 个 translation units、原 unit.c 不改，release/debug/ASan+UBSan 均通过 | 已检查 |
| 原生内存与 ABI | u32 各档 99 cases，int64 各档 100 cases，阶段各档 129 cases；guard pages、alignment、容量、原子溢出拒绝 | 已检查，leak detection 关闭 |
| 原 API 一致性 | 834 组向量，包含全部 controls 和 SIMD 长度；original/patched 双向 decode；剥离 shim count 后逐字节比较 | 已检查 |
| 执行来源门禁 | 修复旧 P2 漏门禁；四入口原始源码、绑定、compile command、binary、compiled source closure 漂移回归 | 已检查 |
| Python 正确性 | 最终组合 222 项通过，含四入口、五层联通、Delta Varint/统计/报告及全量追踪 | 已检查 |
| 五层资格 | modern P0 2 PASS、modern P2 96 PASS；旧 P0 2 PASS、旧 P2 96 PASS；辅助计时独立开关，A/B/C 开关和 D 拒绝 | 已检查 |
| 正式重复 | 现代 P2 240 次/239 有效/1 压力，12 组；现代 P0 40 次全部有效，2 组；旧 P2 240 次/238 有效/2 压力；旧 P0 40 次/39 有效/1 压力，2 组 | 已检查 |
| 五层独立审计 | 四入口均通过当前来源、三档构建、冻结快照、实际码流/解码/账本、计时累计和独立统计重算；所有报告表 hash 复查 | 已检查 |

生成证据位于 ignored `build/`、`runs/`。原失败报告
`build/source-audits/streamvbyte-modern-native-tests-before-upstream-safety-patch.json`
完整保存；最终原生报告为 `streamvbyte-modern-native-tests.json`。现代 qualifier
在 `streamvbyte-modern-u32-qualification-20261007-1` 和
`delta-zigzag-streamvbyte-modern64-switch-qualification-20261007-1`；旧刷新 qualifier
在 `streamvbyte-u32-qualification-20261007-7` 和
`delta-zigzag-streamvbyte64-switch-qualification-20261007-4`。

实际来源一致性仅签署现代 1234 的所测 P0/P2 范围。清单逻辑条目及全量 221 条范围
保持不变，其他 upstream API variants、后续 MaskedVByte/FastDifferentialCoding 和
其他原生候选仍需逐项审查。本页签署这两个现代入口及两个旧入口的所测范围资格，不能据此签署全量目标完成。


当前正式证据（预先固定 20 轮，没有删除压力记录或选择性补齐）：

| codec key | formal run | raw JSONL SHA-256 |
| --- | --- | --- |
| `delta-zigzag-streamvbyte-modern64` | `delta-zigzag-streamvbyte-modern64-formal-20261007-1` | `a0ccc1da84b82fa2d5415b232581a219d6107e657089924596e30ccab40bc76f` |
| `streamvbyte-modern-u32` | `streamvbyte-modern-u32-formal-20261007-1` | `c80e6cb5f577ddaa4d966c4950e88f29ce408d7243566c667dd81621384d7178` |
| `delta-zigzag-streamvbyte64` | `delta-zigzag-streamvbyte64-formal-20261007-4` | `4e5248199200c309d0fefd75ace11b736dacb1c334c58bec327d038630006543` |
| `streamvbyte-u32` | `streamvbyte-u32-formal-20261007-8` | `631e2217fab58a062d5f74b2e5a554186f0a64a7c450fd65cd432f302d6026ea` |

两套 P2 都在 ETTh1、exchange_rate、weather 上生成 12 组 summary（每组 19–20
有效轮），各有 96 项 qualifier 全通过；两套 P0 均为 synthetic uint32 UTS，各有
2 组 summary 与 2 项 qualifier 全通过。主计时每轮 ≥1 s、warmup ≥3 次且 ≥0.5 s，
CPU 0、单线程、对象独立。四个 formal 批次串行运行；压力来源为 SYSTEM_VMSTAT，
不能归因于算法。完整 raw、coverage 和失败批次均保留。

当前独立审计产物为 `build/source-audits/streamvbyte-modern-u32-five-layer-audit.json`、
`streamvbyte-modern-pipeline-five-layer-audit.json`、`streamvbyte-u32-five-layer-audit.json`、
`streamvbyte-pipeline-five-layer-audit.json`。审计除核对签名/字节外，从保留 raw 独立
重算每配置的均值、中位数和标准差，确认只使用符合门禁的重复；核验 report source
hash 和所有派生表 hash。最终组合日志为 `build/source-audits/streamvbyte-modern-final-pytest.log`；
Ruff 与 git diff whitespace 检查通过；没有提交或推送。

FastDifferentialCoding 已完成另一个来源准入及原四 API 的三档 upstream/guard/oracle
测试（每档 520 cases）；其 `adapters/fast_differential/SOURCE_ADMISSION.md` 明确待实现
有界 ABI 与五层接入。全量追踪表保留原始 221 条，其中 115 个 native core candidates，
现代1234以外的 API variants 和其他候选仍逐项进行，完整逻辑条目未自动标成完成。
