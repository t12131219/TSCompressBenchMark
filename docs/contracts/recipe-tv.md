# 配方合同 v1：完整对象 T/V 的可执行绑定

M0 冻结配方语法与解析；这个实现只为已有的 `tv-bundle/1` 执行器提供确定性 lowering，
不实现 M5 的通用能力补齐。配方指向一个按规范化内容锁定的 T/V suite，显式指定每个方法
使用哪张图（`force_recipe`）。不会根据数据或测量结果换图、试别的 codec，也不提供隐含 raw 保底。
构建、插件注册、选项默认值、固定 T/V 对照和资源边界仍走原有 TV planner，不能用新标签改变。

## 图与边界

- 图按拓扑顺序声明，最多 16 张、每张最多 16 个节点、深度上限 8。每个节点检查输入类型、实现支持和
  已登记逆操作；前向引用、循环、孤立分支和不匹配的 bundle lowering 被拒绝。纯图检查不是动态 codec probe。
- 支持三种已有 lowering：联合 T/V、共享 T 加逐列 f64、共享 T 加分组 u16 位片。分组将一个 f64 的
  四个 16 位片按规定顺序打包、逐位逆变换，不作数值转换；`TV planner` 另核对 lane 数和 role。
  联合原生入口不冒充独立 T 或 V，固定 T/V 对照使用冻结的 `route_id`（含插件、选项、格式、分块、构建）。
- 配方锁定原域 T+V 位级恢复、完整 bundle 字节、`artifact_each`、每条消息重置、整对象批和流水线服务范围。
  类型解析、输入时间单位检查和暂存位于 worker 时钟之前；性能不得称为 CSV/NPY/TXT 端到端、在线流或物理 I/O。
  目前只支持每方向进程 deadline 和 frame 上限，不 enforce 独占核或 RSS，不声明主性能准入。
- `recipe-plan` 生成可由原有 `tv-run` 消费的 plan。绑定同时锁住 recipe/schema、基础 TV plan ID、逆图和
  节点到 codec route ID 的映射。提交前从本地配置重新生成；封存进入**同一次运行**，没有额外收据或账本。
  报告与独立恢复只从封存的计划、schema、ledger 与产物重建；它们不依赖外部 recipe 文件。
  修改节点对应的 codec route 再重签内容哈希，仍会因 lowering 不一致被拒绝。

## 使用与进度

```bash
./bmk recipe-plan --recipe configs/recipes/tv-cross-format-v2.json \
  --build-lock build/build-lock.json --out results/tv-recipe-plan.json
./bmk tv-run --plan results/tv-recipe-plan.json
bash tools/probe_offline_recipe.sh "$CONDA_PREFIX" <空结果目录>
```

Python 入口为 `tsbench.planner.recipe.plan_recipe(root, build_lock, recipe_path)`；沿用
`tsbench.api.run_tv`、`report_tv` 和 `restore_tv`。`configs/recipes/tv-composition-v1.json` 同时定义了
已有固定 T、固定 V 与联合对照的配方，该配方不属于本次 CSV/NPY/TXT 运行。

[禁网迁移证据](../../results/m0-recipe-ingress-20261119-r2/report.json)：从空目录构建，不挂载邻接 Unique，
一次提交、主账本 12 槽全部位级还原；CLI 和 Python 计划一致、24 次独立 encode/decode 进程、
两个原始对象各自的三种格式产生同方法相同 bundle，且两种方法的固定 T 分支一致。
[脱离输入与构建的恢复](../../results/m0-recipe-ingress-20261119-r2/restore.json)重解 12 个封存产物，
[复算](../../results/m0-recipe-ingress-20261119-r2/recomputed.json)与原报告逐字节相同；
[对照](../../results/m0-recipe-ingress-20261119-r2/controls.json)拒绝重算哈希后伪改的节点绑定。
旧 ALP 构建指纹不匹配时在提交前拒绝，本结果使用新构建，不复用旧运行的终态。

**不更改 `first_batch_service_v4` 资格。** 同一输入的原域恢复支持后续绑定，但 ingress 义务要求在规定
范围内计入 source 开销，固定 T 需要合格的 T 控制及执行资源，位片 V-only 也不能以 T+V 路线替代。
本轮没有把这些待补的服务条件标为通过；原生资格仍为 0/36，服务义务仍为 0/564。
