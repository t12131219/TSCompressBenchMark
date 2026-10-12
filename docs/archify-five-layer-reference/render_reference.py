"""Current five-layer presentation, generated from source-backed model and preserved layout."""
from pathlib import Path
import json, html, hashlib, re, subprocess, math
from PIL import ImageFont
OUT=Path(__file__).resolve().parent
m=json.loads((OUT/'semantic-model.json').read_text())
base=json.loads((OUT/'history/pre-update-20261012/reference-layout.json').read_text())
W,H=2180,4815
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
fonts={}
def width(text,size):
    if size not in fonts:fonts[size]=ImageFont.truetype(FONT,int(size))
    return fonts[size].getlength(text)
def wrap(text,size,limit):
    tokens=re.findall(r'[A-Za-z0-9_.*-]+|\s+|[^A-Za-z0-9_.*\s-]',text)
    lines=[];current=''
    for token in tokens:
        if token.isspace():
            if current and not current.endswith(' '):current+=' '
            continue
        parts=[];part=''
        for ch in token:
            if part and width(part+ch,size)>limit:parts.append(part);part=ch
            else:part+=ch
        if part:parts.append(part)
        for part in parts:
            if current and width(current+part,size)>limit:lines.append(current.rstrip());current=part
            else:current+=part
    if current:lines.append(current.rstrip())
    return lines
D={'data':0,'plan':220,'exec':480,'measure':750,'stats':1110}
EXTRA={'data':220,'plan':260,'exec':270,'measure':360,'stats':270}
def shift(y):
    return y+(0 if y<585 else 220 if y<1125 else 480 if y<2255 else 750 if y<2785 else 1110)
B={n['id']:[*base['nodeBoxes'][n['id']][:1],base['nodeBoxes'][n['id']][1]+D[n['phase']],*base['nodeBoxes'][n['id']][2:]] for n in m['nodes'] if not n.get('updated')}
B['raw'][1]+=80
STAGES=[(y+D[p['id']],h+EXTRA[p['id']]) for p,(y,h) in zip(m['phases'],base['stageBands'])]
SROWS={p['id']:y+h+D[p['id']]+30+(100 if p['id']=='measure' else 0) for p,(y,h) in zip(m['phases'],base['stageBands'])}
for id,x,w in [('source_identity',350,660),('logical_object',1070,660)]:B[id]=[x,SROWS['data'],w,140]
for id,x in [('experiment_contract',1430),('expected_matrix',1070),('public_projection',710),('frozen_schedule',350)]:B[id]=[x,SROWS['plan'],300,190]
for id,x in [('object_qualification',350),('development_pilot',710),('formal_lanes',1070),('p2_object',1430)]:B[id]=[x,SROWS['exec'],300,210]
for id,x in [('measurement_boundary',350),('resource_lease',710),('trial_store',1070),('resume_audit',1430)]:B[id]=[x,SROWS['measure'],300,190]
for id,x in [('paired_analysis',350),('quality_coverage',710),('v32_reports',1070),('scope_acceptance',1430)]:B[id]=[x,SROWS['stats'],300,210]
R={id:[[x,shift(y)] for x,y in pts] for id,pts in base['edgeRoutes'].items()}
L={id:[x,shift(y)] for id,(x,y) in base['edgeLabelPositions'].items()}
SIDES={id:s[:] for id,s in base['endpointSides'].items()}
def port(id,side,offset=0):
    x,y,w,h=B[id]
    return {'left':[x,y+h/2+offset],'right':[x+w,y+h/2+offset],'top':[x+w/2+offset,y],'bottom':[x+w/2+offset,y+h]}[side]
def route(a,b,sa='right',sb='left',via=(),label=None,oa=0,ob=0):
    id=a+'--'+b;pts=[port(a,sa,oa),*[list(p) for p in via],port(b,sb,ob)]
    clean=[pts[0]]
    for p in pts[1:]:
        if p!=clean[-1]:clean.append(p)
    R[id]=clean;SIDES[id]=[sa,sb]
    if label:L[id]=list(label)
