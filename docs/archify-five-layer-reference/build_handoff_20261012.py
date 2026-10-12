"""Bind the updated reference and its independent checks; preserve historical receipts."""
from pathlib import Path
import datetime
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
def read(name):
    return json.loads((OUT / name).read_text())
def binding(name):
    data = (OUT / name).read_bytes()
    return {'file': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
def link(name, label=None):
    return f'[{label or name}]({OUT / name})'

model = read('semantic-model.json')
source = read('source-evidence.json')
geometry = read('reference-structure-check.json')
browser = read('reference-browser-receipt.json')
dom = read('reference-dom-check.json')
delivery = read('deliver-updated-receipt.json')
native_browser = read('browser-updated-receipt.json')
assert geometry['status'] == browser['status'] == dom['status'] == 'pass'
assert delivery['ok'] and delivery['validation']['compositionProfile'] == 'standard'
assert len(model['nodes']) == 64 and len(model['edges']) == 69
assert browser['artifact']['sha256'] == binding('framework.html')['sha256'] == dom['artifact']['sha256']
assert delivery['artifact']['sha256'] == binding('native-updated.html')['sha256'] == native_browser['artifact']['sha256']
assert delivery['specification']['sha256'] == binding('framework-updated.archify.json')['sha256']

phases = ['data', 'plan', 'exec', 'measure', 'stats']
comparisons = []
for phase in phases:
    name = f'review-current-compare-{phase}.png'
    images = [Image.open(OUT / f'reference.browser.phase.{phase}.{t}.png') for t in ['light', 'dark']]
    images = [im.resize((1000, round(im.height * 1000 / im.width))) for im in images]
    sheet = Image.new('RGB', (2020, images[0].height + 36), 'white')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 20)
    draw.text((12,4), phase + ' / Light', font=font, fill='black')
    draw.text((1022,4), phase + ' / Dark', font=font, fill='black')
    sheet.paste(images[0], (0,36)); sheet.paste(images[1], (1020,36))
    sheet.save(OUT / name)
    comparisons.append(binding(name))
reviewed = [binding(f'reference.browser.phase.{p}.{t}.png') for p in phases for t in ['light', 'dark']]
native_reviewed = [binding('native-updated.visual-check.2048x1320.light.png'), binding('native-updated.visual-check.1440x900.dark.png')]
review = {
    'reviewer': 'Codex image-capable inspection',
    'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'correction_rounds': 2,
    'reference': {
        'artifact': binding('framework.html'), 'visual_review': 'passed',
        'review_scope': 'Five phase comparisons, both themes, from exact artifact-bound Chromium screenshots; long-form document scrolling',
        'reviewed_images': reviewed, 'reviewed_comparisons': comparisons,
        'positive_observations': [
            '五层色带、左标题和右侧说明框保留，V3.2 补充区明确可见。',
            '中文字体与明暗对比正常，节点文字和说明均完整。',
            'Layer 4 旧有三处边标签遮线已修复，新增说明与标签不重叠。',
            '交叉线使用圆弧桥明确表示不相连，无共用模糊走廊。',
            'Legacy 与 V3.2 的合同、测量与统计口径分别标注。',
            'P2 对象展开与同次测量职责明确，未画成第二轮 benchmark。',
        ],
        'limitations': [
            '完整长幅参考图需纵向滚动；不声称首屏容纳五层。',
            '在 1440px 宽窗口中最小节点明细约 10.57px；完整 SVG/PNG 可放大阅读。',
            '图表示源码架构与依赖；当前 P2 pilot 不合格、其他 lane 缺口仍保留。',
        ], 'unresolved': [],
    },
    'native': {
        'artifact': binding('native-updated.html'), 'visual_review': 'failed',
        'reviewed_images': native_reviewed,
        'reason': '原生通用查看器的默认明细字小，首屏不能容纳长图；仅作为可缩放拓扑附件。',
        'browser_evidence': 'failed',
    },
}
write_json('visual-review.json', review)

