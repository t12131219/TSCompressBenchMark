"""Author the detailed Archify specification from inspected working-tree code."""
from pathlib import Path
import json
root=Path(__file__).resolve().parent
# Each tuple: stable ID, semantic role, label, readable detail, implementation anchor.
stages=[
('01 数据准备 / Data Preparation',[
('cli','frontend','命令入口与配置解析','run 子命令 · 配置 / 测量 / 报告','cli.main · load_experiment_config'),
('runset','backend','Run Set 初始化与恢复','冻结 TOML / Environment · 锁与一致性检查','runner.initialize_run_set'),
('dataset','database','数据集注册与源文件校验','Manifest / DatasetID / source SHA-256','datasets.registry.DatasetRegistry'),
('load','backend','加载数据与特征分析','CanonicalDataset · T / V / Topology','load_dataset · characterize'),
('canonical','database','写入并复用 Canonical 工件','二进制 + Manifest + characterization','prepare_dataset · load_preparation_result')]),
('02 能力与配置 / Capability & Configuration',[
('registry','database','Codec / Source / Alias 注册','AlgorithmID · 源码身份 · 工件定位','CodecRegistry · adapter_artifacts'),
('sweep','backend','参数扫描与 ConfigID 生成','算法参数 × 框架参数 · 配置状态','planning.sweep.expand_sweep'),
('descriptor','backend','展开数据集与 Benchmark Track','Dataset × Algorithm × Track × Config','descriptor_from_layer1_artifacts'),
('preprocess-plan','backend','声明算法预处理计划','参数决定 stages / semantic_class','preprocess.contracts.build_preprocess_plan'),
('negotiate','security','四态能力协商与兼容计划','DIRECT_SUPPORTED / UNSUPPORTED','negotiate · ADAPTER_LOSSLESS / ADAPTER_LOSSY'),
('resolve','backend','解析真实执行路径','ISA / 回退 / 亲和性 / 工件哈希','planning.resolution.resolve_execution'),
('semantic-key','backend','构造语义可比性键','Track / LossMode / dtype / 拓扑 / 误差界','SemanticComparabilityKey'),
('execution-key','backend','构造执行与资源比较键','语义键 → 执行策略 → 资源采集策略','ExecutionComparabilityKey / ResourceProfileKey'),
('task','backend','创建确定性 BenchmarkTask','携带兼容 / 预处理 / 执行 / 资源限制','create_task · TaskID / ExecutionPathHash'),
('freeze','database','冻结任务宇宙与注册快照','TaskID 排序 · 完整记录不可执行配置','task_plan.jsonl / resolved_configs.json')]),
('03 执行验证 / Execution & Validation',[
('factory','backend','适配器创建与源工件门控','源身份 / License / Build / AdapterID','create_adapter · preflight_task'),
('route','backend','按 Track 路由 Canonical','TIMESTAMP: T · VALUE: V + Validity','SYSTEM: T + V + Validity / SegmentPlan'),
('input','security','输入契约校验','shape / dtype / 拓扑 / hash / 配对','validation.input.validate_routed_input'),
('compat','backend','应用兼容适配并校验','逐缓冲转换 · 原始引用与输入哈希保留','prepare_execution_input / validate_prepared_input'),
('preprocess-test','security','验证注册预处理执行器','声明与实际 stages 一致 · 阶段证据','reviewed_pipeline_executor / validate_pipeline_stages'),
('boundary','security','边界与内存安全测试','极短输入 / 容量边界 / canary / 确定性','validation.boundary.run_boundary_suite'),
('isolation','security','隔离执行最小 Round-trip','超时 / 内存限制 / CPU affinity','run_isolated · perform_roundtrip'),
('session','backend','创建编码 Session 与输出区','output_bound · 缓冲分配 · 输入快照','adapter.create_session · _encode'),
('compress','backend','增量编码','compress_update → 已用长度校验','编码过程中检查输入及配对引用'),
('finalize','backend','强制 Finalize 与释放 Session','写入尾部 / flush · 输出长度 / canary','session.finalize · session.close'),
('account','backend','完整比特成本记账','payload / header / index / metadata 等','session.accounting · FinalBits'),
('decode','backend','独立解码与适配视图恢复','新 Session → decompress → close','解码后恢复原始 dtype / 形状视图'),
('common','security','公共正确性检查','通道顺序 / T / Validity / T-V 配对','输入不变性 · canary · 确定性'),
('loss','security','按 LossMode 验证重建','无损位精确 · 有界误差 / 质量评估','SUMMARY / UNBOUNDED / RATE 按各自契约'),
('preflight','security','形成 Preflight 资格结论','PASS 才进入预热与正式重复','失败携带阶段 / 原因 / accounting 证据')]),
('04 性能测评 / Performance Evaluation',[
('policy','backend','冻结测量策略并执行预热','warmup 次数 + 时长 · 测量模式','MeasurementPolicy · perform_warmup'),
('repetitions','backend','隔离执行正式重复实验','每轮独立对象 · 复用完整编解码内核','execute_task · perform_measured_roundtrip'),
('duration','backend','最短时长与内循环控制','所选范围的编码 / 解码时长门控','inner_iterations · max_inner_iterations'),
('timing','backend','分范围累计计时与吞吐','CORE / PIPELINE / E2E · wall / CPU','可选 NATIVE / pipeline stage telemetry'),
('resource','backend','同步采集进程资源','CPU · RSS / PSS / USS · I/O / faults','ResourceSampler.start / stop'),
('formal-check','security','逐次正确性与资源资格校验','正式重复仍检查重建 / 安全 / 资源预算','validate_common_correctness · resource eligibility'),
('query','backend','查询 / 随机访问工作负载','配置请求 + query / random_access 能力','固定 seed · WorkloadID · 延迟 / 放大率'),
('stream','backend','流式工作负载与状态测量','配置请求 + streaming 能力','首输出 / 分块延迟 · 状态 / 缓冲 / reset'),
('record','database','创建原始 RunRecord','同一 RunID 关联正确性 / 计时 / 资源','PASS 或诊断状态 · query / streaming 结果'),
('append','database','追加证据与恢复进度','run_components.jsonl → runs.csv 投影','events.jsonl · bitstreams · 未完成重复恢复')]),
('05 统计分析与报告 / Statistics & Reporting',[
('read','database','读取冻结任务和原始证据','TaskID / RunID 唯一性 · provenance','analyze_run_set · source hashes'),
('eligibility','security','按分析维度筛选资格','PASS / 正确性 / accounting / 测量契约','_eligibility · 排除原因全部保留'),
('aggregate','backend','按配置与实际执行路径聚合','Dataset + ConfigID + ExecutionPathHash 等','_summaries · 合格正式 repetitions'),
('robust','backend','稳健统计与 Bootstrap 区间','median / 分位数 / 离散度 / 置信区间','descriptive_statistics · deterministic bootstrap'),
('corpus','backend','生成分数据集与 Corpus 指标','先 per-dataset · 再 micro / GeoMean','_corpus_summaries · 不合并为综合总分'),
('groups','backend','按层级比较键建立分析视图','空间质量: Semantic · 速度: Execution','资源: ResourceProfileKey · _comparability_groups'),
('pareto','backend','计算 Pareto 与逐指标排名','同数据集 / profile / 比较键内计算','_pareto_rows · _ranking_rows · DENSE_EXACT'),
('coverage','backend','按冻结任务全集统计覆盖率','PASS / UNSUPPORTED / FAIL / OOM / TIMEOUT','_coverage · 包含未产生 PASS 的任务'),
('tables','database','写入统计与分析表','summary / eligibility / corpus 等表','rankings.csv / pareto.csv / coverage.csv'),
('report','frontend','生成可追溯实验报告','report.json / report.md / report.html','generate_report · coverage / Pareto SVG')])]
components=[];boundaries=[];edges=[];evidence=[]
y=100
for stage_index,(label,rows) in enumerate(stages):
    ids=[]
    for i,(id,kind,title,detail,anchor) in enumerate(rows):
        r,c=divmod(i,5)
        # Reading direction alternates per row, with no long return corridor.
        c=c if r%2==0 else 4-c
        components.append(dict(id=id,type=kind,label=title,sublabel=detail,tag=anchor,pos=[40+260*c,y+155*r],size=[235,90]))
        ids.append(id)
        evidence.append(dict(node_id=id,label=title,implementation=anchor))
        if i:
            e=dict(from_=ids[-2],to=id,variant='emphasis')
            e['from']=e.pop('from_')
            if i%5==0:e.update(fromSide='bottom',toSide='top')
            edges.append(e)
    boundaries.append(dict(kind='region',label=label,wraps=ids,pad=25))
    if stage_index:
        previous=stages[stage_index-1][1][-1][0]
        # Alternate stage orientation to preserve a facing vertical transition.
        prev=next(c for c in components if c['id']==previous)
        first=next(c for c in components if c['id']==ids[0])
        if prev['pos'][0]!=first['pos'][0]:
            for c in components[-len(rows):]:c['pos'][0]=1120-c['pos'][0]
        edges.append(dict(**{'from':previous,'to':ids[0]},variant='emphasis',fromSide='bottom',toSide='top'))
    y+=155*((len(rows)+4)//5)+100
gate=next(c for c in components if c['id']=='preflight')
fail_id='diagnostic'
components.append(dict(id=fail_id,type='database',label='预检失败：写入诊断记录',sublabel='失败 / 超时 / OOM / 不支持',tag='record_kind=DIAGNOSTIC · 不进入正式测量',pos=[gate['pos'][0]+310,gate['pos'][1]+115],size=[265,80]))
edges.append({'from':'preflight','to':fail_id,'variant':'security','fromSide':'bottom','toSide':'left','label':'失败','labelAt':[gate['pos'][0]+270,gate['pos'][1]+160]})
for e in edges:
    if e['from']=='preflight' and e['to']=='policy':e['label']='PASS';e['labelDy']=24;e['labelDx']=-48
# Runtime hooks are collected with evidence, rather than presented as new services.
spec=dict(schema_version=1,diagram_type='architecture',meta=dict(title='TSDataCompressBenchMark · 源码展开运行框架',locale='zh-CN',quality_profile='showcase',viewBox=[1380,y-45]),components=components,boundaries=boundaries,connections=edges)
(root/'framework.archify.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
(root/'node-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
print(f'{len(components)} detailed nodes; {len(edges)} connections; no output/constraint cards')
