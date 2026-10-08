"""Author source-grounded Archify specifications and a local reading atlas."""
from pathlib import Path
import ast
import hashlib
import html
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
P = 'src/tscompbench/'
pages = []

def n(label, sub, source, symbol, *notes, kind='backend'):
    return dict(label=label, sublabel=sub, source=source, symbol=symbol, notes=list(notes), type=kind)

def page(slug, title, intro, nodes, labels=None):
    assert len(nodes) == 9, (slug, len(nodes))
    pages.append(dict(slug=slug, title=title, intro=intro, nodes=nodes,
                      labels=labels or ['进入','生成','传递','执行','得到','核对','冻结','输出']))

page('01-overview','运行框架总览','CLI 驱动的本地 Python 控制平面；原生算法在隔离子进程中执行。L3 与 L4 共用同一执行生命周期；run report 是独立命令，不由 run validate 自动触发。',[
 n('CLI 与实验配置','python -m tscompbench',P+'cli.py','main','解析 datasets / codecs / run 三个命令组。','run init / prepare / plan / validate / report 均先 initialize_run_set。',kind='frontend'),
 n('初始化与冻结','initialize_run_set',P+'runner.py','initialize_run_set','加载 TOML、冻结配置及环境；检查存储空间和追加能力。','创建 run-set.json、frozen_config.json、environment.json、events.jsonl。'),
 n('L1 · 数据准备','prepare_run_set',P+'runner.py','prepare_run_set','源文件与 manifest 校验 → CSV/NPZ 加载 → canonical 与 characterization。','已有 preparation-record 时核验并复用。'),
 n('L2 · 协商与规划','plan_run_set',P+'runner.py','plan_run_set','算法 × 数据集 × Track × 参数组合；别名按真实 codec key 去重。','CompatibilityPlan、PreprocessPlan、ExecutionResolution、三层可比键共同形成 TaskID。'),
 n('L3 · 预检资格门','preflight_task',P+'execution/preflight.py','preflight_task','源与许可、运行路径、输入、阶段、边界套件、最小 roundtrip。','预检失败生成 DIAGNOSTIC，禁止进入正式重复。'),
 n('L3/L4 · 重复执行','execute_task',P+'execution/orchestrator.py','execute_task','隔离预热 → 隔离正式重复 → 正确性 / 资源门 → 可选查询 / streaming。','计时、账本、校验与 RunID 对应同一批对象。'),
 n('追加原始证据','run_components.jsonl',P+'storage/runs.py','append_run_record','追加 RunRecord；runs.csv 为可重建投影。','压缩位流保存 artifacts/<RunID 摘要>.bin；还保存 preflight 和 warmup。',kind='database'),
 n('L5 · 冻结证据分析','analyze_run_set',P+'statistics/engine.py','analyze_run_set','report 命令读取任务全集与原始运行证据，筛选并按路径聚合。','数据集 / corpus 汇总、coverage、Pareto 与组内排名。'),
 n('报告与可追溯产物','generate_report',P+'reporting/generator.py','generate_report','7 张主要 CSV + 可选 pipeline_stages.csv；report.json / md / html。','coverage.svg、space-encode.svg、space-decode.svg 与 layer5-statistics.json。',kind='frontend')],['初始化','准备数据','注册表 / 参数','逐任务预检','资格通过','逐重复持久化','run report','发布分析'])

page('02-cli','命令入口与分派','命令顺序是依赖关系，而非每条命令都执行完整五层。report 需要已有冻结证据；已有运行集应使用 --run-set-id 与 --resume。',[
 n('可执行入口','tscompbench / __main__',P+'__main__.py',None,'pyproject.toml 指向 tscompbench.cli:main。','python -m tscompbench 进入同一个 main。',kind='frontend'),
 n('解析命令行','_build_parser',P+'cli.py','_build_parser','--project-root 默认为项目根目录。','datasets: list / verify / prepare；codecs: list / verify / classify-sources。'),
 n('构建注册表','DatasetRegistry',P+'cli.py','_registry','registry/datasets；源文件相对项目根解析。','codecs 命令及 plan/validate 使用 SourceRegistry + CodecRegistry。'),
 n('run 公共初始化','initialize_run_set',P+'cli.py','main','所有 run 子命令先初始化运行集。','--output-root 必填；--run-set-id 与 --resume 控制复用。'),
 n('init / prepare','L0 → L1',P+'runner.py','prepare_run_set','init 在冻结初始化后返回。','prepare 完成数据准备，返回 DatasetID 与 canonical SHA-256。'),
 n('plan','L1 → L2',P+'runner.py','plan_run_set','自动准备数据后冻结 task_plan.jsonl。','返回 task_count 与 task_plan 路径。'),
 n('validate','L1 → L2 → L3/L4',P+'runner.py','execute_run_set','完整规划后执行缺失重复；资格和正式测量共用执行器。','返回本次执行任务数与 runs.csv；命令名称 validate 包含实际测量。'),
 n('report','已有证据 → L5',P+'runner.py','report_run_set','调用 generate_report；不重新运行 codec。','返回 ReportID、任务数、汇总数、eligible_run_count 与 report.html。'),
 n('终端输出 / 退出码','JSON / stderr',P+'cli.py','main','成功输出排序后的 JSON；主函数返回 0。','OSError / RuntimeError / ValueError 输出 ERROR 到 stderr，返回 2。',kind='frontend')],['入口','根目录','run 分支','init / prepare 分派','plan 分派','validate 分派','report 分派','返回'])

page('03-init','初始化、环境与冻结','初始化阶段保护运行集身份；它不是持续持有的全局锁。prepare、plan、execute、report 会各自获取并释放同名 flock。',[
 n('TOML 严格配置','load_experiment_config',P+'configuration.py','load_experiment_config','顶层 datasets / algorithms / tracks / seed / data_preparation / profile / reporting / sweep。','字段、类型、枚举与十进制字符串校验；生成 ExperimentConfigID 与 ProfileID。'),
 n('测量配置约束','BenchmarkProfile',P+'configuration.py','BenchmarkProfile','FORMAL: warmup ≥3 次且 ≥0.5 秒；repetitions ≥10。','每重复最小时长在 [1,3] 秒；timeout 大于预热与重复最低时长。'),
 n('安全运行集路径','_default_run_set_id',P+'runner.py','initialize_run_set','默认 runset-UTC 时间戳-配置摘要；显式 ID 必须是单个安全路径组件。','输出根解析为绝对路径；拒绝 .、..、空字符串与多段路径。'),
 n('工作区探测','_probe_workspace',P+'runner.py','_probe_workspace','临时文件追加、flush、fsync 与读取核对。','磁盘可用空间要求 ≥64 MiB；记录隔离与 monotonic_clock 证据。'),
 n('互斥锁 / 分支','fcntl.flock',P+'runner.py','initialize_run_set','runs/.locks/<run_set_id>.lock；LOCK_EX | LOCK_NB。','存在运行集而未 --resume → 拒绝；已被锁 → 拒绝。',kind='security'),
 n('恢复身份核验','resume gate',P+'runner.py','initialize_run_set','frozen_config 必须逐值一致；events.jsonl 必须完整合法。','capture_environment 得到的 EnvironmentID 必须与冻结环境一致。',kind='security'),
 n('环境捕获','capture_environment',P+'environment.py','capture_environment','记录 Python、NumPy、平台、CPU/ISA、CPU 可用性与环境身份。','run-set 另外记录 executable、argv、仓库 commit 与 dirty。'),
 n('冻结初始证据','run-set / config / environment',P+'runner.py','_write_json','独占创建 JSON；ensure_ascii=False、allow_nan=False、排序、flush + fsync。','新建过程中出错删除刚创建的 run_path。',kind='database'),
 n('事件与释放锁','RUN_SET_CREATED / RESUMED',P+'runner.py','initialize_run_set','创建与恢复分别追加对应事件。','finally 解锁并关闭描述符；返回不可变 RunSet。')])

page('04-data','L1 · 源数据加载与表征','运行链使用声明驱动的数据加载；表征只读，不把源 CSV/NPZ 的文件大小当作逻辑数据分母。',[
 n('数据集注册表','DatasetRegistry.load',P+'datasets/registry.py','DatasetRegistry','读取 registry/datasets/<key>.json；验证 required/unknown keys。','来源路径、bytes、SHA-256、format、logical/physical/expected 等合同。'),
 n('源身份与只读核对','verify_source=True',P+'datasets/prepare.py','prepare_dataset','verify_source 核验原始文件；DatasetID 来源于规范身份载荷。','load_dataset 加载后再次核对源 hash，检测加载器是否改写源数据。'),
 n('CSV / NPZ 分派','load_dataset',P+'datasets/loaders.py','load_dataset','CSV：显式值列、dtype、时间格式 / epoch / 单位、validity。','NPZ：显式数组键与 shape；保留声明的拓扑、原生形状及逻辑语义。'),
 n('CanonicalDataset','逻辑 + 物理描述',P+'datasets/models.py','CanonicalDataset','UTS / SYNCHRONOUS_MTS / ASYNCHRONOUS_MTS / NATIVE_ND_ARRAY 合同类型。','timestamp、value 通道、validity、dtype/shape/strides/alignment；实际可用组合由 manifest 与 loader 决定。'),
 n('只读表征','characterize',P+'datasets/characterize.py','characterize','exact 或 sampled；sample_rows 与 seed 冻结。','值分布 / entropy / ACF / 浮点特殊值；时间间隔与顺序相关特征。'),
 n('规范二进制','write_canonical',P+'datasets/canonical.py','write_canonical','little-endian 顺序流；metadata JSON + 命名 buffers。','validity 使用 bitmap-lsb0；保存 payload hash 和逻辑位数。'),
 n('四类 L1 文件','dataset artifact set',P+'datasets/prepare.py','prepare_dataset','<key>.canonical.tscb、<key>.characterization.json、<key>.manifest.json。','preparation-record.json 记录来源、文件 / 内容 hash、loader_provenance 与 self_check。',kind='database'),
 n('复用核验','load_preparation_result',P+'datasets/prepare.py','load_preparation_result','已有 preparation-record：核对 schema / key / DatasetID / 安全文件名。','canonical 文件 hash、元数据 DatasetID、characterization 与 manifest 身份核验。'),
 n('L1 完成事件','LAYER_1_COMPLETED',P+'runner.py','prepare_run_set','逐数据集 STARTED、REUSED/COMPLETED 或 FAILED。','返回 PreparationResult 元组；记录 DatasetID 清单。')])