notes = f'''# 2026-10-12：在原五层框架内更新

已直接更新 {link('framework.html', '完整框架 HTML')}，并同步 {link('framework.light.svg', '浅色 SVG')} / {link('framework.dark.svg', '深色 SVG')} 及 PNG。保留五层色带、左侧职责、右侧输出/约束、原有详细框线和节点交互；在每层增加 V3.2 补充区。图从 46 节点 / 51 条有向关系扩展为 **64 节点 / 69 条有向关系**，画布为 **2180 × 4815**。

## 原图是否正确

原来的“数据准备 → 能力与配置 → 执行与验证 → 性能测评 → 统计分析与报告”职责划分仍然正确。原图主要描述 Legacy TOML / runner / statistics 路径，不能完整代表当前 V3.2 的 comparison、workload、P2 三条执行路径。保留 Legacy 的统计口径，并补上新合同和门禁，才符合当前源码。

本次按当前工作区文件核对，包含已有的未提交 analysis.py 修改。{source['counts']['files']} 个源码、schema、配置、测试或审计文件已记录指纹与符号定位。旧证据的 72 个文件中，31 个指纹变化、1 个文件已移除；指纹漂移本身不等于图义全部错误，但旧回执不能作为当前源码证明。

| 原层 | 本次补充 / 修正 |
| --- | --- |
| 数据准备 | 内容 SHA、DatasetID、父级 lineage；显式 f32 / uint8 / ND / validity 派生；P2 LogicalObjectSchema、轴/单位/channel collection。P2 不强制经过 legacy canonical wire。 |
| 能力与配置 | 测量前的 experiment_decision、Task / Contract / Group / Corpus / ConfigMap / Expected、Protocol / AnalysisPolicy；成员去重、CORE 两方法与两独立真实来源、实际输入公共投影、作业/源码闭包/环境/调度冻结。 |
| 执行与验证 | 原域正确性与保存字节的独立恢复；与评价对象分离的 development pilot；comparison / workload / P2 分 lane 执行；P2 全 T / V / mask、mixed / ND / time_axis、子流/块/RAW_TAIL 与付费恢复依赖。Legacy 预热在每个测量 worker 内，固定门槛不证明统计稳态。 |
| 性能测评 | 完整对象 steady/cold PIPELINE；共同 native API STEADY_PROCESS CORE；ResourceLease、父进程线程观测与 wall 预算；持久 trials / artifacts / STARTED / events。未知 STARTED 不自动重测，P2 有持久预算预留和提交事件链。测量框是同一试次的职责投影。 |
| 统计与报告 | 冻结计划与原始证据的只读重核；均值时间比与真实 Schedule block 配对 bootstrap、多重区间和精度；原域质量、FinalBits、公共投影、全矩阵 Coverage；独立报告和辅助验收。Legacy median / 三级键保留原口径。 |

Rate/Summary 已改为“需要专用 task validator；当前无活动算法或正式比较组”，删除旧“actual rate gate 延后”的表述。恢复信息与 side info 纳入完整对象成本；每个内循环对象独立 Finalize，最后一个对象提供公共正确性/计量证据。

## 如何阅读数据流

上部原有节点继续表示 Legacy 路径；各层下部 V3.2 补充区依次表达输入身份、事前合同、资格/pilot/执行、同次测量/持久证据、只读分析/验收。实线表达处理或数据主依赖，虚线表达条件调度、证据依赖、职责投影或对象展开；圆弧跨线表示不相连。箭头不是逐函数直接调用图。

comparison、workload、P2 使用各自 runner 和协议；补充框是职责概览，不表示四条路径共享一个通用实现。SOURCE_PARITY、N/G/CAP、FORMAL、profile completion 与辅助审计分别验收，任何一种通过都不转授其他资格。

图明确保留当前审计边界：entropy 为 CORE_COMPLETE，stream / query-warm / query-fresh 为 PROFILE_COMPLETE；P2 development pilot 不合格，其他 comparison lane 仍有资源、预期不支持、停止或 cold 汇总缺口。实现流程存在不等于当前所有 lane 已通过。依据为 [当前闭包与 FORMAL 验证]({OUT.parents[1] / 'docs/audits/20261011_closure_formal_verification/README.md'})。

## 检查与交付范围

| 对象 | 结果 |
| --- | --- |
| 原框架 HTML 静态几何 | passed；64 节点 / 69 有向关系一致，节点/标签/端口/正交线路检查通过，无模糊共享走廊 |
| 原框架 HTML 真实 Chromium | passed；1440×900、1600×1000、1920×1080、2048×1320 × 明暗两主题，无横向溢出，允许正常纵向滚动 |
| 原框架 HTML 交互与 DOM | passed；搜索、旧/新节点说明、主题、导出链接、末层可达；节点文字、边标签、补充说明无遮挡 |
| 原框架 HTML 图像检查 | passed；五层明暗截图实际检查；旧 Layer 4 三处遮线已修复 |
| 独立原生规范 / deliver | 9/9 **standard**，0 errors / 15 warnings；不是 showcase 的 0-warning 验收 |
| 附带原生查看器 | browser_evidence / visual_review 均 failed：默认明细小于 6px，首屏纵向溢出；原框架的通过结论不继承它的回执 |

推荐阅读原路径 framework.html。附带 {link('native-updated.html', '原生缩放查看器')} 仅提供简要拓扑，完整细节以五层框架为准。独立 SVG 由展示渲染器生成，PNG 由 rsvg-convert 转换，并非 Viewer 原生导出。本次只更新图与文档，没有运行 Benchmark，没有修改其生产源码。

{link('source-evidence.md', '完整源码定位')} · {link('handoff-receipt.json', '文件指纹与检查回执')} · {link('visual-review.md', '视觉检查记录')}。

原图及全部 91 个旧文件已保存在 {link('history/pre-update-20261012/framework.html', '更新前 HTML')} 所在目录，{link('history/pre-update-20261012/snapshot.json', '快照指纹')} 可核对原字节。仍留在当前目录的 native-final、framework-final、旧 final/handoff 回执、旧 native 导出和旧 overview 截图均属于历史材料。
'''
(OUT / 'update-notes-20261012.md').write_text(notes)

