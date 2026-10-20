# 压缩指标与原生性能边界核查（2026-10-15）

当前框架的完整对象大小与时间有明确计算依据，但不能作为codec纯原生性能。主要问题是主表突出stored fraction、原生与对象工作边界不同，以及对象路径含较重的封装／审计操作。往返正确或与参考bitstream一致证明相应输入上的行为正确，不证明大小统计的分母、数据分块和性能测量与上游相同。

本次只读重算现存Gorilla records的24case／504个成功正式trial；没有重新执行codec或性能测量。逐case大小、时间与证据hash见[机器记录](metrics_diagnosis_20261015.json)。该核查确认这些trial均满足 `stored_bytes = payload_bytes + header_bytes`，报告的compression_ratio与原始记录相符。

## 1. 两种互为倒数的指标

[report.py](../../benchmark/src/tsbench/report.py:102)定义：

- `stored_fraction = compressed_bytes / original_bytes`，越小越好；0.25表示保留25%，对应4倍压缩。
- `compression_ratio = original_bytes / compressed_bytes`，越大越好；小于1表示膨胀。

JSON／CSV保存两者，Markdown主表只展示Stored fraction。不能把主表小于1解读为压缩失败。推荐主表同时展示“压缩倍数（原始/压缩，越大越好）”与“存储占比（压缩/原始，越小越好）”，明确payload还是wire。压缩节省率另用 `1-stored_fraction`，不能与倍数同名。

`raw_bytes`来自请求任务中V／T／mask的实际array.nbytes，不是CSV／NPY文件长度。比较文本压缩或论文结果前必须先统一分母和dtype。

## 2. 当前真实结果中的封装与分母差异

以下均为canonical Gorilla，payload是全部原生raw EncXOR chunk之和，本次输入没有mask。

| 对象 | 原始任务bytes | 实际原生pair输入bytes | 原生chunk bytes | 框架header bytes | 完整wire bytes | 原生pair压缩倍数 | 完整对象压缩倍数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| ETT 128行、7列 | 8192 | 14336 | 6453 | 2811 | 9264 | 2.222× | 0.884× |
| weather 512行、21列 | 90112 | 172032 | 61923 | 20855 | 82778 | 2.778× | 1.089× |
| ILI 512行、7列 | 32768 | 57344 | 14692 | 7707 | 22399 | 3.903× | 1.463× |

来源：[正式summary](../../runs/gorilla-real-records-20261015/report/summary.json)、[原始observations](../../runs/gorilla-real-records-20261015/observations.jsonl)。这些是同一产物的不同观察范围，不是恢复算法失败。

Gorilla每个series接收N个timestamp/value_bits对，每对16bytes；多列对象共享一个T数组，但原生接口按列重复编码T。无mask时：

`B_task = 8*N*(M+1)`，`B_pairs = 16*N*M`。

因此ETT的原生输入分母是任务分母的1.75倍；weather是1.909倍。必须分别报告，不能把重复时间戳当独立有效数据来抬高整个MTS任务吞吐或压缩倍数。

此外，[冻结配置](../../benchmark/experiments/gorilla/records.toml)明确 `chunk_rows=128`。512行对象仍是每列4个独立128点chunk，而不是一个512点原生序列；weather共84个chunk。新增chunk会重置预测／字典状态并增加目录。对象变长但chunk长度不变，不能期待这些成本全部被摊薄。压缩率也受实际序列、浮点位型与参数影响，不能要求任意输入接近论文的特定数值。

一般codec的payload字段也未必等于最内层原生输出。例如RW bridge加入列目录，模型frame含必要模型，records可能带raw mask或其他codec的组件。必须按真实format解析层次，不能全局把payload_bytes重命名为core bytes，不能扣掉恢复必需的native header、Finish尾部、exceptions或模型。

## 3. 时间当前覆盖什么

[CPU executor](../../benchmark/src/tsbench/executors/cpu.py:66)测量完整 `scheme.encode_once` 和 `decode_once`。包括：

- chunk／channel切分、连续化、typed/ABI framing与字节复制；
- native handle创建、reset、bound、输出分配、compress／Finish、destroy；
- 输入／payload身份hash、descriptor JSON、完整wire生成；
- 解码descriptor／payload校验、native session、恢复分配、组件重组。

外部最终bitwise／quality验证与前后输入不变检查在计时外；但编码内部又有生成产物身份所需的fingerprint与hash，不能把“最终验证在外”误解为“计时内没有校验成本”。对象边界本身可以这样定义，名称必须表明工作量。

已有明确可优化点：[schemes.py](../../benchmark/src/tsbench/schemes.py:209)每个普通非raw part解码都构造Registry，而[Registry构造](../../benchmark/src/tsbench/registry.py:95)遍历并读取全部codec JSON。这是对象路径内的重复工作，应在已冻结身份的decoder准备阶段解析一次。具体耗时占比还需单独profile；本次没有用猜测比例替代实测。

即使从C调用ABI也不自动得到最内层core速度。例如[Gorilla shim](../../adapters/gorilla_prometheus_xor/native/tscb_gorilla.cc:97)在 `tscb_compress` 内分配并装拆Sample数组、调用core并复制输出；decode也做转换与复制。纯core性能需要另一个直接调用真实 `gorilla::encode/decode` 的匹配基准。

