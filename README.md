# TSDataCompressBenchMark

TSDataCompressBenchMark 是一个以源码身份、输入契约和原始证据为基础的时间序列压缩基准框架。Python 控制面负责数据准备、能力协商、任务规划、隔离执行、性能测量与统计报告；具体算法通过原生适配器接入。项目比较的是明确声明的压缩对象、配置和执行路径，保留不支持、错误、超时及资源压力记录。

本文对应截至 **2026-10-08 的源码状态**。Python 包版本为 `0.1.0`，数据与运行契约属于 V2；两者是不同的版本体系。本次状态说明见 [RELEASE_DESCRIPTION.md](RELEASE_DESCRIPTION.md)。

后续框架修改、算法接入与评测按 [V3 工程实施总计划](TimeSeries_Compression_Benchmark_V3_工程实施总计划.md)执行。计划版本独立于现有 Schema、canonical 格式与 ABI 版本；当前实现范围及待实施迁移见该计划。

## 当前状态

五层框架已经实现，能够完成从注册数据到可追溯报告的闭环。算法接入仍按来源、API、数据域和运行配置逐项验证。

| 项目 | 当前状态与含义 |
| --- | --- |
| Codec 注册表 | 67 个清单：63 个非 oracle 入口、4 个框架测试 oracle；注册数量不等于完整算法验收数量 |
| 数据集注册表 | 22 个清单，包含真实数据和合成验证 fixture |
| 其他注册身份 | 118 个 SourceArtifact、4 个 Codec 别名；SourceArtifact 不等于可运行算法 |
| 全量接入清单 | 保留 221 个逻辑条目，其中 115 个原生核心候选；完整逻辑条目验收计数为 0 |
| 最近原生入口证据刷新 | 2026-10-07 的 13 个入口通过限定范围重新资格验证；1882 条正式批次记录，1775 条有效测量记录 |
| 能力边界 | 查询、流式、ISA、数据类型与 LossMode 依清单和运行配置门控；没有统一的全算法、全数据域支持声明 |

计数来自当前注册表和保存的审计记录。`registry/native_integration_plan.json` 是接入工作清单快照，其逐条状态可能早于最新专项审计；判断某入口当前资格时，应同时核查接入卡、工件及 SDK 依赖哈希、新运行批次和独立审计。已通过限定范围的 primitive 或 pipeline 不会自动使整个逻辑条目完成。

最近状态依据：[原生入口证据刷新](docs/native_codec_evidence_refresh.md)、[方向最短时长修正](docs/minimum_duration_direction_self_check.md)、[全量工作清单](registry/native_integration_plan.json)。详细 `build/` 与 `runs/` 证据由构建和运行生成，通常不随 Git 分发；文档中的历史计数不代表新机器的验证结果。

## 运行结构

| 层 | 主要模块 | 实际职责 |
| --- | --- | --- |
| 1 数据准备 | `datasets/`、`configuration.py`、`environment.py`、`runner.py` | 加载配置、冻结环境、核查数据源，加载 CanonicalDataset，分析特征并写入 Canonical 工件 |
| 2 能力与任务规划 | `codecs/`、`planning/`、`preprocess/contracts.py` | 扫描参数，按 Dataset × Algorithm × Track × Config 协商能力，生成适配/预处理计划、执行路径及可比性键，冻结任务宇宙 |
| 3 执行与验证 | `adapters/`、`execution/`、`validation/`、`accounting/` | 源与构建门控、输入校验、实际兼容适配、预处理阶段验证、边界测试、最小往返及正式重复正确性检查 |
| 4 性能测量 | `execution/repetition.py`、`measurement/` | 预热与正式重复中的计时、最短时长循环、同步资源采集，以及按能力执行的查询和流式工作负载 |
| 5 统计与报告 | `statistics/`、`reporting/` | 读取冻结任务和原始证据，先筛选资格，再聚合，生成分数据集及 corpus 指标、Pareto、逐指标排名、覆盖率和报告 |