readme = f'''# 五层运行框架与数据流图（2026-10-12 更新）

阅读 {link('framework.html', '完整框架 HTML')}；{link('framework.light.svg', '浅色 SVG')} / {link('framework.light.png', 'PNG')}，另有 {link('framework.dark.svg', '深色 SVG')} / {link('framework.dark.png', 'PNG')}。在原框架内补充 V3.2，保留五层结构与 Legacy 详细路径。当前图为 64 节点、69 条有向关系，2180 × 4815。

{link('update-notes-20261012.md', '逐层更新与原图复核')} 说明源码变化、四条执行路径、真实测量/恢复/分析口径及当前运行资格边界。点击图中节点可查看源码函数；支持搜索、主题切换、静态图下载和页面纵向滚动。

- 语义：{link('semantic-model.json')}；展示：{link('render_reference.py')} / {link('reference-layout.json')}。
- 源码依据：{link('source-evidence.md')} / {link('source-evidence.json')}，119 个当前工作区文件指纹。
- 原框架检查：{link('reference-structure-check.json')} / {link('reference-dom-check.json')} / {link('reference-browser-receipt.json')}；五层明暗截图为 `reference.browser.phase.*.png`。
- 视觉检查：{link('visual-review.md')} / {link('visual-review.json')}；最终指纹：{link('handoff-receipt.json')}。
- 附带原生规范：{link('framework-updated.archify.json')} / {link('native-updated.html')}；{link('validation-updated.json')} / {link('deliver-updated-receipt.json')} / {link('browser-updated-receipt.json')}。
- 更新前原字节：{link('history/pre-update-20261012/framework.html')} / {link('history/pre-update-20261012/snapshot.json')}。

| 验证范围 | 结果 |
| --- | --- |
| 原框架语义、静态几何、DOM 文字/标签/说明 | passed |
| 原框架 Chromium 四尺寸 × 明暗两主题及交互 | passed；无横向溢出，正常纵向滚动 |
| 原框架实际图像检查 | passed；五层两主题已检查，旧遮线修复 |
| 附带原生校验与交付 | 9/9 standard，0 errors / 15 warnings；非 showcase |
| 附带原生 browser / visual | failed；默认明细偏小、首屏纵向溢出，完整阅读使用 framework.html |

Archify architecture schema v1 用于原生拓扑；五层色带、左标题、右注释、菱形、完整说明和跨线桥属于独立展示。原框架与原生查看器分别绑定文件指纹，互不继承检查结论。图只表达源码实现与依赖，当前资格与失败保留；本次未执行 Benchmark。

重建顺序：用项目 Python 3.14 执行 `update_framework_20261012.py`、`render_reference.py`、`build_evidence.py`；运行浏览器检查与独立原生 validate/deliver，再检查图像并更新回执。当前目录中的 framework-final、native-final、旧 final/handoff 回执及旧 native 导出是历史材料，以 history 快照为准。
'''
(OUT / 'README.md').write_text(readme)