现存正式rows没有记录native encode／decode时间，不能从object总时间恢复。bridge的可选last_native_timing字段未被当前executor写入measurement rows；Gorilla timing接口明确返回unsupported。不得把对象时间减去空循环／raw-store时间作为“原生时间”，也不能只加一个report字段就声称已经测得。

## 4. 建议的测量结构

保留统一Python调度、资格、超时隔离、JSONL与只读报告；按问题使用明确的三个边界：

| 边界 | 执行与字节定义 | 主要用途 |
|---|---|---|
| `native_core` | C/C++测量driver直接调用实际codec公开core API；统计该接口的完整有效输出 | 与该实现自己的原生benchmark比较 |
| `native_api` | C/C++测量driver调用实际tscb／rw接口，计完整compress+Finish或decode；适配层内部转换仍计入 | 判断重写绑定及ABI成本 |
| `object_memory` | 完整typed对象→standalone wire→typed对象，维持对象语义 | 评估完整框架／方案的实际代价 |

这些是改造规范，当前主runner尚未实现通用native_core／native_api模式。[现有boundary工具](../../benchmark/tools/boundary_experiment.py)只为Zstd／LZSS提供独立实验，可复用其产物核对与边界声明；它每round启动C进程、Python则在同session重复，不能直接把两者时间差当FFI开销。当前checkout没有历史boundary／current-core／current-pems raw目录，本核查没有重新验证旧文档中的历史性能表。

### 测量driver

1. 子进程启动后读取已冻结typed输入，核对hash并prepare实际codec buffer；配置解析、registry／build身份读取与报告序列化放在测量外。
2. 在一个native进程内预热并执行真实重复操作，编码／解码单独计时；输入、输出与句柄准备边界明确，Python只负责启动和收集。计时器包围实际工作，批次时间远大于计时开销；短操作批次归一化时记录实际calls／bytes／reset政策，不减空循环。
3. 同时明确 `fresh_object`（创建、reset、销毁按定义计入或单列）与 `prepared_context`（合法复用workspace，但每独立输入reset逻辑状态）。不得通过继承前一对象的压缩历史制造更好的独立对象结果。解码不依赖编码器句柄或原始数据模板。
4. 核查每次实际输出与恢复；hash、逐轮bitwise／质量验证放在相应native计时外，校验成本另记；测量结果必须实际消费，避免编译器删除工作。另保留新进程wire-only资格。
5. 对原生时间、API时间、对象时间分别保存原始rows和边界ID。调度／输入／build／runtime／CPU／ISA身份继续冻结，不用旧raw赋予新计时语义。

### 大小与吞吐字段

建议明确保存 `task_raw_bytes`、`codec_logical_input_bytes`、`abi_input_bytes`、`native_output_bytes`、`adapter_output_bytes`、`wire_bytes`及各层必要依赖。输入envelope不能自动当作逻辑数据；同一个native output跨多个组件时必须联合记账，不能重复分摊。

原生主表：`codec_logical_input_bytes / native_output_bytes`，`codec_logical_input_bytes / t_native`。对象表：`task_raw_bytes / wire_bytes`，`task_raw_bytes / t_object`。另外可保存以任务bytes归一化的native吞吐，字段名中明确分母。解压缩吞吐通常用恢复后的原始bytes；samples/s与ns/sample应明确是pair、value还是整个record。MiB/s使用2^20，MB/s使用10^6。

同一固定输入每case先汇总rounds，再以独立session作重复单位；重复round不增加独立source数。当前report把成功primary rounds合在一起做描述median，公式对固定bytes成立，但这不是独立session／source的推断统计。跨不同大小对象的总体压缩倍数采用 `sum(raw)/sum(compressed)`；总体吞吐采用 `sum(bytes)/sum(time)`，与按source等权的配对比较另行声明。失败与unsupported保留分母和原因。

## 5. 对齐上游基准的前提与实施顺序

完全相同的确定性编码实现，在相同输入位型、顺序、chunk／reset、参数和完整输出边界下，应有相同的输出大小；已经要求bitstream一致的路径还应逐字节一致。速度存在调度、cache与频率波动，只能在匹配的编译器／flags／SIMD／线程／runtime／生命周期下作重复测量，不能保证每次耗时完全相同。

例如当前ALP／ALP-RD卡片限定SCALAR及forced方案；不能直接对齐另一套自动选型／SIMD构建的公布带宽。重写C++与上游Java／Go的正确性一致，也不推导为相同实现性能。数据或误差界变化同样会改变比率。

建议依次实施：

1. 报告同时显示两种比率、payload／header／wire字节和明确的时间边界，先消除读表歧义。
2. 首先为Gorilla、Zstd搭建匹配native driver，对同一输入保存core／ABI／wire的产物对应与分层时间，验证通路后扩展其他ABI／codec。
3. 把重复registry读取、审计身份构造等非算法工作移到具名prepare／audit阶段；对象格式另评估只保存恢复必需字段、使用紧凑目录。改变wire和计时语义时生成新身份，重新测量。
4. 按实际算法最大长度设定长度／chunk网格，分别报告短对象延迟和足够大批量吞吐。Gorilla每chunk最多65535点，多chunk批量可以降低计时噪声，但不等于一个超过接口上限的长状态序列。

目标是得到可信的原生主表和完整对象表。单纯将原有比率取倒数、删去header计费或改报表名称，都不能产生尚未测量的原生性能。