实际执行顺序：

```text
初始化 / 恢复 Run Set
  → 数据准备
  → 参数展开、能力协商、执行解析与任务冻结
  → 对每个任务执行 Preflight
      ├─ 失败 / 不支持：保存诊断
      └─ 通过：预热 → 正式重复
                    → 适配、完整编解码、计时及同步资源采集
                    → 逐次正确性与资源检查
                    → 可选查询 / 流式工作负载
                    → 追加原始 Run 证据
  → 单独调用 run report：资格过滤 → 聚合 → 分组分析 → 报告
```

第 2 层冻结计划，实际适配与阶段验证在执行时发生。第 3、4 层共享 `execute_task`，性能测量发生在正式编解码重复中。`run validate` 会完成准备、规划和执行；`run report` 读取已有证据，不重新调用 Codec。

[源码展开架构图](docs/main-runtime-framework-20261008/framework.html)可辅助阅读。它展示职责和步骤展开，包含调用容器及同步观察关系，所有箭头不能都解释为严格串行函数调用。

## 数据、算法与比较契约

### 数据与 Track

- DatasetID 绑定内容哈希和声明语义；源 CSV/NPZ 的文件大小只用于 provenance，不作为压缩比的原始数据分母。
- 加载器按 Manifest 处理形状、dtype、时间戳、值与 Validity；拒绝未声明的转换、排序、填充、插值或 reshape。
- 特征分析记录 exact / sampled 模式，Canonical 工件具有版本、布局和哈希。
- `TIMESTAMP` 使用 T；`VALUE` 使用 V 和适用的 Validity；`SYSTEM` 要求共同的 T/V，生成 SegmentPlan 并由适配器实现具体对象封装。框架没有任意 T Codec 与 V Codec 自动组合的通用装配器。
- UTS、同步 MTS 和原生多维数据的支持范围由各 Codec 清单决定。PEMS 保留原始三维结构，框架不会为其虚构时间轴。

### 能力、身份与成本

能力协商返回 `DIRECT_SUPPORTED`、`ADAPTER_LOSSLESS`、`ADAPTER_LOSSY` 或 `UNSUPPORTED`。非法参数点和不支持的任务保留在任务宇宙中，附带明确原因。

SourceArtifactID 标识源工件，AlgorithmID 标识注册算法合同，ConfigID 标识展开配置，ExecutionPathHash 标识实际工件、适配器、环境、ISA、线程和回退等执行事实。三层比较键依次为：

| 比较维度 | 必须匹配的键 |
| --- | --- |
| 空间与质量 | SemanticComparabilityKey |
| 速度、查询与流式执行条件 | ExecutionComparabilityKey，包含语义键 |
| CPU、内存等资源 | ResourceProfileKey，包含执行键 |

编解码内核要求 `compress_update → finalize → accounting → 独立解码`，即使 Finalize 输出 0 字节也必须发生。FinalBits 计入完整对象及外部必要侧信息成本，输出容量不等于压缩大小。模型、字典、索引或共享 T/V 码流的成本遵循具体账本；不能凭内部拆分字段为 0 就判断其免费。

无损值检查整数精确恢复或 IEEE 位一致；有界有损检查真实误差违反；无界有损记录质量而不虚构误差保证。`SUMMARY_ONLY` 和 `RATE_CONTROLLED_LOSSY` 使用各自合同，其中 rate gate 不应解释为已完成通用码率验收。框架 oracle 用于验证流程，不参与正式算法排名。

## 已注册入口

以下是注册覆盖，具体可用数据域和资格以 Manifest、接入卡及当前审计为准。

