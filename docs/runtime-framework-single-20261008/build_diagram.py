"""Build one source-grounded Archify canvas from the current working tree."""
from pathlib import Path
import ast
import collections
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
P = 'src/tscompbench/'
sections = []
def stage(key, label, sub, file, symbol, items):
    sections.append((key, label, sub, file, symbol, items))
def item(label, sub, file, symbol=None, kind='backend'):
    return (label, sub, P + file, symbol, kind)

stage('entry','01 · 命令与实验配置','CLI → runner；各命令按需执行不同层',P+'cli.py','main',[
 item('可执行入口','tscompbench / python -m tscompbench','cli.py','main','frontend'),
 item('数据与算法命令','datasets: list / verify / prepare；codecs: list / verify / classify-sources','cli.py','_build_parser'),
 item('run 子命令依赖','init → prepare → plan → validate；report 读取已有运行集','cli.py','_build_parser'),
 item('严格加载实验 TOML','datasets / algorithms / tracks / seed / sweep / profile / reporting','configuration.py','load_experiment_config'),
 item('配置与测量身份','生成 ExperimentConfigID、ProfileID；拒绝未知字段与非法值','configuration.py','load_experiment_config'),
 item('QUALIFICATION / FORMAL','框架资格测试与正式测量分开；正式来源仍需准入','configuration.py','BenchmarkProfile'),
 item('FORMAL 最低测量条件','预热 ≥3 次且 ≥0.5s；重复 ≥10 次；每方向最低 1–3s','configuration.py','_load_profile'),
 item('线程与资源政策','threads / processes / affinity / timeout / memory / timing_scope','configuration.py','BenchmarkProfile'),
 item('返回与退出','成功输出 JSON；配置 / I/O / 运行异常输出 stderr，退出 2','cli.py','main','frontend')])

stage('init','02 · 初始化与环境冻结','initialize_run_set：创建或严格恢复 RunSet',P+'runner.py','initialize_run_set',[
 item('输出目录与安全 ID','RunSetID 限单个路径组件；默认时间戳 + 配置摘要','runner.py','initialize_run_set'),
 item('存储与运行能力探测','检查 ≥64MiB 空闲、append/fsync、隔离与单调时钟','runner.py','_probe_workspace'),
 item('运行集文件锁','同名 flock 防并发写；各阶段分别获取和释放','runner.py','initialize_run_set','security'),
 item('创建运行集与元数据','run-set.json 保存 Runner 版本、Git 状态与工作区探测','runner.py','initialize_run_set','database'),
 item('捕获实际运行环境','CPU / ISA / OS / 软件环境 / 设备 → EnvironmentID','environment.py','capture_environment'),
 item('冻结配置与环境','frozen_config.json + environment.json；写入后不可漂移','runner.py','initialize_run_set','database'),
 item('追加启动事件','events.jsonl：RUN_SET_CREATED / RUN_SET_RESUMED','storage/events.py','append_event','database'),
 item('恢复入口的校验门','--run-set-id + --resume；配置、环境与日志必须一致','runner.py','initialize_run_set','security'),
 item('继续执行所选命令','init 到此返回；其他命令各自进入对应层','cli.py','main')])

stage('data','03 · L1 数据准备','CSV / NPZ → CanonicalArtifact + 表征',P+'runner.py','prepare_run_set',[
 item('数据集注册与源校验','registry/datasets：manifest 合同、源路径与文件 SHA-256','datasets/registry.py','DatasetRegistry','database'),
 item('加载 CSV / NPZ','声明驱动解析 timestamp、value、validity；保留实体 / 特征顺序','datasets/loaders.py','load_dataset'),
 item('逻辑语义与物理表示','拓扑、dtype、shape、单位、epoch、字节序、对齐、布局','datasets/models.py','CanonicalDataset'),
 item('规范内容身份与逻辑位数','DatasetID / 内容哈希；timestamp + value + validity 原始位数','datasets/models.py','CanonicalDataset'),
 item('写入 canonical.tscb','版本头 + 规范 JSON 元数据 + 命名缓冲区；little-endian','datasets/canonical.py','write_canonical','database'),
 item('原子落盘并重新核验','临时文件 → flush/fsync → replace；检查长度 / 描述 / 载荷哈希','datasets/canonical.py','read_canonical','security'),
 item('只读数据表征','exact / seeded sampled；分布、熵、差分、相关性及时间特征','datasets/characterize.py','characterize'),
 item('冻结 L1 产物','metadata、characterization、preparation-record、layer1-preparation','datasets/prepare.py','prepare_dataset','database'),
 item('复用已有准备结果','已有 preparation-record 时核验内容、数据身份与表征配置','datasets/prepare.py','load_preparation_result','security'),
 item('传递数据描述与缓冲区','L2 使用元数据与表征；执行阶段读取 canonical payload','runner.py','execute_run_set')])

