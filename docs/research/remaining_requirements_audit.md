# V4.0 未完成项审计与继续执行清单

本审计依据 [V4.0 工程实施总计划](../../TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md)、当前源码、registry 和本轮完成的 manifest/observations 编写。CPU current-core、真实对象五组run、PeMS rank3扩展和cuSZp原始／margin90／真实单列formal run已产生结果；资格、正式测量和只读分析仍具有不同身份，不能用其中一种证据替代另一种。历史记录保留自身source／环境身份。

## 本机工程关闭判断

**本机“搭建框架、现有 codec 在其资格与约束下跑通并得到 bench”目标已有完整证据，可以验收；全论文研究覆盖与独立复现仍有未覆盖项。** CPU 36/36真实key在当前对象框架下至少完成一个合资格正式case；本轮核心1092/1092、真实对象3192/3192、PeMS rank3扩展756/756，GPU独立margin90／真实单列840/840；原始GPU严格质量拒绝与各codec的unsupported请求仍保留。完成判断针对已声明对象、参数、资源和边界，不表示所有理论域或所有扩展均支持。

该判断依据计划的具体适用规则：§5.2默认standalone，另做shared须实际移出依赖；§11.1没有受控scalar变体时明确记录不可做；§12 P4要求真实能力及无能力明确拒绝；§13.1 stream/query/downstream/energy仅对具体声称的任务必需；§13.1也说明新方法/模型依赖不成为其他已可运行实验的全局门槛。不能把20–40个更广来源、一个新shared格式、另一个CPU/OS或第三方的工作不断追加为“工程不能结束”的条件。计划§1–§13的研究目标仍有效，未完成研究项以限定主张处理。

本次确实发现并修复两个本地安装构建缺陷：installed `build.py`错误把自身路径当asset-root相对路径；缺registry／空native选择使 `build --all`返回空成功。修复只修改 [build.py](../../benchmark/src/tsbench/build.py)，已安装包的配方源采用明示 `package:tsbench/...` label、真实source_path和hash，checkout内的源标签仍相对asset root；缺registry或空选择抛Unavailable，已有CLI非零返回。8项[针对性测试](../../benchmark/tests/test_build.py)包含实际wheel构建／安装、仓库外包路径、临时真实Zstd源码checkout的全新native编译，以及新解释器仅凭实际wire和安装roots恢复 `(257,3)` `<f8>` 位元。最终留存测试8/8通过、14.30s，见 [JUnit](tests-build-installed.xml)、[日志](tests-build-installed.log)及 [installed_build_verification.json](installed_build_verification.json)。测试窗口UTC 11:47:51.940–11:48:06.239，早于后续GPU smoke run的created_at_utc 11:51:47.749，无正式计时重叠。这是正确性与构建验证，没有正式计时，也未覆盖/替换当前native builds。

CPU具名execution closure排除build.py，已有current-core source ID仍相同；GPU自己的控制面闭包显式包含build.py，因此这项builder修复使**未来GPU** source ID成为新身份。按实际 `root=Path.cwd()` 参数、包括GPU registry card的完整19源闭包，新ID为 `sha256:1e37ea146c0e477862fc732278ab1394162c5c9cc5dcf7eb90a6ed63f4c56cd1`；与旧GPU manifest的同路径同成员比较只有build.py变化，见 [GPU后续准备](../../benchmark/experiments/gpu-builder-check/preparation.json)。不传root得到的部分闭包ID不是实际run身份。旧GPU run仍保留各自冻结source snapshot、raw及运行结束时的source_unchanged=true；不修改闭包排除表，不把旧run回填为新身份，也不因与CUDA计时无关的builder路径修复再制造全部历史formal数。新身份的有限GPU smoke属于独立后续证据，不能替代原四轮正式证据。

## 共享依赖：接口支持与底层原语分开

当前 [ObjectScheme](../../benchmark/src/tsbench/schemes.py)只生成standalone，`dependency_policy`明示RW native frame包含模型；[rw_decode](../../adapters/completed_rewrites/native/binding.hpp)只接收frame与输出buffer，没有dependency resolver或外部model参数。当前配置没有能直接运行的shared-scope开关。完整wire已真实收费；这一点已完成，不应把无法使用的模式写成漏计成本。

