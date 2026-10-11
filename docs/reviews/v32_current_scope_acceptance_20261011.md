# V3.2 当前压缩器范围验收记录

本记录依据《TimeSeries_Compression_Benchmark_V3_工程实施总计划.md》、
`independent_benchmark_review_20261010.md` 与
`algorithm_capability_support_matrix_20261010.md`。三份规范基线保持只读。
用户范围为现有压缩器适用的 V3.2 工程义务；不新增算法，不恢复退出入口。

**最终状态：V3.2 现有压缩器当前 CPU 范围已完成并签发。16 条 lane 均完成报告、no-op resume 与两项辅助审计；completion 为 CURRENT_CPU_SCOPE_COMPLETE，逐条验收为 CURRENT_EXISTING_CPU_SCOPE_ACCEPTED_WITH_LIMITS。**
本页数量、工件 SHA、RunSet 与验收 ID 均读取自最终证据。早期运行、旧闭包或单元测试
不替代当前正式观测；有限输入、source parity UNKNOWN、统计不足与可选/暂缓处置保持。

## 发布范围与证据层次

完整范围记录使用三个独立分母：现有活动入口及其声明任务、事前承诺的共同实验组、
原规范条款。入口资格证明其有限声明输入能完成任务；正式组证明其冻结共同语料、
成员、参数与测量协议已完成；SOURCE_PARITY 继续是独立证据轴。

现有活动清单为 33 入口、41 个声明 Track/fixture/config 资格案例。
这不是所有合法 dtype/值域/长度/参数的数学全域证明。当前候选台账完整保存
166 条候选记录与旧 163 命名空间的映射；候选登记不冒称已接入，不增加当前算法。

| 范围 | 独立验收条件 | 当前最终签发状态 |
|---|---|---|
| 当前入口与角色 | 当前 source/build/registry 闭包、原任务恢复、正反例、成本及安全证据 | 33 入口 / 41 案例 SCOPED_PASS；32 完整 codec 有共同正式覆盖，P0 独立资格 |
| 普通完整对象组 | 固定成员/语料/配置、两个真实来源、每合法核心单元当前 FORMAL、真实配对分析 | 适用 lane CORE_COMPLETE，当前闭包签发 |
| 原生 API 组件组 | 相同实际输入 schema/字节、独立 CORE 边界、明确组件空间与原生输入分母 | api CORE_COMPLETE，组件边界单列 |
| 无界质量网格 | 所有承诺合法点、原域 RMSE/MaxAE、完整成本与时间、无固定误差保证冒称 | quality CORE_COMPLETE，全部声明配置保持 |
| 冷进程 | 单独 spawn 至输出物化、完整恢复成本、缓存政策与当前时钟/资源门禁 | cold CORE_COMPLETE，OS cache uncontrolled |
| 流式与查询 | 冻结工作负载、真实公共接口、独立会话、方向时钟/粒度/扰动门禁与完整依赖 | 3 个 lane PROFILE_COMPLETE；query 仍为 RESEARCH |
| P2 T/V/validity | 实际完整对象、schema/顺序/单位/null、全部 child/block/tail、独立恢复与成本 | pipeline COMPLETE，32 条实际 PASS |
| async/ragged 集合 | 每通道独立 T/V/mask、原顺序/RawBits、完整集合成本、清洁公共解码器资格 | 12 单元 SCOPED_PASS；19 负例预期 REJECT |
| 全量回归与 SDK | 当前全部测试定义/fixture 与 pytest 配置清单、未过滤日志、独立 SDK 审计 | 基线 2362 / SDK 504 PASS；当前引用重核通过 |
| 逐条要求 | 原 911 行映射和各条所需独立 facet proof 全部可追溯 | 已签发；28 类独立 proof，逐条处置保留 |

本次承诺共 12 个普通实验 lane、3 个 workload lane 和 1 个完整 P2 lane。
在 byte/f64/f32/i16/fixed-error/quality/model/cold/API/T 范围之外，另冻结
FSE/Huff0 的 entropy 组与两个 Sprintz uint8 入口的 u8 组；这些均为现有算法。
所有现有 P1 完整 codec 需在适用原始任务中拥有共同正式证据，不以 child 或宽度
变体角色替代完整方案覆盖。P0 SIMDcomp 保持 primitive/SDK 与入口资格，
按 §7.8 的单方法 primitive 研究边界不冒称双方法完整整数方案比较。
参数、宽度和共享实现不增加同任务的方法数。最终冻结组清单与活动角色台账为权威，
当前各 lane 的报告完成状态与最终统一签发分开记录。

