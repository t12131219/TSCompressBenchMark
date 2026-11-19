# 首批 Unique 证据复用对账

适用 [目标 §3.1](../../TSDataCompressBenchMark目标.md#31-先复用-unique-的现有运行证据再按差异补验)。
对首批 **12 条 selection、11 个来源工程**，逐一对照了 Unique 的
`fix_ReWrite/<工程>/FUNCTIONAL_REPORT.md`、`fix_Release/<工程>/unique-v1/validation.json`
与 TSBench 工程内冻结材料。11 份功能报告与对应源码归档成员逐字节相同，11 份发布验证与
本地 `third_party/provenance/<工程>/unique-validation.json` 逐字节相同；归档、发布验证 JSON
和源码 manifest 的 SHA-256 及 selection 绑定由 `third_party/sources.lock.json` / `bmk check-sources`
校验。下表直接引用这些同版记录，不需要在正式工作流挂载邻接源码树。
逐工程的目标、构建参数、依赖及独立构建复用边界见[首批 Unique 构建对账](first-batch-unique-builds.md)。

**可直接引用**只指 Unique 版本上明示测试的历史结果。多数摘要没有提供原命令、具体输入、
有效参数、机器或所有分支的输出，所涉输入边界/机制/后端没有明确证据时仍**需补验**。较早的
`outputs/source_capability_audit_20261110/` 为**仅作参考**的定位和反例，不能推翻后续修复版对应
归档的实际调用；性能表和历史测试数量不是 TSBench 的正式样本或资格分母。

| Selection / 本地原件 | 可直接引用的历史事实 | 不继承的结论、待定向补验 |
|---|---|---|
| 9 ALP Auto · [发布验证](../../third_party/provenance/alp-native/unique-validation.json) | `test_codec` PASS，且隔离包同名测试 PASS。 | [本地 ALP 合同](alp-native.md) 补 f32/f64 Auto 的实发 decimal、异常 sidecar、RD/raw、尾块与独立恢复；分别记录解码 dispatch 和实际内核计数。f64 AVX512BW 本机不可用，NEON/SVE 未在当前平台执行；开发证据不是正式资格。 |
| 11 pcodec · [发布验证](../../third_party/provenance/pcodec-native/unique-validation.json) | `test_core`、`test_native_ext`、`native_negative`、`pcodec-source-c-consumer` PASS，前三者也有隔离记录。Rust C consumer 有历史 PASS，CUDA 只记 build PASS / runtime SKIP。 | 较早探针的 f16 返回 `PC_UNSUPPORTED` 不是新 SourceAuto 的现状；[本地 pcodec 合同](pcodec-native.md) 已区分并定向验证 `pc_*` / `pcs_*` / `pcn_*`、f16 支持/拒绝、两种页限额及 IntMult 实际模式/体积回退。不是完整配置覆盖或正式资格。 |
| 19 Sprintz-FIRE · [发布验证](../../third_party/provenance/Sprintz-family/unique-validation.json) | 同归档的有界查询、编码恢复、旧回归与 sanitizer 历史证据详见 [Sprintz 合同](sprintz-fire-native.md)。 | 只补本工程的 typed V、封装、独立恢复和实际查询后端对照；并未以历史结果测试 TSBench 的多维布局、f64 位片、查询接口或性能。 |
| 85 Titchy · [发布验证](../../third_party/provenance/titchy-native/unique-validation.json) | `stream_c`、`example` PASS，含隔离运行。后续修复记录指出新增 indexed reader 与 file `read_at`。 | [本地 Titchy 合同](titchy-native.md) 已定向验证 `titchy_c_range` 的全容器校验、复用 reader 的点/bit/范围结果和打开/请求字节，以及原生 packet 背压、尾长和独立恢复；不以旧审计或逻辑读取量推断文件物理 I/O 与资格。 |
| 7 Gorilla · [发布验证](../../third_party/provenance/gorilla-native/unique-validation.json) | `test` 和 `stream` PASS，隔离记录只列 `test`。 | 不把历史 stream PASS 扩写成无原输入 snapshot 恢复、任意 seek、派生 T/V 或严格低首产出。已按[本地 T+V 对照](gorilla-tv-native.md)补毫秒双列恢复、边界位、append/snapshot/resume、iterator/forward seek；T/V 派生及正式执行仍待。 |
| 31 ZFP · [发布验证](../../third_party/provenance/zfp-native/unique-validation.json) | `array`、`features`、`OpenMP-field-workers` PASS；CUDA build PASS、runtime SKIP；隔离表列 array/features PASS 及 CUDA SKIP。 | [本地 ZFP 合同](zfp-native.md) 分开验证 field 四种模式与数组持久化，在指定 field 上统计原生 block 实际线程；不把结果外推到其他布局、并行解码、GPU 或正式资格。 |
| 40 Zstandard / 39 XZ · [共同发布验证](../../third_party/provenance/lzbench-native/unique-validation.json) | `features`、`api_test` PASS，含隔离运行。 | 不把两项摘要解释为同版所有配置均通过；[本地定向对照](lzbench-native-operations.md) 补 legacy 限制、session 背压和 reset、字典依赖以及进程隔离的原生 worker 计数。XZ 批插件另外验证了封装、边界和新进程恢复，未把会话或多线程算给批基线。 |
| 4 SElf* · [发布验证](../../third_party/provenance/elf-selfstar-native/unique-validation.json) | `stress`、`live` PASS，隔离只列 `stress`。 | [本地 SElf* 合同](selfstar-native.md) 补同列顺序学习、批/逐值位流对照、reset/replay 和异常拒绝；区分 `add` 写位、暂读值和 `finish` 后有效块。这不是首值时延或服务资格。 |
| 29 Huff0 · [发布验证](../../third_party/provenance/FiniteStateEntropy/unique-validation.json) | `test_features` PASS，含隔离运行。 | [本地 Huff0 合同](huff0-native.md) 分开对照 FEC1 和 ETB1，验证 1X/4X 与实际 BMI2-aware 入口，区分历史 portable、冻结默认 dynamic 和本机实际执行；ETB1 没有 CRC，不由形状或模型可加载推出资产身份。 |
| 87 PBEPLA-RR · [发布验证](../../third_party/provenance/tsbenchmark-algorithms-native/unique-validation.json) | `fix_ReWrite` 功能报告与归档报告相同，列 `api_test` PASS；归档绑定的发布验证另列 `features` PASS，隔离只列 `api_test`。 | [本地 PBEPLA-RR 合同](pbepla-native.md) 定向验证有限 f64、各级原域误差、独立前缀、callback 源遍数和暂存逻辑字节。`features` 不证明逐层误差；多遍 replay 不算在线流，也不授正式资格。 |
| 80 CORAD · [发布验证](../../third_party/provenance/corad-native/unique-validation.json) | `fix_ReWrite` 功能报告与归档报告相同；`test_model`、`training` PASS，且隔离有同名记录。 | [本地 CORAD 合同](corad-native.md) 分开验证冻结模型推理、C11 LARS/CD 和原样 sklearn Source 训练桥，用不交叠的训练窗及留出窗验证，不以历史摘要推断等价或误差保证。 |

原件中的来源工程名、旧路径、PASS/跳过理由照原样保留；不重写成 TSBench 证据。当前没有任何
一条历史记录直接授予首批选定实现、36 个原生操作组、204 个服务格或 264 个原子关系正式运行资格。
