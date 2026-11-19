# M0 文档合同与实现落位

本批将原生 worker 放在 `native/worker/`，插件加载与生命周期代码放在 `native/runtime/`，
raw-store、Zstd 和 ALP Auto 分别放在 `plugins/codecs/` 的独立包中。`plugins/codecs/common/`
只放共享适配头，不是注册插件。公共 ABI 与控制层入口没有随搬迁更名；根目录设计及来源
文档保留原位置。历史构建目录和证据不迁移；请从新 CMake 构建目录重新配置。
迁移二进制及移除 staged 原始输入的测试在 `tests/isolation/`，直接调用对照和 CLI/API
全流程测试在 `tests/integration/`；禁网迁移审计仍由 `tools/probe_offline_m0.sh` 调用。

## 校验边界

`schemas/` 中每份合同均使用 JSON Schema Draft 2020-12。`tsbench` 的锁定环境包含
`jsonschema`，没有联网获取 `$ref` 的路径。schema 是必要的结构门槛，不能替代语义校验、
文件引用与内容哈希校验，也不能证明 codec 运行或资格。

| 文档 | 当前接入点 | 校验对象 |
|---|---|---|
| `plugin.schema.json` | 插件发现、CMake 选择、开发 smoke | codec manifest、包/目标声明及当前 smoke 任务域，不含每个算法自己的 options schema；运行依赖只能声明相邻库文件名 |
| `experiment.schema.json` | CLI 的 TOML 请求、CLI/Python 的 planner 请求 | M0 规划请求子集，不是正式实验锁 |
| `comparison-contract.schema.json` | `comparison-plan` / Python API、M1 候选计划/复算 | 锁定 R/O、原始恢复任务、固定支路、资源、访问、计费、验证与留存；不授资格 |
| `resource-candidate-policy.schema.json` | M1 候选计划、监督器及离线复算 | 输出挂载点/主机水位、子进程资源观测与暂存处置；不是硬资源隔离 |
| `suite.schema.json` | planner | M0 首批范围草案及单计划、逐产物验证、独占性能资源政策 |
| `required-capabilities.schema.json` | planner | 公共服务定义与展示分组 |
| `case-catalog.schema.json` | planner | 开发用例意图，不是完整执行输入 |
| `service-suite.schema.json` / `service-workloads.schema.json` | `plan --suite first_batch_service_v4` / `service-plan-verify` | 首批服务关系与场景参数、输入、资源和终态合同；重建比较整份定义，不授执行或资格 |
| `native-inventory.schema.json` | planner | 冻结来源的已索引原生入口，不授资格 |
| `native-requirements.schema.json` | `native-contract-plan`、M0 预检计划绑定 | 36 个原生组的必需/条件/不适用范围及用例关系，显式列出未完成定义 |
| `method-boundaries.schema.json` | 预检计划和执行共用 | 边界配置、数据划分、方法参数与开发资源上限 |
| `native-preflight-suite.schema.json` | `native-plan` / `native-run` | 首批原生候选预检的套件、策略、操作组与已配置探针闭包；不授资格 |
| `matrix.schema.json` | planner 输出 | 完整展开的草案矩阵，必须是 `runnable: false`、执行/资格计数均为零 |
| `observation.schema.json` | 开发 smoke 写入与报告复算 | `bmk.dev-observation/1`，单 slot 终态、编码/解码进程身份、产物引用、实际 backend/线程/fallback；无正式性能或资格字段 |
| `corpus.schema.json` | 显式导入、`check-corpus` 和规划 | 逐来源资产身份、时间划分及 canonical ID；当前 v3 六个来源簇，`domain_coverage_only`，不授资格 |
| `lossless-stage-suite.schema.json` | M1 候选计划、执行和报告复算 | 冻结整列无损任务、方法、case、核验、资源上限及保留规则；预检不授阶段资格 |

planner 另行核验组/原子要求/案例闭包、选版来源及矩阵分母；manifest 仍需通过登记 ID、
工程内路径、源码/依赖内容身份和 options 语义检查。计划绑定 schema 集合的内容哈希，插件
manifest 身份还绑定自身的结构合同。迁移或 schema 变更会生成新计划身份，不修改旧日志。

插件选项在合并默认值后仍拒绝未知参数。开发选项合同除标量外支持带 `minItems`、
`maxItems` 界限的标量数组，以及数值 `exclusiveMinimum` 和数值数组的
`x-order: strictly-decreasing`；不自动排序或截断。PBEPLA-RR 的 `eps` 为实际用例；
worker 的原生入口仍独立核验传入参数，恢复用空选项不等于编码可省略必需项。

开发 smoke 的 v2 计划锁定观测 schema 内容身份，运行前检查一致并把该版本随原始证据封存。
写入与报告复算都校验结构与操作顺序；报告另核对统一计划的 slot 闭包、验证、字节账本及
留存产物哈希，不从重复账目中选一条。完成标记原子发布用于区分完整运行和未封存的中断，
不是签名或抗恶意重写证明。旧 v1 开发证据不补写新的合同；请用 v2 计划生成新证据。

正式 recipe、qualification、trace、正式测量观测以及非草案矩阵没有用空文档占位，会随
实际生产者、消费者和独立验证器落地。已锁定的部分真实语料见
[真实语料合同](first-batch-real-corpus.md)；完整语料范围、执行绑定和资源阈值尚未冻结。