# Cross-layer legacy edges bypass the new supplementary boxes.
route('canonical','registry','bottom','top',[[1220,480],[325,480],[325,B['registry'][1]-30],[500,B['registry'][1]-30]])
route('tasks','gates','right','top',[[1795,port('tasks','right')[1]],[1795,B['gates'][1]-30],[500,B['gates'][1]-30]])
route('raw','evidence','bottom','top',[[1120,B['raw'][1]+B['raw'][3]+15],[325,B['raw'][1]+B['raw'][3]+15],[325,B['evidence'][1]-30],[500,B['evidence'][1]-30]],oa=80)
route('formal','policy','bottom','top',[[1220,2493],[1025,2493],[1025,2715],[680,2715],[680,3015],[500,3015]],label=[970,2630])
# Give the former crowded Layer 4 labels a real open band above raw storage.
route('resources','raw','left','top',[[1045,port('resources','left')[1]],[1045,B['raw'][1]-30]],ob=5,label=[970,3330])
route('query','raw','bottom','top',ob=180,label=[1280,3350])
route('streaming','raw','bottom','top',[[1580,3448],[1160,3448]],ob=120,label=[1510,3390])
route('workloads','raw','left','top',[[1385,port('workloads','left',15)[1]],[1385,3405],[1040,3405]],oa=15,label=[1500,3415])
R['diagnostic--raw'][-1]=port('raw','left')
R['diagnostic--raw'][-2][1]=port('raw','left')[1]
L['diagnostic--raw']=[460,port('raw','left')[1]-20]
# Keep independent inbound/outbound relationships on distinct ports.
route('preflight','diagnostic','top','right',[[1220,1960],[1025,1960],[1025,port('diagnostic','right')[1]]])
R['evidence--coverage'][0][0]+=70
R['evidence--coverage'][1][0]+=70
R['summary--corpus'][0][1]+=18
R['summary--corpus'][1][1]+=18
# V3.2 additions form distinct rails inside the same five bands.
route('dataset','source_identity','right','top',[[1780,port('dataset','right')[1]],[1780,SROWS['data']-35],[680,SROWS['data']-35]],label=[1510,SROWS['data']-48])
route('source_identity','logical_object')
route('logical_object','experiment_contract','right','right',[[1760,port('logical_object','right')[1]],[1760,port('experiment_contract','right')[1]]],label=[1630,STAGES[1][0]-20])
for a,b in [('experiment_contract','expected_matrix'),('expected_matrix','public_projection'),('public_projection','frozen_schedule')]:route(a,b,'left','right')
route('frozen_schedule','object_qualification','left','left',[[334,port('frozen_schedule','left')[1]],[334,port('object_qualification','left')[1]]],label=[575,STAGES[2][0]-20])
for a,b in [('object_qualification','development_pilot'),('development_pilot','formal_lanes'),('formal_lanes','p2_object')]:
    route(a,b,label=[(port(a,'right')[0]+port(b,'left')[0])/2,SROWS['exec']-9])
source_bottom=port('formal_lanes','bottom')
route('formal_lanes','measurement_boundary','bottom','left',[[source_bottom[0],source_bottom[1]+18],[334,source_bottom[1]+18],[334,port('measurement_boundary','left')[1]]],label=[920,source_bottom[1]+4])
for a,b in [('measurement_boundary','resource_lease'),('resource_lease','trial_store'),('trial_store','resume_audit')]:
    route(a,b,label=[(port(a,'right')[0]+port(b,'left')[0])/2,SROWS['measure']-7])
source_bottom=port('trial_store','bottom')
route('trial_store','paired_analysis','bottom','left',[[source_bottom[0],source_bottom[1]+25],[334,source_bottom[1]+25],[334,port('paired_analysis','left')[1]]],label=[970,source_bottom[1]+11])
for a,b in [('paired_analysis','quality_coverage'),('quality_coverage','v32_reports'),('v32_reports','scope_acceptance')]:
    route(a,b,label=[(port(a,'right')[0]+port(b,'left')[0])/2,SROWS['stats']-9])
