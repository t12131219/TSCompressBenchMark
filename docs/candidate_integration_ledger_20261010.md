# CandidateIntegrationLedger 与候选版本映射（2026-10-10）

本批实现 V3.2 §1.6/15.4 的 L0 第一部分，修复独立审查 F12 确认的
`load_scope()` 因当前 CSV SHA 变化而整体拒绝的问题。交付的是可验证的候选溯源映射，
范围登记、退出决定、CSV 和历史结果没有重标；新候选没有因此取得活动或 FORMAL 资格。

## 工件与口径

- [候选台账](../registry/candidate_integration_ledger.json)：
  `tscb.candidate-integration-ledger.v1`，166 条，每条有具体去向。
- [映射验证器](../tools/candidate_integration_ledger.py)：CSV BOM/多行字段解析、
  逐行核对、原始与合并命名空间校验、快照完整性校验、只读验证与草案生成。
- [旧活动范围](../registry/algorithm_scope.json)：保持原文件及退出决定。
- [范围工具](../tools/algorithm_scope.py)：接受经核对的当前清单映射，仍返回旧 scope。
- [合同测试](../tests/contracts/test_candidate_integration_ledger.py)：包含重编号碰撞、
  退出组合与保留组件、跨表合并、未知版本、损坏台账和清单漂移反例。

| 口径 | 值 | 解释 |
|---|---:|---|
| 当前清单记录 | 166 | 85 V、81 T；选型记录，不是独立 codec 数 |
| 唯一对应旧 scope 的记录 | 163 | 原始 ID、名称、来源组/名称、合并变体均一致 |
| 新记录 | 3 | bzip2、lzsse2、lzsse8；无旧 scope 记录身份 |
| 发生重编号 | 152 | 当前记录 ID 与其 CSV 声明的原始记录 ID 不同 |
| 映射后的明确退出记录 | 19 | 保留旧 scope 命名空间和退出决定 |
| 有规划去向的非退出记录 | 147 | 包含活动、未来完整方案、组件、配置、来源等不同角色 |
| 关联活动入口的候选记录 | 28 | 对应 33 个活动 key；多对多关系 |
| 范围外旧残留登记 | 3 | 关联新候选，仍是范围外登记，须准入和新资格 |
| 独立方法覆盖分母 | 未冻结 | 台账明确存 null，不以 147 或 166 冒充方法数 |

当前 CSV SHA-256：
`bd0ad832d0a97d939e04ef3eb44039bceb89439336864a1821eeee667c1304a2`。

旧 scope 的清单 SHA-256：
`536dda0cdb068da2014b1a0638d6cca7e7f1cb92a750d4528ead272d5e1b665c`。

台账同时绑定旧 scope 文件 SHA、清单 SHA 和台账内容校验和；旧清单原 CSV 不必存在。
本地当前 CSV 存在时，每次映射验证均重新核对实际文件 SHA 和完整行内容投影。
CSV 不存在时，验证已提交快照的完整性、旧 scope 关系、退出决定和合并命名空间。

## 身份与去向

`candidate_id` 使用 `v1:candidate:sha256:<清单SHA>:<记录ID>`。
`resolve_candidate()` 必须显式传 `selection_sha256` 和 `record_id`，没有裸 ID 接口。
例如当前版本 V10 是 lzsse2；旧版本 V10 是 TRISTAN，并连接到当前 V12。
新 V10/V11 不会继承旧 V10/V11 的退出决定。

`original_ref` 与每个合并来源的 `source_ref` 采用
`CSV_DECLARED_ORIGINAL_RECORD_ID` 命名空间，并记录声明它的当前 CSV SHA。
只有核对到旧 scope 实际成员，才赋予 `legacy_candidate_id`；新原始 V131–V133
与被合并掉的原始来源 ID 不会被伪称为旧 scope 选中记录。合并来源字段、原始合并目标、
当前目标 CandidateID 和差异描述全部保留；Sprintz 的 T 表来源合并到 V 表时保留来源组。

每条非退出记录有 `PLANNED_BATCH_EVALUATION`，指定 L0–L6 批次、拟实施角色，
以及来源/实现审查、恢复/成本合同、构建/资格、共同组/语料冻结等交付条件。
活动关联另列 `ACTIVE_REGISTRATION`；新增三条另列
`RETAINED_OUT_OF_SCOPE_REGISTRATION` 和缺失准入条件。
退出记录只有 `EXPLICITLY_RETIRED`，连接旧版本身份与旧决定，不能默认回到实施批次。

退出实现关系独立列出，依据[退出记录](algorithm_retirement_20261010.md)。
例如 T37/原 T53 的独立 `simdcomp-u32` 仍活动，其 Delta/FOR 组合已退出；
相关退出组合关系不把独立组件误排除，也不恢复组合。

`method_id`、`implementation_id` 和 `comparison_group_ids` 的新规范身份尚未冻结。
台账明确标记待来源审查/方法等价政策/组冻结；现有注册的 v2 AlgorithmID 和 SourceArtifactID
以原名称保存，不转换成 V3 MethodID，也不声称完成独立方法去重。

## 验证与后续更新

```bash
python tools/candidate_integration_ledger.py validate
python tools/candidate_integration_ledger.py validate --check-registrations
python tools/candidate_integration_ledger.py draft --output /tmp/candidate-ledger-draft.json
```

默认验证只确认清单映射与旧 scope 决策。注册 manifest SHA、v2 AlgorithmID、SourceArtifactID
是审核时的溯源快照；后续 manifest 闭包刷新不会阻断 `load_scope()`。
`--check-registrations` 另外核对当前 manifest 与快照，有差异时报告快照已过期。
这项检查不能替代实际构建、依赖闭包或运行资格验证。

后续注册快照刷新应生成新台账内容校验和，保持当前 CandidateID 和旧 scope 关系；
改变 CSV 则产生新的候选版本并逐条审查映射。改变 scope/退出决定须显式新范围审查，
不能通过更新快照偷偷扩大活动集合。

`draft` 输出始终标记 `DRAFT_REQUIRES_EXPLICIT_REVIEW`，验证器拒绝将其用于解锁 scope。
命令拒绝覆盖受审台账、CSV 或 scope；它不提供自动审批、注册、删除或恢复命令。
任意未登记 CSV SHA、原始 ID 重复、名称/来源/变体矛盾、合并目标歧义、旧记录缺失、
损坏快照或被改写的退出去向均失败关闭。

`source_records()`、catalog/worklist 过滤继续消费旧 scope 的 `selection_records`，
输出的 `algorithm_selection` 仍指旧 SHA。此接口没有重标成当前 CSV ID；
想展示当前候选 ID 的调用者须单独消费版本化台账。

## 验收与限制

针对台账、scope、source catalog 和工作清单的回归测试：**27 passed**。
台账逐行验证与审核时 manifest 快照核对通过；改动 Python 文件 Ruff 通过。
当前 CSV 文件和旧 scope 文件的内容未改；未运行全算法或新的 FORMAL 实验。

本批仍未交付稳定 MethodID/ImplementationID、适用角色集合及方法等价去重、
多数覆盖目标的事前阈值、冻结 GroupSpec、批次共同语料或候选算法实现。
角色和 L0–L6 去向是工程实施分类，须源码与真实任务审查，不能被当成源能力、性能或覆盖资格。
既有审查和退出说明保留其当时的历史事实；本记录说明本批工具修复的实际新状态。
