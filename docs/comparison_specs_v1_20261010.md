# V3.2 比较规范、冻结矩阵与真实比较包（2026-10-10）

本批将 V3.2 §7.1、§7.7–7.9、§14、§15、§17 的比较入口落实为可执行合同，
对应独立审查 F01–F15 中原始对象可比性、公共投影、方法去重、来源独立性、
固定分母、选择泄漏和误差保证的控制要求。
合同编译成功表示事前定义一致；实际正确性、冷恢复、成本闭合、计时资格与结果完成
仍须执行器提供新的证据。

## 工件与接口

- `src/tscompbench/comparison/models.py`：七类不可变规范、语义检查与 MethodID/ImplementationID。
- `src/tscompbench/comparison/schema.py`、`schemas/comparison/v1/`：九个闭合 JSON Schema；
  根和嵌套对象均拒绝未知字段，版本明确为 `tscb.*.v1`。
- `src/tscompbench/comparison/planning.py`：完整冻结矩阵编译、真实注册配置归一化、
  活动范围检查、实际配置误差绑定、执行作业与矩阵单元绑定。
- `src/tscompbench/comparison/projection.py`：公共比较键和完整路径披露。
- `tools/build_v32_comparison_bundles.py`：四个具名组的事前冻结生成器；不运行 codec。
- `registry/comparison_datasets/v32_20261010/`：26 份 canonical source 注册，
  其中 8 份真实派生任务、16 份四模式资格样本、2 份独立开发样本。
- `configs/comparisons/*-v32-20261010.json`：保留的四份原始 v1 冻结包。
- `configs/comparisons/*-v32-20261010-v2.json`：四份当前默认的 v2 冻结包，
  启用每 1ms 一次的父进程线程观测；原始 v1 文件和身份不覆盖。
- `src/tscompbench/comparison/analysis_extensions.py`：只读原域质量、实际成本 Pareto、
  来源平衡与四能力视图；不调用 codec。
- `src/tscompbench/comparison/report_renderer.py`：完整固定矩阵的独立 HTML 展示。

公开 API 由 `tscompbench.comparison` 导出：

```python
from tscompbench.comparison import (
    TaskSpec, ComparisonContract, GroupSpec, CorpusSpec,
    MethodConfigMap, ExpectedOutcomeMatrix, ExecutionJob,
    compile_group_plan, public_projection, validate_job_for_cell,
    method_id, implementation_id, registered_source_closure_digest,
)
```

每种规范使用 `.from_document(dict)` / `.load(Path)` 创建，使用 `.to_document()`
获得独立副本；`.serialized` 为自有的 canonical JSON bytes，`.id` 为内容身份。
新增身份使用 `v3:<domain>:sha256:...`，现有 v2 AlgorithmID、SourceArtifactID、DatasetID、
ConfigID 保留各自原口径。

调用顺序是先编译整组，再为真实作业调用 `validate_job_for_cell()` 与
`public_projection()`；公共投影本身不能替代注册配置绑定或实测资格。

```python
plan = compile_group_plan(
    group, contract, corpus, configs, expected,
    codec_registry=codecs, active_codec_keys=active_keys,
)
validate_job_for_cell(group, plan.cells[0], task, job)
projection = public_projection(contract, task, job)
```

MethodID 由审核过的机制、语义变体、语义版本和定义摘要生成，显示名称不参与身份。
ImplementationID 另外绑定 MethodID、来源工件、来源闭包和实现变体。
别名、参数点与 build 副本不能重复增加独立方法数；GroupSpec 的等价类必须完整分割成员。
组中的来源摘要必须与实际注册的根 key 一致；别名、退出项和范围外登记无法通过组准入。

## 公共投影与误差口径