| 类别 | 入口 |
| --- | --- |
| 通用字节压缩 | `lz4-frame`、`zstd-frame`、`snappy-raw`、`brotli-stream`、`deflate-zlib`、`bzip2-stream`、`xz-stream` |
| LZSS / LZSSE | `lzss-raw`、`lzss-dipperstein-c`、`lzsse2-raw`、`lzsse8-raw`；不同来源与格式保持独立身份 |
| 浮点与时间序列无损 | `alp`、`alp-rd`、`chimp`、`chimp128`、`elf`、`elf-plus`、`elf-star`、`self-star`、`neats-lossless-i64`、`leats-lossless-i64` |
| 时间戳与联合对象 | `delta-varint`、`influxdb-tsm-adaptive-timestamp`、`prometheus-xor-chunk`、`prometheus-xor2-chunk`、`prometheus-histogram-st`、`prometheus-float-histogram-st` |
| 熵编码与 Sprintz | `huff0`、`fse`、`sprintz-delta`、`sprintz-fire`、`sprintz-fire-huff0`，以及历史受限的 `sprintz-delta-u8`、`sprintz-fire-u8` |
| 整数 primitive 与 pipeline | StreamVByte 两个 uint32 入口及两个 checked int64 pipeline；MaskedVByte 与 Delta；SIMDComp、Delta、FOR；FastDifferential；Simple9、Simple9hacked、Simple16、Simple8b_RLE；LittleIntPacker 五个入口 |
| 有损与模型压缩 | `zfp-accuracy-1d`、`serf-qt`、`serf-xor`、`abba`、`fabba`、`tristan`、`corad`、`deepzip`、`dzip`、`walloc-1d` |
| 框架 oracle | `oracle-direct`、`oracle-lossless-adapter`、`oracle-lossy-adapter`、`oracle-native-nd-only` |

`lz77` 是 `deflate-zlib` 的来源映射别名；`gorilla`、`delta-of-delta` 和 `second-order-difference` 映射到 `prometheus-xor-chunk`。别名共享规范身份，不增加排名算法；完整 DEFLATE 或联合 Prometheus chunk 不能宣称为隔离的纯 primitive。

完整可选 key 可通过 `codecs list` 查询。重点资料：[StreamVByte](docs/streamvbyte_modern_self_check.md)、[SIMDComp](docs/simdcomp_self_check.md)、[MaskedVByte](docs/maskedvbyte_self_check.md)、[FastDifferential](docs/fast_differential_self_check.md)、[Simple8b_RLE](docs/fastpfor_simple8b_rle_source_review.md)、[重写包接入](adapters/completed_rewrites/README.md)。专项自检文档中的早期批次可能已被后续重新资格验证替代，应优先核对最新证据刷新记录。

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

# lzss-raw 的冻结 Rust 实现使用 rustc，源码配方包含 edition 2021。
sudo apt-get install -y rustc cargo

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

CPU 标志必须满足所选入口清单：例如部分 StreamVByte 配方要求 AVX2，SIMDComp 使用 SSE4.1 和独立 AVX2 对象，Sprintz 还要求 BMI2/LZCNT，DZip 要求 AVX。虚拟机或容器隐藏 ISA 时，不能仅凭宿主机型号判断可用性。缺失 ISA 不通过静默替换算法解决。

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

### 3. CUDA、LibTorch 与 MKL 的选择

| 使用范围 | 所需环境 |
| --- | --- |
| 控制面、oracle 和大多数常规 CPU Codec | 上述 Python + C/C++ 环境；不需要 NVIDIA GPU、CUDA 或 PyTorch |
| 当前 DeepZip / DZip Benchmark binding | 冻结 C++ 源码与模型；构建驱动关闭 CUDA 和 HDF5 importer，不要求 Python PyTorch/TensorFlow |
| TRISTAN / CORAD | 冻结 Intel MKL **2023.1.0，build `h213fc3f_46343`** 及依赖闭包；通用 OpenBLAS 不能代替已锁定 MKL 身份 |
| WaLLoC 当前 binding | LibTorch **2.6.0+cu118、C++ ABI=0**，配套 CUDA runtime/cuDNN、CUDA **11.8 Toolkit / nvcc** 与冻结模型；当前 Benchmark 仍只声明 CPU profile |
| 独立实现的 GPU/训练扩展 | 依各自能力矩阵、GPU 架构与 source/native/SDK/run 审计另行接入；安装 CUDA 不会增加注册能力 |