当前证据根为 `build/v32-evidence-20261010/current-r2`。
最终声明为 `declaration-release-r4.json`。五个有效 lane byte/f64/i16/abs/f32
保留在 `formal-r2/`，quality 在 `formal-r2/continuation-r2/`，model/cold/api/entropy/u8
在 `formal-r2/continuation-r3/`，stream/query-warm/query-fresh/pipeline/timestamp
在 `formal-r2/continuation-r4/`。各批 `release_plan.json`、冻结 bundle、协议、
事前决策与原始记录保留各自身份。初轮及先前 continuation 的失败/部分结果独立保留。

下面状态只读自各 lane 已落盘的报告；16 条完成 lane 均已有同状态的
`resume_verification.json`、`AUXILIARY_COST_AUDIT` 的 `buffer_cost_audit.json`
和 `UNCOMPRESSED_REFERENCE_AUDIT` 的 `uncompressed_reference.json`。
普通报告为 `analysis.json`，workload 为 `workload_analysis.json`，P2 为 `report.json`。
最终签发已统一重核；文件存在、已保存的核心流或局部恢复记录本身不替代资格 PASS。

| Lane | 事前任务/边界 | 当前报告状态 | 相对 evidence root 的目录 |
|---|---|---|---|
| byte | 原 typed VALUE，完整无损对象、稳态 PIPELINE | CORE_COMPLETE；已纳入签发 | `formal-r2/byte` |
| f64 | 冻结有限 f64 原值 UTS/MTS，bit-exact 完整对象 | CORE_COMPLETE；已纳入签发 | `formal-r2/f64` |
| f32 | 明确派生 f32 ground truth，bit-exact 完整对象 | CORE_COMPLETE；已纳入签发 | `formal-r2/f32` |
| i16 | 真实精确整数 i16，原宽度/顺序完整恢复 | CORE_COMPLETE；已纳入签发 | `formal-r2/i16` |
| abs | 原域固定总 MaxAE、原坐标近似恢复、完整对象 | CORE_COMPLETE；已纳入签发 | `formal-r2/abs` |
| quality | 原 f64、完整预声明质量网格、经验 RMSE/MaxAE | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r2/quality` |
| model | 真实源派生 uint8 base4、模型全额成本、独立对象 | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r3/model` |
| cold | 独立 spawn 至恢复输出物化，OS cache uncontrolled | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r3/cold` |
| api | 相同实际输入 bytes/schema，NATIVE_COMPONENT/CORE | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r3/api` |
| timestamp | 原真实 T、单位/顺序/原位模式、完整 Track 对象 | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r4/timestamp` |
| entropy | FSE/Huff0 与 byte 参考，完整原 VALUE 对象 | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r3/entropy` |
| u8 | 现有 Sprintz uint8 与 byte 参考，原 f64 字节派生 uint8 任务 | CORE_COMPLETE；已纳入签发 | `formal-r2/continuation-r3/u8` |
| stream | 已知长度 fixed-row-block、finalized 全输出、独立恢复 | PROFILE_COMPLETE；已纳入签发 | `formal-r2/continuation-r4/stream` |
| query-warm | 冻结 point/range/column、reused session、owned 输出 | PROFILE_COMPLETE；已纳入签发 | `formal-r2/continuation-r4/query-warm` |
| query-fresh | 同请求、fresh session per query，计 session 成本 | PROFILE_COMPLETE；已纳入签发 | `formal-r2/continuation-r4/query-fresh` |
| pipeline | 完整 typed T/V/validity、P2 组合、原 schema 与独立恢复 | COMPLETE；已纳入签发 | `formal-r2/continuation-r4/pipeline` |

16 条 lane 共保留 2400 条计划记录。timestamp 的固定分母为 40 个单元 × 8 次外层
重复，共 320 条：32 个合法核心单元 × 8 = 256 个实际 PASS/formal eligible；
8 个预期缺 T 单元 × 8 = 64 个拒绝/停止槽位，其中 8 次实际 UNSUPPORTED，
其后 56 条按事前停止政策为 STOPPED、record=null。它们没有被补测、删除或伪造为 PASS。
成本辅助审计共覆盖 312 个 cell/artifact profile 与 2336 个实际试验工件；
完整未压缩参考为 65 个对象。辅助观察不加入 FORMAL 性能分母。