assert set(B)=={n['id'] for n in m['nodes']}
assert set(R)=={e['id'] for e in m['edges']}
def overlaps(a,b):
    x,y,w,h=a;X,Y,W,H=b
    return x<X+W and x+w>X and y<Y+H and y+h>Y
def intersects_segment_rect(a,b,r):
    x,y,w,h=r
    if a[0]==b[0]:return x<a[0]<x+w and max(min(a[1],b[1]),y)<min(max(a[1],b[1]),y+h)
    if a[1]==b[1]:return y<a[1]<y+h and max(min(a[0],b[0]),x)<min(max(a[0],b[0]),x+w)
    return True
# Place every meaningful label in free space, preserving its words and arrow.
placed=[]
for e in m['edges']:
    if not e['label']:continue
    id=e['id'];tw=width(e['label'],16)+14
    if id not in L:
        a,b=max(zip(R[id],R[id][1:]),key=lambda q:abs(q[0][0]-q[1][0])+abs(q[0][1]-q[1][1]))
        L[id]=[(a[0]+b[0])/2,(a[1]+b[1])/2-14]
    x,y=L[id];candidates=[(x,y)]
    for dy in [-24,24,-44,44,-64,64,-84,84]:candidates.append((x,y+dy))
    for dx in [-30,30,-60,60,-90,90]:
        for dy in [0,-24,24,-44,44]:candidates.append((x+dx,y+dy))
    for lx,ly in candidates:
        rect=[lx-tw/2,ly-19,tw,26]
        if rect[0]<312 or rect[0]+rect[2]>1820:continue
        if any(overlaps(rect,b) for b in B.values()) or any(overlaps(rect,b) for b in placed):continue
        if any(intersects_segment_rect(a,b,rect) for pts in R.values() for a,b in zip(pts,pts[1:])):continue
        L[id]=[lx,ly];placed.append(rect);break
issues=[]
for id,pts in R.items():
    src,tgt=id.split('--');sa,sb=SIDES[id]
    for a,b in zip(pts,pts[1:]):
        if a[0]!=b[0] and a[1]!=b[1]:issues.append(dict(kind='non-orthogonal',edge=id,segment=[a,b]))
        for n,r in B.items():
            if n not in [src,tgt] and intersects_segment_rect(a,b,r):issues.append(dict(kind='edge-through-node',edge=id,node=n))
    dx=pts[1][0]-pts[0][0];dy=pts[1][1]-pts[0][1];ex=pts[-1][0]-pts[-2][0];ey=pts[-1][1]-pts[-2][1]
    first={'right':dx>0 and dy==0,'left':dx<0 and dy==0,'top':dy<0 and dx==0,'bottom':dy>0 and dx==0}[sa]
    last={'right':ex<0 and ey==0,'left':ex>0 and ey==0,'top':ey>0 and ex==0,'bottom':ey<0 and ex==0}[sb]
    if not first or not last:issues.append(dict(kind='endpoint-direction',edge=id,first=first,last=last))
for i,(id,b) in enumerate(B.items()):
    for id2,b2 in list(B.items())[i+1:]:
        if overlaps(b,b2):issues.append(dict(kind='node-overlap',nodes=[id,id2]))
for e in m['edges']:
    if not e['label']:continue
    x,y=L[e['id']];r=[x-(width(e['label'],16)+14)/2,y-19,width(e['label'],16)+14,26]
    for id,b in B.items():
        if overlaps(r,b):issues.append(dict(kind='label-over-node',edge=e['id'],node=id))
    for id,pts in R.items():
        if any(intersects_segment_rect(a,b,r) for a,b in zip(pts,pts[1:])):issues.append(dict(kind='label-mask-crosses-route',label=e['id'],edge=id))
