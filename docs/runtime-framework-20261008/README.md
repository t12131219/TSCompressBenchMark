# TSDataCompressBenchMark 详细运行框架图集

日期：2026-10-08；基于当前工作区（含未提交内容），静态审阅而非 benchmark 实测。

打开 index.html 查看分章图集及各节点源码证据。每张独立 Archify HTML 支持缩放、搜索、主题与导出。

## 章节

- [运行框架总览](01-overview.html)：CLI 驱动的本地 Python 控制平面；原生算法在隔离子进程中执行。L3 与 L4 共用同一执行生命周期；run report 是独立命令，不由 run validate 自动触发。
- [命令入口与分派](02-cli.html)：命令顺序是依赖关系，而非每条命令都执行完整五层。report 需要已有冻结证据；已有运行集应使用 --run-set-id 与 --resume。
- [初始化、环境与冻结](03-init.html)：初始化阶段保护运行集身份；它不是持续持有的全局锁。prepare、plan、execute、report 会各自获取并释放同名 flock。
- [L1 · 源数据加载与表征](04-data.html)：运行链使用声明驱动的数据加载；表征只读，不把源 CSV/NPZ 的文件大小当作逻辑数据分母。
- [Canonical 格式与身份链](05-canonical.html)：文件 SHA-256、内容 SHA-256 与 DatasetID 是不同证据；原始源文件字节只用于溯源。
- [Source / Codec 注册表与适配器工厂](06-registry.html)：注册表提供可执行合同，不能把“登记”理解为所有数据、硬件和配置已被正式资格认证。附录列出当前 67 个 codec manifest。
- [L2 · 参数展开与任务全集](07-planning.html)：每个算法的参数组合、数据集、Track 都产生可追溯计划；不支持的组合也保留为诊断任务与 coverage 分母。
- [能力协商与数据适配](08-capability.html)：能力协商先判逻辑语义再判物理表示；适配是显式计划，数据复制与精确扩宽均进入成本与身份。
- [实际运行路径与三层可比键](09-resolution.html)：声明的 ISA 不等于实际 ISA；回退及 instrumentation 开关都影响比较身份。三层键构成嵌套合同。
- [三种 Track 与输入路由](10-routing.html)：图的中间三个节点按读取顺序介绍互斥分支；箭头使用“另一路”而非暗示同一任务同时执行三个 Track。
- [L3 · 预检、边界与安全门](11-preflight.html)：任何门失败都会留下 PreflightResult 与 DIAGNOSTIC RunRecord；只有 eligible_for_formal_repetitions=True 才能预热。
- [隔离进程、资源上限与错误传播](12-isolation.html)：隔离针对每次具体函数调用；预检阶段、边界、预热、正式重复、查询及 streaming 都可分别创建 worker。正式任务在父进程 for 循环中逐个执行。
- [编码对象生命周期与 C ABI](13-session.html)：每次压缩是新的、必须 Finalize 的对象；解码也用新的 session。reset / query / timing 是 ABI 能力，具体是否使用或支持取决于路径。
- [L4 · 预热、正式重复与计时边界](14-measurement.html)：默认正式 10 次重复，实验可设更多。每一次重复内部可执行多次独立对象以满足最低时长；编码与解码分别达到门槛。
- [显式预处理 A/B/C/D 与融合路径](15-pipeline.html)：StreamVByte 的 A–D 是一条具体可逆路径；MaskedVByte 与 SIMDComp 的融合 D1/FOR 合同不同，不能把槽字母等同于统一算法。
- [正确性、损失模式与位账本](16-correctness.html)：正确性门与账本闭合共同决定 PASS；大小统计使用 finalized stream，包含解码必须的附加信息。
- [查询、Streaming 与资源资格](17-workloads.html)：附加 workloads 按配置与 features 判定；未请求、无能力与执行失败是不同证据，不能填成零时延。
- [追加日志、位流与幂等持久化](18-storage.html)：原始事实源是 run_components.jsonl；runs.csv 是投影。事件日志同样追加，JSONL 末行不完整会阻止恢复与统计。
- [恢复、缺失重复与终态行为](19-resume.html)：恢复按原始记录存在性推进；已经记录失败的重复也算已完成，不自动重试。已有 DIAGNOSTIC 任务整体跳过。
- [L5 · 资格筛选与稳健统计](20-statistics.html)：资格按分析分别给出；source.kind=BUILTIN_HARNESS 或 QUALIFICATION 测量不进入正式性能排名。
- [覆盖率、Pareto、排名与报告输出](21-report.html)：coverage 以冻结任务全集为分母。排名仅在嵌套可比组内进行；不输出跨 Track / LossMode / ObjectLevel / CPU-GPU 的总榜。
- [算法接入、构建与资格证据](22-onboarding.html)：这是运行前的支撑链，具体算法使用不同工具。当前登记并不代表这些步骤对所有组合都已通过，实际状态以准入卡和任务结果为准。

## 附录

- 67 个 codec manifest，22 个 dataset manifest。
- 100 个运行 Python 模块与全部定义、静态 imports/calls。
- 100 个 tools 脚本、197 个本项目原生文件、26 个 v2 schema。
- source-evidence.json：工作区文件 SHA-256、节点行号与完整注册声明。
- acceptance.json：Archify 规格和 HTML 哈希、验证与浏览器证据。

工作区来源证据与 Archify 固定 commit 验证机制不同，未声明该图集通过 fixed-commit repository verification。

## 验收状态

22 张 architecture 图均通过 9/9 Showcase 校验，0 errors / 0 warnings。规格与 HTML SHA-256 见 acceptance.json。

浏览器证据 skipped：Chrome/Chromium 不可用，应用浏览器阻止 file URL，因此完整 HTML 视觉 / 交互验收未完成。librsvg 静态 PNG 已生成，已检查总览、pipeline 与统计章节；这不是浏览器截图。
