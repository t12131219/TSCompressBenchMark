# 每个计时方向的最短时长自省（2026-10-07）

本次按工程计划 2.4、9.2、9.3、10.1、20.3 检查 MaskedVByte 的正式记录，
发现循环原先以 selected encode + decode 总时长作为终止条件。普通版本的
80 条记录虽然总时长超过 1 秒，解码仅约 0.28 秒；Delta 版本已有 120 条
同类记录。原 `min_duration_satisfied=true` 因而不足以证明各方向达标。

- [x] `MeasurementPolicy.duration_satisfied()` 分别检查 selected encode/decode。
  CORE 使用 CORE 两方向，PIPELINE 使用 PIPELINE 两方向；E2E 使用两方向
  并检查实际完整对象时长。原生 API 时间仍为辅助观测，不改变终止条件。
- [x] `perform_measured_roundtrip()` 使用该条件终止，保持每次 inner iteration
  新建 session、finalize、decode、输入/输出保护及同次正确性检查。
- [x] `measurement_policy` 落盘增加
  `minimum_duration_boundary=PER_SELECTED_DIRECTION_WITH_E2E_V1`。
- [x] 第五层根据原始纳秒与冻结记录中的阈值复查，拒绝伪造的布尔 PASS；
  阈值缺失、非有限数或不符合正式最小值也不得进入统计。
- [x] 26 项 measurement/statistics/Layer 5 测试通过；另 9 项
  Layer 1/2/3/runner 集成测试通过。
- [x] 新增 CORE/PIPELINE/E2E 的两方向不对称反例，以及编码/解码不足但
  `min_duration_satisfied=true` 的统计拒绝测试。
- [x] 原始源码未修改；原 MaskedVByte native 三档六程序 × 9360 场景及
  159 项直接 SDK 已对当前 Python 文件重新冻结和验证。
- [x] `maskedvbyte-u32-formal-20261007-1` 的 80 条原始观测保留为历史证据。
  `delta-maskedvbyte-u32-formal-20261007-1` 已通过 SIGINT 停止，保留 120 条。
  两批均不用于当前接入资格；不补测或替换其原定重复索引。
- [x] 新的两个 `formal-20261007-2` 固定批次完成全部 80/320 次并生成报告。
  独立 raw→report 审计通过：普通版本 80 eligible；Delta 版本 315 eligible、
  5 RESOURCE_PRESSURE。压力记录不替换，各配置仍至少 10 次 eligible。
  两个身份均签署有限 uint32 范围的五层资格，未签署 int64 timestamp 资格。

共享 measurement/repetition/statistics 源码已改变，其他算法的历史资格不能
自动继承到当前执行路径。工作清单保留需重新资格验证状态；该修正和这两个
uint32 身份的资格均不代表 221 条逻辑条目或 int64 timestamp pipeline 完成。
