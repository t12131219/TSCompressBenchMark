# TSDataCompressBenchMark

TSDataCompressBenchMark 是一个以源码身份、输入契约和原始证据为基础的时间序列压缩基准框架。Python 控制面负责数据准备、能力协商、任务规划、隔离执行、性能测量与统计报告；具体算法通过原生适配器接入。项目比较的是明确声明的压缩对象、配置和执行路径，保留不支持、错误、超时及资源压力记录。

本文保留 **V3.2 现有压缩器 CPU 范围的历史签发记录（2026-10-11）**。该批次 16 条 lane 的报告、no-op resume 和两项辅助审计均完成；原 completion 为 `CURRENT_CPU_SCOPE_COMPLETE`，逐条验收为 `CURRENT_EXISTING_CPU_SCOPE_ACCEPTED_WITH_LIMITS`。原始 2400 条计划记录完整保留，结论绑定该批冻结源码和工件。随后按 v3.0 移植规范进行的代码、补丁、构建和登记修正已改变当前执行闭包；旧签发不授予当前闭包的正式性能资格。历史范围与限制见[原范围验收记录](docs/reviews/v32_current_scope_acceptance_20261011.md)。Python 包版本 `0.1.0`、V3.2 工程计划、现有 Schema/canonical/ABI 版本是不同版本体系。

同日完成的 [`lzss-raw` C++ 迁移](docs/lzss_cpp_rewrite_20261011/README.md) 更换了该入口的源码与工件身份。以上已签发 Benchmark 产物保留迁移前身份；当前 C++ 实现的新实验需建立新的运行身份，旧性能记录不作为新实现的测量结果。

当前代码的移植／重写审查与修正见[2026-10-11 审计报告](docs/audits/20261011_porting_standard/README.md)及[33 个入口逐项结论](docs/audits/20261011_porting_standard/rewrite_routes.md)。新验证分别记录源对照、原生测试、入口恢复与全量回归；没有把历史 FORMAL 重新授予修正后的闭包。

依据为 [V3.2 工程实施总计划](TimeSeries_Compression_Benchmark_V3_工程实施总计划.md)、[117 项独立审查](docs/reviews/independent_benchmark_review_20261010.md)和[能力支持矩阵](docs/algorithm_capability_support_matrix_20261010.md)。本轮只使用现有压缩器，不新增算法，不恢复已退出入口；长期多数候选接入另列。

## 已签发批次的范围与完成门禁

| 项目 | 当前范围与含义 |
| --- | --- |
| 活动入口 | 33 个入口、41 个声明 Track/fixture/config 资格案例；有限资格不代表全部合法域和参数 |
| Codec 登记 | 40 个清单：33 个活动入口、3 个范围外残留、4 个框架 oracle；alias 不增加方法数 |
| 普通实验 | 12 个 lane：byte、f64、f32、i16、abs、quality、model、cold、api、timestamp、entropy、u8 |
| 独立工作负载 | stream、query-warm、query-fresh；相关 query 变体保留研究范围 |
| 完整 P2 | 1 个 lane，完整 T/V/validity、typed schema、child/block/tail 与独立恢复 |
| async/ragged | 6 个明确对象 × LZ4/Zstd，12 个集合资格单元；独立于正式性能 lane |
| 候选与条款 | 166 候选记录与旧 163 命名空间映射；911 行规范/审查/矩阵验收映射、28 类独立 proof |
| 历史签发 | 原批次 16/16 lane 完成；completion 与 911 行逐条验收绑定原闭包，保留有限输入及明确结论边界 |

FSE/Huff0 和两个 Sprintz uint8 入口分别进入 entropy/u8 的现有算法共同任务组。所有现有 P1 完整 codec 需在适用任务中取得共同正式证据。SIMDcomp 是单方法 P0 primitive，保留其 primitive/SDK/入口资格，不虚构双方法完整整数方案组。

冻结的核心成员和合法配置保持完整分母；失败、拒绝、环境/资源不足与统计不足分别报告。核心组要求至少两个不同任务相关方法和两个独立真实来源；列、窗口、cast、采样变化不增加来源数。相关实现变体、参数点、ISA/build 副本不会自动增加方法数。SOURCE_PARITY 与任务 correctness、SDK 和正式比较分别验收，UNKNOWN 保留原义。

## 实际执行结构

