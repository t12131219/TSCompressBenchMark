"""Supplement the existing five-layer source model; retain the legacy path."""
from pathlib import Path
import json
OUT=Path(__file__).resolve().parent
BASE=OUT/'history/pre-update-20261012'
m=json.loads((BASE/'semantic-model.json').read_text())
m.update(updated_at='2026-10-12 Asia/Shanghai', update_basis='current working tree; five-layer in-place supplement', presentation='long-form five-layer reference; legacy path plus V3.2 supplementary lanes')
byid={n['id']:n for n in m['nodes']}
def change(id,**fields):byid[id].update(fields)
change('entry',label='Legacy 命令入口与配置',lines=['CLI / Benchmark Runner','Legacy ExperimentConfig / TOML'])
change('freeze',label='Legacy 初始化与恢复')
change('keys',label='Legacy 层级可比性键',lines=['ExecutionPathHash','Semantic / Execution / Resource 键'])
change('tasks',label='Legacy 任务与注册快照')
change('formal',lines=['Legacy Formal Repetitions','外层逐次验证 / 独立对象内循环'])
change('warmup',label='每个测量 worker 内预热',lines=['Warmup 排除于计时边界','固定次数与时长，不证明稳态'],source=['execution/repetition.py:perform_worker_measurement','execution/orchestrator.py:execute_task'])
change('accounting',lines=['Accounting Ledger / FinalBits','完整流 + 公共恢复信息 / side info'],source=['accounting/ledger.py:AccountingLedger','execution/recovery.py:bind_decode_context'])
change('decompress',lines=['独立解码 Context','物化输出 / 恢复原域 dtype 与 shape'],source=['execution/repetition.py:perform_roundtrip','execution/recovery.py:restore_decoded_output'])
change('minimal',lines=['Common Correctness','独立 clean worker 恢复'],source=['execution/preflight.py:preflight_task','execution/recovery.py:decode_in_fresh_worker'])
change('policy',label='Legacy 同次测量策略')
change('timing',lines=['Legacy：CORE / PIPELINE / E2E','Encode、Decode 各自达标','V3.2 scope 由独立合同固定'])
change('workloads',label='Legacy 条件工作负载',lines=['Legacy Profile 请求且支持','V3.2 使用独立 workload runner'])
change('streaming',lines=['请求且支持：块延迟 / 状态','checkpoint 仅按实际能力留证'])
change('raw',label='Legacy 原始证据与投影')
change('evidence',label='Legacy 冻结证据读取')
change('summary',label='Legacy 逐数据集统计')
change('report',label='Legacy 结果与报告生成')
change('lossy',lines=['Error-bounded：误差界 + 质量','Unbounded：质量，无误差保证','Rate / Summary：框架 validator','当前无活动算法或正式比较组'])
def node(id,phase,label,lines,sources,role='process'):
 m['nodes'].append(dict(id=id,phase=phase,label=label,detail=' / '.join(lines),lines=lines,source=sources,role=role,updated=True))
def edge(a,b,label='',kind='flow'):
 m['edges'].append(dict(id=a+'--'+b,source=a,target=b,label=label,kind=kind,updated=True))
node('source_identity','data','来源、内容身份与显式派生',[
 '原内容 SHA / DatasetID / 完整父级 lineage',
 'f32 / uint8 / ND / 缺失模式：分别冻结派生对象'],[
 'datasets/canonical_source.py:register_canonical_source','comparison/models.py:CorpusSpec','comparison/pipeline_runner.py:build_real_pipeline_inputs'])
node('logical_object','data','Canonical / P2 逻辑原对象',[
 'T / V / validity · dtype / shape / time_axis / units',
 'P2 LogicalObjectSchema / channel collection wrapper',
 'async / ragged：独立 schema 与有限对象资格'],[
 'pipelines/models.py:LogicalObjectSchema','pipelines/channel_collection.py:ChannelCollectionSchema','datasets/prepare.py:prepare_dataset'],'artifact')
edge('dataset','source_identity','来源与派生','evidence');edge('source_identity','logical_object')
node('experiment_contract','plan','事前决策与比较合同',[
 'experiment_decision / Task / Contract',
 'Group / Corpus / ConfigMap / Expected',
 'Protocol / AnalysisPolicy：测量前冻结'],[
 'comparison/decision.py:freeze_experiment_decision','comparison/models.py:ComparisonContract','comparison/runner.py:prepare_comparison'],'artifact')
node('expected_matrix','plan','完整期待矩阵与成员准入',[
 'MethodID / ImplementationID 去重',
 'CORE：两方法 / 两独立真实来源',
 'PASS / REJECT / BLOCKED 保留分母'],[
 'comparison/planning.py:compile_group_plan','comparison/models.py:ExpectedOutcomeMatrix'])