page('05-canonical','Canonical 格式与身份链','文件 SHA-256、内容 SHA-256 与 DatasetID 是不同证据；原始源文件字节只用于溯源。',[
 n('规范身份编码','canonical_json_bytes',P+'ids/canonical_json.py','canonical_json_bytes','UTF-8、排序与 NFC 字符串归一化。','身份载荷禁止二进制 float、非有限值、Path；Decimal 使用 $decimal。'),
 n('来源与数据集身份','DatasetID',P+'datasets/registry.py','_identity_payload','manifest 的逻辑数据合同与源内容标识进入身份载荷。','文件路径不能替代内容身份。'),
 n('逻辑位数','CanonicalDataset',P+'datasets/models.py','CanonicalDataset','timestamp_raw_bits、value_raw_bits、validity_raw_bits 与 canonical_raw_bits。','保留有效性逻辑 bit 数，不用 bitmap 对齐后的字节数冒充原始逻辑位数。'),
 n('文件头','<8sHHQI',P+'datasets/canonical.py','write_canonical','MAGIC=TSCB2\\0\\0\\0；格式 major=1、minor=0。','metadata_length 与 buffer_count 显式写入；实现版本标识为 tscb-canonical-v1。'),
 n('元数据区','canonical UTF-8 JSON',P+'datasets/canonical.py','write_canonical','dataset_id / dataset_content_sha256 / logical_descriptor / physical_descriptors。','accounting 与每 buffer 的 name、dtype、shape、logical_bits、payload_bytes、payload_sha256。'),
 n('命名缓冲区','<HQ + name + payload',P+'datasets/canonical.py','_buffer_payload','buffer header 使用 name 长度 + payload 长度；名称 UTF-8。','数值必须 little-endian；validity=np.packbits(bitorder=little)。'),
 n('原子提交','临时文件 → os.replace',P+'datasets/canonical.py','write_canonical','顺序写入、flush、fsync 后原子替换目标。','重新读取 canonical，得到文件 SHA-256 与校验后的元数据。',kind='database'),
 n('读取严格核验','read_canonical',P+'datasets/canonical.py','read_canonical','头版本、精确长度、规范 JSON 与 buffer 数匹配。','核验 buffer descriptor / payload hash / 长度 / dtype / shape；载荷按需要读取。',kind='security'),
 n('供规划与执行','metadata → buffers',P+'runner.py','execute_run_set','L2 用 L1 元数据和表征构建 DataDescriptor，核验内容 hash 一致。','L3 将 include_buffers=True 的 canonical 按 DatasetID 装入内存。')])

page('06-registry','Source / Codec 注册表与适配器工厂','注册表提供可执行合同，不能把“登记”理解为所有数据、硬件和配置已被正式资格认证。附录列出当前 67 个 codec manifest。',[
 n('来源目录与清单','registry/sources',P+'codecs/registry.py','SourceRegistry','只读原始 Source_Code；source artifact 记录内容身份、availability 与 license。','catalog / source classification / onboarding 提供算法来源证据。',kind='database'),
 n('来源卡校验','validate_onboarding_card',P+'codecs/onboarding.py','validate_onboarding_card','版本化准入卡：来源 / 许可 / 构建 / ABI / 验证证据。','这是接入与审核合同，正式任务仍经过 preflight。'),
 n('CodecManifest','registry/codecs',P+'codecs/models.py','CodecManifest','identity / classification / input / semantics / lifecycle。','execution / features / parameters / adapter / accounting 等声明形成 AlgorithmID。'),
 n('注册与别名','CodecRegistry',P+'codecs/registry.py','CodecRegistry','验证来源引用与参数 / 输入 / 工厂相关合同。','算法别名解析到规范 key；规划按 key 去重并保存 alias snapshot。'),
 n('构建产物定位','adapter_artifacts',P+'adapters/factory.py','adapter_artifacts','安全相对 artifact_path 指向 .so / Python oracle。','部分工厂显式检查 build-record / compile-command / runtime dependencies / 源码闭包与对象文件。'),
 n('不可漂移的运行闭包','artifact hashes',P+'adapters/factory.py','adapter_artifacts','StreamVByte、MaskedVByte、SIMDComp、FastPFOR Simple 等来源冻结路径核验。','LittleIntPacker / Simple8b-RLE 有专门 execution_artifacts；missing 或 drift 拒绝。',kind='security'),
 n('工厂分派','create_adapter',P+'adapters/factory.py','create_adapter','按 manifest.adapter.factory 选择 Python adapter 类。','HARNESS_ORACLE → OracleAdapter；未知工厂 → AdapterFactoryError。'),
 n('Python 协议对象','CodecAdapter',P+'execution/protocol.py','CodecAdapter','adapter_id、deterministic、create_session(parameters)。','不等于立即开始正式测量；预检会核验实际 adapter_id 与计划一致。'),
 n('冻结注册表快照','codec / source snapshots',P+'runner.py','plan_run_set','codec_registry_snapshot.json / source_registry_snapshot.json。','source_classification.json、resolved_configs.json 与可选 codec_alias_snapshot.json。',kind='database')])

page('07-planning','L2 · 参数展开与任务全集','每个算法的参数组合、数据集、Track 都产生可追溯计划；不支持的组合也保留为诊断任务与 coverage 分母。',[
 n('前置 L1 与算法检查','plan_run_set',P+'runner.py','plan_run_set','配置至少含一个算法；prepare_run_set 先完成数据准备。','规划锁保护快照与 task_plan 写入。'),
 n('算法规范化','aliases → manifest.key',P+'runner.py','plan_run_set','按 algorithms 请求解析 manifest；同一 codec key 只规划一次。','收集来源、主产物及 supporting artifacts。'),
 n('参数 sweep','expand_sweep',P+'planning/sweep.py','expand_sweep','默认值、类型 / 枚举 / 范围 / 组合约束校验。','framework_parameters 包含 benchmark_seed；ResolvedConfig 包含 ConfigID、status、reason_code。'),
 n('数据集 × Track','DataDescriptor',P+'codecs/negotiation.py','descriptor_from_layer1_artifacts','L1 metadata 与 characterization 形成每个 Track 的输入描述。','规划核验 canonical_content_sha256 与 metadata 内容 hash 一致。'),
 n('显式预处理计划','build_preprocess_plan',P+'preprocess/contracts.py','build_preprocess_plan','从 semantics.preprocess_stages 建立有序 A–D 槽。','参数开关生成有效计划；唯一槽、语义类别与声明一致。'),
 n('能力协商','negotiate',P+'codecs/negotiation.py','negotiate','输入合同匹配后生成 CompatibilityPlan 和 AdapterOperation 序列。','DIRECT_SUPPORTED / ADAPTER_LOSSLESS / ADAPTER_LOSSY / UNSUPPORTED。'),
 n('实际运行路径解析','resolve_execution',P+'planning/resolution.py','resolve_execution','ISA、设备、线程、fallback、affinity、计时 scope 与构建闭包。','ExecutionResolution 与 execution_path_hash 冻结实际选择。'),
 n('可比键与 TaskID','create_task',P+'planning/tasks.py','create_task','SemanticComparabilityKey → ExecutionComparabilityKey → ResourceProfileKey。','加数据集、算法、ConfigID、ProfileID、资源上限等形成 deterministic TaskID。'),
 n('冻结任务全集','write_task_plan',P+'planning/tasks.py','write_task_plan','按 TaskID 排序，task_plan.jsonl 独占写入或核验一致。','layer2-plan.json 记录任务数、任务状态与能力状态计数。',kind='database')])