集合资格另为 6 个 async/ragged 对象 × 两个现有 byte 方法，共 12 单元，覆盖
bitwise/semantic/null-mask 缺省三种声明；它不增加上述 lane 或 FORMAL Trial 数。

## Development 协议改版记录

首轮 `current-r2/byte/pilot.json` 的 Snappy decode collector 扰动为
`0.152526`，超过已冻结 `0.15` 门限，首轮停止且没有产生 FORMAL。
失败 pilot 和原 SHA 保留，不覆盖或改为 PASS。

父/子进程共享声明 CPU 时，1ms collector 唤醒可能影响较短调用。
新 bundle 的基础 comparison protocol 只将采样间隔从 1ms 调整为 5ms，形成新 Protocol/Contract/Group
身份与 `formal-r2` RunSet；算法参数、语料、外层重复和扰动门限不变。
该工程判断来自 development 观测，未使用正式测试性能选择协议。
新版本仍必须重新 qualification、pilot 与正式运行；5ms 不自动证明更低扰动。
独立 WorkloadProtocol 当时仍为 1ms，其实际 monitor 后来由 r4 单独修订；
不能据基础 comparison protocol 的 5ms 声称实际 workload monitor 已改变。
P2 保持其独立协议。采样线程高水位是下界，可能漏掉短暂线程。

事前采样改版记录为 `formal-r2/protocol_adaptation.json`，其当时角色映射
`stage_mapping-sampling5ms.json` 与文档 v6 保留。

时间戳旧资格中的 LZSS TIMEOUT 经串行 development 诊断确认来自累计原生计算：
65537 个 T 的诊断对象约 7.98s，131071 个 T 约 17.85s；旧完整边界集合为
49 个案例、约 8.9MiB。粗略总时长估计约 143s，用于预算规划，不是已观测到的完整
资格总时长或正式性能结果。旧失败与诊断工件均保留。

timestamp v4 仅把同组全部成员共享的 `max_trial_wall_ns` 从 30s 增为 240s，
适用于 qualification/pilot/formal。全部 49 个边界案例、block 和算法参数、原语料、
8 个外层重复、correctness/成本/资源/collector 门禁 `0.15`、总正式预算 3600s 不变。
该新版本生成独立 Protocol/Contract/Group/RunSet，未依据正式测试性能作调整。
诊断时间不拼接为 FORMAL；实际完整边界资格仍需在新身份下完成。
记录为 `formal-r2/continuation/timestamp_budget_adaptation.json`，诊断工件在
`formal-r2/continuation/timestamp_diagnostic/`。

v4 qualification/pilot 通过之后，源码核对确认每个 FORMAL `execute_task` 都完整重跑
49 个 preflight 案例。32 个 native LZSS 槽位乘以 development 粗估 143s，
已超过 3600s 总预算，尚未包括同组其他槽位。正式 executor 累计时长暴露了预算问题；
适配依据 development 诊断与源码调度推算，未使用选取的 encode/decode 数据作性能选择。

旧 v4 批次受控中止（工具 exit 143），保留 17 条 trial：9 条 formal eligible、
8 条预期缺 T 拒绝，以及 1 个未知终态 STARTED。host lease 已确认释放。
`formal-r2/continuation/timestamp/controlled_stop_record.json` 固定这些原始工件 SHA
和 `old_run_must_not_resume=true`；未知 attempt 不重测、不重新标终态，部分结果
不并入最终当前核心完成分母。

timestamp v5 仅将总 `max_total_wall_ns` 从 3600s 增为 10800s（3 小时），
单任务 240s、全部 49 项边界、block/算法参数、语料、8 次正式重复和其他门禁保持。
它拥有新 Protocol/Contract/Group/RunSet，实际 qualification、pilot 和 FORMAL
已在 r4 新身份完整重跑并取得当前资格/pilot 与 FORMAL 完成。记录为
`formal-r2/continuation-r2/timestamp_total_budget_adaptation.json`。

模型 v7 的旧 `continuation-r2/model` qualification 为 PASS，但 development pilot
为 INCONCLUSIVE，未生成 FORMAL 文件。DeepZip/DZip 的 pilot 通过；LZ4/Zstd 快参考
不能在 `max_inner_iterations=8` 内累计每方向要求的 50ms，触发最低信号时长门禁。
模型 v8 仅把所有模型和参考共用的内层迭代 ceiling 从 8 提高为 1,000,000。
3 次真实 pilot、4 次外层重复、encode/decode 最低 50,000,000ns、collector 门限
0.15、线程预算 3、算法参数、4 个核心对象、16 个全部单元/8 个核心单元及语料保持。
单任务 900s、总预算 7200s 不变，新 Protocol/Contract/Group 与 RunSet 独立冻结。
记录为 `formal-r2/continuation-r3/model_inner_budget_adaptation.json`。
改版只使用 development 失败依据，不使用正式测试选择，不修改源码、测试、工具或 registry。
新身份下已实际完成 qualification、pilot、FORMAL、resume 和两项辅助审计。