for n in m['nodes']:
    if n['id']=='negotiate':continue
    x,y,w,h=B[n['id']];sz=16 if n['id'] in ['diagnostic','lossy','accounting','finalize','decompress','compress'] else 17
    tl=wrap(n['label'],21,w-30);dl=sum((wrap(t,sz,w-30) for t in n['lines']),[])
    if n['id']=='preflight':tl=['Preflight'];dl=['正确性 / 安全门控']
    needed=len(tl)*27+len(dl)*22+20
    if needed>h:issues.append(dict(kind='text-capacity',node=n['id'],need=needed,height=h))
crossings=[]
for i,(eid,pts) in enumerate(R.items()):
    for eid2,pts2 in list(R.items())[i+1:]:
        for a,b in zip(pts,pts[1:]):
            for c,d in zip(pts2,pts2[1:]):
                v=a[0]==b[0];u=c[0]==d[0]
                if v==u:
                    if (v and a[0]==c[0]) or (not v and a[1]==c[1]):
                        k=1 if v else 0;length=min(max(a[k],b[k]),max(c[k],d[k]))-max(min(a[k],b[k]),min(c[k],d[k]))
                        if length>0:issues.append(dict(kind='ambiguous-shared-corridor',edges=[eid,eid2],length=length))
                else:
                    aa,bb,cc,dd=(a,b,c,d) if v else (c,d,a,b)
                    if min(aa[1],bb[1])<cc[1]<max(aa[1],bb[1]) and min(cc[0],dd[0])<aa[0]<max(cc[0],dd[0]):
                        crossings.append(dict(edges=[eid,eid2],point=[aa[0],cc[1]],horizontal=eid2 if v else eid))
validation=dict(status='pass' if not issues else 'fail',nodeCount=len(B),edgeCount=len(R),sameSemanticNodes=set(B)=={n['id'] for n in m['nodes']},sameDirectedEdges=set(R)=={e['id'] for e in m['edges']},issues=issues,crossingBridges=crossings,scope='derived five-layer long-form reference, separate from native Archify acceptance')
# A matching native specification is checked independently; the main reference remains exact-path.
native={'schema_version':1,'diagram_type':'architecture','meta':{'title':m['title']+' · 2026-10-12','locale':'zh-CN','quality_profile':'standard','viewBox':[W,H]},'components':[],'connections':[]}
for n in m['nodes']:
    x,y,w,h=B[n['id']]
    typ='database' if n['role']=='artifact' else 'security' if n['role'] in ['validation','decision','failure'] else 'backend'
    # Current working-tree evidence lives in source-evidence.json, independently of native receipts.
    c={'id':n['id'],'type':typ,'label':n['label'],'sublabel':n['lines'][0],'pos':[x,y],'size':[w,h-8 if n['id'] in ['compress','finalize','accounting','decompress'] else h]}
    native['components'].append(c)
for e in m['edges']:
    sa,sb=SIDES[e['id']];pts=R[e['id']];via=[p[:] for p in pts[1:-1]]
    # Native schema uses side-centre ports, whereas the reference has offset ports.
    a=port(e['source'],sa);b=port(e['target'],sb)
    if e['target'] in ['compress','finalize','accounting','decompress']:
        b[1]-=4 if sb in ['left','right'] else 8 if sb=='bottom' else 0
    if not via and (a!=pts[0] or b!=pts[-1]) and sa in ['top','bottom'] and sb in ['top','bottom']:
        mid=(a[1]+b[1])/2;via=[[a[0],mid],[b[0],mid]]
    else:
        if pts[0]!=a:
            q=pts[1];via.insert(0,[a[0],q[1]] if sa in ['top','bottom'] else [q[0],a[1]])
        if pts[-1]!=b:
            q=pts[-2];via.append([b[0],q[1]] if sb in ['top','bottom'] else [q[0],b[1]])
    c={'id':e['id'],'from':e['source'],'to':e['target'],'label':e['label'],'variant':'dashed' if e['kind'] in ['scope','evidence','conditional','expansion'] else 'default','fromSide':sa,'toSide':sb,'via':via}
    if e['label']:c['labelAt']=L[e['id']]
    native['connections'].append(c)
