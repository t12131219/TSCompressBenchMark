# TSDataCompressBenchMark 源码展开运行框架

按 2026-10-08 当前工作区源码绘制，包含现有未提交实现。

已删除原图的全部“关键输出 / 核心约束”说明框，将 10 个概览流程节点展开为 50 个细化职责节点，并增加一个预检失败诊断分支，共 51 个节点。

- framework.html：独立 Archify 查看器。
- framework.archify.json：可编辑规范。
- framework.light.svg / framework.dark.svg：最终 HTML 的完整静态细节导出。
- framework.light.png / framework.dark.png：2760 × 4210 图片。
- expand_framework.py：规范生成脚本及各节点实现锚点。
- node-evidence.json：50 个主要细化节点与实现名对应关系。
- deliver-receipt.json / handoff-receipt.json：当前文件哈希、校验和图片审查记录。

## 阅读说明

该图展开的是五层职责与处理关系，箭头包含主流程推进、内部步骤展开、同步测量与分析结果汇集，不能将所有箭头解释为严格串行调用。隔离 Round-trip 是其后编解码步骤的调用容器；性能计时和资源采集在正式重复期间发生；查询与流式步骤有配置和能力条件；各统计分析视图由同一个 AnalysisBundle 汇集。

源码中适配与预处理在规划时冻结计划，在执行预检及正式重复中实际应用或验证。Layer 3 / 4 共用 execute_task。统计层先资格筛选，再聚合，并生成各类派生分析表。

数据来源：src/tscompbench/cli.py、runner.py、datasets/prepare.py、codecs/negotiation.py、planning/resolution.py、execution/preflight.py、execution/orchestrator.py、execution/repetition.py、measurement/resources.py、statistics/engine.py、reporting/generator.py、storage/runs.py 及其调用模块。

## 验证

Archify showcase 9/9，通过，0 errors / 0 warnings。已检查静态明暗图片，未发现标签裁切、节点重叠或穿节点连线。当前没有 Chrome/Chromium，自动浏览器检查 skipped；HTML 的窗口尺寸适配和交互未验证。布局校验与静态审查不代表所有源码语义都经过自动验证。