完整原始对象比较固定 track、原始逻辑 schema/content、恢复、fidelity、成本、
workload/state、计时边界、机器/资源、测量/分析及配置选择政策。
DIRECT、EXACT_WIDEN、BYTE_SERIALIZATION、独立列与 JOINT 路径可以完成同一原始任务，
但每个作业仍保留实际输入、recipe、view、path hash、来源/build/runtime、ISA 与配置身份。
COMMON_NATIVE_API 另将实际输入内容/schema 纳入公共键；FIXED ISA 另将实际 ISA 纳入键。
因此方法内部表示、独立列和 joint 分别披露，不能偷偷更换原始比较对象。

LOSSLESS、FIXED_ERROR 与 QUALITY_CURVE 是独立协议。
无损作业必须声明完整原始 bits 保留；经验曲线可以含有界、无界和率控制方法，
保留各自保证类型，并明确不取得固定误差榜资格。
FIXED_ERROR 需要相同 metric/unit、完整原域总保证、阈值不超过组预算。

当前编译器对注册 ABS/ABSOLUTE 模式提供可执行映射：
`error_bound_type` 必须由 manifest 声明，归一化后的 `error_bound` 与声明阈值按 Decimal
数值相等，metric 必须为 `MAXAE_V1`，unit 必须为 `ORIGINAL_VALUE_UNITS`。
不能用较大实际界与较小自声明界骗取固定误差准入。
未实现的误差模式映射失败关闭；宣称原域总保证而允许 LOSSY_CAST 或未核算预处理也失败。
REL/rate/precision 以及有损转换的总误差推导须单独落实；样本误差小不能证明普遍保证。

## 冻结分母与来源独立性

ExpectedOutcomeMatrix 必须恰好覆盖每个 TEST/UNSPLIT 数据集 × 每个成员 × 每个合法配置。
PASS、REJECT、BLOCKED 均在计划分母，编译器不观察结果并删行。
源域/任务拒绝与 adapter/environment 不可用区分，后者必须记 BLOCKED。
核心预期 REJECT/BLOCKED 仍是核心缺口，不能缩小核心成功分母。

真实来源独立性按来源 family、entity、independence unit 及全部父/祖先 DatasetID
保守合并；同原文件的窗口、列、UTS/MTS 任务最多计一个独立来源。
拒绝循环派生、伪造父关系，以及将 synthetic lineage 升格为真实来源。
CORE 至少两种方法和两个独立真实来源；来源声明与证据的真实性仍需来源审核。
TRAIN/VALIDATION 不进入评价矩阵，不能设为 CORE；选择数据必须事先登记为开发成员，
且不得与评价对象共享同一 logical content。
配置预算按 MethodID 汇总到全部实现，并拒绝归一化后重复的配置点。

## 四个真实包的确定范围

| 组 | CORE / 参考成员 | 真实任务 / 独立来源 | 全矩阵 / CORE 单元 |
|---|---|---:|---:|
| G-BYTE-LL | lz4-frame、zstd-frame、snappy-raw | 4 / 2 | 12 / 12 |
| G-FLOAT-LL-F64 | alp、alp-rd、chimp、chimp128、elf、elf-plus、elf-star、self-star；LZ4/Zstd 参考 | 4 / 2 | 40 / 32 |
| G-INT-LL-I16 | sprintz-delta、sprintz-fire、sprintz-fire-huff0、neats-lossless-i64、leats-lossless-i64；LZ4/Zstd 参考 | 4 / 2 | 28 / 20 |
| G-FLOAT-ABS | serf-qt、serf-xor、zfp-accuracy-1d，MaxAE=0.001 原值单位 | 4 / 2 | 12 / 12 |

合计 92 个事前评价单元，全部保留具名承诺成员，预期 PASS。
该预期基于源注册结构合法性与数据域证明，不是已观察正确性或 FORMAL 完成。
ALP 与 ALP-RD 是各自强制路径；没有使用每个样本的二者最佳值代替自适应 ALP。
各相关方法保留共享来源标签和实质变体，不把别名/参数/build 当新方法。