| 保留实现 | 当前完整产物的依赖事实 | 已登记shared模式 | 在本机能做的有限工作 |
|---|---|---|---|
| DeepZip | [DZCPP001](../../adapters/completed_rewrites/vendor/deepzip/src/deepzip.cpp)写入alphabet与完整serialized model；decode从frame加载模型。相同model_key可重复嵌入相同模型，当前仍按每frame计费 | 无；完整decoder没有外部model入参 | 只读解析真实frame的model/alphabet/length/checksum字节账单；若另做按hash抽出／重组真实frame的共享集合scheme，须实际保存sidecar并独立恢复，不能只减去账面模型bytes |
| DZip | [DZCP0001](../../adapters/completed_rewrites/vendor/dzip/src/codec.cpp)实际存compressed model、alphabet、mode、length与payload；decoder恢复所存模型 | RW1无；底层确有 [encode_raw/decode_raw](../../adapters/completed_rewrites/vendor/dzip/include/dzip.hpp) 接收外部Network的真实原语 | 可以另接具名raw-payload adapter与集合dependency格式；必须固定模型／alphabet mapping、保留mode/length/profile与hash、每对象独立初始状态及scope总账。当前seeded模型也依赖实际alphabet，不能假定所有frame相同 |
| ABBA / fABBA | [ABBA](../../adapters/completed_rewrites/vendor/abba/src/canonical/abba.cpp)与[fABBA](../../adapters/completed_rewrites/vendor/fabba/src/canonical/fabba.cpp)按本对象得到codebook，并写入centers与symbols；可核实header + 16×centers + 2×symbols + checksum | 无；现有encode没有外部固定codebook入参 | 只读拆分既有codebook成本。跨对象复用聚类codebook是新方法/质量研究，不是给现有params补一个shared字段 |
| ALP-RD / ALP | [shim](../../adapters/alp/native/tscb_alp.cc)保存rowgroup局部dictionary／sample参数与必要exceptions；依赖由当前对象推导 | 无 | 按实际rowgroup解析成本；不把对象局部dictionary当固定全局共享数据 |
| Zstd | [wrapper](../../adapters/zstd_frame/native/tscb_zstd_frame.c)明示dictionary NONE；vendored [Zstd API](../../adapters/zstd_frame/vendor/zstd/lib/zstd.h)有真实load/ref dictionary与相应decoder入口 | 当前wrapper无；底层API有 | 若RQ2确实需要真实字典shared对照，单独接入具名字典variant，冻结开发集字典bytes/hash与scope；standalone和shared分别实际恢复并计完整字典、索引、header成本 |
| Brotli / LZSS / XZ等 | built-in static dictionary、固定初始窗口、内部LZMA2 window分别属于已有格式/程序契约，没有当前外部字典数据文件 | 无 | 保持其当前声明与完整成本；不因名称含dictionary就建立免费共享依赖 |

这些后续工作不需要第二台机器，但**需要新scheme／adapter、格式与资格证据**，不是现有benchmark漏掉一个可直接测的参数。若只需关掉工程scope，报告`not_supported_by_registered_interface`即可；若继续某个RQ，优先选一个来源明确的DZip raw原语或Zstd字典API，不要求把36个codec全部改造成shared。只读账单可以先完成，模型文件hash和框架完整wire hash仍保留；任何摊销必须基于真实外置文件，不能提供假想shared压缩率。

## scalar / SIMD / 线程：当前合法网格

