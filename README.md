# TSBench

**当前排除项（2026-10-17）：** `lzss-raw`、`lzss-dipperstein-c` 已标记为“算法接入异常，处于排除状态”，禁止在所有 Benchmark 边界使用。当前可用真实CPU codec为42个，另加raw-store；LZSSE2／LZSSE8保持可用。源码与历史结果保留，详见[排除记录](docs/lzss_exclusion_20261017.md)。以下历史性能数字保留原实验身份。

**默认目标：codec原生性能（2026-10-15修订）。** Python负责数据准备、调度、资格与结果收集，C/C++ driver内部循环直接调用codec并计时；默认`native_core / prepared / natural`。`native_api`适配器测量与`object_memory / independent_object / natural`完整对象目标保留为辅助配置。37／37个真实CPU codec构建成功，加上driver提供的raw-store，38个key均在prepared与fresh_request下完成合法direct core案例；最终完整suite **715 passed**，无失败、错误或跳过。

主表给同任务／dtype／布局／有效数据量的压缩倍数、bits/value与原生编解码吞吐。codec必要header／参数／模型／索引／finish计入输出；框架JSON／hash／来源及纯ABI envelope另列。padding／ABI头／重复共享T不扩大分母。prepared与fresh_request分列，每份真实产物计时外验证，失败和不支持保留请求分母；无法核实完整输出时主空间指标为null，不估计扣除。

当前全CPU原生矩阵的28份冻结配置串行完成：**358请求，348 ready、10 unsupported；4872／4872正式trial成功，额外尝试0**。统一只读审计通过，核对48216对正式阶段压缩／恢复产物记录（含9744对warmup）及3444对exact资格产物记录。每个key均有两个生命周期共同输入的完整合法案例，覆盖不扩大其dtype、源域、质量或资源保证，也不构成跨任务总排名。结果和逐请求原因见[全量原生结果](docs/all_core_results/README.md)、[完整证据索引](docs/all_core_evidence.json)及[实施报告](docs/implementation.md)。

基础24份配置中的64符号DeepZip／DZip短流不执行神经预测或训练。另4份补充配置使用完整257符号，覆盖DeepZip biGRU及DZip BOOTSTRAP／COMBINED；每次完整编解码各有193次源码推导的预测，COMBINED含1个128-window训练batch、1次Adam更新及更新后65次预测。完整模型与必要参数计入输出，DZip输入相关初始化及在线更新均在编码内。这些次数不是动态counter或独立性能样本。

此前首阶段原生／API／对象对照保留为历史证据：**792请求，181 ready、611 unsupported；2534／2534正式trial成功**，当时的direct core仅为raw-store／Zstd／LZ4-frame／Snappy。36个真实CPU codec的辅助API覆盖不等于当时已有36个direct core；未知完整输出大小的API仍为null。其结果、图表与旧身份见[首阶段原生结果](docs/native_results/README.md)、[首阶段证据索引](docs/native_evidence.json)。

以下为保留的历史对象／GPU结果。基于现有37个真实CPU codec key与真实cuSZp GPU扩展，历史CPU核心1092／1092、真实对象3192／3192和PeMS三维对象756／756正式trial已完成；各组绑定自己的源码、输入和环境身份。GPU原参数保留378个成功trial及126个质量资格拒绝后的not_run槽位；显式90% native参数的四组run共840／840成功。修复安装构建后的GPU控制面检查另完成28／28，不替代原矩阵。见[GPU结果](docs/gpu_results/README.md)、[PeMS结果](docs/pems_results/README.md)和[历史当前证据索引](docs/current_evidence.json)。设计见 [工程实施总计划](TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md)，模块及流程见 [框架图](docs/diagrams/README.md)。运行包位于 `benchmark/`，新目录和文件不附加 `_v4` 或 `-v4` 标记。旧raw保留原身份，后续修正使用新run验证。

新增 **Gorilla（Prometheus XOR）** 的 C++17 接入已恢复并重新验收：完整 suite **343 passed**，专项在两个 Python 环境各 **35 passed**，真实 records 实验 **24/24 case、504/504 trial** 全部通过。实现与范围见 [Gorilla 接入报告](docs/gorilla_integration/README.md)，用法见 [示例](benchmark/examples/gorilla_records.toml) 和 [真实输入实验](benchmark/experiments/gorilla/records.toml)。

测试对象是声明 dtype、shape、layout 和恢复语义的 V / T / mask；当前 wire 版本2校验恢复descriptor与payload，兼容读取历史版本1。保存的 wire 包含独立恢复所需 descriptor、payload、chunk / channel 目录和必要依赖。保留的显式对象 CPU 边界为 `object_memory`：每次对象创建独立 codec session，编码包含 Finish 和完整 wire，解码从 wire 创建新 session；计时外逐轮验证恢复及输入未被修改。`stored_bytes`继续表示该历史／显式对象模式的完整wire长度，不代表codec_complete_bytes。