(OUT/'framework-updated.archify.json').write_text(json.dumps(native,ensure_ascii=False,indent=2)+'\n')

LIGHT=dict(bg='#ffffff',ink='#152331',muted='#3a4c5d',node='#eaf4ff',stroke='#2786c8',success='#daf0df',fail='#ffe3e6',optional='#f7efff',panel='#ffffff',line='#34495b',phases=['#e8f3fe','#ecf8ef','#fff6da','#fff0f3','#f2edff'],strips=['#9bcdfa','#abe3b8','#ffda78','#ffb9c6','#d6c1fa'],accents=['#2688ce','#28a357','#d49a16','#db5572','#9270c5'])
DARK=dict(bg='#101820',ink='#e9f0f8',muted='#c5d2e0',node='#20394b',stroke='#69b9ed',success='#244b37',fail='#5b2c37',optional='#403054',panel='#18242f',line='#cbd8e3',phases=['#152b3c','#192f27','#342d18','#35212a','#2b2441'],strips=['#244b69','#28563b','#6c551f','#663042','#4c3870'],accents=['#70bdf4','#75d795','#f4ce69','#ffa3ba','#c9a8ff'])
def text_block(txt,x,y,size,fill,limit,center=False,bold=False,spacing=None):
    ls=wrap(txt,size,limit);spacing=spacing or size*1.4
    attrs=f'font-size="{size}" fill="{fill}"'+(' text-anchor="middle"' if center else '')+(' font-weight="700"' if bold else '')
    return ''.join(f'<text x="{x}" y="{y+i*spacing}" {attrs}>{html.escape(t)}</text>' for i,t in enumerate(ls)),len(ls)*spacing