| 条件 | 现有接口实际支持 | 关闭结论与有限后续 |
|---|---|---|
| SIMDComp | 同一MASKED API的SSE4.1与AVX2，已有12case/252trial及frame/flags/dispatch证据，见[ISA报告](../isa.md) | 可合法执行两条真实路径；无已登记scalar对应。128/256内部block、tail API等同时变化，不归因于单一向量宽度 |
| ALP、普通SCALAR成员 | 固定isa enum与已有实现；ALP采用forced方案、FastLanes scalar fallback，vendored源还含条件SIMD代码但没有已登记对应variant | 不能仅把isa字符串改为AVX2。SCALAR card或禁自动向量化flags也不证明全部依赖无显式intrinsics／dispatch。建立受控peer需新build/variant与operation证据 |
| Sprintz / LZSSE / DZip | 分别固定AVX2/BMI2/LZCNT、SSE4.1、AVX依赖；DZip数值运算包括会影响在线训练的向量sqrt等 | 不能直接编译禁ISA后冒称等价scalar。尤其DZip scalar算术可能改变模型演化与bitstream数值profile，需要独立方法/格式资格 |
| Native threads | [capability](../../benchmark/src/tsbench/schemes.py)严格要求普通scheme=1、含DZip=3；Zstd wrapper固定`ZSTD_c_nbWorkers=0`；DZip [cpu_ops](../../adapters/completed_rewrites/vendor/dzip/src/cpu_ops.cpp)有两个固定persistent单worker Eigen pools | 现有成员没有可变native thread knob。环境变量和profile线程数只是请求/限制，不产生合法线程scaling |
| Zstd底层MT | vendored API确有nbWorkers，但要求ZSTD_MULTITHREAD；当前配方没有启用它且wrapper固定0 | 本机可另接具名MT build/adapter；须记录caller/helper总预算、固定job/chunk geometry、Finish真正完成和实际threads。只修改profile不成立 |
| fABBA底层parallel_compress | [helper](../../adapters/completed_rewrites/vendor/fabba/src/canonical/fabba.cpp)有threads/partition/std::async；当前完整encode→transform实际调用串行compress，binding固定threads=1 | 放开threads字段仍不会使正式encode并行。helper按分区整数商处理并记录丢弃余数，且改变分段；不能直接用它宣称同对象完整恢复或原方案线程收益 |
| 外部object pool | [pool executor](../../benchmark/src/tsbench/pool.py)合法workers=1/2/4；同集合cold/persistent完整wall已有504/504结果 | 这是可继续跑的已有并行接口；受process×native线程预算限制。与内部线程和同进程调用分开，RW无损shim的全局锁不能靠GIL释放消除 |

若确实需要这些对照在本轮执行闭包下另有身份，有限复跑入口是下列两个新output；原结果保留。这是可选当前身份对照，不是新增codec工程的先决条件，执行时仍须串行独占正式计时窗口。本次审计没有运行它们：

```bash
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/isa-paths/experiment.toml --output runs/current-isa-scope-followup
PYTHONPATH=benchmark/src python -m tsbench.pool benchmark/examples/pool.toml --output runs/current-pool-scope-followup
```

## 最短收尾范围与外部条件

有限PeMS rank3扩展已经完成，见[结果说明](../pems_results/README.md)、[manifest](../../runs/current-pems-20261013/pems-values/manifest.json)与[observations](../../runs/current-pems-20261013/pems-values/observations.jsonl)：4个作者processed NPZ、12个原生对象，固定start=1024、length=128/512/8192、无dtype/rank转换；48请求中36个ready／36个可执行case完成、12个chimp128 rank3明确unsupported。48请求网格对应1008 nominal slots；实际schedule只有36个ready case的756槽，756/756正式terminal全部ok，bitwise及input_unchanged均通过，实际槽位与schedule完整一致。冻结[preparation.json](../../benchmark/experiments/pems-values/preparation.json)保留测量前的pending身份；成功结论来自实际run，不回填准备文件。

36个可执行case各有一次实际独立subprocess的exact-input wire-only恢复，记录passed、decoder_returncode=0、artifact hash、restored object ID、verification与decoder_runtime；没有保存decoder_pid、execution_provenance、native_diagnostics或effective_profile，不补造这些字段，也不把admission profile当作独立decoder或每轮的已保存观测。case admission为affinity `[0..15]`、1 native thread／1 object worker、4GiB RLIMIT_AS。run级UTC窗口是11:52:44.479456–12:02:02.915135，晚于installed tests日志结束11:48:06.238716，二者无重叠；没有per-trial绝对UTC，不据此声明每个trial的绝对起止。