| 职责 | 主要模块 | 行为 |
| --- | --- | --- |
| 原对象与数据准备 | `datasets/`、`pipelines/models.py`、`pipelines/channel_collection.py` | 内容与语义身份、T/V/mask、轴/单位/顺序、固定 Corpus 与来源派生 |
| 实验合同与编译 | `comparison/`、`planning/`、`codecs/` | 事前决策、成员/配置/期待矩阵、公共投影、ordered stages 与 child 源域 |
| 执行与恢复 | `execution/`、`adapters/`、`pipelines/` | Preflight、实际编解码、Finalize、完整依赖、独立公共 decoder 与输出物化 |
| 测量与资源 | `measurement/`、`execution/repetition.py`、`execution/workload_driver.py` | 独立 worker、真实时钟与方向信号、预热/缓存、资源租约与线程门禁 |
| 分析与报告 | `comparison/analysis.py`、`comparison/report_renderer.py`、`reporting/` | 原始证据重核、真实配对、固定分母、质量/Pareto/覆盖及范围结论 |

```text
事前决策 / Contract / Corpus / Config / ExpectedOutcome
  → 冻结源码、工件、资源、Protocol、AnalysisPolicy 与 Schedule
  → 原对象资格、独立恢复、完整成本
  → 独立 development pilot 与方向时钟/粒度/扰动门禁
  → 逐 lane 串行正式执行、append-only trials 与持久 STARTED 事件
  → 只读报告、no-op resume、成本与未压缩对象参考审计
  → 当前闭包 completion audit、逐条 requirement acceptance
```

普通、workload 与 P2 计划在测量前冻结 `experiment_decision.json`，包含用户决策、具体研究问题、目标总体、主要估计量、选择规则及结论边界；`decision_id` 同时绑定计划与报告。缺失或漂移的契约不能在恢复或发布时补填。未知终态的 STARTED attempt 禁止自动重测或覆写原始证据。

## 数据、成本与比较边界

- `TIMESTAMP` 使用原 T；`VALUE` 使用原 V 及适用 validity；完整 P2 保存全部声明 T/V/mask。同步 ND 与 async/ragged 集合分别使用明确 schema 和实际 wrapper，不从能力枚举推断所有算法原生支持。
- DatasetID 绑定原内容与声明语义。未声明的 cast、排序、填充、补 T、flatten、量化不能改变原任务；派生 f32/uint8 对象拥有独立 ground truth 与可审计来源链。
- 新比较使用独立 Contract/Group/Corpus/Config/Protocol/AnalysisPolicy/Schedule 与公共投影。完整对象允许验证过的可逆适配、逐列或组合，并计入完整成本；共同原生 API 组要求相同实际输入 schema 与字节。Legacy 比较键不自动晋升新组资格。
- `FinalBits` 包含最终物理流、描述及所有必需恢复依赖；capacity/workspace、logical payload 与真实存储分开。原 `RawBits` 分母不因内部扩宽而增加。
- 完整未压缩参考另存完整对象及同 Track 的付费 schema 参考。它是 `SIZE_BASELINE`，性能为 null＋reason、统计方法数为 0；组件 native input size 不与完整对象空间混比。
- 固定误差检查原域总预算；无界质量网格保留全部合法点和经验 RMSE/MaxAE。Rate/summary 目前只有框架专属 validator 资格，没有活动算法或正式组。

普通完整对象的当前部署边界为 `SCHEMA_BOUND_OBJECT`；API 为 `NATIVE_COMPONENT`/CORE，二者分别报告。模型组为 uint8 base4 symbol 任务，训练/test overlap 保留 UNKNOWN。流式范围为 known-length fixed-block、Finalize 后完整消费；query bytes 为 logical estimate，样本不足的 p99 为 null。详细限制见[当前范围验收记录](docs/reviews/v32_current_scope_acceptance_20261011.md)。

## 已注册入口

| 类别 | 范围内入口 |
| --- | --- |
| 通用字节 | `lz4-frame`、`zstd-frame`、`snappy-raw`、`brotli-stream`、`deflate-zlib`、`xz-stream` |
| LZSS | `lzss-raw` 为 EI10/EJ4/C32 的 C++ 重写；`lzss-dipperstein-c` 保持独立来源与格式，见[迁移验证](docs/lzss_cpp_rewrite_20261011/README.md) |
| 浮点与整数无损 | `alp`、`alp-rd`、`chimp`、`chimp128`、`elf`、`elf-plus`、`elf-star`、`self-star`、`neats-lossless-i64`、`leats-lossless-i64` |
| 熵编码与 Sprintz | `huff0`、`fse`、`sprintz-delta`、`sprintz-fire`、`sprintz-fire-huff0`、`sprintz-delta-u8`、`sprintz-fire-u8` |
| Primitive | `simdcomp-u32`；plain SSE4.1/AVX2，差分与 FOR 组合未恢复 |
| 有损与模型 | `zfp-accuracy-1d`、`serf-qt`、`serf-xor`、`abba`、`fabba`、`deepzip`、`dzip` |

