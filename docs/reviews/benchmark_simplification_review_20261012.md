# TSDataCompressBenchMark：对照公开 benchmark 的精简审查

审查日期：2026-10-12。对象为当前工作区源码，Git 基点 `6300188e70faf7d93f3a97f87f0d9cebfb7cdf4c`，包含已有未提交修改。本次仅新增此审查文档。

## 1. 判断

**当前框架存在明显的流程过重和职责耦合，尤其在 V3.2 正式 comparison 路径。优先应减少重复验收、降低用户配置负担、分开性能测量与资源分析，并把发布验收移出日常实验的主要使用路径。**

正确性、共同输入、完整成本和计时边界本身并不过分。问题在于“一个结果是否可信”“一种算法是否完成接入”“一组比较能否支撑论文结论”“当前版本是否完成全部承诺”被过度绑定，导致局部工作需要承担整体验收成本。

这一判断有两个边界：

- 项目仍有 `run` 与 V3.2 `comparison` 两套入口；已有单数据集、单算法资格配置。不能说所有本地运行都强制两算法、两来源，或每次运行都执行 911 条发布映射。
- 外部项目接口更简单，不意味着它们覆盖了本项目的 timestamp、validity、模型依赖、流式 Finalize 和组合 pipeline 语义。精简应按实际声明的能力进行。

## 2. 联网对照结果

以下链接均于本次审查联网读取。论文方法部分、官方使用入口与运行脚本分别说明；没有运行这些项目或复现其性能数值。

