"""One source-backed five-layer figure, with a custom SVG renderer and HTML viewer."""
from pathlib import Path
import ast, datetime, hashlib, heapq, html, json, math, re, subprocess
from PIL import Image, ImageFont

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
REF = ROOT / 'docs/archify-five-layer-reference'
PRIOR = ROOT / 'docs/architecture-redraw-20261012'
old = json.loads((REF / 'semantic-model.json').read_text())
old_evidence = json.loads((REF / 'source-evidence.json').read_text())
prior_evidence = json.loads((PRIOR / 'source-evidence.json').read_text())
by_id = {n['id']: n for n in old['nodes']}
ev_by_id = {n['id']: n for n in old_evidence['nodes']}
prior_by_id = {n['id']: n for n in prior_evidence['nodes']}
W, H = 2240, 4972
PITCH = 254
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
FONTS = {}
def width(s, size):
    if size not in FONTS: FONTS[size] = ImageFont.truetype(FONT, size)
    return FONTS[size].getlength(s)
def wrap(s, size, limit):
    result, line = [], ''
    for word in re.findall(r'[A-Za-z0-9_.*/-]+|\s+|[^A-Za-z0-9_.*/\s-]', s):
        if word.isspace():
            if line and not line.endswith(' '): line += ' '
            continue
        chunks, chunk = [], ''
        for ch in word:
            if chunk and width(chunk + ch, size) > limit:
                chunks.append(chunk); chunk = ch
            else: chunk += ch
        if chunk: chunks.append(chunk)
        for chunk in chunks:
            if line and width(line + chunk, size) > limit:
                result.append(line.rstrip()); line = chunk
            else: line += chunk
    if line: result.append(line.rstrip())
    return result