page('08-capability','能力协商与数据适配','能力协商先判逻辑语义再判物理表示；适配是显式计划，数据复制与精确扩宽均进入成本与身份。',[
 n('输入描述','DataDescriptor',P+'codecs/negotiation.py','descriptor_from_layer1_artifacts','Track、topology、dtype vector、rank、n/m、validity、时间 / 值单位。','物理 layout、alignment、endianness 与保序要求。'),
 n('语义与能力筛选','negotiate',P+'codecs/negotiation.py','negotiate','loss_mode / topology / Track / coupling / rank / n/m / 特殊值限制。','不能满足的合同产生具体 reason_code；不调用 codec 猜测能力。'),
 n('dtype 转换判断','_conversion',P+'codecs/negotiation.py','_conversion','原 dtype 支持则直通；否则选择精确可表示的扩宽。','有损转换必须显式声明，否则 LOSSY_DTYPE_CONVERSION_UNDECLARED。'),
 n('物理布局操作','AdapterOperation',P+'codecs/models.py','AdapterOperation','CONTIGUOUS_COPY / TRANSPOSE_COPY / GATHER_SCATTER / ALIGNMENT_COPY。','EXACT_WIDEN / ENDIANNESS_CONVERSION / SAFE_OVERREAD_PADDING / LOSSY_CAST 等是合同枚举；具体执行由计划决定。'),
 n('四态协商结果','CapabilityStatus',P+'contracts/enums.py','CapabilityStatus','DIRECT_SUPPORTED：无需适配。ADAPTER_LOSSLESS：显式无损操作。','ADAPTER_LOSSY：有效损失模式改变；UNSUPPORTED：保留拒绝理由。'),
 n('执行适配','apply_compatibility_plan',P+'adapters/compatibility.py','apply_compatibility_plan','对各非 validity LogicalBuffer 按计划执行转换。','保留原始 RoutedInput；codec_input 重新计算 hash 与逻辑视图。'),
 n('准备输入核验','validate_prepared_input',P+'adapters/compatibility.py','validate_prepared_input','核验 shape、位精确逆变换或显式误差界。','PreparedExecutionInput 分离 original、codec_input 与 telemetry。',kind='security'),
 n('适配成本证据','AdapterTelemetry',P+'execution/preparation.py','prepare_execution_input','read_bytes、written_bytes、allocated_bytes、padding_bytes、copied。','prepared.logical_array 设置为不可写；validity 原样保留。'),
 n('损失与比较身份','effective_loss_mode',P+'planning/resolution.py','build_comparability_keys','适配语义类别与 preprocess_class 纳入 SemanticComparabilityKey。','有损适配不能在无损组中获得直接排名。')])

page('09-resolution','实际运行路径与三层可比键','声明的 ISA 不等于实际 ISA；回退及 instrumentation 开关都影响比较身份。三层键构成嵌套合同。',[
 n('请求 ISA 与环境','resolve_execution',P+'planning/resolution.py','resolve_execution','读取 parameters / execution 声明和环境 CPU flags。','计时 scope 必须被 codec 支持；请求 ISA 必须被声明。'),
 n('ISA 与 fallback 门','actual_isa',P+'planning/resolution.py','resolve_execution','CPU 缺指令集：只在 SCALAR_ALLOWED 且条件满足时显式回退。','否则 ISA_UNSUPPORTED；新整数路径多为 DISALLOWED，按各 manifest 为准。',kind='security'),
 n('设备与资源选择','threads / processes / affinity',P+'planning/resolution.py','resolve_execution','冻结 device、threads、processes、cpu_affinity。','不可用 affinity 会形成 UNSUPPORTED；计入 profile 中的资源上限。'),
 n('产物闭包身份','artifact_sha256',P+'planning/resolution.py','resolve_execution','哈希主二进制及支持产物列表；缺产物 BUILD_UNAVAILABLE。','Python 绑定、构建记录、源码与对象证据纳入对应闭包。'),
 n('execution_path_hash','ExecutionResolution',P+'planning/resolution.py','resolve_execution','包含 source_artifact_id / adapter_id / environment_id / backend。','ISA、tail path、alignment、fallback 与 allocation/cache/gc/jit policy 冻结。'),
 n('语义可比键','SemanticComparabilityKey',P+'planning/resolution.py','build_comparability_keys','Track、ObjectLevel、LossMode、重建模式、拓扑、dtype、时间 / 值单位。','validity、顺序、可解码性、分离性、coupling、adapter/preprocess、block/state 与误差界。'),
 n('执行可比键','ExecutionComparabilityKey',P+'planning/resolution.py','build_comparability_keys','嵌入 semantic_key；mode、scope、warmup / repeat / min-duration 与输入模式。','actual_isa / device / threads / processes / fallback / backend；native_timing 和 stage_timing 开关。'),
 n('资源可比键','ResourceProfileKey',P+'planning/resolution.py','build_comparability_keys','嵌入 execution_key；resource_scope、memory_accounting_scope。','counter_method、energy_method、sampling_policy。'),
 n('冻结并供资格分析','comparability documents',P+'statistics/engine.py','_task_chain_valid','task 保存三层键及对应 documents；RunRecord 保存同一键。','L5 核验嵌套链与 run/task 身份、实际路径一致。',kind='security')])

page('10-routing','三种 Track 与输入路由','图的中间三个节点按读取顺序介绍互斥分支；箭头使用“另一路”而非暗示同一任务同时执行三个 Track。',[
 n('Canonical 缓冲区','read_canonical',P+'datasets/canonical.py','read_canonical','include_buffers=True；按 buffer 名取得 descriptor 与 payload。','未加载 payload 时 route 拒绝。'),
 n('只读 ndarray 视图','_array_from_payload',P+'execution/routing.py','_array_from_payload','按 dtype / shape / payload 长度核对；validity 从 little bit order 解包。','所有视图 writeable=False。'),
 n('TIMESTAMP 分支','timestamp only',P+'execution/routing.py','route_canonical_artifact','要求 timestamp 存在；selected=(timestamp,)。','canonical_raw_bits=timestamp_raw_bits；m=1。'),
 n('VALUE 分支','values + validity',P+'execution/routing.py','route_canonical_artifact','要求 value/* 存在；选择值通道并附 validity。','分母=value_raw_bits+validity_raw_bits；时间作为参考，不混入编码载荷。'),
 n('SYSTEM 分支','timestamp + values + validity',P+'execution/routing.py','route_canonical_artifact','要求时间和值同时存在；默认 ONE_CANONICAL_SEGMENT。','SegmentPlanID、buffer_order 与配对关系显式记录；分母=canonical_raw_bits。'),
 n('LogicalBuffer / RoutedInput','规范路由对象',P+'execution/protocol.py','RoutedInput','dataset_id / Track / buffers / n / m / canonical_raw_bits。','timestamp_reference、validity_reference、单位、epoch、value_units、pairing hash。'),
 n('内容身份与配对保护','hash_logical_buffers',P+'execution/routing.py','hash_logical_buffers','名称、dtype、shape 与 C-order 字节参与 hash。','timestamp_reference 单独 hash，防止 VALUE 编码更改时间配对。'),
 n('输入一致性校验','validate_routed_input',P+'validation/input.py','validate_routed_input','冻结 DataDescriptor 与实际输入的维度 / 类型 / 单位 / epoch 等合同核对。','NaN / ±Inf / -0 计数与输入 hash 进入 InputValidationReport。',kind='security'),
 n('准备执行输入','prepare_execution_input',P+'execution/preparation.py','prepare_execution_input','保留 original，并生成 codec_input 与适配成本。','供阶段校验、边界套件及 roundtrip；正式每个 inner iteration 再做适配。')],['解码视图','Track 选择','另一路','另一路','所选分支汇合','计算 hash','核对合同','物理适配'])

page('11-preflight','L3 · 预检、边界与安全门','任何门失败都会留下 PreflightResult 与 DIAGNOSTIC RunRecord；只有 eligible_for_formal_repetitions=True 才能预热。',[
 n('计划状态 / 来源许可','preflight_task',P+'execution/preflight.py','preflight_task','非 PLANNED 任务直接形成诊断；来源 availability 与 license status 门。','SOURCE_INCOMPLETE / LICENSE_RESTRICTED 等保留 reason_code。',kind='security'),
 n('实际绑定 / 阶段注册','runtime identity',P+'execution/preflight.py','preflight_task','adapter.adapter_id 与 task.execution.adapter_id 必须一致。','显式 pipeline executor 要与 manifest、预处理计划及参数一致。',kind='security'),
 n('路由与适配核验','input validation',P+'execution/preflight.py','preflight_task','route_canonical_artifact → validate_routed_input → prepare_execution_input。','异常映射 SCHEMA_ERROR / INPUT_OR_ADAPTER_VALIDATION_FAILED。'),
 n('独立阶段证据','validate_pipeline_stages',P+'preprocess/runtime.py','validate_pipeline_stages','有 stages 时隔离验证数学 / 字节表示及逆变换。','SourceDomainError→UNSUPPORTED；MemoryError→OOM；合同不符→CORRECTNESS_FAIL。'),
 n('边界案例生成','build_boundary_suite',P+'validation/boundary.py','build_boundary_suite','n=0/1/2、min±1、block±1、2block±1；多种 m 候选。','整数极值 / delta overflow；NaN / Inf / 相邻 float；熵 / 布局 / 时间模式 / reset / finalize。'),
 n('隔离安全干跑','run_boundary_suite',P+'validation/boundary.py','run_boundary_suite','bound 与 bound-1、canary、输入不可变、重复 finalize、确定性。','不支持边界必须按合同拒绝；容量、bound、内存与正确性错误分别记录。',kind='security'),
 n('最小 roundtrip','perform_roundtrip',P+'execution/repetition.py','perform_roundtrip','隔离执行一次完整 Encode → Finalize → Decode。','正式前验证位流、账本及重建；不是用于正式性能汇总的样本。'),
 n('共同正确性门','validate_common_correctness',P+'validation/correctness.py','validate_common_correctness','时间 / validity / dtype / shape / 数量 / 顺序与原始逻辑输入核对。','lossless 位精确；lossy 误差界 / 质量；确定性与输入保护。',kind='security'),
 n('PASS 或诊断终止','PreflightResult',P+'execution/preflight.py','PreflightResult','PASS 包含 input_validation / boundary / correctness / accounting / bitstream hash。','失败生成 DIAGNOSTIC；execute_task 不进入预热或正式重复。')])