作者固定ref为 `9c2e19b98c4cedf1f35214d8789685b6381b3aad`，本地blob/长度匹配，见[来源研究](additional_data_sources.md)及[获取与校验路线](../pems_acquisition.md)；本地formal成功不证明新获取器已实际下载远程四份NPZ。这些processed文件的许可仍unknown，不用一般网站政策或其他primary数据的许可替代。来源先前已接触，窗口还存在前缀重叠，不能称blind或独立总体抽样。n8192的logical输入分别23,461,888／60,358,656／57,868,288／33,423,360bytes，大于cpu0 sysfs记录的共享L3 20,971,520bytes；这只是容量对照，没有实际cache状态或性能因果证据，也未完成20–40源研究覆盖。

| 项目 | 分类 | 机器可执行的下一步 / 停止条件 |
|---|---|---|
| 本地build入口两个真实缺陷 | 本机工程修复，已完成 | 执行`PYTHONPATH=benchmark/src python -m pytest benchmark/tests/test_build.py -q`；已实际8/8通过，包括installed wheel的真实编译与独立恢复 |
| 本轮包／raw／表图／获取路线的交付索引 | 本机工程收尾 | 汇集已存在的current_evidence、真实对象/GPU summary、source/build/runtime/配置和测试hash；索引正确关联冻结身份即可停止，不触发所有codec重测 |
| 可下载依赖lock／本地离线bundle | 本机可完成的发布准备 | 当前environment inventory不是可下载lock。若交付目标包含从零安装，保存选定wheel/sdist及hash、asset/source清单和许可；不可再分发的CSV只保留获取路线与hash。已有纯Python安装验证不等于完整投稿包 |
| Native model/codebook disjoint字节账单 | 本机可完成的纯分析扩展 | 对保存代表wire解析上述真实格式，逐区间hash并校验各分项之和=full wire；不运行codec、不扣实际未外置的依赖。不是框架运行缺陷 |
| 新shared / native MT / scalar variant、更多公开来源 | 本机可开展的新研究范围 | 每次只选择一个具体variant/source/RQ，冻结scope后重新资格；不自动列为本轮工程验收阻断项 |
| 第二物理机、不同OS/ISA、独立第三方 | 外部实验条件 | 同机换Python/NumPy已完成“第二软件环境”；实际第二机器和第三方执行须获得对应资源/参与者，本机不能生成或伪称完成此证据 |
| 许可补足、工业私有语料、通用OOM后GPU恢复或可强制VRAM cap | 对应外部权利／新能力/特定实验 | 保留unknown/unavailable/unsupported及范围。当前executor在恢复不确认时停止，不要求注入真实kernel fault或重置整设备来验收正常对象路径 |

停止条件是当前固定配置能生成可独立恢复、严格验证、完整收费、来源绑定及可重算的真实bench，已检测的入口错误修复，并完整披露未支持能力。本轮达到该工程条件；其后的广域论文覆盖按具体研究请求开展，不给本机验收附加无限扩展门槛。

## 已有证据