phases = [
    dict(id='data', title='数据准备', en=['Data','Preparation'], y=132, h=568,
         duties=['校验来源与内容身份','保留完整原对象语义','准备可复用输入与特征'],
         rows=['入口、来源与冻结身份','原域加载与两种对象表示'],
         outputs=['DatasetID / Manifest / 内容 SHA','特征报告 / 准备记录 / RawBits','Legacy Canonical Binary','P2 LogicalObject / Typed Schema'],
         constraints=['不隐式排序、cast 或填充','T / V / validity 保持配对','显式派生与完整父级 lineage','dtype / shape / 轴 / 单位冻结','P2 不强制 Legacy 二进制格式']),
    dict(id='plan', title='能力与配置', en=['Capability &','Configuration'], y=732, h=822,
         duties=['展开完整合法候选空间','编译事前比较合同','冻结执行闭包与真实调度'],
         rows=['注册能力与完整候选空间','Legacy：显式计划与任务快照','V3.2：比较合同、成员准入与冻结作业'],
         outputs=['Codec / Source / ConfigID','Legacy task_plan.jsonl / 三级键','Task / Contract / Group / Corpus','ConfigMap / Expected Matrix','Job / Recipe / Closure / Schedule'],
         constraints=['不支持单元也保留在固定分母','参数、别名、ISA 不增加方法数','CORE：两方法与两独立真实来源','共同 API 的实际 schema / bytes 相同','Legacy 比较键不授予新组资格','协议和 AnalysisPolicy 在测量前冻结']),
    dict(id='exec', title='执行验证', en=['Execution &','Validation'], y=1586, h=1602,
         duties=['校验实际输入与边界安全','独立恢复与开发 pilot 门禁','分路径执行完整对象','按原域验证结果与成本'],
         rows=['实际输入、安全与预处理执行','完整恢复与 Preflight 判定','V3.2 资格 / pilot 与 Legacy worker 预热','四条独立执行路径 · 各自 runner 与合同','P1 完整对象生命周期 · 正式执行内部展开','公共正确性、损失模式与 P2 对象恢复'],
         outputs=['Preflight / 失败原因 / 资格证据','独立 development pilot 记录','Legacy / comparison / workload / P2','Finalize 后的完整保存产物','原域 correctness / AccountingLedger'],
         constraints=['资格与 pilot 通过才开放正式试次','每个内循环对象独立 Finalize','最后一个对象提供公共验证与成本','不可变 / canary / determinism 累计','独立恢复从保存字节和付费依赖开始','steady 正式解码在同一测量 worker','预热固定门槛不证明统计稳态','Rate / Summary：框架 validator','流程实现不代表当前 FORMAL 合格']),
    dict(id='measure', title='性能测评', en=['Performance','Evaluation'], y=3220, h=822,
         duties=['同次采集计时与资源','按独立 Profile 测量','保存持久试次与状态','审计预算、中断与恢复'],
         rows=['同次测量的策略、边界与资源约束','进程资源与条件工作负载','按所属 runner 留证、恢复与可用性'],
         outputs=['CORE / PIPELINE / E2E / cold 边界','wall / CPU / RSS / I/O / 线程观测','Legacy run_components / runs.csv','comparison / workload / P2 trials','Artifacts / STARTED / Events / 预算'],
         constraints=['计时和资源来自同一试次','测量层是执行职责，不是另跑实验','stream / query 各自冻结协议','未知 STARTED 不得静默重测','P2 持久预算预留与提交事件链','已完成执行的 resume 为 no-op','不可用 counters 如实标记']),
    dict(id='stats', title='统计分析与报告', en=['Statistics &','Reporting'], y=4074, h=822,
         duties=['先资格过滤再统计','真实调度块配对分析','固定全集呈现质量与缺口','输出报告与逐范围验收'],
         rows=['Legacy：冻结证据、资格与逐数据集统计','V3.2 配对分析与 Legacy 描述性结果','报告交付、参考成本与独立范围验收'],
         outputs=['Legacy median / CSV / 三级键分组','V3.2 均值时间比 / block bootstrap','质量 / Pareto / Coverage / 缺口','analysis.json / HTML / P2 report.md','Completion / 条款与范围审计'],
         constraints=['只读冻结 plan 与原始产物','配对来自真实 Schedule block','多重区间 / 精度 / 实用差异检验','失败、缺测、NOT_RUN 保留分母','精度或资格不足保留 INCONCLUSIVE','推断限于冻结 corpus 与本机','参考成本和辅助审计不转授资格']),
]
rows = {
    'data': [['entry','freeze','dataset','source_identity'],['loader','characterize','canonical','logical_object']],
    'plan': [['registry','sweep','universe','negotiate'],['plans','resolution','keys','tasks'],['experiment_contract','expected_matrix','public_projection','frozen_schedule']],
    'exec': [['gates','track','input','adapter'],['preprocess','boundary','minimal','preflight'],['object_qualification','development_pilot','warmup','diagnostic'],['formal','comparison_execute','workload_execute','p2_execute'],['compress','finalize','accounting','decompress'],['correctness','lossless','lossy','p2_object']],
    'measure': [['policy','timing','measurement_boundary','resource_lease'],['resources','workloads','query','streaming'],['raw','trial_store','resume_audit','availability']],
    'stats': [['evidence','eligibility','summary','corpus'],['paired_analysis','quality_coverage','pareto','coverage'],['report','v32_reports','reference_cost','scope_acceptance']],
}
overrides = {
    'entry': ('Legacy 命令与配置',['cli.py / Benchmark Runner','ExperimentConfig / TOML']),
    'freeze': ('运行身份与环境冻结',['initialize_run_set','配置 / Environment / 锁','恢复时校验一致性']),
    'dataset': ('数据集注册与校验',['DatasetRegistry / Manifest','源文件 SHA-256 校验']),
    'source_identity': ('内容身份与显式派生',['DatasetID / 内容 SHA','父级来源与完整 lineage','f32 / uint8 / ND：分别冻结']),
    'loader': ('原域数据加载',['load_dataset','保留 T / V / validity','顺序 / dtype / shape 不隐改']),
    'characterize': ('数据特征分析',['characterize','Timestamp / Value / Topology','只读原域特征']),
    'canonical': ('Legacy Canonical 工件',['prepare_dataset / write_canonical','二进制 / Manifest / 特征','准备记录 / 原始 RawBits']),
    'logical_object': ('P2 逻辑原对象',['LogicalObject / Typed Schema','T / V / mask / shape / time_axis','mixed / ND / channel collection']),
    'registry': ('Codec / Source 注册',['CodecManifest / SourceArtifact','输入域 / 损失模式 / 资源能力','来源与构建工件身份']),
    'sweep': ('参数扫描与配置生成',['expand_sweep / ConfigID','完整合法参数空间']),
    'universe': ('完整候选组合展开',['Dataset × Algorithm × Track','× Config × Profile','期待全集保留所有单元']),
    'negotiate': ('能力协商 · 四态结果',['DIRECT_SUPPORTED','ADAPTER_LOSSLESS','ADAPTER_LOSSY','UNSUPPORTED']),
    'plans': ('显式适配与预处理计划',['CompatibilityPlan / PreprocessPlan','此处声明，执行层验证','恢复依赖须公开并计量']),
    'resolution': ('执行路径解析',['ISA / Device / Threads / Affinity','Fallback / 工件 / 路径身份','resolve_execution']),
    'keys': ('Legacy 层级可比性键',['ExecutionPathHash','Semantic → Execution → Resource','三类键按层级嵌套']),
    'tasks': ('Legacy 任务快照',['BenchmarkTask / task_plan.jsonl','冻结计划与注册身份','不支持任务保留原因']),
    'experiment_contract': ('事前实验决策与合同',['Task / Contract / Group / Corpus','ConfigMap / Protocol','Expected / AnalysisPolicy']),
    'expected_matrix': ('期待矩阵与成员准入',['MethodID / ImplementationID 去重','CORE：两方法 / 两真实来源','PASS / REJECT / BLOCKED']),
    'public_projection': ('公共投影与实际输入',['原对象 / COMMON_NATIVE_API','实际 schema / bytes / 路径披露','P2 recipe / child / block / tail']),
    'frozen_schedule': ('冻结作业、闭包与调度',['ExecutionJob / Recipe / Closure','Build / Environment / CPU / Threads','Schedule block / pair / 重复']),
    'gates': ('任务、来源与构建门控',['任务状态 / 源码 / 构建工件','注册 adapter 与阶段执行器']),
    'track': ('按 Benchmark Track 路由',['TIMESTAMP：时间戳','VALUE：值 / validity','SYSTEM：T + V / Segment Plan']),
    'input': ('实际输入校验',['validate_routed_input','输入描述 / 内容哈希 / 契约']),
    'adapter': ('适配与适配后校验',['Compatibility Adapter','prepare_execution_input','验证真实转换后的 buffers']),
    'preprocess': ('可选预处理阶段验证',['validate_pipeline_stages','声明 / 执行器 / 阶段证据一致','仅按显式计划执行']),
    'boundary': ('边界与安全 Dry-run',['run_boundary_suite','空输入 / 边界 / 容量','输出 canary 与内存安全']),
    'minimal': ('最小完整 Roundtrip',['Common Correctness','保存产物 / clean worker','独立恢复原域对象']),
    'preflight': ('Preflight',['正确性与安全门控']),
    'object_qualification': ('V3.2 原对象资格',['Preflight / 原域 correctness','保存字节 / paid decode context','独立恢复 / 期待矩阵核对']),
    'development_pilot': ('独立 development pilot',['与评价对象分离的开发输入','方向时钟 / 内循环 / 粒度','采集器扰动 / 正式执行门禁']),
    'warmup': ('Legacy worker 内预热',['每个隔离测量进程内执行','Warmup 排除于计时边界','固定次数与时长门槛']),
    'diagnostic': ('失败状态与原因留证',['UNSUPPORTED / BUILD / ISA','CORRECTNESS / BOUND / SAFETY','TIMEOUT / OOM / CRASHED','阻断正式执行，保留证据']),
    'formal': ('Legacy 正式执行',['execution/orchestrator.py','execute_task / 隔离 worker','自己的 repetitions / policy']),
    'compress': ('独立 Context 与编码',['create_session / output_bound','compress_update','检查输入不可变与 canary']),
    'finalize': ('强制 Finalize / Flush',['每个内循环对象独立结束','Update + Finalize 完整流','尾部字节随产物保存']),
    'accounting': ('完整对象成本计量',['AccountingLedger / FinalBits','完整流 + 外部恢复 side info','依赖 / metadata / 容器 / tail']),
    'decompress': ('独立 Context 解码',['物化输出 / restore_decoded_output','恢复原域 dtype / shape','steady：同一测量 worker']),
    'correctness': ('公共正确性与 LossMode',['T-V pairing / channel / shape','原域 validity / dtype','immutability / determinism 累计']),
    'lossless': ('Lossless 按位还原',['LOSSLESS：值数据按位一致','保留 dtype / IEEE bits','时间、通道、mask 一并校验']),
    'lossy': ('Lossy 与专用模式验证',['Error-bounded：界 + 质量','Unbounded：质量，无界保证','Rate / Summary：专用 validator','无活动算法或正式组自动资格']),
    'p2_object': ('P2 完整对象与恢复',['全部 T / V / mask / typed schema','列 / 块子流 / 容器 / RAW_TAIL','paid child 依赖 / 保存字节','独立 decoder 验证原对象']),
    'policy': ('Legacy MeasurementPolicy',['冻结 scope 与时长策略','共享 repetition 的同次观测','CORE / PIPELINE / E2E']),
    'timing': ('方向计时与时长控制',['Encode / Decode 分别达标','wall / process CPU 真时钟','内循环逐对象 Finalize']),
    'measurement_boundary': ('V3.2 生命周期与边界',['完整对象：steady / cold PIPELINE','共同 native API：steady CORE','独立 scope 的成本与时间分母']),
    'resource_lease': ('资源租约与环境门控',['ResourceLease / CPU / Threads','RSS / Affinity / 总 wall 预算','父进程线程与环境观测']),
    'resources': ('同步进程资源观测',['ResourceSampler：同一试次','CPU / RSS / I/O / Memory','保存进程资源和线程证据']),
    'workloads': ('Profile 工作负载选择',['Legacy：请求且 codec 支持','V3.2：独立 workload runner','协议 / requests / sequence 冻结']),
    'query': ('Query / Random Access',['请求 / 会话 / cache 模式','延迟 / 读取放大 / 正确性','按所属 Profile 单独留证']),
    'streaming': ('Streaming Benchmark',['chunk latency / state / finalize','序列与会话边界冻结','checkpoint 按实际能力留证']),
    'raw': ('Legacy 原始记录与投影',['run_components.jsonl：权威记录','runs.csv：可重建扁平投影','events.jsonl / 产物与诊断']),
    'trial_store': ('V3.2 持久试次与产物',['comparison / workload / P2 trials','artifacts / append-only events','STARTED / 固定分母 / 失败终态']),
    'resume_audit': ('中断、预算与恢复审计',['未知 STARTED 禁止自动重测','P2 预算预留 / COMMITTED 链','完成后 no-op resume','漂移时建立新的运行身份']),
    'evidence': ('Legacy 冻结证据读取',['task_plan / raw / provenance','只读核对完整证据链','CSV 不是权威统计输入']),
    'eligibility': ('资格过滤与排除原因',['来源 / 正确性 / 正式模式','计量 / 完整重复 / 路径核对','PASS 本身不足以入统计']),
    'summary': ('Legacy 逐数据集统计',['Dataset / Algorithm / Config','ExecutionPath / Profile / schema','median / 分位数 / bootstrap CI']),
    'corpus': ('Legacy Corpus 与分层比较',['先逐数据集，再 corpus 汇总','Semantic：空间与质量','Execution：性能 / Resource：资源']),
    'paired_analysis': ('V3.2 只读重核与配对',['先 trial_issues 资格过滤','均值时间比 / block bootstrap','真实 Schedule / 多重区间','精度与实用效应检验']),
    'quality_coverage': ('V3.2 原域质量与全矩阵',['原域误差 / 实际 FinalBits','Pareto / 公共投影 / 固定 corpus','缺口与 INCONCLUSIVE 保留']),
    'pareto': ('Legacy Pareto 与排名',['Pareto / 单指标排名','只在对应可比性组内比较']),
    'coverage': ('Legacy 冻结全集 Coverage',['由冻结 tasks + records 计算','无 PASS / 不支持 / 失败全保留','覆盖率不换算为评分']),
    'report': ('Legacy 报告生成',['generate_report','CSV / JSON / Markdown / HTML','引用冻结身份与原始证据']),
    'v32_reports': ('V3.2 各路径报告',['analysis JSON / HTML / P2 MD','comparison / workload / P2','资格 / pilot / raw 证据引用']),
    'scope_acceptance': ('独立范围与条款验收',['completion / no-op resume / 条款','SOURCE_PARITY / CORE / PROFILE','FORMAL 等范围独立验收','结论仅限冻结 corpus 与本机']),
}
new_nodes = {
    'comparison_execute': ('V3.2 comparison 执行',['comparison/runner.py','steady / cold 完整对象','COMMON_NATIVE_API CORE'], 'comparison_execute', 'process'),
    'workload_execute': ('独立 workload 执行',['comparison/workload_runner.py','stream / query 专用协议','独立 pilot / 调度 / 试次'], 'workload_execute', 'process'),
    'p2_execute': ('P2 pipeline 执行',['comparison/pipeline_runner.py','LogicalObject + PipelineRecipe','独立 runtime / recovery / 预算'], 'p2_execute', 'process'),
    'availability': ('采集器与可用性披露',['collector 扰动在 pilot 中核验','测量不扣除 collector 开销','Energy / counters 如实 availability'], 'trial_observation', 'validation'),
    'reference_cost': ('参考成本与辅助审计',['未压缩 SIZE_BASELINE','buffer / harness cost / 恢复审计','辅助证据不转授正式资格'], 'scope_acceptance', 'validation'),
}
nodes, boxes, sources = [], {}, {}
for p in phases:
    for r, ids in enumerate(rows[p['id']]):
        for col, id in enumerate(ids):
            if id in new_nodes:
                label, lines, base_id, role = new_nodes[id]
                ev = prior_by_id.get(base_id, ev_by_id.get(base_id))
                refs = ev.get('sources', ev.get('evidence', []))
                desc = ev.get('description', '')
            else:
                n = by_id[id]; label, lines = overrides[id]; role = n['role']
                refs = ev_by_id[id]['evidence']; desc = n.get('detail','')
            if id in ['object_qualification','development_pilot','workloads','v32_reports']:
                extra_id = {'object_qualification':'qualification_gate','development_pilot':'pilot_gate','workloads':'workload_plan','v32_reports':'scoped_reports'}[id]
                refs = refs + prior_by_id[extra_id]['sources']
            if id=='development_pilot':
                refs = refs + [dict(path='src/tscompbench/comparison/workload_runner.py',symbol='pilot_workload_comparison')]
            unique = {(x['path'], x['symbol']): x for x in refs}
            sources[id] = list(unique.values())
            nodes.append(dict(id=id, phase=p['id'], label=label, lines=lines, role=role, description=desc))
            boxes[id] = [356 + col*362, p['y']+90+r*PITCH, 318, 178]

