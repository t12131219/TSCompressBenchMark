# Cold STOPPED 空记录汇总修复提案（未应用）

当前 FORMAL 串行执行期间仅静态阅读；没有修改生产代码、测试、注册、配置、适配器或 FORMAL driver，没有执行测试、codec、模型、构建或测量。

`analysis.py::_cold_trial_issues` 在保护性 try 之前读取 `trial["record"]` 并调用 `.get()`。runner 的合法 STOPPED/INTERRUPTED 槽位会保存 `record: null`，因此报告器发生 AttributeError。通用 `trial_issues` 和 exclusions 状态提取已经使用 `trial.get("record") or {}`；提案让 cold helper 使用相同的一行处理。

空记录不会通过门禁：缺少 cold_observation 在已有 try 中产生 `COLD_EVIDENCE_MISSING_OR_INVALID`；通用检查仍产生 `FORMAL_EXECUTION_NOT_PASS`、correctness/accounting/recovery/timing 等不合格原因。冻结计划的行、planned_process_count 和 planned raw bits 仍由原 plan 构造，失败试次保留 exclusions，不能产生 FORMAL_COMPLETE 或核心聚合。

补丁附加一个三参数化的纯分析回归测试（null、缺少字段、空字典）。使用既有 `_experiment` 计划，将16个槽位全部设为 STOPPED 且仍保留已保存的 success booleans，检查 raw 门禁拒绝、汇总不崩溃、4行与每行4次的固定分母、全部16条STOPPED排除、无聚合和输入不变。该测试是控制流与拒绝行为验证，不作为真实 FORMAL 数据或模型/算法资格。

当前提案状态：STATIC_REVIEW_ONLY_NOT_APPLIED_NOT_TESTED。父任务须等当前16个分支和原闭包审计结束，再应用补丁并运行目标 unit 文件，以及现有正常分析/拒绝测试。生产代码修改会改变分析实现身份；旧原始日志、回执、失败和旧报告应保持不变。修复后的报告或新测量必须另存且按新的身份审查，不把旧结果重新授予新 FORMAL。

建议执行（仅供父任务结束后使用，本轮未执行）：`python -m pytest tests/unit/test_comparison_analysis.py`。既有实际 cold 集成测试包含正常边界与变更证据拒绝；如另有需要，应在允许启动codec后单独验证，不能在当前测量窗口运行。

quiet：本子任务无后台构建、测试、模型、codec或性能进程。
