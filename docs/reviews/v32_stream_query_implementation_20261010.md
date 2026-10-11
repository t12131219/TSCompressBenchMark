# V3.2 原生流式与查询 profile

## 冻结配置

`tools/build_v32_workload_bundles.py` 仅使用现有登记压缩器，不添加算法。流式组为
DEFLATE、LZ4 frame、Zstd frame、Brotli stream、XZ stream，共 20 个固定 cell；查询组为
NeaTS lossless i64、LeaTS lossless i64，共 8 个固定 cell。两组均沿用四个原始 VALUE 对象与
两份独立真实源数据。查询组保守合并为一个方法等价类，scope 为 RESEARCH，结果只描述相关实现变体。
整数查询保留原始 i16 身份；登记公共 API 接收原始整数 dtype，适配器内部使用 i64 的转换成本
包含在 API 调用中，不能将其误标为公共 API 之前的 framework EXACT_WIDEN。
生成器接受 `--byte-base`、`--int-base` 与 `--revision`，以新文件名冻结更新后的配置；
已有不同内容的 bundle 或协议不允许覆盖。协议 sidecar 明确保存 `clock=PERF_COUNTER_NS`。

正式配置为 8 个独立 spawn 会话、5 对采集器 enabled/disabled pilot、固定线程资源租约、
每 trial 30 秒、总预算 1 小时。请求和 block_rows 在测量前冻结；pilot 使用独立 development
数据并禁止与正式 logical_content_id 重合。任何资格或 pilot 不合格均拒绝正式测量。
查询同时生成 REUSED_SESSION 的 `-protocol.json` 与 FRESH_SESSION_PER_QUERY 的
`-fresh-protocol.json`，各自生成独立 workload_id 与 RunSet，不混合冷/预热会话结果。

## 流式测量

这是已知长度、固定 65536 行分块、finalize 后恢复完整对象的 profile。`stream_start` 的输入
描述已知总长度，宿主已持有完整 canonical 输入，因此不声称无限流、未知长度或恒定端到端内存。
每个 worker 自行 warmup；正式编码包括 forward preparation、session 创建、全部 push、finalize、
容器、上下文和关闭。全部 block 的延迟和 emitted bytes、finalize 与完整 encode/decode 时间保留。
PROCESS_RSS 及父进程线程采样保留；state_bytes 是适配器遥测，不能等同于完整内存占用。

输出第一字节可能只是容器/codec header；first_payload_byte 与 first_consumable_sample 均为 NA。
当前恢复 API 只支持 finalized full object，不宣称在线下游消费。backpressure 是调用者同步 push。
压缩流、完整 paid context 均实际落盘并计入 final_bits。恢复在新的 spawn worker 中进行，接口仅接收
登记依赖、stream/context/hash，没有原始数组、routed input 或编码器会话；输出在 decoder 内拥有自己的内存。

## 查询测量

固定 point/range × projection 请求在 worker 和计时前生成。API 只接收压缩流与 request；原始数组仅供
timer 外验证每次返回的 exact slice。timer 包含 API 与 owned copy；选择 FRESH_SESSION_PER_QUERY 时
创建和关闭也计入每次 latency。REUSED_SESSION 保留同一会话并执行冻结 warmup。
两种策略都明确声明当前 API 的 parse/index/checksum 成本随实现逐次计入，未证明 parsed cache。
OS cache 未清空。bytes_touched 标为 LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC，
不能解释为磁盘、cache line 或硬件流量。
查询 worker 的 ResourceSampler 覆盖请求循环和 timer 外正确性验证；PROCESS_CPU/RSS 是该
worker 阶段的观测，不应标成纯 query API CPU 成本。latency 主指标仍是每次 API 与 owned copy。

请求逐次保留 wall_ns、requested/decoded elements、requested logical bytes 与 touched estimate。
p50/p95/p99 每个独立会话单独计算；不足 100 个请求时 p99=NA。置信区间按配对独立会话 block
bootstrap，绝不把同一 worker 的 1000 个请求伪装成 1000 个独立实验。所有配对比较使用冻结
family size 的 Bonferroni 区间；精度不足保留 INCONCLUSIVE。

## 持久性和审计