page('12-isolation','隔离进程、资源上限与错误传播','隔离针对每次具体函数调用；预检阶段、边界、预热、正式重复、查询及 streaming 都可分别创建 worker。正式任务在父进程 for 循环中逐个执行。',[
 n('父进程调用','run_isolated',P+'execution/isolation.py','run_isolated','timeout_seconds 必须 >0；接收函数、args/kwargs、memory_limit 与 affinity。','返回 IsolatedCallResult 状态 / 值 / exception / message / trace / exit_code。'),
 n('进程与 Pipe','multiprocessing',P+'execution/isolation.py','run_isolated','可用时使用 fork，否则 spawn；Pipe(duplex=False)。','Process daemon=False；父子关闭各自不需要的连接端。'),
 n('子进程资源边界','_child',P+'execution/isolation.py','_child','sched_setaffinity 固定 CPU；RLIMIT_AS 限制虚拟地址空间。','effective=max(配置上限, 已有 VM +64 MiB)，记录 WITH_EXISTING_VM_HEADROOM。',kind='security'),
 n('执行具体函数','function(*args, **kwargs)',P+'execution/isolation.py','_child','执行 roundtrip / warmup / workload 等函数。','成功发送 PASS + value；MemoryError→OOM；其他 BaseException→CRASHED。'),
 n('父进程期限等待','parent.poll(timeout)',P+'execution/isolation.py','run_isolated','收到信封则 recv 并 join(timeout=1)。','没有结果则执行 deadline 终止分支。'),
 n('超时终止分支','terminate → kill',P+'execution/isolation.py','run_isolated','先 terminate + join(2秒)，仍 alive 则 kill + join(2秒)。','TIMEOUT / TimeoutError / PARENT_DEADLINE；EOF→CRASHED / WorkerExit。',kind='security'),
 n('领域异常映射','_worker_failure_status',P+'execution/orchestrator.py','_worker_failure_status','OutputCapacityError→HARNESS_CAPACITY_ERROR；MemoryError→OOM。','max_inner_iterations 超限→RESOURCE_PRESSURE；其他保留 worker status。'),
 n('隔离结果校验','类型与状态',P+'execution/orchestrator.py','execute_task','不仅检查 PASS，还检查 WarmupObservation / MeasuredRoundTripObservation 类型。','失败信封记录 exception_type / message / exit_code / limit_method。'),
 n('父进程证据回调','record_callback / event_callback',P+'runner.py','execute_run_set','原始运行记录、位流与事件由父进程持久化。','正式 worker 失败仍生成 FORMAL_REPETITION，随后继续剩余重复。')],['创建','设置限制','执行','发信封 / 等待','超时分支','分类失败','校验结果','持久化'])

page('13-session','编码对象生命周期与 C ABI','每次压缩是新的、必须 Finalize 的对象；解码也用新的 session。reset / query / timing 是 ABI 能力，具体是否使用或支持取决于路径。',[
 n('Python Adapter','create_session(parameters)',P+'execution/protocol.py','CodecAdapter','按工厂选中的 adapter 创建 session；ctypes 桥接 .so。','参数经过 resolved config 冻结，运行协议为 CodecSession。'),
 n('Native ABI v1','tscb_create / abi_version','native/include/tscb_adapter_v1.h',None,'tscb_buffer_v1: data / capacity / used / dtype / rank / shape / strides / alignment / ownership。','配置为 canonical UTF-8 JSON；ABI/version 不符必须拒绝。'),
 n('输出上界与分配','output_bound',P+'execution/repetition.py','_encode','必须返回非负整数；按 bound 分配 bytearray 并追加 canary。','input / timestamp pairing hash 在计时前保存。'),
 n('压缩更新','compress_update',P+'execution/repetition.py','_encode','计时开始后调用 compress_update，返回 used length。','要求 0≤used≤capacity；SourceDomainError 必须保持输入、输出与 canary 原子不变。'),
 n('强制 Finalize','finalize',P+'execution/repetition.py','_encode','向 storage[updated:capacity] 写尾部；检查总长度不越界。','Finalize 成本属于 CORE encode；即使零输出字节也必须调用。'),
 n('位流、账本与计时扩展','EncodedArtifact',P+'execution/repetition.py','_encode','停止 CORE 计时后 native timing 查询；截取实际位流并计算 SHA-256。','accounting(stream,routed) 闭合账本；codec_telemetry 收集后 close。'),
 n('独立解码上下文','session.decompress',P+'execution/repetition.py','perform_measured_roundtrip','新的 session 解析 finalized stream，得到 DecodedOutput。','decompress 的 Python 调用属于 CORE decode；finally close。'),
 n('逆适配与逻辑恢复','_measure_reverse_adapter',P+'execution/repetition.py','_measure_reverse_adapter','PIPELINE decode 包含逆适配 / 布局恢复。','通用校验随后与 original 逻辑对象比较。'),
 n('销毁 / 可选扩展','tscb_destroy / timing / query','native/include/tscb_adapter_v1.h',None,'tscb_reset / set_native_timing / get_native_timing / query / get_accounting_json / get_last_error。','create/free/bound 等显式生命周期在核心计时边界之外；算法内部发生的分配仍计入调用。')])

page('14-measurement','L4 · 预热、正式重复与计时边界','默认正式 10 次重复，实验可设更多。每一次重复内部可执行多次独立对象以满足最低时长；编码与解码分别达到门槛。',[
 n('冻结测量策略','MeasurementPolicy',P+'measurement/contracts.py','MeasurementPolicy','measurement_mode、scope、resource scope、GC/cache/allocation、线程与次数。','duration_satisfied 判断 selected encode AND decode；E2E 还检查 e2e。'),
 n('隔离预热','perform_warmup',P+'execution/repetition.py','perform_warmup','次数和墙钟时长两个条件均满足才完成。','max_inner_iterations 防无限循环；预热独立保存 warmup evidence。'),
 n('每个正式重复','perform_measured_roundtrip',P+'execution/repetition.py','perform_measured_roundtrip','资源采样启动；INDEPENDENT_OBJECT；按策略暂时关闭 GC。','每 iteration：重新适配 → 新 encode session → finalize → 新 decode session → 逆适配。'),
 n('CORE encode / decode','Python API wall / CPU',P+'execution/repetition.py','_encode','encode: compress_update + finalize；decode: session.decompress。','显式 session create、output_bound、输出分配、账本、hash、native timing 查询在 CORE 外。'),
 n('PIPELINE / E2E','CANONICAL_MEMORY_ROUTED_VIEW',P+'execution/repetition.py','perform_measured_roundtrip','PIPELINE 包含适配、上下文、分配与包装开销；encode/decode 各自计时。','E2E 从内存 routed view 开始完成整轮，未包含 CSV/NPZ 磁盘加载或全部父进程校验。'),
 n('原生与阶段辅助计时','native / stage timing',P+'adapters/native_timing.py',None,'同一对象的原生 clock totals；边界依算法不同；缺失为 null。','每 inner iteration 原生观测必须齐全才提供总计；不控制 min-duration，不替换 selected 排名。'),
 n('内循环停止判定','duration_satisfied',P+'measurement/contracts.py','MeasurementPolicy','encode ≥ min、decode ≥ min，E2E 另满足完整时长。','未满足则 fresh object 重复；超 max_inner_iterations → RESOURCE_PRESSURE。'),
 n('资源与吞吐','ResourceSampler',P+'measurement/resources.py','ResourceSampler','RSS/增量峰值、CPU user/system、线程、fault、I/O、swap、scope availability。','canonical bytes 与 codec-input bytes 分母分别输出；MB/s 用十进制百万。'),
 n('同一重复证据','MeasuredRoundTripObservation',P+'execution/repetition.py','MeasuredRoundTripObservation','所有内迭代确定性 / immutable / canary 聚合。','最后一个 finalized object 提供位流、账本与解码正确性；总时间记录 inner_iterations。')])

