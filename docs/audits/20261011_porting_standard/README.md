# 现有算法移植规范审查与修正（2026-10-11）

本轮依据三份完整 Markdown 文档审查当前 33 个活动入口，修正代码并重新验证。文档是验收依据；其中操作说明不作为额外授权。范围保持现有算法，退出项不恢复，旧证据不改写。完整阅读覆盖见 [document_reading_coverage.json](document_reading_coverage.json)。

不能把所有入口统一称为“全部满足完整重写条件”。原生复用／修改后的原生移植按 N0–N5 审查，核心翻译按 G0–G6 审查；当前 Benchmark 资格、源码对照、独立 API、安全资格与 FORMAL 性能分别表达。受限 profile 的正确性成立，不授予上游所有能力、模型和平台的 FULL_PARITY。

[33 个活动入口的逐算法结论](rewrite_routes.md)逐项列出实际核心、对象层级、适用门禁、声明输入／执行范围与剩余缺口，机器可读映射见 [rewrite_routes.json](rewrite_routes.json)。11 个入口属于核心重写，22 个属于原生路线；薄 binding 不代替核心翻译。

## 已实施修正

| 问题 | 修正与验证范围 |
| --- | --- |
| 不可信容器在分配或 native 调用前缺少完整尺寸与类型验证 | 共享 typed-byte 验证层；检查重复键、dtype、rank、shape、可寻址乘积、名称、长度、logical bits 和资源预算，覆盖六 byte、两个 LZSS、FSE/Huff0 入口 |
| one-shot decoder 未正确恢复多 buffer 的流式 block-major 保存对象 | 明确恢复布局、dtype、shape、IEEE 位模式及 tail；新独立 decoder 用保存对象恢复 |
| 少量非空数据与大量空 buffer 使 block-major 恢复工作量按两者乘积放大 | 预计算 row bytes，每块只遍历非空 buffer；空 shape/类型保留，加入操作量边界和恢复回归 |
| DeepZip 的模型定位硬编码旧构建目录层级，新 output-root 下找不到模型 | 按已登记 artifact 相对路径确定项目根，校验模型路径与符号链接边界；新旧构建层级和真实恢复回归 |
| ABBA/fABBA 的 2^64 浮点长度转 size_t 可触发 UB，并可能先进行巨量循环 | 转换前排除不可表示长度、循环前核剩余容量；实际 patch、旧 core、旧 harness 与对照日志保留；新包加入原生回归 |
| LZ4/Zstd C 解码 API 接受非法 output.used、EOF 后再次 update | 原生输出描述与状态检查；实际 descriptor/EOF/reset/合法字节及交叉解码回归 |
| NeaTS/LeaTS 的 patch 为说明文字，无法重放 | 三份实际 patch 从冻结 upstream 重放，172/172 vendor 文件完全一致；派生新 SourceArtifactID 并同步登记 |
| 只观察 hash 或只验少量已声明文件就称完整 source closure | source_evidence 分开观察、锁匹配、selected closure 与 tree 检查；新增文件与缺失目录亦阻断 |
| 空 CTest、旧 binary 或变动测试程序也可能获得 native PASS | 严格非空 inventory/JUnit；实际编译 TU/header、runtime、测试可执行文件、recipe/driver 前后闭包验证；缺记录必须重建 |
| factory 对一些实际入口未核验已声明 build 证据 | 运行前统一验证声明的源、补丁、对象、生成文件、工具链与依赖，保留 SIMD 特别门禁；真实支持模块纳入身份 |
| onboarding 仍消费旧格式的宽松 PASS | 新 completed admission 复核严格资格闭包、日志、JUnit 和 driver，保留 before/candidate 迁移证据 |
| 间接 adapter Python helper 或 ALP 条件恢复模块变化没有改变执行身份 | 递归绑定实际 adapter import 及条件恢复依赖；用真实 `resolve_execution` 的变异反例验证身份变化 |
| 只验证构建记录里的运行库路径，未识别本次解析与已加载的同 SONAME 替换 | 新 runtime profile 分开构建 linkage 与实际 ELF 加载；核验当前解析、已加载映射及加载后状态，并把 profile／实际库绑定执行身份 |
| 旧六入口无损 admission 可接受空 cases、旧 driver 和替换日志 | 显式新输出与严格当前资格／源对照门禁，候选登记前后闭包一致，保留 historical／fresh／END／拒绝的独立范围 |
| 来源身份更新后旧比较配置在实际输入门禁前即被拒绝 | 保留旧配置，派生四组新 source revision；绑定当前 source/closure/tags 并重算身份链，严格保持语料、参数、结果预期、协议、预算及方法语义 |
| 当前接入工作清单仍引用旧 AlgorithmID／SourceArtifactID | 依据当前库存和有限入口资格同步 47 处引用，保存 before 和逐字段变更；历史审查内容不重签 |
| 全量回归只冻结 pytest 配置，未冻结比较配置、登记和 schema | v2 回归驱动增补三个目录的完整非缓存文件快照和 driver 前后不变检查，原 v1 证据保留 |

