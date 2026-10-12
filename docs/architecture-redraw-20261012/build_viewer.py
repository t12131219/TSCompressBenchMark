"""Build the independently checked publication viewer from native geometry exports."""
import json,re,xml.etree.ElementTree as ET
from pathlib import Path
OUT=Path(__file__).resolve().parent
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
def el(tag,attr=None,text=None):
 e=ET.Element('{'+NS+'}'+tag,attr or {})
 if text is not None:e.text=text
 return e

def diagram(name,theme):
 root=ET.fromstring((OUT/(name+'.native.'+theme+'.svg')).read_text())
 root.set('data-theme',theme)
 # Derived publication exports intentionally do not inherit native receipts.
 root.set('data-quality-profile','publication-derived')
 styles=root.find('{'+NS+'}style')
 styles.text += '\nsvg text{font-family:"Noto Sans CJK SC","Microsoft YaHei",sans-serif} .stage-band{fill:var(--bg);stroke:var(--grid-major);stroke-width:1;stroke-dasharray:4 5}.stage-label{fill:var(--text-muted);font-weight:600}.publication-node{cursor:pointer}.publication-node:hover>rect:not(.c-mask){stroke-width:2.7}.publication-node.match>rect:not(.c-mask){stroke-width:3.5}.publication-node:focus{outline:none}.publication-node:focus>rect:not(.c-mask){stroke-width:3}'
 for g in root.findall('.//{'+NS+'}g'):
  if 'data-node-id' in g.attrib:
   g.set('class','publication-node')
   for t in g.findall('{'+NS+'}text'):
    font=14 if 'data-node-label' in t.attrib else (12 if t.get('font-size')=='9' else 10)
    t.set('font-size',str(font));t.attrib.pop('data-detail',None)
    if 'data-node-label' in t.attrib:t.set('y',str(float(t.get('y'))-4))
 for t in root.findall('.//{'+NS+'}text'):
  if 'data-edge-label' in t.attrib or 'data-label-for' in t.attrib: t.set('font-size','12')
 # Replace implementation type names with domain wording and generous spacing.
 for g in list(root):
  if 'data-legend' in g.attrib:root.remove(g)
 vb=[float(x) for x in root.get('viewBox').split()];y=vb[3]-25
 legend=el('g',{'data-publication-legend':''})
 kinds=[('frontend','合同入口与报告'),('backend','执行与计算'),('database','冻结 / 持久工件'),('security','资格 / 正确性'),('external','来源数据')]
 present={g.get('data-node-kind') for g in root.findall('.//{'+NS+'}g')}
 x=35
 for kind,label in kinds:
  if kind not in present:continue
  legend.append(el('rect',{'x':str(x),'y':str(y-10),'width':'15','height':'10','rx':'3','class':'c-'+kind}))
  legend.append(el('text',{'x':str(x+24),'y':str(y),'font-size':'12','class':'t-muted'},label))
  x+=220
 root.append(legend)
 if name=='overview':
  band=el('g',{'data-phase-bands':''})
  for i,label in enumerate(['01 数据与来源','02 能力与合同','03 资格与开发','04 执行与证据','05 统计与报告']):
   x=20+270*i
   band.append(el('rect',{'x':str(x),'y':'58','width':'226','height':'700','rx':'12','class':'stage-band'}))
   band.append(el('text',{'x':str(x+113),'y':'39','font-size':'14','text-anchor':'middle','class':'stage-label'},label))
  ix=next(i for i,g in enumerate(root) if g.get('data-edge-from'))
  root.insert(ix,band)
 # Disambiguate every inline ID in the multi-figure HTML and standalone exports.
 text=ET.tostring(root,encoding='unicode')
 ids=re.findall(r'(?<![-\w])id="([^"]+)"',text)
 for id in sorted(ids,key=len,reverse=True):
  text=re.sub(r'(?<![-\w])id="'+re.escape(id)+'"','id="'+name+'-'+id+'"',text).replace('url(#'+id+')','url(#'+name+'-'+id+')')
 for attr in ['aria-labelledby','aria-describedby']:
  text=re.sub(attr+r'="([^"]+)"',lambda m:attr+'="'+' '.join(name+'-'+v if v in ids else v for v in m.group(1).split())+'"',text)
 return text

