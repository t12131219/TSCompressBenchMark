# 当前项目数据流程与旧图复核

- [交互框线图](framework.html)：当前工作树的 dataflow 概览，12 节点、11 条依赖边。
- [浅色 SVG](framework.light.svg) / [PNG](framework.light.png)；[深色 SVG](framework.dark.svg) / [PNG](framework.dark.png)。SVG 主题变体仅为原生自适应导出的根元素增加 `data-theme`；[原始自适应 SVG](framework.svg) 单独保留。
- [逐层复核说明](review.md)：当前五阶段、四条执行路径、旧图准确部分与十项更新/澄清。
- [源码定位](source-evidence.md) / [指纹及拓扑](source-evidence.json)：27 个源码文件、12 节点；旧图 72 项证据中 32 项指纹漂移。
- [交付与视觉回执](handoff-receipt.json)：精确 specification/artifact SHA-256、导出身份和验收范围。

几何校验 9/9，0 errors / 0 warnings；实际 Chromium 检查 1440×900、1600×1000、1920×1080、2048×1320 均完整显示，明暗主题截图和视觉检查通过。原生主题/节点点击和导出检查通过，独立 SVG 12 节点与文字边界通过。

图中的资格和 pilot 显示通过路线，不宣称当前全部 lane 均通过。P2 使用独立逻辑原对象而非强制沿用 legacy canonical wire。失败或未知中断可阻断正式执行；报告依赖冻结计划与原始证据，范围验收使用额外独立审计。

本任务只创建本目录文档与图，未修改旧 HTML/SVG，也未运行 Benchmark。源码依据包含捕获时已有未提交修改。

复现：使用项目 Python 3.14 运行 `build_evidence.py`；用 archify CLI 验证并交付 JSON。`export_and_check.mjs` 通过浏览器原生按钮导出，`check_static.mjs` 验证独立 SVG；其 runtime/Chromium 路径对应本机已安装环境。