`bzip2-stream`、`lzsse2-raw`、`lzsse8-raw` 为范围外残留登记；4 个 oracle 用于框架测试，不参与算法排名。`lz77` 是 `deflate-zlib` 的来源别名。范围以 `registry/algorithm_scope.json` 为准，历史退出列表见[算法退出记录](docs/algorithm_retirement_20261010.md)。

## 环境配置与快速开始

以下命令从仓库根目录执行。先配置 CPU 基础环境，再按实际使用的算法添加可选依赖。安装 Python 控制面不会安装原生 Codec、数据集、模型或 CUDA。

### 1. 操作系统与系统工具

当前原生构建与资源采集主要面向 **Linux x86_64**。下面给出 Ubuntu 22.04 / 24.04 的 CPU 环境配置；Debian 用户可安装对应同名软件包。Windows 建议使用 WSL2 Ubuntu，资源与性能结果应标明 WSL2 环境；macOS、ARM 和其他平台尚无全量原生资格声明。

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential cmake pkg-config git curl ca-certificates \
  binutils util-linux procps
```

| 系统依赖 | 用途 |
| --- | --- |
| `build-essential` | GCC、G++、make、C/C++ 标准库与开发头文件；基础 binding 使用 C11 / C++17，NeaTS/LeaTS binding 使用 GNU C++20 |
| `cmake`、`pkg-config` | CMake 构建与依赖发现；建议 CMake >=3.22 |
| `git` | 获取仓库，在构建副本上检查/应用冻结补丁 |
| `binutils` | ELF、链接及原生工件检查工具 |
| `util-linux`、`procps` | `lscpu`、`taskset`、进程和内存诊断；框架同时读取 Linux `/proc` |
| `curl`、`ca-certificates` | 下载环境安装器和依赖时使用 HTTPS |

可选工具按算法安装：

```bash
# ALP / ALP-RD 的默认配方使用 clang++；包含 Clang sanitizer runtime。
sudo apt-get install -y clang libclang-rt-dev

# 仅在独立 DeepZip / DZip 构建中启用 HDF5 checkpoint importer 时安装。
sudo apt-get install -y libhdf5-dev
```

LZ4、Zstd、Snappy、Brotli、zlib、bzip2、XZ、zfp 等当前配方编译 `adapters/` 中的冻结源码，**不要求安装系统 `liblz4-dev` / `libzstd-dev` 等来替代这些源码**。DZip 的 Eigen、MKLDNN 和 libbsc，WaLLoC 的 libwebp 也由冻结副本构建。上游 README 中独立 benchmark 的依赖不一定属于本框架 binding，例如 NeaTS 的上游 Squash benchmark 不在当前 binding 构建路径中。

检查工具与机器 ISA：

```bash
gcc --version
g++ --version
cmake --version
lscpu
```

CPU 标志必须满足所选入口清单：例如 SIMDComp 使用 SSE4.1 和独立 AVX2 对象，Sprintz 还要求 BMI2/LZCNT，DZip 要求 AVX。虚拟机或容器隐藏 ISA 时，不能仅凭宿主机型号判断可用性。缺失 ISA 不通过静默替换算法解决。

### 2. 获取仓库并创建 Conda 环境

如果尚未安装 Conda，可选择 [Miniforge](https://github.com/conda-forge/miniforge)。下面的安装器适用于 Linux x86_64；其他架构应选择匹配的安装器。

```bash
curl -fL -o Miniforge3-Linux-x86_64.sh \
  https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh
```

安装时按提示选择自己的目录并初始化 bash；重新打开终端后执行 `conda --version`。已有 Miniconda、Anaconda 或 Miniforge 可直接使用，不依赖特定安装位置。

```bash
git clone https://github.com/t12131219/TSCompressBenchMark.git TSDataCompressBenchMark
cd TSDataCompressBenchMark

conda create -n tscompbench --override-channels -c conda-forge \
  python=3.14 pip -y
