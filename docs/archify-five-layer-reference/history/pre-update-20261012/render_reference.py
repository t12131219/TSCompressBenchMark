"""Reference presentation of the accepted Archify semantic graph; no installed Skill edits."""
from pathlib import Path
import json, html, hashlib, re, subprocess, math
from PIL import ImageFont
OUT=Path(__file__).resolve().parent
m=json.loads((OUT/'semantic-model.json').read_text());native=json.loads((OUT/'framework-final.archify.json').read_text())
W,H=2180,3435
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
assert Path(FONT).is_file()
fonts={}
def width(text,size):
    if size not in fonts:fonts[size]=ImageFont.truetype(FONT,int(size))
    return fonts[size].getlength(text)
def wrap(text,size,limit):
    # Keep Latin identifiers/words intact where a token fits; CJK wraps by glyph.
    tokens=re.findall(r'[A-Za-z0-9_.*-]+|\s+|[^A-Za-z0-9_.*\s-]',text)
    lines=[];current=''
    for token in tokens:
        if token.isspace():
            if current and not current.endswith(' '):current+=' '
            continue
        if width(token,size)>limit:
            parts=[];part=''
            for ch in token:
                if part and width(part+ch,size)>limit:parts.append(part);part=ch
                else:part+=ch
            if part:parts.append(part)
        else:parts=[token]
        for part in parts:
            if current and width(current+part,size)>limit:lines.append(current.rstrip());current=part
            else:current+=part
    if current:lines.append(current.rstrip())
    return lines

B={}
def box(id,x,y,w=300,h=100):B[id]=[x,y,w,h]
for id,x,y in [('entry',350,145),('freeze',710,145),('dataset',1070,145),('loader',350,285),('characterize',710,285),('canonical',1070,285)]:box(id,x,y,h=90)
for id,x,y,h in [('registry',350,455,100),('sweep',710,455,100),('universe',1070,455,100),('negotiate',1430,455,170),('plans',350,690,110),('resolution',710,690,110),('keys',1070,690,110),('tasks',1430,690,110)]:box(id,x,y,h=h)
for id,x,y,w,h in [('gates',350,950,300,110),('track',710,950,660,120),('input',350,1120,300,100),('adapter',710,1120,300,100),('preprocess',1070,1120,300,100),('boundary',350,1280,300,100),('minimal',710,1280,300,100),('preflight',1070,1280,300,110),('diagnostic',710,1460,300,155),('warmup',1070,1480,300,100),('formal',1070,1640,300,110),('compress',1430,1160,300,88),('finalize',1430,1268,300,88),('accounting',1430,1376,300,104),('decompress',1430,1500,300,88),('correctness',1430,1608,300,130),('lossless',1070,1830,300,100),('lossy',1430,1810,300,155)]:box(id,x,y,w,h)
for id,x,y,w,h in [('policy',350,2080,300,100),('timing',710,2080,300,120),('resources',1070,2080,300,120),('workloads',1430,2080,300,100),('query',1070,2250,300,105),('streaming',1430,2250,300,105),('raw',710,2410,660,100)]:box(id,x,y,w,h)
for id,x,y,w,h in [('evidence',350,2590,300,100),('eligibility',710,2590,300,100),('summary',1070,2590,660,130),('corpus',350,2790,660,130),('pareto',1070,2790,300,100),('coverage',1430,2790,300,130),('report',710,3000,660,100)]:box(id,x,y,w,h)
# Actual text footprint drives capacity before routes are authored.
for id in ['entry','freeze','dataset','loader','characterize','canonical']:B[id][3]=100
for id in ['loader','characterize','canonical']:B[id][1]+=60
for id,h in {'keys':120,'diagnostic':215,'compress':100,'finalize':100,'accounting':120,'decompress':100,'correctness':140,'resources':140,'raw':120,'streaming':120,'lossy':145}.items():B[id][3]=h
for id,y in {'compress':1160,'finalize':1280,'accounting':1400,'decompress':1540,'correctness':1660,'lossless':1840,'lossy':1840}.items():B[id][1]=y
STAGES=[(105,450),(585,470),(1125,1100),(2255,510),(2785,570)]
# All lower phases move together; relations retain the same semantics.
for n in m['nodes']:
    if n['phase']=='plan':B[n['id']][1]+=160
    elif n['phase']!='data':B[n['id']][1]+=225