| 项目或论文 | 公开做法及本次阅读范围 | 对本项目的启示 |
| --- | --- | --- |
| **[FCBench](https://github.com/hpdps-group/FCBench)**，PVLDB 17(7), 2024；[论文](https://www.vldb.org/pvldb/vol17/p1418-tao.pdf) | 阅读论文 §5、官方 README、`eval_all.sh`、`awk_all.sh`、`fcb_res.py`。覆盖 8 个 CPU、5 个 GPU 方法及 33 个数据集；论文每方法/数据重复 10 次，报告平均值，并用 Friedman/CD 图比较跨数据集排名。使用说明支持分别运行方法。 | 通用压缩指标、查询实验、roofline 分析可以服务于不同研究问题，不必都成为一次普通测速的准入条件。统计不是可以全部删除的装饰。 |
| **[Sprintz](https://github.com/dblalock/sprintz)**；[论文原文](https://arxiv.org/html/1808.02515v1) | 阅读论文 §5 和 README。计时采用 10 次中的最好值；UCR 85 个数据集的压缩率比较使用 Nemenyi 检验。显式说明整数化、数据拼接、布局和内存驻留。 | 先把输入变换、计时边界和比较目标解释清楚，再选择统计方法。它与 FCBench 的时间汇总方式不同，不能把某一种汇总或检验硬写成所有 benchmark 的唯一标准。 |
| **[ALP](https://github.com/cwida/ALP)**，SIGMOD 2024；[自有数据指南](https://github.com/cwida/ALP/blob/main/how_to_benchmark_your_dataset.md) | 阅读 README、使用指南；未据此声称已阅读全文或完成复现。用户提供 `id,column_name,data_type,path,file_type` 五字段 CSV，运行 `bench_your_dataset`，输出 bits/value、压缩/解压 cycles/value。论文复现有独立 `publication/script/master_script.sh` 入口。 | 论文复现流程可以很完整，用户接入自己的数据仍可以很小。内部严格模型不必变成用户手写多份合同。 |
| **[lzbench](https://github.com/inikep/lzbench)** | 阅读官方 README。内存载入后压缩、解压并核对原始内容；统一构建各 compressor。CLI 可选择文件、算法、级别、测量时长或迭代次数。 | 最小路径可以围绕“数据、算法、重复、恢复校验、结果”建立。它是字节压缩工具，不能直接替代本项目的时序对象语义。 |
| **[LibPressio](https://robertu94.github.io/libpressio/)**；[插件接口](https://robertu94.github.io/libpressio/writingacompressor.html) | 阅读官方总览和 compressor plugin 文档。compressor、metrics、IO 分开；CLI 按需选择 time、size、error 等指标。 | 扩展能力与指标应按任务启用；不必让每个 codec、每次实验承担全部指标与生命周期协议。 |
| **[TerseTS](https://github.com/cmcuza/TerseTS)** | 阅读官方 README。C API 的主要数据结构为 double 数组与 byte 数组，主要操作为压缩、解压和内存释放；包含有损和无损方法。README 明确当前为 beta。 | 说明简单公共接口可行；其语义较窄，不能用它证明本项目的 T/V/mask 或完整依赖账本应被删掉。 |

方法工具也支持分开基础测量和额外分析：

- [Google Benchmark 用户指南](https://google.github.io/benchmark/user_guide.html)：动态确定迭代次数，可配置 warmup、repetitions、random interleaving；提供均值、中位数、标准差等报告。其 **Profiling** 部分明确在独立 benchmark run 收集 profile，输出单独报告。
- [pyperf 运行指南](https://pyperf.readthedocs.io/en/latest/run_benchmark.html)：校准、进程重复和 worker 内 warmup 都有依据；不稳定示例保留数值并发出警告。它还明确 pystats 的额外开销会使对应计时失去意义。由此支持“保留原始观测，限定可用结论”，而不是自动把所有观测视为合格。
- [Time series compression survey](https://arxiv.org/html/2101.08784v2)：阅读分类及讨论部分。其结论按数据特性、误差、速度和训练需求区分适用方法；文中跨算法结果是对原论文报告的汇集，不能当作统一机器上重跑的 benchmark。

**外部实现也有不足，不能照搬。** FCBench 当前仓库的 `eval_all.sh` 有大量方法调用被注释；结果处理脚本有针对特定数据集的硬编码和占位值；README 说明因 bit-packing 错误未展示 BUFF。其论文说明部分方法调用自己的内置计时函数。因此，应借鉴其可理解的使用入口和研究范围划分，保留本项目对失败、缺失、共同边界与恢复正确性的更明确处理。

## 3. 当前源码中最值得精简的八处

### 3.1 完整边界验收在正式重复中反复执行：优先级最高

证据链：

- [comparison/runner.py:940](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:940)：qualification 已验证冻结真实矩阵及额外资格样本。
- [comparison/runner.py:1533](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1533)：steady 正式调度每个槽位重新调用 `execute_task`，只传一个 repetition index。
- [execution/orchestrator.py:136](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:136)：该函数在 repetition 循环之前无条件执行 `preflight_task`。
- [execution/preflight.py:199](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:199)：preflight 会启动完整边界测试；同函数还执行保存码流的独立恢复。

这是正式计时区间之外的重复工作，但它消耗执行预算，并可能改变之后的机器状态。不能把这笔成本说成 encode timer 内直接增加的时间。

[历史运行记录:104](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/reviews/v32_current_scope_acceptance_20261011.md:104) 已具体记载：旧 timestamp 资格包含 49 个边界案例，development 粗估约 143 秒；32 个 LZSS 正式槽位重复这套检查，推算已超 3600 秒总预算。后续总预算改为 10800 秒并重新冻结运行。**143 秒是规划估计，不是实测整套资格均值，也不能据此承诺精简后的实际加速倍数。**

建议把 preflight 拆为算法接入/边界验收、实际输入检查、当前输出恢复检查。优先在同一冻结运行中复用已通过的重型边界套件；复用键包括 codec/build、adapter、参数、输入语义及验证器版本。不同实际输入仍做对应检查，正式试次仍验证自己的输出、误差、Finalize 和成本。持久化独立恢复按声明的产物/依赖语义验证，随机或状态相关产物不能靠旧产物代替。

### 3.2 强制 collector 与主计时互相阻断

[comparison/runner.py:304](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:304) 拒绝关闭 collector 的 CPU 正式 comparison。[measurement/v32_protocol.py:522](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/v32_protocol.py:522) 把 harness/collector 扰动超阈值列为 pilot 不合格，正式执行又要求 pilot 通过。

[历史记录:88](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/reviews/v32_current_scope_acceptance_20261011.md:88) 中，Snappy decode 的 collector 对照相对变化 `0.152526` 超过 `0.15`，未产生 FORMAL。另有 stream XZ 超 `0.20` 的记录。这说明当前门禁确实在影响实际流程；on/off 对照差异同时包含测量噪声，不能全部解释为采样器的确定性开销。

建议默认主计时采用低扰动观测，把高频 RSS、线程采样及其他 profiling 放到单独 pass，明确不是同次观测。保留时钟信号校准、超时/内存限制及实际可实施的资源控制。若线程上限或峰值资源的主张缺乏可靠证据，则这些主张不能获资格；不能通过关闭采样继续宣称“同次精确验证全部资源”。

`5%`、`15%`、`20%` 可以是具体实验的预声明政策，但本轮没有找到它们作为所有压缩 benchmark 通用硬标准的依据。

### 3.3 普通固定算法测速也强制独立 development corpus

[bundle 加载器:190](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:190) 强制 development 数据与至少四类资格样本；[run_pilot:574](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/v32_protocol.py:574) 强制 development/test corpus ID 不同，comparison 还检查内容重叠。

训练模型、搜索超参数、根据结果选择 codec/configuration 时，独立开发数据有实际作用。已经固定算法和配置、只确定重复粒度及计时预算，则不必自动套用同等的数据留出门禁。Google Benchmark 与 pyperf 展示的是对被测 workload 校准迭代次数。

建议把“模型训练/方法与参数选择”与“timer calibration”分开：前者执行适合时序依赖的留出政策；后者允许在已声明的评价 workload 上校准，记录算法参数未变、校准值不计入正式结果，以及预热/cache 状态。若利用校准结果选择赢家或修改算法参数，仍属于选择过程。

### 3.4 两方法、两真实来源是特定比较政策，不应成为基础运行标准

[GroupSpec:215](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:215) 对 `CORE_COMPARISON` 要求至少两个不同方法及两个真实来源；[planning.py:182](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/planning.py:182) 检查实际覆盖；发布审计进一步要求活动 complete codec 的两来源覆盖。

这里的 CORE 是比较组成员/范围角色，与 `COMMON_NATIVE_API` 的 CORE 计时边界不是一个概念。项目既有 `run` 路径和单算法资格配置，因此这不是全项目统一限制。

建议现代统一入口也允许单方法、单数据集、合成边界输入和回归测试，并输出其实际范围。对具体来源的两个方法比较可以成立；对跨来源总体的结论需要采样与代表性设计。两个真实来源只是当前政策下限，既不是每次测速的必要条件，也不自动证明广泛代表性。

### 3.5 多份互相绑定的文档成为用户配置负担

[load_comparison_bundle:190](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:190) 包含 contract、corpus、group、config_map、expected_matrix、protocol、analysis_policy、dataset_bindings、CPU affinity、seed、development 与 qualification 数据等字段。[decision.py:58](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/decision.py:58) 还派生并绑定研究决策文档；其中部分内容已经是自动生成，不能算作全由用户重复手填。

这些字段大多有用途，但不适合让一般使用者直接理解和维护全部内部模型。建议公开一份小型 experiment 配置：数据、方法/参数、语义/误差目标、计时边界、重复/预算、输出。CPU 默认策略和资源实值自动解析并记录；高级使用者可覆盖。内部计划、内容指纹、预期拒绝与来源映射由编译器产生，研究问题和高级统计策略按需提供。

不建议直接删除 typed contract 或改成无校验字典。应减少公开配置面，消除重复事实，而非取消内部一致性验证。

### 3.6 整个 Python 控制面冻结导致无关变更使执行失效

[control_plane_snapshot:156](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:156) 对 `src/tscompbench` 下全部 Python 文件做 SHA 快照；[execute_comparison:1384](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1384) 发现任何差异便要求新 RunSet。因此只修改报告渲染器也会触发这个执行门禁。

建议区分测量身份与分析/展示身份。codec、native build、adapter、preprocess、计时执行器和影响测量的依赖变化，失效对应测量资格；分析/渲染变化生成新的报告版本和源码指纹。原始测量及原版本报告继续保留。划分依赖前不能简单停止记录全源码来源，也不能让旧 codec 数据获得新 codec 的身份。

### 3.7 统计政策写死过多，但统计计算不是首要成本

[AnalysisPolicy:24](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:24) 固定支持 schedule-block bootstrap、均值时间比、Bonferroni 区间和固定分母政策，默认 4000 次 bootstrap、至少 4 个配对 block、2% 实际效应与 10% 相对区间半宽。[effect:482](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:482) 据此产生结论。

这些方法对相应设计有依据，代码确实按真实共同 block 重采样，而不是把 inner iterations 当独立样本。当前 [analysis.py:590](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:590) 也已经为存在的有效记录生成大小、时间的描述统计；不能说 INCONCLUSIVE 会让全部数值消失。

建议基础报告始终展示实际观测、完成数和描述统计；比较推断作为分析选项。效应界限、精度目标和多重比较范围随具体问题设定。固定语料的运行噪声区间不等于跨来源泛化区间。FCBench/Sprintz 的跨数据集秩检验也不是本项目固定语料配对时间区间的直接替代。

优先级是解耦推断与运行准入，**不是先把 bootstrap 从 4000 次降到 1000 次**。本次没有剖析证明 bootstrap 是主要耗时。

### 3.8 发布、迁移闭包与实验框架本体过度绑定

当前台账统计为：

| 内容 | 本次实际读取的数量 |
| --- | ---: |
| 计划条目 | 684 |
| 其中 `kind=NORMATIVE_REQUIREMENT` | 241 |
| 所有 `normative=true` 条目，含交付/完成门禁等 | 277 |
| 审查交叉引用 | 117 |
| 能力矩阵快照行 | 110 |
| 发布验收映射行 | 911 = 684 + 117 + 110 |
| 发布证明类别 | 28 |

[台账生成器:1](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/build_v32_requirement_ledger.py:1) 保留叙述、列表和表格条目，包括上下文；[发布工具:1](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/publish_v32_requirement_acceptance.py:1) 明确 publish 先重复 release audit；[completion audit:375](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_completion.py:375) 执行全范围结果要求。

这些工件可以证明某次历史交付的覆盖范围，但**911 行不是 911 个独立科学标准，也不是每个 trial 执行的 911 项检查**。大量固定 lane、源码闭包、SDK、回归和逐条证明属于发布或接入工作。

建议分别定位：每次实验的有效性检查、codec/能力接入 CI、版本发布验收、可选论文复现清单。历史证明保留为历史证据，不继续扩张成普通用户的操作主流程。已有 source parity/重写真实性审计按相应声明启用；它不能代替实际压缩恢复测试，也不必绑在每个数据文件测速上。

## 4. 应保留的最小可信核心

1. **共同任务语义。** 同一比较使用共同原始输入、类型、布局和恢复目标。是否包含 T/V/mask、schema、模型或索引取决于声明的边界；组件实验明确限于组件。
2. **实际恢复验证。** 无损按声明的按位/语义标准验证；有损验证原始域误差与非有限值政策。流式输出完成 Finalize，结果不能借未声明的原始数据完成恢复。
3. **完整成本。** 用同一原始分母，说明 payload、headers、必要 schema/模型/索引等依赖及共享摊销方式。不混淆组件 payload 与完整对象存储成本。
4. **可解释的计时。** 说明 API/PIPELINE、I/O、初始化、context、cache、warm/cold 以及同步边界；合理校准和重复，保留原始时长与环境。
5. **真实失败记录。** 不支持、超时、错误和未完成显式记录；不以 0 代替缺失，不通过删失败改变宣称范围，不把同源窗口和重复执行当新增来源。
6. **可追溯配置。** 记录数据与构建指纹、实际参数、seed、线程/资源设置及执行版本；报告从已有事实生成，避免通过重测修饰旧结果。

这些是保住结果意义的基础，不需要再配一套庞大的逐条验收文档才能执行。

## 5. 建议的使用结构和实施顺序

| 使用场景 | 默认承担的工作 | 按需增加 |
| --- | --- | --- |
| 日常测速/回归 | 一份配置、必要资格复用、计时校准/预热、重复、当前输出校验、raw 与描述报告 | 单方法/单数据集也可运行；保留噪声和范围标记 |
| 研究比较 | 上述核心，明确比较问题、共同资源和实际调度 | 方法/参数选择留出、随机配对、CI/多重比较、跨来源设计、冷启动、stream/query/P2、单独 profiling |
| 接入与发布 | 声明能力的边界套件、CI 和版本检查 | 源码移植/重写真实性、SDK、全范围覆盖、论文复现和历史交付映射 |

这是建议的组织方式，不是新增三套必须逐条验收的规范，也不建议复制出三套 runner。

基础执行路径可收敛为：

```text
读取一份实验配置
  → 解析并记录实际输入、构建与测量计划
  → 执行必要资格，复用未失效的重型边界结果
  → 校准 / 按目标预热
  → 重复 encode + decode，并验证当前输出
  → raw JSONL/CSV + 描述报告
```

建议分三步落地：

1. **先解决已证实的重复工作。** 拆开 heavy boundary qualification 与正式 trial；把高频 profiling 从主时间测量中解耦。验证资格失效行为、当前 trial 校验和时间边界均正确，再用同一 workload 实测总执行成本。
2. **再收敛用户入口。** 一份配置生成内部计划；在现代路径支持局部实验；区分训练/选择留出与校准；复用共享执行、存储和报告逻辑，保留不同生命周期的真实差别。
3. **最后精简政策与文档。** 测量/分析身份分开；统计作为相应研究问题的选项；发布清单迁至 CI/版本流程；稳定后归档历史版本配置。不要先删除历史工件或通过把 FAIL 改成 PASS 实现“简化”。

## 6. 规模与证据限度

新增本文件前，按目录和文件后缀统计：

| 目录 | 文件数 | 文本行数 |
| --- | ---: | ---: |
| `src/tscompbench`，Python | 120 | 42,222 |
| `tools`，Python/JSON/Markdown | 93 | 26,690 |
| `tests`，Python/JSON/Markdown | 127 | 22,558 |
| `schemas`，JSON | 52 | 6,073 |
| `configs/comparisons`，JSON | 71 | 53,496 |
| `docs/reviews`，Markdown/JSON/Python | 35 | 143,254 |

行数包含生成配置和审查工件，只说明维护面，不能独立证明设计错误。这里没有给出“能删掉百分之多少代码”或“能加速多少”的未经验证承诺。Python/NumPy 版本门槛是否可以降低也需要单独兼容性验证，本次不据版本号直接认定为过度设计。

本次完成的是联网文献与官方项目阅读、当前源码调用链检查、历史记录核对及条目统计。没有运行新的正式 benchmark，没有复测历史时间，没有修改运行代码、配置、测试或已有验收证据。公开项目的在线源码可能继续变化；以上比较以本次读取内容为准。