page('15-pipeline','显式预处理 A/B/C/D 与融合路径','StreamVByte 的 A–D 是一条具体可逆路径；MaskedVByte 与 SIMDComp 的融合 D1/FOR 合同不同，不能把槽字母等同于统一算法。',[
 n('有效阶段计划','PreprocessPlan',P+'preprocess/contracts.py','build_preprocess_plan','槽位唯一且按 A→D 排序；enable_parameter 保留有效开关。','PreprocessClass 决定无损布局、无损语义、有损或学习类别。'),
 n('运行执行器准入','reviewed_pipeline_executor',P+'preprocess/runtime.py','reviewed_pipeline_executor','注册 key / factory / executor_id / stage spec / adapter 实例 / effective plan 必须一致。','未注册而声明 stages → PREPROCESS_EXECUTOR_NOT_REGISTERED；D 不允许关闭。'),
 n('A · checked delta / ZigZag','int64 → uint64',P+'preprocess/streamvbyte.py','validate_stage_snapshot','保存第一个 int64 seed；差分检查 i64 溢出，ZigZag 转 u64。','A disabled：保留 original int64 位模式，seed=0；有独立数学 oracle。'),
 n('B · low/high limb','u64 → interleaved u32',P+'preprocess/streamvbyte.py','validate_stage_snapshot','每个 u64 拆 LOW32、HIGH32；保序并要求 byte-identical。','B disabled 使用字节保持的 little-endian u32 view，语义仍显式声明。'),
 n('C · Stream VByte','codec / raw words',P+'adapters/streamvbyte_pipeline.py','StreamVBytePipelineSession','C enabled 使用冻结原始 Stream VByte APIs；C disabled 写 count 与 raw LE words。','modern64 使用另一原始来源身份；stage wall 包含该槽 copy/allocation/FFI。'),
 n('D · 自包含封装','descriptor / frame / checksum',P+'adapters/streamvbyte_pipeline.py','StreamVBytePipelineSession','规范描述符、native framing、seed / flags / lengths / checksum 计入 final stream。','stage_d=False 被拒绝；阶段 final_contribution_bits 必须与账本一致。'),
 n('逆序与独立验证','D → C → B → A',P+'preprocess/runtime.py','validate_pipeline_stages','inspect_preprocess 提供中间态；数学 / 字节 oracle 检查每阶段与逆变换。','并非用待测编码器自身输出作为唯一验证标准。'),
 n('D1 / FOR 融合例外','MaskedVByte / SIMDComp',P+'preprocess/simdcomp.py','validate_stage_snapshot','SIMDComp A 为原始源 API 中 MODULAR_2_32 D1 或 fixed FOR；B 为 bitpack，D 为封装。','A+B 在源 API 内融合，独立阶段时间不可用；不能伪造分解耗时。'),
 n('阶段证据与导出','pipeline_stages.csv',P+'reporting/generator.py','generate_report','阶段 input/output bytes、enabled、wall_ns、final contribution、观测数。','identity 或 geometry 在重复中漂移时报错；缺失时间保留 null。')])

page('16-correctness','正确性、损失模式与位账本','正确性门与账本闭合共同决定 PASS；大小统计使用 finalized stream，包含解码必须的附加信息。',[
 n('观测保护门','validate_common_correctness',P+'validation/correctness.py','validate_common_correctness','input_immutable / canary / deterministic_match。','前置失效返回具体 first_failure_stage。',kind='security'),
 n('恢复逻辑视图','_restore_adapter_view',P+'validation/correctness.py','_restore_adapter_view','按 compatibility 恢复原 dtype / shape / 布局。','buffer 名称、数量、顺序与原始 routed object 一致。'),
 n('时间与有效性','exact semantics',P+'validation/correctness.py','validate_common_correctness','timestamp、epoch / unit、row count、时间-值配对与 validity 必须保留。','有损值重建也不能默许改变时间或缺失信息。'),
 n('LOSSLESS / LOSSY 门','LossMode',P+'validation/correctness.py','validate_common_correctness','LOSSLESS：字节位精确，保留 -0、NaN 位模式等。','ERROR_BOUNDED：声明界限；UNBOUNDED：结构与质量表征；其他模式按重建合同处理。'),
 n('损失质量证据','validate_error_bound',P+'validation/lossy.py','validate_error_bound','逐通道 MAE / RMSE / max absolute error / bias / percentile 等质量指标。','特殊非有限值与有限域分开；支持声明的误差界与时间加权证据。'),
 n('序列化组件账本','AccountingLedger',P+'accounting/ledger.py','AccountingLedger','timestamp / value / shared / unallocated_shared / metadata / validity / dictionary / model。','index / checkpoint / checksum / padding / container；每组件非负整数 bit。',kind='database'),
 n('物理闭合与外部信息','serialized_bits / final_bits',P+'accounting/ledger.py','AccountingLedger','组件总和=SerializedBits；physical bytes=ceil(SerializedBits/8)。','FinalBits=SerializedBits+external_side_information_bits；Track 不允许串入另一载荷。',kind='security'),
 n('大小分母与比例','canonical_raw_bits',P+'accounting/ledger.py','AccountingLedger','compression_factor=CanonicalRawBits/FinalBits。','size_ratio=FinalBits/CanonicalRawBits；原始源文件 bytes 仅用于 provenance。'),
 n('正确性资格 RunRecord','same repetition',P+'execution/orchestrator.py','execute_task','正确性状态结合资源 / workloads 形成最终 status。','性能、账本、质量与 finalized stream hash 同属于 RunID。')])

page('17-workloads','查询、Streaming 与资源资格','附加 workloads 按配置与 features 判定；未请求、无能力与执行失败是不同证据，不能填成零时延。',[
 n('正式重复结果','observation',P+'execution/orchestrator.py','execute_task','取得 finalized stream、original input 与账本。','query_workload / streaming_workload 均来自冻结 MeasurementPolicy。'),
 n('查询集合与身份','build_query_workload',P+'measurement/workloads.py','build_query_workload','由 n / m / seed / query_count 生成确定请求。','请求集合 + dataset_id + seed 形成 QueryWorkloadID；生成在延迟计时外。'),
 n('features 能力门','unavailable_workloads',P+'measurement/workloads.py','unavailable_workloads','query 或 random_access；streaming feature 分别判定。','未请求 / 不支持 / 待执行状态与明确 reason，missing metrics 保留 null。'),
 n('隔离查询执行','execute_query_workload',P+'measurement/workloads.py','execute_query_workload','session.query(stream, request) 必须返回 QueryResult。','逐逻辑切片校验，采集 latency / decode amplification / read amplification / index bits。'),
 n('隔离流式执行','execute_streaming_workload',P+'measurement/workloads.py','execute_streaming_workload','create_stream_session；stream_start → 多次 stream_push → stream_finalize。','block_size 来自参数；首输出与 block latency、lookahead、buffer/state、reset/backpressure 等证据。'),
 n('流式最终校验','stream_decompress / accounting',P+'measurement/workloads.py','execute_streaming_workload','拼接所有输出并核对最终账本、checkpoint telemetry 与重建。','不会以普通 one-shot roundtrip 冒充连续流式会话。',kind='security'),
 n('workload 失败传播','INCOMPARABLE',P+'execution/orchestrator.py','execute_task','worker 失败保存 exception / reason / workload status。','本来 PASS 的正式记录改为 INCOMPARABLE / QUERY_WORKLOAD_FAILED 或 STREAMING_WORKLOAD_FAILED。'),
 n('swap / 超额线程门','RESOURCE_PRESSURE / OVERSUBSCRIBED',P+'execution/orchestrator.py','execute_task','swap_observed=True 时取消 PASS；观察线程数 > threads*processes 时 OVERSUBSCRIBED。','swap 范围为 SYSTEM_VMSTAT，资源 scope availability 单独记录。',kind='security'),
 n('指标缺失与资格','resource / counter / energy',P+'measurement/resources.py','ResourceSampler','PROCESS 范围可用；其他请求范围按实现报告 availability。','当前硬件 counters / energy 的 NOT_COLLECTED 或 UNSUPPORTED 明确输出，不作为已采集数据。')],['构造请求','能力判定','查询分支','另一路 streaming','最终验证','映射状态','资源门','可用性证据'])

page('18-storage','追加日志、位流与幂等持久化','原始事实源是 run_components.jsonl；runs.csv 是投影。事件日志同样追加，JSONL 末行不完整会阻止恢复与统计。',[
 n('RunRecord.create','内容身份 RunID',P+'storage/runs.py','RunRecord','run_set / task / dataset / algorithm / config / path / 三层可比键。','record_kind=DIAGNOSTIC 或 FORMAL_REPETITION；status / reason / eligibility 显式记录。'),
 n('重复即时回调','persist_repetition',P+'runner.py','execute_run_set','execute_task 每产生记录即回调父进程持久化。','返回结果后再次持久化依靠 RunID 幂等性，不生成第二份原始事实。'),
 n('原始记录去重','append_run_record',P+'storage/runs.py','append_run_record','同 RunID 已存在：内容相同复用，不同拒绝。','写入受运行存储锁保护；append-only + fsync。'),
 n('原始 JSONL','run_components.jsonl',P+'storage/runs.py','append_run_record','含正确性、账本、timing、resources、workloads 与 diagnostics 文档。','保留失败重复和拒绝任务，不仅保存 PASS。',kind='database'),
 n('投影 CSV','rebuild_runs_csv',P+'storage/runs.py','rebuild_runs_csv','从原始 JSONL 重建 runs.csv；启动执行阶段时先重建。','每次记录追加后刷新投影；原子替换避免半写 CSV。',kind='database'),
 n('位流独立保存','artifacts/<RunID>.bin',P+'runner.py','_write_or_verify_bytes','以 RunID 的 SHA-256 尾段为文件名；已有文件必须逐字节相等。','L5 重新哈希，与 RunRecord.bitstream_sha256 核验。',kind='database'),
 n('预检 / 预热证据','preflight / warmup',P+'runner.py','execute_run_set','preflight/<TaskID摘要>.json；warmup/<Task摘要>.from-<首缺重复>.json。','已有冻结 JSON 必须内容完全一致，不能静默覆盖。',kind='database'),
 n('事件日志','append_event',P+'storage/events.py','append_event','events.jsonl：事件时刻、event_type、payload；O_APPEND 写入并 fsync。','validate_event_log 核验完整行与合法事件。',kind='database'),
 n('层完成状态文件','layer3 / layer4',P+'runner.py','execute_run_set','layer3-execution.json：record/status counts；layer4-performance.json：冻结 measurement_policy。','统计聚合明确 DEFERRED_TO_LAYER_5；这些派生状态文件原子替换。')])