最终独立审查额外复现了间接 Python helper 未绑定执行身份、同 SONAME 运行库替换和旧六入口无损 onboarding 接受空测试结果的问题；[独立审查目录](final_independent_review/README.md)保留隔离反例、修复前源码及 SHA。对应门禁和实际运行库 profile 的最终验证记录另列，原反例不会改写成修复后 PASS。

首轮完整入口资格 [active33-r1](../../../build/port-standard-v30-20261011/active33-r1/summary.json)保留 40 个 PASS 与 1 个 DeepZip 模型路径失败。该轮失败由模型路径修正解决，15 个路径安全反例、2 个资格命令退出码回归和 17 个真实 completed adapter 回归共 34 项通过。失败资格命令现在返回非零退出码；首轮原日志、冻结计划和结果不修改。

## 当前登记与独立资格

- [完整活动入口资格 r2](../../../build/port-standard-v30-20261011/active33-r2/summary.json)：33 个入口全部选中，41 个声明 Track／fixture／config 案例均为 `SCOPED_PASS`，包括当前原生执行、边界、完整成本和新 worker 独立恢复；[四张证据矩阵](../../../build/port-standard-v30-20261011/active33-r2/four_matrices.json)保留未执行领域，不授性能或全源域性质。
- [最终源码／执行库存 r2](source_build_inventory_r1/inventory-final-r2.json)：33 个活动入口的已声明执行依赖全部通过，零源码漂移。8 项 vendor tree、1 项 selected closure 通过相应哈希检查；24 项完整源码树／摘要协议仍为 `UNKNOWN`，没有从已声明哈希检查升级为完整源码闭包证明。
- [无损严格接入 r2](lossless_admission_r2/admission.json)：六入口、12 个 release／sanitizer profile，复核最终原生资格、fresh source 与当前生产依赖后登记；END 和存档失败预期单列。
- [SIMD SDK r4](../../../build/source-audits/simdcomp-sdk-port-standard-v30-20261011-r4/report.json)：504 项实际测试通过，77 个项目 Python 依赖绑定修正后的代码；[登记刷新](../../../build/source-audits/native-sdk-registry-refresh-port-standard-v30-20261011-r4/report.json)保留原 runtime profile 和 native 构建。
- [运行库与 Python 执行身份审查](../20261011_port_standard_v30/native_runtime_and_python_identity_review.md)：实际加载门禁、间接模块变异、当前 factory/API 复验与新证据索引。该独立资格限定动态加载和身份，不授完整 N1。

[解码合同](decoder_contract.md)明确默认输出与 metadata 预算。资源政策不冒称原生算法源域限制。

## 当前比较配置与回归修正

[四组来源绑定修订](comparison_source_rebind_r2/README.md)保存新的 `20261011-port-v2` 整数、质量、时间戳和查询配置与独立 proof，当前默认模板引用已迁移。53 份原比较配置中 17 份固定旧来源身份，作为历史修订保留。新配置只取得当前计划检查，不继承原 codec 资格、pilot 或 FORMAL 测量。LZSS 的显示名称按当前 C++ 来源修正；语义定义不变，MethodID 保持，来源与 revision 更新使 GroupID 和配置身份重新派生。

