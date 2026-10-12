"""Author source-grounded, bounded views of the current framework."""
import json
from pathlib import Path
OUT = Path(__file__).resolve().parent

def node(id, typ, label, sublabel, stage, row, tag=''):
    d = dict(id=id, type=typ, label=label, sublabel=sublabel, stage=stage, row=row, width=168, height=72)
    if tag: d['tag'] = tag
    return d

def flow(id, source, target, label, variant='emphasis'):
    return dict(id=id, **{'from':source, 'to':target}, label=label, variant=variant)

def component(id, typ, label, sublabel, x,y,w=240,h=86):
    return dict(id=id,type=typ,label=label,sublabel=sublabel,pos=[x,y],size=[w,h])

def rel(id, source,target,label,variant='emphasis'):
    return dict(id=id, **{'from':source,'to':target},label=label,variant=variant)

overview = {
 'schema_version':1,'diagram_type':'dataflow',
 'meta':{'title':'TSDataCompressBenchMark · 当前框架总览','locale':'zh-CN','quality_profile':'showcase','viewBox':[1160,765],
 'legend':{'mode':'auto','entries':{'emphasis':{'label':'主数据流'},'security':{'label':'测量门禁'},'dashed':{'label':'独立路径'},'database':{'label':'冻结或持久工件'}}}},
 'stages':[{'label':x} for x in ['数据与来源','能力与冻结合同','资格与开发校准','执行与持久证据','统计与报告']],
 'nodes':[
 node('dataset_identity','external','数据来源与身份','Manifest / SHA / 派生链',0,0,'DatasetID'),
 node('logical_inputs','database','规范化原对象','时间 / 值 / mask / 轴',0,1,'Canonical / LogicalObject'),
 node('codec_sources','backend','算法能力与来源','CodecRegistry / SourceRegistry',1,0,'参数域 / ISA / 工件'),
 node('contract_bundle','frontend','事前实验合同','Task / Corpus / Protocol',1,1,'Group / ConfigMap / Expected'),
 node('compiled_matrix','database','冻结全矩阵与调度','协商 / 公共投影 / 源码闭包',1,2,'ExecutionJob / Schedule'),
 node('qualification_gate','security','完整原对象资格','输入安全 / 正确性 / 独立恢复',2,2,'按预期核对支持与拒绝'),
 node('pilot_gate','security','独立 development pilot','计时阈值 / 内循环 / 采集扰动',2,3,'通过后开放正式测量'),
 node('formal_workers','backend','分 lane 隔离执行','对象 / native API / P2 / workload',3,3,'Finalize / 恢复 / 资源观测'),
 node('persistent_trials','database','持久原始证据','Trials / Artifacts / Events',3,4,'失败 / STARTED / 预算'),
 node('readonly_statistics','backend','只读重核与统计','block 配对 / 质量 / Coverage',4,4,'先资格过滤，再估计效应'),
 node('scoped_reports','frontend','报告与结论范围','JSON / HTML / Markdown',4,3,'有限语料与主机 / INCONCLUSIVE'),
 node('legacy_contract','backend','Legacy TOML 路径','task_plan / runs / statistics',0,4,'独立合同与三级可比性键'),
 ],
 'flows':[
 flow('dataset_to_object','dataset_identity','logical_inputs','校验与准备'),
 flow('objects_to_contract','logical_inputs','contract_bundle','输入身份'),
 flow('capability_to_contract','codec_sources','contract_bundle','声明能力'),
 flow('contract_to_matrix','contract_bundle','compiled_matrix','编译冻结'),
 flow('matrix_to_qualification','compiled_matrix','qualification_gate','全部单元'),
 flow('qualification_to_pilot','qualification_gate','pilot_gate','资格通过','security'),
 flow('pilot_to_execution','pilot_gate','formal_workers','校准合格','security'),
 flow('execution_to_trials','formal_workers','persistent_trials','逐次提交'),
 flow('trials_to_statistics','persistent_trials','readonly_statistics','原始证据'),
 flow('statistics_to_reports','readonly_statistics','scoped_reports','固定分母'),
 flow('objects_to_legacy','logical_inputs','legacy_contract','独立旧合同','dashed'),
 ],
}

lanes = {'schema_version':1,'diagram_type':'architecture','meta':{'title':'四条执行路径 · 各自冻结与验收','locale':'zh-CN','quality_profile':'showcase','viewBox':[1320,750]},
 'components':[], 'connections':[], 'boundaries':[]}
