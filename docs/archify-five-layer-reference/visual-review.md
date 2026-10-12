# 2026-10-12 视觉检查

主交付 [framework.html](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.html) 的 `visual_review: passed`。图像检查基于最终 HTML 绑定的 Chromium 截图，每层浅色/深色各一份，并以五张主题对照图检查。静态几何、浏览器和 DOM 检查是各自独立的自动证据。

已确认五层层次、中文字体、明暗对比、节点文字和右侧说明完整；原 Layer 4 三处遮线已修复，新增标题、局部生命周期说明与边标签不重叠。正交线交叉使用桥，明确不相连。长幅阅读需要正常页面纵向滚动，不声称首屏容纳全图。修正轮次：2。

完整图 2180×4815；最窄已测窗口中 16px 明细投影约 10.57px。当前 P2 pilot 不合格和其他 lane 缺口没有被图示流程掩盖。

附带 native-updated.html 的 `visual_review: failed`，其 2048×1320 浅色及 1440×900 深色截图已实际检查：默认明细过小且长图无法首屏容纳；自动 visual-check 同样 failed。原框架的通过不适用于此附件，也不冒称原生 showcase 通过。

[精确图像指纹与审查记录](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/visual-review.json) · [主图浏览器证据](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-browser-receipt.json) · [主图 DOM 检查](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/reference-dom-check.json) · [原生自动浏览器结果](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/browser-updated-receipt.json)。