# Logical/control/evidence edges; expansions do not imply another benchmark run.
edges = []
def edge(a,b,kind='flow',label='',sa=None,sb=None,meaning=None):
    ax,ay,aw,ah=boxes[a]; bx,by,bw,bh=boxes[b]
    if not sa or not sb:
        if ay==by: sa,sb=('right','left') if bx>ax else ('left','right')
        elif ax==bx: sa,sb=('bottom','top') if by>ay else ('top','bottom')
        else: sa,sb=('bottom','top') if by>ay else ('top','bottom')
    edges.append(dict(id=a+'--'+b,source=a,target=b,kind=kind,label=label,sides=[sa,sb],meaning=meaning or '处理、数据或证据依赖；不宣称是直接函数调用。'))
def chain(ids):
    for a,b in zip(ids,ids[1:]): edge(a,b)
chain(['entry','freeze','dataset','source_identity'])
edge('dataset','loader',sa='bottom',sb='left')
chain(['loader','characterize','canonical'])
edge('source_identity','logical_object','evidence',meaning='P2 逻辑对象保留冻结内容身份与来源链；不要求先写 Legacy wire。')
edge('loader','logical_object','evidence',sa='bottom',sb='bottom')
edge('canonical','registry','evidence',sa='bottom',sb='left',meaning='Legacy 数据准备是规划前提；不表示工件调用注册表。')
chain(['registry','sweep','universe','negotiate'])
edge('negotiate','plans',sa='bottom',sb='left')
chain(['plans','resolution','keys','tasks'])
edge('logical_object','experiment_contract','evidence',sa='right',sb='left')
chain(['experiment_contract','expected_matrix','public_projection','frozen_schedule'])
edge('tasks','gates',sa='right',sb='left')
edge('frozen_schedule','object_qualification','evidence',sa='right',sb='left')
chain(['gates','track','input','adapter'])
edge('adapter','preprocess',sa='bottom',sb='left')
chain(['preprocess','boundary','minimal','preflight'])
edge('preflight','warmup',label='通过')
edge('preflight','diagnostic','error','失败留证')
edge('object_qualification','development_pilot')
edge('development_pilot','comparison_execute',label='pilot 通过')
edge('development_pilot','workload_execute','conditional',sa='bottom',sb='top',meaning='各 workload 使用自己的冻结协议与独立 pilot；通过后开放该路径。')
edge('development_pilot','p2_execute','conditional',sa='bottom',sb='top',meaning='P2 使用自己的 development 输入和 pilot；此处表示共通门禁职责。')
edge('warmup','formal',sa='bottom',sb='top')
edge('formal','compress','expansion')
edge('comparison_execute','compress','expansion',sa='bottom',sb='top',meaning='完整对象 PIPELINE 路径包含 P1 对象生命周期；CORE 仅测其注册组件边界。')
chain(['compress','finalize','accounting','decompress'])
edge('decompress','correctness',sa='bottom',sb='left')
edge('correctness','lossless')
edge('correctness','lossy',label='按有损模式',sa='bottom',sb='bottom')
edge('p2_execute','p2_object','expansion',sa='right',sb='right',meaning='P2 是独立完整对象 runtime，不共用 Legacy wire。')
edge('formal','policy','scope',sa='left',sb='left',meaning='测量层表示同一正式试次的职责投影，非再执行一轮。')
edge('comparison_execute','measurement_boundary','scope',sa='left',sb='top')
edge('workload_execute','trial_store','evidence',sa='right',sb='left')
edge('p2_object','trial_store','evidence',sa='bottom',sb='right')
edge('diagnostic','raw','evidence',sa='right',sb='left')
chain(['policy','timing'])
edge('policy','resources','scope')
edge('measurement_boundary','resource_lease','scope')
edge('timing','workloads','conditional')
edge('workloads','query','conditional')
edge('workloads','streaming','conditional',sa='top',sb='top')
edge('resources','raw','evidence')
edge('query','raw','evidence',sa='bottom',sb='right',meaning='Legacy 请求且支持的 Query 辅助结果写入其 run record；V3.2 workload 有独立 trials。')
edge('streaming','raw','evidence',sa='bottom',sb='top',meaning='Legacy Streaming 辅助结果归自身 raw；V3.2 workload 独立留证。')
edge('resource_lease','trial_store','evidence',sa='bottom',sb='top')
edge('trial_store','resume_audit','evidence')
edge('availability','trial_store','evidence',sa='bottom',sb='bottom')
edge('raw','evidence','evidence')
edge('trial_store','paired_analysis','evidence',sa='bottom',sb='left')
chain(['evidence','eligibility','summary','corpus'])
edge('evidence','coverage','evidence',sa='top',sb='right',meaning='Coverage 从完整冻结 tasks 和 raw 求得，不从通过资格的 summaries 推算。')
edge('summary','pareto')
edge('corpus','report','evidence',sa='bottom',sb='left')
edge('pareto','report',sa='bottom',sb='right')
edge('coverage','report',sa='bottom',sb='top')
edge('paired_analysis','quality_coverage','evidence',meaning='同一冻结证据的只读描述性质量/Pareto/Coverage 扩展，不改变配对分析估计量。')
edge('quality_coverage','v32_reports')
edge('v32_reports','scope_acceptance','evidence',sa='bottom',sb='bottom')
edge('reference_cost','scope_acceptance','evidence')
model=dict(title='TSDataCompressBenchMark · 五层运行框架与数据流',phases=phases,nodes=nodes,edges=edges,
           basis='当前工作区源码（含已有未提交修改）',as_of='2026-10-12',
           semantics='有向处理 / 控制 / 证据依赖；scope 表示同次观测，expansion 表示对象内部展开。')

