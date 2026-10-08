# TSDataCompressBenchMark

TSDataCompressBenchMark 是一个以源码身份、输入契约和原始证据为基础的时间序列压缩基准框架。Python 控制面负责数据准备、能力协商、任务规划、隔离执行、性能测量与统计报告；具体算法通过原生适配器接入。项目比较的是明确声明的压缩对象、配置和执行路径，保留不支持、错误、超时及资源压力记录。

本文描述 **2026-10-08 当前工作区**。Python 包版本为 `0.1.0`，数据与运行契约属于 V2；两者是不同的版本体系。本次状态说明见 [RELEASE_DESCRIPTION.md](RELEASE_DESCRIPTION.md)。

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

最近状态依据：[原生入口证据刷新](docs/native_codec_evidence_refresh.md)、[方向最短时长修正](docs/minimum_duration_direction_self_check.md)、[全量工作清单](registry/native_integration_plan.json)。详细 `build/` 与 `runs/` 证据保留在本机，通常不随 Git 分发。

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

[源码展开架构图](docs/main-runtime-framework-20261008/framework.html)可辅助阅读。它展示职责和步骤展开，包含调用容器及同步观察关系，所有箭头不能都解释为严格串行函数调用；浏览器交互尚未验证。

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

## 环境与快速开始

### 环境

`pyproject.toml` 要求 Python **>=3.14**、NumPy **>=2.5,<3**。现有验证环境为 Conda `CompressBench14`；以下命令从仓库根目录执行，通过 `PYTHONPATH=src` 使用源码，不要求预先安装包。

```bash
conda activate CompressBench14
export PYTHONPATH=src
python -m tscompbench --help
python -m tscompbench datasets list
python -m tscompbench codecs list
python -m tscompbench codecs verify
python -m tscompbench datasets verify
```

新环境也可使用兼容的 Python 执行 `python -m pip install -e .` 安装控制面；原生算法仍需单独构建。当前原生验证主要在 Linux x86_64 进行，编译器、ISA、系统库、模型和 runtime 依赖由具体 adapter 的构建脚本及源锁指定。`debug` 仅对已声明该配方的入口支持；`--profile all` 会执行该入口支持的构建组合。

`datasets/`、`build/`、`runs/` 和独立重写工作区通常被 Git 忽略。新 checkout 需要准备 Manifest 指定的数据和依赖；`datasets verify` 会核对文件存在与哈希，不负责下载数据。合成数据有对应 `tools/generate_*_fixture.py`，应使用匹配的生成器与固定参数。源资料目录保持只读，安全补丁只应用于构建副本。

### 跑通一个资格实验

以已提供的 LZ4 配置为例，需要匹配的 `national_illness` 数据。现有合格工件可直接使用；首次运行需要构建，并满足清单要求的原生/SDK 证据门控。

```bash
python tools/build_codec.py lz4-frame --profile all
python -m tscompbench run validate \
  configs/experiments/lz4-frame-qualification.toml \
  --output-root runs --run-set-id lz4-local-qualification
python -m tscompbench run report \
  configs/experiments/lz4-frame-qualification.toml \
  --output-root runs --run-set-id lz4-local-qualification --resume
```

`QUALIFICATION` 用于边界和接入检查，不参加正式性能排名；出现空 `summary.csv` 可以是预期结果。检查 raw、诊断、eligibility 和 coverage，而不是只看汇总行数。

### 正式实验与恢复

以下配置比较 LZ4 / Zstd，需要对应构建和已通过门控的执行工件。

```bash
python tools/build_codec.py zstd-frame --profile all
python -m tscompbench run validate \
  configs/experiments/zstd-lz4-formal-comparison.toml \
  --output-root runs --run-set-id zstd-lz4-local-formal
python -m tscompbench run report \
  configs/experiments/zstd-lz4-formal-comparison.toml \
  --output-root runs --run-set-id zstd-lz4-local-formal --resume
```

从已有批次恢复时，对同一配置、输出目录和 RunSetID 的 `run validate` 加 `--resume`。已有路径拒绝覆盖；恢复会核对冻结配置、环境、工件和日志。修改冻结条件后应使用新 RunSetID，不覆盖或补写旧批次。

其他分步命令为 `run init`、`run prepare`、`run plan`。CPU affinity 必须属于当前进程可用集合；示例中的历史 CPU 0 不应直接当作另一台机器的默认值。

## 测量与结果阅读

`FORMAL` 要求至少 3 次且累计 >=0.5 秒预热，至少 10 次预定重复，配置的重复最短时长为 1–3 秒。当前循环分别检查**所选范围的编码和解码方向**；E2E 还检查完整对象时长。共享计时规则在 2026-10-07 修正过，旧的总时长达标记录不能自动当作当前方向门禁合格。

CORE、PIPELINE 和 E2E 同时保留；E2E 输入是内存中的 Canonical 路由视图，不包含文件读取。每个内循环对象独立创建、Finalize、解码和关闭。可选 NATIVE 与阶段计时是辅助观察，缺失值保留 null，不替代主范围时长门控，也不自动等同于上游 benchmark 的 kernel 时间。详见[计时边界](docs/native_codec_timing.md)。

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
PYTHONPATH=src conda run -n CompressBench14 python -m pytest
PYTHONPATH=src conda run -n CompressBench14 python -m pytest \
  tests/unit/test_measurement.py tests/unit/test_statistics.py \
  tests/integration/test_layer5_reporting.py
```

pytest 及需要的原生依赖应在开发环境中安装。算法专属 source / native / SDK / run auditor 位于 `tools/`；必须按对应接入文档运行。共享执行源码或二进制变化可能使旧证据失效，工厂会拒绝漂移；编译成功、注册成功、会话创建成功和历史 PASS 都不能单独代替当前五层资格。最近刷新流程见[原生入口证据刷新](docs/native_codec_evidence_refresh.md)。

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
