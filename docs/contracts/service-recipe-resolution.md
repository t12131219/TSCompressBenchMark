# 首批服务配方解析：`bmk.service-recipe-plan/1`

这是 M0 的解析计划，不是 M5 执行入口或运行记录。保留 `first_batch_service_v4` 的 12 个 selection、17 个展示组、
22 条原子要求、204 个展示格、264 个原子关系和 564 项场景义务；132 项预期拒绝仍在分母内。
输出锁定原 scope plan ID，不改动 v4 的场景、slot、展示格或原生矩阵，并给每个 slot 增加解析结果。

```bash
./bmk service-recipe-plan \
  --bindings configs/suites/first_batch_service_v4/recipe-bindings.json \
  --build-lock build/build-lock.json --out results/service-recipe-plan.json
./bmk service-recipe-verify --plan results/service-recipe-plan.json
```

`build/build-lock.json` 必须指向相符的 TV worker、适配器和实际依赖。Python 共用
`tsbench.planner.service_recipes.plan_service_recipes` 和 `verify_service_recipes`，CLI 不做独立解析。
复核从当前配置、语料和构建重算整个文档，不只检查外层哈希。

## 解析规则

- [注册表](../../configs/suites/first_batch_service_v4/recipe-bindings.json) 按摘要锁定配方，显式声明主要编解码支路的
  selection 与插件。规划核对选集、发布包归档和插件 manifest；Gorilla-T 在固定 T 对照中是辅助支路，
  不会给 Gorilla 第 7 项增加这一方法的资格。保留方法、解析后的选项、构建、原始输入、比较合同和恢复闭包 ID，
  不读取历史报告，不把可用 codec 与全部输入做笛卡尔积，只匹配 TV 执行器已经排定的槽。
- 逐项检查完全一致的输入 manifest、加载器/选项/数据身份、原域列与数据关系。CSV、NPY、TXT 可还原成同一个
  canonical 对象，但只有同一源文件/摄取身份才匹配相应的 ingress 义务。正例执行路径不替代预期拒绝驱动。
- `incompatible_candidates` 表示找到相同 selection 和输入的开发槽，但至少一个正式合同条件不符；候选逐项列出
  任务/控制、转换、计费范围、资源、验证器等差异。匹配固定 T 的方式是比对真实的比较合同 ID，仍须控制支路合格。
  每方向 10 秒的进程超时不等于 15 秒的整场景 deadline，帧大小上限也不代表已限制 RSS 或暂存。
- `unbound` 区分无已注册的 selection 配方、操作没有对应 lowering、用例输入不在已排定槽内、负向驱动缺失，
  以及注册配置中的插件未构建、未注册或已禁用。显式提供的构建指纹错误会拒绝计划，不会悄悄退到其他算法。
  `not_run` 是执行状态；上述是计划状态，而非负向运行结果。外层计划不能交给 `tv-run` 执行。

本版本只登记已实际接入开发执行器的 ALP f64 和 Sprintz-FIRE 分组 u16 两条 T/V 方法。禁网迁移审核中，
**24 项同源候选合同不匹配，540 项无绑定；0/564 执行或合格**。其中 source 用例的解析在 worker 计时前完成，
V-only 和 T-only 用例不能借用联合恢复；固定 T 有相同输入与比较键，但仍缺实际服务计量、资源和控制资格。
这不是 24 项正式拒绝终态，也不将历史 12 槽开发恢复并入新计划。

[计划复核](../../results/m0-service-recipes-20261119-r3/verification.json) 和
[对照检查](../../results/m0-service-recipes-20261119-r3/controls.json) 只读挂载匹配的 worker、DSO 与构建锁，
不挂载 Unique、历史运行及报告；重封存后删除义务、误将辅助支路当主算法、错绑发布归档和误改构建指纹均被拒绝。
[临时禁用 ALP](../../results/m0-service-recipes-20261119-r3/disabled-controls.json) 后固定 T 对照不能用单个方法替代，
564 项全部保留。可用 `bash tools/probe_offline_service_recipes.sh "$CONDA_PREFIX" <匹配TV构建目录> <空结果目录>` 复查。
