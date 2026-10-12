# 当前闭包与 FORMAL 验证

本轮针对修正后的 33 个活动入口验证源码、真实构建／链接、适用 N/G/CAP 及新的 Benchmark FORMAL。范围不新增算法。生产代码、登记、旧来源锁和旧 expected 保持原字节；验证程序及恢复资产使用本目录和新的 build 输出。旧失败、限定 PASS、历史正式运行及冻结索引不追认、不覆盖。

**本轮冻结队列已结束，结论仍有明确缺口。** 16 个 lane 均已尝试，4 个驱动成功（entropy、stream、query-warm、query-fresh），pipeline 在 pilot 阶段因 `P2 development pilot is ineligible` 退出；12 个 comparison lane 保留资源压力、预期不支持、停止和 cold 汇总缺口。语义复核只确认当前声明范围内的 4 个 lane，不能授予完整上游移植／重写资格。

| 专项 | 当前实际证据与边界 |
|---|---|
| 当前安装源码 | [source_closure/r4/report.json](source_closure/r4/report.json) 的 33/33 限定集合与字节闭包 PASS；17 个独立 pinned Git tree 的 14,331 blobs、1,619,641,728 bytes 逐 GitOID/SHA 通过；不是全部源码外部依赖和能力域验收。 |
| 精确来源补证 | [upstream_authority_r3/verification.json](upstream_authority_r3/verification.json) 核验 Elf 指定旧提交、Dipperstein LZSS、bitfile 和 optlist 共 4 tree、363 blobs、16,376,562 bytes；Elf 20 锁文件和 Dipperstein 12 vendor 文件全部匹配。旧“本地未取得”的调查保留其当时状态。 |
| 精确旧源环境 | [completion_supplement.json](oracle_recovery_network_r1/completion_supplement.json) 记录 71 个锁定包、1,778,340,023 bytes 的实际取得／核 SHA 及三套独立前缀恢复。TF-GPU 1.8/1.14 识别主机 RTX 2070；TF-CPU 1.14 单独探针通过。DeepZip 8170 个代码／数据文件及 DZip CPU/GPU 3073/2934 个 Python/ELF 成员匹配。安装 RECORD／脚本迁址差异单列，恢复环境不授算法 parity。 |
| DeepZip 新源差分 | [summary-r2.json](learned_source_oracle_r1/summary-r2.json) 对当前 biGRU 权重及 3 contexts 实测，源重新导出逐字节一致，原 TF 的 GPU CuDNN 实际执行；12/12 概率符合原 `3e-5` 合同，最大差 `1.49e-8`，同一源概率输入的 15 CDF 转换整数 exact PASS；**独立预测的完整 CDF equality FAIL，1/15 差异**，第三 context total 源 `10000004`、CPU `10000003`。不授源码流一致性。独立复算见 [learned-result-independent-review-r1.json](formal_static_review/learned-result-independent-review-r1.json)。 |
| 真实构建／链接 | [67 配置汇总](build_link/fresh_profile_summary_r1.json)：33 release、33 sanitizer、1 SIMD debug 均在声明观察范围 PASS，冻结登记无漂移；共享产物 50 个与旧工件相同、17 个不同。[strict_release_summary_r1.json](build_link/strict_release_summary_r1.json)：33/33 新 release 在 exec／解释器 pre/post SHA、read-capable OPEN 初始版本范围 PASS；33 release 共享适配产物均与当前登记内容字节一致。独立审查的原发现保留，新记录器两样本见 [review-r2](formal_static_review/build-link-independent-review-r2.json)。same-fd 后续写读不在所授范围，旧 build 不追认为已追踪。DZip 生成版本头被 98 对象消费，1 个 verbose 对象和 4 测试程序字节不同，未称整个依赖树相同。全部 177 份试验回执与早期失败见[试验索引](build_link/all_trial_index_r1.json)，不混作 67 配置分母。 |
| N/G/CAP | [acceptance_review_r1.json](gate_acceptance_review/acceptance_review_r1.json) 逐条审阅 33 入口、220 适用门禁，3 个 G0 PASS、32 条完整验收条件 FAIL、185 具名 UNKNOWN，保留全部 42 个 REQUIRED 分类。FAIL 包含未测试及合同／API／发布条件缺失，不冒称 32 个算法编解码失败；完整资格未授予。 |
| 新 FORMAL | [formal-r3 release plan](../../../build/closure-formal-verification-20261011/formal-r3/preparation/release_plan.json) 冻结 16 个新运行分支，保留原 corpus、参数、MethodID、协议、资源和分母；资格／pilot／raw observations 均按冻结计划尝试。三驱动拒绝门禁 [22 cases](formal_static_review/report-r3.json) 符合预期。队列结果与失败日志见 [queue_attempts](../../../build/closure-formal-verification-20261011/formal-r3/runs/queue_attempts.jsonl)。entropy 为 `CORE_COMPLETE` 16/16；stream、query-warm、query-fresh 为 `PROFILE_COMPLETE`；pipeline pilot 不具资格；其余 comparison lanes 保留 `CORE_INCOMPLETE`、资源压力、预期不支持、停止或 cold 汇总缺口。语义复核见 [post-queue audit](../../../build/closure-formal-verification-20261011/formal-r3/runs/formal_audit_post_queue_semantic.json)，成本／未压缩参考见 [auxiliary summary](../../../build/closure-formal-verification-20261011/formal-r3/runs/post_queue_auxiliary/summary.json)。cold 空记录修复已应用并由[独立重分析回执](cold_reporter_fix/reanalysis/receipt.json)验证；未重测性能、未覆盖原 raw。 |

原先“24 UNKNOWN”是有限库存器对于选集和历史摘要协议的状态，不能直接读作“24 个入口没有原源码”。新限定集合 proof 已补齐；6 个历史 digest 序列化及 2 个 Sprintz u8 旧选集仍未声明，未猜测或重签原摘要。

DeepZip 固定权重预测与 CDF、DZip 原初始化／loaded PRNN／online 轨迹分别审阅。当前 DZip `NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET` 不因环境恢复或同 seed 变成原 TensorFlow 初始化。完整 G/CAP、独立交付、FULL_PARITY 与当前 Benchmark FORMAL 均单独记录。

当前矩阵更新前的原字节已保存于 [matrix_sync_r1/before](matrix_sync_r1/before/current_algorithm_data_function_matrix_20261011.md)，SHA `6b7b424dd30377fa5a5ffa45f78d9a7e8da5cd6e673d355febbedddec1dacd83`。本轮队列和审计完成后，矩阵将绑定新的语义复核、辅助审计和 cold 修复回执；旧矩阵回执保持原样。

本轮最终证据索引见 [final_index_r4.json](final_index_r4.json)；索引只绑定已保存文件，不把任何补充审计转授为完整 N/G/CAP 或上游 parity。