# Side geometry: source and target ports are explicit presentation controls.
def port(id,side='right',offset=0):
    x,y,w,h=B[id]
    return {'left':[x,y+h/2+offset],'right':[x+w,y+h/2+offset],'top':[x+w/2+offset,y],'bottom':[x+w/2+offset,y+h]}[side]
R={};L={};SIDES={}
def route(a,b,sa='right',sb='left',via=(),label=None,oa=0,ob=0):
    id=a+'--'+b;start=port(a,sa,oa);end=port(b,sb,ob);SIDES[id]=[sa,sb]
    # Presentation points below use pre-shift coordinates; shift by their band.
    via=[list(v) for v in via]
    for v in via:
        if v[1]>=900:v[1]+=225
        elif v[1]>=395:v[1]+=160 if v[1]<830 else 225
    if via:
        if sa in ['left','right'] and len(via)>1 and via[0][0]==via[1][0]:via[0][1]=start[1]
        if sb in ['left','right'] and len(via)>1 and via[-1][0]==via[-2][0]:via[-1][1]=end[1]
    if not via and start[0]!=end[0] and start[1]!=end[1]:
        if sa in ['right','left'] and sb in ['right','left']:
            mid=(start[0]+end[0])/2;via=[[mid,start[1]],[mid,end[1]]]
        elif sa in ['top','bottom'] and sb in ['top','bottom']:
            mid=(start[1]+end[1])/2;via=[[start[0],mid],[end[0],mid]]
    pts=[start,*via,end];fixed=[start]
    for i,q in enumerate(pts[1:]):
        prev=fixed[-1]
        if prev[0]!=q[0] and prev[1]!=q[1]:
            fixed.append([q[0],prev[1]] if (i==0 and sa in ['left','right']) or (i==len(pts)-2 and sb in ['top','bottom']) else [prev[0],q[1]])
        if fixed[-1]!=q:fixed.append(q)
    R[id]=fixed

    if label:
        lx,ly=label
        if ly>=900:ly+=225
        elif ly>=395:ly+=160 if ly<830 else 225
        L[id]=[lx,ly]
