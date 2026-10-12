# 当前压缩器构建与链接闭包复核（2026-10-11）

当前 33 个算法、67 个注册配置均有本次实际子进程构建与链接观察；有限观察范围 PASS 为 67/67。严格发布构建覆盖 33/33 个算法，所声明严格门禁 PASS 为 33/33。

该结论只适用于本次新构建。67 配置的普通观察保留实际 exec、文件打开、链接 map、archive member 与外部检查点，其历史 exec/解释器前置 SHA、按进程绑定文件版本缺口没有追溯修复。33 严格发布构建额外验证实际 exec/内核解释器执行前后 SHA，以及可读 OPEN 时的初始文件版本。没有证明同一描述符写入后的读取字节，也没有重建历史执行。本报告不授予完整 N1、source parity 或其他 N/G/CAP 门禁。

| 配置 | 本次观察 PASS / 配置数 | 新旧共享产物字节相同 | 新旧共享产物字节不同 |
|---|---:|---:|---:|
| release | 33/33 | 33 | 0 |
| sanitizer | 33/33 | 17 | 16 |
| debug | 1/1 | 0 | 1 |

冻结注册产物、记录、显式链接输入、元数据、依赖文件、测试产物和注册快照的 SHA 复核：PASS（无漂移）。未覆盖、重签或修改既有记录；新旧产物字节不同的 sanitizer/debug 配置不向旧产物转移新闭包证明。

33 个严格发布构建的新旧共享库字节全部相同。DZip 的这个一致性结论只覆盖共享适配库：939 项声明源闭包中只有生成的 mkldnn_version.h 不同，MKLDNN_VERSION_HASH 从 355468119cd20d8ede370f5063839549806c3bb8 变为 6300188e70faf7d93f3a97f87f0d9cebfb7cdf4c；98 个编译依赖项消费该头文件，verbose.cpp.o 一个对象不同，四个已登记测试可执行文件也不同。共享库字节相同不等价于整个源树、所有对象和测试程序相同。

| DZip sanitizer 阶段 | CMake configure 秒 | CMake build 秒 | driver 秒 | 批次含分析秒 |
|---|---:|---:|---:|---:|
| discovery | 3.327 | 2130.400 | 2143.435 | 2235.869 |
| pinned-replay | 3.131 | 2124.723 | 2137.249 | 2176.942 |

全部试验索引保留 177 份分析回执，其中 PASS 171、FAIL 6；严格范围 GAPS_REMAIN 有 4 份，已包含在上述 177 份中（3 份基础 PASS、1 份基础 FAIL）。这些是原始试验数量，不能当作唯一 67 配置或 33 算法的分母。原 XZ 分析失败、严格 collector 的失败 pilot，以及 r9 错误 codec 名导致的中断均保留；后续隔离试验没有改写它们。

每份汇总保留实际命令、driver/analyzer 身份、逐配置回执及声明的证明边界。审计辅助 wrapper/helper 仅在新输出树运行；ldd 使用不带审计 LD_PRELOAD 的环境。本轮构建没有执行正式测量，也没有将 ctest --show-only 清单当作测试运行。

| 回执 | SHA-256 |
|---|---|
| [67 配置汇总](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/build_link/fresh_profile_summary_r1.json) | `4217a67e7de30a7adf73297953db5d4bbe5d2ac414138fd83dea42c289d9db6e` |
| [33 严格发布构建汇总](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/build_link/strict_release_summary_r1.json) | `07e6464dd106ba0b476ac39dbca464769c96fdede161fd015560abafb774efc2` |
| [全部试验及失败索引](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/build_link/all_trial_index_r1.json) | `7c18622e47759f228f4c52589a0247e2e6018e27a02a3548fcceaf6dfee277c8` |
| [DZip 实际阶段耗时](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/build_link/dzip_sanitizer_stage_timing_r2.json) | `dc56fa3f7d9239b8bbf66769aa7d75719f2ef30172e24f372cf4d3ae95d5dc32` |
| [DZip 生成头文件差异](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/build_link/dzip-release-generated-header-difference-r1.json) | `5a0d3c43be844910f39143f84d98ea3c0441ab878ff9ace860328889bf2bf689` |