conda activate tscompbench

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
python -m pip check
python -c 'import sys, numpy; print(sys.version); print("NumPy", numpy.__version__)'
```

`pyproject.toml` 的运行要求是 **Python >=3.14、NumPy >=2.5,<3**，构建后端要求 `setuptools>=77`；`pip install -e .` 会按这些约束安装依赖。此处 `tscompbench` 只是示例环境名，可以自行替换。当前控制面没有 pandas、SciPy、scikit-learn、PyTorch 或 TensorFlow 的必装依赖。

[requirements.txt](requirements.txt) 固定了参考环境 `CompressBench14` 中已核实的 NumPy、setuptools、pytest 和 ruff 版本，并补充交付/收尾工具使用的 PyYAML。参考环境的 Python 为 3.14.5；环境名无需相同。该文件用于安装直接 Python 依赖，不是包含所有传递依赖和原生 runtime 的 Conda 锁文件；只运行控制面时也可仅执行 `pip install -e .`。

如果包源暂时无法提供上述版本，安装会失败，应先解决包源或版本可用性；不能将 NumPy 1.x 或 Python 3.11 当作控制面的兼容替代。尤其不要为安装旧模型 runtime 降级此环境。

不使用 Conda 时，也可在已有 Python 3.14 上创建 venv：

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

如果选择直接运行源码而不安装 editable 包，仍需在 Python >=3.14 环境中安装运行依赖：

```bash
python -m pip install 'numpy>=2.5,<3'
export PYTHONPATH="$PWD/src"
```

随后使用同样的 `python -m tscompbench` 命令。运行工具脚本时也应使用选定环境中的 `python`。

### 3. 当前保留的模型压缩依赖

DeepZip / DZip 的 Benchmark 构建关闭 CUDA 和 HDF5 importer，按各自冻结依赖与模型合同运行 CPU profile。控制面环境不要求安装 Python PyTorch/TensorFlow。依赖定位使用 `TSCB_TORCH_ROOT`，仍须逐文件匹配冻结依赖哈希；不能把位置覆盖当作版本或数值行为资格。

TRISTAN、CORAD、WaLLoC 已退出活动范围，相应 MKL、WaLLoC CUDA / LibTorch 安装步骤不再是当前 Bench 的配置要求。独立源码/重写工程自己的依赖说明作为历史资料保留。未来 GPU、训练或其他模型方法按 V3 重新接入与验收。

### 4. 确认控制面与准备数据

当前 CLI 的默认项目根目录推导不适合所有安装方式，因此以下所有命令都**显式传入 `--project-root .`，放在子命令之前**。editable 安装只提供 Python 包，仓库中的 registry/configs/源工件仍必需。

```bash
python -m tscompbench --project-root . --help
python -m tscompbench --project-root . codecs list
python -m tscompbench --project-root . codecs verify
python -m tscompbench --project-root . datasets list
```

`codecs verify` 验证注册合同，不代表二进制已经构建或当前机器取得运行资格。数据准备按 `registry/datasets/<key>.json` 中的 `file.path`、字节数、SHA-256、parser 和逻辑契约进行；该路径相对于仓库根目录。

`datasets/` 通常不随 Git 分发。以 LZ4 示例为例，需要取得匹配版本的 `national_illness.csv`，放在 `datasets/national_illness.csv`。该清单目前登记的是 `local:` 来源，没有自动下载地址；用户需从合法的数据提供方或已有数据归档取得内容并核对许可。不同格式或内容的同名 CSV 不能沿用旧 DatasetID，应登记新的 Manifest。

```bash
mkdir -p datasets
# 将取得的数据放入 Manifest 指定的位置后，核对文件哈希。
sha256sum datasets/national_illness.csv
# 仅准备并核验一个实际要使用的数据集。
python -m tscompbench --project-root . datasets prepare national_illness \
  --output build/dataset-checks/national_illness
# 仅在所有已注册数据文件齐全后执行全表校验。
python -m tscompbench --project-root . datasets verify
```

`national_illness` 当前预期 SHA-256 为 `93601f64d2566dc796ca4305adad8b8560c2db1a1ff04543c3bd813a7263570a`。`datasets verify` 不负责下载文件；只准备部分数据时，全表校验因其他文件缺失而失败是可解释的结果。

合成数据应使用匹配的 `tools/generate_*_fixture.py` 与固定参数。部分生成器会同时重写对应 Manifest，执行前应阅读脚本并检查生成后的变更；合成 fixture 不构成真实数据上的性能结论。`build/`、`runs/` 和独立重写工作区也通常被 Git 忽略，需要在自己的机器生成，参见[文件保留规则](docs/git_tracking_policy.md)。

无后缀 canonical 现可通过 `datasets import-canonical PATH --key KEY` 正式登记。用全局 `--dataset-manifest-root PATH` 选择独立源登记目录，后续 prepare/run 命令使用同一路径；默认许可为 REVIEW_REQUIRED，应按实际来源登记许可状态。Dataset_Verify 的版本化生成器与全入口资格命令见 [V3 第一轮实施记录](docs/dataset_verify_v3_implementation.md)。统一容器不扩大算法原生数据域；特殊 IEEE 位模式、shape、时间戳和模型约束仍须通过协商与 Preflight。

### 5. 跑通一个 CPU 资格实验

以 LZ4 为例，在数据准备完成后构建本机工件。`--profile all` 执行该入口声明的构建组合，一般为 release + sanitizer，部分整数入口还包含 debug；不是所有入口都支持单独 `--profile debug`。

```bash
python tools/build_codec.py lz4-frame --profile all
python -m tscompbench --project-root . run validate \
  configs/experiments/lz4-frame-qualification.toml \
  --output-root runs --run-set-id lz4-local-qualification