- CPU 主路径、36 个真实 CPU codec key、raw-store 参考、typed wire、独立 wire decoder、失败分类、缓存、resume、运行库绑定、时间戳 affine scheme、records 组合、ISA 路径、外部进程池和第二 Python/NumPy 环境均有历史 run 与 raw hash。历史 CPU 主实验报告 1092/1092 trials；三源 study 报告 2772 trials；第二软件环境报告 924/924 trials；边界对照 252 组；外部进程池报告 504/504 集合操作。它们各自绑定当时源码和实现身份。
- 当前 [CPU current-core](../../runs/current-core-20261013/) 六组共1092/1092成功：无损833、timestamps affine28、ABS63、经验质量28、records35、三源pilot105。36个真实CPU key均有合资格case；当前身份结果与旧六组分开保存。
- 当前 [真实对象五组 run](../../runs/current-real-20261013/) 完成152/152请求、3192/3192正式trials；[只读分析](../real_object_results-current-20261013/summary.json)保存120个scheme pairs、60个layout pairs、完整分母和逐trial溯源。
- 当前[PeMS rank3扩展](../pems_results/README.md)完成36/36可执行case、756/756正式trials与36次fresh subprocess wire-only恢复；12个Chimp128 rank3 unsupported请求保留。恢复记录字段与run级时间范围的限制见上文，不能用本次四个同发布体系文件推导广域总体结论。
- 当前保留实现已完成真实 cuSZp 1D FIXED GPU 资格：48 个普通样例、48 个 fresh decoder、30 个预期失败子进程、0 个意外错误；主/子进程 checked allocation、stream、event 计数平衡，实际 binary/runtime hash 已核对。证据见 `docs/research/cuszp_qualification_20261013.md` 和 `runs/cuszp-qualification-20261013-v2/qualification.json`。这不是吞吐结果，也没有证明 kernel fault/OOM 后设备恢复。
- 当前 CPU/GPU provenance、foreign-run、精确 schedule、来源变化锁存和独立 decoder 进程组清理的修订已进入最新源码；任何修订过的执行闭包都不能回填旧 run 的实现身份。
- 两组cuSZp formal各保留252个预定slots：[ABS=0.01](../../runs/gpu/cuszp-formal-0p01-20261013/) 为168 `ok`、84 `not_run`／`quality_violation`；[ABS=0.1](../../runs/gpu/cuszp-formal-0p1-20261013/) 为210 `ok`、42 `not_run`／`quality_violation`。f32严格原始域质量拒绝不是crash、OOM或设备不可用；两组均不能标记为complete success。
- 新的margin90方法将native bound显式设为task bound的90%（0.009／0.09），task原始域ABS仍为0.01／0.1。[synthetic 0.01](../../runs/gpu/cuszp-margin90-0p01-20261013/)和[synthetic 0.1](../../runs/gpu/cuszp-margin90-0p1-20261013/)各252/252成功；[真实单列f64 0.01](../../runs/gpu/cuszp-real-f64-0p01-20261013/)和[真实单列f64 0.1](../../runs/gpu/cuszp-real-f64-0p1-20261013/)各168/168成功，来源为ETT OT／weather T(degC)的128／512点一维投影。四个新run的source／native unchanged均为true；这些是新参数方法的结果，不覆盖原strict失败，也不是多变量GPU实现。
- `plot_results.py` 已接入公共 `scheduled_rows`／`case_coverage`：重复terminal、重复schedule、unscheduled和foreign-run拒绝，source drift不计complete；原始物理行号与行hash保留，trace另记录analysis helper hash。分析修订不改写原manifest／raw，也不触发codec测量。
- 本轮plot／公共分析回归为37 passed／1.49s，覆盖 `test_plot_results.py`、`test_analysis_integrity.py`、`test_report_schedule.py` 和 `test_study.py`；只使用合成保存记录，未运行codec、build或绘图。该测试耗时不是benchmark性能。

## 本轮完成的固定对象与 GPU 运行

### 真实 ETT/weather 对象

`benchmark/experiments/real-objects/` 已冻结 5 份配置、152 个请求、3192 个名义 trial（每个请求 3 sessions × 7 rounds），数据画像包含全源词法精度、binary64 数值统计、时间差、缺失/特殊值计数和 exact object identity。评价窗口是两个源共同的 `[2048, 2560)`，长度 128 使用其前缀；这避免了旧性能窗口 `[1024,1536)`，但全文件已经解析和画像，因此不能称盲测。

配置覆盖：