stage('plan','04 · L2 注册、协商与任务规划','算法 × 数据集 × Track × 参数 → 冻结任务全集',P+'runner.py','plan_run_set',[
 item('读取 Source / Codec 注册表','来源、许可、availability、能力、语义、生命周期、适配器合同','codecs/registry.py','CodecRegistry','database'),
 item('别名解析与来源分类','按真实 codec key 去重；冻结 alias / source / codec snapshots','runner.py','plan_run_set'),
 item('定位适配器构建闭包','主产物 / binary / build-record / supporting artifacts 哈希校验','adapters/factory.py','adapter_artifacts','security'),
 item('展开参数 sweep','默认值、类型、范围、枚举与组合约束 → ConfigID / status','planning/sweep.py','expand_sweep'),
 item('按数据集与 Track 建描述','n / m / topology / dtype / validity / timestamp / value units','codecs/negotiation.py','descriptor_from_layer1_artifacts'),
 item('建立显式 PreprocessPlan','A–D 槽位及开关进入身份；每阶段逆变换、账本归属可核验','preprocess/contracts.py','build_preprocess_plan'),
 item('能力协商与适配计划','DIRECT_SUPPORTED / ADAPTER_LOSSLESS / ADAPTER_LOSSY / UNSUPPORTED','codecs/negotiation.py','negotiate'),
 item('解析实际执行路径','ISA / device / threads / fallback / affinity / timing → ExecutionPathHash','planning/resolution.py','resolve_execution'),
 item('构建三层可比键','Semantic → Execution → Resource；包含损失、对象、路径、预算','planning/resolution.py','build_comparability_keys'),
 item('生成与冻结 BenchmarkTask','TaskID / ProfileID / 资源限额；排序 task_plan.jsonl + resolved_configs','planning/tasks.py','write_task_plan','database'),
 item('保留不支持与非法组合','诊断任务仍进入冻结任务全集，后续计入 coverage 分母','runner.py','plan_run_set')])

stage('preflight','05 · L3 输入路由与预检','preflight_task：通过所有资格门后才允许预热',P+'execution/preflight.py','preflight_task',[
 item('选择 Track 的输入缓冲区','TIMESTAMP / VALUE / SYSTEM 是每个任务的互斥路由','execution/routing.py','route_canonical_artifact'),
 item('TIMESTAMP 路径','只编码 timestamp；原始位数分母使用 timestamp_raw_bits','execution/routing.py','route_canonical_artifact'),
 item('VALUE 路径','编码 value + validity；timestamp 留作配对验证参考','execution/routing.py','route_canonical_artifact'),
 item('SYSTEM 路径','timestamp + value + validity；冻结 SegmentPlanID 与统一分母','execution/routing.py','route_canonical_artifact'),
 item('来源、许可与运行路径门','来源完整且许可可用；Task 状态与实际 adapter_id 必须匹配','execution/preflight.py','preflight_task','security'),
 item('输入合同与显式适配','检查 dtype / shape / 单位 / 配对；复制、对齐、字节序、精确扩宽或 lossy cast','execution/preparation.py','prepare_execution_input'),
 item('已审核预处理执行器门','独立数学 / 位流 oracle 校验；来源值域拒绝保持原子性','preprocess/runtime.py','validate_pipeline_stages','security'),
 item('隔离边界套件','空数据、特殊值、容量、截断、溢出、确定性、内存安全等','validation/boundary.py','run_boundary_suite','security'),
 item('隔离最小 roundtrip','编码 → Finalize → 解码 → 正确性 + 位账本闭合','execution/repetition.py','perform_roundtrip'),
 item('生成 PreflightResult','失败写 DIAGNOSTIC / reason_code；PASS 才 eligible_for_formal_repetitions','execution/preflight.py','PreflightResult','security')])

