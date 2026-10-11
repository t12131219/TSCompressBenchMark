# 本轮独立审查：反例与纯文件复核

本目录保存独立审查的修复前反例、源文件快照与只读证据。修复后复测将另存 `fixed/`，不得把修复前 receipt 改写为通过。文件身份见 [before-manifest.json](before-manifest.json)。

## 修复前可行动发现

1. 11 个活动入口的间接 adapter Python 模块未绑定至执行身份：ALP/ALP-RD、LeaTS/NeaTS、五个 Sprintz 入口缺 `lzsse8_raw.py`，FSE/Huff0 缺 `deflate_zlib.py`。隔离目录把 helper 的 ABI `_MAX_RANK` 从 8 改为 7 后，factory 支持路径、`resolve_execution.artifact_sha256` 和 `execution_path_hash` 均不变。两个 LZSS 的 `lzss_common.py` 已绑定，其变化可改变身份；SIMDComp 的 `native_buffers.py` 亦已明确绑定。ALP 条件 source-reject 组合 helper 另需绑定。见 [Python 反例](before/python_closure_report.json)。
2. 运行库登记只核验保存路径与 SHA，没有校验生产加载的实际解析。隔离非 codec 反例仅编译三个 toy DSO；record、command、包装库、登记运行库字节不变，两次 `verified_build_dependencies` 通过。仅改变 `LD_LIBRARY_PATH` 后，实际 `/proc/self/maps` 运行库改变，返回值从 11 变为 22。见 [运行库反例](before/runtime_resolution/result.json)。这不是现有 codec 的恶意流测试或性能测量。
3. 旧 `tools/onboard_requested_lossless.py` 仍有公开调用路径。对隔离工程调用其真实 `main()`，将 native qualification 的 cases 清空、driver SHA 置零、六份 run log 替换后，仍输出 `onboarding 6 PASS` 并生成六张卡片。主仓库登记未改变。见 [旧 onboarding 反例](before/legacy_onboarding_report.json)。
4. mixed-zero block-major 容器虽满足 metadata/output 预算，但每个 block 仍遍历空 buffer。纯算术例为 4,096 个 buffer、65,536 行、363,518 字节 metadata、65,536 字节 payload，产生 268,435,456 次内循环；未实际执行该大例。见 [工作量分析](before/mixed_zero_block_major_work_report.json)。

## 已完成的纯文件复核

- Java/Rust/CLI-core 证据：20,157 个 hash 引用、20,108 个唯一文件，零漂移。逐案例计数为 613 个 Java 合法无损 PASS，另有 2 个 END sentinel 与 8 个使用存档 source failure 预期的 native rejection；Rust 282 个声明 EI10/EJ4/C32 案例均 PASS 且记录双向交叉解码。见 [源证据复核](before/fresh_source_readonly_report.json)。审查者只读取报告、源码、二进制和日志并计算 SHA，没有重新执行源 oracle 或 codec；这些 hash 检查不得当作新源执行证据。
- 62 个新普通 native 构建记录：31 release＋31 sanitizer，498 个实际 TU/object、608 份 depfile、14,868 个 compiler closure 条目；记录 closure 与保存 `.d` 并集一致。2,827 个依赖唯一文件及 60 个原生测试证据无漂移；持久化 receipt 包含报告/审查脚本自身后列为 2,829 个文件。见 [62 记录复核](before/runtime_resolution/62-record-review.json)。此复核没有调用 `ldd`、构建、codec、pytest 或审计 CLI。
- 六活动通用 byte 入口、共享 native streaming、两个 LZSS 与 FSE/Huff0 的当前解码路径已静态核查：descriptor 尺寸/类型/布局/资源预算先于输出分配与 native 调用；本段是源码审查结论，没有授予额外动态测试 PASS。
- completed 原生记录：8 个 profile、32 个 JUnit testcase，1,750 个唯一文件 hash 无漂移。DZip release/sanitizer 各 143 个 TU/depfile、939 个实际 compiler dependency 与记录一致；完整测试名称 universe 无 failure/error/skipped。实际 sanitizer 优化 flags 顺序为 `-O1 -O3`，外部运行库未 instrument、leak 检查关闭的边界保留。见 [completed 纯文件审查](completed_file_review.json)。审查者未执行 CTest、ldd 或 codec。

## 修复后的独立复测

