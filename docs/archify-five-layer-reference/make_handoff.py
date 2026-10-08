from pathlib import Path
import json,hashlib,datetime
from PIL import Image,ImageDraw,ImageFont
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
def bind(name):
 p=OUT/name;b=p.read_bytes();return {'file':name,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(name):return json.loads((OUT/name).read_text())
d=read('deliver-final-receipt.json');assert d['ok']
assert bind('framework-final.archify.json')['sha256']==d['specification']['sha256']
assert bind('native-final.html')['sha256']==d['artifact']['sha256']
b=read('browser-final-receipt.json');r=read('reference-browser-receipt.json');dom=read('reference-dom-check.json')
assert b['artifact']['sha256']==d['artifact']['sha256']
assert r['artifact']['sha256']==bind('framework.html')['sha256']
assert dom['artifact']['sha256']==bind('framework.html')['sha256']
assert read('validation-handoff.json')['ok']
# Same exact canonical receipt bytes; neither delivered native artifact nor receipts edited.
(OUT/'native-final.visual-check.json').write_bytes((OUT/'browser-final-receipt.json').read_bytes())
font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
reviewed=['review-overview.light.png','review-overview.dark.png',*[f'review-{p}.light.png' for p in ['data','plan','exec','measure','stats']],
'native-final.visual-check.1440x900.light.png','native-final.visual-check.2048x1320.dark.png','native-review-overview.light.png',
'reference.browser.2048x1320.light.png','reference.browser.1440x900.dark.png','reference.browser.phase.measure.light.png','reference.browser.phase.measure.dark.png','reference.browser.phase.plan.dark.png','reference.browser.phase.stats.dark.png']
unique=[]
for i in dom['issues']:
 q={k:v for k,v in i.items() if k!='theme'}
 if q not in unique:unique.append(q)
review={'reviewer':'Codex image-capable visual inspection','time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'correction_rounds':2,'reviewed_images':[bind(x) for x in reviewed],
'native':{'artifact':bind('native-final.html'),'visual_review':'failed','browser_evidence':'failed','reason':'详细纵向图不能首屏容纳，右侧/下方存在明显空白；未缩小字体、隐藏溢出或改变已交付 HTML。'},
'reference':{'artifact':bind('framework.html'),'visual_review':'failed','browser_evidence':'passed','browser_scope':'8 viewport/theme measurements, full captures, search/dialog/theme/export/scroll-end; allows vertical page scroll','rendered_structure':'failed','unresolved':unique,
'positive_observations':['明暗主题与中文字体正常，无缺字方框','阶段标题层次清晰，右侧说明框对齐且无裁切','46 节点 / 51 边稳定 ID 与原生模型一致，说明框不参与拓扑','节点不重叠；正交路径端点方向正常，未穿不相关节点','条件 Query/Streaming 有虚线/斜纹和请求且支持标记','五阶段完整导出，2180×3435 PNG 与 SVG viewBox 相符','局部编解码展开标明父节点 formal，未暗示二次 benchmark'],
'limitations':['Layer 4 三处边说明底框遮线/相交，明暗主题重复发现；两轮修正上限后保留并报告','图内三种可比性键用 Semantic / Execution / Resource 缩写，完整准确键名见 source-evidence.md','最小 16 px SVG 明细在 1440 px 窗口投影约 10.57 px；完整 PNG 保留 2180 px 宽，可放大阅读']}}
(OUT/'visual-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
md=['# 最终视觉审查','', '本记录基于图像工具实际打开最终导出图、真实浏览器完整截图与阶段截图。自动验证不替代视觉审查。','',
'`correction_rounds: 2`。未开展第三轮视觉修改；节点交互修复仅校正 SVG DOM 属性，不改变展示几何。','',
'## 推荐参考风格长幅图','', '`visual_review: failed`；窗口与交互专项 `browser_evidence: passed`。八组窗口/主题无横向溢出，允许普通页面纵向滚动。精细 DOM 检查为 `failed`，不能以窗口专项通过代替整体视觉合格。','']
md += ['- '+t for t in review['reference']['positive_observations']]
md += ['','未解决的三处具体问题（两主题各发现一次）：','']
for u in unique:md.append('- `'+u['kind']+'`：'+json.dumps(u,ensure_ascii=False))
md += ['','## 原生 Archify 文件','', '`validation: 9/9 showcase, 0 errors, 0 warnings`；`browser_evidence: failed`；`visual_review: failed`。','',
'原生 Viewer 的首屏只展示上部，纵向 scrollHeight 为 7083–7489 px，所有四种桌面尺寸均超过窗口高度。图可正常滚动，但这不满足原生首屏契约。实际截图还显示较多空白；原生静态导出完整保留此布局。浏览器专项中横向容纳、readability、viewer chrome 和四张截图采集均通过。','',
'## 图像与导出来源','', '参考风格 SVG：独立展示 renderer 从 semantic-model.json 构建；PNG：rsvg-convert 独立静态渲染。原生 SVG：从不变 native-final.html 提取并解析 classic theme CSS；PNG：rsvg-convert。均不是通过 Viewer 原生导出按钮操作所得。浏览器截图由现有 Chromium/Playwright 或 Archify visual-check 实拍。','',
'支持中文的实际字体：`'+font+'`。没有安装字体、浏览器或更新 Skill。','',
'详细截图指纹与审查范围见 visual-review.json；八组原生补测见 native-browser-supplement.json，补测不改变 canonical browser-final-receipt.json 的 failed 状态。']
(OUT/'visual-review.md').write_text('\n'.join(md)+'\n')
# Contact sheets contain thumbnails of existing captures, not new browser evidence.
for kind,names in [('native',[c['file'] for c in b['captures']['screenshots']]),('reference',[c['file'] for c in r['captures']])]:
 thumbs=[]
 for name in names:
  im=Image.open(OUT/name).convert('RGB');im.thumbnail((580,920));thumbs.append((name,im.copy()))
 rowh=max(im.height for _,im in thumbs)+40
 sheet=Image.new('RGB',(1200,rowh*2),'#e6ecf1');draw=ImageDraw.Draw(sheet);fnt=ImageFont.truetype(font,16)
 for k,(name,im) in enumerate(thumbs):
  x=(k%2)*600+10;y=(k//2)*rowh+10;draw.text((x,y),name,fill='#1d2933',font=fnt);sheet.paste(im,(x,y+30))
 sheet.save(OUT/f'{kind}-contact-sheet.png')
links=lambda f:f'[{f}]({ROOT/"docs/archify-five-layer-reference"/f})'
readme=f'''# 五层运行框架与数据流图

推荐阅读 {links('framework.html')}；完整图为 {links('framework.light.png')}（2180 × 3435）和 {links('framework.light.svg')}。此版本复现参考图的三列与五层颜色，但仍有三处 Layer 4 边标签底框遮线/相交，因此整体视觉审查 **failed**，不声称所有验收项通过。

diagram_type 为 **architecture schema v1**。详细五层、自由分区和完整对象展开适合该类型；未把 architecture schema_version 伪写为 2。原生规范只使用安装版支持字段；每层色带、左标题、右注释与菱形属于独立的派生展示，非原生 schema 能力。

- 编辑语义：{links('semantic-model.json')}。
- 编辑原生规范：{links('framework-final.archify.json')}。
- 编辑展示位置：{links('reference-layout.json')} / {links('render_reference.py')}。
- 原生交互 HTML：{links('native-final.html')}。
- 完整源码证据：{links('source-evidence.md')} / {links('source-evidence.json')}，覆盖 46 节点、51 有向边、72 个当前工作区文件指纹。
- 最终原生校验：{links('validation-handoff.json')}；交付：{links('deliver-final-receipt.json')}。
- 原生浏览器：{links('browser-final-receipt.json')} / {links('native-final.visual-check.html')} / {links('native-contact-sheet.png')}。
- 参考版浏览器：{links('reference-browser-receipt.json')} / {links('reference-contact-sheet.png')} / `reference.browser.phase.*.png`。
- 参考版几何：{links('reference-structure-check.json')}；渲染后的 DOM：{links('reference-dom-check.json')}。
- 视觉审查：{links('visual-review.md')} / {links('visual-review.json')}。
- 完整文件哈希与范围：{links('handoff-receipt.json')}。

| 范围 | 结果 |
| --- | --- |
| 原生 showcase / deliver | 9/9；composition 0 errors / 0 warnings；退出码 0 |
| 原生 browser_evidence | failed：4 种尺寸首屏纵向溢出；明暗补测同样失败 |
| 原生 visual_review | failed：首屏与空白不满足目标 |
| 参考版语义/拓扑一致性 | passed：46 个节点和 51 条有向边（含稳定 ID）一致；注释不加入拓扑 |
| 参考版静态几何 | passed：节点、正交路径、端口与 annotation capacity 检查 |
| 参考版窗口/交互浏览器 | passed：8/8，无横向溢出，允许页面纵向滚动 |
| 参考版渲染后文字/路径检查 | failed：三处 label mask/label box 问题，两主题各一次 |
| 参考版 visual_review | failed：未忽略上述文字/路径问题 |
| correction_rounds | 2 |

原生已验收 HTML 字节保持不变，派生版没有沿用它的 SHA 或 9/9 回执。两个版本均由当前源码核对形成；图片只作为视觉参考，其文字未作为指令执行。未修改 benchmark 源码、原有图或安装的 Skill。

PNG/SVG 均为独立静态渲染/提取，非 Viewer 原生导出。全部输出保留完整长图；没有 hidden overflow、内部隐藏滚动区或字号缩小伪造首屏通过。原生导出另存 `native.light.svg/png`、`native.dark.svg/png`；参考版深色另存 `framework.dark.svg/png`。

图内三级键使用缩写，完整名称是 ExecutionPathHash、SemanticComparabilityKey、ExecutionComparabilityKey、ResourceProfileKey；完整源码位置见 evidence。额外时序解释（非直接调用边、最终内循环对象提供正确性证据、Rate-controlled gate 延后）也见 evidence。

`framework.archify.json`、`native.html` 及未带 final/handoff 的旧回执是候选审计材料，不能替代当前版本。
'''
(OUT/'README.md').write_text(readme)
main=['framework-final.archify.json','semantic-model.json','native-final.html','framework.html','reference-layout.json','framework.light.svg','framework.dark.svg','framework.light.png','framework.dark.png','native.light.svg','native.dark.svg','native.light.png','native.dark.png','source-evidence.md','source-evidence.json','validation-handoff.json','deliver-final-receipt.json','browser-final-receipt.json','native-browser-supplement.json','reference-browser-receipt.json','reference-structure-check.json','reference-dom-check.json','visual-review.md','visual-review.json','README.md','native-contact-sheet.png','reference-contact-sheet.png']
handoff={'diagram_type':'architecture','schema_version':1,'native':{'output':str(OUT/'native-final.html'),'specification_sha256':d['specification']['sha256'],'specification_bytes':d['specification']['bytes'],'artifact_sha256':d['artifact']['sha256'],'artifact_bytes':d['artifact']['bytes'],'validation':'9/9 showcase, 0 errors, 0 warnings','validation_exit_code':0,'deliver_exit_code':0,'browser_evidence':'failed','browser_exit_code':1,'visual_review':'failed','limitation':'first-screen viewport overflow; conspicuous whitespace'},
'reference':{'output':str(OUT/'framework.html'),'artifact':bind('framework.html'),'browser_evidence':'passed','browser_exit_code':0,'browser_scope':'long form document scrolling; no horizontal overflow; 4 sizes x 2 themes; interactions','semantic_consistency':'passed','static_geometry':'passed','rendered_dom_geometry':'failed','visual_review':'failed','unresolved_distinct_issues':unique,'does_not_inherit_native_acceptance':True},
'correction_rounds':2,'overall_acceptance':'incomplete: disclosed native viewport and reference label collision failures','export_origin':'independent SVG construction/extraction + rsvg-convert; not Viewer-native export',
'font':{'path':font,'sha256':hashlib.sha256(Path(font).read_bytes()).hexdigest()},'artifacts':[bind(x) for x in main],'reviewed_images':review['reviewed_images']}
(OUT/'handoff-receipt.json').write_text(json.dumps(handoff,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'native_sha256':d['artifact']['sha256'],'reference_sha256':bind('framework.html')['sha256'],'source_files':read('source-evidence.json')['counts'],'visual_review':'failed','correction_rounds':2}))