python -m tscompbench --project-root . run report \
  configs/experiments/lz4-frame-qualification.toml \
  --output-root runs --run-set-id lz4-local-qualification --resume
```

对需要专项 source/native/SDK 门控的其他入口，仅运行 `build_codec.py` 不足以取得资格，还需按接入卡执行对应测试与 auditor，并生成匹配本机工件及依赖身份的证据。共享源码、编译器、runtime 或二进制改变都可能使旧证据失效。

`QUALIFICATION` 用于边界和接入检查，不参加正式性能排名；空 `summary.csv` 可以是预期结果。检查 raw、诊断、eligibility 和 coverage。命令退出成功也不代表每个任务都 PASS，应读取任务级状态。

### 6. Legacy TOML 实验、线程与恢复

以下 TOML 保留原运行与统计合同，用于 legacy 路径；其结果不能自动升级为 V3.2 新共同比较。V3.2 执行入口见下一节。运行此配置前应完成 LZ4/Zstd 资格和构建：

```bash
python tools/build_codec.py zstd-frame --profile all

# 与示例的单线程预算一致；带线程池的其他算法按其清单配置。
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python -m tscompbench --project-root . run validate \
  configs/experiments/zstd-lz4-formal-comparison.toml \
  --output-root runs --run-set-id zstd-lz4-local-formal
python -m tscompbench --project-root . run report \
  configs/experiments/zstd-lz4-formal-comparison.toml \
  --output-root runs --run-set-id zstd-lz4-local-formal --resume
