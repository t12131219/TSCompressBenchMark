from pathlib import Path
import json,re,hashlib,subprocess,datetime
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
MODEL=json.loads((OUT/'semantic-model.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
files={}
def file_record(rel):
 p=ROOT/rel
 if rel not in files:
  state=subprocess.run(['git','status','--porcelain','--',rel],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
  files[rel]={'path':rel,'sha256':sha(p),'bytes':p.stat().st_size,'working_tree_status':state or 'clean'}
 return files[rel]
def symbol(ref):
 f,s=ref.rsplit(':',1);rel='src/tscompbench/'+f;p=ROOT/rel;ls=p.read_text().splitlines()
 hits=[i for i,l in enumerate(ls) if re.match(r'\s*(?:async )?(?:def|class)\s+'+re.escape(s)+r'\b',l)]
 assert len(hits)==1,(ref,hits)
 start=hits[0];indent=len(ls[start])-len(ls[start].lstrip());end=len(ls)
 for j in range(start+1,len(ls)):
  if re.match(r'\s*(?:async )?(?:def |class |@)',ls[j]) and len(ls[j])-len(ls[j].lstrip())<=indent:
   end=j;break
 f=file_record(rel)
 return {'path':rel,'symbol':s,'line':start+1,'end_line':end,'sha256':f['sha256']}
def anchor(ref,token):
 s=symbol(ref);ls=(ROOT/s['path']).read_text().splitlines()
 hits=[i+1 for i,l in enumerate(ls) if s['line']<=i+1<=s['end_line'] and token in l]
 assert hits,(ref,token)
 return {'path':s['path'],'symbol':s['symbol'],'line':hits[0],'snippet':ls[hits[0]-1].strip(),'sha256':s['sha256']}
extra={
 'freeze':['environment.py:capture_environment','runner.py:prepare_run_set'],
 'canonical':['datasets/canonical.py:write_canonical'],
 'registry':['codecs/registry.py:SourceRegistry','codecs/models.py:CodecManifest'],
 'keys':['planning/models.py:ComparabilityKeys'],
 'tasks':['planning/models.py:BenchmarkTask'],
 'adapter':['adapters/compatibility.py:apply_compatibility_plan','adapters/compatibility.py:validate_prepared_input'],
 'preprocess':['preprocess/runtime.py:reviewed_pipeline_executor'],
 'formal':['execution/isolation.py:run_isolated'],
 'lossy':['validation/lossy.py:validate_error_bound','validation/lossy.py:profile_unbounded_loss'],
 'summary':['statistics/core.py:descriptive_statistics'],
 'pareto':['statistics/core.py:pareto_front','statistics/core.py:rank_values'],
}
nodes=[{'id':n['id'],'phase':n['phase'],'label':n['label'],'evidence':[symbol(r) for r in n['source']+extra.get(n['id'],[])]} for n in MODEL['nodes']]
# Directed edges are logical dependencies, not an invented one-to-one call graph.
edge_details={
 'entry--freeze':('CLI run 子命令初始化/恢复 Run Set。',[('cli.py:main','run_set = initialize_run_set(')]),
 'freeze--dataset':('冻结环境之后准备数据；先校验可复用记录，否则调用 prepare_dataset。',[('runner.py:prepare_run_set','prepare_dataset(')]),
 'dataset--loader':('prepare_dataset 先 registry.load(verify_source=True)，随后加载规范化内存。',[('datasets/prepare.py:prepare_dataset','manifest = registry.load'),('datasets/prepare.py:prepare_dataset','dataset = load_dataset')]),
 'loader--characterize':('特征分析读取加载完成的内存数据，不依赖新写出的二进制。',[('datasets/prepare.py:prepare_dataset','characterization = characterize')]),
 'characterize--canonical':('分析后才 write_canonical；相关记录来自同一份已加载数据。',[('datasets/prepare.py:prepare_dataset','canonical = write_canonical')]),
 'canonical--registry':('数据准备结果是 Layer 2 规划前提；不是 Canonical 文件调用 CodecRegistry。',[('runner.py:plan_run_set','preparations = prepare_run_set'),('runner.py:plan_run_set','manifest = codec_registry.get')]),
 'registry--sweep':('按注册 manifest 扫描完整配置空间。',[('runner.py:plan_run_set','configs = expand_sweep')]),
 'sweep--universe':('配置与 dataset/track 逐一组合；Profile 已冻结。',[('runner.py:plan_run_set','for dataset_key'),('runner.py:plan_run_set','for track_name'),('runner.py:plan_run_set','for config in configs:')]),
 'universe--negotiate':('从 Layer 1 工件生成 track 数据描述，再按配置协商。',[('runner.py:plan_run_set','descriptor = descriptor_from_layer1_artifacts'),('runner.py:plan_run_set','compatibility = negotiate')]),
 'negotiate--plans':('四态是替代结果，CompatibilityPlan 含显式适配；PreprocessPlan 独立制定。图中逻辑计划整理不宣称严格函数先后。',[('runner.py:plan_run_set','preprocess = build_preprocess_plan(manifest.document, config.parameters)'),('runner.py:plan_run_set','compatibility = negotiate')]),
 'plans--resolution':('执行解析接收 CompatibilityPlan，并纳入 preprocess/工件/冻结资源口径。',[('runner.py:plan_run_set','execution = resolve_execution')]),
 'resolution--keys':('解析路径是层级可比性键的输入。',[('runner.py:plan_run_set','comparability = build_comparability_keys')]),
 'keys--tasks':('create_task 冻结 compatibility、preprocess、execution、comparability；不支持组合保留。',[('runner.py:plan_run_set','create_task('),('runner.py:plan_run_set','write_task_plan(')]),
 'tasks--gates':('execute_task 首先执行 preflight；不合格组合返回 DIAGNOSTIC 而非正式 repetition。',[('execution/orchestrator.py:execute_task','preflight, prepared = preflight_task'),('execution/orchestrator.py:execute_task','record_kind="DIAGNOSTIC"')]),
 'gates--track':('任务状态、来源、工件与注册执行器门控后，才路由 Canonical。',[('execution/preflight.py:preflight_task','reviewed_pipeline_executor'),('execution/preflight.py:preflight_task','routed = route_canonical_artifact')]),
 'track--input':('TIMESTAMP / VALUE / SYSTEM 为当前任务所选 Track；路由后输入验证。',[('execution/preflight.py:preflight_task','input_validation = validate_routed_input')]),
 'input--adapter':('输入验证后实际 apply CompatibilityPlan，并调用 post-adapter validator。',[('execution/preflight.py:preflight_task','prepared = prepare_execution_input'),('execution/preparation.py:prepare_execution_input','validate_prepared_input(')]),
 'adapter--preprocess':('有声明 stages 时运行已注册的阶段验证，非所有任务必经额外处理。',[('execution/preflight.py:preflight_task','if task.preprocess.stages:'),('execution/preflight.py:preflight_task','validate_pipeline_stages,')]),
 'preprocess--boundary':('可选 stage validation 成功后，隔离 Boundary/Safety suite。',[('execution/preflight.py:preflight_task','boundary_call = run_isolated(')]),
 'boundary--minimal':('Boundary 成功后执行最小完整 roundtrip。',[('execution/preflight.py:preflight_task','perform_roundtrip,')]),
 'minimal--preflight':('最小 roundtrip 与 Common Correctness 共同产生 PreflightResult。',[('execution/preflight.py:preflight_task','validate_common_correctness(')]),
 'preflight--warmup':('仅 eligible_for_formal_repetitions 通过才能进入预热。',[('execution/orchestrator.py:execute_task','if not preflight.eligible_for_formal_repetitions'),('execution/orchestrator.py:execute_task','perform_warmup,')]),
 'preflight--diagnostic':('失败原因写结构化 DIAGNOSTIC，通过 callback 保留，不静默删除。',[('execution/orchestrator.py:execute_task','record_kind="DIAGNOSTIC"'),('execution/orchestrator.py:execute_task','record_callback(record, None)')]),
 'warmup--formal':('Warmup 是独立预热门槛，后续正式 repetition 含自身最短时长内循环。',[('execution/orchestrator.py:execute_task','perform_measured_roundtrip,')]),
 'formal--compress':('局部展开父节点 formal：每个内循环迭代是独立完整对象，不代表再执行一次 benchmark。',[('execution/repetition.py:perform_measured_roundtrip','while True:'),('execution/repetition.py:perform_measured_roundtrip','artifact, enc_wall')]),
 'compress--finalize':('独立 session.compress_update 后强制 finalize。',[('execution/repetition.py:_encode','updated = session.compress_update'),('execution/repetition.py:_encode','finalized = session.finalize')]),
 'finalize--accounting':('完整 stream 包括 update+finalize 字节，session.accounting 计算完整解码所需成本。',[('execution/repetition.py:_encode','stream = bytes(storage[: updated + finalized])'),('execution/repetition.py:_encode','ledger = session.accounting')]),
 'accounting--decompress':('完成编码 ledger 后，独立解码 Context 重建完整 stream。',[('execution/repetition.py:perform_measured_roundtrip','session = adapter.create_session'),('execution/repetition.py:perform_measured_roundtrip','decoded = session.decompress')]),
 'decompress--correctness':('每次正式 repetition 的结果由 orchestrator 进行 Common Correctness。最终内循环对象提供结果证据；输入/canary/确定性跨内循环累计。',[('execution/orchestrator.py:execute_task','validate_common_correctness(')]),
 'correctness--lossless':('LOSSLESS 值数据 dtype 一致并按 C-order 字节还原。',[('validation/correctness.py:validate_common_correctness','if loss_mode is LossMode.LOSSLESS:')]),
 'correctness--lossy':('Error-bounded 检查界与质量；Unbounded 只有质量；Rate 记录目标，actual FinalBits 的 rate gate 留待 rate profile；Summary 无重建但仍安全校验。',[('validation/correctness.py:validate_common_correctness','if loss_mode is LossMode.ERROR_BOUNDED_LOSSY:'),('validation/correctness.py:validate_common_correctness','DEFERRED_TO_RATE_PROFILE_WITH_ACTUAL_FINAL_BITS')]),
 'formal--policy':('同一次执行的职责投影：runner 将冻结 policy 传给执行器，非验证后重新运行 benchmark。',[('runner.py:execute_run_set','measurement_policy = MeasurementPolicy.from_profile'),('execution/orchestrator.py:execute_task','perform_measured_roundtrip,')]),
 'policy--timing':('正式 repetition 使用冻结 policy 控制范围与最短时长。',[('execution/repetition.py:perform_measured_roundtrip','if policy.duration_satisfied(')]),
 'policy--resources':('ResourceSampler 与正式 repetition 共用起止边界。',[('execution/repetition.py:perform_measured_roundtrip','sampler = ResourceSampler'),('execution/repetition.py:perform_measured_roundtrip','sampler.start(start_wall)')]),
 'timing--workloads':('正式编解码结果之后，条件工作负载分别在隔离 worker 执行；连线不是并发声明。',[('execution/orchestrator.py:execute_task','workloads = unavailable_workloads')]),
 'workloads--query':('Profile 请求且 manifest.query 或 random_access 才执行；否则记录明确不可用状态。',[('execution/orchestrator.py:execute_task','measurement_policy.query_workload'),('execution/orchestrator.py:execute_task','execute_query_workload,')]),
 'workloads--streaming':('Profile 请求且 manifest.streaming 才执行；与 Query 按代码顺序分别隔离。',[('execution/orchestrator.py:execute_task','if measurement_policy.streaming_workload and bool('),('execution/orchestrator.py:execute_task','execute_streaming_workload,')]),
 'workloads--raw':('workload 结果与正式运行记录汇合，通过 record_callback 追加原始记录。',[('execution/orchestrator.py:execute_task','record_callback(record, observation.encoded.stream)')]),
 'diagnostic--raw':('不支持、预检、warmup 失败等诊断也进入权威证据。正式失败保留原 FORMAL_REPETITION 状态，不统改为 DIAGNOSTIC。',[('execution/orchestrator.py:execute_task','record_callback(record, None)'),('storage/runs.py:append_run_record','run_components.jsonl')]),
 'resources--raw':('同次 resource observation 写入结构化 record，不是第二次资源压测。',[('execution/orchestrator.py:execute_task','observation.resources')]),
 'query--raw':('隔离 Query 的 status/原因/latency 等进入本次 workload 字段。',[('execution/orchestrator.py:execute_task','query=query_document')]),
 'streaming--raw':('隔离 Streaming 的 status/原因/块状态等进入本次 workload 字段。',[('execution/orchestrator.py:execute_task','streaming=streaming_document')]),
 'raw--evidence':('统计读取 run_components.jsonl 与冻结 task/provenance，runs.csv 不是权威统计输入。',[('statistics/engine.py:analyze_run_set','records = _read_jsonl(raw_path)')]),
 'evidence--eligibility':('完整冻结证据核对后先做资格过滤。',[('statistics/engine.py:analyze_run_set','eligibility, _ = _eligibility')]),
 'eligibility--summary':('仅合格 repetition 进入逐数据集统计，PASS 本身不足。',[('statistics/engine.py:analyze_run_set','summaries = _summaries'),('statistics/engine.py:_summaries','if record.get("run_id") not in performance_ids:')]),
 'summary--corpus':('先逐数据集统计，再基于 summaries 作 corpus 汇总；图中同框呈现分层比较职责，其 group universe 同时来自 tasks。',[('statistics/engine.py:analyze_run_set','corpus_summaries=tuple(_corpus_summaries(summaries))'),('statistics/engine.py:analyze_run_set','comparability_groups=tuple(_comparability_groups(tasks))')]),
 'summary--pareto':('Pareto 与单指标排名从合格 summaries 生成，组内比较。',[('statistics/engine.py:analyze_run_set','pareto=tuple(_pareto_rows(summaries))'),('statistics/engine.py:analyze_run_set','rankings=tuple(_ranking_rows(summaries))')]),
 'evidence--coverage':('读取节点包含冻结 task 全集，Coverage 使用 tasks+records；包括无 PASS 任务，不从合格 summary 推算。',[('statistics/engine.py:analyze_run_set','coverage = _coverage(tasks, records)')]),
}
for eid in ['pareto--report','corpus--report','coverage--report']:
 edge_details[eid]=('AnalysisBundle 的对应输出交给报告生成器，只读分析，不重新调用 codec。',[('reporting/generator.py:generate_report','analyze_run_set(')])
edges=[]
for e in MODEL['edges']:
 note,anchors=edge_details[e['id']]
 edges.append({**e,'meaning':note,'evidence':[anchor(ref,t) for ref,t in anchors]})
# Required supplementary modules, actual contracts and focused tests.
supplement=[
 ('environment.py:capture_environment','冻结 Environment 指纹与能力/工具信息'),
 ('datasets/registry.py:DatasetRegistry','Manifest 与源 SHA-256 入口'),
 ('datasets/canonical.py:write_canonical','Canonical raw bits、数据描述与二进制工件'),
 ('datasets/characterize.py:characterize','只读数据特征'),
 ('codecs/models.py:DataDescriptor','冻结输入描述'),('codecs/models.py:CompatibilityPlan','协商与显式适配契约'),
 ('planning/models.py:ExecutionResolution','ISA/device/线程进程/affinity/fallback/工件身份'),
 ('planning/models.py:ComparabilityKeys','嵌套 Semantic/Execution/Resource 文档'),
 ('adapters/factory.py:create_adapter','实际已注册 codec adapter 分派'),
 ('preprocess/contracts.py:build_preprocess_plan','声明的预处理计划'),
 ('preprocess/runtime.py:reviewed_pipeline_executor','已注册执行器门控'),
 ('execution/isolation.py:run_isolated','独立 worker、超时、内存与 affinity'),
 ('validation/lossy.py:validate_error_bound','Error-bounded 边界与质量'),
 ('validation/lossy.py:profile_unbounded_loss','Unbounded 质量，无误差保证'),
 ('measurement/resources.py:ResourceSampler','process CPU/memory/I/O；Energy/counters 未采集 availability'),
 ('measurement/contracts.py:duration_satisfied','encode 和 decode 各自达标；E2E 时还要 E2E 达标'),
 ('measurement/workloads.py:unavailable_workloads','未请求/不支持工作负载状态'),
 ('storage/runs.py:append_run_record','追加 JSONL、按 RunID 结构化证据及 CSV 投影'),
 ('statistics/core.py:descriptive_statistics','确定性 bootstrap 与分位数/离散度'),
 ('statistics/engine.py:_analysis_reasons','按分析类型审查性能/资源资格'),
]
supplement_records=[{'purpose':purpose,**symbol(ref)} for ref,purpose in supplement]
contract_paths=[
 'configs/experiments/data-preparation-smoke.toml','configs/experiments/capability-configuration-smoke.toml','configs/experiments/performance-evaluation-smoke.toml',
 'registry/datasets/national_illness.json','registry/codecs/lz4-frame.json','registry/codecs/delta-maskedvbyte-u32.json','registry/sources/lz4-frame-lzbench.artifact.json',
 *['schemas/v2/'+n+'.schema.json' for n in ['experiment-config','dataset-manifest','canonical-artifact-metadata','dataset-characterization','codec-manifest','compatibility-plan','preprocess-plan','execution-resolution','comparability-keys','benchmark-task','measurement-policy','run-record','eligibility-record','summary-record','corpus-summary-record','report']],
 *['tests/'+n for n in ['unit/test_canonical.py','unit/test_negotiation.py','unit/test_preprocess.py','unit/test_execution_validation.py','unit/test_measurement.py','unit/test_statistics.py','integration/test_layer2_plan.py','integration/test_layer3_execution.py','integration/test_layer5_reporting.py','unit/test_formal_direction_duration_audit.py']],
]
contracts=[]
for rel in contract_paths:
 rec=file_record(rel);ls=(ROOT/rel).read_text().splitlines()
 defs=[{'symbol':q[1],'line':i+1} for i,l in enumerate(ls) if (q:=re.match(r'\s*(?:def|class)\s+(\w+)',l))]
 contracts.append({**rec,'inspection':'契约参照；未在本图任务中执行 benchmark/test','symbols':defs,'line':1})
receipt={'basis':'current-working-tree-file-bytes','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repository':str(ROOT),'pinned_commit_validation':False,'source_edits_by_this_task':False,'nodes':nodes,'edges':edges,'supplementary_modules':supplement_records,'contracts':contracts,'files':list(files.values()),'counts':{'nodes':len(nodes),'edges':len(edges),'files':len(files)}}
(OUT/'source-evidence.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
def link(e):return f"[{e['path']}:{e['line']}]({ROOT/e['path']}:{e['line']}) — `{e['symbol']}`"
md=['# 五层框架源码证据','',f"核对基准：当前工作区（含未提交内容），采集时间 `{receipt['captured_at']}`。图由 46 个语义节点、51 条有向关系组成。所有 SHA-256 对应实际文件字节，不使用 HEAD blob 冒充当前实现；未使用 Archify `--repo-root` 提交校验。",'',
'图的实线表达处理/数据依赖；并非每条箭头都表示直接函数调用。scope 为同次测量职责投影，expansion 为 formal 的局部对象生命周期，conditional 为条件调度，evidence 为证据依赖。未标注的顺序边两端已说明依赖，标签省略不改变方向。右侧说明框与左侧标题栏仅为展示注释，不进入运行拓扑。','',
'准确键名为 `ExecutionPathHash`、`SemanticComparabilityKey`、`ExecutionComparabilityKey`、`ResourceProfileKey`；图内 Semantic / Execution / Resource 为这三个可比性键的缩写。执行路径并非第四种独立比较世界；Execution 文档包含 Semantic key，Resource 文档包含 Execution key。','',
'重要细节：正式 repetition 的每个内循环对象独立 Finalize；最后一个对象提供正确性/计量结果，输入不可变、canary、确定性证据跨内循环累计。正式 repetition 仍逐次验证。Rate-controlled 当前记录目标，actual FinalBits 的 rate gate 延后至相应 profile；不是误差界验证。','',
'## 阶段与节点','']
for phase in MODEL['phases']:
 md += [f"### {phase['title']} / {phase['en']}",'','| 稳定 ID / 节点 | 实查路径、函数与行号 |','| --- | --- |']
 for n in nodes:
  if n['phase']==phase['id']:md.append(f"| `{n['id']}` · {n['label']} | "+'<br>'.join(link(e) for e in n['evidence'])+' |')
 md.append('')
md += ['## 有向关系与实查语义','','| 稳定边 ID | 关系解释 | 实查调用 / 分支 / 数据依赖 |','| --- | --- | --- |']
for e in edges:md.append(f"| `{e['id']}` ({e['kind']}) | {e['meaning']} | "+'<br>'.join(link(a)+f"：`{a['snippet'].replace('|','&#124;')}`" for a in e['evidence'])+' |')
md += ['','## 补充实现与契约','','| 实现职责 | 路径 / 函数 / 行号 |','| --- | --- |']
for s in supplement_records:md.append(f"| {s['purpose']} | {link(s)} |")
md += ['','测试仅用于源码契约核对；本次只新增图及文档，未执行 benchmark 或声称相关测试通过。配置与 manifest 是例证，不表示所有 codec 都支持其能力。','']
for c in contracts:md.append(f"- [{c['path']}]({ROOT/c['path']}:1)"+('：'+', '.join(f"`{s['symbol']}` L{s['line']}" for s in c['symbols']) if c['symbols'] else '：已核对冻结字段/声明结构。'))
md += ['','## 当前工作区文件指纹','','| 相对路径 | SHA-256（当前文件） | 字节 | Git 状态 |','| --- | --- | ---: | --- |']
for f in files.values():md.append(f"| `{f['path']}` | `{f['sha256']}` | {f['bytes']} | `{f['working_tree_status']}` |")
(OUT/'source-evidence.md').write_text('\n'.join(md)+'\n')
print(json.dumps(receipt['counts']))