此前36个codec范围的完整suite在Python3.11／NumPy1.24与Python3.14／NumPy2.5两个本机软件环境均 **308 passed**；[日志与JUnit索引](docs/current_evidence.json)保留实际结果。测试与正式性能测量分开执行。

Python 要求为 3.11 或更高，核心依赖只有 NumPy。原生构建需要现有资产配方所指定的 C/C++ 编译器、CMake 及相关开发库。原生最小入口使用现有257×3 float64 fixture与raw-store／Zstd／LZ4-frame／Snappy四个direct codec入口。先构建codec和测量driver，再读取配置运行；默认示例省略boundary／lifecycle，解析为native_core／prepared：

```bash
cd ~/PycharmProjects/TSDataCompressBenchMark
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
python benchmark/examples/generate_fixtures.py
python -m tsbench build zstd-frame lz4-frame snappy-raw
python -m tsbench build-driver
python -m tsbench inspect benchmark/examples/native.toml
python -m tsbench run benchmark/examples/native.toml
python -m tsbench report runs/native-prepared
# 首次请求：含context创建、buffer分配和context关闭；保留产物最终释放在计时外。
python -m tsbench run benchmark/examples/native_fresh.toml
python -m tsbench report runs/native-fresh
```

[native.toml](benchmark/examples/native.toml)固定8个原生内循环、2个warmup循环、256 MiB保留内存上限；[native_fresh.toml](benchmark/examples/native_fresh.toml)显式设置fresh_request。每个batch内的真实产物和恢复结果均在原生时钟外验证，loops不当独立样本。上述四入口用于最小示例；当前38个key的direct core支持及合法输入分别冻结在[全量基础设计](benchmark/experiments/native-all/design.json)和[神经路径补充设计](benchmark/experiments/native-neural/design.json)，每个ready case均为2 sessions ×7 rounds。不支持的任务保留unsupported，不自动改为API或对象模式。通用C1／RW辅助native_api限单组件／无外部分块或transform、RW rank1，尚未审完的codec大小保持null；[首阶段六组结果](docs/native_results/README.md)继续保留原身份。

原有对象目标继续使用显式object_memory／independent_object配置，以下入口保留完整wire及对象处理时间：

```bash
python -m tsbench build zstd-frame snappy-raw
python -m tsbench run benchmark/examples/minimal.toml
python -m tsbench report runs/minimal-object-loop
```

`generate_fixtures.py` 生成固定seed、257行的不同dtype、特殊浮点bits、empty和records fixture，用于协议验证与开发。这些合成输入不能作为跨独立来源的论文排名证据。`records.toml` 展示T/V/mask完整成本，`corpus_pilot.toml` 展示三源CSV的显式解析和窗口。原始语料位于 `~/PycharmProjects/材料/TSBench_Corpus`；[数据说明](docs/data_sources.md)与[catalog](registry/datasets/catalog.json)已冻结精确获取、文件hash、解析和开发／评价分区，分别披露ETT／weather／ILI许可的已知及未知部分。仓库不捆绑原始CSV。

一份 TOML 声明 datasets、methods、task、profiles、execution 和 analysis。`npy` 保留自身 dtype；CSV 必须显式指定 `dtype` / `columns`，时间轴使用 `timestamp_column`、`timestamp_parser` 和 `time_unit`；`start` / `stop` / `step` 是声明的窗口。多数组 NPZ 用 `components = { V = "V", T = "T", mask = "mask" }`。未知配置或 codec 参数报具体错误，不静默 cast、量化、排序或插值。

```bash
python -m tsbench build --all
python benchmark/examples/generate_experiments.py
python -m tsbench run benchmark/examples/all_lossless.toml --output runs/reproduce-all-lossless
python -m tsbench run benchmark/examples/bounded_quality.toml --output runs/reproduce-bounded
python -m tsbench run benchmark/examples/empirical_quality.toml --output runs/reproduce-empirical
python -m tsbench run benchmark/examples/records.toml --output runs/reproduce-records
python -m tsbench run benchmark/examples/corpus_pilot.toml --output runs/reproduce-pilot
python -m tsbench run benchmark/examples/minimal.toml --resume
python -m tsbench run benchmark/examples/minimal.toml --retry
python -m tsbench profile runs/minimal-object-loop/manifest.json --interval-ms 10
python benchmark/tools/native_crosscheck.py
python -m pytest benchmark/tests -q
```

当前机器的 Conda `libstdc++` 缺少 DZip 所需的 `GLIBCXX_3.4.30`。显式运行库配置会在 worker 启动前加载指定库，并保存 worker／独立 decoder 实际映射的路径与 hash；不修改 Conda 或系统库。此机器的完整无损复跑配置如下，其他机器应使用其已安装、与构建兼容的库路径：

