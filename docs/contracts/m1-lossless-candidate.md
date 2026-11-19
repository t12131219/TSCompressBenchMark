# M1 无损候选阶段计划（M0 开发预检）

本计划用于 M0 检验“配置 → 完整阶段计划 → 单 run 账本”的实际链路。它不是 M1 正式验收，
没有等待阶段签发的运行不会自动转正。`qualification_granted` 固定为 `false`。

## 冻结范围与分母

`m1_lossless_candidate_v1`（功能）、`m1_lossless_candidate_v2`（直接子进程诊断）与
`m1_lossless_candidate_v3`（执行时文件隔离）共享 `schemas/lossless-stage-suite.schema.json`，都固定 `values_only`、O 轨道、整列 batch 访问、原始域 f64 位无损、`artifact_each`。
三个方法串行，声明一个 worker 线程，编码/解码各新建进程；每个 slot 只尝试一次。

| 必需用例 | 输入 |
|---|---|
| `empty-f64` | 0 元素 f64 |
| `short-finite-f64` | 9 元素有限值 fixture，包括负零 |
| `special-f64-bits` | 9 元素 fixture，包含 subnormal、无穷、不同 NaN payload 和极值 |
| `alpn-vector-tail` | Beutenberg 气象 held-out 分区 `air_temperature` 列，偏移 0、长度 1,025 |
| `zstd-near-maximum-f64-block` | 葡萄牙电力 held-out 分区 `MT_231`，偏移 0、长度 8,191（65,528 B） |
| `zstd-exact-maximum-f64-block` | 同一列同一分区，偏移 8,191、长度 8,192（65,536 B） |

分母为 **6 个用例 × 3 个方法 = 18 个 slot**。两个电力窗口不是独立数据来源；
这三段真实输入仅来自两组。三方法为 raw-store typed V、Zstd 单线程 level-3 byte-codec
（对 canonical f64 字节工作，**不是**原生 typed V）、ALP Auto typed V（显式 `scalar-unfused`
解码）。ALP 记录 raw/RD/ALP 真实分支元数据，但不把 raw 回退当成 SIMD 或其他路线通过。
同一原始值列的完整 worker frame 字节可核对；v1 不采时，v2 仅采父进程墙钟诊断，均没有正式性能样本，不能据此排名。

## 计划与执行约束

- CLI/Python 共用一套 planner。计划绑定语料锁、fixture 锁、直接调用对照合同、suite schema、
  observation schema、插件配置以及构建锁。窗口身份含完整资产摘要、分区 ID、来源簇、列、
  分区内偏移和长度；执行前检查配置未变，加载时再次核对规范化值和 schema 哈希。
- 导入器/规划器只读工程内已锁定的语料格式，不直接读 `datasets/raw/unique/` 全量副本。
  窗口解包在 codec 调用外；不写一套永久 canonical 副本，也不假装新的独立来源。
- 计划给出输入逻辑总字节、最大单用例逻辑输入、最多 36 次 worker 操作、成功产物文件费用上界；
  单次操作默认超时 5 s，单个成功 frame 上限 256 KiB 超出即拒绝进入 decode。此上限是成品检查，
  不是 OS 内存/磁盘隔离限额。进程 RSS、峰值磁盘和正式计时显式未估计或未采集。v2 另锁定[计时、计费与验证政策](m0-measurement-policy.md)。
- 执行一次完整计划，仅有一个 `run_id`。原始值临时副本删除后再启动解码，按位验每个产物，
  保留 frame、尝试终态、日志和原始账目；没有分段晋级。恢复证明不传原始输入且 staged 文件不在，
  不等于禁止解码进程访问所有 OS 路径。报告复算从 seal 和原始记录加载，不依赖当前语料、
  worker 或 schema，也不重新解码。
- `configs/experiments/measurement_controls/direct_routes_v1.json` 是单独的同工作量和原生差分
  合同。此候选执行只绑定其定义，不把其他对照运行拼接为本 run 的成功 slot。

## 运行

在 Conda `tsbench` 下先完成 README 的 Release 构建，再运行：

```sh
scripts/smoke.sh build/m0-layout-abi m1_lossless_candidate_v2
# 删除派生报告后也可重算：
./bmk smoke-report <run_id>
```

若单独生成计划，使用 `bmk smoke-plan --suite m1_lossless_candidate_v2 --build-lock <local-lock>`。
Python 为 `plan_smoke(root, SmokePlanRequest(build_lock, "m1_lossless_candidate_v2"))`。
M0 下一步仍须把原生入口、M5 具体 case/recipe 和全套语料覆盖、正式资源/时钟/计费与
留存政策绑定；M1 正式验收须接入声明的计时/账本边界并满足已通过的 M0 前置门槛。

### 每一方向的冻结比较条件

新运行把正式字段定义的开发子集随 schema 一同封存。六个输入各有 encode/decode 两个独立
[`comparison_id`](statistics-and-comparison.md)，同一方向跨三方法共用；历史 `comparison_id` 仍为旧诊断
分组字段，新字段 `frozen_comparison_ids` 才是按方向计算的合同键。报告不以同键声称资源合规；
`primary_comparison.admitted` 为 false，并留下缺正式资源观测和正式资格的原因。