```

正式运行前核查 `profile` 的设备、线程/进程预算、超时、内存限制与 ISA，必要时复制 TOML 为自己的实验配置。保持足够空闲内存并减少其他负载，框架会保留换页和线程超预算证据。DZip 等线程池入口有独立进程线程预算，不能通过统一设置 1 将其声明为单线程算法。

CPU affinity 必须属于当前进程可用集合，可用下列命令查看，随后在自己的配置中选择；不要复制历史报告的 CPU 0、GPU 编号或机器内存参数。

```bash
python -c 'import os; print(sorted(os.sched_getaffinity(0)))'
```

从已有批次恢复时，对同一配置、输出目录和 RunSetID 的 `run validate` 加 `--resume`。已有路径拒绝覆盖；恢复会核对冻结配置、环境、工件和日志。首次运行需使用尚不存在的 RunSetID，条件改变后创建新批次。

其他分步命令为 `run init`、`run prepare`、`run plan`。先准备与核验依赖，再冻结实验环境，避免在执行或恢复中改变 runtime、线程环境变量或工件。

### 常见安装与运行问题

| 现象 | 检查与处理 |
| --- | --- |
| `No module named tscompbench` | 激活正确环境，执行 `python -m pip install -e .`，或在仓库根目录设置 `PYTHONPATH="$PWD/src"` |
| registry 为空或找不到配置 | 确认当前目录为仓库根目录，显式传 `--project-root .`；仅安装 wheel 不提供完整仓库资产 |
| Python / NumPy 依赖无法解析 | 核查 Python >=3.14 和 NumPy >=2.5,<3 的可用包；不要混用旧模型环境 |
| 缺少数据或 SHA-256 不匹配 | 按 Manifest 准备正确内容，或为新数据建立新身份；全表校验要求全部已注册文件 |
| `g++` / `clang++` 找不到 | 安装 `build-essential`；ALP / ALP-RD 默认配方另需 Clang。`lzss-raw` 使用 C++17，无 Rust 工具链依赖 |
| 缺失 `.so`、`ldd` 显示 `not found` | 构建本机工件、安装对应 runtime，核查配方的 RPATH 和依赖前缀；不要全局加入另一个 Conda 环境的 `lib/` 目录 |
| dependency / SDK evidence drift | 按该入口接入流程重新生成并审计证据；历史报告不替代本机结果 |
| 任务不支持、资源压力或空汇总 | 检查 Preflight、Run 原始状态、eligibility 与 coverage；QUALIFICATION 和不足资格的配置不产生正式排名 |

## V3.2 执行入口

已完成范围为 12 个 comparison、3 个 workload、1 个 pipeline lane。byte/f64/i16/abs/f32 在 `formal-r2/`，quality 在 `formal-r2/continuation-r2/`，model/cold/api/entropy/u8 在 `formal-r2/continuation-r3/`，stream/query-warm/query-fresh/pipeline/timestamp 在 `formal-r2/continuation-r4/`。最终发布通过 `declaration-release-r4.json` 引用这四批独立证据。旧计划、失败和部分运行均保留。该 `build/` 工件通常不随 Git 分发；新机器须准备数据/工件并冻结自己的完整计划和资源，身份改变后使用新 RunSet。

首轮 byte 的 development pilot 因 Snappy decode collector 扰动 `0.152526 > 0.15` 未通过，没有产生 FORMAL。新版本把基础 comparison protocol 的线程采样间隔从 1ms 调为 5ms，保留 `0.15` 门限、算法参数、语料和外层重复；P2 保持独立协议。改版记录为 `formal-r2/protocol_adaptation.json`，只依据 development 观测。当时独立 WorkloadProtocol 的实际 monitor 仍为 1ms，后来由 r4 单独修订。线程采样是实际高水位的下界，短暂线程可能漏采；改采样间隔本身不授予资格。

时间戳组旧资格另因 LZSS 累计原生计算超过 30s 单任务时限而 TIMEOUT；timestamp v4 统一把单任务时限增为 240s 后资格和 pilot 通过。源码核对显示每个正式槽位仍重跑全部 49 项 preflight，development 粗略估计 143s × 32 个 native LZSS 槽位已超过 3600s 总预算。旧批次保留 17 条记录（9 条正式有效、8 条预期缺 T 拒绝）与一个 STARTED 未知终态，已受控停止、释放 host lease 并禁止 resume。timestamp v5 只将总预算增为 10800s；单任务 240s、全部边界、block/算法参数、语料、8 个重复和 collector 门限 `0.15` 保留。适配依据 development 诊断和源码槽位推算，未用选取的 encode/decode 观测优化性能。记录见 `formal-r2/continuation-r2/timestamp_total_budget_adaptation.json`。v5 已在 r4 新身份下实际完成资格、pilot、256 个合法核心 FORMAL 槽位及报告/resume/两审计；64 个预期缺 T 槽位保留 8 次实际 UNSUPPORTED 与 56 条 STOPPED，不缩分母。

模型 v7 的 development pilot 因快参考 LZ4/Zstd 无法在 8 次 inner iterations 内累计每方向 50ms 而停止；DeepZip/DZip pilot 通过，旧批没有 FORMAL。模型 v8 只把同组共享 ceiling 提高至 1,000,000，3 次 pilot、4 次 outer repetitions、50ms 方向最低时长、0.15 门限、参数/语料与线程预算保持。记录为 `formal-r2/continuation-r3/model_inner_budget_adaptation.json`；新身份已完成实际资格、pilot、FORMAL、resume 与两项辅助审计。

旧 r3 stream pilot 的 XZ decode collector 扰动 `0.27376386156568376 > 0.20`，raw 恢复与时钟/资源门禁通过但没有 FORMAL。只读 development 诊断发现 1ms `/proc` 采样与部分 decode timer 重叠，提供相关性依据，未证明因果。r4 将 stream/query-warm/query-fresh 的实际 WorkloadProtocol monitor 统一从 1ms 调为 5ms；0.20 门限、5 对 pilot、8 个独立会话、1000 个 query 请求、成员/参数/语料保持，并冻结新 workload/decision/schedule/run 身份。记录为 `formal-r2/continuation-r4/workload_collector_monitor_adaptation.json`；三个 workload lane 及该队列的 P2 已实际完成。以上适配没有使用正式测试性能选择协议，没有修改源码、测试、工具或 registry。

角色台账生成器另修正了 LZSS 的旧全局说明，改为遵循各任务 GroupSpec 的方法等价政策；只有文案/policy 与 ledger ID 改变，14 个组的身份、成员和方法分母未变。记录为 `documentation_generator_revision.json`，当前台账为 `stage_mapping-release-r4.json` / `.md`。Benchmark 源码、测试、registry 和三个正式驱动继续冻结；SDK 与 2362 项全量回归的当前引用重新核验通过，此次没有重跑性能或 pytest。`release_r4_preparation_validation.json` 是结构准备记录，不替代最终 completion。

普通组的分步命令如下，`BUNDLE` 指已经冻结的本机 ComparisonBundle，`RUNSET` 是尚未使用的名字：

```bash
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python tools/run_v32_comparison.py plan "$BUNDLE" \
  --output-root build/v32-local --run-set-id "$RUNSET"