# Freeze exact node/edge source anchors against current file bytes.
file_records, evidence_nodes = {}, []
def bind(ref):
    rel, name = ref['path'], ref['symbol']; path=ROOT/rel; data=path.read_bytes()
    tree=ast.parse(data)
    found=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name]
    if name not in ['module',None] and len(found)!=1: raise ValueError((rel,name,len(found)))
    sha=hashlib.sha256(data).hexdigest()
    if 'sha256' in ref and ref['sha256']!=sha: raise ValueError('Stale source evidence: '+rel)
    file_records[rel]=dict(path=rel,sha256=sha,bytes=len(data))
    n=found[0] if found else None
    return dict(path=rel,symbol=name or 'module',line=n.lineno if n else 1,end_line=n.end_lineno if n else len(data.splitlines()),sha256=sha)
for n in nodes:
    evidence_nodes.append(dict(id=n['id'],phase=n['phase'],label=n['label'],evidence=[bind(r) for r in sources[n['id']]]))
for e in edges:
    older=next((x for x in old_evidence['edges'] if x['id']==e['id']),None)
    if older and e['meaning'].startswith('处理、'):
        e['meaning']=older['meaning']
    e['source_refs']=list(dict.fromkeys([x['path']+':'+str(x['line']) for n in evidence_nodes if n['id'] in [e['source'],e['target']] for x in n['evidence']]))
evidence=dict(captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),basis=model['basis'],repository=str(ROOT),
              commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),nodes=evidence_nodes,
              edges=[dict(id=e['id'],source=e['source'],target=e['target'],kind=e['kind'],meaning=e['meaning'],references=e['source_refs']) for e in edges],
              files=list(file_records.values()),benchmark_executed=False,source_code_modified=False)