旧 `continuation-r3/stream` qualification 为 PASS，development pilot 为 INCONCLUSIVE；
唯一超门限为 XZ decode collector 扰动 `0.27376386156568376 > 0.20`。
50 条 raw observations 全 PASS，恢复、资源、环境与时钟门禁通过，旧批次没有 FORMAL。
只读 development 诊断发现 1ms `/proc` 采样与 5 次 enabled decode 中 3 次计时重叠，
各次读取约 43–47µs。这支持潜在扰动来源的相关性判断，没有证明因果。

r4 为 stream/query-warm/query-fresh 的三个独立 WorkloadProtocol 统一事前修订实际
monitor 间隔 1ms → 5ms；collector 门限 0.20、5 对 pilot、8 个独立外层会话、
1000 个 query 请求、全部成员、参数、语料与组分母保持。Group bundle 未变；
新的 WorkloadProtocol/decision/workload/schedule/run 身份按实际执行重新冻结。
记录为 `formal-r2/continuation-r4/workload_collector_monitor_adaptation.json`，
未修改源码、测试、工具或 registry，没有使用正式测试观测作协议选择。
三个 workload lane 与同一 r4 队列的 P2 已实际完成报告、resume 和两项辅助审计；
P2 没有套用这次 WorkloadProtocol 修订。

最终角色映射为 `stage_mapping-release-r4.json` 与 `.md`：33 活动入口中
32 项进入选定组，14 个 distinct bundle 记录，P0 SIMDcomp 保留专属资格。
Ledger ID 为
`v2:active-stage-role-ledger-v32:sha256:240eb9d39eaecb7ef483fa9c76946466f418068c78a7a469f4bcbeabe95b9834`。
该台账是事前角色/身份记录，未独立授予执行或正式比较资格。
`release_r4_preparation_validation.json` 记录 r4 结构及引用验证通过；该准备记录本身
未执行 codec、pytest 或性能，也不授予最终验收。
以上采样/预算适配未修改 Benchmark 源码、测试、registry 与三个正式队列驱动；
此前基线资格与回归独立保留。

`documentation_generator_revision.json` 另记录了一次文档生成器修正：
`tools/build_v32_active_role_ledger.py` 中两个 LZSS 入口的 family relationship policy
和 markdown 尾段，改为遵循各任务 GroupSpec，清除旧的全局“尚未冻结”说明。
14 个组 ID、33 活动入口、32 入组入口、成员和方法分母全部保持。
仅台账解释与 ledger ID 更新，早期 JSON/md 不覆盖。

该生成器不在 SDK 实际导入闭包内。504 项 SDK/74 个实际导入项目文件、2362 项
全量回归的当前引用核验 PASS，正式队列 control-plane、registry input 与三个驱动的
SHA 未变。本次核验没有重新运行 pytest、codec 或性能；不能将文档修正误报为
全工具未改变，也不能把引用核验冒称新一轮测试。

## 已实现的可审计合同

普通、workload、P2 执行在资格、pilot 和正式测量之前冻结
`experiment_decision.json`：用户决策、具体研究问题、目标总体、主要估计量、
选择规则、fidelity/恢复、成本/资源/冷热/工作负载边界，以及来源与结论范围。
`decision_id` 和文档同时进入计划及报告；计划、原始 sidecar 和重新派生输入必须一致。
恢复时缺少 sidecar、来源或配置漂移、试图在已有测量之后补填均会拒绝。
这项附加版本合同兼容现有 bundle v1，不重解释旧 bundle 或历史数据。

完整未压缩参考保留原完整 canonical 对象或 NPZ 与付费 context，另存与当前 Track
相同边界的未压缩对象参考。其 `FinalBits` 包含实际文件与必需描述；`RawBits`
只保留原任务逻辑分母。TIME 参考仅在匹配边界计 T，完整 dataset 参考另列；
API 组件的 native input size 与完整对象空间不混比。
参考标记 `SIZE_BASELINE`、`statistical_method_count=0`，性能为 null 与原因，
不注册新 codec，不加入核心方法等价类，不拼接为正式性能 Trial。

