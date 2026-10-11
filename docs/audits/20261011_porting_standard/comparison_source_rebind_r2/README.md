# 当前源码绑定的新比较配置

四份 `*-v32-20261011-port-v2.json` 是新的计划配置，不继承旧资格、旧性能结果或正式接受状态。原比较文件、语料与结果保留。默认活动角色模板中的整数、质量、时间戳和查询组，以及 workload builder 的整数 base，改为引用新配置。

| 新配置族 | 保留的原配置 |
| --- | --- |
| G-INT | `g-int-ll-i16-v32-20261010-v3.json` |
| G-QUALITY | `g-quality-v32-20261010-v5.json` |
| G-TIMESTAMP | `g-timestamp-v32-20261010-v1.json` |
| G-QUERY | `g-query-ll-variants-v32-20261010.json` |

工具 `tools/rebind_v32_comparison_sources.py` 校验原身份链，严格绑定当前源码身份、闭包字段、方法语义定义及 source tags，重算修订版的派生身份，并通过当前 registration 的 `compile_group_plan()`。方法的机制、变体、语义版本和 classification/semantics/input/lifecycle 定义哈希必须相同；改变这些语义会拒绝自动迁移。LZSS 的方法显示名称随来源描述由 Rust 改为 C++；MethodID 不包含显示名称，语义保持时其身份保持，GroupID 随新来源和 revision 更新。proof 保存精确旧、新名称和身份。

语料、参数网格、预期结果、角色与路径、选择和分析策略、测量协议、随机种子和资源预算保持原样。每份 proof 保存 registration 前后相等的冻结快照，以及新配置、原配置和 driver 的实际哈希。配置和 proof 均使用新路径独占写入，已有输出不会覆盖。迁移只生成新的计划，没有执行 codec、pilot 或 formal 测量。

早期 `comparison_source_rebind_r1` 的两份整数/质量计划原件保留，其生成工具的精确版本保存在 `driver-r1.py`；最终默认引用使用 r2 的四份计划。
