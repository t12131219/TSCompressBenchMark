from pathlib import Path
import json
OUT=Path(__file__).resolve().parent
nodes=[]; edges=[]; phases=[]
def node(id,phase,label,detail,lines,source,role='process'):
    nodes.append(dict(id=id,phase=phase,label=label,detail=detail,lines=lines,source=source,role=role))
def edge(a,b,label='',kind='flow'):
    edges.append(dict(id=a+'--'+b,source=a,target=b,label=label,kind=kind))
def chain(ids):
    for a,b in zip(ids,ids[1:]): edge(a,b)
def phase(id,title,en,duties,outputs,constraints):
    phases.append(dict(id=id,title=title,en=en,duties=duties,outputs=outputs,constraints=constraints))
phase('data','数据准备','Data Preparation',['统一数据输入','保留原始语义','冻结可复用数据基础'],['DatasetID / Manifest 快照','*.canonical.tscb','*.characterization.json','preparation-record.json','冻结配置 / environment.json'],['校验源文件 SHA-256','不隐式排序或重采样','保留 shape / dtype / validity','保留 timestamp 来源与 topology','复用工件须验证一致性'])
phase('plan','能力与配置','Capability & Configuration',['注册算法与来源','展开完整参数空间','生成任务与可比性键'],['AlgorithmID / SourceArtifactID','ConfigID / resolved_configs.json','显式适配与预处理计划','ExecutionPathHash / 三级键','task_plan.jsonl / 注册快照'],['按数据与参数匹配能力','此阶段制定计划，不执行适配','实际 ISA / fallback 可追溯','冻结完整任务全集','不静默丢弃不支持组合'])
phase('exec','执行验证','Execution & Validation',['Track 安全路由','预检与隔离执行','逐次验证完整编解码'],['Preflight / Warmup 记录','逐次 Correctness 与原因','FinalBits / 完整成本','bitstream / input 与输出哈希','PASS 与各类失败诊断'],['输入 / canary / 边界检查','超时与内存限制、进程隔离','Finalize 必须计入完整对象','每次正式 repetition 仍验证','不同 LossMode 按契约检查'])
phase('measure','性能测评','Performance Evaluation',['与正式实验共享执行','分口径计时与资源采集','条件查询与流式工作负载'],['Encode / Decode / E2E 计时','CORE / PIPELINE 分离','同次 CPU / Memory / I/O','条件 Query / Streaming 结果','RunID / 原始记录 / CSV 投影'],['编码、解码分别满足最短时长','E2E 模式还须 E2E 达标','Query / Streaming 请求且支持','Energy / counters 未激活时','记录 NOT_COLLECTED / UNSUPPORTED'])
phase('stats','统计分析与报告','Statistics & Reporting',['证据资格过滤','分层比较与完整覆盖率','统计、排名与最终报告'],['eligibility.csv / summary.csv','corpus_summary.csv','comparability.csv / pareto.csv','ranking.csv / coverage.csv','机器报告 / Markdown / HTML'],['只读冻结证据，不再调用 codec','资格过滤先于统计聚合','性能计划完整且至少 10 次','仅在相应可比性组内比较','Coverage 不是综合评分'])
data=[('entry','命令入口与配置','CLI / ExperimentConfig',['CLI / Benchmark Runner','加载 ExperimentConfig'],['cli.py:main','configuration.py:load_experiment_config']),('freeze','Run Set 初始化与恢复','配置 / Environment 冻结',['冻结配置与 Environment','锁、恢复与一致性校验'],['runner.py:initialize_run_set']),('dataset','数据集注册与校验','DatasetRegistry / Manifest',['DatasetRegistry / Manifest','校验源文件 SHA-256'],['datasets/registry.py:DatasetRegistry']),('loader','规范化数据加载','load_dataset / 内存表示',['load_dataset','保留 T / V / validity / shape'],['datasets/loaders.py:load_dataset']),('characterize','数据特征分析','Timestamp / Value / Topology',['characterize','Timestamp / Value / Topology'],['datasets/characterize.py:characterize']),('canonical','Canonical 工件生成','二进制 / 分析 / 准备记录',['写 Canonical Binary Data','Manifest / 特征 / 准备记录'],['datasets/prepare.py:prepare_dataset'])]
for id,l,d,ls,s in data:node(id,'data',l,d,ls,s,'artifact' if id=='canonical' else 'process')
chain([n[0] for n in data])
plans=[('registry','Codec / Source 注册','AlgorithmID / 来源与工件',['Codec / Source Registry','AlgorithmID / 工件身份'],['codecs/registry.py:CodecRegistry','adapters/factory.py:adapter_artifacts']),('sweep','参数扫描与配置生成','ConfigID / 完整参数空间',['Parameter Sweep','ConfigID / 完整参数空间'],['planning/sweep.py:expand_sweep']),('universe','展开完整候选组合','Dataset × Algorithm × Track × Config',['遍历 Dataset × Algorithm','× Track × Config / Profile'],['runner.py:plan_run_set']),('negotiate','能力协商与四态结果','直接 / 无损适配 / 有损适配 / 不支持',['DIRECT_SUPPORTED','ADAPTER_LOSSLESS','ADAPTER_LOSSY','UNSUPPORTED'],['codecs/negotiation.py:negotiate']),('plans','显式适配与预处理计划','计划制定 · 执行时验证',['Compatibility / Preprocess Plan','此处制定，Layer 3 执行验证'],['codecs/negotiation.py:negotiate','preprocess/contracts.py:build_preprocess_plan']),('resolution','执行路径解析','ISA / Device / Threads / Fallback',['Execution Resolution','ISA / Device / Threads / Fallback'],['planning/resolution.py:resolve_execution']),('keys','层级可比性键','Semantic → Execution → Resource',['ExecutionPathHash','Semantic / Execution / Resource 键'],['planning/resolution.py:build_comparability_keys']),('tasks','冻结任务与注册快照','BenchmarkTask / task_plan.jsonl',['BenchmarkTask / task_plan.jsonl','保留不支持任务与状态原因'],['planning/tasks.py:create_task','runner.py:plan_run_set'])]
for id,l,d,ls,s in plans:node(id,'plan',l,d,ls,s,'artifact' if id=='tasks' else 'process')
edge('canonical','registry');chain([n[0] for n in plans])
executions=[('track','按 Benchmark Track 路由','TIMESTAMP / VALUE / SYSTEM',['TIMESTAMP：时间戳','VALUE：值 / validity','SYSTEM：T + V / Segment Plan'],['execution/routing.py:route_canonical_artifact']),('gates','任务、源码与工件门控','Source / Build / Executor',['任务状态 / 源码 / 构建工件','已注册的预处理执行器'],['execution/preflight.py:preflight_task']),('input','输入校验','Input Validation',['Input Validation','输入描述、哈希与契约'],['validation/input.py:validate_routed_input']),('adapter','实际适配与适配后验证','Compatibility Adapter',['Compatibility Adapter','Post-Adapter Validation'],['execution/preparation.py:prepare_execution_input']),('preprocess','可选预处理阶段验证','Preprocess Stage Validation',['可选 Preprocess Stage Validation','声明、执行器与阶段证据一致'],['preprocess/runtime.py:validate_pipeline_stages']),('boundary','边界与安全 Dry-run','Boundary / Safety Suite',['Boundary / Safety Dry-run','空输入、边界、容量与内存安全'],['validation/boundary.py:run_boundary_suite']),('minimal','最小完整 Roundtrip','独立编解码 / Common Correctness',['最小完整 Roundtrip','Common Correctness'],['execution/preflight.py:preflight_task']),('preflight','Preflight 是否通过','正确性与安全门控',['Preflight','正确性 / 安全是否通过'],['execution/preflight.py:preflight_task']),('warmup','预热 Warmup','次数与预热时长门槛',['Warmup','预热次数与时长门槛'],['execution/repetition.py:perform_warmup']),('formal','正式重复实验','Formal Repetitions / 独立对象',['Formal Repetitions','独立对象 / 逐次验证 / 时长内循环'],['execution/orchestrator.py:execute_task','execution/repetition.py:perform_measured_roundtrip'])]
for id,l,d,ls,s in executions:node(id,'exec',l,d,ls,s,'decision' if id=='preflight' else 'process')
edge('tasks','track');chain([n[0] for n in executions[:8]])
edge('preflight','warmup','通过');edge('warmup','formal')
node('diagnostic','exec','失败诊断与状态证据','失败原因 / DIAGNOSTIC',['UNSUPPORTED / BUILD_UNAVAILABLE','ISA_UNSUPPORTED / CORRECTNESS_FAIL','BOUND_VIOLATION / MEMORY_SAFETY_FAIL','TIMEOUT / OOM / CRASHED'],['execution/orchestrator.py:execute_task'],'failure')
edge('preflight','diagnostic','失败留证','error')
objects=[('compress','独立 Context 与编码','Compress Update',['独立 Context','Compress Update'],['execution/repetition.py:_encode']),('finalize','强制 Finalize / Flush','结束写入 / 完整对象',['Finalize / Flush','结束写入，包含尾部字节'],['execution/repetition.py:_encode']),('accounting','完整对象成本计量','Accounting Ledger / FinalBits',['Accounting Ledger / FinalBits','metadata / index / padding / side info'],['accounting/ledger.py:AccountingLedger']),('decompress','独立 Context 解码','Decompress',['独立解码 Context','Decompress / 重建结果'],['execution/repetition.py:perform_roundtrip']),('correctness','公共正确性与 LossMode','T / V / Validity / Pairing',['Common Correctness','shape / channel / T-V pairing','输入不可变 / canary / determinism'],['validation/correctness.py:validate_common_correctness'])]
for id,l,d,ls,s in objects:node(id,'exec',l,d,ls,s)
edge('formal','compress','对象展开','expansion');chain([n[0] for n in objects])
node('lossless','exec','Lossless 按位还原','值数据 dtype / IEEE bits',['Lossless','值数据按位还原 / dtype'],['validation/correctness.py:validate_common_correctness'],'validation')
node('lossy','exec','Lossy 按模式验证','误差界或质量 · 区分模式',['Error-bounded：误差界 + 质量','Unbounded：质量，无误差保证','Rate：实际 FinalBits / 目标记录','Summary：无重建，安全检查'],['validation/correctness.py:validate_common_correctness'],'validation')
edge('correctness','lossless','无损');edge('correctness','lossy','有损或摘要')
measures=[('policy','同次正式实验测量策略','冻结 MeasurementPolicy',['冻结 MeasurementPolicy','共享 repetition，非第二轮实验'],['measurement/contracts.py:MeasurementPolicy']),('timing','分范围计时与时长控制','CORE / PIPELINE / E2E',['CORE / PIPELINE / E2E 分离','Encode、Decode 各自达标','native / stage timing 有条件补充'],['execution/repetition.py:perform_measured_roundtrip','measurement/contracts.py:MeasurementPolicy']),('resources','同步进程资源观测','CPU / Memory / I/O',['同一次 repetition 采集资源','CPU / Memory / I/O','Energy / counters：如实 availability'],['measurement/resources.py:ResourceSampler']),('workloads','条件工作负载调度','Profile 请求且 codec 支持',['Profile 请求且 codec 支持','Query / Streaming 隔离执行'],['execution/orchestrator.py:execute_task']),('raw','原始证据与可恢复投影','run_components.jsonl / runs.csv',['追加 run_components.jsonl','runs.csv：可重建扁平投影','events.jsonl：运行事件'],['storage/runs.py:append_run_record','storage/events.py:append_event'])]
for id,l,d,ls,s in measures:node(id,'measure',l,d,ls,s,'artifact' if id=='raw' else 'process')
edge('formal','policy','同次采集','scope');edge('policy','timing');edge('policy','resources','同步资源','scope');edge('timing','workloads')
node('query','measure','Query / Random Access','请求且支持时执行',['Query / Random Access','请求且支持：延迟 / 放大 / 正确性'],['measurement/workloads.py:execute_query_workload'],'optional')
node('streaming','measure','Streaming Benchmark','请求且支持时执行',['Streaming Benchmark','请求且支持：块延迟 / 状态 / checkpoint'],['measurement/workloads.py:execute_streaming_workload'],'optional')
edge('workloads','query','请求且支持','conditional');edge('workloads','streaming','请求且支持','conditional');edge('workloads','raw','同次运行记录');edge('diagnostic','raw','诊断记录','evidence')
stats=[('evidence','读取冻结任务与原始证据','只读 task / raw / provenance',['冻结任务 / raw / provenance','只读，校验完整证据链'],['statistics/engine.py:analyze_run_set']),('eligibility','资格过滤与排除原因','Eligibility Filtering',['正式模式 / 来源 / 正确性 / 计量','完整重复与路径 / 排除原因'],['statistics/engine.py:_eligibility']),('summary','合格重复的逐数据集统计','median / quantiles / bootstrap CI',['Dataset + Algorithm + Config','ExecutionPath + Profile + schema','median / 分位数 / bootstrap CI'],['statistics/engine.py:_summaries']),('corpus','Corpus 汇总与分层比较','Semantic → Execution → Resource',['先逐数据集，后 corpus 汇总','Semantic：空间 / 质量','Execution：性能 → Resource：资源'],['statistics/engine.py:_corpus_summaries','statistics/engine.py:_comparability_groups']),('pareto','Pareto 与单指标排名','同数据集 / 同键 / 同 Profile',['Pareto / 单指标排名','只在相应可比性组内比较'],['statistics/engine.py:_pareto_rows','statistics/engine.py:_ranking_rows']),('report','最终结果与报告生成','CSV / 机器报告 / Markdown / HTML',['Result / Report Generator','CSV / 机器报告 / Markdown / HTML'],['reporting/generator.py:generate_report'])]
for id,l,d,ls,s in stats:node(id,'stats',l,d,ls,s,'artifact' if id=='report' else 'process')
edge('raw','evidence');chain([n[0] for n in stats])
node('coverage','stats','冻结任务全集 Coverage','保留无 PASS 的任务',['Coverage：冻结任务全集','包括无 PASS / 不支持 / 失败','不把覆盖率换算成评分'],['statistics/engine.py:_coverage'])
edge('evidence','coverage','任务全集','evidence');edge('coverage','report','覆盖率')
# Native: readable vertical spine, nearby local branches. Reference layout is separate.
main=[n[0] for n in data]+[n[0] for n in plans]+[n[0] for n in executions]+[n[0] for n in measures]+[n[0] for n in stats]
byid={n['id']:n for n in nodes}; positions={}; y=90; phasebounds=[]
for p in phases:
    start=y
    ids=[i for i in main if byid[i]['phase']==p['id']]
    for id in ids:positions[id]=[60,y];y+=140
    if p['id']=='exec':
        fy=positions['formal'][1]
        positions['diagnostic']=[460,positions['preflight'][1]]
        for k,id in enumerate([n[0] for n in objects]):positions[id]=[460,fy+k*140]
        positions['lossless']=[860,fy+3*140];positions['lossy']=[860,fy+5*140]
        y=max(y,fy+6*140+60)
    if p['id']=='measure':
        positions['resources']=[460,positions['timing'][1]]
        positions['query']=[460,positions['workloads'][1]]
        positions['streaming']=[860,positions['workloads'][1]]
    if p['id']=='stats':positions['coverage']=[460,positions['evidence'][1]+140]
    phasebounds.append(dict(kind='region',label=p['title']+' / '+p['en'],wraps=[n['id'] for n in nodes if n['phase']==p['id']],pad=24))
    y+=130
components=[]
for n in nodes:
    components.append(dict(id=n['id'],type='database' if n['role']=='artifact' else ('security' if n['id'] in ['preflight','boundary','input','correctness','eligibility'] else 'backend'),label=n['label'],sublabel=n['detail'],pos=positions[n['id']],size=[300,80]))
connections=[]
for e in edges:
    c=dict(id=e['id'],**{'from':e['source'],'to':e['target']})
    if e['label']:c['label']=e['label']
    if e['kind'] in ['scope','expansion','evidence','conditional']:c['variant']='dashed'
    if e['kind']=='error':c['variant']='security'
    connections.append(c)
spec=dict(schema_version=1,diagram_type='architecture',meta=dict(title='TSDataCompressBenchMark · 五层运行框架',locale='zh-CN',quality_profile='showcase',viewBox=[1240,y]),components=components,boundaries=phasebounds,connections=connections)
model=dict(title=spec['meta']['title'],phases=phases,nodes=nodes,edges=edges,expansion=dict(parent='formal',nodes=[n[0] for n in objects]+['lossless','lossy']))
(OUT/'semantic-model.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n')
(OUT/'framework.archify.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
print('Authored',len(nodes),'nodes and',len(edges),'edges.')