[当前角色与来源台账](current_role_ledger_port_v2.md)依据新默认配置生成，状态为 `PASS_DECLARED_ROLE_PROVENANCE_ONLY`，33 个活动入口和原映射分母保留。入口资格 r2 的实际 41 个 Track/fixture 案例与新组的计划元数据分别表达；新组还需以新 RunSet 执行自身资格与正式测量。

[工作清单同步](current_reference_refresh_r1/report.json)记录 30 个现有 codec 的 47 处当前引用更新。撤销候选的两个身份字段及新增 refresh receipt 后，整个 JSON 与 before 完全相同；原审查状态、证据与算法范围均保留。

首轮 [full-regression-r1](../../../build/port-standard-v30-20261011/full-regression-r1/validation.json)实际为 2763 passed、10 failed、6 errors、602 warnings，1664.50 秒；`input_snapshot_unchanged=true`。完整错误为旧补丁哈希期望、旧错误文案以及比较配置／工作清单身份未同步。修复没有放宽来源校验、篡改拒绝、实际输入一致性或缺失时间戳门禁。原结果和 [失败批次独立核验](final_independent_review/full_regression-r1_historical_review.json)保留，历史失败核验 PASS 不表示测试 PASS。

原测试与精确旧回归 driver 保存于 `regression_test_expectation_repair_r1/before/`；新测试使用明确的当前源码修订，原配置、参数和断言语义保留。修正后的 [full-regression-r2](../../../build/port-standard-v30-20261011/full-regression-r2/validation.json) 为 **2798 passed、0 failed、0 errors、650 warnings，1783.85 秒**，pytest 与回归驱动均退出 0；默认测试全集未通过 `PYTEST_ADDOPTS` 过滤，终态没有 skipped 或 deselected。源码控制平面、131 份测试／fixture、`pyproject.toml`、396 份 configs／registry／schemas 文件及回归驱动的执行前后快照均不变。`input_snapshot_unchanged`、`configuration_snapshot_unchanged` 和 `driver_snapshot_unchanged` 全部为 true。

该回归证明当前默认测试集合通过；它没有冻结其余 `tools/` 的完整传递依赖，也不授完整工具闭包、上游全域语义或新 FORMAL 性能。首轮失败与当时 pending 修复记录仍保留，[完成回执](regression_test_expectation_repair_r1/completion-receipt-r2.json)另行关联最终通过记录。

补丁哈希、篡改拒绝和工作清单 5 项回归通过；[专项集成回归首轮](../../../build/port-standard-v30-20261011/targeted-regression-repairs-r1.log)为 55 passed、1 failed，唯一失败是新测试误将来源显示名称变化预期为 MethodID 变化，日志保留。修正该测试为语义身份保持并核对当前名称后，[迁移单测最终记录](../../../build/port-standard-v30-20261011/source-rebind-unit-final.log)19/19 通过。专项回归包含 STREAM/QUERY、实际输入 schema/bytes 及缺失时间戳门禁；短集成协议仅验证软件合同。

## 新原生构建与测试

普通原生工件已在新目录构建：31 个既有／保留工件 × release、sanitizer 共 62 份记录。三个范围外工件只用于既有回归，不加入活动集合。实际核验 17,024 个按记录去重的依赖路径、60 个 ABI/kernel/分配失败测试；LZ4/Zstd 另有 590 个旧／新合法编码字节一致案例和 1,180 次双向解码。完整依据见[原生契约报告](../20261011_port_standard_v30/native_contract_review.md)。这些次数是各测试驱动的真实范围，不代表全部上游 API 测试。

最终普通原生测试采用[第四轮资格记录](../20261011_port_standard_v30/general_native_qualification_v4/qualification.json)，另核验每个独立测试可执行程序的运行库解析，执行前后相同。该报告的系统运行库测试与 Python 生产加载 profile 分开；[36 工件运行库登记](../20261011_port_standard_v30/runtime_profiles_v2/registration.json)记录 72 次 fresh capture／pre-post replay。SDK 随后刷新了资格与登记引用，现有 SIMD native 构建和 runtime profile 保持原身份；第四轮 SDK 绑定当前 Python 代码。