stage('measure','06 · L3/L4 调度、隔离与测量','父进程串行任务循环；具体函数调用进入 worker',P+'execution/orchestrator.py','execute_task',[
 item('读取任务进度与缺失重复','父进程 for task；仅调度未出现的 repetition_index','runner.py','execute_run_set'),
 item('每次调用创建隔离进程','fork（可用时）/ spawn；结果与异常经单向 Pipe 返回','execution/isolation.py','run_isolated'),
 item('亲和性与内存限制','sched_setaffinity；RLIMIT_AS 保留现有 VM + 64MiB 余量','execution/isolation.py','_child'),
 item('截止时间与失败传播','父进程 deadline → terminate / kill；OOM / TIMEOUT / CRASHED','execution/isolation.py','run_isolated','security'),
 item('独立 worker 预热','重复 fresh roundtrip，次数与累计时长均满足阈值','execution/repetition.py','perform_warmup'),
 item('独立 worker 正式重复','每次重复内部是 INDEPENDENT_OBJECT；对象重新创建并 Finalize','execution/repetition.py','perform_measured_roundtrip'),
 item('最低时长分别达标','编码和解码均达到 min_repetition_seconds；E2E 还检查端到端时长','measurement/contracts.py','MeasurementPolicy'),
 item('达到上限仍未达标则失败','max_inner_iterations 防无限扩张；不发布未满足时长的数据','execution/repetition.py','perform_measured_roundtrip','security'),
 item('资源采样与可用性','RSS / PSS / USS / CPU / faults / I/O / threads / swap；scope 如实记录','measurement/resources.py','ResourceSampler'),
 item('资源资格门','swap → RESOURCE_PRESSURE；实测线程超预算 → OVERSUBSCRIBED','execution/orchestrator.py','execute_task','security'),
 item('计时状态政策','GC / cache / state / allocation / JIT 政策进入测量合同与可比身份','measurement/contracts.py','MeasurementPolicy')])

stage('session','07 · 原生适配与计时边界','同一次重复对应 finalized 对象、计时、资源与校验',P+'execution/repetition.py','perform_measured_roundtrip',[
 item('Python 工厂创建 Adapter','manifest.adapter.factory → codec adapter；Oracle 与第三方区分','adapters/factory.py','create_adapter'),
 item('适配器进入 ctypes / C ABI','Python 协议桥接本项目 native wrapper 与锁定 vendor 来源','execution/protocol.py','CodecAdapter'),
 item('创建新的编码 Session','create_session(parameters)；output_bound 分配容量 + canary','execution/repetition.py','_encode'),
 item('编码并完成对象','compress_update → finalize；尾部、字典、模型、索引都进入最终位流','execution/repetition.py','_encode'),
 item('获取账本与编码观测','accounting(stream)；SHA-256、native_timing、codec_telemetry','execution/repetition.py','_encode'),
 item('finally 关闭编码 Session','无论成功失败均 close；状态不从上一独立对象继承','execution/repetition.py','_encode'),
 item('新建解码 Session','decompress(finalized stream) → close；物化逆适配工作','execution/repetition.py','perform_measured_roundtrip'),
 item('CORE 计时','压缩 update + finalize 与 decompress 的调用时间；分别记录 encode/decode','execution/repetition.py','perform_measured_roundtrip'),
 item('PIPELINE / E2E 计时','PIPELINE 纳入适配及 session 工作；E2E 覆盖 encode→decode 的内存路径','execution/repetition.py','perform_measured_roundtrip'),
 item('原生计时独立保留','原生 clock / boundary / 分母明确；不可将部分原生总量冒充全部循环','execution/repetition.py','_native_timing'),
 item('按真实分母记录吞吐','canonical bytes、codec input bytes、native bytes、rows、value elements','measurement/contracts.py','TimingObservation')])