def render(theme):
    c=LIGHT if theme=='light' else DARK;out=[]
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc"><title id="title">{html.escape(m["title"])}</title><desc id="desc">五层源码框架；正式验证与测量共享执行，资格过滤先于统计，覆盖率来自冻结任务全集。</desc><style>text{{font-family:"Noto Sans CJK SC",sans-serif}}.node{{cursor:pointer}}.node:hover rect{{stroke-width:3}}.edge{{fill:none}}.selected rect,.selected polygon{{stroke-width:4}}@media print{{.node{{cursor:default}}}}</style><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0 L9 4.5 L0 9 Z" fill="{c["line"]}"/></marker><pattern id="optional" patternUnits="userSpaceOnUse" width="9" height="9"><path d="M-2 9 L9 -2 M7 11 L11 7" stroke="{c["stroke"]}" stroke-opacity=".14" stroke-width="1"/></pattern></defs><rect width="{W}" height="{H}" fill="{c["bg"]}"/>')
    out.append(f'<text x="30" y="55" font-size="34" font-weight="700" fill="{c["ink"]}">{html.escape(m["title"])}</text>')
    out.append(f'<text x="2148" y="53" font-size="18" text-anchor="end" fill="{c["muted"]}">当前工作区源码 · 2026-10-12</text>')
    for i,(p,(sy,sh)) in enumerate(zip(m['phases'],STAGES)):
        accent=c['accents'][i]
        out.append(f'<g data-stage="{p["id"]}"><rect x="18" y="{sy}" width="2144" height="{sh}" rx="14" fill="{c["phases"][i]}" stroke="{accent}" stroke-width="2" stroke-dasharray="5 5"/><rect x="29" y="{sy+12}" width="276" height="{sh-24}" rx="10" fill="{c["strips"][i]}"/></g>')
        out.append(f'<text x="49" y="{sy+58}" font-size="18" fill="{c["ink"]}">LAYER 0{i+1}</text>')
        title,dh=text_block(p['title'],49,sy+105,32,c['ink'],235,bold=True);out.append(title)
        eng_lines={'data':['Data','Preparation'],'plan':['Capability &','Configuration'],'exec':['Execution &','Validation'],'measure':['Performance','Evaluation'],'stats':['Statistics &','Reporting']}[p['id']]
        for k,t in enumerate(eng_lines):out.append(f'<text x="49" y="{sy+105+dh+10+k*35}" font-size="25" font-weight="700" fill="{c["ink"]}">{html.escape(t)}</text>')
        dy=sy+sh-40-30*(len(p['duties'])-1)
        for d in p['duties']:out.append(f'<text x="49" y="{dy}" font-size="21" fill="{c["ink"]}">{html.escape(d)}</text>');dy+=30
        for kind,title,items,cy,ch in [('outputs','关键输出',p['outputs'],sy+14,(sh-42)/2),('constraints','核心约束',p['constraints'],sy+28+(sh-42)/2,(sh-42)/2)]:
            # Small first-stage cards need compact actual height; wrap all strings.
            out.append(f'<g data-annotation="{p["id"]}-{kind}"><rect x="1830" y="{cy}" width="312" height="{ch}" rx="10" fill="{c["panel"]}" stroke="{accent}" stroke-width="2"/>')
            out.append(f'<text x="1848" y="{cy+32}" font-size="23" font-weight="700" fill="{c["ink"]}">{title}</text>')
            yy=cy+60
            for item in items:
                t,hh=text_block(item,1848,yy,18,c['muted'],278,spacing=25);out.append(t);yy+=hh+2
            if theme=='light' and yy-2>cy+ch-8:issues.append(dict(kind='annotation-capacity',phase=p['id'],card=kind,need=yy-cy+8,height=ch))
            out.append('</g>')
    # Object lifecycle expansion is not a second run.
    out.append(f'<polygon points="1417,1810 1745,1810 1745,2700 1050,2700 1050,2525 1417,2525" fill="none" stroke="{c["accents"][2]}" stroke-dasharray="8 5" stroke-width="2"/><text x="1430" y="1840" font-size="18" font-weight="700" fill="{c["ink"]}">Formal Repetitions 的对象展开</text>')
    out.append(f'<text data-lifecycle-note="formal" x="350" y="2665" font-size="18" fill="{c["muted"]}">每个内循环对象独立 Finalize；最后一个对象提供公共正确性 / 计量证据。</text>')
    for phase in m['phases']:
        note={'data':'V3.2 补充：输入身份与逻辑原对象','plan':'V3.2 补充：事前合同与冻结计划','exec':'V3.2 资格与正式执行','measure':'V3.2 同次测量与证据','stats':'V3.2 补充：只读分析与范围验收'}[phase['id']]
        out.append(f'<text data-supplement-note="{phase["id"]}" x="350" y="{SROWS[phase["id"]]-20}" font-size="18" font-weight="700" fill="{c["accents"][1]}">{note}</text>')
    # Draw paths before nodes; every relation carries its stable semantic ID.
    for e in m['edges']:
        pts=R[e['id']];dash=' stroke-dasharray="8 5"' if e['kind'] in ['scope','evidence','conditional','expansion'] else ''
        out.append(f'<polyline class="edge" data-edge-id="{e["id"]}" data-from="{e["source"]}" data-to="{e["target"]}" points="'+ ' '.join(f'{x},{y}' for x,y in pts)+f'" stroke="{c["line"]}" stroke-width="1.8" marker-end="url(#arrow)"{dash}/>' )
    # Bridges explicitly distinguish crossing dependencies from connected junctions.
    for crossing in crossings:
        x,y=crossing['point'];fill=c['bg']
        for i,(sy,sh) in enumerate(STAGES):
            if sy<=y<=sy+sh:fill=c['phases'][i]
        out.append(f'<g data-crossing-bridge="{crossing["horizontal"]}"><circle cx="{x}" cy="{y}" r="8" fill="{fill}"/><path d="M{x-8},{y} Q{x},{y-12} {x+8},{y}" fill="none" stroke="{c["line"]}" stroke-width="1.8"/></g>')
    for n in m['nodes']:
        id=n['id'];x,y,w,h=B[id];fill=c['fail'] if n['role']=='failure' else c['success'] if id in ['warmup','formal','lossless','keys'] else c['optional'] if n['role'] in ['optional','validation'] else c['node']
        stroke=c['accents'][2] if id in [z['id'] for z in m['nodes'] if z['id'] in ['compress','finalize','accounting','decompress','correctness']] else c['stroke']
        out.append(f'<g class="node" id="node-{id}" data-node-id="{id}"><title>{html.escape(n["label"]+" · "+" / ".join(n["source"]))}</title>')
        if id=='preflight':out.append(f'<polygon points="{x+w/2},{y} {x+w},{y+h/2} {x+w/2},{y+h} {x},{y+h/2}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        else:
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"'+(' stroke-dasharray="6 4"' if n['role']=='optional' else '')+'/>')
            if n['role']=='optional':out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="url(#optional)"/>')
        if id=='negotiate':
            out.append(f'<text x="{x+w/2}" y="{y+30}" font-size="21" text-anchor="middle" font-weight="700" fill="{c["ink"]}">能力协商与四态结果</text>')
            for j,(s,col) in enumerate(zip(n['lines'],[c['node'],c['success'],c['optional'],c['fail']])):
                out.append(f'<rect x="{x+15}" y="{y+43+j*29}" width="{w-30}" height="25" rx="4" fill="{col}"/><text x="{x+w/2}" y="{y+62+j*29}" font-size="17" text-anchor="middle" fill="{c["ink"]}">{s}</text>')
        else:
            sz=16 if id in ['diagnostic','lossy','accounting','finalize','decompress','compress'] else 17
            tl=wrap(n['label'],21,w-30);dl=sum((wrap(t,sz,w-30) for t in n['lines']),[])
            if id=='preflight':tl=['Preflight'];dl=['正确性 / 安全门控']
            total=len(tl)*27+len(dl)*22;yy=y+(h-total)/2+20
            for t in tl:out.append(f'<text x="{x+w/2}" y="{yy}" font-size="21" font-weight="700" text-anchor="middle" fill="{c["ink"]}">{html.escape(t)}</text>');yy+=27
            for t in dl:out.append(f'<text x="{x+w/2}" y="{yy}" font-size="{sz}" text-anchor="middle" fill="{c["muted"]}">{html.escape(t)}</text>');yy+=22
        out.append('</g>')
    for e in m['edges']:
        if e['label']:
            x,y=L[e['id']];tw=width(e['label'],16)+14
            out.append(f'<g data-edge-label="{e["id"]}"><rect x="{x-tw/2}" y="{y-19}" width="{tw}" height="26" rx="3" fill="{c["bg"]}"/><text x="{x}" y="{y}" text-anchor="middle" font-size="16" fill="{c["ink"]}">{html.escape(e["label"])}</text></g>')
    out.append(f'<text x="30" y="4783" font-size="17" fill="{c["muted"]}">实线：处理 / 数据主路径　虚线：条件、证据、同次测量或对象展开　圆弧跨线：不相连</text><text x="2148" y="4783" font-size="16" text-anchor="end" fill="{c["muted"]}">源码依据与检查记录随图交付</text></svg>')
    return ''.join(out)
for theme in ['light','dark']:
    svg=render(theme);(OUT/f'framework.{theme}.svg').write_text(svg)
    subprocess.run(['rsvg-convert','-w','2180','-o',str(OUT/f'framework.{theme}.png'),str(OUT/f'framework.{theme}.svg')],check=True)
validation['issues']=issues;validation['status']='pass' if not issues else 'fail'
(OUT/'reference-structure-check.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
# Readable long-form companion: normal document scrolling, no clipping or inner scroller.
svgs={t:(OUT/f'framework.{t}.svg').read_text() for t in ['light','dark']}
for t in svgs:
    svgs[t]=re.sub(r'(?<![\w-])id="([^"]+)"',lambda q:'id="'+t+'-'+q[1]+'"',svgs[t])
    svgs[t]=re.sub(r'url\(#([^)]+)\)',lambda q:'url(#'+t+'-'+q[1]+')',svgs[t])
    svgs[t]=svgs[t].replace('aria-labelledby="title desc"',f'aria-labelledby="{t}-title {t}-desc"')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSDataCompressBenchMark · 五层运行框架</title><style>*{box-sizing:border-box}body{margin:0;background:#edf1f5;color:#152331;font:16px "Noto Sans CJK SC",sans-serif}header{padding:14px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}header strong{margin-right:auto}button,a{font:inherit;padding:7px 12px;border:1px solid #a9bbc9;border-radius:6px;background:white;color:#152331;text-decoration:none}input{font:inherit;min-width:0;max-width:100%;padding:7px;width:210px;border:1px solid #a9bbc9;border-radius:6px}main{max-width:2180px;margin:auto}svg{display:block;width:100%;height:auto}section[hidden]{display:none}body.dark{background:#101820;color:#e9f0f8}body.dark header button,body.dark header a,body.dark input{background:#223444;color:#e9f0f8}footer{padding:16px 20px}mark{background:#ffdf85}dialog{max-width:min(760px,92vw);border:1px solid #9caebd;border-radius:12px;padding:24px}dialog::backdrop{background:#0005}@media print{header,footer,dialog{display:none}body{background:white}main{max-width:none}}</style><header><strong>五层运行框架与数据流 · 已更新 2026-10-12</strong><input id="search" aria-label="搜索节点" placeholder="搜索节点 / 代码函数"><button id="theme">切换深色</button><a id="svg-download" download href="framework.light.svg">下载 SVG</a><a id="png-download" download href="framework.light.png">下载 PNG</a><a href="native-updated.html">Archify 原生查看器</a></header><main>'''
page+='<section id="light">'+svgs['light']+'</section><section id="dark" hidden>'+svgs['dark']+'</section></main>'
page+='''<footer>长幅阅读版支持页面纵向滚动。点击节点查看源码依据；新增 V3.2 补充区；原有 Legacy 合同单独保留。<a href="update-notes-20261012.md">更新说明与源码证据</a></footer><dialog><h2 id="dialog-title"></h2><div id="dialog-content"></div><p><button id="close">关闭</button></p></dialog><script>const model='''+json.dumps(m,ensure_ascii=False)+''';let dark=false;const $=s=>document.querySelector(s);$('#theme').onclick=()=>{dark=!dark;document.body.classList.toggle('dark',dark);$('#light').hidden=dark;$('#dark').hidden=!dark;$('#theme').textContent=dark?'切换浅色':'切换深色';$('#svg-download').href='framework.'+(dark?'dark':'light')+'.svg';$('#png-download').href='framework.'+(dark?'dark':'light')+'.png'};$('#search').oninput=e=>{const q=e.target.value.toLowerCase().trim();for(const n of model.nodes){const match=q&&JSON.stringify(n).toLowerCase().includes(q);document.querySelectorAll('[data-node-id="'+n.id+'"]').forEach(el=>el.classList.toggle('selected',!!match))}};document.querySelectorAll('[data-node-id]').forEach(el=>el.onclick=()=>{const n=model.nodes.find(n=>n.id===el.dataset.nodeId);$('#dialog-title').textContent=n.label;const div=$('#dialog-content');div.replaceChildren();for(const t of [...n.lines,...n.source]){const p=document.createElement('p');p.textContent=t;div.append(p)}$('dialog').showModal()});$('#close').onclick=()=>$('dialog').close();</script></html>'''
(OUT/'framework.html').write_text(page)
(OUT/'reference-layout.json').write_text(json.dumps({'viewBox':[0,0,W,H],'nodeBoxes':B,'edgeRoutes':R,'edgeLabelPositions':L,'endpointSides':SIDES,'stageBands':STAGES,'role':'presentation geometry; topology is semantic-model.json'},ensure_ascii=False,indent=2)+'\n')
print('Final presentation:',validation['status'],'issues:',len(issues))
if issues:raise SystemExit(1)