每种正式执行保留事前 STARTED 记录、冻结计划、任务/试验身份与预算。
未知终态禁止自动重测或原始记录覆写。P2 使用 hash-chain
`pipeline_events.jsonl`，终态绑定 STARTED 与已落盘 trial 的 SHA；孤儿工件或未提交
attempt 触发独立中断记录与阻断。报告保留实际成本已知或未知的状态，不能用零替代。

查询报告完整 `FinalBits` 及 logical read/decode amplification、原输出单位与请求计数；
无法将 opaque frame 账本分配为 index/checkpoint 时使用 null＋reason。
时钟与 harness/collector 门禁来自真实 worker 的预热后观测，分别检查 encode、decode
和每项 query latency，不用整轮时间掩盖不足的方向信号。

## 保留的结论边界

1. 两个独立真实来源满足项目最小交付门槛，不能证明所有时序数据的代表性。
   列、窗口、重采样、cast、seed 或重新序列化不增加独立来源数。
2. 普通完整对象使用 `SCHEMA_BOUND_OBJECT` 部署：schema/context 显式可取得且全额计费。
   它不证明单个流自描述。f32 是明确派生后的 ground truth，不冒称恢复原 f64。
3. 学习模型任务为 uint8 base4 symbol streams；原浮点无损并未由该任务证明。
   模型训练与测试重叠继续 UNKNOWN；当前帧中已实际包含的 opaque 模型依赖计费一次。
   u8 组为另一个原 f64 字节派生的 uint8 byte object 任务，不与模型 base4 任务混称，
   不据该组恢复结论宣称原浮点对象恢复或未知源泛化。
4. 流式范围为 known-length、fixed-row-block、Finalize 后完整消费；首 emitted byte
   可以是 header。当前证据不证明 unknown-length、实时背压或严格 bounded-memory 流。
5. 查询比较为相关 NeaTS/LeaTS 实现变体研究，含真实 point/range/column 请求。
   logical bytes 不是硬件内存流量；样本不足的 p99 为 null＋reason。
6. Rate/summary 当前没有活动算法，其专属 validator 与 fixture 只验收框架接口。
   对 future 算法的算法资格和正式比较没有提前签发。
7. SOURCE_PARITY、wire compatibility、原任务 correctness、standalone decoder
   分开保存；Bench/SDK/自回环通过不能晋升 UNKNOWN source 结论。
8. Auxiliary buffer 成本与未压缩对象审计是独立辅助观察，不与正式 Trial 拼接。
   opaque native 缓冲细分不可取得时保留 null＋reason。
9. 统计校准只覆盖有限的 paired lognormal 场景；小样本可出现 undercoverage。
   不能从有限校准声称普遍 95% 覆盖保证，当前区间与统计不足原因均如实报告。
   各报告的 INCONCLUSIVE 和 null 原因保持；实施完成不自动判定算法优胜。
10. Device/P3、高级 collector、process-tree/cgroup/hard-RSS、NUMA memory binding
    按明确适用范围保留可选状态；basic CPU leases、实际线程/affinity 不是可选门禁。
    用户暂缓的是新增算法和长期候选接入，不是现有 framework/stream/query/task 义务。

## 最终工件与签发方式

最终 evidence root 为 `build/v32-evidence-20261010/current-r2`，最终声明为
`declaration-release-r4.json`，分别引用 `formal-r2/` 的五个 lane、
`formal-r2/continuation-r2/quality`、`formal-r2/continuation-r3/` 的五个 lane 与
`formal-r2/continuation-r4/` 的五个 lane；回归入口为 `regression-final/validation.json`，
活动角色映射为 `stage_mapping-release-r4.json` 与 `.md`。
声明 SHA-256 为 `1d578c369ec8a723868050a653948d7e74fdafd038a4df80a1d87d7f801153c2`，
角色映射 JSON SHA-256 为 `a941ce2804da22d704d487c4ed56cd25cfa38b18c3de0c6553f06731f4443b01`。
早期声明、失败及 partial 工件保留原身份。
最终 completion、逐条验收和 28 类 proof 均已实际生成。发布器内部再次执行 completion
audit，验证结果与已保存 completion 完全相等；它重新核验原工件和独立恢复，不重新
测量正式性能，也未重新运行 pytest/SDK 测试。

