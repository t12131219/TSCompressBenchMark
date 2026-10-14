# TSBench

基于现有36个真实CPU codec key与真实cuSZp GPU扩展的独立Python benchmark。已完成CPU核心1092／1092、真实对象3192／3192和PeMS三维对象756／756正式trial；各组绑定自己的源码、输入和环境身份。GPU原参数保留378个成功trial及126个质量资格拒绝后的not_run槽位；显式90% native参数的四组run共840／840成功。修复安装构建后，新的GPU控制面检查另完成28／28，不替代原矩阵。结果与测试见[实施报告](docs/implementation.md)、[GPU结果](docs/gpu_results/README.md)、[PeMS结果](docs/pems_results/README.md)和[当前证据索引](docs/current_evidence.json)。设计见 [工程实施总计划](TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md)，模块及流程见 [框架图](docs/diagrams/README.md)。运行包位于 `benchmark/`，新目录和文件不附加 `_v4` 或 `-v4` 标记。旧raw保留原身份，后续修正使用新run验证。

测试对象是声明 dtype、shape、layout 和恢复语义的 V / T / mask；当前 wire 版本2校验恢复descriptor与payload，兼容读取历史版本1。保存的 wire 包含独立恢复所需 descriptor、payload、chunk / channel 目录和必要依赖。默认 CPU 边界为 `object_memory`：每次对象创建独立 codec session，编码包含 Finish 和完整 wire，解码从 wire 创建新 session；计时外逐轮验证恢复及输入未被修改。`stored_bytes` 是实际完整 wire 长度。

收尾后的完整suite在Python3.11／NumPy1.24与Python3.14／NumPy2.5两个本机软件环境均 **308 passed**；[日志与JUnit索引](docs/current_evidence.json)保留实际结果。测试与正式性能测量分开执行。

Python 要求为 3.11 或更高，核心依赖只有 NumPy。原生构建需要现有资产配方所指定的 C/C++ 编译器、CMake 及相关开发库。直接从仓库运行即可：

```bash
cd ~/PycharmProjects/TSDataCompressBenchMark
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
python benchmark/examples/generate_fixtures.py
python -m tsbench build zstd-frame lzss-raw
python -m tsbench inspect benchmark/examples/minimal.toml
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

[直接 native 交叉核对](docs/research/native_crosscheck.md) 用独立 C 程序与 Python bridge 比较 Zstd / LZSS 的最终 payload、恢复 bytes 与 ABI buffer 大小，证据可复跑。其 `native_api_diagnostic` 时间与对象边界分别标明。

现有资产按真实能力接入：ALP／ALP-RD是forced scalar方案；SIMDComp是uint32 primitive；Sprintz是整数矩阵路径；ABBA／fABBA是经验质量方案；DeepZip现有模型仅支持0..3符号；DZip有持久Eigen workers，按实际资源层运行。库、ISA、dtype、长度、源域或资源条件不满足时明确记录原因。cuSZp-fixed-1d 已在宿主 RTX2070 上完成 48 个成功资格样例、48 个独立 decoder 和 30 个预期拒绝；P4 两个 synthetic formal run 已保存 host_to_host 与 device_resident 结果。严格原始域质量检查保留 f32 大输入的 quality_violation，因此对应槽位为 not_run，不能用成功子集冒称完整矩阵。宿主只读检查见[GPU宿主探测](docs/research/gpu_host_probe.json)，stream／query／energy在本项目没有性能主张。

清理后只保留算法/native/model 资产、来源与许可资料、V4 研究和架构说明，以及新框架所需文件。旧框架、旧结果、旧资格台账和历史架构不会参与新运行。保留的旧 codec capability/source JSON 作为资产资料；新 build、资格和测量证据独立生成。

本机的实测表、原始结果和图表入口见 [实施结果](docs/implementation.md)。当前源码身份下的 CPU 核心重跑位于 `runs/current-core-20261013/`，真实对象正式结果位于 `runs/current-real-20261013/`，GPU 正式结果位于 `runs/gpu/cuszp-formal-*`；真实对象只读配对分析见 `docs/real_object_results-current-20261013/`。目录统一为 `benchmark/`、`build/tsbench/`、`runs/`；迁移前测量的 manifest／raw 原字节保留，[路径映射](docs/path_relocation.json)解释历史路径。迁移前的运行可重新出报告，继续测量应使用新运行目录。

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