page('19-resume','恢复、缺失重复与终态行为','恢复按原始记录存在性推进；已经记录失败的重复也算已完成，不自动重试。已有 DIAGNOSTIC 任务整体跳过。',[
 n('显式恢复请求','--run-set-id --resume',P+'cli.py','main','同一个配置文件与输出根；先 initialize_run_set。','未 resume 而目标已存在会拒绝，避免合并不同实验。'),
 n('配置 / 环境 / 日志门','frozen identity',P+'runner.py','initialize_run_set','配置 canonical_document 与 frozen_config 完全一致。','EnvironmentID 一致；validate_event_log；追加 RUN_SET_RESUMED。',kind='security'),
 n('L1 完成集复用','load_preparation_result',P+'runner.py','prepare_run_set','已有 preparation-record 则验证完整 L1 文件集并复用。','部分 L1 产物存在但无完成记录时 prepare_dataset 拒绝覆盖，需显式处理残留。'),
 n('L2 重新计算并比对','write-or-verify',P+'runner.py','plan_run_set','当前来源 / codec / adapter 重新解析，已有冻结产物必须一致。','schema、配置、任务 / 闭包漂移不会被覆盖为“同一实验”。'),
 n('读取实际进度','_layer3_progress',P+'runner.py','_layer3_progress','原始 JSONL 逐行检查完整 newline 与 JSON。','每 Task 聚合 diagnostic 标志与所有 FORMAL_REPETITION index。'),
 n('终态复用','LAYER_3_TASK_REUSED',P+'runner.py','execute_run_set','diagnostic=True 或无 missing_repetitions → 跳过该 Task。','不按 PASS 过滤进度：已失败正式 index 不会自动重做。'),
 n('只执行缺失 index','repetition_indices',P+'execution/orchestrator.py','execute_task','range(profile.repetitions) 减去已记录 index。','重新预检 / 预热后执行缺失项；warmup 文件以首缺 index 区分。'),
 n('回调记录与位流窗口','persist_repetition',P+'runner.py','execute_run_set','先 append_run_record，再写位流。','极端中断若仅记录落盘而位流缺失，恢复会视 index 已有；L5 通过 BITSTREAM_ARTIFACT_MISSING 拒绝资格。',kind='security'),
 n('报表可重建','report_run_set',P+'runner.py','report_run_set','report 对冻结原始证据重新分析，不需要 codec 重跑。','原始坏行 / 重复 RunID / provenance 缺失 / hash 不符阻止或排除分析。')])

page('20-statistics','L5 · 资格筛选与稳健统计','资格按分析分别给出；source.kind=BUILTIN_HARNESS 或 QUALIFICATION 测量不进入正式性能排名。',[
 n('冻结证据输入','analyze_run_set',P+'statistics/engine.py','analyze_run_set','task_plan.jsonl、run_components.jsonl、run-set、config、environment、codec/source snapshots。','要求 provenance 存在，拒绝重复 TaskID / RunID；计算 source hashes。'),
 n('基础资格理由','_base_reasons',P+'statistics/engine.py','_base_reasons','FORMAL_REPETITION、PASS、eligibility=True、任务在全集、nested keys 正确。','算法 / 数据 / ConfigID / Track / 路径、源 / adapter / environment 身份完整一致。',kind='security'),
 n('证据完整性门','correctness / bits / duration',P+'statistics/engine.py','_base_reasons','正确性 PASS、误差界通过、账本闭合、timing schema 与内迭代合法。','FORMAL 策略、encode/decode 独立最低时长、artifacts 存在且位流 hash 相符。',kind='security'),
 n('分析特有资格','_analysis_reasons',P+'statistics/engine.py','_analysis_reasons','各分析独立形成 eligible + reason_codes。','RESOURCE 需要资源观测及可用 scope；不将缺失硬件数据视为零。'),
 n('同路径重复聚合','_summaries',P+'statistics/engine.py','_summaries','同数据集、算法、ConfigID、execution_path_hash、profile 与可比键的 PASS 重复。','保留 RunID / indices / input/bitstream hashes；时间按 inner_iterations 还原每对象。'),
 n('稳健描述统计','descriptive_statistics',P+'statistics/core.py','descriptive_statistics','n / median / p25 / p75 / mean / SD / CV。','bootstrap median percentile CI：seed_material 经 SHA-256 派生种子；默认 2000 samples。'),
 n('辅助与阶段汇总','_auxiliary_timing_fields',P+'statistics/engine.py','_auxiliary_timing_fields','CORE / PIPELINE / native 并列诊断；原生吞吐使用对应 native_input_bytes。','完整观测才输出原生汇总，缺失次数可见；阶段 timing 缺失仍为 null。'),
 n('Corpus 汇总','_corpus_summaries',P+'statistics/engine.py','_corpus_summaries','先逐数据集汇总再 corpus；micro 位率 / 吞吐与几何平均压缩因子。','memory max / p95、CPU core-seconds/GB；缺失 native 数据传播到 corpus。'),
 n('AnalysisBundle','source hashes + tables',P+'statistics/engine.py','AnalysisBundle','eligibility、summaries、corpus_summaries、coverage、comparability、pareto、rankings。','交给 reporting 导出，不改写原始运行或任务证据。')])

page('21-report','覆盖率、Pareto、排名与报告输出','coverage 以冻结任务全集为分母。排名仅在嵌套可比组内进行；不输出跨 Track / LossMode / ObjectLevel / CPU-GPU 的总榜。',[
 n('冻结任务覆盖率','_coverage',P+'statistics/engine.py','_coverage','计划状态 / 最终状态、记录数、expected / pass / failed repetitions。','PASS / UNSUPPORTED / FAIL / OOM / TIMEOUT 分类；保留没有 PASS 的任务。'),
 n('嵌套可比组','_comparability_groups',P+'statistics/engine.py','_comparability_groups','Semantic → Execution → Resource 三层组与完整 context。','table 记录 task_ids、task_count 及所有 identity documents。'),
 n('多目标 Pareto','_pareto_rows',P+'statistics/engine.py','_pareto_rows','仅用合资格 summary，按各 view 指标形成 Pareto front。','保留 domination / pareto_optimal 证据。'),
 n('组内稠密排名','_ranking_rows',P+'statistics/engine.py','_ranking_rows','每 metric 按 direction 做 dense exact ranking；缺失值先过滤。','coverage 单独发布，不转换成加权综合得分。'),
 n('七类 CSV 表','generate_report',P+'reporting/generator.py','generate_report','eligibility、summary、corpus_summary、coverage、comparability、pareto、ranking。','出现 pipeline 阶段证据时附 pipeline_stages.csv；空指标保留缺失语义。',kind='database'),
 n('图表与可追溯证据','SVG + table hashes',P+'reporting/generator.py','generate_report','report/coverage.svg、space-encode.svg、space-decode.svg。','报告含 source hashes、environment、source/codec registry 与数据准备证据。'),
 n('机器与人读报告','report.json / md / html',P+'reporting/generator.py','generate_report','ReportID 由确定输入 / 策略 / 分析身份产生；保存 JSON、Markdown、HTML。','原子文件写入；报告同页说明 qualification 与 comparability 边界。',kind='frontend'),
 n('L5 统计收据','layer5-statistics.json',P+'reporting/generator.py','generate_report','ReportID、任务 / summary / eligible count、来源与输出文件 hashes。','辅助原生数据只作诊断，不回填旧样本也不替代 selected metrics。',kind='database'),
 n('CLI 返回与事件','LAYER_5_COMPLETED',P+'runner.py','report_run_set','在运行集锁内记录 REPORTING_STARTED / COMPLETED。','返回报告路径；报告是派生工件，可基于冻结证据重建。')],['同组比较','多目标分析','单指标排名','导出表','生成图','生成报告','记录 hashes','返回'])