```bash
python benchmark/examples/generate_experiments.py --dzip-runtime-preload /usr/lib/x86_64-linux-gnu/libstdc++.so.6
python -m tsbench run benchmark/examples/all_lossless_runtime.toml --output runs/reproduce-lossless-runtime
python -m tsbench run benchmark/examples/timestamps_normalized.toml --output runs/reproduce-timestamps
```

`timestamps_normalized.toml` 将 `transform = "integer_affine_gcd"` 明确绑定到时间戳方法。偏置与整数 GCD 按 part 写入 wire，变换和逆变换均计入对象时间，完整长度计入变换元数据；资格及每轮验证均在原始纳秒域。原始 NeaTS／LeaTS 直接时间轴反例见 [失败分析](docs/research/neats_timestamp_failure_analysis.md)，新方法不赋予原生 codec 全 int64 域保证。

全资产实验分开三种恢复目标：`all_lossless.toml` 是 31 个现有无损 codec 与 raw-store 在六种 typed fixture 上的请求矩阵；`bounded_quality.toml` 是 Serf-QT、Serf-XOR、ZFP 的原始域 ABS=0.01；`empirical_quality.toml` 是 ABBA / fABBA 的实际误差曲线点。DZip 的三线程资源层单独声明，其他方法在该 profile 上明确拒绝；不能把它混入单线程排名。这些配置默认每可执行 case 为 1 session × 7 rounds、2 个独立 warmup objects，输出到 `runs/*-20261013`。

新构建输出进入 `build/tsbench/<build-id>`，保存真实配方、编译选项、source 与产物身份。每个 run 保存 `manifest.json`、append-only `observations.jsonl`、代表 wire 和描述报告。manifest 保存完整请求 case 矩阵、resolved 配置、实际 schedule 和环境；资格缓存复用 implementation suite / exact-input 的 PASS 范围。命中资格不会跳过正式每轮编码、独立 decoder session 和恢复验证。

状态为 `ok / unsupported / unavailable / error / crash / timeout / oom / not_run`。不支持的 case 保留原因，不伪造重复测量；恢复或质量失败的时间只作诊断。报告同时给完整覆盖、计划/完成数和成功条件下的 median / IQR，读取 raw 重生成报告不会运行 codec。resume 补未完成项，retry 创建新 attempt，原失败历史保留。

`profile` 使用同一 manifest 另开 pass。Linux 的默认 sampler 记录 profiling runner 及全部可观察子进程的 RSS、线程和 CPU consumed time，输出位于原 run 的 `profile/`。采样峰值是下界，RSS 求和可能重复计共享页；它是 run-level 总量，不是每 trial 峰值。主测量不启动该 sampler，profiling 时间不进入主性能摘要。

[直接 native 交叉核对](docs/research/native_crosscheck.md) 用独立 C 程序与 Python bridge 比较 Zstd / LZSS 的最终 payload、恢复 bytes 与 ABI buffer 大小，证据可复跑。其`native_api_diagnostic`仅为具名历史诊断，与新默认core和对象边界分别标明。

现有资产按真实能力接入：ALP／ALP-RD已替换为冻结safe-v1原生移植包（自适应ALP／forced RD，当前开放portable），接入范围见[ALP接入报告](docs/alp_integration/README.md)；SIMDComp是uint32 primitive；Sprintz已替换为独立原生发布包的Delta／FIRE及两种Huffman组合，8/16位、1–128维、最多64KiB，见[Sprintz接入报告](docs/sprintz_integration/README.md)；ABBA／fABBA是经验质量方案；DeepZip现有模型仅支持0..3符号；DZip有持久Eigen workers，按实际资源层运行。库、ISA、dtype、长度、源域或资源条件不满足时明确记录原因。cuSZp-fixed-1d 已在宿主 RTX2070 上完成 48 个成功资格样例、48 个独立 decoder 和 30 个预期拒绝；P4 两个 synthetic formal run 已保存 host_to_host 与 device_resident 结果。严格原始域质量检查保留 f32 大输入的 quality_violation，因此对应槽位为 not_run，不能用成功子集冒称完整矩阵。宿主只读检查见[GPU宿主探测](docs/research/gpu_host_probe.json)，stream／query／energy在本项目没有性能主张。

清理后只保留算法/native/model 资产、来源与许可资料、V4 研究和架构说明，以及新框架所需文件。旧框架、旧结果、旧资格台账和历史架构不会参与新运行。保留的旧 codec capability/source JSON 作为资产资料；新 build、资格和测量证据独立生成。