(OUT/'semantic-model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n')
(OUT/'source-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
md=['# 五层运行框架：当前源码依据','','以当前工作区实际文件字节为依据；保留已有未提交内容。本次只生成图和查看器，未运行 Benchmark。','',
    '箭头表示处理、控制或证据依赖，不是一一对应的函数调用图。虚线表示同次观测、条件分支、证据依赖或对象内部展开。四条执行路径各有自己的 runner 和合同。','']
for n in evidence_nodes:
    md += [f"## {n['label']} · {n['id']}",'']
    md += [f"- [{r['path']}:{r['line']}]({ROOT/r['path']}:{r['line']}) · `{r['symbol']}`" for r in n['evidence']]
    md.append('')
md += ['## 关系语义','','| 有向关系 | 语义 |','| --- | --- |']
md += [f"| {e['source']} → {e['target']} | {e['meaning']} |" for e in edges]
(OUT/'source-evidence.md').write_text('\n'.join(md)+'\n')

def overlaps(a,b):
    x,y,w,h=a; X,Y,ww,hh=b
    return x<X+ww and x+w>X and y<Y+hh and y+h>Y
def seg_hits(a,b,r):
    x,y,w,h=r
    if a[0]==b[0]:return x<a[0]<x+w and max(min(a[1],b[1]),y)<min(max(a[1],b[1]),y+h)
    if a[1]==b[1]:return y<a[1]<y+h and max(min(a[0],b[0]),x)<min(max(a[0],b[0]),x+w)
    return True
def collinear_overlap(a,b,c,d):
    if a[0]==b[0]==c[0]==d[0]: k=1
    elif a[1]==b[1]==c[1]==d[1]: k=0
    else:return False
    return min(max(a[k],b[k]),max(c[k],d[k]))>max(min(a[k],b[k]),min(c[k],d[k]))
def crossing(a,b,c,d):
    if (a[0]==b[0])==(c[0]==d[0]):return None
    if a[1]==b[1]: a,b,c,d=c,d,a,b
    if min(a[1],b[1])<c[1]<max(a[1],b[1]) and min(c[0],d[0])<a[0]<max(c[0],d[0]):return [a[0],c[1]]
    return None

# Assign distinct side ports; Hanan-grid routing keeps arrows outside unrelated nodes.
port_usage={}
for e in edges:
    for id,side in zip([e['source'],e['target']],e['sides']):port_usage.setdefault((id,side),[]).append(e['id'])
ports={}
def port(id,side,edge_id):
    x,y,w,h=boxes[id];ids=port_usage[(id,side)];offset=(ids.index(edge_id)-(len(ids)-1)/2)*28
    if id=='preflight':
        return {'left':(x+abs(offset)*w/h,y+h/2+offset),'right':(x+w-abs(offset)*w/h,y+h/2+offset),
                'top':(x+w/2+offset,y+abs(offset)*h/w),'bottom':(x+w/2+offset,y+h-abs(offset)*h/w)}[side]
    return {'left':(x,y+h/2+offset),'right':(x+w,y+h/2+offset),'top':(x+w/2+offset,y),'bottom':(x+w/2+offset,y+h)}[side]
def stub(pt,side):
    x,y=pt
    return {'left':(x-22,y),'right':(x+22,y),'top':(x,y-22),'bottom':(x,y+22)}[side]
for e in edges:
    a=port(e['source'],e['sides'][0],e['id']);b=port(e['target'],e['sides'][1],e['id'])
    ports[e['id']]=(a,stub(a,e['sides'][0]),stub(b,e['sides'][1]),b)
headers=[]
for p in phases:
    for r,title in enumerate(p['rows']):
        yy=p['y']+61+r*PITCH
        headers.append([356,yy-20,width(title,18)+12,26])
obstacles=[[x-10,y-10,w+20,h+20] for x,y,w,h in boxes.values()]+headers
xs={328,340,1800,1812,1824};ys=set()
for x,y,w,h in boxes.values():
    xs.update([x-22,x+w+22,x+w/2]);ys.update([y-22,y+h+22,y+h/2])
for p in phases:
    ys.update([p['y']-12,p['y']+12,p['y']+p['h']-12,p['y']+p['h']+12])
    for r in range(len(rows[p['id']])):
        yy=p['y']+90+r*PITCH
        ys.update([yy-38,yy-30,yy+178+28,yy+178+36,yy+178+44])
for a,s,t,b in ports.values():xs.update([s[0],t[0]]);ys.update([s[1],t[1]])
xs=sorted(x for x in xs if 326<=x<=1826);ys=sorted(ys)
grid={(i,j):(x,y) for i,x in enumerate(xs) for j,y in enumerate(ys) if not any(rx<x<rx+rw and ry<y<ry+rh for rx,ry,rw,rh in obstacles)}
adj={}
for ij,point in grid.items():
    i,j=ij;neighbors=[]
    for ni,nj,direction in [(i-1,j,1),(i+1,j,1),(i,j-1,2),(i,j+1,2)]:
        q=grid.get((ni,nj))
        if q is not None and not any(seg_hits(point,q,r) for r in obstacles):
            neighbors.append(((ni,nj),direction,abs(point[0]-q[0])+abs(point[1]-q[1])))
    adj[ij]=neighbors
used=[];routes={}
def simplify(pts):
    result=[]
    for p in pts:
        if result and p==result[-1]:continue
        if len(result)>1 and ((result[-2][0]==result[-1][0]==p[0]) or (result[-2][1]==result[-1][1]==p[1])):result[-1]=p
        else:result.append(p)
    return result
def route_edge(e):
    a,s,t,b=ports[e['id']];start=(xs.index(s[0]),ys.index(s[1]));goal=(xs.index(t[0]),ys.index(t[1]))
    if start not in grid or goal not in grid:
        raise ValueError(('Blocked endpoint', e['id'], s, t, [r for r in obstacles if any(r[0]<z[0]<r[0]+r[2] and r[1]<z[1]<r[1]+r[3] for z in [s,t])]))
    # Route short dependencies first; long dependencies use available outer channels.
    costs={};queue=[];parents={};start_dir=1 if e['sides'][0] in ['left','right'] else 2
    state=(*start,start_dir);costs[state]=0;heapq.heappush(queue,(0,0,state))
    segment_cost={}
    final=None
    while queue:
        _,cost,current=heapq.heappop(queue)
        if cost!=costs.get(current):continue
        ij=current[:2];p=grid[ij]
        if ij==goal:
            final=current;break
        for nxt,dr,length in adj[ij]:
            q=grid[nxt];key=tuple(sorted([ij,nxt]))
            if key not in segment_cost:
                blocked=any(collinear_overlap(p,q,c,d) for _,c,d in used)
                cr=sum(crossing(p,q,c,d) is not None for _,c,d in used)
                segment_cost[key]=None if blocked else length+cr*22
            weight=segment_cost[key]
            if weight is None:continue
            next_state=(*nxt,dr);nc=cost+weight+(36 if dr!=current[2] else 0)
            if nc<costs.get(next_state,math.inf):
                costs[next_state]=nc;parents[next_state]=current
                h=abs(q[0]-t[0])+abs(q[1]-t[1]);heapq.heappush(queue,(nc+h,nc,next_state))
    if final is None:raise ValueError('No free route: '+e['id'])
    pts=[];current=final
    while True:
        pts.append(grid[current[:2]])
        if current==state:break
        current=parents[current]
    result=simplify([a,*reversed(pts),b]);routes[e['id']]=result
    used.extend((e['id'],c,d) for c,d in zip(result,result[1:]))
order=sorted(edges,key=lambda e:abs(boxes[e['source']][0]-boxes[e['target']][0])+abs(boxes[e['source']][1]-boxes[e['target']][1]))
for e in order:route_edge(e)

# Place edge labels in free whitespace, without hiding any arrow.
labels={};label_rects=[]
for e in edges:
    if not e['label']:continue
    tw=width(e['label'],16)+16;candidates=[]
    for a,b in sorted(zip(routes[e['id']],routes[e['id']][1:]),key=lambda q:abs(q[0][0]-q[1][0])+abs(q[0][1]-q[1][1]),reverse=True):
        mx,my=(a[0]+b[0])/2,(a[1]+b[1])/2
        for dy in [-14,20,-28,34,-42,48,-102,108,-126,132,-154,160]:
            for dx in [0,-24,24,-48,48,-84,84]:candidates.append((mx+dx,my+dy))
    for x,y in candidates:
        rect=[x-tw/2,y-18,tw,25]
        if rect[0]<344 or rect[0]+rect[2]>1790:continue
        if any(overlaps(rect,r) for r in list(boxes.values())+headers+label_rects):continue
        if any(seg_hits(a,b,rect) for _,a,b in used):continue
        labels[e['id']]=[x,y];label_rects.append(rect);break
    else:raise ValueError('No label space: '+e['id'])

issues=[]
for i,(id,box) in enumerate(boxes.items()):
    for other,r in list(boxes.items())[i+1:]:
        if overlaps(box,r):issues.append(dict(kind='node-overlap',nodes=[id,other]))
for e in edges:
    pts=routes[e['id']]
    for a,b in zip(pts,pts[1:]):
        if a[0]!=b[0] and a[1]!=b[1]:issues.append(dict(kind='diagonal',edge=e['id']))
        for id,r in boxes.items():
            if id not in [e['source'],e['target']] and seg_hits(a,b,r):issues.append(dict(kind='edge-through-node',edge=e['id'],node=id))
    a,b=pts[0],pts[1];c,d=pts[-2],pts[-1]
    ok_first={'left':b[0]<a[0] and b[1]==a[1],'right':b[0]>a[0] and b[1]==a[1],'top':b[1]<a[1] and b[0]==a[0],'bottom':b[1]>a[1] and b[0]==a[0]}[e['sides'][0]]
    ok_last={'left':d[0]>c[0] and d[1]==c[1],'right':d[0]<c[0] and d[1]==c[1],'top':d[1]>c[1] and d[0]==c[0],'bottom':d[1]<c[1] and d[0]==c[0]}[e['sides'][1]]
    if not (ok_first and ok_last):issues.append(dict(kind='endpoint-direction',edge=e['id']))
for i,(id,a,b) in enumerate(used):
    for other,c,d in used[i+1:]:
        if id!=other and collinear_overlap(a,b,c,d):issues.append(dict(kind='shared-corridor',edges=[id,other]))
bridges=[]
for i,(id,a,b) in enumerate(used):
    for other,c,d in used[i+1:]:
        cr=crossing(a,b,c,d)
        if id!=other and cr:
            horizontal=id if a[1]==b[1] else other
            if not any(x['point']==cr for x in bridges):bridges.append(dict(point=cr,horizontal=horizontal,edges=[id,other]))

LIGHT=dict(bg='#ffffff',ink='#182c42',muted='#40556a',node='#eef6ff',stroke='#458ecb',success='#e4f5e9',fail='#ffe8ed',optional='#f4efff',panel='#ffffff',line='#496176',
    phases=['#edf5ff','#eef9f0','#fff7df','#fff0f3','#f4efff'],strips=['#9fcdf6','#afe2bb','#f7d47b','#f4b9c6','#d4c0f4'],accents=['#297fc4','#39925a','#bd8b23','#c85c7a','#8c69b8'])
DARK=dict(bg='#111b25',ink='#edf4fa',muted='#c3d3e2',node='#20364b',stroke='#72b5e9',success='#224b36',fail='#542c3b',optional='#3c2d52',panel='#182632',line='#b8ccdf',
    phases=['#172c41','#193329','#37301d','#37232e','#2d2542'],strips=['#285271','#315b40','#765b27','#71364b','#523f75'],accents=['#83c5f5','#8cd49d','#efca73','#f6a8bf','#cfb3f7'])
def txt(s,x,y,size,fill,bold=False,center=False):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}"'+(' font-weight="700"' if bold else '')+(' text-anchor="middle"' if center else '')+'>'+html.escape(s)+'</text>'
def text_lines(s,x,y,size,fill,limit,bold=False,spacing=25):
    ls=wrap(s,size,limit)
    return ''.join(txt(t,x,y+i*spacing,size,fill,bold) for i,t in enumerate(ls)),len(ls)*spacing

