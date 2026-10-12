# 五层运行框架与数据流图（2026-10-12 更新）

阅读 [完整框架 HTML](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.html)；[浅色 SVG](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.light.svg) / [PNG](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.light.png)，另有 [深色 SVG](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.dark.svg) / [PNG](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.dark.png)。在原框架内补充 V3.2，保留五层结构与 Legacy 详细路径。当前图为 64 节点、69 条有向关系，2180 × 4815。

[逐层更新与原图复核](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/update-notes-20261012.md) 说明源码变化、四条执行路径、真实测量/恢复/分析口径及当前运行资格边界。点击图中节点可查看源码函数；支持搜索、主题切换、静态图下载和页面纵向滚动。

- 语义：[semantic-model.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/semantic-model.json)；展示：[render_reference.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/render_reference.py) / [reference-layout.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-layout.json)。
- 源码依据：[source-evidence.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/source-evidence.md) / [source-evidence.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/source-evidence.json)，119 个当前工作区文件指纹。
- 原框架检查：[reference-structure-check.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-structure-check.json) / [reference-dom-check.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-dom-check.json) / [reference-browser-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-browser-receipt.json)；五层明暗截图为 `reference.browser.phase.*.png`。
- 视觉检查：[visual-review.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/visual-review.md) / [visual-review.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/visual-review.json)；最终指纹：[handoff-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/handoff-receipt.json)。
- 附带原生规范：[framework-updated.archify.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework-updated.archify.json) / [native-updated.html](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/native-updated.html)；[validation-updated.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/validation-updated.json) / [deliver-updated-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/deliver-updated-receipt.json) / [browser-updated-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/browser-updated-receipt.json)。
- 更新前原字节：[history/pre-update-20261012/framework.html](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/history/pre-update-20261012/framework.html) / [history/pre-update-20261012/snapshot.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/history/pre-update-20261012/snapshot.json)。

| 验证范围 | 结果 |
| --- | --- |
| 原框架语义、静态几何、DOM 文字/标签/说明 | passed |
| 原框架 Chromium 四尺寸 × 明暗两主题及交互 | passed；无横向溢出，正常纵向滚动 |
| 原框架实际图像检查 | passed；五层两主题已检查，旧遮线修复 |
| 附带原生校验与交付 | 9/9 standard，0 errors / 15 warnings；非 showcase |
| 附带原生 browser / visual | failed；默认明细偏小、首屏纵向溢出，完整阅读使用 framework.html |

Archify architecture schema v1 用于原生拓扑；五层色带、左标题、右注释、菱形、完整说明和跨线桥属于独立展示。原框架与原生查看器分别绑定文件指纹，互不继承检查结论。图只表达源码实现与依赖，当前资格与失败保留；本次未执行 Benchmark。

重建顺序：用项目 Python 3.14 执行 `update_framework_20261012.py`、`render_reference.py`、`build_evidence.py`；运行浏览器检查与独立原生 validate/deliver，再检查图像并更新回执。当前目录中的 framework-final、native-final、旧 final/handoff 回执及旧 native 导出是历史材料，以 history 快照为准。
