# M0：统一原生提交前闸门 v1

`bmk native-submission-plan --execution-plan <batch-plan> --predecessor-audit <sealed-audit> --out <submission-plan>`
生成一份带资源和留存政策的完整计划。`bmk batch-execution-run --plan <submission-plan> --results <已存在目录>`
通过闸门后调用同一个原生执行器。Python 入口为 `tsbench.application.native_submission`。计划中的
`execution` 是现有执行器理解的内层投影，不是另一份提交；只有执行器分配一次 run ID、写一个主 `ledger.jsonl`。
闸门输出是同次运行的启动观测和派生报告，不是阶段收据，不参与多次结果拼接。

- [政策](../../configs/profiles/native_submission_v1.json)及 [schema](../../schemas/native-submission-policy.schema.json)
  冻结 12 个选项、36 组、180 项必需及 6 项条件。只接完整 `extended-v20`，不接受删除路线、缺绑定、不同用途或手填资格。并要求锁定一份同一候选 build/plan 的 M0 原生资格审计；审计必须明确列出尚未正式提交、前置接纳未绑定和正式资源政策未绑定，且仍为 `stage_accepted=false`、`qualification_granted=false`。这一步验证前置证据，但不把它改名为接纳。
  校验受约束的每槽 driver、每操作预算和 CORAD Source 训练的单步覆盖值。计划上限与实测用量分列。
- 按完整计划核算需留存的产品、对照载荷、stdout/stderr 及两份共享恢复闭包，另加工作区和元数据空间。
  启动前在目标结果文件系统测可用空间与 inode，并测宿主 `MemAvailable`。水位、政策或构建不满足时，不创建运行目录或主账本。
  结果目录 inode 锁可跨挂载命名空间阻止对同一目录的协作提交；另复用 `tsbench` 计时的同 UID 锁，后者仅在共享同一 `/tmp` 时互斥。
- 原执行器仍重新解析和比对构建、输入、配置及校验代码，预置恢复闭包后才发布运行。原子操作继续采用禁网、文件限定挂载、
  `RLIMIT_AS`、`RLIMIT_FSIZE`、禁 core 和超时；已有复算路径按实际封存字节核对留存上限。没有删除任何历史运行或重用其 PASS。
- 宿主水位不是 cgroup 预留，也不保证后续磁盘/内存仍有这么多；每进程虚拟地址空间不是进程树 RSS，
  每文件限额不是目录配额，子进程事前超时之和不是 run 墙钟上限。此次不做提前删除样本、全局资源独占、正式前置阶段收据校验，
  也不把外层提交观测冒充原有 seal 的组成部分。M0 阶段收据另行复算这些证据；旧入口可原样运行历史开发计划，但其结果不能宣称经过此闸门。

## 禁网实测

[提交计划](../../results/m0-native-governed-submission-20261119-r3/submission-plan.json)预计 **200 槽、1,186 次操作**，
子操作的最大声明限额为 **768 MiB 地址空间、6 MiB 单文件、25 s**，子操作超时预算合计 **6,220 s**。
保留项上界 **2,276,241,470 B**，加工作区和元数据后启动水位 **2,544,676,926 B**；还要求 8,192 inode 和 1 GiB 整机可用内存。
[提交报告](../../results/m0-native-governed-submission-20261119-r3/submission-report.json)记录实际读数并关联到唯一 run
`65a17345a2f442639b2809bc76c19289`。只读复用先前已锁定的主构建，Huff0 portable 对照从空目录构建。
同次执行 174 个验证产物、26 个预期拒绝；四类留存项实计 **46,270,386 B**。
禁网、无构建与原输入的 [复算报告](../../results/m0-native-governed-submission-20261119-r3/recomputed.json)与原报告逐字节相同；
[恢复报告](../../results/m0-native-governed-submission-20261119-r3/restore.json)实际恢复 174/174。
必需项 179 项候选通过、CORAD 冻结质量界 1 项拒绝；条件项 5 项候选通过、ALP AVX512BW 仍待兼容宿主。均不授正式资格。

真实 5 MiB 文件系统上的 [容量拒绝](../../results/m0-native-governed-submission-20261119-r3/negative-controls/low-capacity.stderr)
发生于执行器前；[前置审计拒绝](../../results/m0-native-governed-submission-20261119-r3/negative-controls/bad-predecessor.stderr)也在创建运行前发生；[缺锁定构建拒绝](../../results/m0-native-governed-submission-20261119-r3/negative-controls/stale-build.stderr)
没有发布运行。合同测试另核对 inode、内存、锁竞争、策略漂移和提交前取消。

复现：在 `tsbench` 环境运行 `bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" <Rust工具链目录> <空结果目录> --huff0-bmi2`。
可以用 `TSBENCH_REUSE_BUILD_EVIDENCE` 指向具有一致构建锁的旧禁网构建，不复用其运行证据。

## 空构建补验

为关闭“只读复用构建不能证明空缓存闭包”的 M0 缺口，另在
`results/m0-native-empty-v20-20261119-r1/` 从空 `build/` 和空 `runs/` 开始执行同一流程。
该目录没有 `TSBENCH_REUSE_BUILD_EVIDENCE`：

- CMake 空构建完成，CTest **17/17** 通过；构建目录封存前约 **200,870,111 B**；
- `tsbench` Python 回归 **200** 项通过；
- 仍为同一个 build identity `5009ff5142b89a988d21fba908ffc1b96d3da4ab4c1ace97f22002731498d67e`；
- 统一计划仍为 200 槽、174 个验证产物、26 个预期拒绝；运行 ID 为
  `8623dd4e0e894583836fe72cfe613022`；
- 原报告和无构建/原输入的复算报告一致，174/174 产物独立恢复。

这证明本地源码、CMake、插件、控制器、数据和恢复依赖可以在禁网空构建中闭合；它仍不替代
正式 M0 阶段收据，也不把 CORAD 质量拒绝或 ALP AVX512BW 条件改为通过。
