# 本轮原生结果审计范围

2026-10-15，在六组正式计时全部结束后，由主执行者和两个独立只读审计任务核对。审计没有重新执行 codec；逐次恢复结论来自实际测量时保存的验证记录，压缩产物及身份重新按文件核对。

| 检查 | 结果 | 证据 |
|---|---|---|
| schedule 与正式终态一一对应 | 2534／2534，0 缺失、重复、额外或 retry | 六组 manifest.schedule 与 observations 的 measurement／terminal |
| 请求分母 | 792 = 181 ready + 611 unsupported | manifest.cases、各 report.admission_counts |
| 运行完成与源码不变 | 六组 complete／true；共同执行 source_id | manifest.execution_provenance、source_snapshot；当前源码与保存快照均重算 hash |
| 原生内部循环与时钟 | 2254 trial，每次 loops=8、warmup=2；单 encode／decode batch 时钟，CLOCK_MONOTONIC | native_batch；每次时间×8=真实 batch totals，python_inside_batch_clock=false |
| 逐份正确性／质量与输入不变 | 正式 trial 内 22540 份配对产物全部 passed／input_unchanged | native_products、verification.validated_operations=10；core restored_hash=原始 bytes hash |
| 独立进程恢复资格 | 181 ready case 各一次 exact-input 资格通过 | qualification_kind=exact、independent_recovery.passed／decoder_process；native decoder PID 与编码 PID 不同 |
| 有效数据分母 | core 每对象跨 codec 输入身份一致；raw_bytes=原数组 nbytes | codec_input_id、native_input、value_count；V-only 的 timestamp_count=0 |
| 完整直接输出 | raw 逐字节一致；Zstd FCS、LZ4 contentSize、Snappy 长度一致；LZ4 head+finalize=完整帧 | 实际 `.codec` 文件、native_batch head_sizes／finalize_sizes／output_sizes |
| 辅助大小未知项 | API lossless68case与bounded6case保持null，无ABI输出fallback | codec_complete_bytes、stored_bytes、bits/value、ratio及null原因 |
| 产物、映射库与构建 | 保存payload的hash／size、maps原文hash、实际runtime库和binary身份一致 | native_products、native_runtime、native_batch.runtime_maps_path、case.build_evidence |
| 主／辅报告隔离 | 仅 core/prepared 入主表；fresh、API、对象独立辅助 | measurement_groups、report_role、boundary／lifecycle |

直接 core 两组还重新核对原始 CSV 得到的 raw_object_id、每组 20 个 exact 独立恢复、driver 的 298 项编译依赖以及实际 maps 的路径集合。API／object 审计重新核对相应 build 记录、二进制、runtime 文件和 driver 依赖。主报告工具自动检查的范围记录在 [native_evidence.json](../native_evidence.json) 的 audit 字段，源码为 [report_native_results.py](../../benchmark/tools/report_native_results.py)。

API lossless 的 271 个拒绝为 144 dtype、114 线程 profile、12 Gorilla 联合入口、1 DeepZip model alphabet。最后一项在 exact-input 资格触发，见 [observations.jsonl:262](../../runs/native-api-lossless-20261015/observations.jsonl:262)；不是正式试验后删去失败样本。实现小 fixture 中，NeaTS／LeaTS 的 2 个空输入以及 ABBA／fABBA 的 4 个 0／1 行输入按声明约束保留 unsupported，不授予这些输入资格。

所有 ready case 的独立资格、主性能与质量只覆盖其实际声明输入。未实现的 core 入口继续 unsupported；native_api 的通过不授予 core 资格。fresh_request 包含预热、产物最终释放在计时外；prepared 计时外建立工作区，内部必需的 reset／建模／finalize 仍计入。没有将本轮辅助结果或历史对象 wall 时间改名为原生主结果。