**WaLLoC 依赖准备。** PyTorch 2.6.0+cu118 的 Python wheel 可作为 C++ 头文件和 LibTorch 库的分发方式；它不安装到 Python 3.14 控制面中。另建 Python 3.11 环境：

```bash
conda create -n tscompbench-torch --override-channels -c conda-forge \
  python=3.11 pip -y
conda run -n tscompbench-torch python -m pip install \
  torch==2.6.0 --index-url https://download.pytorch.org/whl/cu118
conda run -n tscompbench-torch python -c \
  'import torch; print(torch.__version__, torch.version.cuda); print("CXX11 ABI", torch._C._GLIBCXX_USE_CXX11_ABI)'

# 将 LibTorch 的位置传给构建驱动；随后仍使用 tscompbench 控制面环境。
export WALLOC_TORCH_ROOT="$(conda run -n tscompbench-torch python -c \
  'from pathlib import Path; import torch; print(Path(torch.__file__).parent)' | tail -n 1)"
conda activate tscompbench
```

预期版本为 `2.6.0+cu118`、CUDA `11.8`、ABI 为 `False`（0）。当前配方直接链接 CUDA 版 LibTorch，CPU-only wheel 或 cu12x/cu13x wheel 都不能直接替换。wheel 提供的 CUDA runtime **不包含完整 nvcc 编译工具链**，还需安装 Toolkit。