python tools/run_v32_comparison.py qualify "$BUNDLE" \
  --output-root build/v32-local --run-set-id "$RUNSET" --resume
python tools/run_v32_comparison.py pilot "$BUNDLE" \
  --output-root build/v32-local --run-set-id "$RUNSET" --resume
python tools/run_v32_comparison.py formal "$BUNDLE" \
  --output-root build/v32-local --run-set-id "$RUNSET" --resume
python tools/run_v32_comparison.py report "$BUNDLE" \
  --output-root build/v32-local --run-set-id "$RUNSET"
```

`tools/run_v32_existing_comparison.py` 一次执行上述链及 no-op resume 核对。工作负载用 `tools/run_v32_existing_workload.py BUNDLE --protocol PROTOCOL --output-root PATH --run-set-id NAME`；P2 用 `tools/run_v32_pipeline_comparison.py all --output PATH --cpu CPU --verify-resume`。已保存资格或 pilot 在 `--resume` 时只核验并复用，不重新测量修复失败。未知终态会阻断，修复代码后使用新身份保留旧证据。

已完成的 r4 计划按串行 queue 执行 stream/query-warm/query-fresh/pipeline/timestamp；先前三批的 11 条有效 lane 独立保留，各自资格、pilot、方向信号、资源与停止门禁分别生效。新机器运行队列的示例为：

```bash
python tools/run_v32_release_queue.py \
  build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/release_plan.json \
  --output-root build/v32-evidence-local/continuation-r4
```

独立 async/ragged 集合资格与辅助未压缩成本参考不会加入性能试验或算法方法数：

```bash
python tools/qualify_v32_channel_collection.py \
  --output build/v32-evidence-local/channel-collection
python tools/audit_v32_uncompressed_reference.py \
  build/v32-local/"$RUNSET" --lane comparison
```

`--lane` 是接口种类 `comparison`、`workload` 或 `pipeline`，不是算法组名称。入口全量资格入口为 `tools/qualify_v32_active_entries.py`；正式源码冻结后的回归入口为 `tools/verify_v32_regression.py --output-dir PATH`。

## 测量、结果与最终验收

V3.2 的预热、外层独立单位、inner iterations、方向粒度、时钟、缓存、线程/内存、预算、停止与重跑规则来自已冻结 Protocol；不使用一个全局重复数或时长代替所有 profile。worker 预热后真实时钟、空 clock/dispatch 观测及 collector 对照用于门禁，正式时间不减去估算开销。Encode、Decode 和实际 E2E 分列；完整恢复物化属于用户边界，独立 correctness 审计在计时外。

固定 Corpus/host 的真实配对区间与统计不足结论并存。完成测量不意味着已证明某成员更快；小样本有限校准不提供普遍覆盖保证。资源使用主要为 PROCESS 范围；实际 affinity/thread 与 host lease 必须通过，未采集高级 counter/energy/device 指标保留 null＋reason。

```text
build/<evidence-root>/<comparison>/
  bundle.json / environment.json / control_plane.json
  experiment_decision.json / comparison_plan.json / execution_plan.json
  schedule.json / jobs/ / codecs/ / datasets/
  qualification.json / pilot.json
  events.jsonl / comparison_trials.jsonl / artifacts/
  analysis.json / analysis_extensions.json / report.html
  resume_verification.json
  uncompressed_reference.json / uncompressed_reference.md / reference_artifacts/
```

workload 另保存 `workload_plan.json`、`workload_pilot.json`、`workload_trials.jsonl` 和 `workload_analysis.json`；P2 使用 `plan.json`、`pipeline_events.jsonl`、`trials.jsonl` 与 `report.json`。报告从冻结计划与 raw 重建，不重测性能；各独立 decoder/成本审计的运行范围单独记录。

历史批次最终回归保留全部测试定义/fixture 和 pytest 配置 hash、未过滤的真实日志与 skip 原意。基线全量回归实际为 2362 passed、650 warnings、523.65s，SDK 为 504 项 PASS / 74 个实际导入项目文件；发布器重新核验这些冻结引用，没有冒称重新运行全量测试。SDK/source 资格另审计，UNKNOWN 保持。以下是该批次实际使用的签发命令；输出已生成且不可覆盖，重签须选择新输出名：

```bash
EVIDENCE_ROOT=build/v32-evidence-20261010/current-r2
DECLARATION="$EVIDENCE_ROOT/declaration-release-r4.json"
python tools/audit_v32_completion.py "$EVIDENCE_ROOT" \
  --declaration "$DECLARATION" --output "$EVIDENCE_ROOT/completion-final.json"
python tools/publish_v32_requirement_acceptance.py publish \
  "$EVIDENCE_ROOT/completion-final.json" \
  --output "$EVIDENCE_ROOT/requirement_acceptance-final.json"
