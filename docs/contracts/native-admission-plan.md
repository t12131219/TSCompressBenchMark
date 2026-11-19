# M0 冻结定义：首批原生准入计划

`bmk native-admission-plan` 与 `tsbench.api.plan_native_admission(root)` 生成同一份内容寻址定义。
它把 [v1 原生检查](first-batch-native-requirements.md) 与 [v2 域及恢复政策](../../configs/suites/m3_first_batch_native_v2/admission.json)
闭合为 **12 项选择、36 个原生操作组、180 项必需 + 6 项条件义务**。当前 180 项必需义务均关联已有输入定义，共 215 个不同
case；另有 26 项明确排除的原生主张（不从 M5 服务分母扣除）。不接受少组、重复路径、陌生协议、跨路径挪用输入或未声明参数。

- 每组绑定 `selection_id`、源码包哈希、target、原生入口及域。冻结的域限于该组引用的输入与明确反例，不把源码可接受的所有类型或参数自动视为已经验收。
  每项义务绑定稳定 ID、用例定义及来源 bundle ID；真正的正式 driver/build/限额仍须逐项绑定。
- 质量分别按原始域位级、精确无符号逐通道聚合、按用例误差、冻结留出实证和训练 solver/桥接 oracle 判定，不能互换。
  ZFP 固定 rate、precision、accuracy 各自取已声明的原始域界，reversible 子项仍按位；array 恢复核对重新打开后的原值和更新。
  PBEPLA 每个前缀都须满足 `原始域最大绝对误差 ≤ 实际有效 eps ≤ 请求 eps`，replay 另验证读遍数和写入行为。
  CORAD 锁住两个模型配置、同一留出窗和 train-only 逐列界；每个部署分别判定，超界即拒绝比较。训练 oracle 通过也不授预测质量资格。
- 访问完成条件和恢复保留要求按协议独立定义。完整页需要 file/chunk 元数据，字典/表路线需要对应资产和错/缺资产的拒绝证据；
  原生 span 必须 drain/finish，不认首次输出为整任务完成；可变 array 要 flush/reopen，扫描/索引要保存实际逻辑读取范围。
  正式资格要求 `artifact_each`、仅凭产物和所声明依赖新进程恢复；完整序列化产物及必需资产全部计费。回收、访问资源上限和隔离闭包未正式落地的部分保留 `unbound`。
- 六项条件只允许在**所选构建、当前宿主、对应负载、实际执行**的同一运行证据上判定。ALP AVX512BW 能力继续保留，不用本机不可执行来删除路线。
  初始环境定义记录 Linux x86_64/CPU/glibc、GNU 11.4.0 Release、CMake 3.22.1、`tsbench` 锁和隔离约束；这不是宿主能力证明，也不是正式性能环境。
  正确性／隔离／兼容回归与受控主机性能回归分开。

```sh
# 已激活 tsbench
./bmk native-admission-plan --out /tmp/native-admission-plan.json
# 同次预检包含 Huff0 的对应 portable 对照；输出目录须先创建且为空。
tools/probe_offline_m0.sh --with-huff0-portable "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录>
```

`native-plan` 直接内嵌相同定义，整个预检仍只有一次提交、一个 `run_id` 和一份主账本。
`native-report` 从封存计划及终态验证定义身份，另按实际证据报探针、条件观察和 CORAD 原始域质量结果。
**定义 `runnable=false`、资格为 0；外围预检可执行但不授资格。** 既不把历史开发结果拼进新 run，也不把 `not_run`
改为不适用。正式执行仍需各义务的 driver/build 绑定、可执行的工作/资源上限、证据留存预算、逐产物独立恢复与阶段退出核验；
研究性能另行冻结比较计划。本定义保留原有 M0–M4 目标和 M5 的 204/264 分母。

2026-11-19：[准入定义](../../results/m0-native-admission-20261119-r3/native-admission-plan.json)与[预检报告](../../results/m0-native-admission-20261119-r3/native-report.json)
使用相同定义 ID；`tsbench` 禁网预检 25/25 探针通过，新旧报告在不挂载构建、项目配置或语料时均逐字节复算。
[负测](../../results/m0-native-admission-20261119-r3/admission-negative-controls.json)拒绝拿定义执行、将定义升格和移除一项条件。
报告显示 CORAD 两个部署仍拒绝 held-out 质量，ALP AVX512BW 待兼容宿主；这些状态不是从历史报告填入。