items = [
 ('legacy','Legacy TOML','TOML / BenchmarkTask','execute_task','warmup + measured roundtrip','generate_report','median / 三级键 / Coverage'),
 ('comparison','V3.2 对象与 API','Bundle / ComparisonRun','execute_comparison','PIPELINE / CORE / cold','report_comparison','paired block CI / 效应判定'),
 ('workload','V3.2 工作负载','stream / query 合同','execute_workload_comparison','冻结序列 / 缓存 / 查询会话','report_workload_comparison','profile 口径 / 正确性审计'),
 ('p2','P2 组合流水线','LogicalObject / PipelineRecipe','execute_pipeline_comparison','encode_object / 独立恢复','report_pipeline_comparison','完整对象成本 / P2 trial 审计'),
]
for i,(id,title,sub,execute,execsub,report,repsub) in enumerate(items):
 x=35+i*320
 for j,(suffix,typ,label,subtitle) in enumerate([('plan','database',title,sub),('execute','backend',execute,execsub),('report','frontend',report,repsub)]):
  lanes['components'].append(component(id+'_'+suffix,typ,label,subtitle,x,100+j*220,w=280,h=90))
 lanes['connections'] += [rel(id+'_plan_exec',id+'_plan',id+'_execute','冻结计划与门禁'),rel(id+'_exec_report',id+'_execute',id+'_report','持久试次与审计')]
 lanes['boundaries'].append(dict(kind='region',label=title,wraps=[id+'_plan',id+'_execute',id+'_report'],pad=15))

object_flow = {'schema_version':1,'diagram_type':'architecture','meta':{'title':'完整对象闭环 · 编码、恢复与计量','locale':'zh-CN','quality_profile':'showcase','viewBox':[1320,750]},'components':[
 component('original_domain','database','冻结原域输入','T / V / mask / dtype / shape',35,100,240),
 component('explicit_transform','backend','显式路由与预处理','CompatibilityPlan / PreprocessPlan',365,100,250),
 component('encoding_session','backend','独立编码对象','create → update → finalize',705,100,250),
 component('finalized_artifact','database','完整编码产物','stream / Ledger / DecodeContext',1035,100,250),
 component('recovery_worker','security','独立解码与恢复','新 worker / 已保存字节与依赖',1035,335,250),
 component('correctness_contract','security','原域正确性验证','逐位 / 误差界 / 原时间网格',705,335,250),
 component('paid_accounting','database','完整对象比特成本','FinalBits = Serialized + SideInfo',365,335,250),
 component('trial_observation','backend','同一试次观测','wall / CPU / RSS / 线程 / 计数器',35,335,250),
 component('stored_evidence','database','保存试次与恢复证据','TrialID / 工件 SHA / 失败原因',35,570,250),
 component('eligible_analysis','frontend','资格筛选后的分析','冻结分母 / 效应 / 质量 / Pareto',365,570,250),
 ],'connections':[
 rel('original_to_transform','original_domain','explicit_transform','输入验证'),
 rel('transform_to_encode','explicit_transform','encoding_session','实际缓冲区'),
 rel('encode_to_artifact','encoding_session','finalized_artifact','完整 Finalize'),
 rel('artifact_to_recovery','finalized_artifact','recovery_worker','保存字节'),
 rel('recovery_to_validation','recovery_worker','correctness_contract','还原原对象'),
 rel('validation_to_accounting','correctness_contract','paid_accounting','原域验证结果'),
 rel('accounting_to_trial','paid_accounting','trial_observation','成本与正确性'),
 rel('trial_to_storage','trial_observation','stored_evidence','持久提交'),
 rel('storage_to_analysis','stored_evidence','eligible_analysis','证据重核'),
 ]}
# Architecture free placement fixes the diagnosed fixed dataflow sizing.
overview['diagram_type'] = 'architecture'
overview['meta']['viewBox'] = [1350,835]
overview['meta'].pop('legend')
overview['components'] = [
 dict(id=n['id'],type=n['type'],label=n['label'],sublabel=n['sublabel'],tag=n.get('tag',''),pos=[35+n['stage']*270,90+n['row']*140],size=[196,80])
 for n in overview.pop('nodes')
]
overview['connections'] = overview.pop('flows')
overview.pop('stages')
for name,model in [('overview',overview),('lanes',lanes),('object',object_flow)]:
 (OUT/(name+'.archify.json')).write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n')
print('Wrote three candidates: overview, lanes, object')
# Place only labels identified by the first layout diagnostic in the clear gaps.
repairs={
 'overview':{'dataset_to_object':[133,184],'capability_to_contract':[403,184],'contract_to_matrix':[403,324],'qualification_to_pilot':[673,464],'execution_to_trials':[943,604],'objects_to_legacy':[133,324]},
 'lanes':{**{x+'_plan_exec':[175+i*320,204] for i,x in enumerate(['legacy','comparison','workload','p2'])},**{x+'_exec_report':[175+i*320,424] for i,x in enumerate(['legacy','comparison','workload','p2'])}},
 'object':{'artifact_to_recovery':[1160,200],'trial_to_storage':[160,435]},
}
for name in repairs:
 p=OUT/(name+'.archify.json'); m=json.loads(p.read_text())
 for c in m['connections']:
  if c['id'] in repairs[name]: c['labelAt']=repairs[name][c['id']]
 p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
