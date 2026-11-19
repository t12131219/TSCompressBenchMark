# TSDataCompressBenchMark

TSDataCompressBenchMark 是一个面向时序数据的压缩评测框架。它分别评测时间戳（T）、数值（V）和原生联合编解码（TV），也支持固定 T 或固定 V 的组合对照。Python 控制层负责冻结计划、运行调度和报告复算，原生 worker 通过 C ABI 调用插件。一次运行使用一个 `run_id` 和一份主账本，保留通过、预期拒绝、失败和取消等结果，而不只展示成功样本。

**当前进度：M0–M4 已完成各自范围的阶段验收。** 目前没有正式算法资格或性能排名；M5 完整服务矩阵与 M6 稳定版交付尚未完成。

## 快速开始

从仓库根目录运行以下命令。原生构建面向 **Linux x86-64**，需要主机提供 **CMake 3.22+** 和支持 **C11/C++17** 的编译工具链。Python 和项目依赖使用 **`tsbench`** Conda 环境，不使用 `base`。以下锁定清单用于创建 Linux 环境；已有 `tsbench` 时跳过第一行：

```sh
conda create -n tsbench --file environment/tsbench-linux-64.explicit.txt
conda activate tsbench
```

### 运行最小无损示例

```sh
cmake -S . -B build/smoke -DCMAKE_BUILD_TYPE=Release \
  -DTSBENCH_PLUGINS='raw-store;zstd;alp-auto' \
  -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"
cmake --build build/smoke --parallel 4
ctest --test-dir build/smoke --output-on-failure
scripts/smoke.sh build/smoke
```

默认 smoke 用两个 f64 fixture 验证三种路线（共 **6 个用例**）：raw-store 作为无压缩基线，Zstd 压缩规范值字节，ALP 对 f64 数值编码。每个用例都解码并按位校验。预期输出包含 `all_verified: true` 和 `run_id`；这是功能检查，不是性能测量，也不替代文件级隔离恢复。当前示例不需要 Rust、Bubblewrap、历史结果或相邻的源码工程。

`./bmk` 可直接运行，无需安装本项目。将 `RUN_ID` 替换为上一步的 `run_id`，可从同一运行的封存记录复算报告，无需重新编解码：

```sh
./bmk smoke-report RUN_ID
```

### 查看插件、数据与服务计划

```sh
./bmk plugins list
./bmk check-sources
./bmk check-corpus --parse
./bmk plan --suite first_batch_service_v4 --out results/first-batch-service-plan.json
./bmk service-plan-verify --plan results/first-batch-service-plan.json
```

最后两条命令生成并核对首批服务范围：**204 个展示格、264 个原子关系、564 个场景义务**。它们不运行 codec，也不表示服务已经通过。计划文件不会被覆盖；再次生成时请使用新路径。参见[首批服务范围](docs/contracts/first-batch-service-scope.md)。

## 如何比较不同路线

- **T / V / TV**：比较完整 TV 方法时，可固定 T 或 V 一侧，观察另一侧的影响；原生 TV 和组合 TV 分开标明，按共同任务与产物边界比较。
- **单线程 / 多线程 / SIMD**：在共同任务、质量约束、计量边界和资源预算下比较，不要求实际线程数或指令集相同。框架外层并行、算法内部并行和 SIMD 后端分别记录；线程区间相加不是墙钟耗时。
- **原生流式 / 外部包装的批算法**：可以在同一个有界流服务合同下比较，前提是使用相同的输入到达、输出与结束规则，验证背压和恢复，并把包装的缓冲、延迟和字节开销计入结果。批算法加包装不等于原生流式，也不能冒充严格逐点在线。首批完整服务对照尚未验收。

详细规则见[比较合同](docs/contracts/statistics-and-comparison.md)与[原生功能清单](docs/contracts/first-batch-native-requirements.md)。首批登记的是 **12 个实现选型、36 条候选原生路线**，不是 36 个独立算法。Gorilla 原生 TV 使用 C11，C++ 代码是 ABI 适配层；ALP AVX512/AVX512BW 后端保留，宿主不支持时记录为 `pending_supported_runtime`；CORAD 在当前冻结质量合同下的拒绝记录也保留。

## 阶段状态

| 阶段 | 当前范围 |
| --- | --- |
| M0 | [首批范围与工程骨架](docs/m0-acceptance.md)已冻结。 |
| M1 | [最小无损闭环](docs/m1-acceptance.md)：18 个产物验证并独立恢复。 |
| M2 | [计量与调度协议](docs/contracts/m2-frame-timing.md)：两次独立诊断各验证 144 个批次；未开放正式计量。 |
| M3 | [原生功能与数据管线覆盖](docs/m3-acceptance.md)：覆盖 36 条候选路线，并验证 T/V 派生、TV 组合、跨格式与位片路线。 |
| M4 | [剖析与测量对照](docs/m4-acceptance.md)：28 个试验覆盖 ALP 融合内核、Zstd 工作线程重叠和 XZ 不可观测的内部阶段。剖析与主计时分开。 |
| M5 | 完整有效服务矩阵未执行。 |
| M6 | 稳定版与离线交付未验收。 |

## 仓库与复现边界

| 目录 | 用途 |
| --- | --- |
| `src/tsbench/`、`bmk` | Python API、CLI、计划、编排及分析。 |
| `include/tsbench/`、`native/`、`plugins/` | 公共 ABI、原生执行层和插件。见[本地 codec 接入指南](docs/plugin-authoring/local-codec.md)。 |
| `catalog/`、`configs/`、`schemas/` | 插件注册、工作负载与实验配置、数据合同。 |
| `datasets/`、`assets/`、`third_party/` | 冻结语料与 fixture、运行资产、源码归档与来源记录。见[语料合同与归因](docs/contracts/first-batch-real-corpus.md)。 |
| `environment/`、`tests/`、`scripts/`、`tools/` | 依赖锁、测试、运行入口与维护脚本。 |

- 仓库不包含完整本地语料镜像 `datasets/raw/unique/`，也不提交 `build/`、`results/`、`dist/`。快速开始所需 fixture 和源码归档保留；语料维护脚本需要完整原件时应另行准备。文档中引用的历史运行路径指向本地证据，不保证在 GitHub 上可打开。
- 不设置 `TSBENCH_PLUGINS` 时，CMake 根据 [`catalog/plugins.toml`](catalog/plugins.toml) 构建启用的插件。全插件构建如启用 pcodec，需要 `cargo` 和 `rustc`；文件级隔离恢复需要 Bubblewrap 和可用的 Linux 命名空间。
- 阶段验收测试依赖历史封存证据，不适合作为新克隆后的首个检查。以下合同测试不需要历史账本：

```sh
PYTHONPATH=src "$CONDA_PREFIX/bin/python" -B -m unittest \
  tests.contracts.test_document_schemas \
  tests.contracts.test_comparison \
  tests.contracts.test_service_scope
```