后续执行证据单列：[Gorilla #7 `tv-batch` 执行候选](gorilla-batch-execution.md)挂接一组义务及构建与限额，完成 8 帧逐产物恢复与 1 项边界拒绝。
这是单独的运行计划，不修改本文件所述冻结定义、`formal_execution_bindings` 或资格状态。
2026-11-19 后续同组 V2 执行在一个账本内加入直接 C 双向对照，4/4 项有候选证据。仍属独立的候选计划，不改全量 36 组的正式执行状态。

[ALP Auto / Zstd baseline](linear-batch-execution.md)复用了同一批执行/恢复层，一次提交覆盖两组 14 项候选义务。两组并未自动改变全量正式准入定义、ALP 后端的条件或其余路线的状态。

同一入口后续由 `extended-v1` 独立执行 ALP Auto、Zstd baseline、Titchy batch、ZFP field-baseline 的 23 项候选义务；`extended-v2` 加入 XZ baseline 后一次执行五组 28 项，使用同一准入定义中的义务 ID。XZ 档仅提高其自身地址空间上限，实际测到 preset 6 的后台 job 和 decoder 内存限额拒绝。两次均从封存产物独立恢复，不合并报告；执行记录见[原生批执行合同](linear-batch-execution.md)。定义的 36 组与 180+6 分母、`formal_execution_bindings=0` 和资格状态不变。

`extended-v3` 在同一计划内验证 selection #11 的两个独立 pcodec 批入口，合计七个操作组、39 个候选义务。规划器按 `(selection, route)` 绑定，C NativeAuto 的 f16 拒绝与 SourceAuto 的 f16 正常恢复不互相替代。独立审计从封存的 SourceAuto f16 产物恢复原值，实际复跑 C 双入口拒绝；见[七路线执行合同](linear-batch-execution.md#七路线-extended-v3pcodec-sourceauto--c-nativeauto)。原生准入定义分母和正式状态仍不变。

`extended-v4` 再加入 #11 两条 wrapped page 组的 12 项候选义务，单次覆盖九组 51 项。区分实际工具驱动和此前的 ABI 单帧插件，封存并计费每个分页恢复依赖；仍使用一次提交与一份主账本。报告复核强制要求两页组的义务和槽位归属完整，禁止移除或把累计配额义务挂到 Source 页。见[分页执行合同](linear-batch-execution.md)，未改变 180 + 6 分母或正式资格。

`extended-v5` 首次把 Gorilla C11 批对照、既有批/分页路线及**完整原生分母**放在同一冻结执行计划中。新增执行视图把 10/36 组的 55 项必需义务关联到同一构建、逐产物有界 driver 和恢复程序闭包，另列 125 项未绑定必需义务与 6 项待同次验证条件（详见[执行与复跑](linear-batch-execution.md#十路线-extended-v5同次-gorilla-c11-对照与全分母绑定视图)）。冻结定义和 `formal_execution_bindings=0` 不变；绑定视图是正在建设的执行候选，不是 M0 通过或 M3 资格收据。

`extended-v6` 继续将 SElf* 顺序批和原生逐值两组接入该统一绑定视图，实测 12/36 组、64 项候选必需义务。余下 116 项必需与 6 项条件保持未绑定；`formal_execution_bindings=0` 和正式资格不变。详见[SElf* 合同](selfstar-native.md)和[同次运行](../../results/m0-ordered-selfstar-20261119-r1/report.json)。

`extended-v7` 在同一冻结构建和主账本中加入 #29 Huff0 FEC1 / ETB1 两条候选路线，实测 **14/36 组、75/180 项必需义务**。余下 **105 项必需、6 项条件**未绑定。Huff0 的同次 portable 对照仍不在该执行套件；独立预检不能填入此账本。详见[Huff0 恢复与模型绑定合同](huff0-native.md#extended-v7同一执行计划中生成验证并独立恢复)和[联合报告](../../results/m0-huff0-unified-20261119-r2/report.json)。分母、`formal_execution_bindings=0` 和正式资格不变。

`extended-v8` 在同一冻结计划与主账本中新增 #19 Sprintz-FIRE `fire-batch` / `query`，实测 **16/36 组、85/180 项必需义务**。余下 **95 项必需、6 项条件**未绑定。查询仅使用 SFB1 实跑，原值 oracle 在进程外校验，无符号归约和全量恢复各有独立操作。见[执行合同](sprintz-fire-native.md#extended-v8独立批恢复与压缩域查询)和[联合报告](../../results/m0-sprintz-unified-20261119-r2/report.json)。分母、`formal_execution_bindings=0` 和正式资格不变。

`extended-v9` 在同一冻结计划和主账本中加入 #85 Titchy `loaded-file-access` / `batch-range`，实测 **18/36 组、96/180 项必需义务**。11 项新增候选义务分别核对只挂载 backing 的原生返回、按请求的 callback 读账，以及同一损坏在惰性校验和整容器校验中的差异。余下 **84 项必需、6 项条件**未绑定，含 #85 `packet-stream`。见[执行合同](titchy-native.md#extended-v9复用索引与无状态范围进入同一冻结执行计划)和[联合报告](../../results/m0-titchy-unified-20261119-r1/report.json)。未更改分母、`formal_execution_bindings=0` 或正式资格。

`extended-v10` 在同一冻结计划和主账本中加入 #85 Titchy `packet-stream`，实测 **19/36 组、102/180 项必需义务**。六项新增义务复用同一原生 slot，覆盖 finish 前排包、背压和缓冲重试、尾部零填充、reset、截断/累计配额拒绝及只挂载 TSTR + TSC1 的独立恢复。余 **78 项必需、6 项条件**未绑定。见[流合同](titchy-native.md#extended-v10原生-packet-流进入同一冻结执行计划)和[联合报告](../../results/m0-titchy-stream-unified-20261119-r2/report.json)。未更改分母、`formal_execution_bindings=0` 或正式资格。

`extended-v11` 在同一冻结计划和主账本中加入 #11 pcodec `intmult`，实测 **20/36 组、106/180 项必需义务**。四项新增义务区分请求 TryIntMult 与实际 IntMult/Classic、整数大基数、只用完整裸帧的末尾排空及三个原生拒绝。余 **74 项必需、6 项条件**未绑定；未更改分母、`formal_execution_bindings=0` 或正式资格。见[执行合同](pcodec-native.md#extended-v11tryintmult-接入统一执行)和[联合报告](../../results/m0-pcodec-intmult-unified-20261119-r1/report.json)。

`extended-v12` 在同一冻结计划和主账本中加入 #7 Gorilla C11 `append-resume` / `iterator`，实测 **22/36 组、114/180 项必需义务**。八项新增义务在四槽验证独立 snapshot/续写、扫描与复制、迭代/向前 seek 和尾随错误。余 **66 项必需、6 项条件**未绑定；未更改分母、`formal_execution_bindings=0` 或正式资格。见[执行合同](gorilla-tv-native.md#extended-v12原生续写逐行迭代与工作量进入同一执行计划)和[联合报告](../../results/m0-gorilla-state-unified-20261119-r2/report.json)。

`extended-v13` 在同一冻结计划和主账本中加入 #40 `zstd-session` 与 #39 `xz-session`，实测 **24/36 组、124/180 项必需义务**。十项新增义务在两个槽核对真实原生跨度、两方向 reset、finish 排空、配置与拒绝；四份裸帧先独立恢复，再用恢复的原字节复跑状态序列。余 **56 项必需、6 项条件**未绑定。分母与正式资格不变。见[执行合同](lzbench-native-operations.md#extended-v13两个原生字节会话接入统一执行)及[联合报告](../../results/m0-lzbench-session-unified-20261119-r2/report.json)。

`extended-v14` 加入 `zstd-dictionary`、`zstd-workers` 与 `xz-workers`，同一账本实证 **27/36 路线、135/180 项必需义务、2/6 项运行条件**。两项条件分别绑定 Zstd 编码实做工和 XZ 分方向实做工；由同次实测和独立恢复判定，不从构建声明推断。余 **45 项必需、4 项条件**未绑定，定义分母、`formal_execution_bindings=0` 与正式资格不变。见[字典和 worker 合同](lzbench-native-operations.md#extended-v14字典与原生-worker-对照接入统一执行)及[联合报告](../../results/m0-lzbench-profiles-unified-20261119-r3/report.json)。


`extended-v15` 将 ALP #9 `decode-backends` 的四项必需义务接入同一计划；**28/36 路线、139/180 项必需义务**有同次候选证据。四项已绑定条件中，AVX2、Zstd worker、XZ worker 有同次候选证据，已构建的 AVX512BW 为 `pending_supported_runtime`。仍有 **41 项必需义务**（ZFP 三路线、PBEPLA 两路线、CORAD 三路线）和 **2 项条件**（ZFP OpenMP、Huff0 BMI2）未绑定。见 [ALP 同帧合同](alp-native.md#extended-v15同一-aln1-裸帧的后端对照)及[统一报告](../../results/m0-alp-decode-unified-20261119-r2/report.json)。这不改变阶段状态或正式资格。


`extended-v16` 同次接入 ZFP #31 多模式 field、OpenMP 编码和固定率 array，统一候选实证达到
**31/36 路线、154/180 项必需义务**。OpenMP 条件依赖 2 个实际参与编码的 OS TID、相同 field
及调用线程解码，不由线程配置推断。仍有 **26 项必需义务**（PBEPLA 两路线、CORAD 三路线）和
**1 项未绑定条件**（Huff0 BMI2）；已绑定的 ALP AVX512BW 仍待兼容宿主。混合有损/无损的运行使用新的
计划/报告 schema，正式资格未改变。参见 [ZFP 证据合同](zfp-native.md#extended-v16三条原生路线纳入统一账本)
与[统一报告](../../results/m0-zfp-native-unified-20261119-r1/report.json)。

`extended-v17` 同次加入 PBEPLA-RR #87 的渐进和三遍回放（空输入一遍）两条路线：**33/36 路线、163/180 项必需义务**
有候选实证。新加入的 13 槽中 11 槽独立恢复、2 槽为预期拒绝；逐层验原值误差，回放只与同账本的原生批产物比较。
其余 **17 项必需义务**均属于 CORAD 三条路线；Huff0 BMI2 是唯一未绑定的运行条件，已绑定的 ALP AVX512BW 仍待兼容宿主。
见 [PBEPLA 执行合同](pbepla-native.md#extended-v17渐进与回放纳入同一冻结执行)和
[统一报告](../../results/m0-pbepla-native-unified-20261119-r3/report.json)。分母、`formal_execution_bindings=0` 与阶段状态不变。

`extended-v18` 同次绑定 #80 `corad-inference`，达到 **34/36 条绑定路线、169/180 项绑定必需义务**；
其中 **168 项**为 `verified_candidate`，一项由留出质量界实际判为 `quality_rejected`，没有升格为通过。
两份冻结部署的六个帧均可独立恢复，质量仍不具可比性。还有 **11 项必需义务**（CORAD C 与 Source 训练）和
**1 项运行条件**（Huff0 BMI2）未绑定；ALP AVX512BW 已绑定但待兼容宿主。见
[统一报告](../../results/m0-corad-inference-unified-20261119-r2/report.json)及[推理合同](corad-native.md#extended-v18同一账本里的推理独立恢复与质量拒绝)。不改变阶段状态和正式资格。

`extended-v19` 同次加入 #80 C11 和 Source 训练：**36/36 个操作组、180/180 项必需义务均已绑定并执行**；
其中 **179 项候选通过、1 项 CORAD 冻结推理质量拒绝**。两条新路线的 11 项检查均候选通过，三份新训练模型的评估帧
独立恢复，不替换冻结部署。条件义务仍为 **4 项候选通过、1 项 ALP AVX512BW 待兼容宿主、1 项 Huff0 BMI2 未绑定**。
[统一报告](../../results/m0-corad-training-unified-20261119-r2/report.json)与[独立恢复](../../results/m0-corad-training-unified-20261119-r2/restore.json)。
全必需项绑定不等于达到质量要求、阶段通过或正式资格。

`extended-v20` 将最后一项未绑定条件 Huff0 BMI2 加入同一计划和主账本，不新增槽或把旧探针结果拼入本次运行。
[统一报告](../../results/m0-huff0-bmi2-unified-20261119-r1/report.json)与[独立恢复](../../results/m0-huff0-bmi2-unified-20261119-r1/restore.json)
显示 **36/36 路线、180/180 必需项、6/6 条件项已有候选执行绑定**，174 槽独立恢复、26 槽符合预期拒绝。
必需项仍为 **179 项候选通过、1 项 CORAD 冻结推理质量拒绝**；条件项 **5 项候选通过、1 项 ALP AVX512BW 待兼容宿主**。
Huff0 两个同名 DSO 的独立加载闭包、同帧/同表实际挂载与调用记录见 [Huff0 对照合同](huff0-native.md#extended-v20在主账本绑定同次-bmi2portable-对照)。
只读复用上次已核验的主构建，不复用其运行结果；当次构建 OFF 闭包。候选绑定零缺项不是正式准入，M0 仍未通过，正式原生资格仍为 **0/36**。

同一份封存运行已通过 [资格证据审计合同 v1](native-qualification-evidence.md) 重核，补齐逐槽的实际构建、
验证器与隔离恢复关联。它不改变原计划的 `formal_execution_bindings=0`，也不签发阶段收据。
