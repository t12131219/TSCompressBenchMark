# TSDataCompressBenchMark 五层运行框架

按 `docs/archify-five-layer-reference/framework.light.svg` 的视觉形式重新绘制：一张完整的纵向五层图，左侧职责栏、中间详细模块和有向数据流、右侧关键输出与核心约束。使用自定义 SVG / HTML，无 Archify 渲染依赖。

- [交互 HTML](framework.html)：纵向阅读、层级跳转、模块与源码搜索、节点源码详情、浅色 / 深色切换、SVG / PNG 下载。
- [浅色完整 SVG](framework.light.svg) / [PNG](framework.light.png)。
- [深色完整 SVG](framework.dark.svg) / [PNG](framework.dark.png)。
- [源码依据](source-evidence.md) / [文件指纹与节点绑定](source-evidence.json)。

图包含 68 个模块、76 条关系，绑定 63 个当前工作区源码文件。五层依次为数据准备、能力与配置、执行验证、性能测评、统计分析与报告。参考图中的新增内容已融入主结构，四条执行路径明确显示各自的 runner：Legacy、V3.2 comparison、独立 stream/query workload、P2 pipeline。

实线表示处理与控制依赖；虚线表示证据、条件、同次观测或对象内部展开。跨线拱桥表示交叉但不连接。节点来源可点击查看；图中的箭头不是一一对应的函数调用时序。测量层表示同一次执行的观测职责，P1 生命周期表示正式执行的内部对象展开。

语义边界：Legacy 的任务和统计合同单独保留；V3.2 的比较合同、完整期待矩阵、真实 Schedule 配对与独立 pilot 单独冻结。P2 使用 LogicalObject / PipelineRecipe，不强制通过 Legacy Canonical wire。CORE 组件边界与完整对象 PIPELINE 的时间、成本分母分别定义。实现存在不代表当前所有路径已通过资格、pilot 或 FORMAL；图任务没有运行 Benchmark，也没有修改项目业务源码。

`structure-check.json` 检查模块、文本容量、正交路径、端点方向、共享通道、穿过无关节点以及源码身份。`browser-check.json` 检查四种桌面尺寸、双主题的实际浏览器文字边界、横向溢出、节点详情、键盘操作、搜索、层级跳转、主题和导出链接。`review.*.png` 为逐层的浅色 / 深色视觉检查图。

重新生成：

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/architecture-five-layer-20261012/build_framework.py
node docs/architecture-five-layer-20261012/browser_check.mjs
```

生成器使用 Pillow 测量中文字体、Graph routing 绘制正交连线、`rsvg-convert` 输出 PNG。源码语法需要 Python 3.14。生成结果独立保存在本目录，原参考图与其他版本保留。