ABBA、fABBA、DeepZip、DZip 的 release／sanitizer 8 个 profile 已通过严格非空 CTest，共 32 项测试；[8-profile 汇总](completed_native_r1-summary/report.json)引用原始 JUnit、日志、驱动及构建闭包。CUDA unavailable 是明确的拒绝／能力预检，不表示 CUDA 路径实际运行通过。sanitizer 的实际命令保留 `-O1 -O3` 顺序，最终优化为 `-O3`，没有冒称最终编译为 `-O1`。

## 源对照的证明范围

- Java 来源六入口：在哈希匹配的 Java 8/JAR 隔离环境重新执行原实现差分，613 个有效无损用例；拒绝与 END 单列。fresh CLI 的核心与当前 vendor/FROZEN_APIS 逐 SHA 相连，binding/FFI 另验。
- LZSS：保留的 Rust 原实现离线重建，282 个 raw equality 与双向交叉解码用例通过，限 EI10/EJ4/C32 profile。
- ABBA/fABBA：当前新 CLI 对阶段／声明参数能力进行 fresh 对照；fABBA 为稳定化 profile，stage-composed oracle 不能授予未改全部原作一致性。
- DeepZip/DZip：当前原生 CPU profile、嵌入模型和恢复资格与完整源语言／训练路径分开。旧 TensorFlow/Keras 环境、CuDNN 路径及未部署 trained checkpoint 的未验证范围保持明确；没有用当前实现生成 expected 替代源 oracle。

新 source 执行记录为 [source-oracles-final/report.json](../../../build/port-standard-v30-20261011/source-oracles-final/report.json)、[LZSS 源对照](../../../build/port-standard-v30-20261011/lzss-source-oracle-final/report.json)及 [CLI/vendor 关联](lossless_cli_vendor_link.json)。

[fresh 源对照汇总](fresh_source_summary.json)保存每项数量及报告 SHA。Elf+ 的 8 个源失败预期来自存档，本次执行了有界 native 拒绝；它们没有计入 613 个 fresh Java 有效无损用例。

## 尚未签发的完整条件

- DeepZip/DZip 的完整旧 TensorFlow/Keras 源环境与训练／模型轨迹未恢复；DeepZip 的原 trained xor20 checkpoint 在外部 authority 中仍存在且 SHA 匹配，但未部署到当前四符号 CPU profile。详情见 [learned_oracle_availability.json](learned_oracle_availability.json)。
- 普通构建已核验真实 TU/header depfile、对象、声明工具与动态运行依赖；编译器发现记录不等于进程执行追踪，隐式静态启动／runtime archive 及完整链接闭包尚未全部 pin。completed 构建的测试闭包亦不构成完整工具链 N1。
- Dipperstein LZSS 的指定外部 authority 缺独立源码副本；当前 vendored 文件与测试存在，但不能据此签独立原始来源比对 PASS。
- 有限 profile 的源对照、安全测试、SDK 或 Benchmark 资格不能代替全部 REQUIRED_PARITY、其它平台与独立发布门禁。每项剩余范围保留在逐入口表，不以 waiver 或自回环替代。

## 证据时效

旧 V3.2 16-lane completion 和 FORMAL 仍绑定原冻结闭包，保留历史价值。当前源码、补丁、Python 恢复及构建登记已变化，新安全／入口资格不能重签旧性能。当前闭包的正式性能需要另建 RunSet；本次没有把旧测量改成新工件测量。

嵌入 `Compression_Rewrite/ReWrite` 的旧发布／参考快照保持原样；本轮 ABBA/fABBA 修复和新独立原生测试发生在当前 vendored 包。新 vendor 资格不反向授予旧独立发布包。

本轮完整阅读、逐入口审查、必要修正和限定验证已完成；[最终证据索引](final_evidence_index.json)绑定主要最终文件的 SHA，保留上述未签发范围。该完成状态不表示 V3.2 所有上游条件、独立发布或当前新 FORMAL 性能全部完成。