stage('validate','08 · 正确性、位账本与附加负载','计时之外核验，再形成该重复的最终状态',P+'execution/orchestrator.py','execute_task',[
 item('恢复消费者可见表示','逆适配后检查缓冲区身份、顺序、长度、shape 与 dtype','validation/correctness.py','validate_common_correctness','security'),
 item('时间、缺失与 T/V 配对','timestamp 精确、顺序、unit、epoch；validity 位精确与配对 reference hash','validation/correctness.py','validate_common_correctness','security'),
 item('LOSSLESS 无损检查','整数逐字节、符号与溢出；浮点 IEEE bits、NaN / Inf / ±0','validation/correctness.py','validate_common_correctness','security'),
 item('有界 / 无界损失模式','ERROR_BOUNDED_LOSSY：误差界；UNBOUNDED_LOSSY：有限域与质量表征','validation/lossy.py','validate_error_bound','security'),
 item('速率控制 / 摘要分支','RATE_CONTROLLED_LOSSY：记录目标、延后速率门；SUMMARY_ONLY：摘要与安全检查','validation/correctness.py','validate_common_correctness','security'),
 item('输入不变、canary、确定性','同一正式重复中的多次位流比较；与本次对象观测绑定','execution/repetition.py','perform_measured_roundtrip','security'),
 item('按位闭合 AccountingLedger','T / V / shared / metadata / validity / dictionary / model / index 等互斥归属','accounting/ledger.py','AccountingLedger'),
 item('最终大小与解码成本','Σcomponents = serialized_bits；FinalBits = serialized + external side info','accounting/ledger.py','AccountingLedger'),
 item('可选 Query / random access','seeded range / projection 请求在计时外生成；能力与协议均满足才执行','measurement/workloads.py','execute_query_workload'),
 item('可选 Streaming','记录首输出 / block latency、state / buffer、checkpoint / reset 等','measurement/workloads.py','execute_streaming_workload'),
 item('附加负载失败与不可用','未请求 / 不支持 / 失败各自记录；失败可将 PASS 改为 INCOMPARABLE','execution/orchestrator.py','execute_task','security')])

stage('persist','09 · 原始证据与恢复','追加记录为事实源；runs.csv 是可重建投影',P+'runner.py','execute_run_set',[
 item('构造不可漂移 RunRecord','TaskID / RunID / repetition / status / reason / timing / resources / ledger','storage/runs.py','RunRecord'),
 item('逐重复追加事实记录','run_components.jsonl：RunID 幂等写入并核验重复记录一致','storage/runs.py','append_run_record','database'),
 item('保存同对象 finalized 位流','artifacts/<RunID摘要>.bin；写入或验证 SHA-256 一致','runner.py','execute_run_set','database'),
 item('保存预检与预热观测','preflight/<TaskID>.json；warmup/<TaskID>.from-<index>.json','runner.py','execute_run_set','database'),
 item('追加运行生命周期事件','预检、warming、running、validating、accounting、terminal','storage/events.py','append_event','database'),
 item('重建 CSV 与层总结','runs.csv；layer3-execution.json / layer4-performance.json','runner.py','execute_run_set','database'),
 item('恢复前验证完整 JSONL','末行必须换行；坏 JSON 或不完整事件阻止恢复 / 分析','runner.py','_layer3_progress','security'),
 item('按任务和重复判断完成','已有 DIAGNOSTIC 整任务跳过；已有失败重复也视为已记录','runner.py','_layer3_progress'),
 item('只补缺失重复','配置 / 环境 / 任务计划仍一致；已存在记录不会自动重测','runner.py','execute_run_set'),
 item('交给独立 report 命令','报告阶段仅使用冻结证据，不再调用 codec','runner.py','report_run_set')])

stage('statistics','10 · L5 资格筛选与统计','analyze_run_set：证据只读、按可比合同聚合',P+'statistics/engine.py','analyze_run_set',[
 item('读取冻结计划与来源证据','task_plan + run_components + run-set/config/environment/snapshots','statistics/engine.py','analyze_run_set','database'),
 item('核验引用与内容身份链','重复 TaskID / RunID、missing artifact、哈希 / 账本 / 路径漂移拒绝','statistics/engine.py','_base_reasons','security'),
 item('分别判定三种分析资格','space/quality、performance、resource；每个排除原因均保留','statistics/engine.py','_eligibility','security'),
 item('正式统计的重复组门','FORMAL + 完整 PASS 重复组；BUILTIN_HARNESS / QUALIFICATION 不进正式榜','statistics/engine.py','_eligibility','security'),
 item('按数据集与路径分组','DatasetID + AlgorithmID + ConfigID + ExecutionPathHash + ProfileID + schema','statistics/engine.py','_summaries'),
 item('按 inner_iterations 归一化','时间与 CPU 使用每独立对象值；不将重复总时间当单次时间','statistics/engine.py','_per_iteration'),
 item('稳健分布统计','median / P25 / P75 / mean / sample SD / CV；不取最快一次作排名','statistics/engine.py','_stats_fields'),
 item('确定性 Bootstrap 区间','固定 seed 与 reporting policy；中位数置信区间可重现','statistics/core.py',None),
 item('独立 corpus 汇总','micro size / throughput；压缩因子几何均值；memory max/p95；CPU cost','statistics/engine.py','_corpus_summaries'),
 item('分析过程绑定原始哈希','SourceHashes 与 provenance 随汇总保留；原始证据不被报告改写','statistics/engine.py','analyze_run_set','database')])