visual_md = f'''# 2026-10-12 视觉检查

主交付 {link('framework.html')} 的 `visual_review: passed`。图像检查基于最终 HTML 绑定的 Chromium 截图，每层浅色/深色各一份，并以五张主题对照图检查。静态几何、浏览器和 DOM 检查是各自独立的自动证据。

已确认五层层次、中文字体、明暗对比、节点文字和右侧说明完整；原 Layer 4 三处遮线已修复，新增标题、局部生命周期说明与边标签不重叠。正交线交叉使用桥，明确不相连。长幅阅读需要正常页面纵向滚动，不声称首屏容纳全图。修正轮次：2。

完整图 2180×4815；最窄已测窗口中 16px 明细投影约 10.57px。当前 P2 pilot 不合格和其他 lane 缺口没有被图示流程掩盖。

附带 native-updated.html 的 `visual_review: failed`，其 2048×1320 浅色及 1440×900 深色截图已实际检查：默认明细过小且长图无法首屏容纳；自动 visual-check 同样 failed。原框架的通过不适用于此附件，也不冒称原生 showcase 通过。

{link('visual-review.json', '精确图像指纹与审查记录')} · {link('reference-browser-receipt.json', '主图浏览器证据')} · {link('reference-dom-check.json', '主图 DOM 检查')} · {link('browser-updated-receipt.json', '原生自动浏览器结果')}。
'''
(OUT / 'visual-review.md').write_text(visual_md)

artifact_names = [
    'framework.html', 'framework.light.svg', 'framework.dark.svg', 'framework.light.png', 'framework.dark.png',
    'semantic-model.json', 'reference-layout.json', 'source-evidence.json', 'source-evidence.md',
    'reference-structure-check.json', 'reference-browser-receipt.json', 'reference-dom-check.json',
    'framework-updated.archify.json', 'native-updated.html', 'validation-updated.json', 'deliver-updated-receipt.json',
    'browser-updated-receipt.json', 'visual-review.json', 'visual-review.md', 'README.md', 'update-notes-20261012.md',
    'reference-contact-sheet.png', 'update_framework_20261012.py', 'render_reference.py', 'build_evidence.py',
    'browser_check.mjs', 'inspect_final.mjs', 'build_handoff_20261012.py',
]
handoff = {
    'diagram_type': 'architecture', 'schema_version': 1, 'updated_at': '2026-10-12',
    'user_requested_output': str(OUT / 'framework.html'),
    'reference': {
        'output': str(OUT / 'framework.html'), 'artifact': binding('framework.html'),
        'semantic_model': binding('semantic-model.json'), 'counts': source['counts'], 'canvas': [2180,4815],
        'semantic_consistency': 'passed', 'static_geometry': 'passed', 'rendered_dom_geometry': 'passed',
        'browser_evidence': 'passed', 'browser_exit_code': 0, 'visual_review': 'passed',
        'browser_scope': '4 desktop sizes x 2 themes; long-form vertical document scrolling; horizontal overflow forbidden',
        'interactions': browser['interactions'], 'crossing_bridges': len(geometry['crossingBridges']),
        'unresolved_distinct_issues': [], 'does_not_inherit_native_acceptance': True,
    },
    'native': {
        'output': str(OUT / 'native-updated.html'),
        'specification_sha256': delivery['specification']['sha256'],
        'artifact_sha256': delivery['artifact']['sha256'], 'validation': delivery['validation'],
        'validation_exit_code': 0, 'deliver_exit_code': 0,
        'browser_evidence': 'failed', 'browser_exit_code': 1, 'visual_review': 'failed',
        'limitation': 'Default native context text below 6px; full long-form topology exceeds first-screen viewports',
        'role': 'Optional scalable topology companion, not the requested five-layer reference presentation',
    },
    'correction_rounds': 2,
    'overall_acceptance': 'Requested in-place reference update passed; optional native default first-screen review failed and disclosed',
    'export_origin': 'Independent reference SVG renderer + rsvg-convert PNG; not Viewer-native export',
    'source_basis': 'Current working tree, including pre-existing user changes; no benchmark execution or production source edits',
    'historical_snapshot': str(OUT / 'history/pre-update-20261012/snapshot.json'),
    'artifacts': [binding(f) for f in artifact_names], 'reviewed_images': reviewed + native_reviewed,
}
write_json('handoff-receipt.json', handoff)
print(json.dumps({'reference': handoff['reference']['artifact'], 'source_counts': source['counts'], 'native_validation': delivery['validation'], 'native_browser': native_browser['status']}, ensure_ascii=False))