- 同步 MTS values：ETT 全 7 通道、weather 全 21 通道，C/F 布局；raw-store、zstd-frame、chimp128，以及 Zstd 的 channelwise、64-row、256-row 和 channelwise+64-row 消融。
- timestamps：原始日期按 naive wall-clock 相对 epoch 的 int64 纳秒；raw、Zstd、raw/NeaTS/LeaTS 加显式 `integer_affine_gcd`。bias/scale 进入 wire，验证仍在原始纳秒域；不能把它解释为直接 NeaTS/LeaTS 已支持任意 epoch-ns。
- records：V 与真实 T 的完整组件组合；组件 route、chunk 和 channelwise 方案按各自 wire 成本计费。
- ABS 温度：ETT `OT` 与 weather 的三个 `degC` 列，只使用 Serf-QT、Serf-XOR、ZFP，界限 `0.01` 与 `0.1`。不同物理单位不共用同一语义误差尺度。

`docs/data_characterization/component_pairing.json` 已重新读取并验证 32 个对象描述；C/F 是相同 C-order 组件 bits 的布局干预，但 raw_object_id 有意不同。`benchmark/tools/analyze_real_objects.py` 只读原始 run，按完整 task/profile/boundary/lifecycle/cache/implementation/runtime 条件配对，保留最早失败、retry、foreign-run、schedule 和 observation line，不给总体赢家。

5个CPU run和只读paired analysis已完成，正式trial分组为1176／420／840／378／378，合计3192/3192成功。分析实际形成120个scheme pairs和60个C/F layout pairs。32个对象描述对应26个canonical object IDs，仅来自两个固定来源；C/F配对和嵌套窗口不增加独立来源数。

### GPU P4 正式网格

原始GPU formal网格是项目生成的 `<f4>/<f8>` 一维 synthetic fixtures，长度33、32769、1048576；两份ABS配置各12 cases（6 datasets × 2 boundaries），各自252预定slots，合计504。实际378个slots `ok`、126个slots因exact-input质量拒绝为`not_run`；未完成case的性能保持null。它覆盖partial tile、32768 tile边界和大对象。后续margin90 synthetic两组各252/252成功；真实ETT OT／weather T(degC)的f64一维128／512点两组各168/168成功，补入有限真实来源GPU证据，但仍不代表多变量GPU覆盖。`host_to_host`与`device_resident`分开报告。

GPU资格和formal运行均已保存admission、独立fresh decoder、requested/effective/actual bound、原始域质量、host/device完成边界、完整persisted wire、资源／映射／source hash以及failure/not_run分母。f32失败仍按严格quality policy保留；不能用放宽容差或成功子集改写完整网格。明确的VRAM上限目前不可实施；任何配置请求VRAM cap都应unsupported。OOM、kernel execution fault和失败context recovery仍未由资格suite注入证明。

## 覆盖状态与剩余计划要求

以下记录完成范围和广域论文主张边界；新增shared、物理环境或具体任务只有在选定对应研究范围时才需新证据，不追加为当前本机工程验收的门槛。各项事实不能由“36个key”“CPU 504集合操作”或“GPU接口已存在”替代：