复现当前 CUDA 11.8 配方建议使用 Ubuntu 22.04 x86_64 和 GCC 11。下面的 NVIDIA APT 仓库地址只适用于该发行版；其他发行版应在 [CUDA 11.8 下载页](https://developer.nvidia.com/cuda-11-8-0-download-archive)选择对应安装方式，不能把 `ubuntu2204` 仓库用于 Ubuntu 24.04。

```bash
sudo apt-get install -y wget gcc-11 g++-11
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get install -y cuda-toolkit-11-8

export PATH="/usr/local/cuda-11.8/bin:$PATH"
nvcc --version
```

使用 `cuda-toolkit-11-8` 保持 Toolkit 版本固定；不要以滚动的 `cuda` 元包替代。当前框架驱动已写死 `/usr/local/cuda-11.8`，仅设置 PATH 或安装 Conda `cudatoolkit` 不会改写该路径。构建时可用 `CC=gcc-11 CXX=g++-11 CUDAHOSTCXX=g++-11` 指定 CUDA 11.8 兼容的 host 编译器；Ubuntu 24.04 默认 GCC 13 不是该配方的直接替代。

仅准备当前 CPU profile 的构建依赖，不要求有可运行的 GPU；若要执行独立 GPU 验证，还需 NVIDIA GPU 和兼容驱动。CUDA 11.8 GA 对应的 Linux 驱动基线为 520.61.05，具体兼容规则见 [NVIDIA CUDA 兼容性文档](https://docs.nvidia.com/deploy/cuda-compatibility/)。在 Ubuntu 实体机上，可查看并安装系统推荐的兼容驱动；已具备兼容驱动时无需重装：

```bash
sudo apt-get install -y ubuntu-drivers-common
ubuntu-drivers devices
sudo ubuntu-drivers autoinstall
# 安装完成后重启系统，再检查驱动。
nvidia-smi
```

WSL2 使用 Windows 宿主机的 NVIDIA 驱动，容器使用宿主机驱动与 NVIDIA Container Toolkit，不在其中执行上述实体机驱动安装。`nvidia-smi` 显示的 CUDA 字段是驱动支持上限，已安装 Toolkit 版本以 `nvcc --version` 为准。WaLLoC 独立 CUDA 目标固定为 `sm75`，其他 GPU 架构需要单独核查，当前注册不包含 GPU 验收。

**MKL 依赖准备。** 可在独立环境中准备锁定的 runtime，不改变控制面的 NumPy 依赖：

```bash
conda create -n tscompbench-mkl --override-channels -c defaults \
  python=3.11 'mkl=2023.1.0=h213fc3f_46343' -y
conda run -n tscompbench-mkl python -c \
  'import sys; from pathlib import Path; print(Path(sys.prefix) / "lib" / "libmkl_rt.so.2")'
```

**当前迁移限制必须处理：** `tools/build_completed_rewrite.py` 仍固定了原验证机器的 MKL 前缀，TRISTAN/CORAD 的 `DEPENDENCY_LOCK.json` 也含绝对路径；当前没有可直接覆盖它们的 `TSCB_MKL_ROOT` 环境变量。上述命令只准备 runtime，不能让这两个 Benchmark 入口自动完成跨机器构建。迁移时需将构建配置和依赖定位机制适配到实际前缀，再核验锁定文件，重新构建并执行 source/native/SDK/run 审计，刷新注册证据。WaLLoC 的 `WALLOC_TORCH_ROOT` 已支持位置覆盖，但仍逐文件核对依赖 SHA-256；版本号一致也不代表所有依赖文件匹配。不要创建原作者目录、删掉哈希门禁或把历史 PASS 复制为本机验收。

更多 runtime、模型及能力细节见[重写包接入](adapters/completed_rewrites/README.md)和对应 `DEPENDENCY_LOCK.json`。这些接入资料中的旧环境名、绝对路径和报告属于历史来源记录，不是用户必须采用的安装位置。

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

### 6. 正式实验、线程与恢复

以下配置在同一数据上比较 LZ4 / Zstd；应先完成资格检查，并构建两个入口：

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
| `clang++` / `rustc` / `nvcc` 找不到 | 按所选算法安装工具链；WaLLoC 还检查固定的 CUDA 11.8 路径 |
| 缺失 `.so`、`ldd` 显示 `not found` | 构建本机工件、安装对应 runtime，核查配方的 RPATH 和依赖前缀；不要全局加入另一个 Conda 环境的 `lib/` 目录 |
| dependency / SDK evidence drift | 按该入口接入流程重新生成并审计证据；历史报告不替代本机结果 |
| 任务不支持、资源压力或空汇总 | 检查 Preflight、Run 原始状态、eligibility 与 coverage；QUALIFICATION 和不足资格的配置不产生正式排名 |

## 测量与结果阅读

`FORMAL` 要求至少 3 次且累计 >=0.5 秒预热，至少 10 次预定重复，配置的重复最短时长为 1–3 秒。当前循环分别检查**所选范围的编码和解码方向**；E2E 还检查完整对象时长。共享计时规则在 2026-10-07 修正过，旧的总时长达标记录不能自动当作当前方向门禁合格。

CORE、PIPELINE 和 E2E 同时保留；全部已注册入口的三模式接入验证见[逐项审查](docs/all_algorithm_timing_scopes.md)。E2E 输入是内存中的 Canonical 路由视图，不包含文件读取。每个内循环对象独立创建、Finalize、解码和关闭。可选 NATIVE 与阶段计时是辅助观察，缺失值保留 null，不替代主范围时长门控，也不自动等同于上游 benchmark 的 kernel 时间。详见[计时边界](docs/native_codec_timing.md)。

资源采集目前主要支持 PROCESS CPU、RSS/PSS/USS、faults、I/O 等；进程树、设备、perf counter 和 Energy 在没有有效采集器时明确记为未采集或不支持。系统换页或线程超预算产生 `RESOURCE_PRESSURE` / `OVERSUBSCRIBED`，保留观测并按资格规则排除。

Query / Random Access 目前由 NeaTS、LeaTS 清单声明支持；persistent streaming 由 LZ4、Zstd、Brotli、DEFLATE、bzip2、XZ 清单声明支持。两类工作负载都要求配置请求开启及适配器协议支持；注册能力声明仍不等于每个新配置已取得当前正式资格。

典型输出：

```text
runs/<run-set-id>/
  frozen_config.json / environment.json / run-set.json
  datasets/<key>/*canonical.tscb / *manifest.json / *characterization.json
  task_plan.jsonl / resolved_configs.json / *_registry_snapshot.json
  events.jsonl                 # 生命周期与失败事件
  run_components.jsonl        # 权威的完整原始 Run 证据
  runs.csv                    # 可恢复的平面投影
  eligibility.csv / summary.csv / corpus_summary.csv
  comparability.csv / coverage.csv / pareto.csv / ranking.csv
  report/report.json / report.md / report.html
  report/coverage.svg / space-encode.svg / space-decode.svg
```

统计层先过滤资格，再按 DatasetID、AlgorithmID、ConfigID、ExecutionPathHash、ProfileID 和记录 schema 分组。预定重复必须完整且不重复，合格组至少有 10 次有效正式重复；压力记录不删除、不用补轮替换。报告保留 median、P25/P75、mean、SD/CV、确定性 Bootstrap 区间和 contributing RunIDs。排名只在相应比较键内进行，Coverage 独立发布，不形成跨 Track、LossMode、对象层级或设备的加权总分。

## 开发、证据与限制

```bash
python -m pytest
python -m pytest \
  tests/unit/test_measurement.py tests/unit/test_statistics.py \
  tests/integration/test_layer5_reporting.py
```

以上命令使用已激活的控制面环境。完整测试集还会消费算法专属工件、数据与审计记录；新 checkout 仅配置基础环境时不保证全量测试通过。算法专属 source / native / SDK / run auditor 位于 `tools/`；必须按对应接入文档运行。共享执行源码或二进制变化可能使旧证据失效，工厂会拒绝漂移；编译成功、注册成功、会话创建成功和历史 PASS 都不能单独代替当前五层资格。最近刷新流程见[原生入口证据刷新](docs/native_codec_evidence_refresh.md)。

当前尚未完成全量 221 条目验收，也没有所有算法在统一真实语料上的最终排名。合成 uint32 / uint28 UTS 资格不覆盖真实 int64 timestamp 或 float 数据；checked int64 StreamVByte pipeline 的现有范围只覆盖其登记数据和配置。DCT、DWT、PCA 当前继续跳过；TerraCodec 两个阻塞重写包未进入已完成接入声明。

部分重写入口依赖冻结模型、MKL 或 LibTorch，CPU-only profile 不意味着 GPU/训练/查询/增量流式全部支持。sanitizer 证据有明确范围，未重新插桩的外部二进制和未执行的 LeakSanitizer 不包含在通过声明中。详见[重写接入范围](adapters/completed_rewrites/README.md)。

本项目代码的许可证见 [LICENSE](LICENSE)；各 vendored 源码、模型和 runtime 的许可证遵循各自源锁及接入卡，不能用项目许可证覆盖上游条款。

## 目录导航

| 路径 | 内容 |
| --- | --- |
| `src/tscompbench/` | 五层控制面与 Python adapter |
| `native/include/` | Canonical、C ABI 与计时接口 |
| `adapters/` | 冻结源码、binding、补丁、合同及算法测试 |
| `registry/` | Dataset、Codec、SourceArtifact、别名与 onboarding 清单 |
| `schemas/v2/` | 配置、任务、运行、账本、统计与报告契约 |
| `configs/experiments/` | QUALIFICATION / FORMAL 实验配置 |
| `fixtures/`、`tests/` | 受控数据、golden vectors 与回归测试 |
| `tools/` | 构建、冻结、资格验证、接入和独立审计 |
| `docs/` | 专项自检、接入范围与架构资料 |

阅读顺序：[发布状态说明](RELEASE_DESCRIPTION.md) → [最近证据刷新](docs/native_codec_evidence_refresh.md) → 对应算法接入卡与实验配置。历史变化见 [CHANGELOG.md](CHANGELOG.md)，文件保留规则见 [Git tracking policy](docs/git_tracking_policy.md)。
