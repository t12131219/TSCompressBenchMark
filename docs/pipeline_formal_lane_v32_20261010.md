# V3.2 通用 P2 对象管线正式入口

本入口使用已经注册的 `lz4-frame` 和 `zstd-frame` 作为子压缩器，不增加算法注册。它与 P1、CORE/native 和查询/流式入口分别保存运行身份；结果只描述冻结对象、配方和本机 CPU 的 PIPELINE 成本。

实现：`src/tscompbench/comparison/pipeline_runner.py`。命令：`tools/run_v32_pipeline_comparison.py`。

## 冻结对象与配方

ETTh1 和 Jena Weather 各提供两个任务：四列 f32；混合 f64/f32 对象，其中 f64 以 `[entity=2,time=513,feature=2]` 保存，时间轴显式为 1，并带共享 i64 时间轴和每个值缓冲的有效性掩码。所有对象遵循 BITWISE 空值恢复。

评测窗口为 `[0,513)`，开发窗口为 `[1024,1537)`；两个窗口行数、形状及转换相同，内容独立。每个现有子压缩器绑定完整值、时间和掩码角色，256 行独立块、RAW_TAIL、LOSSLESS。f32 转换、ND 形状、时间和掩码均为派生任务，原始来源清单、canonical 文件及转换声明被保存；不将派生时间/缺失模式冒充真实源时间/缺失模式。

计划固定 4 个对象任务 × 2 个配方 × 4 个独立外层调度块 = 32 次正式试验。子流、重复公开元数据、块/列顺序、RAW 尾部、T 和有效性掩码均参与完整账本，原始分母由原始逻辑对象固定。较短对象的元数据成本可能导致压缩后扩张，报告保留实际结果。

## 边界与证据

正式边界为 STEADY_PROCESS / PIPELINE。每次正式工作进程先进行自己的预热；每个对象创建独立的真实子编码和子解码上下文。选定时钟包含容量 API、准备和兼容操作、真实子 API、公开对象树、散列、完整输出物化。冻结文件读取、spawn/import 和额外的独立恢复资格均在稳态方向时间之外，生命周期记录明确保存。

每次正式试验另启动干净的 spawn 解码进程，参数只有公共解码程序根目录和压缩产物字节；不传原始对象或编码会话。解码进程退出后，父进程检查 owned 输出、原始 schema/dtype/形状、T/V 配对、有效性与位模式。每次试验保留原始压缩文件及 SHA-256。

开发 pilot 执行真实相同工作量的采集器开/关配对，不扣除开销。正式过程使用共享 `ResourceLease` 串行运行、固定单 CPU/单线程预算、父进程线程采样、环境边界和资源门禁。RSS 高水位包括进程导入与预热历史；RLIMIT_AS 为已有 VM 留余量，另按观测 RSS 检查内存预算，不声称 cgroup 硬 RSS 限额。

报告按独立调度块计算配对区间，保持冻结单元分母；未满足预先声明精度目标的效果保持 INCONCLUSIVE。缺失、失败及不合格记录不能通过删行产生新的“共同子集”排名，不进行跨任务/来源泛化排名。

## 执行、恢复和审计

源代码、Python 控制面、子压缩器 manifest/source/build/native binary、实际 native source/header 文件、输入内容、公开配方、资源及测量协议都进入冻结身份。输入、配方、分母、源码或构建漂移会拒绝继续。每次正式试验以 append-only JSONL 保存；没有自动失败重试。报告与恢复检查保存的 artifact/hash 和原始资格/pilot，不改写 trial 或压缩字节。

`experiment_decision.json` 在计划和测量前冻结使用者决策、研究问题、固定目标语料、主要 estimand、精确恢复、资源、选择政策和结论范围。其 `decision_id` 进入运行身份；prepare、资格、pilot、正式执行和报告均校验计划内合同及原始 sidecar。旧运行缺少原始决策文件时拒绝恢复，不能在看到结果后补写。报告直接披露该合同，并稳定引用独立生成的 `uncompressed_reference.json/md` 和 `buffer_cost_audit.json/md`；辅助证据单独验收，不补写原始性能观测。

`pipeline_events.jsonl` 在启动任何正式 worker 前持久化 `STARTED` 意图和当前预算预留，SHA-256 事件链绑定冻结 `plan.json`、slot、唯一 attempt 和后续 raw terminal。worker 与额外独立恢复共用预留 deadline。原始 trial 经规范化后 append、flush 和 fsync，再追加 `TERMINAL_COMMITTED`；完成事件绑定实际 raw trial 字节及累计实际 wall 预算。已完成失败保留终态，`max_attempts_per_slot=1`。

恢复重建持久事件预算。未知 `STARTED` 保留全部预留，写 `interruption_audit.json` 并阻断；已有但无绑定的产物同样阻断，未知成本明确标记，不按零成本复用预算。raw terminal 已持久化但提交事件未完成时，先验证 terminal 和产物，只补提交事件，避免再启动 worker。截断日志、事件链/计划/预算漂移及重复 attempt 一律拒绝。`.pipeline.lock` 拒绝并发恢复；压缩产物以 exclusive create 保存并 fsync，保留中断前字节。

资格为独立辅助阶段。`qualification_intent.json` 在首次 codec 调用前持久化；资格产物在独立恢复前保存，已知编码/恢复失败写 `qualification_failure.json`。没有最终 `qualification.json` 的旧 intent、failure 或资格产物会生成 `qualification_interruption_audit.json` 并阻断重跑。完整已保存资格仍按工件与计划校验复用；这些资格成本不会升级为正式性能观测。

在 SDK 和 source freeze 后运行：

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/run_v32_pipeline_comparison.py all \
  --output /tmp/tscb-v32-final/p2-object --verify-resume
```

`--cpu` 选择当前允许 affinity 中的一枚逻辑 CPU；可省略，让入口选择当前最小 CPU ID。其他正式 lane 应先结束，并由统一协调者串行安排。

各阶段也可单独执行 `prepare`、`qualify`、`pilot`、`run`、`report`。再次 `run` 是对同一冻结运行的断点恢复；已完成时仅审计与生成报告。`--verify-resume` 比较再次执行前后的 raw SHA 和完整报告；其中公共解码器审计需要 codec 解码，范围明确为 `READ_ONLY_INDEPENDENT_DECODER_AUDIT`，不启动新的性能试验。输出包括 `experiment_decision.json`、`plan.json`、`qualification_intent.json`、`qualification.json`、`pilot.json`、`pipeline_events.jsonl`、`trials.jsonl`、`artifacts/*.p2`、`report.json` 与 `report.md`。

验证覆盖真实双来源派生、非首时间轴、T/validity 位分母、公开干净解码、完整资格→pilot→正式→报告→恢复链、输入/配方/closure/分母/artifact 漂移和非法预热 PID。`tests/unit/test_pipeline_interrupted_resume.py` 使用纯 mock 验证 worker 前、产物保存后/raw 前、raw 后/commit 前中断，预算保留、日志损坏、并发锁、失败终态和资格工件保护；不调用真实 codec。容量 facade 另覆盖 67 个单行小块、空对象、重复 update/finalize 和输出不足时原子拒绝。
