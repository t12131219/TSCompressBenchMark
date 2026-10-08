# 五层运行框架与数据流图

推荐阅读 [framework.html](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.html)；完整图为 [framework.light.png](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.light.png)（2180 × 3435）和 [framework.light.svg](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.light.svg)。此版本复现参考图的三列与五层颜色，但仍有三处 Layer 4 边标签底框遮线/相交，因此整体视觉审查 **failed**，不声称所有验收项通过。

diagram_type 为 **architecture schema v1**。详细五层、自由分区和完整对象展开适合该类型；未把 architecture schema_version 伪写为 2。原生规范只使用安装版支持字段；每层色带、左标题、右注释与菱形属于独立的派生展示，非原生 schema 能力。

- 编辑语义：[semantic-model.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/semantic-model.json)。
- 编辑原生规范：[framework-final.archify.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework-final.archify.json)。
- 编辑展示位置：[reference-layout.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-layout.json) / [render_reference.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/render_reference.py)。
- 原生交互 HTML：[native-final.html](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/native-final.html)。
- 完整源码证据：[source-evidence.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/source-evidence.md) / [source-evidence.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/source-evidence.json)，覆盖 46 节点、51 有向边、72 个当前工作区文件指纹。
- 最终原生校验：[validation-handoff.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/validation-handoff.json)；交付：[deliver-final-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/deliver-final-receipt.json)。
- 原生浏览器：[browser-final-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/browser-final-receipt.json) / [native-final.visual-check.html](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/native-final.visual-check.html) / [native-contact-sheet.png](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/native-contact-sheet.png)。
- 参考版浏览器：[reference-browser-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-browser-receipt.json) / [reference-contact-sheet.png](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-contact-sheet.png) / `reference.browser.phase.*.png`。
- 参考版几何：[reference-structure-check.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-structure-check.json)；渲染后的 DOM：[reference-dom-check.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-dom-check.json)。
- 视觉审查：[visual-review.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/visual-review.md) / [visual-review.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/visual-review.json)。
- 完整文件哈希与范围：[handoff-receipt.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/handoff-receipt.json)。

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
