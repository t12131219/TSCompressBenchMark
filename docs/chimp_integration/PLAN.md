# Chimp family 接入计划（N0，2026-10-17）

请求：移除旧 Chimp / Chimp128，消费独立 chimp-family 研究发布包；新增明确的 32 位、N 窗口、no-index 和四种有损方法。Gorilla、ALP 与 Elf 家族不在替换范围。

1. 旧 vendor、共享 shim（含工作区未提交修改）、冻结清单及旧卡片先归档，再删除旧 Chimp 活动资产／分支。
2. 从发布包选择性读取、独立写入源码与研究资格／许可文件，不保留 tar 硬链接；核心不修改。记录发布包、文件、编译依赖、构建与运行身份。
3. key：chimp(f64)、chimp32(f32)、chimp128(ChimpN/128,f64)、chimpn(f64,N)、chimp128-no-index(f64,128)、chimpn32(f32,N)、pmc-mr、swing-filter、swing-filter-disjoint、swing-filter-disjoint-quantized（后四者 f32）。FPC / filter2 不开放。
4. 无损每块完整 CFP1，默认 block_size=1000，范围 1..1048576，尾块准确，空流也产生完整帧；N 为 1..65536 的二次幂。EOF 正规范 NaN 拒绝，不做降级。对象按列，core 为物理连续标量流。
5. 有损按完整列运行，有限 f32，隐式 t=0..N-1，不开放原始不规则时间戳接入；默认 quality_mode=strict_abs，实际重构必须有限且 maxABS<=float32(epsilon)，否则拒绝。compatible 保留源码误差／非有限结果，仅 empirical_quality。严格检查是逐输入拒绝式验证，不是全域数学界证明。bounded_abs 任务另执行框架实际质量检查；不使用未经证明的相对界。core 有损仅 rank1／单列以避免跨列拟合。
6. 默认原生 core 调用冻结 owning-vector API；输入 word/Point staging、对象创建／reset、完整帧、重构及严格检查均为操作工作，owned result 生存到 release。辅助 C1 是 CFP1 列容器并复制到 caller buffer，零字节 finalize。prepared / fresh_request 都验证全部产物及独立冷恢复。
7. 绑定单独验证：独立 CMake CLI 参考；存档 Java oracle 原始字节／重构案例重放（不冒充本次新 Java 验证）；dtype、N、EOF、窗口回绕、损坏帧、容量／重试、原子失败、ownership、冷解码、已知 Swing 失败；本机 sanitizer；完整 Python 回归。
8. 独立包 RESEARCH_REWRITE_VALIDATED 和有限本地研究授权（到 2026-11-17）如实保留，不改签 FULL_PARITY；不继承独立包跨架构／fuzz 结果为 Bench 结果。本轮正确性接入，不重签历史正式吞吐；完成报告、开发日志和 V4 时间线。

执行补充：除存档证据重放，本轮实际新编译并运行了冻结 Java oracle；完成报告 README.md 与 evidence.json 记录最终范围、全部身份和本机验证。10 个 key 的满元素上限与超限拒绝另行实测。
