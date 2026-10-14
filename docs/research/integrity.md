# 输入、质量与分析完整性修正

这次补强改变data／validate／worker／measurement及执行来源身份。旧manifest／observations保留原字节；现有报告可只读重建，旧结果不改写为新代码结果。新正式运行必须重新资格，并保存实际执行源码快照。

- 多列选择同步V、mask和schema.columns；T按同一行窗口对齐。越界／负值／布尔／非整数／重复列明确拒绝，零长度窗口保留；C/F source布局和显式order分别处理。
- point-relative违例保留实际误差、分母／floor／阈值及违例数。NRMSE／PSNR保存原valid finite V range及null原因；特殊bits／mask／T检查仍独立且严格。
- ZFP task目标、native requested／effective tolerance和实际误差分开。原生帧checksum／record geometry验证后，在计时外读取实际参数，含0.1请求实际0.0625的真实验证案例。
- 所有分析使用同一exact schedule检查：case/session/round必须已计划，每attempt最多一个terminal。缺失键不能由额外成功行抵消，最早实际执行失败不能被成功retry覆盖。
- execution_source_unchanged=false永久阻止该run变成完整性能证据；恢复源码也不能resume洗去这一事实。report／study／环境比较／replay均采用相同gate，仍保留诊断和原始状态。
- 未完成started无terminal的中断先追加未知恢复error，再由resume新增attempt；已完成实际失败只在显式retry时重试。两种情况均保留最早执行失败。
- 新manifest具名hash测量／runner／config／records源码闭包，并保存Python package字节快照。环境快照在trial clocks外，volatile频率／power字段不作为严格resume身份；旧缺失环境不倒填。

[33组历史schedule审计](schedule_integrity_audit.json)保存逐run manifest/raw hash、分析id、完整case和missing keys；原测量文件均未改变。不同实施身份、数据窗口、边界、资源和恢复任务仍分别统计。完整当前代码测试、36成员重新资格与新正式run结果将在实施报告中更新，不能把focused回归或capability预检称作formal结果。
