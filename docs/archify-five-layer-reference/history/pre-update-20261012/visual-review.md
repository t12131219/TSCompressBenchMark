# 最终视觉审查

本记录基于图像工具实际打开最终导出图、真实浏览器完整截图与阶段截图。自动验证不替代视觉审查。

`correction_rounds: 2`。未开展第三轮视觉修改；节点交互修复仅校正 SVG DOM 属性，不改变展示几何。

## 推荐参考风格长幅图

`visual_review: failed`；窗口与交互专项 `browser_evidence: passed`。八组窗口/主题无横向溢出，允许普通页面纵向滚动。精细 DOM 检查为 `failed`，不能以窗口专项通过代替整体视觉合格。

- 明暗主题与中文字体正常，无缺字方框
- 阶段标题层次清晰，右侧说明框对齐且无裁切
- 46 节点 / 51 边稳定 ID 与原生模型一致，说明框不参与拓扑
- 节点不重叠；正交路径端点方向正常，未穿不相关节点
- 条件 Query/Streaming 有虚线/斜纹和请求且支持标记
- 五阶段完整导出，2180×3435 PNG 与 SVG viewBox 相符
- 局部编解码展开标明父节点 formal，未暗示二次 benchmark

未解决的三处具体问题（两主题各发现一次）：

- `label-masks-unrelated-route`：{"kind": "label-masks-unrelated-route", "label": "workloads--query", "edge": "workloads--raw"}
- `label-masks-unrelated-route`：{"kind": "label-masks-unrelated-route", "label": "query--raw", "edge": "workloads--raw"}
- `edge-label-overlap`：{"kind": "edge-label-overlap", "labels": ["workloads--raw", "streaming--raw"]}

## 原生 Archify 文件

`validation: 9/9 showcase, 0 errors, 0 warnings`；`browser_evidence: failed`；`visual_review: failed`。

原生 Viewer 的首屏只展示上部，纵向 scrollHeight 为 7083–7489 px，所有四种桌面尺寸均超过窗口高度。图可正常滚动，但这不满足原生首屏契约。实际截图还显示较多空白；原生静态导出完整保留此布局。浏览器专项中横向容纳、readability、viewer chrome 和四张截图采集均通过。

## 图像与导出来源

参考风格 SVG：独立展示 renderer 从 semantic-model.json 构建；PNG：rsvg-convert 独立静态渲染。原生 SVG：从不变 native-final.html 提取并解析 classic theme CSS；PNG：rsvg-convert。均不是通过 Viewer 原生导出按钮操作所得。浏览器截图由现有 Chromium/Playwright 或 Archify visual-check 实拍。

支持中文的实际字体：`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`。没有安装字体、浏览器或更新 Skill。

详细截图指纹与审查范围见 visual-review.json；八组原生补测见 native-browser-supplement.json，补测不改变 canonical browser-final-receipt.json 的 failed 状态。
