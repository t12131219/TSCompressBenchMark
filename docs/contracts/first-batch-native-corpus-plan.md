# 首批原生真实语料：M0 适用性定义计划

设计 2.8 §14 / 目标 2.5 §4.1 的定义计划。它不替代旧原生候选运行、M0 阶段收据或 M3 的新全量运行。

## 冻结和复核

- 数据使用 [23 文件全语料输入锁](first-batch-full-corpus.md)。规划时完整复核原件、规范身份、行列形状、时间轴顺序和缺失哨兵，不能从后缀、同名旧窗口或未经验证的清单自报数据域推断。
- [逐路线输入政策](../../configs/suites/m3_first_batch_native_v3/real_input_policy_v5.json) 覆盖原生准入清单的全部 36 条路线，以 `selection + route` 绑定来源、原生入口及既有义务。引用首批 Unique 对账和本地合同的摘要，不把历史结果写入新执行账本。
- [r8 冻结计划](../../results/m0-native-corpus-definition-20261119-r8/plan.json) 有 828 个文件—路线适用性决定，另外绑定 180 项必需与 6 项条件义务及其已有输入/条件定义。已有定向用例仍是单独的边界、已知答案和拒绝检查；真实语料和定向用例不互相替代。
- [r8 复核](../../results/m0-native-corpus-definition-20261119-r8/verification.json) 重新生成完整定义并核对内容，而不是只比较客户端传入的 ID。删除决定、重复路线、漏义务和重签后伪造准入均拒绝。r7 更新 CORAD CRD1 验证器的实现身份，范围和分母与 r6 相同；未改写 r6 历史证据。

```sh
/home/fzg/anaconda3/envs/tsbench/bin/python -B bmk native-corpus-plan --out results/<新目录>/plan.json
/home/fzg/anaconda3/envs/tsbench/bin/python -B bmk native-corpus-verify --plan results/<新目录>/plan.json
```

`tsbench.api.plan_native_corpus` / `verify_native_corpus_plan` 与 CLI 共用实现。输出 `runnable=false`、`stage_accepted=false`、`qualification_granted=false`；没有一项被登记为实际运行。

## 定义结果与边界

| 定义决定 | 数量 | 解释 |
|---|---:|---|
| `input_domain_matches` | 724 | 有可指定的表示和范围；不等于已绑定全量驱动、原始域验证器或资源合同。 |
| `outside_declared_domain` | 74 | 23 项 intmult 没有显式无符号数值语义；21 项 Gorilla TV 的源索引没有定义到毫秒的映射；30 项不满足本版 CORAD 多变量门槛。是当前请求的域，不是上游原生库的普遍能力结论。 |
| `condition_not_triggered` | 30 | Zstd/XZ worker 对照输入达不到预声明的工作尺寸，不填充、不据此断定不可并行。真实 worker 活动仍需实际观察。 |
| `unresolved_contract` | 0 | 先前 39 项 CORAD 与 7 项短 Zstd 已有定义；全量执行及阶段收据仍未完成。 |

每个匹配范围给出行、列索引范围、分区、原始任务与 native 布局、估计逻辑字节及输入单元数。V、T+V 和字节任务分开；Gorilla 针对每列实际消费 T，输入工作计数保留重复的 T，整对象逻辑 T 只计一次。Sprintz `f64` 到四个 `u16` 位片、Titchy `f64` 到 `u64` 均显式标记为可逆表示转换；用于 Sprintz query 的结果是无符号位片统计，不是原始 f64 的统计。功能所需的薄表示转换不当成 codec 原生数据类型或 M5 外置服务。

字节 baseline 以规范 V 的 row-major 字节为输入，既不是 CSV 文件压缩，也没有 T 恢复。真流会话独立于 loader 批次；按列记录 ordered state。输入单元估算不是进程数量、实际消耗、产物上界或样本数；全量运行应在一个 run 内复用有界会话，不能为输入单元各交一份收据。条件义务包括 ALP AVX512BW，仍需兼容主机、真实 decimal 工作和独立恢复；CORAD 的旧质量拒绝不变。原生配置绑定、质量预算、适用直接调用、独立恢复和执行资源/清理政策仍是新版验收门槛。

## 训练范围与 ZFP array 质量定义

- Huff0 和 Zstd 字典只消费同文件、已锁定 `train` 分区的有界字节前缀；`test` 单独绑定并按配置拆帧。估算是训练输入消费字节加留出帧输入字节，训练按一次提交计，不按训练样本数计。训练产物、绑定资产与额外往返不在输入估算里；实测必须单独计费。不读取 `development` 或 `test` 扩充训练，不填充、不跨文件拼接，原生训练失败不回退。
- Zstd 的训练前缀不足 8 KiB 时选短档：32 B 连续样本、至少 8 个且最多 128 个、字典容量 256 B；不足样本下限不填充。标准档仍用容量 2,048 B。档位只由编解码前已锁的 train 区间决定，不根据留出结果选择。[短档开发探针](../../results/m0-zstd-short-dictionary-20261119-r1/report.json) 实际训练全部 7 项，7/7 留出帧只挂载封存字典和帧独立还原，7/7 缺字典预期拒绝。产物记实际大小（字典为 192 或 256 B），不把小载荷或可恢复本身等同于压缩收益或阶段资格。
- ZFP fixed-rate array 使用 rank-1 `f64` 单列布局，独立于 field 格式；每个连续可用范围均衡切成 8–4,096 行的窗口。输入审计按列定位气象文件 3 列中的 81 个哨兵；仅跳过这些位置及因哨兵分隔而不足 8 行的 10 个单列位置，未改写原件，也未把整份气象文件记为不适用。气象计划明确不覆盖全量行列位置。
- 用同一窗口的原始值定义点与跨块范围更新。阵列前后各须独立重开；每个输出值与未修改/精确修改后的原始 `f64` 参考比较，接受限为 `abs(actual − expected) ≤ max(1e-5, 1e-6 × abs(expected))`。配置请求 18 bit/value，计划期望对齐后有效 32 bit/value，须由原生运行核验。预算不是固定率的误差保证；超限应拒绝，不换率重试冒充成功。适用时验证未接触块的原生码流和恢复值不变。r4 仅冻结范围与验收约束，尚未接入可变输入驱动、质量验证执行和资源/恢复绑定。