node('public_projection','plan','公共投影与实际输入',[
 '原对象与 COMMON_NATIVE_API 分组',
 '实际输入 schema / bytes / 路径披露',
 'P2 有序 recipe / child / block / tail'],[
 'comparison/projection.py:public_projection','comparison/planning.py:validate_job_for_cell','comparison/pipeline_runner.py:prepare_pipeline_comparison'])
node('frozen_schedule','plan','冻结作业、源码与调度',[
 'ExecutionJob / Recipe / Closure',
 'Build / Environment / CPU / Threads',
 'Schedule block / pair / 固定重复'],[
 'comparison/runner.py:prepare_comparison','execution/schedule.py:build_schedule','comparison/pipeline_runner.py:prepare_pipeline_comparison'],'artifact')
edge('logical_object','experiment_contract','原对象依赖','evidence')
edge('experiment_contract','expected_matrix');edge('expected_matrix','public_projection');edge('public_projection','frozen_schedule')
node('object_qualification','exec','原对象资格与独立恢复',[
 'Preflight / 安全 / 原域 correctness',
 '公共恢复信息 + 保存字节 / clean worker',
 '未通过留证，阻断正式测量',
 'SOURCE_PARITY / N/G/CAP 分别验收'],[
 'comparison/runner.py:qualify_comparison','execution/preflight.py:preflight_task','comparison/pipeline_runner.py:qualify_pipeline_comparison'],'validation')
node('development_pilot','exec','独立开发 pilot 门禁',[
 '与评价对象分离的 development 输入',
 '方向时钟 / 粒度 / 采集器开关扰动',
 '资格与 pilot 通过后才可 FORMAL'],[
 'comparison/runner.py:pilot_comparison','measurement/v32_protocol.py:run_pilot','comparison/pipeline_runner.py:pilot_pipeline_comparison'],'validation')
node('formal_lanes','exec','分 lane 隔离正式执行',[
 'comparison：完整对象 / API / cold',
 'workload：query / stream 独立协议',
 'pipeline：完整 P2 对象与公开配方',
 '逐 lane 串行 / frozen Schedule / spawn'],[
 'comparison/runner.py:execute_comparison','comparison/workload_runner.py:execute_workload_comparison','comparison/pipeline_runner.py:execute_pipeline_comparison'])
node('p2_object','exec','P2 完整对象与公共恢复',[
 '全部 T / V / mask · mixed / ND / time_axis',
 '列 / 块子流 / RAW_TAIL / LZ4-Zstd',
 'paid schema / child 依赖 / 原始 RawBits',
 '独立 decoder 物化恢复 / 产物保存'],[
 'pipelines/runtime.py:encode_object','pipelines/runtime.py:decode_in_fresh_process','comparison/pipeline_runner.py:_recovery'],'optional')
edge('frozen_schedule','object_qualification','冻结作业','evidence')
edge('object_qualification','development_pilot','资格通过');edge('development_pilot','formal_lanes','pilot 通过')
edge('formal_lanes','p2_object','P2 对象展开','expansion')
node('measurement_boundary','measure','V3.2 计时与生命周期边界',[
 '完整对象：steady / cold PIPELINE',
 '共同 native API：STEADY_PROCESS CORE',
 'encode / decode 真时钟与方向门槛'],[
 'comparison/runner.py:prepare_comparison','execution/repetition.py:perform_declared_worker_measurement','execution/cold_driver.py:measure_cold_object'])
node('resource_lease','measure','资源租约与同步观测',[
 'ResourceLease / CPU / Threads / RSS gate',
 '父进程线程观测 / 环境 / 总 wall 预算',
 '同一试次采集，不扣除 collector 开销'],[
 'measurement/resource_lease.py:ResourceLease','measurement/thread_monitor.py:ParentThreadMonitor','comparison/runner.py:execute_comparison'])
node('trial_store','measure','持久试次、事件与恢复产物',[
 'comparison_trials / workload_trials',
 'P2 trials / pipeline_events / artifacts',
 'append-only / STARTED / 固定分母'],[
 'comparison/runner.py:_append_trial','comparison/workload_runner.py:execute_workload_comparison','comparison/pipeline_runner.py:_commit_attempt'],'artifact')
node('resume_audit','measure','中断、预算与 no-op resume',[
 '未知 STARTED 禁止自动重测',
 'P2 预留预算 / 事件链 / COMMITTED',
 '失败终态保留 / 完成后 no-op resume',
 '源码或工件漂移需建立新运行身份'],[
 'comparison/runner.py:execute_comparison','comparison/pipeline_runner.py:_attempt_state','comparison/pipeline_runner.py:_block_interrupted_attempts'])
