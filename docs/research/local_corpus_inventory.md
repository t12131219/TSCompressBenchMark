# 本地真实时序语料盘点与下一轮对象预算

核查日期：2026-10-13。本盘点支持 [V4.0 工程实施总计划](/home/fzg/PycharmProjects/TSDataCompressBenchMark/TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md:431) §9.1 的来源选择，不修改已有 study、解析规则或测量身份。当前本地数字材料足以构造 20–40 个具名对象；已有证据不足以把这些对象称为覆盖所有目标领域的独立真实来源。

本轮只读取目录、文件长度、CSV 首行、NPZ central directory／NPY header 和小型 legacy catalog；没有全量解析数组、重新计算整个候选库的文件 hash、下载或运行 codec。下面 CSV 行数来自旧 catalog 的 `expected`，不是本次重新数行；CSV 的 dtype 是解析方案，不是文件自带类型。NPZ shape／dtype 来自当前归档内 NPY header。三个已冻结 CSV 的完整身份、获取路线和先前实际解析证据另见 [data_sources.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/data_sources.md) 与 [catalog.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/registry/datasets/catalog.json)。

## 可见材料范围

`/home/fzg/PycharmProjects/材料` 内本次可见 647 个文件。`TSBench_Corpus` 有 37 个文件，其中 13 个真实数据候选、2 个明确合成 fixture、22 个旧 catalog；其余主要是旧方案、报告、源码及旧框架压缩包。

| 目录 | 文件数 | 总文件字节 | 内容及可用性 |
|---|---:|---:|---|
| [TSBench_Corpus](/home/fzg/PycharmProjects/材料/TSBench_Corpus) | 37 | 376111321 | 下面列出的实际数据与旧元信息 |
| [1](/home/fzg/PycharmProjects/材料/1) | 146 | 59421791 | SZ3 源码、两份旧 benchmark zip 等；代码 license 不能作为数据 license |
| [2](/home/fzg/PycharmProjects/材料/2) | 464 | 160908884 | 旧计划、代码与输出，未发现额外真实语料 |

旧 `TimeSeries_Compression_Benchmark_Python_V1.zip`／`Python_v0.1.zip` 只检查 archive member 名称：前者的数据后缀条目为算法清单，后者还有 benchmark 输出与 run summary，未发现额外原始观测语料。没有为此解包或恢复旧框架。

## 当前 13 个真实候选

所有路径区分大小写。CSV 首行均与对应 legacy header 身份相符；除已有三源冻结外，不据此声称全文件 hash、来源或许可已经核实。

| 文件 | 字节 | 当前结构证据 | 领域／来源绑定与许可状态 |
|---|---:|---|---|
| [ETTh1.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/ETTh1.csv) | 2589657 | 旧预期 17420 行；当前 `date` + 7 数值列 | 已绑定原作者 ETT 专用仓库固定提交和精确字节；能源／变压器监测；CC-BY-ND-4.0，保留引用与原始取得路线 |
| [ETTh2.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/ETTh2.csv) | 2417960 | 旧预期 17420 行；当前 `date` + 同名 7 列 | ETT 家族候选；本地精确字节尚未绑定上游提交／data license，旧记录为 `REVIEW_REQUIRED` |
| [ETTm1.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/ETTm1.csv) | 10360719 | 旧预期 69680 行；当前 `date` + 同名 7 列 | 同上；不能由文件名推定采样规则或由 ETTh1 核实自动覆盖 |
| [ETTm2.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/ETTm2.csv) | 9677236 | 旧预期 69680 行；当前 `date` + 同名 7 列 | 同上 |
| [weather.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/weather.csv) | 7235425 | 旧预期 52696 行；当前 `date` + 21 数值列 | 精确研究分发 CSV 已绑定；所有数值／时间与 MPI 2020 屋顶原数据核对；primary 数据 CC-BY-4.0，预处理包装额外条款未知 |
| [electricity.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/electricity.csv) | 95581762 | 旧预期 26304 行；当前 `date`、`0`…`319`、`OT` | 能源候选；本地精确来源、实体含义、单位和许可未核实 |
| [traffic.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/traffic.csv) | 136478119 | 旧预期 17544 行；当前 `date`、`0`…`860`、`OT` | 交通候选；本地精确来源、实体含义、单位和许可未核实 |
| [exchange_rate.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/exchange_rate.csv) | 637800 | 旧预期 7588 行；当前 `date`、`0`…`6`、`OT` | 金融／业务候选；国家／汇率单位、原始来源和许可未核实，不能据名称称业务监控日志 |
| [national_illness.csv](/home/fzg/PycharmProjects/材料/TSBench_Corpus/national_illness.csv) | 67620 | 旧预期 966 行；当前 `date` + 7 列 | 精确作者研究分发已核实；claimed CDC ILINet primary 提取版本与精确 CSV license 未知；公共卫生统计，不能替代 ECG／PPG 生理信号 |
| [PEMS03.npz](/home/fzg/PycharmProjects/材料/TSBench_Corpus/PEMS03.npz) | 15800415 | 当前 `data.npy`：`<f8`、C-order、`(26208,358,1)`；逻辑数组 75059840 bytes | 交通 tensor 候选；旧 axes 为 time/sensor/feature，尚未建立上游／许可／传感器映射证据 |
| [pems04.npz](/home/fzg/PycharmProjects/材料/TSBench_Corpus/pems04.npz) | 32956284 | 当前 `data.npy`：`<f8`、C-order、`(16992,307,3)`；逻辑数组 125197184 bytes | 同上；没有 timestamp 数组，不制造绝对时间戳 |
| [PEMS07.npz](/home/fzg/PycharmProjects/材料/TSBench_Corpus/PEMS07.npz) | 43705518 | 当前 `data.npy`：`<f8`、C-order、`(28224,883,1)`；逻辑数组 199374464 bytes | 同上 |
| [pems08.npz](/home/fzg/PycharmProjects/材料/TSBench_Corpus/pems08.npz) | 18525419 | 当前 `data.npy`：`<f8`、C-order、`(17856,170,3)`；逻辑数组 72852608 bytes | 同上；3 个 feature 的具体语义仍需绑定文档 |