本机的实测表、原始结果和图表入口见 [实施结果](docs/implementation.md)。当前全CPU原生结果位于 `runs/native-all-*-20261015/` 与 `runs/native-neural-*-20261015/`；历史CPU对象核心结果位于 `runs/current-core-20261013/`，真实对象正式结果位于 `runs/current-real-20261013/`，GPU正式结果位于 `runs/gpu/cuszp-formal-*`。真实对象只读配对分析见 `docs/real_object_results-current-20261013/`。目录统一为 `benchmark/`、`build/tsbench/`、`runs/`；迁移前测量的manifest／raw原字节保留，[路径映射](docs/path_relocation.json)解释历史路径。迁移前的运行可重新出报告，继续测量应使用新运行目录。

PeMS保持原生三维 `<f8`、C-order、V-only，对4份固定来源取128／512／8192行的12个嵌套对象；36个合资格case完成3sessions×7rounds，12个Chimp128请求明确unsupported。来源版本与精确字节见[来源核查](docs/research/additional_data_sources.md)，重新取得或验证见[PeMS获取说明](docs/pems_acquisition.md)。四份文件属于同一采集体系；processed数据许可、单位与传感器映射仍未知，不能当四个独立物理总体。

安装构建支持仓库外的明确asset/build roots，缺registry或空native选择返回失败；实际wheel安装、新Zstd编译及仅wire的新解释器恢复已通过，[验证记录](docs/research/installed_build_verification.json)保留证据。当前wheel位于 `build/package-installed/tsbench-0.1.0-py3-none-any.whl`。本地源码与当前证据可按[复现说明](docs/reproduction.md)导出和逐文件校验；数据原文件不随包再分发，许可限制保留。

三源研究、进程池和native边界分别使用独立入口，避免将不同完成边界混入CPU对象表。已有输出禁止覆盖，复跑时使用新目录。三源研究的128点是512点前缀，ILI评价部分与旧pilot重叠；固定网格不称全新holdout。统计仅描述这3个选定source。

```bash
python benchmark/tools/fetch_datasets.py verify \
  --directory /home/fzg/PycharmProjects/材料/TSBench_Corpus \
  --manifest /tmp/tsbench-data-verify-new.json
python benchmark/tools/generate_study.py
python benchmark/tools/replay_environment.py \
  benchmark/experiments/cpu-study/*.toml --skip-build \
  --build-root build/tsbench --output-root runs/reproduce-study
python -m tsbench.study runs/reproduce-study/study-* --output docs/reproduce-study
python benchmark/tools/plot_study.py docs/reproduce-study/summary.json --output docs/reproduce-study/figures
python -m tsbench.pool benchmark/examples/pool.toml --output runs/reproduce-pool
python benchmark/tools/boundary_experiment.py --output-dir runs/reproduce-boundary \
  --preload /usr/lib/x86_64-linux-gnu/libstdc++.so.6 \
  --preload /home/fzg/anaconda3/lib/libgcc_s.so.1
```

[三源统计](docs/study_results/README.md)、[进程池边界](docs/pool.md)、[native边界](docs/boundary.md)、[SIMD路径](docs/isa.md)及[第二软件环境](docs/alternate_environment_results/README.md)各自列出配置、状态分母和原始证据，[完整证据索引](docs/completion_evidence.json)保存对应hash。选择另一已安装解释器运行 `replay_environment.py` 并使用新build／output root，可独立构建和复跑；同主机软件环境复现不表示第二机器／OS／ISA或第三方复现。以上系统运行库路径仅适用于本机，其余环境需声明本机实际兼容库。

2026-10-15 的原生实现覆盖当时 registry 的37个真实CPU codec及raw-store的直接入口，支持范围由逐任务资格、参数和资源约束限定；通用C1／RW原生API保留为辅助入口。具体contract和正式结果状态见[总计划§14.19–14.20](TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md)与[实施状态](docs/implementation.md)。所有新结果使用新run／source／build身份，保留旧对象配置及现存历史证据；用户指定的旧`build/reproduction-bundles/current-private-source.tar.gz`在当前checkout缺失，本轮未使用或验证该包。

2026-10-17：已将旧 Chimp / Chimp128 替换为独立 chimp-family 研究发布包，新增显式 32 位、N 窗口、no-index 和四种有损方法；该次接入后为45个真实CPU codec（另加raw-store）。10个新接入入口的源码差分、原生／对象冷恢复和本机安全验证见[接入报告](docs/chimp_integration/README.md)。这些新实现的正式吞吐未重跑，既有38-key性能报告保持原时点。

2026-10-17：旧Sprintz五个登记及接入代码已归档删除；当前仅保留新包的 `sprintz-delta`、`sprintz-fire`、`sprintz-delta-huffman`、`sprintz-fire-huffman`。目前共44个真实CPU codec，另加raw-store。完整1259项回归与96个绑定sanitizer案例通过；[接入证据](docs/sprintz_integration/README.md)和[示例](benchmark/examples/sprintz-family.toml)已保存，新实现正式性能未重跑。
