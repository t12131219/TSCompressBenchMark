# Stream VByte 旧 Benchmark 来源自省（2026-10-07，已刷新）

对照计划 7.2、7.6、7.7、8.3、8.5、11.5、13.3、13.8、16、20.3 和 ODT，
旧来源固定为 `dblalock/lzbench@580c4f085381f31b1ad669525ed04e63cbc385f3`，
Apache-2.0。scalar encode、SSE4.1 decode、声明 scalar tail、禁止 fallback。
工作表来源为现代 fast-pack/streamvbyte，本地旧源码不能冒充现代版本。现代版本
现在已单独接入，完整当前四入口证据见 [现代来源自省](streamvbyte_modern_self_check.md)。

本轮发现旧 `STREAMVBYTE_PIPELINE_CTYPES_V1` 被遗漏在 factory 外层条件，造成 P2
没有执行源码/绑定/命令/binary drift 门禁。此缺口已修复并对四个新旧入口回归；
实际补丁后的 compiled source closure 也参与执行 hash 与运行前检查。历史批次
完整保留，但不再用于当前绑定签署；本轮已重新构建、资格、正式运行和独立审计。

| 对象 | 当前验收范围与结果 |
| --- | --- |
| `streamvbyte-u32` | P0/VALUE/V0、synthetic uint32 UTS；2 qualifier PASS，formal 40 次中 39 有效、1 系统压力，2 summary |
| `delta-zigzag-streamvbyte64` | 显式 checked int64 Delta/ZigZag/limb32 P2/TIMESTAMP/T1；ETTh1/exchange_rate/weather，96 开关 qualifier PASS；formal 240 次中 238 有效、2 系统压力，12 summary |
| 原生安全 | 六 ABI 二进制，u32 各99/int64各100 cases；三档 stage 各129；原 API 278 向量逐字节及双向解码 |
| 来源门禁 | 原始 source、binding、binary、compile command、补丁源码漂移拒绝；完整记录与冻结快照独立审计 |
| 正确性 | 无界 Python 整数 Delta/ZigZag oracle、limb oracle、scalar decoder、每阶段 inverse；fresh decode、input immutable、canary、exact ledger |
| 计时与报告 | native/stage 计时各开/关；all inner iteration 累计；PIPELINE ≥1 s/轮，warmup ≥3次且0.5s，CPU0/单线程；summary/coverage/eligibility/ranking/Pareto及报告表 hash、独立均值/中位数/标准差重算 |

A/B/C/D 显式执行，A/B/C 关闭分别为 original bits/byte-preserving limbs/raw limbs。
D 自包含 wrapper 必需，false 产生保留的 SCHEMA_ERROR；未注册 stage spec 仍拒绝。
Delta subtraction/recovery checked int64，overflow 原子 UNSUPPORTED，不缩单位、
不排序、不去重、不隐式 raw fallback。A/B/C/D FinalBits 排他闭合，中间数组不重复
收费；主语义分母为原始8*N，native backend 分母为实际 C word bytes。

当前 qualifier：`streamvbyte-u32-qualification-20261007-7`、
`delta-zigzag-streamvbyte64-switch-qualification-20261007-4`。
当前 formal：`streamvbyte-u32-formal-20261007-8`、
`delta-zigzag-streamvbyte64-formal-20261007-4`。每配置预定20轮，压力记录未删除或选择性
补齐，summary 每组19–20有效轮。历史系统压力批次仍保留；SYSTEM_VMSTAT swap
不能归因 codec。生成证据在 ignored build/runs，源码/合同/锁/测试/复现配置保留。

当前两份独立五层 audit 均 PASS；最终四入口与相关框架组合222 tests PASS。
平台范围为 Linux x86_64；ASan/UBSan leak detection 关闭，不宣称 leak-clean
或 ARM/Windows/macOS。未注册的其他 upstream API variants 与其他 native candidates
仍在全量追踪中；不能由这两个旧源码入口的范围资格宣布全量目标完成。