ETT 当前列名是 `HUFL,HULL,MUFL,MULL,LUFL,LULL,OT`。天气的原始 header 带有几个已有替换字符；保留 raw header，并用单独显示映射解释单位。`OT` 的 MPI primary 对应为 `CO2 (ppm)`，该映射有既有逐行核对证据，不根据通用字段名推测。ILI 为 `% WEIGHTED ILI,%UNWEIGHTED ILI,AGE 0-4,AGE 5-24,ILITOTAL,NUM. OF PROVIDERS,OT`；这些空格和列名应以实际 parser/catalog 为准，不自动规范化。

除三源新 catalog 外，旧记录的来源只有 `local:datasets/<file>`、取得时间 `UNSPECIFIED`、许可 `UNSPECIFIED / REVIEW_REQUIRED`。旧记录中的 hash 与字段约定可作为待验证预期，不能替代精确上游版本、来源引用或授权证据。

## 按 V4 领域查看缺口

| 目标领域 | 本地可见候选 | 已建立的证据与缺口 |
|---|---|---|
| 工业 IoT | ETT 变压器监测 | 有 ETTh1 能源设备观测证据，但没有独立的通用工厂／设备 IoT 来源；不能把同一来源重复计到两个 domain 权重 |
| 能源 | ETT 家族、electricity | ETTh1 已绑定；其他精确文件与 license 待核实；ETT 的列、频率版本或变压器实体不能直接作为额外独立采集来源 |
| 交通 | traffic、4 份 PeMS | 数值结构可用；精确来源、版本、许可、实体与时间解释均需补证 |
| 气象／环境 | weather | MPI primary 身份与数据条款有证据；预处理包装条款缺口单列记录 |
| 生理信号 | 未发现 ECG、PPG、可穿戴等 | ILI 是聚合公共卫生统计，Sprintz fixture 是合成序列，均不能补这个缺口 |
| 业务监测 | exchange_rate 为候选 | 没有已核实的应用业务事件／监控日志来源；金融序列能否承担预定业务 RQ 需明确定义 |

当前完整身份已冻结的三源 study 是 ETT、weather、ILI 的选定单列，已能支持明确范围内的结果。来源和许可证据都较充分、适合优先继续冻结的本地池为 ETTh1 与 weather，但仍应遵循各自的数据条款：仓库发布取得路线、hash、解析／对象元信息和分析结果，不捆绑或发布修改后的原始数据。ILI 继续保留精确分发路线和许可未知状态；不凭“政府数据”推定其精确加工文件为公有领域。

## 20–40 个具名 typed 对象的可行预算