```

最终声明 `declaration-release-r4.json` 引用四批独立工件：`formal-r2/` 的 byte/f64/i16/abs/f32，`formal-r2/continuation-r2/quality`，`formal-r2/continuation-r3/` 的 model/cold/api/entropy/u8，以及 `formal-r2/continuation-r4/` 的 stream/query-warm/query-fresh/pipeline/timestamp。回归为 `regression-final/validation.json`，活动角色映射为 `stage_mapping-release-r4.json` / `.md`，ledger 为 `v2:active-stage-role-ledger-v32:sha256:240eb9d39eaecb7ef483fa9c76946466f418068c78a7a469f4bcbeabe95b9834`；SDK、active33 和集合资格独立引用。旧失败、受控中止与未知 STARTED 记录独立保留。

该批次 audit 核实原始工件与当时 source/build/registry/config 绑定一致，发布器内部重新 audit 与已保存 completion 完全相等。12 条普通报告均为 `CORE_COMPLETE`、3 条 workload 为 `PROFILE_COMPLETE`、P2 为 `COMPLETE`，16 条均通过 no-op resume 与两项辅助审计。2400 条计划记录包括 timestamp 的 64 个预期缺 T 拒绝/停止槽位；成本审计覆盖 312 个 profile / 2336 个实际试验工件，另有 65 个完整未压缩对象参考。

最终工件为 [completion-final.json](build/v32-evidence-20261010/current-r2/completion-final.json)（`CURRENT_CPU_SCOPE_COMPLETE`）和 [requirement_acceptance-final.json](build/v32-evidence-20261010/current-r2/requirement_acceptance-final.json)（`CURRENT_EXISTING_CPU_SCOPE_ACCEPTED_WITH_LIMITS`），28 类 proof 保存于同目录 `requirement_acceptance-final_proofs/`。逐条验收覆盖 684 计划行＋117 审查项＋110 矩阵行：768 行 `ACCEPTED_CURRENT_SCOPE`，26 行现有子集验收且新增成员暂缓，2 行分别为固定 pool/资格的受限验收，40 行 context、58 行历史、2 行 source parity 原状、5 行用户暂缓、10 行可选未声明。完整验收 ID 与每组身份见[当前范围验收记录](docs/reviews/v32_current_scope_acceptance_20261011.md)。原报告的统计 `INCONCLUSIVE`、source parity `UNKNOWN` 与 null 原因保留；实施完成不自动证明算法优胜或全域性质。

## 开发、证据与限制

```bash
python -m pytest
python -m ruff check src tests tools
```

使用已激活控制面环境；完整 suite 会消费真实算法工件、数据、模型与专项资格。正式测试、SDK 与性能批次串行安排；源码或依赖改变使相关冻结证据失效。当前 finite-domain 资格、SOURCE_PARITY、数学保证、经验质量、wire 兼容和统计结论各自保留，不从自回环或历史结果互相推导。

本轮暂缓新增算法和长期多数候选实施。SYSTEM/P3/device、unknown-length bounded-memory stream、高级 collector 等未签发范围详见[当前验收限制](docs/reviews/v32_current_scope_acceptance_20261011.md)。项目许可证见 [LICENSE](LICENSE)，vendored 源码、模型和 runtime 遵循各自 source lock 与许可证。

## 目录导航

| 路径 | 内容 |
| --- | --- |
| `src/tscompbench/` | 数据、实验合同、执行/测量、完整管线与报告 |
| `native/include/` | Canonical、C ABI 与计时接口 |
| `adapters/` | 冻结源码、binding、补丁、合同及算法测试 |
| `registry/` | Dataset、Codec、SourceArtifact、别名与 onboarding 清单 |
| `schemas/v2/` | 配置、任务、运行、账本、统计与报告契约 |
| `configs/comparisons/` | V3.2 共同比较 bundle 与 workload protocol |
| `configs/experiments/` | Legacy QUALIFICATION / FORMAL TOML |
| `fixtures/`、`tests/` | 受控数据、golden vectors 与回归测试 |
| `tools/` | 构建、冻结、资格验证、接入和独立审计 |
| `docs/` | 专项自检、接入范围与架构资料 |

阅读顺序：[当前范围验收](docs/reviews/v32_current_scope_acceptance_20261011.md) → [V3.2 总计划](TimeSeries_Compression_Benchmark_V3_工程实施总计划.md) → 对应算法接入卡与冻结配置。历史变化见 [CHANGELOG.md](CHANGELOG.md)，文件保留规则见 [Git tracking policy](docs/git_tracking_policy.md)。