1. **当前实现身份下的CPU主矩阵复跑：已覆盖本轮固定矩阵。** `current-core-20261013` 六组1092/1092成功，保存各自admission、资格和正式测量。旧manifest/observations保持原样，不能用新结果改写其身份或失败。
2. **真实对象正式结果：已覆盖本轮固定网格。** ETT/weather的152-request grid已经完成3192/3192trials、独立wire recovery和只读paired summary；这不等于广域语料或两个来源的总体代表性。
3. **真实GPU性能结果：已覆盖固定synthetic和真实单列，仍有限制。** 原始两组synthetic formal分别168/252与210/252slots成功，其余因严格f32 `quality_violation`未运行；独立margin90两组各252/252成功，真实ETT／weather单列f64两组各168/168成功。native bound减为task bound的90%，task严格ABS保持不变；原始失败和新方法身份分开保存。仍没有多变量GPU／真实来源f32全域证明。GPU运行若出现设备恢复不确定，仍必须停止后续槽位并写`not_run/device_recovery_unconfirmed`，当前质量拒绝不能误写成这种设备故障。
4. **更广的独立时序来源。** 当前ETT、weather、national_illness及新增PeMS仍是有限选择。PeMS四份作者processed NPZ、12个rank3对象已正式完成，包含8192行大窗口；它们属于同一采集／发布体系、嵌套窗口且已有暴露，不能支持广域domain、独立总体抽样或20–40源覆盖结论。更广工业IoT、能源、生理、业务监测等研究尚未冻结；weather预处理CSV、ILI与精确PeMS processed文件的许可未知项继续保留，不能打包或扩展授权主张。
5. **共享依赖/模型成本消融。** 当前 standalone wire 对已声明依赖收费；尚未有显式 shared-scope 的模型/字典摊销实验，也不能把 native frame 内嵌依赖当作免费共享。
6. **可变 native 线程与受控 scalar/SIMD 因果对照。** DZip 的固定内部线程契约、SIMDComp 的实际 SSE4.1/AVX2 路径和外部进程池已有证据；没有一般 codec 的受控 scalar 版本或可变内部线程 scaling，不能从 `native_threads` 配置推导算法线程收益。
7. **跨物理环境复现。** Python 3.14/NumPy 2.5 是同机第二软件环境，不是第二机器、OS、ISA 或第三方独立复跑。计划要求的多机器/OS/ISA和独立第三方复现仍未完成。
8. **stream/query/downstream/energy。** 当前框架只对具体 object encode/decode 声称完成；没有真实 push/finish、checkpoint/query、下游预测/分类、能耗或端到端工作负载结果。普通压缩 wire 结果不能推导这些能力。
9. **上游算法总体等价与论文覆盖。** registry 保留 36 个具名实现/变体，但 ALP、SIMDComp、DeepZip、fABBA 等均有已声明实现限制；已有结果只适用于冻结 adapter/build/input 条件，不能外推为 upstream 全域或理论算法总体排名。TerseTS/FCBench 等相关工作的强竞争方法尚未形成同一对象/边界的完整对照套件。
10. **论文复现包与数据发布限制。** 当前 hash、获取脚本、resolved config、schedule、raw JSONL、代表 artifacts 和分析代码已具备主要骨架；尚未形成可宣称完整投稿包。不可再分发数据只能提供来源、许可证范围、获取路线和 SHA-256，不能复制到仓库。

## 后续研究执行顺序（不影响本机验收）

1. 本轮core、real-object、PeMS与GPU结果已保存，保持各run的source closure／native build／runtime身份和精确schedule。若有新的执行源码变化，应新建run，不resume旧实现；分析修订只生成新的analysis记录。
2. 保留152-request／3192-trial真实对象完整分母和120／60配对条件。未来新增来源先冻结source/license/window/parameter grid，再做qualification和formal pass；C/F只作为布局配对，不合并raw_object_id，也不增加独立source数。
3. 对GPU严格f32质量拒绝保留requested／effective／actual bound，查阅原生算术与roundoff证据。margin90已经独立声明并完成资格／formal，task strict policy保持不变；如果再新增输入域约束或新的参数，继续使用新方法／run身份，不能覆盖本轮失败，也不能从当前成功外推任意浮点输入。
4. 新GPU实验仍分开报告host/device boundary，核对source unchanged、foreign-run、精确schedule、独立decoder、实际runtime和resource counters；不能把`device_event_ms`当host completion或把source-accounted allocation peak当VRAM peak。VRAM限制和OOM／kernel fault恢复需独立证据。
5. 若选定继续某个具体RQ，再冻结共享模型、线程/ISA、跨物理环境或具体声称的stream/query/downstream/energy范围。所有结果按source/domain层级描述，不以有限同源窗口的bootstrap代替总体推断；未明许可的数据只提供核实过的获取路线和hash。

本轮固定CPU、真实对象和PeMS rank3扩展已完成，GPU已有synthetic和有限真实单列formal结果，原始网格仍保留质量拒绝。本机工程目标已经达到；更广来源、依赖成本、资源控制与独立复现按另行选定的研究范围推进。其余能力保持显式“未覆盖”，不因接口占位、synthetic qualification或成功子集提前标记完成，也不继续给当前验收增加门槛。