page('22-onboarding','算法接入、构建与资格证据','这是运行前的支撑链，具体算法使用不同工具。当前登记并不代表这些步骤对所有组合都已通过，实际状态以准入卡和任务结果为准。',[
 n('原始源码集合','read-only Source_Code',P+'codecs/registry.py','SourceRegistry','外部 Compression_Source_Code/Source_Code 保持只读。','来源 pin、license 与 translation-unit closure 先核实。',kind='external'),
 n('审查与冻结来源','SOURCE_LOCK / admission',P+'codecs/onboarding.py','validate_onboarding_card','adapters/<family> 下 SOURCE_LOCK、SOURCE_ADMISSION、contract 与 patches。','onboard_ / freeze_ / discover_ / review_ 工具按算法提供证据；不是统一自动调用链。'),
 n('复制受审源闭包','adapters/<family>/vendor','tools/build_codec.py','_build','仅取 reviewed 编译单元闭包；保持 upstream commit 与 hash。','安全 patch 与 generated source 有独立 hash；不隐式更换不同格式算法。'),
 n('ABI 适配实现','native shim / Python binding','native/include/tscb_adapter_v1.h',None,'统一 create/bound/compress/finalize/decompress/accounting/error 协议。','native/include canonical / timing headers；各 adapter 的 dtype/ISA/容量语义显式检查。'),
 n('构建多种 profile','tools/build_codec.py','tools/build_codec.py','main','release / qualification 所需 sanitizer 等 profile 由具体工具支持。','部分整数算法由 adapters/<family>/build_native.py 专门构建；不运行所有源代码。'),
 n('冻结构建证据','build-record / compile-command','tools/build_codec.py','_build','产物 SHA-256、flags、compiler、source/object closure 与运行依赖。','运行时工厂和注册表再核验受支持路径，漂移即拒绝。',kind='database'),
 n('原生 / SDK / source 资格','qualify_ / audit_','tools/qualify_simdcomp_sdk.py',None,'源 API guard、ABI smoke、边界 / 重建、SDK、upstream 与 native audit。','测试层包含 contracts / golden / unit / integration / native；具体覆盖按工具证据。',kind='security'),
 n('注册版本化清单','registry/onboarding / codecs',P+'codecs/registry.py','CodecRegistry','SourceArtifactID / AlgorithmID / AdapterID 及参数、域、ISA、计时、账本合同。','新的 SIMDComp、MaskedVByte、FastDifferential、LittleIntPacker、Simple、Simple8b-RLE 均纳入当前目录。',kind='database'),
 n('L1–L5 实验消费','configs/experiments',P+'runner.py','execute_run_set','qualification / formal / unsupported / switch 等 TOML 驱动完整控制平面。','运行 audit 审查原始样本、拒绝与报告；没有验收 fixture 就不能推断真实 corpus 性能。')])

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def scan_file(path):
    text = path.read_text()
    tree = ast.parse(text)
    symbols=[]
    def walk(node,prefix=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                name=prefix+child.name
                calls=sorted({ast.unparse(c.func) for c in ast.walk(child) if isinstance(c,ast.Call)})
                symbols.append(dict(name=name,line=child.lineno,end_line=child.end_lineno,kind=type(child).__name__,doc=ast.get_docstring(child) or '',calls=calls))
                walk(child,name+'.')
    walk(tree)
    imports=sorted({ast.unparse(x) for x in ast.walk(tree) if isinstance(x,(ast.Import,ast.ImportFrom))})
    return dict(path=str(path.relative_to(ROOT)),sha256=digest(path),lines=len(text.splitlines()),imports=imports,symbols=symbols)

def author():
    inventory=[scan_file(p) for p in sorted((ROOT/'src/tscompbench').rglob('*.py'))]
    by_path={x['path']:x for x in inventory}
    coords=[(60,85),(450,85),(840,85),(840,335),(450,335),(60,335),(60,585),(450,585),(840,585)]
    for chapter in pages:
        comps=[]
        for i,(node,pos) in enumerate(zip(chapter['nodes'],coords)):
            path=ROOT/node['source']
            assert path.is_file(),path
            symbol=node['symbol']
            info=by_path.get(node['source'])
            if not info and path.suffix=='.py':info=scan_file(path)
            match=next((s for s in (info or {}).get('symbols',[]) if s['name']==symbol),None)
            if symbol:assert match, (chapter['slug'],symbol,node['source'])
            node['line']=match['line'] if match else 1
            node['end_line']=match['end_line'] if match else min(80,len(path.read_text().splitlines()))
            node['sha256']=digest(path)
            node['id']='tscb-'+chapter['slug']+'-n'+str(i+1)
            comps.append(dict(id=node['id'],type=node['type'],label=node['label'],sublabel=node['sublabel'],pos=list(pos),size=[250,95]))
        spec=dict(schema_version=1,diagram_type='architecture',meta=dict(title='TSDataCompressBenchMark · '+chapter['title'],locale='zh-CN',quality_profile='showcase',viewBox=[1150,755]),components=comps,connections=[dict(id='tscb-'+chapter['slug']+'-e'+str(i),from_=comps[i]['id'],to=comps[i+1]['id'],label=label) for i,label in enumerate(chapter['labels'])])
        for e in spec['connections']:e['from']=e.pop('from_')
        (OUT/(chapter['slug']+'.json')).write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
    codecs=[]
    for path in sorted((ROOT/'registry/codecs').glob('*.json')):
        d=json.loads(path.read_text())
        if 'identity' in d and 'key' in d:
            codecs.append(dict(path=str(path.relative_to(ROOT)),sha256=digest(path),**d))
    datasets=[]
    for path in sorted((ROOT/'registry/datasets').glob('*.json')):
        d=json.loads(path.read_text());datasets.append(dict(path=str(path.relative_to(ROOT)),sha256=digest(path),**d))
    tools=[scan_file(p) for p in sorted((ROOT/'tools').glob('*.py'))]
    native=[dict(path=str(p.relative_to(ROOT)),sha256=digest(p)) for base in ('adapters','native') for p in sorted((ROOT/base).rglob('*')) if p.is_file() and p.suffix in {'.c','.cc','.cpp','.h','.hpp','.rs'} and 'vendor' not in p.parts]
    schemas=[dict(path=str(p.relative_to(ROOT)),sha256=digest(p)) for p in sorted((ROOT/'schemas/v2').glob('*.json'))]
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()
    evidence=dict(snapshot_date='2026-10-08',scope='CURRENT_WORKING_TREE_INCLUDING_UNCOMMITTED_FILES',base_commit=revision,repository_dirty=True,pages=pages,modules=inventory,codecs=codecs,datasets=datasets,tools=tools,native=native,schemas=schemas)
    (OUT/'source-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    build_reader(evidence)
    print(json.dumps(dict(pages=len(pages),nodes=sum(len(p['nodes']) for p in pages),modules=len(inventory),symbols=sum(len(x['symbols']) for x in inventory),codecs=len(codecs),datasets=len(datasets),tools=len(tools),native=len(native)),ensure_ascii=False))

def build_reader(evidence):
    esc=html.escape
    content=[]
    for p in pages:
        content.append('<section id="'+p['slug']+'"><p class="eyebrow">'+p['slug'].split('-')[0]+' / 运行框架</p><h1>'+esc(p['title'])+'</h1><p class="intro">'+esc(p['intro'])+'</p><p><a class="action" target="_blank" href="'+p['slug']+'.html">打开独立 Archify 图 ↗</a> <a href="'+p['slug']+'.json">JSON 规格</a></p><iframe loading="lazy" title="'+esc(p['title'])+'" src="'+p['slug']+'.html"></iframe><h2>节点、行为与源码证据</h2><div class="node-grid">')
        for i,node in enumerate(p['nodes']):
            source=ROOT/node['source']; lines=source.read_text().splitlines();line=node['line']
            snippet='\n'.join(f'{j+1:4}  {lines[j]}' for j in range(line-1,min(node['end_line'],line+25)))
            content.append('<article><span class="num">'+str(i+1).zfill(2)+'</span><h3>'+esc(node['label'])+'</h3><code>'+esc(node['sublabel'])+'</code><ul>'+''.join('<li>'+esc(x)+'</li>' for x in node['notes'])+'</ul><p class="source">'+esc(node['source'])+':'+str(line)+'</p><details><summary>查看源码节选与 SHA-256</summary><pre>'+esc(snippet)+'</pre><small>SHA-256 '+node['sha256']+'</small></details></article>')
        content.append('</div></section>')
    content.append('<section id="codec-catalog"><p class="eyebrow">附录 A / 注册表原始声明</p><h1>当前算法目录 · '+str(len(evidence['codecs']))+' 个 manifest</h1><p class="intro">下列状态是静态注册声明，资格与性能须以具体 Task / RunRecord 为准。展开查看全部输入限制、参数、源身份及工厂合同。</p>')
    for d in evidence['codecs']:
        c=d['classification'];s=d['semantics']; a=d['adapter']; inp=d['input']
        content.append('<details class="catalog searchable"><summary><b>'+esc(d['key'])+'</b><span>'+esc(c['object_level']+' · '+', '.join(c['tracks'])+' · '+', '.join(s['loss_modes']))+'</span></summary><p>'+esc(d['identity']['display_name'])+'</p><p>factory: <code>'+esc(str(a.get('factory','HARNESS_ORACLE')))+'</code></p><p>topology '+esc(', '.join(inp['topologies']))+' · dtype '+esc(', '.join(inp['dtypes']))+' · ISA '+esc(', '.join(d['execution']['isa']))+'</p><p class="source">'+esc(d['path'])+'</p><pre>'+esc(json.dumps(d,ensure_ascii=False,indent=2))+'</pre></details>')
    content.append('</section><section id="data-catalog"><p class="eyebrow">附录 B</p><h1>数据集注册目录 · '+str(len(evidence['datasets']))+'</h1>')
    for d in evidence['datasets']:
        content.append('<details class="catalog searchable"><summary>'+esc(d['key'])+'</summary><p class="source">'+esc(d['path'])+'</p><pre>'+esc(json.dumps(d,ensure_ascii=False,indent=2))+'</pre></details>')
    content.append('</section><section id="api-catalog"><p class="eyebrow">附录 C / AST 静态索引</p><h1>全部运行模块、函数与方法</h1><p class="intro">'+str(len(evidence['modules']))+' 个 Python 模块；导入与调用名称由当前源码 AST 提取。调用名称是静态语法证据，动态 dispatch 与同名函数不能由此判定真实运行因果。</p>')
    for m in evidence['modules']:
        content.append('<details class="catalog searchable"><summary>'+esc(m['path'])+'<span>'+str(m['lines'])+' 行 · '+str(len(m['symbols']))+' 个定义</span></summary><small>SHA-256 '+m['sha256']+'</small><pre>'+esc('\n'.join(m['imports']))+'</pre>')
        for s in m['symbols']:
            content.append('<details class="symbol"><summary><code>'+esc(s['name'])+'</code> :'+str(s['line'])+'–'+str(s['end_line'])+'</summary><p>'+esc(s['doc'])+'</p><pre>'+esc('\n'.join(s['calls']))+'</pre></details>')
        content.append('</details>')
    content.append('</section><section id="tool-catalog"><p class="eyebrow">附录 D</p><h1>构建、资格与审计工具</h1><p class="intro">'+str(len(evidence['tools']))+' 个工具脚本；按名称检索 onboard / build / freeze / qualify / audit 等职责。</p>')
    for m in evidence['tools']:
        content.append('<details class="catalog searchable"><summary>'+esc(m['path'])+'<span>'+str(len(m['symbols']))+' 个定义</span></summary><small>'+m['sha256']+'</small><pre>'+esc('\n'.join(s['name']+':'+str(s['line']) for s in m['symbols']))+'</pre></details>')
    content.append('</section><section id="native-catalog"><p class="eyebrow">附录 E</p><h1>原生适配、测试与 Schema</h1><p class="intro">原生文件排除 vendored 上游库，保留本项目 shim、guard、smoke 与 ABI 头。版本化 schema 文件单独列出。</p>')
    for group in ('native','schemas'):
        content.append('<h2>'+group+'</h2><table><thead><tr><th>文件</th><th>SHA-256</th></tr></thead><tbody>')
        for x in evidence[group]:content.append('<tr class="searchable"><td>'+esc(x['path'])+'</td><td class="hash">'+x['sha256']+'</td></tr>')
        content.append('</tbody></table>')
    content.append('</section><section id="receipts"><p class="eyebrow">附录 F</p><h1>快照、验收与阅读说明</h1><p>本图集基于 2026-10-08 当前工作区，包含未提交及未跟踪的新增代码。基础 commit 为 <code>'+evidence['base_commit']+'</code>。每个节点的路径、行号、节选和 SHA-256 绑定工作区内容。</p><p>Archify 的原生 repository evidence 链核验固定 commit blob，不能覆盖此次工作区新增内容。因此当前源码证据单独保存在 source-evidence.json，未把它标成固定提交核验。</p><p>本次只静态阅读源码并生成图集，没有执行算法构建或 benchmark；图集不证明每个算法的所有输入组合都通过资格。</p><p><a href="source-evidence.json">下载完整源码证据 JSON</a> · <a href="acceptance.json">查看图集验收收据</a> · <a href="README.md">Markdown 阅读说明</a></p></section>')
    nav=''.join('<a href="#'+p['slug']+'"><span>'+p['slug'].split('-')[0]+'</span>'+esc(p['title'])+'</a>' for p in pages)
    nav+=''.join('<a href="#'+i+'"><span>附</span>'+t+'</a>' for i,t in [('codec-catalog','算法清单'),('data-catalog','数据集清单'),('api-catalog','全部模块 / 函数'),('tool-catalog','构建 / 资格 / 审计'),('native-catalog','原生适配 / Schema'),('receipts','源码快照 / 验收')])
    css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#09111d;color:#d9e6f5;font:15px/1.7 system-ui,-apple-system,"Noto Sans CJK SC",sans-serif}a{color:#72d6d0;text-decoration:none}a:hover{color:#b7fffa}aside{width:270px;position:fixed;inset:0 auto 0 0;background:#101d2e;border-right:1px solid #27394d;padding:24px 18px;overflow:auto}aside h2{font-size:18px;color:#fff;margin:0}aside p{font-size:12px;color:#8196ae}nav a{display:flex;gap:10px;padding:9px 5px;font-size:13px;border-bottom:1px solid #203249}nav a span{color:#63819f;font:12px monospace;min-width:22px}input{width:100%;padding:10px;background:#07121f;color:white;border:1px solid #38516c;border-radius:8px;margin:8px 0 16px}main{margin-left:270px;padding:28px 36px;max-width:1900px}section{margin-bottom:64px;scroll-margin-top:20px}.eyebrow{letter-spacing:2px;color:#6bd7d0;font-size:12px}h1{font-size:30px;line-height:1.3;color:#fff}h2{font-size:21px;color:#f1f7ff}h3{font-size:16px;color:#e8f7ff;margin:10px 0}.intro{max-width:1100px;color:#a9bed5}iframe{width:100%;height:900px;border:1px solid #2b425d;border-radius:12px;background:#0e1825}.action{display:inline-block;background:#12363e;padding:7px 15px;border:1px solid #287c81;border-radius:6px}.node-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}article{border:1px solid #2b4058;background:#111f31;border-radius:10px;padding:18px;min-width:0}.num{font:12px monospace;color:#59c7d0}code{font-family:ui-monospace,monospace;font-size:12px;color:#9de3d6;overflow-wrap:anywhere}li{margin:6px 0}ul{padding-left:19px}.source{font:11px/1.8 monospace;color:#86a0bd;overflow-wrap:anywhere}details summary{cursor:pointer;color:#89c9df}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.65 ui-monospace,monospace;color:#b4c8e0;background:#07121d;padding:12px;border-radius:6px}small{font:10px/1.6 monospace;overflow-wrap:anywhere;color:#758eaa}.catalog{padding:14px 16px;margin:8px 0;background:#111f31;border:1px solid #283f58;border-radius:8px}.catalog summary{display:flex;justify-content:space-between;gap:14px}.catalog summary span{color:#889fb9;font-size:12px}.symbol{padding:8px;border-top:1px solid #273f54}table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:9px;text-align:left;border-bottom:1px solid #253a50}td{overflow-wrap:anywhere}.hash{font:10px monospace;color:#8195ac}[hidden]{display:none!important}@media(min-height:1000px){iframe{height:1000px}}@media(max-width:1100px){main{padding:20px}aside{width:220px}main{margin-left:220px}.node-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:750px){aside{position:relative;width:100%;max-height:330px}main{margin:0;padding:16px}.node-grid{grid-template-columns:1fr}h1{font-size:25px}iframe{height:900px}}'''
    js='''const search=document.querySelector('input');search.addEventListener('input',()=>{const q=search.value.toLowerCase().trim();document.querySelectorAll('.searchable').forEach(x=>{x.hidden=!!q&&!x.textContent.toLowerCase().includes(q)});document.querySelectorAll('nav a').forEach(x=>{x.hidden=!!q&&!x.textContent.toLowerCase().includes(q)})});'''
    document='<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSDataCompressBenchMark · 详细运行框架图集</title><style>'+css+'</style><aside><h2>TSDataCompress<br>BenchMark</h2><p>当前源码 · 2026-10-08<br>22 张运行图 / 198 个节点</p><input aria-label="搜索章节与附录" placeholder="搜索章节、算法、文件…"><nav>'+nav+'</nav></aside><main>'+''.join(content)+'</main><script>'+js+'</script></html>'
    (OUT/'index.html').write_text(document)
    md=['# TSDataCompressBenchMark 详细运行框架图集','', '日期：2026-10-08；基于当前工作区（含未提交内容），静态审阅而非 benchmark 实测。','', '打开 index.html 查看分章图集及各节点源码证据。每张独立 Archify HTML 支持缩放、搜索、主题与导出。','', '## 章节','']
    md.extend(f"- [{p['title']}]({p['slug']}.html)：{p['intro']}" for p in pages)
    md+=['','## 附录','',f"- {len(evidence['codecs'])} 个 codec manifest，{len(evidence['datasets'])} 个 dataset manifest。",f"- {len(evidence['modules'])} 个运行 Python 模块与全部定义、静态 imports/calls。",f"- {len(evidence['tools'])} 个 tools 脚本、{len(evidence['native'])} 个本项目原生文件、{len(evidence['schemas'])} 个 v2 schema。",'- source-evidence.json：工作区文件 SHA-256、节点行号与完整注册声明。','- acceptance.json：Archify 规格和 HTML 哈希、验证与浏览器证据。','','工作区来源证据与 Archify 固定 commit 验证机制不同，未声明该图集通过 fixed-commit repository verification。']
    (OUT/'README.md').write_text('\n'.join(md)+'\n')

if __name__=='__main__':author()