| 最终工件 | 状态 / 身份 |
|---|---|
| `completion-final.json` | CURRENT_CPU_SCOPE_COMPLETE |
| completion acceptance ID | `v3:v32-current-scope-acceptance:sha256:e81208534b3adfd827e81323088faf9eabc1749857a1839aba40f282172084ec` |
| completion SHA-256 | `27f0ec760111a9238c01f29b862649f60c899db4a3fbee1612a4ea1152e78ae2` |
| `requirement_acceptance-final.json` | CURRENT_EXISTING_CPU_SCOPE_ACCEPTED_WITH_LIMITS |
| requirement acceptance ID | `v3:v32-accepted-requirement-ledger:sha256:08f55e6a2f383ed2e24556fe3cfa56d78fe80a8113b155effbfd8d6545f966bc` |
| requirement ledger SHA-256 | `f7f8b6a59f7a9d1397da06a1c6238cbd96e6d004f02eca0671f012cecbb3b0eb` |
| `requirement_acceptance-final_proofs/` | 28 个 immutable proof；27 个 ACCEPTED_WITH_EXPLICIT_SCOPE，rate/summary 为 FRAMEWORK_INTERFACE_ONLY |
| `regression-final/validation.json` | PASS；完整基线日志为 2362 passed、650 warnings、523.65s |
| `regression-final/full-suite.log` SHA-256 | `eec3e0519ee3eb1a610c3d97a9870e1f384184d9f1dfb8f1b2fd664c786df4ac` |
| `sdk_qualification.json` | 独立 SDK audit PASS；504 项 / 74 个实际导入项目文件，有限 plain uint32 SSE4.1/AVX2 域 |

全部 proof 绑定各自当前身份、任务域、实际引用 SHA 与限制；逐条验收副本保存
各组固定矩阵、analysis/comparison/workload/pipeline 身份及所有工件引用。
以下是本次实际执行的签发命令；现有输出不可覆盖，重签须使用新输出名。

```bash
EVIDENCE_ROOT=build/v32-evidence-20261010/current-r2
python tools/audit_v32_completion.py "$EVIDENCE_ROOT" \
  --declaration "$EVIDENCE_ROOT/declaration-release-r4.json" \
  --output "$EVIDENCE_ROOT/completion-final.json"
python tools/publish_v32_requirement_acceptance.py publish \
  "$EVIDENCE_ROOT/completion-final.json" \
  --output "$EVIDENCE_ROOT/requirement_acceptance-final.json"
```

运行入口见 [README V3.2 执行入口](../../README.md#v32-执行入口)。统一回归、SDK、
正式 lane 和集合资格按独立串行窗口运行；`run_v32_release_queue.py` 自身也逐 lane
串行执行，不绕过各自 qualification/pilot/资源/方向信号门禁。

`docs/reviews/v32_acceptance_mapping_20261010.json` 保留 684 计划行、117 审查条目、
110 能力矩阵行；其中 277 为计划 normative/delivery 条款。
`tools/publish_v32_requirement_acceptance.py publish` 先重新执行真实 completion audit，
再为每种 proof 生成 immutable 证据文档并写出完整条款验收副本。
每条保留规范原文、source/line、处置、独立工件 SHA、当前身份、域与限制。

911 行的最终处置完整保留，合计如下：

| 处置状态 | 行数 |
|---|---:|
| ACCEPTED_CURRENT_SCOPE | 768 |
| ACCEPTED_EXISTING_SUBSET_NEW_MEMBERS_DEFERRED | 26 |
| ACCEPTED_FIXED_POOL_NO_SWEEP_CLAIM | 1 |
| ACCEPTED_QUALIFICATION_NO_SPEEDUP_CLAIM | 1 |
| ACCOUNTED_CONTEXT_NO_RUNTIME_CLAIM | 40 |
| ACCOUNTED_HISTORICAL_NO_CURRENT_PROMOTION | 58 |
| ACCOUNTED_SOURCE_PARITY_UNCHANGED | 2 |
| DEFERRED_BY_USER_NOT_COMPLETE | 5 |
| OPTIONAL_NOT_CLAIMED | 10 |

新增成员、长期多数候选、明确可选能力及历史来源处置均按原授权范围记账，
不是尚未完成的当前适用 CPU 工程门禁；SOURCE_PARITY UNKNOWN 没有被晋升。

该副本不修改三份规范基线、历史结果或原 coverage-only 台账。
Context、历史事实、明确可选能力、暂缓新增算法保持各自状态，不能被一个通用 PASS
自动关闭；任何必需 proof 缺失或不一致都阻止最终签发。
