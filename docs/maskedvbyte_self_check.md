# MaskedVByte 原生接口、SDK 和五层资格阶段自省（2026-10-07）

本阶段按工程计划 7.2、8.3、11.5、13.3、20.3 执行，并核对 ODT 中
P0/P2 分层、int64 timestamp、padding、safe overread、actual ISA 和 FinalBits
约束。覆盖全量审计的 Masked VByte 与 Delta + Masked VByte 两条原始条目，
没有通过共享仓库或名称匹配自动给它们签署五层资格。

- [x] 先调查本地 FastPFOR 的 MaskedVByte 包装与 lzbench 公共 API，确认
  FastPFOR 为 plain-only、32-bit 0xFF padding、不同 decoder 入口。
- [x] 原仓库 pin/clean/submodule/license 与 11 个原样文件均冻结，原源码未改。
- [x] 明确 uint32 LEB128、模 2^32 delta、任意 prev、count/byte-length 两类
  decoder、select/search 的前提和 sentinel，不暗中截断 int64 或 float。
- [x] 原 full-range uint32 scalar tail 的 signed-shift UBSan 失败保留；显式
  patch 只修复 unsigned shifts，encoder 不改。patch 在 build 目录应用。
- [x] 原 release/debug 和补丁三档源码 API 检查通过；原 sanitizer 的
  decode guard 失败仍在 18 项完整原/补丁矩阵中，未混成全原源码 PASS。
- [x] 每个补丁 decode executable 覆盖 1872 场景；查询 executable 覆盖
  936 场景和 175344 次调用。完整 byte-level scalar oracle、四 seeds、
  empty/tails、unsigned 边界、重复/OOO/模溢出、protected pages、只读输入。
- [x] compiler -MD 冻结真实 system/source/test dependencies；独立审计重查
  二进制、对象、closure、原失败与 patch 可复现性。七种独立副本漂移均被拒绝。
- [x] 有界 C ABI：验证畸形输入、capacity/alias/canary、失败原子性、count
  预算、staging、Finalize/reset、独立解码、ISA gate 与原生 API 计时。
- [x] 三档共享库及同对象故障可执行文件各 9360 场景；六原 API 全部验证。
  实际分配请求/free、错误 source length、timer 失败/倒退/累计溢出有独立证据。
- [x] 直接 Python SDK：159 项，明确 plain/delta 两身份、完整 metadata/FinalBits、
  decoder/timer 不改变 bytes、fresh seed/decoder、布局拷贝与闭合 lifecycle。
- [x] 实际 compiler 依赖与 76 个 imported Python 文件冻结；独立审计拒绝
  源码、patch、生成源码、encoder、shim、binary、test、command、coverage 漂移。
- [x] source/binding/build 的中央 admission、registry、全部默认 ConfigID。
  `maskedvbyte-u32` 为 P0，`delta-maskedvbyte-u32` 为原始 uint32 模运算 P2。
- [x] P2 显式 A/B/D 阶段，独立 scalar LEB128 与模 D1 inverse 预检；
  原 API 融合 A/B，单阶段计时为 null 并说明原因。
- [x] 集成 34 项通过。实际 supported 4/16 个配置和 unsupported 8/32
  个任务均经五层产生完整文件、报告和 Coverage；资格运行不进入性能榜。
- [x] 当前源码、ABI、SDK、独立审计漂移及完整集成组合 81 项通过，
  包括有效 checksum 下的错误 residual/seed/descriptor 拒绝。
- [x] 五层实际任务、每配置 20 次事先固定正式重复、Unsupported 终态、
  raw→report 独立审计均完成并通过，资格只限原 uint32 API 范围。
- [ ] checked int64 Delta/zigzag pipeline 需要独立 P2 身份与完整五层资格。

源码阶段报告：`build/source-audits/maskedvbyte-source-both-tests.json`；当前
独立审计：`build/source-audits/maskedvbyte-source-current-audit.json`。
两条逻辑条目的 `full_logical_entry_qualified=false`。当前资格限
Linux x86_64/SSE4.1，leak
detection 关闭；缺少 sse_to_neon.h 的原 checkout 不能宣称 AArch64 支持。

本轮证据：`build/source-audits/maskedvbyte-native-tests.json`（三档 shared 与
instrumented 完整输出）、`maskedvbyte-native-current-audit.json`（当前输入/
patch/实际 closure 重查）、`maskedvbyte-sdk-tests.json`（159 项及真实 import
closure）与 `maskedvbyte-sdk-current-audit.json`（上述后三项位于相同目录）。
计划 20.3 的五层门禁已在下述两个 uint32 身份范围闭合，完整逻辑条目仍 pending。

正式计时独立检查发现原框架用 encode+decode 总时长结束循环，故此前
`formal-20261007-1` 两批不作为当前资格。修正已经通过 measurement/statistics
反例与集成测试，当前两身份重新执行固定的 `formal-20261007-2`。
详情见 `docs/minimum_duration_direction_self_check.md`；独立审计入口为
`tools/audit_maskedvbyte_run.py`。已保存的资格/Unsupported run ID 均为
`<key>-qualification-20261007-2`、`<key>-unsupported-qualification-20261007-2`。

当前完整证据：

| 身份 | 正式配置 / 固定尝试 | Eligible / 压力 | 资格任务 / Unsupported |
| --- | --- | --- | --- |
| `maskedvbyte-u32` | 4 / 80 | 80 / 0 | 4 / 8 |
| `delta-maskedvbyte-u32` | 16 / 320 | 315 / 5 | 16 / 32 |

每个配置事先固定 20 次重复。5 条压力观测保存原 RunID、码流和资源诊断，
独立统计器排除，未补测替换。全部配置仍满足至少 10 eligible、预热及各方向
最短时长；独立审计核对原始 CSV/JSONL、实际 payload、四 seeds、相反 decoder、
descriptor、FinalBits、Coverage、summary 统计和报告哈希。
最终审计：`build/source-audits/maskedvbyte-u32-five-layer-audit.json` 和
`build/source-audits/delta-maskedvbyte-u32-five-layer-audit.json`，均 PASS。
清单分别记录 `P0_PLAIN_MASKEDVBYTE_UINT32_SCOPE_QUALIFIED_OTHER_DOMAINS_PENDING`
与 `P2_ORIGINAL_MODULAR32_MASKEDVBYTE_SCOPE_QUALIFIED_INT64_TIMESTAMP_PENDING`。
原 uint32 模 D1 未改成 checked int64，不通过 dtype 截断进入时间戳主榜。