独立 `workload_plan.json` 绑定 base GroupSpec/cells、源闭包、资源合同、完整协议、请求、schedule。
资格检查沿用已冻结 original-object recovery 要求。pilot 保留每次真实流与 context，读报表时重新
检查 raw coverage、采集扰动、PID/线程/环境门禁、恢复与物理文件 SHA。正式 raw append-only、
单一 RunSet 与主机租约互斥，共用绝对 deadline；失败、未解析的中断不自动重试。
报表重新推导冻结 plan/request/schedule、资源租约身份与环境阈值，物理 context/stream 变化会排除对应
session；不重写已有 raw。固定 cell 缺 session 时 PROFILE_INCOMPLETE，完整覆盖仅为 PROFILE_COMPLETE，
与推断达到精度分开。

## 时钟和空驱动资格

workload plan 单独冻结 `timing_calibration_policy`，继承 base `MeasurementProtocol` 的
`min_clock_signal_ratio` 与 `max_harness_fraction`，并固定原始样本数和边界。
每个 development pilot 的实际测量 worker 在声明的 warmup 之后、采集器与正式方向 timer
之前记录 clock info、257 个连续读钟时间戳及 33 次空外部 clock/dispatch 样本。stream
encode/decode 和 query 的证据分别绑定真实 worker PID、warmup/measurement/lifecycle 时间。
这段校准不进入 API latency，也不冒充 codec 包装、复制或启动的全部开销。

审计从原始时间戳重新计算正增量 quantum，与 clock info 的 resolution 取较大者，并以
空驱动 median 除以冻结 `max_harness_fraction` 得到最小信号。pilot 每方向、每次 query
均须达到 clock ratio 和空驱动比例门限；正式门限取相同 member/config/direction 的所有
pilot worker 中最保守的值。正式 query 不得用 1000 次请求的总时长掩盖单次过短信号。
缺少原始样本、PID/时间边界不符、过短信号均不能通过资格或报表审计，且不减去 overhead。

## 查询放大率和依赖成本

每个独立 query session 报告 `sum(bytes_touched)/sum(requested_bytes)` 的 read amplification，
以及 adapter 报告的 `sum(decoded_elements)/sum(requested_elements)` 的 decode amplification。
分母为零时保留 null、availability 与具体原因。前者是逻辑 native frame 估计，后者是
adapter 报告的元素数，不等同于硬件流量或未观测的 native 内部中间操作数。

当前 NeaTS/LeaTS 的 model/index 完整 frame 全部计费；未独立物理分摊的 index/checkpoint
报告 null、`NOT_SEPARATELY_IDENTIFIED` 和原因，同时保留 ledger 的 allocation bucket。
ledger 的 0 不能解释为免费索引或不存在索引。每个 session 链接实际压缩 frame、paid
decode context、冻结 decoder manifest 与 source artifact 的位置和 SHA；前两者闭合到
FinalBits，登记可执行软件依赖属于软件成本边界，不重复计入数据对象位数。

## 验证

`tests/unit/test_workload_driver.py`：28 项已通过，其中 19 项真实原生测试覆盖五个 stream 的空输入、整块和
partial 尾块，以及两项 query 的 reused/fresh session 策略。stream fresh decoder 的接口签名同时验证
不接收原 input 或 encoder。新 runner 集成测试执行实际 qualification → pilot → formal → report → resume；
包含 physical context 变更、pilot coverage 伪造、冻结 cells/request 重签后修改。native API 的
plan-stage 负例向真实准备函数注入 array schema 或 bytes 变更，验证来自同一原始 corpus 的
不同 actual public API 输入会被拒绝；负例没有测量或生成性能结果。

新增计时证据缺失、PID 篡改、resolution 信号门禁、正式单次过短延迟，以及查询放大率与
不可分摊成本的针对性检查。unit 日志为 `/tmp/tscb-v32-workload-timing-unit.log`。
更新后的 15 项 integration 检查已通过，日志为
`/tmp/tscb-v32-workload-timing-integration.log`（103.71 秒）；包含两个真实 workload profile
和计时负例、三项 plan-stage 负例。Ruff 已通过。统一源码冻结后的正式证据仍须另外生成，
不能将合同测试的通过数解释为正式测量结果。
正式 evidence 需在统一源码冻结后生成；软件集成协议只执行两个 outer sessions，不能作为性能结论。