stage('report','11 · 覆盖、比较与报告交付','generate_report：可追溯表格、图表与文档',P+'reporting/generator.py','generate_report',[
 item('Coverage 使用完整任务分母','partial / failed / unsupported / OOM / timeout 均可见；coverage 不变成分数','statistics/engine.py','_coverage'),
 item('展开三层可比上下文','Semantic 比空间；Execution 比性能；Resource 比资源','statistics/engine.py','_comparability_groups'),
 item('组内 Pareto 与 dense rank','逐指标排名；不跨 Track / LossMode / ObjectLevel / CPU-GPU 混成总榜','statistics/engine.py','_ranking_rows'),
 item('输出 7 张核心 CSV','eligibility / summary / corpus_summary / coverage / comparability / pareto / ranking','reporting/generator.py','generate_report','database'),
 item('可选阶段观测 CSV','pipeline_stages.csv：A–D enabled、wall_ns、输入输出量、最终贡献','reporting/generator.py','generate_report','database'),
 item('报告目录与统计记录','report/report.json、report.md、report.html；layer5-statistics.json','reporting/generator.py','generate_report','frontend'),
 item('嵌入确定性 SVG 图表','coverage.svg / space-encode.svg / space-decode.svg','reporting/generator.py','generate_report','frontend'),
 item('性能图按可比组拆分','DatasetID × ExecutionComparabilityKey × ProfileID，保证相邻点可比','reporting/generator.py','_pareto_svg'),
 item('汇总仍保留完整溯源链','RunIDs / 输入、位流、canonical 哈希 / 来源、binary、环境、配置、路径','statistics/engine.py','_summaries'),
 item('绑定 ReportID 与表格哈希','确定性报告 + 表格 / 图表哈希；终端返回产物路径与 eligible_run_count','reporting/generator.py','generate_report','frontend')])

W,H,DX,DY = 400,84,510,155
nodes, edges, evidence = [], [], []
source_cache = {}
def source_record(file, symbol):
    p=ROOT/file
    if not p.is_file():
        raise ValueError('Missing source: '+file)
    if file not in source_cache:
        text=p.read_text(); defs={}
        if file.endswith('.py'):
            for n in ast.walk(ast.parse(re.sub(r"(?m)^(\s*except) ([^():]+,[^:]+):",r"\1 (\2):",text))):
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    defs.setdefault(n.name,(n.lineno,n.end_lineno))
        source_cache[file]=(hashlib.sha256(p.read_bytes()).hexdigest(),defs)
    sha,defs=source_cache[file]
    span=defs.get(symbol)
    if symbol and span is None: raise ValueError(f'Missing symbol {symbol} in {file}')
    return dict(path=file,symbol=symbol,line=span[0] if span else 1,end_line=span[1] if span else None,sha256=sha)
def add(id,label,sub,x,y,file=None,symbol=None,kind='backend',width=W):
    tag=''
    if file:
        record=source_record(file,symbol)
        evidence.append(dict(node_id=id,**record))
        tag=file.removeprefix(P)+':'+str(record['line'])
    nodes.append(dict(id=id,type=kind,label=label,sublabel=sub,tag=tag,pos=[x,y],size=[width,H]))
    return id

def edge(a,b,label=None,variant='default'):
    d=dict(id='e_'+a+'_'+b,from_=a,to=b,variant=variant)
    d['from']=d.pop('from_')
    if label: d['label']=label
    if label in ('展开','细节续列'): d['labelDy']=24
    edges.append(d)

