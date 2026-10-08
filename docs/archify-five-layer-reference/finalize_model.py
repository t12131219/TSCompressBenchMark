import json
from pathlib import Path
p=Path(__file__).resolve().parent
m=json.loads((p/'semantic-model.json').read_text());s=json.loads((p/'framework.archify.json').read_text())
# Source corrections and complete evidence dependencies; keep accepted v1 files frozen.
remove={'tasks--track','track--gates','gates--input','corpus--pareto'}
more=[('tasks','gates','','flow'),('gates','track','','flow'),('track','input','','flow'),('summary','pareto','','flow'),('corpus','report','汇总结果','evidence'),('resources','raw','资源证据','evidence'),('query','raw','查询结果','evidence'),('streaming','raw','流式结果','evidence')]
m['edges']=[e for e in m['edges'] if e['id'] not in remove]
s['connections']=[e for e in s['connections'] if e['id'] not in remove]
for a,b,label,kind in more:
 m['edges'].append(dict(id=a+'--'+b,source=a,target=b,label=label,kind=kind))
 c=dict(id=a+'--'+b,**{'from':a,'to':b})
 if label:c['label']=label
 if kind=='evidence':c['variant']='dashed'
 s['connections'].append(c)
n={n['id']:n for n in s['components']}
n['track']['pos'],n['gates']['pos']=n['gates']['pos'],n['track']['pos']
n['corpus']['pos']=[460,n['summary']['pos'][1]]
s['meta']['title']='TSDataCompressBenchMark · 五层运行框架与数据流'
m['title']=s['meta']['title']
(p/'semantic-model.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
(p/'framework-final.archify.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
print(len(m['nodes']),len(m['edges']))