- [Python 执行身份](fixed/python_closure_report.json)：14 个隔离变异均改变 artifact 与 execution path 身份，包括原 11 个遗漏、两个 LZSS common 及 ALP 条件 fallback。惯性 fixture 不加载 native；生产运行库另由 toy DSO 复测。SDK r4 登记刷新后再次读取全部 33 个工厂，间接 adapter import 无遗漏、factory 无 pending error。
- [动态运行库门禁](fixed/runtime_resolution_r2/result.json)：14 个实际生产 factory 路径的非 codec 场景符合预期。声明 hash 都通过，但未登记 `LD_LIBRARY_PATH` 替换、已加载同 SONAME、实际 `LD_PRELOAD`/`LD_AUDIT`、profile drift 与加载窗口替换在 toy 操作前被拒绝；明确登记的 alternative profile 正常工作并改变 adapter/artifact/execution 身份。生产 factory 先验证并保持实际 CDLL handle，可正确服务延迟创建 session 的 adapter。r1 使用审查脚本错误枚举名产生的 FAIL 保持原样，r2 修正审查脚本后独立重跑；不得把 r1 说成生产失败。
- [mixed-zero 真实 helper 对照](fixed/mixed_zero_helper_review.json)：128 buffer、256 行、4,608 字节 payload，旧 helper 的 `math.prod` 调用 33,024 次，修复后 384 次；IEEE 位模式含 NaN/负零、validity、dtype/shape、空 buffer 与只读恢复逐字节相同。旧 helper 快照来自修复前 13 份相同的隔离源码副本；未执行巨大的旧反例、codec 或 native。
- [旧 lossless 报告门禁](fixed/lossless_gate_review.json)：当前真实 `read_native_report` 接受 v4 的六算法十二 profile，拒绝五种缺证据/漂移/重复/缺 profile 变异。此项未执行完整 admission，也没有修改生产卡片；最终 strict admission 另由资格结果证明。
- [模型路径静态审查](fixed/model_path_static_review.json)：登记 artifact 的路径后缀用于推导 checkout 根目录，模型名称限安全相对路径且拒绝 symlink 越界；7 个代码/test/manifest 文件、17 个 DeepZip 模型 SHA 一致。15 个新增测试场景做了静态覆盖复核，审查者没有执行 helper、测试或 codec；native 再开文件及 TOCTOU 不由静态审查授予。

## 最终冻结证据的纯文件复核