svgs={}
for name in ['overview','lanes','object']:
 for theme in ['light','dark']:
  text=diagram(name,theme)
  prefix='framework' if name=='overview' else name
  (OUT/(prefix+'.'+theme+'.svg')).write_text('<?xml version="1.0" encoding="UTF-8"?>\n'+text+'\n')
  if theme=='light':svgs[name]=text
facts=json.loads((OUT/'source-evidence.json').read_text())
panels='\n'.join('<section class="figure" id="'+name+'" '+('' if name=='overview' else 'hidden')+'>'+svgs[name]+'</section>' for name in svgs)
page=r'''<!doctype html>
<html lang="zh-CN" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>TSDataCompressBenchMark · 当前代码架构</title><style>
*{box-sizing:border-box}html{--page:#f1f4f8;--paper:#fff;--ink:#172637;--muted:#657487;--line:#dbe3eb;--accent:#147c9a;--shade:#e8f5f9;color-scheme:light}html[data-theme=dark]{--page:#101821;--paper:#17232f;--ink:#e8f0f8;--muted:#a4b4c5;--line:#314252;--accent:#60d1e5;--shade:#203e4a;color-scheme:dark}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 "Noto Sans CJK SC",system-ui,sans-serif}.shell{width:var(--reader-width,1180px);max-width:calc(100% - 56px);margin:0 auto}header{padding:16px 0 12px;display:flex;align-items:center;gap:20px}.identity{flex:1;min-width:0}.kicker{font-size:11px;letter-spacing:.14em;color:var(--accent);font-weight:700}.identity h1{font-size:24px;letter-spacing:-.6px;line-height:1.2;margin:5px 0 0}button,a.action{font:inherit;color:var(--ink);background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:7px 12px;cursor:pointer;text-decoration:none}button:hover,a.action:hover{border-color:var(--accent)}button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.controls{display:flex;align-items:center;gap:7px}nav{display:flex;gap:8px;margin:0 0 13px}nav button{background:transparent;white-space:nowrap}nav button[aria-selected=true]{background:var(--shade);color:var(--accent);border-color:var(--accent);font-weight:700}.search-wrap{margin-left:auto;position:relative}input{font:inherit;background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:7px 10px;width:235px;color:var(--ink)}#matches{position:absolute;right:0;top:42px;width:360px;max-width:80vw;z-index:3;background:var(--paper);border:1px solid var(--line);border-radius:9px;box-shadow:0 10px 35px #0002}#matches button{display:block;width:100%;text-align:left;border:0;border-radius:0;background:transparent}#matches span{float:right;font-size:11px;color:var(--muted)}article{background:var(--paper);border:1px solid var(--line);border-radius:13px;box-shadow:0 4px 24px #10263806}.figure-head{padding:12px 20px 0;display:flex;gap:15px;align-items:baseline}.figure-head h2{font-size:17px;margin:0}.figure-head p{font-size:12px;color:var(--muted);margin:0 0 0 auto}.figure{padding:0 12px 4px}.figure svg{display:block;width:100%;height:auto}.insight{padding:10px 20px;border-top:1px solid var(--line);display:flex;align-items:center;gap:14px;font-size:12px;color:var(--muted)}.insight strong{color:var(--accent);font-size:11px;letter-spacing:.06em}.insight p{margin:0}footer{padding:8px 2px;color:var(--muted);font-size:11px;display:flex;justify-content:space-between;gap:18px}footer a{color:var(--muted)}[hidden]{display:none!important}dialog{color:var(--ink);background:var(--paper);border:1px solid var(--line);border-radius:14px;width:640px;max-width:calc(100% - 32px);padding:25px;max-height:85vh}dialog::backdrop{background:#08182788;backdrop-filter:blur(3px)}dialog .close{float:right}dialog h3{font-size:20px;margin:8px 0 16px}dialog p{line-height:1.8}dialog small{color:var(--muted)}.sources{padding:0;list-style:none}.sources li{border-top:1px solid var(--line);padding:10px 0}.sources a{color:var(--accent);text-decoration:none;overflow-wrap:anywhere}.sources code{font-size:12px}#detail-code{font-size:11px;color:var(--muted)}.publication-node{cursor:pointer}.publication-node.match{filter:drop-shadow(0 0 4px #1483b540)}@media(max-width:900px){.shell{max-width:calc(100% - 24px);width:auto}header{flex-wrap:wrap;padding-top:16px}.identity h1{font-size:20px}.controls{margin-left:auto}nav{flex-wrap:wrap}.search-wrap{width:100%;margin-left:0}input{width:100%}.figure-head{display:block}.figure-head p{margin:7px 0}.figure{min-width:0;padding:0 4px}.insight{display:block}.insight p{margin-top:4px}footer{display:block}.figure svg{min-width:0}}@media print{header,nav,footer,.figure-head p{display:none}body{background:white}.shell{width:100%;max-width:100%}article{border:0;box-shadow:none}.figure svg{width:100%}}
</style></head><body><div class="shell">
<header><div class="identity"><div class="kicker">当前源码架构 · 2026.10.12</div><h1>TSDataCompressBenchMark</h1></div><div class="controls"><button id="theme" aria-label="切换明暗主题">深色</button><button id="svg-export">SVG</button><button id="png-export">PNG</button><a class="action" id="native-link" href="overview.native.html">缩放查看</a></div></header>
<nav aria-label="架构图视图" role="tablist"><button role="tab" aria-selected="true" data-view="overview">01 · 框架总览</button><button role="tab" aria-selected="false" data-view="lanes">02 · 四条执行路径</button><button role="tab" aria-selected="false" data-view="object">03 · 完整对象闭环</button><div class="search-wrap"><input id="search" aria-label="搜索节点和源码函数" placeholder="搜索节点 / 源码函数"><div id="matches" hidden></div></div></nav>
<article><div class="figure-head"><h2 id="view-title">从原始对象到可审计结论</h2><p id="view-note">五项职责 · Legacy 与 V3.2 分别保留合同</p></div>
__PANELS__
<div class="insight"><strong id="insight-label">阅读重点</strong><p id="insight">资格与 pilot 先于测量；冻结全集决定 Coverage；原对象决定正确性与质量。</p></div></article>
<footer><span>当前工作区 · 34 个源码节点 · 47 个文件依据 · 点击节点查看职责与函数</span><span><a href="source-evidence.md">源码依据</a> &nbsp; 箭头表示数据、控制或证据依赖</span></footer></div>
<dialog id="detail"><button class="close" id="close-detail" aria-label="关闭节点说明">关闭</button><small id="detail-code"></small><h3 id="detail-title"></h3><p id="detail-body"></p><ul class="sources" id="detail-sources"></ul><small>图表达代码实现；门禁通过路线不代表当前运行已完成。</small></dialog>
<script type="application/json" id="source-data">__FACTS__</script><script>
const facts=JSON.parse(document.getElementById('source-data').textContent),byId=Object.fromEntries(facts.nodes.map(n=>[n.id,n]));
const meta={overview:{title:'从原始对象到可审计结论',note:'五项职责 · Legacy 与 V3.2 分别保留合同',insight:'资格与 pilot 先于测量；冻结全集决定 Coverage；原对象决定正确性与质量。'},lanes:{title:'四条执行路径，各自冻结与验收',note:'Legacy / comparison / workload / P2',insight:'CORE 与完整对象 PIPELINE 分开计量；stream、query 与 P2 使用各自冻结协议和报告。'},object:{title:'一个完整对象，闭合恢复与成本',note:'对象与证据的依赖闭环',insight:'每个内循环对象独立 Finalize；恢复依赖计入 FinalBits；计时和资源来自同一试次。'}};
let active='overview';
function fit(){const ratio=active==='overview'?1350/835:1320/750;const width=Math.min(window.innerWidth-56,(window.innerHeight-238)*ratio,1900);document.documentElement.style.setProperty('--reader-width',Math.max(640,width)+'px');}
function select(view){active=view;document.querySelectorAll('.figure').forEach(s=>s.hidden=s.id!==view);document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===view)));document.getElementById('view-title').textContent=meta[view].title;document.getElementById('view-note').textContent=meta[view].note;document.getElementById('insight').textContent=meta[view].insight;document.getElementById('native-link').href=view+'.native.html';fit();}
function openNode(id){const n=byId[id];if(!n)return;document.getElementById('detail-code').textContent=n.view.toUpperCase()+' / '+n.id;document.getElementById('detail-title').textContent=n.label;document.getElementById('detail-body').textContent=n.description;const ul=document.getElementById('detail-sources');ul.replaceChildren();n.sources.forEach(r=>{const li=document.createElement('li'),a=document.createElement('a'),code=document.createElement('code');a.href='../../'+r.path;a.target='_blank';code.textContent=r.path+':'+r.line+'  ·  '+(r.symbol||'module');a.append(code);li.append(a);ul.append(li)});document.getElementById('detail').showModal();}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>select(b.dataset.view));
document.querySelectorAll('svg [data-node-id]').forEach(g=>{g.onclick=()=>openNode(g.dataset.nodeId);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openNode(g.dataset.nodeId)}};g.setAttribute('tabindex','0');g.setAttribute('role','button');g.setAttribute('aria-label','查看 '+g.dataset.nodeLabel+' 的职责与源码')});
document.getElementById('close-detail').onclick=()=>document.getElementById('detail').close();document.getElementById('detail').onclick=e=>{if(e.target===e.currentTarget){const b=e.currentTarget.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)e.currentTarget.close()}};
document.getElementById('theme').onclick=()=>{const theme=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=theme;document.querySelectorAll('.figure svg').forEach(s=>s.dataset.theme=theme);document.getElementById('theme').textContent=theme==='light'?'深色':'浅色';};
const search=document.getElementById('search'),matches=document.getElementById('matches');search.oninput=()=>{const q=search.value.trim().toLowerCase();document.querySelectorAll('.publication-node').forEach(n=>n.classList.remove('match'));matches.replaceChildren();if(!q){matches.hidden=true;return;}const found=facts.nodes.filter(n=>(n.label+' '+n.id+' '+n.sources.map(r=>r.path+' '+r.symbol).join(' ')).toLowerCase().includes(q)).sort((a,b)=>Number(b.label.toLowerCase().includes(q))-Number(a.label.toLowerCase().includes(q)));found.slice(0,7).forEach(n=>{const b=document.createElement('button');b.textContent=n.label;const span=document.createElement('span');span.textContent={overview:'总览',lanes:'执行路径',object:'对象闭环'}[n.view];b.append(span);b.onclick=()=>{select(n.view);matches.hidden=true;const g=document.querySelector('#'+n.view+' [data-node-id="'+n.id+'"]');g.classList.add('match');openNode(n.id)};matches.append(b)});if(!found.length){const b=document.createElement('button');b.textContent='没有匹配的节点或函数';matches.append(b)}matches.hidden=false;};document.addEventListener('keydown',e=>{if(e.key==='Escape'){matches.hidden=true;search.value='';document.querySelectorAll('.match').forEach(n=>n.classList.remove('match'))}});
function exportedSvg(){const original=document.querySelector('#'+active+' svg'),s=original.cloneNode(true);s.setAttribute('xmlns','http://www.w3.org/2000/svg');s.querySelectorAll('.match').forEach(n=>n.classList.remove('match'));return new XMLSerializer().serializeToString(s)}
function save(blob,ext){const a=document.createElement('a'),url=URL.createObjectURL(blob);a.href=url;a.download=(active==='overview'?'framework':active)+'.'+document.documentElement.dataset.theme+'.'+ext;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000)}
document.getElementById('svg-export').onclick=()=>save(new Blob([exportedSvg()],{type:'image/svg+xml;charset=utf-8'}),'svg');
document.getElementById('png-export').onclick=async()=>{const svg=document.querySelector('#'+active+' svg'),box=svg.viewBox.baseVal,blob=new Blob([exportedSvg()],{type:'image/svg+xml;charset=utf-8'}),url=URL.createObjectURL(blob),img=new Image();try{await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=reject;img.src=url});const c=document.createElement('canvas');c.width=box.width*2;c.height=box.height*2;const ctx=c.getContext('2d');ctx.fillStyle=document.documentElement.dataset.theme==='light'?'#ffffff':'#0f172a';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(img,0,0,c.width,c.height);c.toBlob(b=>save(b,'png'));}finally{URL.revokeObjectURL(url)}};
window.addEventListener('resize',fit);fit();
</script></body></html>'''
page=page.replace('__PANELS__',panels).replace('__FACTS__',json.dumps(facts,ensure_ascii=False).replace('</','<\\/'))
(OUT/'framework.html').write_text(page)
print('Wrote publication viewer and six derived SVG exports')