新候选同时锁定[资源观测和留存政策](candidate-resource-retention.md)：按实际结果目录水位决定是否启动，
按直接子进程观测 CPU/RSS，验证通过并写账、且共享解码闭包完整后回收暂存，失败留存现有暂存。原候选执行仍未取得正式资源预算或资源隔离资格。


### 保留帧独立恢复

- 新 v2 计划冻结 Linux x86-64/glibc 恢复闭包：可信 build lock 中的 worker 和插件、声明的项目
  共享库、发行版 loader 与可达的系统运行库。用本机 `readelf` 展开 ELF `DT_NEEDED`，拒绝未声明依赖
  和非本地项目 runpath。首个 verified slot 写账后原子发布一套运行级 `recovery/`，不按 slot 复制。
  同一个 run seal 记录每份文件的路径、字节、哈希，并封存 `recovery.json` 的闭包身份及 verified slot 集合。`ready` 表示闭包已封存，不表示已实际恢复；旧候选没有闭包，仍可原样复算历史报告。
- 运行 `./bmk --root <搬迁目录> smoke-restore-audit <run_id>` 或调用 `audit_smoke_restore(root, run_id)`；
  目录下只需保留 `results/<run_id>`，不读当前目录的构建、语料、插件表及 schema。命令用 seal 复核
  账本，之后为每个 verified 帧新启一个 Bubblewrap 隔离解码进程。进程只看到该帧、封存的二进制和库、
  暂存输出目录；不挂载宿主 `/usr`、加载器缓存或源输入。按封存的 dtype、shape、原始逻辑字节和
  值/schema 哈希逐项比对。成功报告附 seal 和各帧身份；缺依赖或不一致拒绝，临时输出不留在原 run。
- 恢复只对可信内部运行开放。Linux 内核、兼容 CPU/ISA、支持无网络命名空间的 Bubblewrap 和控制层
  `tsbench` 环境仍是前置条件；闭包不是跨平台或重新分发承诺。该独立审计是测量外验证，不给未恢复、
  未进行 `artifact_each` 或未纳入本候选的首批方法补记资格。

复现本套件的实际恢复和三个负对照（缺解码库、同形异帧、错误 schema 哈希）：

```sh
tools/probe_offline_m1_restore.sh "$CONDA_PREFIX" <含-results-的搬迁目录> <run_id>
```

需在 `tsbench` 环境运行；脚本只读挂载该次 run 与控制层运行时，JSON 证据输出到 stdout。


## v3：原始运行即隔离，不仅是事后恢复

- 覆盖和算子保持 6 × 3 不变。第一次通过水位检查时，在启动任何 slot 子进程前验证并发布本次运行的
  一份共享 ELF 闭包；缺少锁定依赖时，不从宿主搜索库，不重试，账本仍收齐每个 slot 的终态。
  v2 的首次验证后才封存行为和历史报告复算不变。
- 用共享的 `prlimit` + Bubblewrap 启动器分别运行 encode、decode。每个子进程只能看到自身传递 ELF
  依赖、一组只读输入和一个独立可写输出目录。encode 只绑定 canonical 值和 schema，decode 只绑定
  本 slot 的完整 frame，不挂载语料、宿主 `/usr` 或原始构建。每个已启动操作记录输入挂载的字节与哈希；
  报告复算校验其与计划或该 frame 相符、启动会话独立、双向日志封存、worker 输出元数据和恢复验证一致。
- 每操作最多 5 s、每进程地址空间 256 MiB、每文件 256 KiB，禁 core dump；这些不是整个进程树的内存
  或总磁盘上界。墙钟从启动 launcher 到回收 launcher，含 Bubblewrap 的设置与退出。`wait4` 观测的是
  launcher 直接子进程，不是 codec 独占 CPU/RSS；各方向的新 comparison ID 不能和 v2 的诊断混用。
- 用 `tsbench` 从空构建运行 `scripts/smoke.sh <build> m1_lossless_candidate_v3`：
  [单次正式前预检](../../results/8eec7da8e6d743739f86c33b02a8d9cf/derived/report.json) **18/18** 位级验证、
  36 次独立子进程调用，序列化帧共 **280,140 B**、共享闭包另列 **10,069,152 B**。CLI 与 Python
  [生成同一计划](../../results/m1-files-only-20261119-evidence/plan-parity.json)。
  [搬迁审计](../../results/m1-files-only-20261119-evidence/offline-restore.json)只挂载封存运行和控制层，
  报告逐字节复算且 **18/18** 实际恢复；缺库、有效同形异帧和错误期望 schema 均拒绝。
- [负对照](../../results/m1-files-only-20261119-evidence/negative-controls.json)使用测试 worker 检查子进程实际可见的挂载：
  14 个正常产物、真实非零退出、SIGSEGV、超时与运行中的取消各 1。另一次提交故意撤去锁定的 Zstd 依赖，
  同一计划的 18 个 slot 都记录 `dependency_failed`，没有子进程。即使重算封存清单，为 decode 私加原输入的记录也会被拒。
  两次负对照各自封存，不拼入 18/18 正常运行。复现命令：

```sh
cmake --build <build> --target tsbench_m1_isolation_control
"$CONDA_PREFIX/bin/python" -I -B tests/isolation/m1_smoke_files_only.py <build>
```

仍是开发候选：M0 未通过；未进行 M2 匹配重复、资源独占或性能排名，不授正式资格。