- [SDK r4、strict admission r2 与库存 r2](stable_receipts_review.json)：18,681 个哈希引用、3,669 个唯一文件无漂移。33 活动入口的当前声明 dependency 均由真实工厂核验；源码库存为 8 个完整 vendor tree、1 个 selected closure、24 个尚未等价完整 closure 的 UNKNOWN。SDK JUnit 为 504 个 testcase，零 failure/error/skipped；六算法 strict admission 对齐 12 个 native profile、613 个合法 Java 案例，2 个 END 与 8 个 archive-expected rejection 保持分列。36 个运行库 profile 的 72 份 fresh capture/replay observation 保存的路径和身份一致，范围为实际 ELF 运行库选择。
- [首次活动入口资格的历史边界](active33-r1_historical_review.json)：全部 41 个 track case 已保存，40 个 `SCOPED_PASS`、DeepZip 1 个 `NOT_ACCEPTED`。40 份保留 stream/context 与成本、独立 worker recovery 闭合；四矩阵为 33/33/41/41 行。DeepZip 的错误路径位于 `build/adapters/completed_rewrites/vendor/...`，不能称模型缺失。报告与 case 内容身份一致，但 8 个指向后续修改源码/登记的 hash 引用明确列为漂移；该 receipt 不授当前源码资格。实施方报告旧 CLI 对失败 summary 返回 exit 0 的事实以消息为来源，无独立保存终端日志，不补造退出记录。
- [活动入口资格 r2 的当前闭包](active33-r2_file_review.json)：33 个活动入口全选、41 个实际 track case 全为 `SCOPED_PASS`。22,564 个哈希引用、4,232 个唯一文件零漂移；plan/case canonical 内容身份一致，41 份保留 stream/context 的实际字节与完整成本、配置及独立 worker 恢复身份相符。四矩阵为 33/33/41/41 行；本轮仅授有限 fixture 与已执行边界，未执行的域仍为 UNKNOWN，不授完整 source domain 或 FORMAL。
- [SDK r3 对当前源码的漂移](stable_receipts_review-r3-drift.json) 与 [对应工厂 pending](fixed/python_closure_report-r3-drift.json) 均保留。它们反映 `completed_rewrites.py` 修正模型路径后，r3 旧 snapshot 不再对应当前代码；r4/r2 另验通过，没有改写旧 receipt。
- [首次完整回归的历史失败边界](full_regression-r1_historical_review.json)：真实默认无过滤 pytest 终态为 2,763 passed、10 failed、6 errors、602 warnings。120 个当前源码与 130 个测试/fixture 文件、解释器、driver 和日志 SHA 复核一致，执行期快照 unchanged；独立审查没有重新运行 pytest。该 v1 回归仅冻结 `pyproject.toml` 作为 test configuration，没有冻结 configs/registry/schemas，因此不授完整项目配置闭包；新 v2 driver 已加入上述目录的文件全集和前后不变校验，最终结果另验。使用的独立审查脚本原字节保留在 [r1 review driver](review_full_regression-r1.py)。
- [旧断言的纯文件复算](fixed/regression_expectation_precheck.json)：两原测试快照与修前当前文件字节一致。NeaTS 已登记 `RELATIVE_PATH_NUL_FILE_BYTES_V1` 的 patch directory-relative 名称＋NUL＋原始字节 digest 确认为 `43ed9bfbea3cf84bccc341427c2f242c76441bb66c3d82a85aa26e1a9041178f`；旧 sha256sum 文本方法不等于此登记协议。此复算未运行测试，也不替完整回归修复授予 PASS。
- [当前工作清单引用](current_reference_file_review.json)：47 个引用、30 个 codec key 与当前库存身份一致。回滚两个 candidate 身份字段并移除本次新增 refresh receipt 后，整份清单严格等于 before，历史资格、来源审查与状态没有重签；本项不授额外资格。
- [四份新比较配置](source_rebind_file_review.json)：308 个哈希引用、89 个唯一文件无漂移；19 个 member slot 的 source pin、closure digest、方法语义定义、source tag 和派生配置身份链均相符。非 source/revision/display/derived-ID 决策严格保留，corpus 身份不变。LZSS 显示名由 Rust 更新为当前 C++ profile，MethodID 因显示名称不参与身份而保持；所有 19 个方法身份均保留。本项只读核验新计划，没有调用 `compile_group_plan`、codec、pilot 或 FORMAL，旧资格/性能没有转移。
- [修复差异与新角色元数据](regression_repair_file_review.json)：7 对 before/current 文件中，6 对精确对应完整回归 r1 的冻结哈希，1 对只属于首轮 targeted 中错误的新 MethodID 断言。6 份测试文件的函数名称与参数 decorator 不变；workload 原 assert 完全保留，comparison 原 assert 全保留并补 source-transfer 限制。保存的 targeted JUnit 为 55 PASS＋1 错误断言 FAIL，修正后独立一次 source-rebind 单测为 19 PASS，两个运行分开列示、不累加为同一测试。新角色台账的 canonical 身份与 46 个 input file SHA 一致，33 活动入口、28 个选定组入口、10 个组、5 个未入组入口，只授声明角色/来源映射；stage 不是实际测量 trace。精确差异见 [test diff](fixed/regression_test_repairs.diff)。审查者首次把允许变化的测试函数名称写错产生的 [harness FAIL](regression_repair_file_review-harness-r1.json) 与当时脚本保留，修正名称后另验通过，不把 harness 错误说成生产失败。

- [完整回归 r2 的当前文件闭包](full_regression_file_review.json)：真实默认无过滤命令为 `python -m pytest -q --tb=short`，保存日志最后非空行为 `2798 passed, 650 warnings in 1783.85s (0:29:43)`；零 failed/error/skipped/deselected。653 个唯一文件 SHA 零漂移，120 个源码、131 个测试/fixture、396 个 configs/registry/schemas 文件全集一致；解释器、`pyproject.toml`、回归 driver 和完整输出日志均匹配登记字节，执行前后 input/configuration/driver 快照 unchanged。独立审查增加真正末行摘要及零 deselected 检查，没有重新收集或执行 pytest。本 v2 未冻结其余 `tools` 模块（测试实际导入的 audit/build/bundle/rebind 等代码），因此不把这一运行扩展为完整工具模块闭包。
- [新增回归完成 receipt 的独立链接复核](regression_completion_file_review.json)：23 个唯一文件 SHA 一致，7 对 before/current 的 14 份快照、r2 validation/log/driver、真实计数与执行期稳定标记均匹配；原 repair-record 的 PENDING 状态和历史失败证据保持原字节，新 receipt 单独记录 r2 完成。完整工具模块闭包、全 upstream parity、全部门禁、独立发布与当前 FORMAL 性能仍未由该 receipt 授予。

以上均限定于保存的实际证据范围。完整工具链/链接闭包、全部 N0–N5/G0–G6/CAP 门禁、完整 REQUIRED_PARITY、独立发布与新 FORMAL 性能不由本目录授予。历史 V3.2 completion 继续属于旧冻结闭包；当前完整 Python 回归由 r2 的真实终态与文件闭包授予，历史 r1 失败及修复范围继续保留。