# Data: two left-to-right rows.
route('entry','freeze');route('freeze','dataset')
route('dataset','loader','bottom','top',[[1220,260],[500,260]])
route('loader','characterize');route('characterize','canonical')
route('canonical','registry','bottom','top',[[1220,410],[500,410]])
# Planning; four result states are fields of negotiation, not four running services.
route('registry','sweep');route('sweep','universe');route('universe','negotiate')
route('negotiate','plans','bottom','top',[[1580,655],[500,655]])
route('plans','resolution');route('resolution','keys');route('keys','tasks')
route('tasks','gates','bottom','top',[[1580,865],[500,865]])
route('gates','track')
route('track','input','bottom','top',[[1040,1095],[500,1095]])
route('input','adapter');route('adapter','preprocess')
route('preprocess','boundary','bottom','top',[[1220,1250],[500,1250]])
route('boundary','minimal');route('minimal','preflight')
route('preflight','warmup','bottom','top',label=[1270,1435])
route('warmup','formal','bottom','top')
route('preflight','diagnostic','left','right',[[1040,1335],[1040,1537.5]],label=[985,1415])
route('formal','compress','right','left',[[1400,1695],[1400,1204]],label=[1360,1787])
for a,b in [('compress','finalize'),('finalize','accounting'),('accounting','decompress'),('decompress','correctness')]:route(a,b,'bottom','top')
route('correctness','lossless','bottom','top',[[1580,1820],[1220,1820]],label=[1280,1830])
route('correctness','lossy','bottom','top',label=[1700,1824],oa=80)
route('formal','policy','bottom','top',[[1220,1788],[1025,1788],[1025,2010],[500,2010]],label=[780,1995])
# Measurement is a shared responsibility projection; dashed paths are labeled.
route('policy','timing')
route('policy','resources','bottom','bottom',[[500,2240],[1220,2240]],label=[850,2238])
route('timing','workloads','top','top',[[860,2055],[1580,2055]])
route('workloads','query','left','right',[[1400,2130],[1400,2302.5]],label=[1360,2230])
route('workloads','streaming','bottom','top',label=[1640,2220])
route('workloads','raw','left','top',[[1385,2145],[1385,2380],[1040,2380]],oa=15)
route('resources','raw','left','top',[[1045,2140],[1045,2410]],label=[1000,2355],ob=5)
route('query','raw','bottom','top',label=[1255,2385],ob=180)
route('streaming','raw','bottom','top',[[1580,2393],[1160,2393]],label=[1500,2373],ob=120)
route('diagnostic','raw','left','left',[[325,1537.5],[325,2470]],label=[460,2450])
route('raw','evidence','bottom','top',[[1120,2550],[500,2550]],oa=80)
route('evidence','eligibility');route('eligibility','summary')
route('summary','corpus','left','top',[[1040,2655],[1040,2760],[680,2760]])
route('summary','pareto','bottom','top',oa=-180)
route('evidence','coverage','top','right',[[500,2575],[1795,2575],[1795,2855]],label=[1580,2568])
route('corpus','report','bottom','top',[[680,2960],[880,2960]],label=[785,2940],ob=-160)
route('pareto','report','bottom','top',[[1220,2940],[1040,2940]],ob=0)
route('coverage','report','bottom','top',[[1580,2970],[1200,2970]],label=[1470,2950],ob=160)
assert set(B)=={n['id'] for n in m['nodes']}
assert set(R)=={e['id'] for e in m['edges']}
# For unlabeled data/execution steps, endpoints already express the operation.
# Every meaningful condition/evidence label is kept; exact position is checked below.
L['workloads--raw']=[1408,2623]
L['workloads--query']=[1400,2464]
L['streaming--raw']=[1510,2620]
L['query--raw']=[1280,2600]
L['workloads--raw']=[1430,2640]
for e in m['edges']:
    if e['label'] and e['id'] not in L:
        pts=R[e['id']];a,b=max(zip(pts,pts[1:]),key=lambda ab:abs(ab[0][0]-ab[1][0])+abs(ab[0][1]-ab[1][1]))
        L[e['id']]=[(a[0]+b[0])/2+30,(a[1]+b[1])/2-13]

def intersects_segment_rect(a,b,r):
    x,y,w,h=r
    if a[0]==b[0]:return x-1<a[0]<x+w+1 and max(min(a[1],b[1]),y)<min(max(a[1],b[1]),y+h)
    if a[1]==b[1]:return y-1<a[1]<y+h+1 and max(min(a[0],b[0]),x)<min(max(a[0],b[0]),x+w)
    return True
issues=[]
for id,pts in R.items():
    src,tgt=id.split('--')
    for a,b in zip(pts,pts[1:]):
        if a[0]!=b[0] and a[1]!=b[1]:issues.append(dict(kind='non-orthogonal',edge=id,segment=[a,b]))
        for n,r in B.items():
            if n not in [src,tgt] and intersects_segment_rect(a,b,r):issues.append(dict(kind='edge-through-node',edge=id,node=n,segment=[a,b]))
for i,(id,r) in enumerate(B.items()):
    x,y,w,h=r
    for id2,r2 in list(B.items())[i+1:]:
        x2,y2,w2,h2=r2
        if x<x2+w2 and x+w>x2 and y<y2+h2 and y+h>y2:issues.append(dict(kind='node-overlap',nodes=[id,id2]))
for e in m['edges']:
    if e['id'] in L:
        x,y=L[e['id']];tw=width(e['label'],16)+14;r=[x-tw/2,y-18,tw,26]
        for n,b in B.items():
            if r[0]<b[0]+b[2] and r[0]+r[2]>b[0] and r[1]<b[1]+b[3] and r[1]+r[3]>b[1]:issues.append(dict(kind='label-over-node',edge=e['id'],node=n))
# Actual multiline text footprint is verified; no fitted/shrunk type.
for n in m['nodes']:
    if n['id']=='negotiate':continue
    x,y,w,h=B[n['id']];sz=16 if n['id'] in ['diagnostic','lossy','accounting','finalize','decompress','compress'] else 17
    title=wrap(n['label'],21,w-30)
    details=sum((wrap(t,sz,w-30) for t in n['lines']),[])
    if n['id']=='preflight':details=['正确性 / 安全门控'];title=['Preflight']
    needed=len(title)*27+len(details)*22+20
    if needed>h:issues.append(dict(kind='text-capacity',node=n['id'],need=needed,height=h))
