# 12 条 comparison lane 独立只读复核（partial）

本报告仅核对 `formal-r3` 已完成的 12 条 comparison lane。它不授予整体 FORMAL，也不把 V3.2 历史运行转移到本轮。工作负载与 pipeline 尚未纳入本 partial 结论。

## 统计

|lane|planned/raw|actual record status|top STOPPED|core formal complete|analysis|
|---|---:|---|---:|---:|---|
|abs|96/96|PASS=79, RESOURCE_PRESSURE=3|14|9/12|CORE_INCOMPLETE|
|api|96/96|PASS=93, RESOURCE_PRESSURE=1|2|11/12|CORE_INCOMPLETE|
|byte|96/96|PASS=87, RESOURCE_PRESSURE=2|7|10/12|CORE_INCOMPLETE|
|cold|96/96|PASS=83, RESOURCE_PRESSURE=3|10|9/12|MISSING|
|entropy|128/128|PASS=128|0|16/16|CORE_COMPLETE|
|f32|320/320|PASS=298, RESOURCE_PRESSURE=7|15|27/32|CORE_INCOMPLETE|
|f64|320/320|PASS=294, RESOURCE_PRESSURE=6|20|29/32|CORE_INCOMPLETE|
|i16|224/224|PASS=175, RESOURCE_PRESSURE=10|39|12/20|CORE_INCOMPLETE|
|model|64/64|PASS=56, RESOURCE_PRESSURE=2|6|6/8|CORE_INCOMPLETE|
|quality|192/192|PASS=145, RESOURCE_PRESSURE=10|37|14/24|CORE_INCOMPLETE|
|timestamp|320/320|PASS=230, UNSUPPORTED=8, RESOURCE_PRESSURE=4|78|28/32|CORE_INCOMPLETE|
|u8|128/128|PASS=120, RESOURCE_PRESSURE=1|7|15/16|CORE_INCOMPLETE|

总计：268 cells（228 CORE PASS、32 EXTENSION PASS、8 EXTENSION REJECT），2080 schedule/raw rows，1845 nested actual records（1788 PASS、49 RESOURCE_PRESSURE、8 UNSUPPORTED），235 top-level STOPPED。

## 复核结论

- 每条 lane 的计划槽位、raw 行、cell repetition 覆盖均完整；槽位存在不等于 codec 实际执行。
- actual `record.status` 与冻结期望的语义一致：`PASS→PASS`，timestamp 的 8 个 `UNSUPPORTED→REJECT`（原因 `CAPABILITY_MISMATCH`）；49 个 `RESOURCE_PRESSURE` 出现在 expected PASS 槽位并按资源门禁排除。未发现 `FAIL` 或期望错配。
- STOPPED 行均为顶层 `status=STOPPED`、`record=null`、`PATH_STOPPED_AFTER_FAILED_ATTEMPT`；沿 `failed_trial_id` 可追到同 cell 的资源压力根（或 timestamp 预期拒绝根）。
- `cold` 的 qualification/pilot 已有，但 `analysis.json` 缺失：reporter 对 STOPPED 的 `record=null` 调用 `.get` 失败；因此不能把 cold 当作分析闭合。
- 只有 entropy 为 `CORE_COMPLETE`；其余有 analysis 的 lane 是 `CORE_INCOMPLETE`。不据此授整体 FORMAL。

证据索引见同目录 JSON 的每 lane `evidence` 字段；引用了各 lane 的 `comparison_trials.jsonl`、`execution_plan.json`、`comparison_plan.json`、`bundle.json`、`analysis.json`（cold 缺失）及统一 `queue_attempts.jsonl`。