浮点/字节/ABS 共用现有本地 ETTh1 与 weather：事前固定最前 8192 行，
MTS 保留前四个原始 f64 列，UTS 保留第一列，数值、顺序和单位不改。
这些是 VALUE 任务，源时间戳不在原始 VALUE 对象内；没有声称覆盖 T+V。
当前 ABS 真实任务为 f64，f32、特殊 IEEE、mixed、ND、validity、T+V 仍须另外冻结扩展集。

整数任务来自两个不同来源族：PEMS04 的 feature-axis 0，
以及 national_illness 的 `AGE 0-4`、`NUM. OF PROVIDERS` 原计数列。
PEMS04 feature 0 全档案 5,216,544 个值均为整数，范围 0–919；
两列 illness 全档案 1,932 个值均为整数，范围 98–24,097。
全源域证明通过后，再固定最前 8192 行（短文件完整 966 行）、前四个 sensor
或两列 illness 和第一列 UTS；逐字段向 i16 转换再回到源 dtype，验证数值精确相等。
这里定义的是有证据的原始 typed i16 任务，没有量化，也不声称恢复原 f64 文件位模式。

每种 dtype 另固定 constant、linear、periodic、random 四模式 × UTS/MTS 的 8 份资格数据，
N=257、M=1/4、seed=20261010；开发样本 N=1027、M=3、seed=20261011。
这些内容与真实评价对象不同，仅服务资格和开发 pilot，不增加真实来源分母。

源 URI、retrieval 与 license 状态继承已有本地 manifest；未知 license 保留
`REVIEW_REQUIRED`。source notes 保存完整派生规则、父 DatasetID、raw SHA、域证明
和第一方项目链接，并明确本地文件 lineage 未经外部认证；链接没有被当作已核实下载证据。

## 重生、验证与后续资格

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/build_v32_comparison_bundles.py --revision 2
/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/build_v32_comparison_bundles.py --groups byte
```

生成器直接使用当前可用的最小逻辑 CPU，本批冻结为 `[0]`；可用 `--cpu-affinity` 明确指定
一个可用 CPU。四组协议为 STEADY_PROCESS、spawn、PROCESS collector ENABLED、
独立对象的 PIPELINE；N=8，每方向至少 50ms，worker 墙时最多 30s，组墙时最多 1h。
分析政策使用 paired schedule block、至少 4 blocks、4,000 bootstrap 和固定全部分母。
生成器默认 revision=2，只接受新的 revision>=2；v2 使用
`thread_monitor_interval_ns=1000000`。监控是否真的启动、覆盖 worker 整个生命周期、
实际 native/process 线程数和资源资格仍须实测，声明该间隔不等于观测通过。

payload/prepare/plan/provenance 放在 `artifacts/comparisons/v32_20261010/`，
数据注册使用 `registry/comparison_datasets/v32_20261010/`。
已有生成文件验证相等后复用；若已冻结文件内容不同则拒绝覆盖。
canonical source 导入会产生新的语义 DatasetID 与新 transport：bundle 绑定的是
`prepare_dataset()` 之后实际 transport SHA，而不是导入前的源 transport SHA。
来源、配置、完整 corpus、expected matrix、组及协议均在运行之前冻结。
native adapter/supporting files 的当时 SHA 另保存在 build provenance；作业仍须绑定运行时
真实 build/runtime/environment，变更影响的资格不可复用。

规范、真实比较包与候选台账合同测试 **84 passed**；分析扩展和 HTML 展示另有
**25 passed**，本批五个测试文件及候选台账合计 **109 passed**。九份导出 Schema 使用
标准 Draft 2020-12 校验器独立验证，并通过 fixture 文档校验；相关 Python Ruff 和格式通过。
fixture 明确是测试材料，真实比较包不使用 fixture 来源或数据。
执行器负责新 canonical 正确性、参数级原域误差、真实恢复/成本、完整资格、资源租约、
开发 pilot、配对调度/测量和分析；这些不能由计划身份或预期 PASS 自动授予。

## 只读分析扩展与报告

```python
from tscompbench.comparison.analysis_extensions import augment_analysis
from tscompbench.comparison.report_renderer import render_comparison_report