# One main rail. Dashed edges below it expose implementation details, not another run.
for col,(key,label,sub,file,symbol,items) in enumerate(sections):
    x=110+col*DX
    add(key,label,sub,x,270,file,symbol,'frontend' if col in (0,10) else 'database' if col==8 else 'backend')
    if col: edge(sections[col-1][0],key,['启动','准备','描述','任务计划','资格通过','调用','观测','结果','run report','分析产物'][col-1],'emphasis')
    prev=key
    for row,(label,sub,file,symbol,kind) in enumerate(items):
        id=key+'_detail_'+str(row+1)
        add(id,label,sub,x,490+row*DY,file,symbol,kind)
        # These links express a reading expansion, not runtime causality.
        edge(prev,id,'展开' if row==0 else '细节续列','dashed')
        prev=id

# Explicit reading and evidence notes are part of the same SVG.
add('reading','阅读方式：横向主流程，纵向节点展开','粗实线表示数据 / 控制依赖；虚线只串联同阶段细节，不能当作逐条执行顺序',110,75,kind='external',width=1600)
add('scope','运行边界：本地 Python 控制平面 + 隔离 Native worker','项目要求 Python ≥3.14 / NumPy ≥2.5；L3/L4 共用生命周期，report 单独触发；2026-10-08 工作区静态审阅',1900,75,kind='external',width=1600)
add('identity','身份链：Dataset → Algorithm / Source → Config → Execution → Task → Run → Report','内容哈希、文件哈希、EnvironmentID、ProfileID 与三层可比键贯穿运行和报告',3690,75,kind='security',width=1600)

# Reviewed preprocessing paths, visible alongside runtime on this one canvas.
pipelines=[
 ('pipeline_a','StreamVByte A · 语义变换','checked int64 Delta + ZigZag → uint64；首值 seed；检查溢出','preprocess/streamvbyte.py'),
 ('pipeline_b','StreamVByte B · 数据布局','uint64 拆为交错 low/high uint32 limbs；独立 oracle 验证','preprocess/streamvbyte.py'),
 ('pipeline_c','StreamVByte C · 编码后端','LZBENCH 或 modern StreamVByte；保留控制字节与值域合同','preprocess/streamvbyte_modern.py'),
 ('pipeline_d','StreamVByte D · 独立解码封装','native frame + canonical descriptor + checksum；D 不允许禁用','preprocess/streamvbyte.py'),
 ('pipeline_inverse','StreamVByte 逆向与成本归属','D⁻¹ → C⁻¹ → B⁻¹ → A⁻¹；stage timing / bytes / final bits 分别记录','preprocess/runtime.py'),
 ('masked_fused','MaskedVByte · 融合 A/B + D','modular D1 + LEB128 uint32；C 无后端；融合阶段不虚构独立时间','preprocess/maskedvbyte.py'),
 ('simd_fused','SIMDComp · 融合 A/B + D','modular D1 / 固定 FOR + bitpack；C 无后端；尾块与 width32 合同','preprocess/simdcomp.py'),
 ('pipeline_switch','预处理开关的比较边界','开关改变 ConfigID / ExecutionPathHash；不同融合路径不共用计时语义','preprocess/contracts.py')]
for i,(id,label,sub,file) in enumerate(pipelines):
    add(id,label,sub,110+i*650,2280,P+file,kind='backend',width=535)
    if 0<i<5: edge(pipelines[i-1][0],id,'可逆阶段')
# Admitted executor branch from the preflight subtree to the pipeline strip.
# This is a support description; the catalogue below is a static registry inventory.

# Build/onboarding is a real supporting lifecycle, separate from the measured path.
build_steps=[
 ('source_admit','接入 ① 原始来源与许可','Source_Code 只读；来源身份 / license / availability / admission 证据','codecs/onboarding.py'),
 ('source_freeze','接入 ② 冻结来源与补丁','vendor + SOURCE_LOCK + patches；变更必须有 provenance 与审核记录','codecs/registry.py'),
 ('native_build','接入 ③ 构建 Native wrapper','tools/build_codec.py；本项目 adapters/*/native + vendor → .so','adapters/factory.py'),
 ('abi_qualify','接入 ④ ABI / source / sdk 验证','tools/qualify_* / audit_*；边界、原生计时、源码与构建闭包证据','codecs/onboarding.py'),
 ('register_codec','接入 ⑤ 登记并冻结合同','registry/sources + onboarding + codecs；能力声明与 provenance 引用','codecs/registry.py'),
 ('benchmark_qualify','接入 ⑥ 针对具体组合正式准入','配置/数据/ISA/Track 仍需运行时预检与 FORMAL 测量，登记不等于全通过','execution/preflight.py')]
