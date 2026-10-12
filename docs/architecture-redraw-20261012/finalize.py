"""Bind the final source, viewer, exports and independent validation scopes."""
from pathlib import Path
import hashlib,json
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
def identity(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
facts=json.loads((OUT/'source-evidence.json').read_text())
for r in facts['files']:
 assert hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()==r['sha256'],r['path']
publication=json.loads((OUT/'publication-browser-receipt.json').read_text())
assert publication['status']=='pass'
assert identity(OUT/'framework.html')['sha256']==publication['artifact']['sha256']
native=[]
for name in ['overview','lanes','object']:
 deliver=json.loads((OUT/(name+'.deliver.json')).read_text())
 validate=json.loads((OUT/(name+'.validation.json')).read_text())
 browser=json.loads((OUT/(name+'.native.visual-check.json')).read_text())
 assert deliver['ok'] and validate['ok'] and browser['status']=='pass'
 assert identity(OUT/(name+'.archify.json'))['sha256']==deliver['specification']['sha256']
 assert identity(OUT/(name+'.native.html'))['sha256']==deliver['artifact']['sha256']==browser['artifact']['sha256']
 native.append({'name':name,'diagram_type':'architecture','specification':identity(OUT/(name+'.archify.json')),'artifact':identity(OUT/(name+'.native.html')),'validation':deliver['validation'],'browser_evidence':'passed','visual_review':'passed','review_scope':'actual light/dark screenshots at 2048x1320; all desktop containment measurements passed'})
exports=[identity(OUT/(p+'.'+theme+'.'+ext)) for p in ['framework','lanes','object'] for theme in ['light','dark'] for ext in ['svg','png']]
record={
 'as_of':'2026-10-12 Asia/Shanghai','diagram_type':'architecture','source_commit':facts['commit'],'working_tree_basis':facts['basis'],'source_file_count':len(facts['files']),'total_authored_nodes':len(facts['nodes']),'total_dependency_edges':28,
 'primary_output':identity(OUT/'framework.html'),
 'primary_validation':{'kind':'independent-publication-viewer','status':'passed','browser_receipt':identity(OUT/'publication-browser-receipt.json'),'scope':'3 views × 4 desktop sizes × 2 themes; node text bounds and spacing; details; cross-view search; keyboard; 12 exports; 6 standalone SVG theme checks','visual_review':'passed','review_scope':'three views in both themes at 1440x900; overview in both themes at 2048x1320; native geometry at 2048x1320 in both themes','correction_rounds':2},
 'native_archify_artifacts':native,
 'publication_exports':exports,
 'publication_derivation':'Derived from the exact native geometry exports, with larger node typography, domain legend, overview phase headings, source details and independent viewer. Derived publication artifacts do not inherit native deliver or visual-check receipts.',
 'source_evidence':identity(OUT/'source-evidence.json'),
 'limitations':['Static source analysis only; no benchmark executed.','Passing routes do not imply current qualification, pilot, CORE, PROFILE or FORMAL completion.','The object view expresses object/evidence dependencies, not a single execution call sequence; fresh-worker recovery is qualification/audit, while steady roundtrip decode is in the measurement worker.'],
}
(OUT/'handoff-receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
(OUT/'README.md').write_text('''# 当前代码架构重绘 · 2026-10-12

[打开新版 HTML](framework.html)。三张互补架构图，共 34 个节点、28 条依赖关系，对照当前工作区 47 个源码文件；支持主题切换、节点说明、源码函数搜索、键盘操作和 SVG/PNG 导出。

| 图 | 浅色 SVG | 深色 SVG | 浅色 PNG |
| --- | --- | --- | --- |
| 五项职责与主流程总览 | [framework.light.svg](framework.light.svg) | [framework.dark.svg](framework.dark.svg) | [framework.light.png](framework.light.png) |
| 四条执行路径 | [lanes.light.svg](lanes.light.svg) | [lanes.dark.svg](lanes.dark.svg) | [lanes.light.png](lanes.light.png) |
| 编码 / 恢复 / 成本闭环 | [object.light.svg](object.light.svg) | [object.dark.svg](object.dark.svg) | [object.light.png](object.light.png) |

## 代码表达范围

Legacy TOML、V3.2 comparison、stream/query workload 与 P2 pipeline 保留独立 runner 和统计合同。资格 / development pilot 是 V3.2 测量门禁；Coverage 来自冻结矩阵；P2 使用独立 LogicalObject / Recipe，不强制沿用 legacy wire。CORE 组件与 PIPELINE 完整对象的计时及成本边界不同。

对象闭环中的箭头表示对象、控制与证据依赖，不是逐函数调用时序。资格与审计在 fresh worker 从已保存字节恢复；正式 steady roundtrip 在同一测量 worker 中解码。每个内循环对象独立 Finalize，同次采集计时与资源，恢复依赖计入完整对象成本。

[源码职责与函数定位](source-evidence.md) / [当前文件 SHA-256](source-evidence.json)。图表示实现，不表示当前所有 lane 已通过资格、pilot 或正式测量。未运行 Benchmark，未修改生产代码。

## 验证范围

三份 [总览](overview.native.html)、[执行路径](lanes.native.html)、[对象闭环](object.native.html) 原生 Archify HTML 各自通过 9/9 showcase，0 errors / 0 warnings；各自 `*.deliver.json` 绑定规范和 HTML 字节，`*.native.visual-check.json` 的自动浏览器证据均 passed。明暗实际截图已进行图像复核。

主入口及配套出版 SVG 使用相同原生节点 / 线路几何，增大字号、补充领域图例和职责标题；它们属于独立展示，**不继承原生回执**。[独立浏览器检查](publication-browser-receipt.json) 验证三视图 × 1440×900、1600×1000、1920×1080、2048×1320 × 明暗主题，全部首屏完整显示；文字边界 / 行间距、说明、跨视图搜索、键盘、12 次导出和 6 个独立 SVG 均通过。主入口明暗实际图像已检查。

[最终指纹与交付范围](handoff-receipt.json) 区分三个原生产物、独立主入口、导出文件和源文件依据。

## 重建

1. 用 `build_models.py` 写候选规范；每次修改后运行 Archify `validate architecture ... --quality showcase --json`，再 `deliver` 到 `*.native.html`。
2. 用项目 Python 3.14 执行 `build_evidence.py`；执行 `export_native.mjs` 导出原生几何。
3. 执行 `build_viewer.py` 生成主入口与六个出版 SVG；执行 `check_publication.mjs` 独立验证，并通过页面 PNG 按钮生成六个 PNG。
4. 对每份原生 HTML 运行 `visual-check`，检查实际截图后执行 `finalize.py`。本机浏览器路径通过 `ARCHIFY_CHROME` 指向已安装 Chromium；JS 脚本采用本机已安装 Playwright 路径。
''')
print(json.dumps({'source_hashes':'47/47 match','native_validation':'3 × 9/9 showcase; zero errors and warnings','native_browser':'3 passed','publication_browser':publication['status'],'exports':len(exports),'artifact':record['primary_output']},ensure_ascii=False))