下面是**下一轮冻结方案**，没有在本盘点中实际创建、解析或测量这些新对象，也不改变既有 study。具名对象数是工程预算，独立 source/domain 数仍分别报告。

| 方案 | 具名对象构成 | 数量与覆盖 |
|---|---|---|
| 最小扩展 | ETTh1 的 7 个原生列各 1 个 UTS；weather 预先声明的 11 个列各 1 个 UTS；两源各 1 个保留原生列边界的 MTS | 18 UTS + 2 MTS = 20；仅 2 个物理来源、能源与气象 |
| 完整本地双源池 | ETTh1 全部 7 个列、weather 全部 21 个列各 1 个 UTS；两源各 2 个预先指定窗口的 MTS | 28 UTS + 4 MTS = 32；多列／窗口相依，不能声称 32 个独立来源 |
| 领域扩展 | 在 20–32 对象基础上，为精确绑定后的 electricity、traffic／PeMS、exchange_rate 预先分配对象名与权重 | 可控制在 20–40；需要先补各源身份与许可，仍缺独立生理来源和已定义的业务监测来源 |

20 对象方案的 weather 11 列可预先声明为：`p (mbar)`、`T (degC)`、`Tpot (K)`、`Tdew (degC)`、`rh (%)`、`VPmax (mbar)`、`VPact (mbar)`、`VPdef (mbar)`、`sh (g/kg)`、`H2OC (mmol/mol)`、`rho (g/m**3)`。这是明确且可复查的列预算，不按压缩结果挑列；完整 32 方案保留所有 21 列。对象 ID 应包含 source/entity、列名或列集合、stop-exclusive 窗口、schema 与 typed bytes 身份，不能仅按对象序号区分。

冻结前需要顺序完成这些工作：

1. 绑定每个新增源的实际文件完整 SHA-256、上游精确版本、引用与 data-license evidence；对未知项保留状态，不挪用软件代码 license。固定解析规则和窗口选择，再执行全源 typed parse、有限性、列数和 timestamp 顺序检查。
2. 为 CSV 明示 V 的 `<f8` 转换与 T 的 `<i8` 时间表示，保留时区未知事实、原始排列和 weather 的相邻重复时间。ILI 的旧计数列 `<i8` 提案需要逐 token 的整数／范围验证，不能从既有 float64 study 静默换型。NPZ 保留 `<f8` 原生 shape、实体／feature 边界，没有来源时间戳就明确使用索引语义或 V-only 任务。
3. 在测量前固定 development/evaluation、窗口起点／长度、通道选择、missing/special policy、raw object 身份与依赖关系。既有 pilot 已观察过的窗口应披露；ILI 旧 `[256,512)` 与当前评价重叠的事实不能因新 run ID 消失。不得循环复制、padding、插值或偷偷将 float64 cast 到 integer／float32 来凑 codec 支持矩阵。
4. 先按每个 codec 的实际 dtype、维度、特殊值和时间／mask 能力生成支持矩阵，再为 UTS/MTS 或 V-only scheme 运行独立资格。多通道对象经显式 split／reshape 方案进入一维 codec 时，记录完整元信息与时间／空间成本；原生边界不得丢失。正式 CPU/GPU 测量仍由统一调度串行安排。

## 两份合成 fixture 及失效旧路径

| 文件 | 本次实际 header | 旧记录的来源／许可 | 用途 |
|---|---|---|---|
| [sprintz_i16_mts.npz](/home/fzg/PycharmProjects/材料/TSBench_Corpus/sprintz_i16_mts.npz) | 33034 bytes；`values.npy`、`<i2`、`(4096,4)` | `generated:tools/generate_sprintz_i16_mts_fixture.py@20260919`；CC0-1.0／RUN_ALLOWED | 合成 int16 多通道资格 fixture |
| [sprintz_u8_uts.npz](/home/fzg/PycharmProjects/材料/TSBench_Corpus/sprintz_u8_uts.npz) | 2314 bytes；`values.npy`、`|u1`、`(2048,)` | `generated:tools/generate_sprintz_fixture.py@20260919`；CC0-1.0／RUN_ALLOWED | 合成 uint8 资格 fixture |

其他旧 `rewrite_*`、`streamvbyte_*`、`simple_uint28_*` catalog 指向本地当前不存在的文件；若将来恢复，也应按其原始声明作为合成／机制 fixture 审核，不能计入真实观测 corpus。当前可见材料没有额外真实生理或业务监测来源。