validation=dict(status='pass' if not issues else 'fail',nodeCount=len(B),edgeCount=len(R),sameSemanticNodes=set(B)=={n['id'] for n in native['components']},sameDirectedEdges={(e['source'],e['target']) for e in m['edges']}=={(e['from'],e['to']) for e in native['connections']},issues=issues)
(OUT/'reference-structure-check.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
# Validate actual crossing/corridor and port contracts in the derived layout.
from itertools import combinations
for id,pts in R.items():
    sa,sb=SIDES[id]
    dx=pts[1][0]-pts[0][0];dy=pts[1][1]-pts[0][1]
    ex=pts[-1][0]-pts[-2][0];ey=pts[-1][1]-pts[-2][1]
    first={'right':dx>0 and dy==0,'left':dx<0 and dy==0,'top':dy<0 and dx==0,'bottom':dy>0 and dx==0}[sa]
    last={'right':ex<0 and ey==0,'left':ex>0 and ey==0,'top':ey>0 and ex==0,'bottom':ey<0 and ex==0}[sb]
    if not first or not last:issues.append(dict(kind='endpoint-direction',edge=id,first=first,last=last))
for (id1,pts1),(id2,pts2) in combinations(R.items(),2):
    if set(id1.split('--'))&set(id2.split('--')):continue
    for a,b in zip(pts1,pts1[1:]):
        for c,d in zip(pts2,pts2[1:]):
            if a[0]==b[0] and c[1]==d[1] and min(a[1],b[1])<c[1]<max(a[1],b[1]) and min(c[0],d[0])<a[0]<max(c[0],d[0]):issues.append(dict(kind='proper-crossing',edges=[id1,id2],point=[a[0],c[1]]))
            if a[1]==b[1] and c[0]==d[0] and min(a[0],b[0])<c[0]<max(a[0],b[0]) and min(c[1],d[1])<a[1]<max(c[1],d[1]):issues.append(dict(kind='proper-crossing',edges=[id1,id2],point=[c[0],a[1]]))
            if a[0]==b[0]==c[0]==d[0] and min(max(a[1],b[1]),max(c[1],d[1]))-max(min(a[1],b[1]),min(c[1],d[1]))>=8:issues.append(dict(kind='ambiguous-corridor',edges=[id1,id2]))
            if a[1]==b[1]==c[1]==d[1] and min(max(a[0],b[0]),max(c[0],d[0]))-max(min(a[0],b[0]),min(c[0],d[0]))>=8:issues.append(dict(kind='ambiguous-corridor',edges=[id1,id2]))
print('Pre-render geometry issues:',len(issues))

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
    out.append(f'<text x="2148" y="53" font-size="18" text-anchor="end" fill="{c["muted"]}">当前工作区源码 · 2026-10-08</text>')
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
    out.append(f'<polygon points="1417,1330 1745,1330 1745,2220 1050,2220 1050,2045 1417,2045" fill="none" stroke="{c["accents"][2]}" stroke-dasharray="8 5" stroke-width="2"/><text x="1430" y="1360" font-size="18" font-weight="700" fill="{c["ink"]}">Formal Repetitions 的对象展开</text>')
    out.append(f'<text x="350" y="2205" font-size="18" fill="{c["muted"]}">正式执行仍逐次验证；Context / Finalize / 计量 / 解码随每个独立对象发生。</text>')
    out.append(f'<text x="710" y="2755" font-size="17" fill="{c["muted"]}">条件工作负载按请求顺序隔离调度；分支连线不代表同时并发。</text>')
    # Draw paths before nodes; every relation carries its stable semantic ID.
    for e in m['edges']:
        pts=R[e['id']];dash=' stroke-dasharray="8 5"' if e['kind'] in ['scope','evidence','conditional','expansion'] else ''
        out.append(f'<polyline class="edge" data-edge-id="{e["id"]}" data-from="{e["source"]}" data-to="{e["target"]}" points="'+ ' '.join(f'{x},{y}' for x,y in pts)+f'" stroke="{c["line"]}" stroke-width="1.8" marker-end="url(#arrow)"{dash}/>' )
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
    out.append(f'<text x="30" y="3403" font-size="17" fill="{c["muted"]}">实线：处理 / 数据主路径　虚线：条件工作负载、证据依赖、同次测量或对象展开（见连线标签）</text><text x="2148" y="3403" font-size="16" text-anchor="end" fill="{c["muted"]}">源码依据与检查记录随图交付</text></svg>')
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
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TSDataCompressBenchMark · 五层运行框架</title><style>*{box-sizing:border-box}body{margin:0;background:#edf1f5;color:#152331;font:16px "Noto Sans CJK SC",sans-serif}header{padding:14px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}header strong{margin-right:auto}button,a{font:inherit;padding:7px 12px;border:1px solid #a9bbc9;border-radius:6px;background:white;color:#152331;text-decoration:none}input{font:inherit;min-width:0;max-width:100%;padding:7px;width:210px;border:1px solid #a9bbc9;border-radius:6px}main{max-width:2180px;margin:auto}svg{display:block;width:100%;height:auto}section[hidden]{display:none}body.dark{background:#101820;color:#e9f0f8}body.dark header button,body.dark header a,body.dark input{background:#223444;color:#e9f0f8}footer{padding:16px 20px}mark{background:#ffdf85}dialog{max-width:min(760px,92vw);border:1px solid #9caebd;border-radius:12px;padding:24px}dialog::backdrop{background:#0005}@media print{header,footer,dialog{display:none}body{background:white}main{max-width:none}}</style><header><strong>五层运行框架与数据流</strong><input id="search" aria-label="搜索节点" placeholder="搜索节点 / 代码函数"><button id="theme">切换深色</button><a id="svg-download" download href="framework.light.svg">下载 SVG</a><a id="png-download" download href="framework.light.png">下载 PNG</a><a href="native-final.html">Archify 原生查看器</a></header><main>'''
page+='<section id="light">'+svgs['light']+'</section><section id="dark" hidden>'+svgs['dark']+'</section></main>'
page+='''<footer>长幅阅读版支持页面纵向滚动。点击节点查看源码依据；原生查看器另含搜索、聚焦、关系追踪与导出功能。</footer><dialog><h2 id="dialog-title"></h2><div id="dialog-content"></div><p><button id="close">关闭</button></p></dialog><script>const model='''+json.dumps(m,ensure_ascii=False)+''';let dark=false;const $=s=>document.querySelector(s);$('#theme').onclick=()=>{dark=!dark;document.body.classList.toggle('dark',dark);$('#light').hidden=dark;$('#dark').hidden=!dark;$('#theme').textContent=dark?'切换浅色':'切换深色';$('#svg-download').href='framework.'+(dark?'dark':'light')+'.svg';$('#png-download').href='framework.'+(dark?'dark':'light')+'.png'};$('#search').oninput=e=>{const q=e.target.value.toLowerCase().trim();for(const n of model.nodes){const match=q&&JSON.stringify(n).toLowerCase().includes(q);document.querySelectorAll('[data-node-id="'+n.id+'"]').forEach(el=>el.classList.toggle('selected',!!match))}};document.querySelectorAll('[data-node-id]').forEach(el=>el.onclick=()=>{const n=model.nodes.find(n=>n.id===el.dataset.nodeId);$('#dialog-title').textContent=n.label;const div=$('#dialog-content');div.replaceChildren();for(const t of [...n.lines,...n.source]){const p=document.createElement('p');p.textContent=t;div.append(p)}$('dialog').showModal()});$('#close').onclick=()=>$('dialog').close();</script></html>'''
(OUT/'framework.html').write_text(page)
(OUT/'reference-layout.json').write_text(json.dumps({'viewBox':[0,0,W,H],'nodeBoxes':B,'edgeRoutes':R,'edgeLabelPositions':L,'endpointSides':SIDES,'stageBands':STAGES,'role':'presentation geometry; topology is semantic-model.json'},ensure_ascii=False,indent=2)+'\n')
print('Final presentation:',validation['status'],'issues:',len(issues))