def render(theme):
    c=LIGHT if theme=='light' else DARK
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="figure-title figure-desc"><title id="figure-title">{model["title"]}</title><desc id="figure-desc">左侧层级职责，中间当前源码模块与四条执行路径，右侧关键输出与核心约束。一张完整的五层纵向框架。</desc><style>text{{font-family:"Noto Sans CJK SC",sans-serif}}.node{{cursor:pointer;outline:none}}.node:hover .node-shape,.node:focus .node-shape{{stroke-width:3.5}}.selected .node-shape{{stroke-width:4.5;stroke:#e46835}}.edge{{fill:none}}</style><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L9 4.5L0 9Z" fill="{c["line"]}"/></marker><marker id="error-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L9 4.5L0 9Z" fill="{c["accents"][3]}"/></marker></defs><rect width="{W}" height="{H}" fill="{c["bg"]}"/>']
    out.append(txt('TSDataCompressBenchMark',28,50,34,c['ink'],True))
    out.append(txt('五层运行框架与数据流',28,87,24,c['muted']))
    out.append(txt('当前工作区源码 · 2026-10-12',1800,48,18,c['muted']))
    out.append(txt('处理 / 控制依赖',1222,85,16,c['muted']))
    out.append(f'<path d="M1160 80H1210" stroke="{c["line"]}" stroke-width="2" marker-end="url(#arrow)"/>')
    out.append(txt('证据 / 条件 / 同次观测 / 对象展开',1578,85,16,c['muted']))
    out.append(f'<path d="M1516 80H1566" stroke="{c["line"]}" stroke-width="2" stroke-dasharray="7 5" marker-end="url(#arrow)"/>')
    for i,p in enumerate(phases):
        sy,sh=p['y'],p['h'];accent=c['accents'][i]
        out.append(f'<g data-stage="{p["id"]}"><rect x="18" y="{sy}" width="2204" height="{sh}" rx="14" fill="{c["phases"][i]}" stroke="{accent}" stroke-dasharray="5 5" stroke-width="1.7"/><rect x="30" y="{sy+12}" width="276" height="{sh-24}" rx="10" fill="{c["strips"][i]}"/></g>')
        out.append(txt(f'LAYER 0{i+1}',50,sy+42,17,c['ink']))
        out.append(txt(f'0{i+1}',48,sy+122,64,accent,True))
        title=wrap(p['title'],32,235);yy=sy+180
        for t in title:out.append(txt(t,50,yy,32,c['ink'],True));yy+=43
        yy+=18
        for t in p['en']:out.append(txt(t,50,yy,23,c['ink'],True));yy+=34
        yy=sy+sh-36-31*(len(p['duties'])-1)
        for t in p['duties']:out.append(txt(t,50,yy,19,c['ink']));yy+=31
        for r,title in enumerate(p['rows']):out.append(txt(title,356,sy+61+r*PITCH,18,accent,True))
        card_h=(sh-42)/2
        for kind,title,items,cy in [('outputs','关键输出',p['outputs'],sy+14),('constraints','核心约束',p['constraints'],sy+28+card_h)]:
            out.append(f'<g data-annotation="{p["id"]}-{kind}"><rect x="1854" y="{cy}" width="350" height="{card_h}" rx="10" fill="{c["panel"]}" stroke="{accent}" stroke-width="1.8"/>')
            out.append(txt(title,1876,cy+36,23,c['ink'],True));yy=cy+74
            for item in items:
                size,spacing,gap=(17,24,8) if p['id']=='data' else (18,26,10)
                t,hh=text_lines(item,1892,yy,size,c['muted'],288,spacing=spacing)
                out.append(f'<circle cx="1880" cy="{yy-6}" r="2.5" fill="{accent}"/>');out.append(t);yy+=hh+gap
            if p['id']=='exec' and kind=='outputs':
                yy+=22
                for item in ['完整对象成本闭合','FinalBits = SerializedBits','+ ExternalSideInformationBits','容器、元数据、尾部及恢复依赖','均按所属边界计入公开成本。']:
                    t,hh=text_lines(item,1876,yy,18,c['muted'],304,bold=item=='完整对象成本闭合',spacing=26);out.append(t);yy+=hh+6
            if theme=='light' and yy>cy+card_h-12:issues.append(dict(kind='annotation-overflow',phase=p['id'],card=kind))
            out.append('</g>')
    for e in edges:
        color=c['accents'][3] if e['kind']=='error' else c['line'];marker='error-arrow' if e['kind']=='error' else 'arrow'
        dash=' stroke-dasharray="7 5"' if e['kind'] not in ['flow','error'] else ''
        pts=' '.join(f'{x},{y}' for x,y in routes[e['id']])
        out.append(f'<polyline class="edge" data-edge-id="{e["id"]}" data-from="{e["source"]}" data-to="{e["target"]}" data-kind="{e["kind"]}" points="{pts}" stroke="{color}" stroke-width="1.8" marker-end="url(#{marker})"{dash}><title>{html.escape(e["meaning"])}</title></polyline>')
    for br in bridges:
        x,y=br['point'];bg=c['bg']
        for i,p in enumerate(phases):
            if p['y']<=y<=p['y']+p['h']:bg=c['phases'][i]
        out.append(f'<g data-crossing-bridge="{br["horizontal"]}"><circle cx="{x}" cy="{y}" r="6" fill="{bg}"/><path d="M{x-6},{y}Q{x},{y-9} {x+6},{y}" stroke="{c["line"]}" stroke-width="1.8" fill="none"/></g>')
    for n in nodes:
        id=n['id'];x,y,w,h=boxes[id]
        fill=c['fail'] if id=='diagnostic' else c['success'] if id in ['formal','comparison_execute','workload_execute','p2_execute','lossless','keys','warmup'] else c['optional'] if n['role']=='validation' or id in ['object_qualification','development_pilot','lossy'] else c['node']
        accent=c['accents'][next(i for i,p in enumerate(phases) if p['id']==n['phase'])]
        out.append(f'<g class="node" id="node-{id}" data-node-id="{id}" tabindex="0" role="button" aria-label="{html.escape(n["label"])}"><title>{html.escape(n["label"])}</title>')
        if id=='preflight':
            out.append(f'<polygon class="node-shape" points="{x+w/2},{y} {x+w},{y+h/2} {x+w/2},{y+h} {x},{y+h/2}" fill="{c["optional"]}" stroke="{accent}" stroke-width="2"/>')
            out.append(txt('Preflight',x+w/2,y+84,23,c['ink'],True,True));out.append(txt('正确性与安全门控',x+w/2,y+114,17,c['muted'],center=True))
        else:
            out.append(f'<rect class="node-shape" x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{c["stroke"]}" stroke-width="1.8"/><rect x="{x+1}" y="{y+1}" width="4" height="{h-2}" rx="2" fill="{accent}"/>')
            ts=wrap(n['label'],22,w-34);yy=y+33
            for t in ts:out.append(txt(t,x+18,yy,22,c['ink'],True));yy+=28
            yy+=9
            for line in n['lines']:
                ls=wrap(line,17,w-34)
                for t in ls:
                    out.append(txt(t,x+18,yy,17,c['muted']));yy+=24
            if theme=='light' and yy-24>y+h-14:issues.append(dict(kind='node-text-overflow',node=id,baseline=yy-24,bottom=y+h-14))
        out.append('</g>')
    for e in edges:
        if e['id'] not in labels:continue
        x,y=labels[e['id']];tw=width(e['label'],16)+16;bg=c['bg']
        for i,p in enumerate(phases):
            if p['y']<=y<=p['y']+p['h']:bg=c['phases'][i]
        out.append(f'<g data-edge-label="{e["id"]}"><rect x="{x-tw/2}" y="{y-18}" width="{tw}" height="25" rx="3" fill="{bg}"/>'+txt(e['label'],x,y,16,c['muted'],center=True)+'</g>')
    out.append(txt('实线：处理与控制依赖    虚线：证据、条件、同次观测或对象展开    跨线拱桥：交叉但不连接',30,H-34,16,c['muted']))
    out.append(txt('实现结构图 · 不表示所有路径当前已通过资格 / pilot / FORMAL',1480,H-34,16,c['muted']))
    out.append('</svg>')
    return ''.join(out)

svgs={theme:render(theme) for theme in ['light','dark']}
validation=dict(status='pass' if not issues else 'fail',node_count=len(nodes),edge_count=len(edges),source_file_count=len(file_records),
                orthogonal_routes=True,bridge_count=len(bridges),issues=issues,scope='custom SVG geometry and source anchors; no Archify acceptance claim')
(OUT/'structure-check.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
if issues:
    print(json.dumps(issues,ensure_ascii=False,indent=2));raise SystemExit(1)
for theme,svg in svgs.items():
    path=OUT/f'framework.{theme}.svg';path.write_text(svg)
    subprocess.run(['rsvg-convert','--output',str(OUT/f'framework.{theme}.png'),str(path)],check=True)
    image=Image.open(OUT/f'framework.{theme}.png')
    for p in phases:
        image.crop((0,p['y']-5,W,p['y']+p['h']+5)).save(OUT/f'review.{p["id"]}.{theme}.png')
Image.open(OUT/'framework.light.png').resize((1120,2486)).save(OUT/'preview.light.png')
(OUT/'layout.json').write_text(json.dumps(dict(viewBox=[0,0,W,H],nodeBoxes=boxes,edgeRoutes=routes,edgeLabelPositions=labels,bridges=bridges),ensure_ascii=False,indent=2)+'\n')

page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSDataCompressBenchMark · 五层运行框架</title><style>
:root{color-scheme:light;--bg:#f0f4f8;--ink:#1b3045;--panel:#fff;--border:#cbd8e4;--accent:#236eac}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px "Noto Sans CJK SC",sans-serif}body.dark{color-scheme:dark;--bg:#0d1620;--ink:#eaf2fa;--panel:#182632;--border:#405568;--accent:#9dcff5}header{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:13px 24px;background:var(--panel);border-bottom:1px solid var(--border);box-shadow:0 2px 10px #0001}header strong{margin-right:auto;font-size:15px}button,input,.download{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--border);border-radius:6px;padding:7px 11px}button,.download{cursor:pointer}a{color:var(--accent);text-decoration:none}.download:hover,button:hover{border-color:var(--accent)}input{width:220px}nav{display:flex;gap:12px;align-items:center;padding:12px 24px;flex-wrap:wrap}nav a{padding:5px 11px;border-radius:20px;border:1px solid var(--border);background:var(--panel)}main{max-width:2240px;margin:0 auto;padding:0 14px 14px}main svg{display:block;width:100%;height:auto;border-radius:10px;box-shadow:0 8px 28px #0001}[hidden]{display:none!important}.svg-stage-anchor{scroll-margin-top:110px}footer{padding:16px 24px 26px;text-align:center;color:var(--ink);font-size:12px;line-height:1.8}dialog{background:var(--panel);color:var(--ink);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:min(760px,92vw);max-height:85vh;overflow:auto}dialog::backdrop{background:#09142188}dialog h2{font-size:21px;margin:0 0 12px}dialog p{line-height:1.7}dialog ul{padding-left:22px;line-height:1.9}dialog code{word-break:break-word}#source-list a{display:block;overflow-wrap:anywhere;font:13px monospace;line-height:1.9}#search-count{min-width:50px;font-size:12px;color:var(--accent)}@media(max-width:900px){header{padding:10px}header strong{width:100%}nav{padding:10px}input{width:180px}main{padding:0 4px}}@media print{header,nav,footer,dialog{display:none}main{padding:0;max-width:none}main svg{box-shadow:none}body{background:white}}
</style><header><strong>TSDataCompressBenchMark · 五层运行框架</strong><input id="search" aria-label="搜索节点" placeholder="搜索模块 / 函数 / 关键词"><span id="search-count" aria-live="polite"></span><button id="theme">切换深色</button><a class="download" id="svg-download" download href="framework.light.svg">下载 SVG</a><a class="download" id="png-download" download href="framework.light.png">下载 PNG</a></header><nav aria-label="层级跳转">'''
for i,p in enumerate(phases):page+=f'<a href="#layer-{p["id"]}" data-jump="{p["id"]}">0{i+1} {p["title"]}</a>'
page+='</nav><main><section id="light">'+svgs['light']+'</section><section id="dark" hidden>'+svgs['dark']+'</section></main>'
page+='''<footer>一张完整五层长图，支持纵向阅读。点击节点查看当前源码路径与函数依据。<br><a href="source-evidence.md">源码依据</a> · <a href="README.md">图例与说明</a></footer><dialog aria-labelledby="dialog-title"><h2 id="dialog-title"></h2><div id="dialog-content"></div><div id="source-list"></div><p><button id="close">关闭</button></p></dialog><script>'''
page+='const model='+json.dumps(model,ensure_ascii=False)+';const evidence='+json.dumps(evidence,ensure_ascii=False)+';'
page+='''let dark=false;const $=s=>document.querySelector(s);const visible=()=>document.querySelector(dark?'#dark':'#light');
function search(){const q=$('#search').value.toLowerCase().trim();let count=0;for(const n of model.nodes){const e=evidence.nodes.find(e=>e.id===n.id);const match=!!q&&JSON.stringify([n,e]).toLowerCase().includes(q);if(match)count++;document.querySelectorAll('[data-node-id="'+n.id+'"]').forEach(el=>el.classList.toggle('selected',match))}$('#search-count').textContent=q?count+' 个匹配':''}
$('#search').oninput=search;$('#search').onkeydown=e=>{if(e.key==='Enter'){const el=visible().querySelector('.selected');if(el)el.scrollIntoView({behavior:'smooth',block:'center'})}};
$('#theme').onclick=()=>{const ratio=scrollY/Math.max(1,document.documentElement.scrollHeight-innerHeight);dark=!dark;document.body.classList.toggle('dark',dark);$('#light').hidden=dark;$('#dark').hidden=!dark;$('#theme').textContent=dark?'切换浅色':'切换深色';$('#svg-download').href='framework.'+(dark?'dark':'light')+'.svg';$('#png-download').href='framework.'+(dark?'dark':'light')+'.png';window.scrollTo(0,ratio*Math.max(1,document.documentElement.scrollHeight-innerHeight));search()};
document.querySelectorAll('[data-jump]').forEach(a=>a.onclick=e=>{e.preventDefault();visible().querySelector('[data-stage="'+a.dataset.jump+'"]').scrollIntoView({behavior:'smooth',block:'start'});history.replaceState(null,'','#layer-'+a.dataset.jump)});
function showNode(id){const n=model.nodes.find(n=>n.id===id),ev=evidence.nodes.find(n=>n.id===id);$('#dialog-title').textContent=n.label;$('#dialog-content').replaceChildren();const p=document.createElement('p');p.textContent=n.lines.join(' · ');$('#dialog-content').append(p);const list=$('#source-list');list.replaceChildren();for(const ref of ev.evidence){const a=document.createElement('a');a.textContent=ref.path+':'+ref.line+' — '+ref.symbol;a.href='file://'+evidence.repository+'/'+ref.path+'#L'+ref.line;list.append(a)}const hash=document.createElement('p');hash.textContent='依据：当前工作区实际文件字节 · '+model.as_of+'；箭头表示实现依赖，不表示当前运行已通过。';$('#dialog-content').append(hash);$('dialog').showModal()}
document.querySelectorAll('[data-node-id]').forEach(el=>{el.onclick=()=>showNode(el.dataset.nodeId);el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showNode(el.dataset.nodeId)}}});$('#close').onclick=()=>$('dialog').close();$('dialog').onclick=e=>{if(e.target===$('dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()}};document.querySelectorAll('[data-stage]').forEach(el=>el.classList.add('svg-stage-anchor'));
</script></html>'''
(OUT/'framework.html').write_text(page)
print(json.dumps(validation,ensure_ascii=False))