for i,(id,label,sub,file) in enumerate(build_steps):
    add(id,label,sub,110+i*890,2525,P+file,kind='security' if i in(0,3,5) else 'backend',width=700)
    if i: edge(build_steps[i-1][0],id,'准入证据')

# All registered codec keys and datasets are authored as visible text, not hidden chapters.
codec_docs=[]
for p in sorted((ROOT/'registry/codecs').glob('*.json')):
    d=json.loads(p.read_text())
    if 'adapter' in d:
        codec_docs.append((p,d))
by_factory=collections.defaultdict(list)
for p,d in codec_docs:
    by_factory[d['adapter'].get('factory') or d.get('classification',{}).get('kind','HARNESS_ORACLE')].append(d['key'])
catalog=[]
for factory,keys in sorted(by_factory.items()):
    for off in range(0,len(keys),2):
        pair=keys[off:off+2]
        catalog.append((pair[0],pair[1] if len(pair)>1 else '此工厂下的登记算法',factory))
for i,(label,sub,factory) in enumerate(catalog):
    row,col=divmod(i,11)
    add('codec_'+str(i+1),label,sub,110+col*DX,2850+row*DY,kind='external')
    nodes[-1]['tag']=factory

last_y=2850+(len(catalog)-1)//11*DY+H
# Dataset inventory is also visible. Group into pairs without dropping any key.
datasets=[]
for p in sorted((ROOT/'registry/datasets').glob('*.json')):
    d=json.loads(p.read_text());datasets.append(d.get('key',p.stem))
for i in range(0,len(datasets),2):
    add('dataset_'+str(i//2+1),datasets[i],datasets[i+1] if i+1<len(datasets) else '数据集',110+(i//2)*DX,last_y+185,kind='database')
    nodes[-1]['tag']='registry/datasets/*.json'
end_y=last_y+185+H
spec=dict(schema_version=1,diagram_type='architecture',meta=dict(
 title=f'TSDataCompressBenchMark · 单图详细运行框架 · {len(nodes)} 节点',
 locale='zh-CN',quality_profile='standard',viewBox=[5750,end_y+150],
 legend=dict(mode='auto',entries=dict(frontend=dict(label='入口 / 阅读输出'),backend=dict(label='运行 / 适配 / 测量'),database=dict(label='数据 / 冻结证据'),security=dict(label='合同 / 资格 / 校验门'),external=dict(label='说明 / 注册目录')))),
 components=nodes,connections=edges,boundaries=[
 dict(kind='region',label='运行前支撑链：来源冻结 → 构建 → 资格认证 → 注册；具体工具因算法而异',wraps=[x[0] for x in build_steps],pad=32),
 dict(kind='region',label=f'算法注册目录：{len(codec_docs)} 个 CodecManifest；逐个列出 key，工厂为辅助来源标记（登记 ≠ 所有组合已正式准入）',wraps=['codec_'+str(i+1) for i in range(len(catalog))],pad=32),
 dict(kind='region',label=f'数据集注册目录：{len(datasets)} 个 DatasetManifest；实际源文件由各 manifest 指定',wraps=['dataset_'+str(i//2+1) for i in range(0,len(datasets),2)],pad=32),
 dict(kind='region',label='显式预处理细化：A–D 是已审核执行器的合同槽；StreamVByte、MaskedVByte、SIMDComp 语义分别核验',wraps=[x[0] for x in pipelines],pad=32)] )
(OUT/'runtime.archify.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
for p,d in codec_docs:
    source_record(str(p.relative_to(ROOT)),None)
for p in sorted((ROOT/'registry/datasets').glob('*.json')):
    source_record(str(p.relative_to(ROOT)),None)
sha_docs={path:value[0] for path,value in sorted(source_cache.items())}
(OUT/'source-evidence.json').write_text(json.dumps(dict(date='2026-10-08',basis='current working tree including uncommitted files; not fixed-commit repository verification',nodes=evidence,files=sha_docs,codecs=[d['key'] for p,d in codec_docs],datasets=datasets),ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(nodes=len(nodes),edges=len(edges),codecs=len(codec_docs),datasets=len(datasets),viewBox=spec['meta']['viewBox']),ensure_ascii=False))