## PBEPLA 渐进与回放

- r5 为两条路线绑定完全相同的有限 `f64` 单列窗口。连续合法范围均衡切为 1–4,096 行；只排除气象原始的 81 个缺失哨兵，不跨哨兵拼接、填值或丢弃邻接有限记录。框架不缩放输入。三个请求界固定为原始数值单位下的 `16 / 4 / 1`；它们是本工作负载的验收参数，不是各数据源的科学精度要求，也不用于跨不同单位排名。
- 每层分别封存前缀、独立恢复并核验 `精确最大绝对误差 ≤ 有效界 ≤ 请求界`，报告有效界、观察误差、增量载荷和前缀完整字节。单次 native 回放不等于单遍在线：应记录实际源遍数、数值重试、首写和逻辑暂存，并同批方法对照完整原生帧字节。不得发现质量或资源失败后放宽配置、丢层或改用批输出。
- [双输入开发探针](../../results/m0-pbepla-real-corpus-probe-20261119-r2/report.json) 按 r5 窗口绑定 Economics-17 `channel_1` 的 193 行与 national-illness `AGE 0-4` 的 966 行（仅投影一列），重用锁定的 native/ABI 验证器。两输入分别独立执行渐进和 callback 回放，4/4 产品、12/12 仅封存前缀恢复通过。两组回放均读源 3 遍、无数值重试，与同次批载荷逐字节一致。该探针不是全量入口或阶段证据；全量仍须绑定有界文件会话、非零重试的记录/复算及资源政策。

## CORAD 训练、部署与留出

- 13 个多变量输入的全部值列按原顺序组成 346 个互不重叠的列组，每组 2–8 列；这是独立建模的投影，不当作全列联合建模。每组仅用 train 分区最早的连续、无缺失哨兵的 129 行；训练向量只取完整 4 行 tricklet，余下的 1 行不伪造向量。逐组列出未选 train 范围、开发分区及 test 哨兵影响的范围。
- C11 LARS 与原样 Source 桥为两个不同生产者。推理须从同一次执行中按生产者、训练输入、列序和模型字节身份加载相符的已冻结模型；缺依赖、训练失败或列序不符不回退旧部署。新模型与旧 CORAD 质量拒绝是不同证据，既往拒绝必须保留。test 的其余连续范围逐帧接收（每帧最多 4,096 行），不跨哨兵拼接。运行绑定时验证 train 最后时间小于 test 首时间，trainer 不得挂载留出值。
- 质量门槛仅由训练列的精确均值常量预测器给出，按列锁定 train 最大绝对误差与 MSE；每列、每项均须达标，`threshold=0.9` 不是误差界。保留超限恢复及量化证据，不能调参掩盖拒绝。训练义务引用推理产物而不重复累计留出成本。定义不能推断质量或训练成功。
- [r7 双输入运行](../../results/m0-corad-real-corpus-20261119-r1/run/report.json) 从新构建运行 `national-illness` 和 `etth1` 的各一个 7 列组。两份 C11 和两份 Source 模型实际训练并封存，相应的 194 行、3,484 行 test 帧分别用各自产生的模型编码。4/4 新进程仅挂载完整 CRD1 帧，恢复字节与独立解释器一致；4/4 同时因超出预声明的 train-only 质量门槛而拒绝。拒绝保留帧、实际误差和模型依赖，不进入性能比较。探针使用一份账本，尚未合并进 36 路线正式提交，也未运行其余 344 个列组。

## M1 双真实输入候选闭环

[候选计划](../../results/m1-real-two-inputs-20261119-r1/plan.json) 用同一公共入口运行 Economics-17 和 Bitcoin-1 的两个 31 行 `test` V 切片，方法均为 raw-store、Zstd、ALP。run `03c2283823a34e0a9db3930b98333e0d` 的 [报告](../../results/m1-real-two-inputs-20261119-r1/report.json) 为 6/6 `artifact_each` 验证通过，[独立恢复](../../results/m1-real-two-inputs-20261119-r1/restore-isolated.json) 为 6/6，仅挂载封存资产。[控制记录](../../results/m1-real-two-inputs-20261119-r1/controls.json) 核对 CLI/API 计划一致、只换数据配置不改方法和构建、T 列冒充 V 时未发布计划或 run、报告复算逐字节一致。该候选复用已有构建，没有绑定新版 M0 收据或授予新版 M1 验收。

## M0 更新版收据

输入锁与 r8 适用性定义已由 [`M0 real-corpus 收据`](../../results/m0-real-corpus-acceptance-20261119-r1/receipt.json) 接纳。该收据只证明绑定内容可复核：不执行 codec，不授予 36 条路线的原生资格，也不替代后续统一 M3 全量运行。

## M1 更新版最小闭环

[M1 real-corpus 收据](../../results/m1-real-r8-20261119/receipt.json) 已绑定上述 M0 收据和 r8 定义，在 Economics-17 与 Bitcoin-1 两个不同真实输入上完成 raw-store、Zstd、ALP 的 6/6 `artifact_each` 验证及 6/6 sealed-files-only 独立恢复。该收据仍是最小无损闭环，不代表 36 条路线原生资格或正式性能准入。