edge('formal_lanes','measurement_boundary','同次执行职责','scope')
edge('measurement_boundary','resource_lease','同一试次','scope');edge('resource_lease','trial_store','观测与状态','evidence');edge('trial_store','resume_audit','恢复重核','evidence')
node('paired_analysis','stats','V3.2 只读重核与真实配对',[
 '冻结 plan / 原始 raw / artifacts 重核',
 '均值时间比 / Schedule block bootstrap',
 '多重区间 / 效应与精度 / 固定分母'],[
 'comparison/analysis.py:analyze_comparison','comparison/analysis.py:_effect','comparison/pipeline_runner.py:report_pipeline_comparison'])
node('quality_coverage','stats','原域质量、Pareto 与 Coverage',[
 '原域误差 / 实际 FinalBits / 公共投影',
 '固定 corpus 与真实来源 / 全矩阵缺口',
 '不合格或精度不足保留 INCONCLUSIVE'],[
 'comparison/analysis_extensions.py:augment_analysis','comparison/analysis.py:analyze_comparison'])
node('v32_reports','stats','V3.2 报告与结论边界',[
 'analysis JSON / HTML / P2 report.md',
 '引用 decision / 资格 / pilot / raw',
 '结论仅限冻结 corpus 与本机范围'],[
 'comparison/runner.py:report_comparison','comparison/workload_runner.py:report_workload_comparison','comparison/pipeline_runner.py:report_pipeline_comparison'],'artifact')
node('scope_acceptance','stats','辅助审计与逐条范围验收',[
 '未压缩 SIZE_BASELINE / buffer cost',
 'no-op resume / completion / 条款验收',
 '不转授 SOURCE_PARITY 或正式资格',
 '当前 P2 pilot 不合格仍保留'],[
 'tools/audit_v32_uncompressed_reference.py','tools/audit_v32_buffer_costs.py:build_buffer_cost_audit','tools/audit_v32_completion.py:audit'])
edge('trial_store','paired_analysis','只读证据','evidence')
edge('paired_analysis','quality_coverage');edge('quality_coverage','v32_reports');edge('v32_reports','scope_acceptance','独立验收','evidence')
# Five responsibilities stay in the original frame; sidebar describes both contracts.
phase_updates={
 'data':(['统一原对象与输入','保留语义与派生链','冻结可复用数据基础'],['DatasetID / Manifest / Canonical','LogicalObjectSchema / P2 输入','完整 T / V / mask 与 typed schema','特征 / 准备记录 / 原始 RawBits'],['校验源字节与内容身份','不隐式排序 / cast / 填充','显式派生、轴、单位和来源链','async/ragged 不扩大 codec 原生域','P2 不强制沿用 legacy wire']),
 'plan':(['Legacy 能力与任务','V3.2 事前合同编译','冻结全矩阵与真实调度'],['Legacy task_plan / 配置 / 三级键','experiment_decision / bundle','Expected Matrix / 公共投影','ExecutionJob / Recipe / Schedule','Closure / Build / Environment'],['完整合法配置与期待分母','别名/参数/ISA 不增加方法数','CORE 两方法、两真实来源','API 实际 schema / bytes 相同','旧比较键不授新组资格']),
 'exec':(['输入安全与正确性','独立恢复与开发 pilot','分 lane 正式对象执行'],['Preflight / 资格与恢复证据','独立 development pilot','P1/P2 完整产物与 FinalBits','comparison / workload / P2','失败原因与原域 correctness'],['资格与 pilot 是测量门禁','Finalize 与恢复依赖计入成本','最后内循环对象供公共验证','Rate/Summary 无活动正式组','流程存在不等于当前运行通过']),
 'measure':(['同次计时与资源','独立 profile 与工作负载','持久证据与中断审计'],['CORE / PIPELINE / cold 边界','ResourceLease / 线程观测','Legacy raw / CSV 投影','comparison / workload / P2 trials','STARTED / Events / 恢复产物'],['同次采集，非第二轮测量','Query / stream 各自冻结协议','未知 STARTED 不自动重测','P2 持久预留预算与事件链','collector/counters 如实 availability']),
 'stats':(['按合同核验资格','真实配对与固定分母','报告、辅助审计与验收'],['Legacy CSV / median / 三级键','V3.2 block 配对 / 固定矩阵','质量 / Pareto / Coverage / 缺口','分析 JSON / HTML / P2 报告','参考成本 / completion / 条款验收'],['Legacy 重复要求按其合同','V3.2 精度与配对块按冻结政策','缺口 / INCONCLUSIVE 保留','仅冻结 corpus / 本机范围','辅助审计不替代 FORMAL/parity'])}
for phase in m['phases']:
 phase['duties'],phase['outputs'],phase['constraints']=phase_updates[phase['id']]
(OUT/'semantic-model.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
print('Updated model:',len(m['nodes']),'nodes;',len(m['edges']),'edges')