extensions = augment_analysis(analysis, execution_plan, trials, bundle["corpus"])
page = render_comparison_report(
    analysis,
    plan=execution_plan,
    bundle=bundle,
    extensions=extensions,
    raw_links={"原始试次": "comparison_trials.jsonl", "分析": "analysis.json"},
    disclosures=saved_job_disclosures_by_cell_id,
)
```

`augment_analysis()` 重新核对完整计划/分析矩阵、逐单元 dataset/member/config，
原始试次摘要、重复或未计划 TrialID，以及每条选中观测的实际资格；旧 eligibility
标记本身不能通过复核。它返回独立、有版本和代码摘要的扩展文档，不改动输入。
数值输出为 Decimal 的有限非负字符串或显式 null；无效原域质量不转换为零。

质量点保留 MethodID、等价类、配置和保证语义。每列质量须具备原域有效性、零 nonfinite
错配、正的有限配对数和有限 RMSE/MaxAE；跨进程列身份及观测总体必须一致。
多列 pooled RMSE 仅为未作单位归一化的数值描述；质量 Pareto 使用每列原单位目标，
不构造任意复合质量分。无损观测单列为 bitwise 正确性的精确参考。
有界观测验证声明不自动取得固定误差排名：execution plan 须显式提供
`contract.fidelity.kind=FIXED_ERROR` 或 `fidelity.kind=FIXED_ERROR`。
QUALITY_CURVE 中的有界、无界、率控方法仍各自保留保证类型。

Pareto 按 dataset 和公共投影分区，同时最小化实际 FinalBits、编码/解码 ns/对象与
完整 PROCESS 绝对 RSS 高水位；无界/率控分区再要求全部逐列质量目标。
缺少观测、完整进程 RSS 或有效质量时，固定点继续保留并标记 N/A，
前沿改为 `PARTIAL_OBSERVED_FRONTIER`。不为这些点估计声称 Pareto 置信区间。
分项成本直接来自实际 eligible records，不反推或补造缺失 metadata/model 成本。

来源平衡沿全部父关系和来源身份保守分组，源内使用固定 RawBits 工作负载，
独立来源组间等权；任何来源或单元缺口阻止成员的平衡汇总。
该描述量没有对来源总体的推断或置信区间。
SourceCapabilityMatrix、StandalonePortMatrix、BenchProfileMatrix、PipelineCoverageMatrix
分别显示未知源/port 事实、冻结声明和实际任务证据；执行计划没有提供原源能力审核时，
SOURCE/PORT 显式为 UNKNOWN/UNKNOWN_OR_NA，不能用本任务 PASS 自动扩大源域覆盖。

报告优先展示完成状态和固定分母，然后提供全部成员身份、协议、逐单元成本/时间/RSS/
原域质量、固定工作负载与来源平衡、配对区间、Pareto 和完整证据摘要。
`disclosures` 接受只读加载的 saved jobs 按 CellID 映射，以显示真实输入、recipe、
path、build/runtime 和 ISA；没有提供时保留 N/A，不能拿允许路径当实际路径。
文本与 JSON 全部 HTML escaping，链接只接受 HTTP(S)、相对或绝对本地工件路径；
主动 URL scheme 和模糊 network path 拒绝。扩展复核出现失败时，报告明确标记
`EVIDENCE_RECHECK_FAILED` 并停止展示基础统计的工作负载汇总与配对判定。

HTML 测试验证固定缺口、N/A、原域质量、成本分项、配对证据、完整身份、escaping、
链接约束和文档绑定。本次环境没有可用浏览器，尚未完成页面截图的视觉核验；
`artifacts/comparisons/report_renderer_fixture_qa.html` 明确是展示验证 fixture，
不进入真实比较结果。
