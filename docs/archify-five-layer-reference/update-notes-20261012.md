# 2026-10-12：在原五层框架内更新

已直接更新 [完整框架 HTML](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.html)，并同步 [浅色 SVG](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.light.svg) / [深色 SVG](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/framework.dark.svg) 及 PNG。保留五层色带、左侧职责、右侧输出/约束、原有详细框线和节点交互；在每层增加 V3.2 补充区。图从 46 节点 / 51 条有向关系扩展为 **64 节点 / 69 条有向关系**，画布为 **2180 × 4815**。

## 原图是否正确

原来的“数据准备 → 能力与配置 → 执行与验证 → 性能测评 → 统计分析与报告”职责划分仍然正确。原图主要描述 Legacy TOML / runner / statistics 路径，不能完整代表当前 V3.2 的 comparison、workload、P2 三条执行路径。保留 Legacy 的统计口径，并补上新合同和门禁，才符合当前源码。

本次按当前工作区文件核对，包含已有的未提交 analysis.py 修改。119 个源码、schema、配置、测试或审计文件已记录指纹与符号定位。旧证据的 72 个文件中，31 个指纹变化、1 个文件已移除；指纹漂移本身不等于图义全部错误，但旧回执不能作为当前源码证明。

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

图明确保留当前审计边界：entropy 为 CORE_COMPLETE，stream / query-warm / query-fresh 为 PROFILE_COMPLETE；P2 development pilot 不合格，其他 comparison lane 仍有资源、预期不支持、停止或 cold 汇总缺口。实现流程存在不等于当前所有 lane 已通过。依据为 [当前闭包与 FORMAL 验证](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/README.md)。

## 检查与交付范围

| 对象 | 结果 |
| --- | --- |
| 原框架 HTML 静态几何 | passed；64 节点 / 69 有向关系一致，节点/标签/端口/正交线路检查通过，无模糊共享走廊 |
| 原框架 HTML 真实 Chromium | passed；1440×900、1600×1000、1920×1080、2048×1320 × 明暗两主题，无横向溢出，允许正常纵向滚动 |
| 原框架 HTML 交互与 DOM | passed；搜索、旧/新节点说明、主题、导出链接、末层可达；节点文字、边标签、补充说明无遮挡 |
| 原框架 HTML 图像检查 | passed；五层明暗截图实际检查；旧 Layer 4 三处遮线已修复 |
| 独立原生规范 / deliver | 9/9 **standard**，0 errors / 15 warnings；不是 showcase 的 0-warning 验收 |
| 附带原生查看器 | browser_evidence / visual_review 均 failed：默认明细小于 6px，首屏纵向溢出；原框架的通过结论不继承它的回执 |

推荐阅读原路径 framework.html。附带 [原生缩放查看器](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/native-updated.html) 仅提供简要拓扑，完整细节以五层框架为准。独立 SVG 由展示渲染器生成，PNG 由 rsvg-convert 转换，并非 Viewer 原生导出。本次只更新图与文档，没有运行 Benchmark，没有修改其生产源码。

[完整源码定位](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/source-evidence.md) · [文件指纹与检查回执](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/handoff-receipt.json) · [视觉检查记录](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/visual-review.md)。

原图及全部 91 个旧文件已保存在 [更新前 HTML](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/history/pre-update-20261012/framework.html) 所在目录，[快照指纹](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/history/pre-update-20261012/snapshot.json) 可核对原字节。仍留在当前目录的 native-final、framework-final、旧 final/handoff 回执、旧 native 导出和旧 overview 截图均属于历史材料。
