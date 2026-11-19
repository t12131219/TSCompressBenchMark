# M0 对账：2026-11-18 至 2026-11-19 开发批次

**M0 已通过（冻结合同与独立工程骨架）；M1–M4 尚未正式验收，M5–M6 尚未开始。** 本文记录现有证据的作用域，
不是原生资格收据。M0 阶段收据为 [receipt.json](../results/m0-acceptance-20261119-r2/receipt.json)，只确认冻结与工程骨架，不授予 M3 原生资格。当前 benchmark 原生运行资格 **0**；首批 12 项全部待正式运行资格，
36 个已索引操作组均未取得正式资格（`not_run`）；**36/36** 已有源码复核和至少一项可重跑的开发诊断。这不等于组内必需边界全部通过，也不等于全部接入 worker。
有效服务 204 展示格 / 264 原子关系展开为 564 个场景义务，全部未运行、0 绿。
下方“已记录的证据差异”和历史批次段落保留各次运行当时的状态文字；当前阶段结论以本页顶部和 `m0-acceptance-20261119-r2/receipt.json` 为准。

[配方合同 v1](contracts/recipe-tv.md) 已实接 T/V 开发执行器：12 槽均在同次禁网迁移运行并脱离原输入恢复；
保留类型、逆图与费用/资源拒绝。随后 [服务配方解析](contracts/service-recipe-resolution.md) 对全部 564 项给出
逐槽的已知方法/构建与合同不匹配或未绑定原因：24 项同源候选不兼容、540 项未绑定、0 项正式执行。
仍缺完整阶段的独立性与准入证据；不要求在 M0 提前完成 M5 的服务执行。
[加载器可插拔性](contracts/source-provider-pluggability.md) 已完成禁网迁移验证：独立测试新增、撤下注册、
不兼容更新和实际移除，16 个产物在无原输入和加载器的封存解码闭包中恢复。尚不覆盖全部组件和正式任务。
[原生资格证据审计](contracts/native-qualification-evidence.md) 已从统一封存运行重核 36 个操作组和 186 项义务；
174 槽重新恢复，26 个原输入拒绝中 6 个重新执行、20 个只核对原账本。候选不能代替正式提交，历史质量拒绝和 ISA 条件保留。
[统一提交前闸门](contracts/native-submission.md) 已在真实入口绑定完整分母、过程预算、留存空间和启动水位；[M0 阶段收据](../results/m0-acceptance-20261119-r2/receipt.json)已复算来源、语料、服务分母、空构建和封存恢复； 前置审计固定为 `third_party/provenance/m0-native-qualification-audit-20261119-r2.json`，不将其改写为阶段接纳。
新一份禁网提交在一个账本完成 200 槽并独立恢复 174 个产物，真实空间不足和缺锁定构建时不发布运行。
空构建补验已在 [m0-native-empty-v20-20261119-r1](../results/m0-native-empty-v20-20261119-r1/) 完成：17/17 CTest、200 项 Python 回归、同一 200 槽计划和 174/174 独立恢复，未复用已有 build。`check-corpus --version 3 --parse` 另核对 6 个来源簇、18 个分区、222,574 行和 10,692,822 B 存储资产。
该闸门仅约束 M0 预检；阶段收据仍不授予原生资格，也不提供操作系统总作业配额。


| M0 退出条件 | 当前证据与版本 | 缺口 | 下一项检查 |
|---|---|---|---|
| 冻结选择与供应来源、实际入口 | 本地来源锁、Unique CSV 和 manifest 冻结 12 项/11 包；36 组已全部绑定统一预检。[原生功能用例合同](contracts/first-batch-native-requirements.md) 将 36 组展开为 180 个必需项、6 个条件项及 26 条不适用主张；180 个必需项全部绑定 215 个开发用例；[准入定义](contracts/native-admission-plan.md)另绑定逐组域、质量、访问完成和恢复保留 | 6 个条件项已同次判定：5 项满足开发检查，ALP AVX512BW 待兼容宿主；仍须正式执行并判定。两份冻结 CORAD 部署在当前经验界上拒绝。已有开发用例不是正式执行绑定和资格 | 把每项定义关联真实正式 driver/build，冻结可执行资源上限和独立恢复闭包；拒绝结果不得被开发探针状态覆盖 |
| 工程资产闭包、空缓存和路径迁移 | 新增 [空构建 extended-v20](../results/m0-native-empty-v20-20261119-r1/)：空 `build/`、禁网、17/17 CTest、200 项 Python 回归、200 槽统一提交和 174/174 独立恢复；[语料闭合审计](../results/m0-corpus-closure-20261119-r1/corpus-check.json)确认 6 个数据集、18 个分区、222,574 行和 10,692,822 B 存储资产，[特征报告](../results/m0-corpus-closure-20261119-r1/corpus-feature-report.json)列出真实/合成覆盖与明确 gap；前置构建/恢复闭包由[提交合同](contracts/native-submission.md)锁定 | 运行闭包和复制语料已补实；仍不能把 CORAD 当前质量拒绝改成通过，也未形成 M0 阶段接纳或跨平台发行承诺；全部服务矩阵仍是 M5 范围 | 继续把正式支持环境、质量拒绝、特征 gap 与待补验项写入阶段收据，不用候选 PASS 替代接纳 |
| 公共 API/ABI、增删替换、配置扩展 | `bmk` 与 `tsbench.api` 共用解析、计划和开发执行；C/C++ ABI 与原有 14 个开发插件有实际探针（12 个算法条目，pcodec 两方法，另有 raw-store 对照）；另有两个独立 Gorilla 派生插件的开发验证，不增加原生分母。CMake 由 manifest 选择构建目标，且[禁网实测](../results/m0-catalog-pluggability-20261118-r4/pluggability/audit.json) codec 新增、同任务替换、禁用/移除、配置扩展和不兼容格式升级；对旧格式实际保留旧二进制恢复路径 | 真实可插拔回归限单列 f64 小型无损任务与测试 codec；未覆盖所有组合、正式方法套件或所有选定算法的版本兼容性 | 沿同一生命周期扩展 loader/路由/服务等组件的配置和交付用例 |
| 完整阶段计划与拒绝行为 | [M0 统一原生预检](contracts/m0-native-preflight.md) 冻结 36 组与 24 个基础开发探针（含派生角色回归；启用 Huff0 portable 对照时为 25 个），一次提交、单账本、独立复算；拒绝缺组、配置或构建失配，并记录跳过／取消／缺证据等终态。强制留存方法边界的 12 个恢复帧、Titchy 的 12 份批封装、1 个访问留样及 TSTR/TSC1、ZFP 的 32 份 field/OpenMP/array 及原值证据、Sprintz 的 9 份 SFB1 与 4 份 worker 封装、pcodec 的 25 份批帧、8 份分页恢复依赖与 3 份 IntMult 裸帧、PBEPLA 的 29 个前缀和配套数据、CORAD 推理共享原值和六份帧及训练的 17 份用例材料、批计时对照的八份参考帧、Gorilla 的九份留存帧、SElf* 的九份封装、十份状态对照、两份原生上限块与一份气象原值、Huff0 的五份 FEC1 封装、六份模型、十四份 ETB1 块与两份气象原值、ALP 的九份帧及气象尾块原值和 Zstd/XZ 的十八份成功帧、一份负向帧和一份字典。M1 候选冻结 6 case×3 方法，v2 还保存新进程墙钟诊断。M5 草案仍不可执行，分母 204/264 | M0 已可执行候选预检，但不是完整正式合同或收据；M1 仅功能预检；M5 尚无逐原子 case×方法×数据×配置锁 | 在统一入口上补齐正式 M0 语料、适用条件、验证、测量、留存及依赖闭包，再依阶段推进 |
| 数据/质量/访问/测量/字节及留存政策 | [v3 语料](contracts/first-batch-real-corpus.md) 绑定 222,574 行、6 来源簇、18 分区，六个领域都有资产；范围计划另绑定画像政策和 17 个可再生成合成资产。v1/v2 canonical 身份不变。[方法边界](contracts/first-batch-method-boundaries.md) 固定三条批路线的开发用例及资源拒绝；新增两域仅定向验证 ALP 与 Zstd 的 V 路线；[Titchy](contracts/titchy-native.md) 冻结一个交通窗口的访问正确性和逻辑读预算；[PBEPLA](contracts/pbepla-native.md) 冻结逐层误差、前缀及多遍 replay 计费；[测量政策](contracts/m0-measurement-policy.md) 冻结验证强度下限、进程候选边界和原生稳态／冷上下文批诊断 | 语料仅有领域覆盖。已备的掩码、新 dtype 和布局未按所有适用方法验证。缓存内外、其他资源档、质量/访问限额及正式保留/恢复合同仍待覆盖；功能和研究套件仍需各自正式计划 | 按画像缺口和已确认原生入口，逐组锁定必需、条件适用、不适用的用例及成本、验证器、保留样本 |
| 实现忠实性、直接调用对照与支持平台 | 三方法一次执行 16 个对照用例（14 个恢复一致、2 个按合同拒绝）；原生 payload 差分与同工作对照分开；来源成员、编译命令及二进制哈希可查。当前开发构建在 Linux x86-64、Conda `tsbench`（Python 3.11.5）、GNU 11.4.0、CMake 3.22.1、Rust/Cargo 1.94.0 上通过 | 未完成所有路线的适用上游/差分/已知答案，也未冻结正式支持环境与系统化测量；开发诊断不授资格 | 开始逐算法核验实义；为 M1 固定原生入口、验证器、测量边界和对照用例 |

## 已记录的证据差异

- [首批服务用例定义 `first_batch_service_v4`](contracts/first-batch-service-scope.md)：12 个选项、22 项原子要求原样保留，**204 展示格 / 264 原子关系**展开为 **47 场景 × 12 = 564 项义务**，其中 132 项要求预期拒绝。真实跨格式副本逐列对上同一冻结语料窗口；绑定四类 T/V 恢复任务、训练三分区、场景资源上限和计费范围。`tsbench` 禁网迁移环境不挂载 Unique、原构建和原运行；[计划复核](../results/m0-service-scope-20261119-r2/verification.json)、CLI/API 一致性和五项负向/边界合同测试通过。尚未绑定实际合格 recipe、build、域验证器或执行，564 项仍未运行；M0 不签通过。
- [条件全部绑定 `extended-v20`](../results/m0-huff0-bmi2-unified-20261119-r1/report.json)：Huff0 BMI2 加入同一次统一候选执行，**36/36 路线、180/180 必需项、6/6 条件项**均有绑定。**200 槽中 174 槽独立恢复、26 项预期拒绝**。Huff0 主构建和 portable 构建分别实传 `1` 与 `0`，各完成 FEC1 4X／ETB1 1X／ETB1 4X **3／4／4** 次 Huff 解码，九对同帧/同表恢复一致。复用 v19 的禁网空构建（当次 17/17 CTest）仅限只读原生二进制；v20 新建 OFF 闭包、重跑 177 项 Python 测试并重新提交全套，补两项条件判定回归后 [179 项 Python 测试通过](../results/m0-huff0-bmi2-unified-20261119-r1/python-postcheck.log)。CLI/API 同计划，报告逐字节复算，[独立恢复](../results/m0-huff0-bmi2-unified-20261119-r1/restore.json)不挂载原构建及原语料；[Huff0 负测](../results/m0-huff0-bmi2-unified-20261119-r1/huff0-reseal.json)全部拒绝。CORAD 的冻结质量拒绝和 ALP AVX512BW 待兼容宿主状态不变；M0 未通过、正式资格仍为 **0/36**。
- [三十六条绑定路线 `extended-v19`](../results/m0-corad-training-unified-20261119-r2/report.json)同次加入 CORAD C11 与 Source 训练，补齐最后 11 项未绑定必需义务：**200 槽、174 槽独立恢复、26 项预期拒绝；36/36 路线、180/180 项必需义务**均已执行，**179 项候选通过、1 项冻结模型质量拒绝**。两个 C11 fit 在同一 seed 下模型一致；两次原样 Source fit 的字典不同，三份评估帧均独立恢复。禁网迁移空构建、**17/17 CTest、177 项 Python 测试**通过；CLI/API 同计划，报告逐字节复算。[恢复审计](../results/m0-corad-training-unified-20261119-r2/restore.json)不挂载原语料及原构建。Huff0 BMI2 仍未绑定，ALP AVX512BW 保留、待兼容宿主；M0 未通过，正式资格仍为 **0/36**。
- [三十四条绑定路线 `extended-v18`](../results/m0-corad-inference-unified-20261119-r2/report.json)同次新增 CORAD 冻结模型推理：**198 槽、172 槽独立恢复、26 项预期拒绝**；**34/36 路线、169/180 项必需义务**已绑定，**168 项候选通过、1 项质量拒绝**。两份部署的六个帧均通过 C11 直调比对和独立恢复，但两份模型都超出预声明留出质量界。禁网迁移空构建、**17/17 CTest、177 项 Python 测试**通过，CLI/API 同计划，报告逐字节复算。[独立恢复](../results/m0-corad-inference-unified-20261119-r2/restore.json)不挂载原语料或原构建。余 **11 项必需义务**（CORAD 两条训练路线）、**1 项未绑定运行条件**（Huff0 BMI2）；ALP AVX512BW 待兼容宿主。M0 未通过，正式资格仍为 **0/36**。
- [三十三条路线 `extended-v17`](../results/m0-pbepla-native-unified-20261119-r3/report.json)同次新增 PBEPLA-RR `pbepla-progressive` / `pbepla-replay` 的九项必需义务：**197 槽、171 槽通过独立恢复、26 项预期拒绝；33/36 路线、163/180 项必需义务**有候选证据。29 个批前缀加 7 个回放前缀，各自独立恢复；非空回放读三遍，首写在第三遍，不算在线单遍。原构建在迁移路径与禁网 `tsbench` 中从空目录通过 **16/16 CTest**；计划修正后只读复用该构建，**177 项 Python 测试**通过并仅提交一次运行。CLI/API 同计划，[独立恢复](../results/m0-pbepla-native-unified-20261119-r3/restore.json)不挂载原语料或原构建，报告逐字节复算。余 **17 项必需义务**（CORAD 三条路线）、**1 项未绑定运行条件**（Huff0 BMI2）；ALP AVX512BW 保留、待兼容宿主。M0 未通过，正式资格仍为 **0/36**。
- [三十一条路线 `extended-v16`](../results/m0-zfp-native-unified-20261119-r1/report.json)同次新增 ZFP `field-modes`、`openmp-encode`、`fixed-rate-array`：**184 槽、160 槽通过独立恢复、24 项预期拒绝；31/36 路线、154/180 项必需义务**有候选证据。实际观察 serial/OMP 1/OMP 2 编码参与线程数为 1/1/2，均由调用线程解码；有损 field 和 array 分开按原值域核验。五项运行条件已绑定，四项满足，AVX512BW 仍待兼容宿主。余 **26 项必需、1 项条件**未绑定。见 [ZFP 恢复与计费合同](contracts/zfp-native.md#extended-v16三条原生路线纳入统一账本)；M0 未通过，正式资格不变。
- [二十八路线 `extended-v15`](../results/m0-alp-decode-unified-20261119-r2/report.json)同次新增 ALP `decode-backends`：**178 槽、154 槽通过独立恢复、24 项预期拒绝；28/36 路线、139/180 项必需义务**在统一候选执行中有证据。四项运行条件已绑定，三项有实证；AVX512BW 保留编译，本机拒绝执行，状态为待兼容宿主。九份同帧后端对照实测 32 次逐位恢复及 13 次后端拒绝；后者在成功槽内部，不另计入 24 项。余 **41 项必需、2 项条件**未绑定。详情见 [ALP 同帧合同](contracts/alp-native.md#extended-v15同一-aln1-裸帧的后端对照)。M0 未通过，正式资格不变。
- [二十七路线 `extended-v14`](../results/m0-lzbench-profiles-unified-20261119-r3/report.json)同次新增 `zstd-dictionary`、`zstd-workers`、`xz-workers`：**169 槽、145 槽通过独立恢复、24 项预期拒绝；27/36 路线、135/180 项必需义务、2/6 项运行条件**有候选证据。两项条件取原生实际 worker hook，不从配置推断。字典及码流总计 2,568 B；XZ 两档 MT 与调用线程在同一码流上分别观察到 1、2、0 个原生后台解码线程。余 **45 项必需、4 项条件**未绑定，不改正式资格。试验路径及恢复见[字典与 worker 合同](contracts/lzbench-native-operations.md#extended-v14字典与原生-worker-对照接入统一执行)。
- [二十四路线 `extended-v13`](../results/m0-lzbench-session-unified-20261119-r2/report.json)同次加入 #40 `zstd-session` 和 #39 `xz-session` 的十项必需义务：**166 槽、142 槽通过独立恢复、24 项预期拒绝；24/36 组、124/180 项必需义务**有候选证据。两槽共四份裸帧只挂载各自码流和冻结依赖恢复，并用恢复原值重跑会话、生成相同帧。`tsbench` 空构建、迁移、禁网，15/15 CTest、166 项 Python 测试；[恢复审计](../results/m0-lzbench-session-unified-20261119-r2/restore.json)、报告逐字节复算及[会话重封存负测](../results/m0-lzbench-session-unified-20261119-r2/lzbench-session-reseal.json)。仍有 **56 项必需、6 项条件**未绑定，不改正式资格。见[字节会话合同](contracts/lzbench-native-operations.md#extended-v13两个原生字节会话接入统一执行)。
- [十二路线 `extended-v6`](../results/m0-ordered-selfstar-20261119-r1/report.json)在同一冻结计划、单次提交及主账本新增 SElf* 顺序批和原生逐值两组；**120 槽、103 个产品独立恢复、17 项预期输入拒绝**，12/36 组的 **64 项必需义务**有本次候选实证。SElf* 实际生成、独立恢复 18 个产物；已完成逐值块与直接批逐字节一致，未 finish 的第二块能暂读但不能提交学习状态；跳首块拒绝而 reset 后从头回放精确。[恢复](../results/m0-ordered-selfstar-20261119-r1/restore.json)不挂载原语料或原构建，报告逐字节复算，6 项重封存负例拒绝。116 项必需和 6 项条件仍待绑定，原生资格不变，见[机制合同](contracts/selfstar-native.md)。
- [十四路线 `extended-v7`](../results/m0-huff0-unified-20261119-r2/report.json)同一次提交加入 Huff0 FEC1 与 ETB1：**131 槽、112 个产品独立恢复、19 项预期输入拒绝**，14/36 组的 **75/180 项必需义务**有候选实证。`tsbench` 空构建、迁移路径、禁网，153 项 Python 测试和 14/14 CTest 通过。5 份 FEC1 帧与原生编码对照；4 个训练 profile 的 14 份 ETB1 块反序恢复，完整计主表、块及 SHA-256 绑定。[恢复审计](../results/m0-huff0-unified-20261119-r2/restore.json)不挂载原语料或原构建；报告逐字节复算，8 项计划及 4 项产品重封存负例拒绝。仍有 **105 项必需、6 项条件**未绑定；Huff0 portable 对照不跨 run 导入，正式资格不变。详见[机制合同](contracts/huff0-native.md#extended-v7同一执行计划中生成验证并独立恢复)。
- [十六路线 `extended-v8`](../results/m0-sprintz-unified-20261119-r2/report.json)同次加入 Sprintz-FIRE 批与原生查询：**151 槽、130 个产品独立恢复、21 项预期输入拒绝**，16/36 组的 **85/180 项必需义务**有候选实证。`tsbench` 空构建、迁移、禁网，153 项 Python 测试和 15/15 CTest 通过（随后 155 项 Python 回归通过）。9 份批与 9 份查询各自编码；[独立审计](../results/m0-sprintz-unified-20261119-r2/restore.json)从封存 SFB1 重跑 9 项查询，包含 128 通道、非整行尾、低维标量、generic SIMD 和 UINT32_MAX 以上无符号 SUM。报告逐字节复算；10 项计划重封存和 3 项 Sprintz 产品重封存负例拒绝。仍有 **95 项必需、6 项条件**未绑定，不提高正式资格。见[执行合同](contracts/sprintz-fire-native.md#extended-v8独立批恢复与压缩域查询)。
- [二十二路线 `extended-v12`](../results/m0-gorilla-state-unified-20261119-r2/report.json)同次新增 Gorilla C11 #7 `append-resume` / `iterator` 的八项义务：**164 槽、140 个独立恢复产品、24 项预期拒绝**，**22/36 组、114/180 项必需义务**有候选实证。`tsbench` 空构建、迁移路径、禁网，15/15 CTest、162 项 Python 测试通过。实测 resume 扫描 23 行并复制完整 184 B snapshot；前向 seek 扫描 51 行，向后请求不倒退。[审计](../results/m0-gorilla-state-unified-20261119-r2/restore.json)独立恢复并重跑续写，报告逐字节复算，18 项计划与 4 项 Gorilla 重封存负例被拒绝。余 **66 项必需、6 项条件**未绑定；不改变正式资格。[状态执行合同](contracts/gorilla-tv-native.md#extended-v12原生续写逐行迭代与工作量进入同一执行计划)。
- [二十路线 `extended-v11`](../results/m0-pcodec-intmult-unified-20261119-r1/report.json)同次加入 pcodec #11 `intmult` 的四项义务：**160 槽、136 个独立恢复产品、24 项预期拒绝**，**20/36 组、106/180 项必需义务**有候选实证。`tsbench` 空构建、迁移、禁网，15/15 CTest、158 项隔离 Python 测试及新增用例后的 160 项回归通过。三份裸帧实测模式为 IntMult／Classic／IntMult，大基数 `2^53+1` 精确保留；[独立审计](../results/m0-pcodec-intmult-unified-20261119-r1/restore.json)重跑三份帧恢复和三个原生拒绝。报告逐字节复算；16 项计划及 4 项定向 IntMult 重封存负例拒绝。余 **74 项必需、6 项条件**未绑定，正式资格不变。[IntMult 执行合同](contracts/pcodec-native.md#extended-v11tryintmult-接入统一执行)。
- [十九路线 `extended-v10`](../results/m0-titchy-stream-unified-20261119-r2/report.json)同次加入 Titchy 原生 `packet-stream` 六项义务：**154 槽、133 个独立恢复产品、21 项预期输入拒绝**，**19/36 组、102/180 项必需义务**有候选实证。`tsbench` 空构建、迁移路径、禁网，15/15 CTest 和 158 项 Python 回归通过。[独立审计](../results/m0-titchy-stream-unified-20261119-r2/restore.json)只用封存产物与依赖恢复；报告逐字节复算，同一 run 的 14 项计划和 8 项 Titchy 产物/证据重封存负例均拒绝。首包在第 28 次 push 后排出，finish 前排出 143/144 包，TSTR + TSC1 共 50,549 B。余 **78 项必需、6 项条件**未绑定，正式资格不变。[流执行合同](contracts/titchy-native.md#extended-v10原生-packet-流进入同一冻结执行计划)。
- [十八路线 `extended-v9`](../results/m0-titchy-unified-20261119-r1/report.json)同次加入 Titchy 复用 reader 与无状态范围：**153 槽、132 个产品独立恢复、21 项预期输入拒绝**，18/36 组的 **96/180 项必需义务**有候选实证。`tsbench` 空构建、迁移路径、禁网，15/15 CTest 和 155 项 Python 测试通过，随后 156 项 Python 回归通过。两路线分别封存完整 backing 与回答，[独立审计](../results/m0-titchy-unified-20261119-r1/restore.json)脱离原构建与原语料重跑访问；报告逐字节复算，12 项计划重封存与 4 项 Titchy 产物/证据重封存负例拒绝。复用 reader 打开 86 B、点 58 B、九点范围 174 B、单 bit 26–27 B，仅为逻辑回调字节；同一后段坏 split 使无状态 range 即使查询前段也拒绝。还剩 **84 项必需、6 项条件**，不改正式资格。详见[执行合同](contracts/titchy-native.md#extended-v9复用索引与无状态范围进入同一冻结执行计划)。
- [十路线 `extended-v5` 主报告](../results/m0-unified-batch-20261119-r1/report.json)：一次冻结计划、一次禁网运行、一份主账本，实跑 **95 槽、85 个产物独立恢复、10 项预期拒绝**，其中 6 个 Gorilla C11 原生 payload 双向交叉解码。55 项候选义务均在本次有证据，未拼接旧报告；[执行计划](../results/m0-unified-batch-20261119-r1/build/batch-plan.json)内逐产物绑定 driver、限额及精确 ELF 恢复闭包，并列出尚未绑定的 125 项必需义务和 6 项条件。[恢复](../results/m0-unified-batch-20261119-r1/restore.json)与逐字节报告复算不挂载源码、语料或原构建；CLI/API 同计划，5 个重封存负例拒绝，152 项 Python 测试、12/12 CTest。仍属候选，正式资格不变；详见[统一执行合同](contracts/linear-batch-execution.md)。
- [九路线 `extended-v4` 主报告](../results/m0-pcodec-wrapped-20261119-r2/batch-report.json)将 pcodec Source/C Native 的 wrapped 分页接入同一冻结计划：**86 槽、77 个产物独立恢复、9 项预期输入拒绝，51/51 项候选义务有证据**。两条分页路线各保留原生元数据、两页和计费侧车；[迁移审计](../results/m0-pcodec-wrapped-20261119-r2/restore-audit.json)仅用封存依赖逆序恢复四页，重跑缺元数据、终端截断、会话和配额，确认 Source 按页、C Native 按会话累计。CLI/API 同计划、禁网复算逐字节一致。仍不是输入流、IntMult 或正式阶段资格，r2 不合并 r1。
- [七路线 `extended-v3` 主报告](../results/m0-pcodec-unified-batch-20261119-r1/batch-report.json)把 pcodec #11 的 SourceAuto 与 C NativeAuto 接入同一冻结提交：**84 槽、75 个产物独立恢复、9 项预期输入拒绝，39/39 项候选义务有证据**。Rust SourceAuto 原生编码 13 份、C NativeAuto 原生编码 12 份，均由 Rust Source 解码；C f16 同时由 worker 与直接 C 入口拒绝。[迁移审计](../results/m0-pcodec-unified-batch-20261119-r1/restore-audit.json)重跑 344 次坏帧拒绝、25 次直接 pcodec 对照，并用恢复出的 SourceAuto f16 输入重跑 C 双拒绝；禁网复算逐字节一致，CLI/API 同计划，139 项 Python 测试通过。未接入 pcodec 分页及 IntMult 到通用执行器，不授予阶段资格或计时准入。
- [五路线 `extended-v2` 主报告](../results/m0-xz-batch-20261119-r2/batch-report.json)扩展到 XZ baseline：**58 槽、50 份独立恢复、8 项预期输入拒绝，28/28 候选义务有证据**。[恢复审计](../results/m0-xz-batch-20261119-r2/restore-audit.json)重跑 171 次坏帧拒绝及 4 次直接 XZ 对照；XZ 每个非空正例观测一个后台 worker 而非调用线程同步，1 B 派生坏帧验证原生 `LZMA_MEMLIMIT_ERROR`。仅 XZ 使用经实测的 256 MiB 地址空间档，其他仍用 128 MiB。r2 不拼 r1，迁移禁网复算逐字节一致，CLI/API 计划同一，136 项 Python 测试通过。不授正式资格或计时准入；XZ 的流式及不同 worker 路线未纳入。
- [四路线 `extended-v1` 主报告](../results/m0-extended-batch-20261119-r1/batch-report.json)覆盖 ALP、Zstd、Titchy 批和 ZFP 可逆一维串行：53 槽、46 份独立恢复、7 项预期输入拒绝、23/23 候选义务。独立迁移复核重跑 162 次坏帧及 12 次 Titchy 直接 C 对照；拒绝将 ZFP 限额错误改标损坏或省略 Titchy 调用。133 项 Python 测试通过。该报告不与其他路线拼接。
- [ALP Auto 与 Zstd baseline 一次提交](contracts/linear-batch-execution.md)绑定两条原生批路线：24 槽中 23 产物隔离恢复、1 项真实资源拒绝；还重跑 12 个坏帧拒绝、1 个直接 vendored Zstd 入口产物及 1 个 ALP 非默认舍入对照。**14/14 项有候选执行证据**。迁移恢复、报告逐字节复算、资源/账本负测通过；`tsbench` 130 项测试通过。仅两组本轮实测，不算正式资格，未触碰 ALP AVX512BW 条件。下一步是将统一执行计划扩展到更多已接入批路线，保留各自的专用验证与恢复依赖。
- [Gorilla #7 同次直接 C 双向对照](../results/m0-gorilla-batch-cross-20261119-r1/batch-report.json)从新构建完成 **8 帧隔离恢复、1 项 513 行拒绝、6/6 个用例双向交叉解码**；同组 **4/4 项均有候选执行证据**。
  C 工具、ABI 插件和同一份 Unique C11 库及其执行依赖按实际 ELF 闭包绑定；重新封存缺一方向或错误 payload 的负证均被拒绝。[恢复审计](../results/m0-gorilla-batch-cross-20261119-r1/restore-audit.json)实际重跑双向，报告从不挂载原源码构建与语料的环境复算。127 项 Python 测试通过。未扩大至其他路线，不授正式资格；下一步扩展 Zstd/ALP 等批路线。
- [Gorilla #7 `tv-batch` 执行候选](contracts/gorilla-batch-execution.md)挂接已有准入 ID，而不是重写用例或复制探针 PASS。**一次冻结提交：8 个产品完整恢复、1 个 513 行显式拒绝**；
  每进程地址空间、每文件限额与截止有实测负证。复算报告不挂载项目配置、原构建或语料，迁移后只凭帧和闭包重新恢复 8/8。126 项 Python 测试通过。
  此一组的 4 项中 3 项获得候选证据，`native_payload_cross_decode` 留待同运行直接 C 双向对照；不授资格、未扩展至其余 35 组。M0 与原 204/264 分母不变。
- [首批原生准入定义](../results/m0-native-admission-20261119-r3/native-admission-plan.json)将 36 组的域、质量、完成条件和恢复保留绑定到 180 项必需与 6 项条件义务。215 个开发用例关联已冻结输入与 bundle 身份，不把 case 当正式 driver。
  定义内嵌到[统一开发预检](../results/m0-native-admission-20261119-r3/native-report.json) `203f501ee5b84495a4b1b5443236da2c`；复用本轮从空目录在迁移、禁网环境编译的两套只读构建，**123 项 Python 测试、25/25 探针**通过，有 36/36 组开发证据。5 项条件得到开发实测，ALP AVX512BW 保留为待兼容宿主；两个 CORAD 部署在同一冻结 held-out 界上均 `quality_rejected`，不因探针通过而改判。
  [拒绝检查](../results/m0-native-admission-20261119-r3/admission-negative-controls.json)验证拒绝执行独立定义、提升资格和删除 AVX512BW；新旧报告均从封存运行独立逐字节复算。上一轮[产物路径失败](../results/m0-native-admission-20261119-r2/native-report.json)保留，未拼接进本轮。正式 driver/build、资源限额和逐案恢复依赖闭包仍未绑定，M0 未通过，原生正式资格为 0/36。
- [首批 Unique 构建对账](contracts/first-batch-unique-builds.md) 核对 11 个选定工程、1,385 个归档文件和两套构建的 287 个库编译单元；区分来源包的独立构建与 TSBench 集成执行。日常禁网预检不再串行重复编译 11 个来源包，独立核验保留为显式 `--release-builds-only`。改动后集成审计 `results/m0-build-review-integrated-20261118-r1/` 通过 35 项 Python 测试、19/19 探针，报告复算逐字节相同；独立构建沿用匹配的 `results/m0-native-plan-20261118-r1/release-builds/audit.json`，不是这次集成运行的新增结果。
- 现有原生执行代码已迁入 `native/worker/` 与 `native/runtime/`，开发 codec 迁入
  `plugins/codecs/`，新进程恢复及二进制迁移测试归入 `tests/isolation/`。插件包路径、注册清单、
  构建定义和测试引用同步更新；
  根目录设计/来源文档和历史证据未迁移。
- [M0 文档合同](contracts/m0-document-schemas.md) 列出 11 份已接入真实读写路径的 schema。
  schema 版本选择及内容随计划锁定；未知字段、超范围、外部 schema 引用、错误类型和伪造资格均拒绝。
  无法执行的草案不代替正式实验/运行合约。
- [三路线直接对照](contracts/direct-control.md) 已执行：Zstd 单线程 level 3 无字典块基线、
  ALP Auto 批处理、raw-store 独立格式参考。动态加载和链接入口对同一完整产物逐位一致。
  Zstd 的 64 KiB+1 编码、ALP f32 + AVX2 解码均按合同拒绝。ALP 现场 FALP Auto 走 AVX2，
  原生计数看到实际融合向量；测试不视为其他 ISA 或 RD 的资格，此三方法对照不覆盖 Zstd 多线程、原生流或字典。
  `results/m0-smoke-20261118-r3/abi-build/direct-control.json` 保存当前完整诊断。
- Zstd/XZ 的 [冻结入口合同](contracts/lzbench-native-operations.md) 与 CTest `tsbench.control.lzbench`
  独立于 TSBench 正式方法：对照 legacy 64 KiB 边界、caller-span 会话及失败后 reset、新进程
  读取字典并拒绝缺失/错误字典、Zstd 0/2 编码 worker、同一多块码流的 XZ 1/2 解码 worker。
  在 `results/m0-lzbench-native-20261118-r1/` 的迁移、禁网、空构建审计中 7/7 组诊断匹配
  （`abi-build/lzbench-native-probe.json`，诊断 ID `e6e6ca7222574f00ad76f05a25824ba7`）；同次审计
  通过 22 个 Python 测试、9 个 CTest、11 个来源工程构建、语料复算和 CORAD 训练桥探针。
  不报告计时或授予运行资格；该轮尚未接入 XZ worker。
- 新增 Sprintz-FIRE16 typed `u16` 的 ABI 适配；[同版来源证据与新增用例](contracts/sprintz-fire-native.md)
  不重复历史查询套件。禁网迁移审计的 `abi-build/sprintz-native-control.json` 记录 4/4 完整 SFB1
  差分一致、删除原输入后位级恢复，20 个损坏帧拒绝及 f64/超长输入拒绝。同次纯原生探针
  验证查询的四 lane SIMD 与两 lane 标量路径，不宣称框架查询接口或正式资格。
- [Gorilla T+V](contracts/gorilla-tv-native.md) 新接入双列 worker，绑定交通 512 行和汇率尾 13 行，
  加上空、单行和时间/特殊位边界共 5 项原生 payload 对照与新进程独立恢复。以同版 Unique
  历史验证为来源证据，定向检查 append/snapshot/resume、向前 seek 和 drain 才能发现的尾部错误；
  后两组保留为直接原生诊断，未声明 TSBench 流式或查询服务，也未继承派生 T/V 资格。
  新一轮审计保存于 `results/m0-gorilla-tv-20261118-r1/abi-build/gorilla-tv-control.json`
  （诊断 ID `114565459fff470c856b0a08ac3c7f72`），旧 f64 候选仍 18/18 逐产物通过。
- [pcodec](contracts/pcodec-native.md) 新接入 SourceAuto 与显式 C NativeAuto 两种批编码身份；
  二者通过完整构建的 Rust Source 解码。真实交通 V-only、位边界和空输入共 **25 项**
  独立逐位恢复，与直接入口 payload 一致，另验证 C f16 拒绝和 148 个拒绝产物。
  直接原生诊断在同一 773 行窗口恢复两种 wrapped 页，实测 Source 的逐页限额与 C 的会话累计限额；
  IntMult 观测到实际选用、尺寸兜底退回 Classic 以及完整 u64 基数。证据为
  `results/m0-pcodec-20261118-r2/abi-build/pcodec-control.json`（诊断 ID
  `e7fd285139714bf9a0eec6301d75bb2b`）；页和 IntMult 未注册框架服务，没有正式性能、在线流
  能力或阶段资格。同一审计的 M1 候选功能预检 `5587b85465e04c3ca5d13c8265c09379` 仍 18/18，
  不改 M1 阶段状态。
- [Titchy](contracts/titchy-native.md) 批处理注册 `titchy-batch`；7 个产物与原生 TCHY payload
  一致且在新进程逐位恢复，49 个异常产物及 3 个非法输入按合同拒绝。绑定的 4,013 个交通
  f64 值在驱动明确映射为 u64 bits，worker 不隐式接受 f64。原生 packet 流实测背压、重置和
  尾部裁剪；索引访问分开记录打开和读取请求量，stateless range 验证整个容器。只有 batch
  接入 ABI，流和访问是原生直调诊断，不属于正式 M5 功能、物理 I/O 或性能样本。证据为
  `results/m0-titchy-20261118-r1/abi-build/titchy-control.json`（诊断 ID
  `f18be8d83bc94784a6f9930d2bcbef7c`）；同一审计的 M1 功能预检 `9f5f751878f94019910674e574e3e6a4`
  仍 18/18，不改阶段状态。
- [ZFP](contracts/zfp-native.md) 新注册 `zfp-reversible` 串行 1D field；5 项新进程逐位恢复
  与直接 native payload 一致，另拒绝 30 个坏封装和 3 个不支持的输入/选项。实际参数、
  原值域误差、1–4D 布局及 stride 由直调诊断分开记录。OpenMP 两个 TID 分别处理 1,024 个
  编码块，decode 只见调用线程；固定率 array 验证脏缓存、已触及与未触及的块、flush、新进程
  重开，并确认本冻结版 `set_cache_size` 只 flush、不扩容。证据为
  `results/m0-zfp-20261118-r1/abi-build/zfp-control.json`（诊断 ID
  `47d36de63d2945e3904340518b7137dd`）；原生 raw ZFP 只处理受信产物，不提供外来码流解码服务。
  同次审计的 M1 候选 `f4abc2ab32544e05a8736b8161e6ba96` 仍 18/18，不改阶段状态。
- [ALP Auto](contracts/alp-native.md) 复用 Unique `test_codec` 历史证据，定向验证 f32/f64 的
  `ALN1` 实发 decimal/RD/raw、六种异常位、rowgroup 切换和实际解码计数。九个产物得到
  32 次新进程逐位恢复、13 次按宽度/本机条件拒绝后端、27 次坏产物拒绝。f64 的 AVX2
  decimal 内核有实测工作计数，RD/raw 不计为该内核工作；AVX512BW 本机不可用，保留为条件原生能力并在兼容主机补验，不能按通过或从清单移除。
  证据为 `results/m0-alp-20261118-r1/abi-build/alp-native-control.json`（诊断 ID
  `9b5b83339c8545678aee2742fe1dcca4`）；同次 M1 候选 `7d2eefdfcd744585bac4f07ba35961fd`
  仍 18/18，只验证功能，不改阶段状态。
- [SElf*](contracts/selfstar-native.md) 接入 `selfstar-batch`，按 Unique 基线固定每块 512 值且块间
  保留学习。7 个 f32/f64 对象在删除 staged 输入后逐位恢复，55 个异常产物拒绝。原生直调
  另证 10 个逐值块与批编码字节一致、5 条序列 reset 后从头回放恢复，跳过首块均失败；
  `finish` 前写入位数不等于可完成的块。证据为
  `results/m0-selfstar-20261118-r1/abi-build/selfstar-control.json`（诊断 ID
  `48be6a35057841debf81a23caedcd633`）；同次 M1 候选 `e65fcd97096c4d59b5e5e4f831137940`
  仍 18/18，不采正式时间，不改阶段状态。
- [Huff0](contracts/huff0-native.md) 接入 FEC1 `u8` 独立批路线：5 个自产物独立恢复、28 个异常产物拒绝。
  原生直调分别用 1X/4X 的 ETB1 模型，在独立进程反序恢复 14 块，模型身份和块字节分别检查；训练读取新版
  语料的独立 train 分区，原 M1 仍仅允许 test。默认构建实际完成 3/4/4 次带 BMI2 参数的解码入口调用；
  显式 portable 对照同用例、不同构建，压缩产物相同，实传 BMI2 参数为零。证据为
  `results/m0-huff0-20261118-r1/abi-build/huff0-control.json`（诊断 ID `032d335a9b6944af8a0ff0f3181c4fa0`）和
  同目录树的 `huff0-portable-control.json`（诊断 ID `a62cff5ab221459b95898a07070016f7`，本机迁移定向测试）。
  同次离线审计的 M1 候选 `60197aeda09d4c7a9afbce10c9bd3fa5` 仍 18/18，不采正式时间，不改阶段状态。
- [PBEPLA-RR](contracts/pbepla-native.md) 接入有界 f64 批处理与独立逐层恢复。7 个用例、29 个
  前缀逐个验证实际误差；callback replay 的非空样本需要 3 遍输入，首个输出在第 3 遍之后。
  暂存操作按逻辑字节报告，不算物理 I/O 或在线流。最新证据见
  `results/m0-corad-20261118-r1/abi-build/pbepla-control.json`（`0adea4ff025f43ffba9a5f5fd19acd51`）。
- [CORAD](contracts/corad-native.md) 的原生模型推理、C11 训练和原样 sklearn Source 桥
  在同次禁网迁移中分别实跑。绑定气象 train 129 行、test 67 行，不交叠；两种模型产物
  各在新进程独立恢复并与第三方无关的 CRD1 解析器逐字节对照。报告保留湿度原域最大误差
  155.02/156.43（百分点），不凭 `threshold=0.9` 判质量通过。C LARS 达到 6 次外层上限，
  `converged=0`；两个稀疏求解器另有解析对照。证据见
  `results/m0-corad-20261118-r1/corad-native-control/audit.json`（`45d6bfbe17b94b9db8a851e5a3c71f95`）。
  此为该轮的直接对照，不授正式资格。同次 M1 候选
  `49a42b9ae8dc4226886ff78973323bbb` 的功能预检仍 18/18。
- [M0 统一原生预检](contracts/m0-native-preflight.md)：在迁移、空构建与禁网环境一次实跑，
  计划 `e15a875b0d15ff834a2e5bb193cf361109734b33bb7fa79af0fa5bb4d626197f`，
  外层运行 `223a173f3f3d4527b94e4c0de8b640ac`，19/19 探针通过、36/36 组有本次探针结果，0/36
  正式资格。全部 209 个输出文件合计 722,831 字节（不含计划、账本、完成标记和派生报告）。
  在新目录仅暂存控制层与封存证据，不暂存构建、语料或派生报告，复算得到逐字节相同的报告。
  证据见 `results/m0-native-plan-20261118-r1/native-report.json` 与 `native-report-recompute-check.json`。
  应用回归内的 M1 候选 `6f88cdd336184ccbbd116af8a7aa04eb` 仍 18/18，不改 M1 阶段状态。
- 开发 smoke 的统一运行 `47c4f683df784e978645766e537e775e` 对 2 个 fixture × 3 种方法
  完成 6/6 逐产物位级验证。`results/m0-smoke-20261118-r3/smoke/` 包含原始证据与派生报告。
  回归覆盖依赖缺失、非零退出、崩溃、非法输出、超时、执行中取消与无完成标记的拒绝；
  无原始输入、worker 或当前 schema 时仍可复算。恢复探针验证未传入原始源文件且 staged
  副本已删除，不代表 OS 已禁止所有原始数据路径。没有性能样本、检查点恢复或资格结论。
- [M1 候选阶段计划](contracts/m1-lossless-candidate.md) 的离线迁移预检运行
  `ada350d11f644e3e8e0edad7b7d5f5e3`，一份计划串行完成 18/18。6 个输入包含空数组、
  特殊浮点位、气象 1025 元素尾块及两个电力块边界，36 次编解码操作分别启动；
  无输入、worker 或当前 schema 时重算报告。证据在
  `results/m0-stage-plan-20261118-r1/smoke/m1-candidate-verified.json`。不采集正式时间，不能替代 M1 验收。
- 本轮仅更新 Conda `tsbench`，不使用或更改 `base`。按 CORAD 包内 NOTICE 对齐 Python
  3.11.5、NumPy 1.24.3、SciPy 1.11.1、pandas 2.0.3、scikit-learn 1.3.0；仅增加 `jsonschema` 4.23.0 与依赖，未替换这些版本。完整
  包构建及 SHA-256 见 `environment/tsbench-linux-64.lock.json`。这是已准备前缀的禁网运行证据，
  不是从空机器离线安装 Conda 包的交付证据。历史 Python 3.12 和 base 日志保留，不算本次结果。
- raw-store 通过空数组及含负零、NaN payload 的 f64 位级恢复，源文件和 schema 文件删除后
  由另一个进程恢复；验证插件错误拒绝、ABI 版本／表／ID、以及 context 销毁后产物保持有效。
  它只接受 little-endian、连续、无 validity 的 rank-1 单列视图；不是原生流式或多线程实现。

- Unique 总 manifest 的旧 `file_count` 对 ALP、Titchy、ZFP、lzbench、CORAD 分别写为
  31、12、127、424、13；实际归档与各发布版逐文件 manifest 对应为 35、13、196、425、16。
  两表原值保留；归档 SHA-256 不变，和发布版 manifest、历史 validation 及本地实际文件一致。
- pcodec 首测失败是隔离工具链没有 `cc` 别名，不是依赖下载或编码器失败。
  首次 audit 与诊断日志保存在 `results/m0-offline-source-audit-20261118-r1/`；重跑在同样禁网
  条件下提供编译器别名，默认 Rust Source 后端通过构建，没有改源码或改走 C-only。
- `datasets/manifests/unique-intake-candidates.json` 保留初始 23 个文件的清点快照；按用户确认，
  整个来源目录已原样复制到 `datasets/raw/unique/`，不要求核对上游版本或许可。v2 运行资产由
  其中 7 份原件生成，覆盖 4 个来源簇；详见[真实语料合同](contracts/first-batch-real-corpus.md)。
  M1 候选仍绑定原 v1；当时的服务范围草案绑定 v2，分母 204/264 不变。
  `results/m0-corpus-v2-20261118-r1/corpus-audit.json` 保存禁网迁移后的全量规范数据复算，
  `corpus-rebuild.json` 记录只读本地原始副本时全数 9 份生成文件的逐字节复现。
  未纳入项和覆盖缺口继续保留，合成 fixture 不能替代真实覆盖。
- v2 [语料画像](contracts/first-batch-real-corpus.md) 与规范哈希在同一遍扫描中计算。
  `results/m0-corpus-features-offline-20261118-r1/corpus-profile.json` 的画像 ID 为
  `daf1df835b1cd48ffec380fa25fc850da2e7baa084bb80893e7d9ea403c48733`，与非隔离路径独立复算逐字节一致，
  政策与语料 ID 均匹配本次范围计划。同次禁网集成审计通过 40 项 Python 测试及 19/19 个原生开发探针，
  运行 `e8789f5560294143ae216e3491b17663`，统一原生报告也逐字节复算一致；未重复构建来源包，不授资格。
- [合成/方法边界补验](contracts/first-batch-method-boundaries.md)：本次禁网迁移输出
  `results/m0-method-boundaries-offline-20261118-r1/`。重建器逐字节复现 17 个 NPY 与清单，v2 画像仍验证原真实语料 ID，
  三条批方法的同源前缀 B−1/B/B+1 加 f32 特殊字共 10 例：8 个逐位恢复帧、2 个实际返回 7 且无帧的预期拒绝。
  同一运行 `98934096714a48f3a4b5f7dd78ecc20e` 通过 42 项 Python 测试和 20/20 个原生开发探针，36 组均有开发结果；
  未重复编译独立来源包，不授正式资格。
- v3 [禁网迁移集成审计](../results/m0-corpus-v3-20261118-r1/) 使用 Conda `tsbench`、空构建和一个统一运行
  `e76de8f3c18f447487bd6635f23d36ac`，通过 **43 项 Python 测试与 20/20 个开发探针**。两份新增 gzip 和
  v3 清单可从本地锁定的来源字节逐字节重建；画像和范围计划的语料、政策及 fixture ID 一致。实际核对方法边界
  探针的 12 个留存帧的字节数及 SHA-256 和 2 个按合同拒绝且无帧的用例。仅挂载封存运行与控制层、无语料或构建
  目录时，`native-report` 复算[逐字节相同](../results/m0-corpus-v3-20261118-r1/replay/report.json)。新集成与
  旧独立包构建命令已[对照](../results/m0-corpus-v3-20261118-r1/build-command-recheck.json)，没有重编独立包；不授资格。
- [目录迁移下的可插拔回归](../results/m0-catalog-pluggability-20261118-r4/pluggability/audit.json) 在不含第三方归档的副本中，
  通过注册和包内文件加装测试 codec，无核心改动；用同一份 f64 位边界输入实际更换方法。禁用或删除 raw-store 后，
  引用它的 CMake 和 planner 明确拒绝，保留的方法仍可构建并按位恢复。修改选项后默认值进入冻结计划，显式 `165`
  进入新实现的实际编码调用；旧构建锁及实际旧码流分别被新配置和新解码器拒绝。旧工件使用[保留的解码定义与二进制](../results/m0-catalog-pluggability-20261118-r4/pluggability/retained-decoder-v1.json)
  从无 staged 输入的工作目录按位恢复；旧原始账本不改写、旧报告可复算。另有一项单选 lzbench 的来源闭包测试，
  不读取其他来源归档，而完整首批核验仍拒绝缺包。
- 目录驱动构建后的[首批禁网集成复核](../results/m0-catalog-integrated-20261118-r2/) 通过 **44 项 Python 测试、20/20 个开发探针**，
  统一外层运行 `7fa5bab3c78f44dca880c292f4e588d1` 覆盖原 36 组；报告复算逐字节一致，M1 候选仍是开发期 18/18 核验。
  与保存的 Unique 独立发布构建相比，[287 个库编译单元、11 个共享目标的链接命令和 pcodec Cargo 命令不变](../results/m0-catalog-integrated-20261118-r2/build-command-recheck.json)，
  本轮没有重编独立发布包。此处不授阶段通过或正式资格。
- [原生定义计划与边界验收复核](../results/m0-native-requirements-20261118-r2/) 在禁网环境只读复用上述匹配的集成构建，
  单独挂载 CTest 临时日志目录，没有重新编译。**48 项 Python 测试、20/20 个开发探针**通过；
  统一运行 `686b037516e940a09081d33822734709` 将 14 个冻结用例逐一与恢复摘要、后端、线程及产物核对，
  12 个按位恢复帧与 2 个无帧的预期超限均匹配。只挂载封存运行和控制层的报告复算逐字节一致。
  其余 174 个必需项尚无可执行用例/验证器绑定；这里不授资格或 M0 通过。
- [Titchy 访问开发合同复核](../results/m0-titchy-access-20261118-r1/) 使用禁网 `tsbench`，仅复用同一匹配的
  只读集成构建，没有重编 Unique 或 TSBench 原生目标。统一运行 `dd91e7add45340b996b0c2afbdf07127` 通过
  **50 项 Python 测试、20/20 个开发探针**，同一账本新增三个可复算访问检查。留存一份 49,486 字节 TCHY；
  `read_at` 观察值为打开 86、点 58、范围 174、单 bit 26–27 字节，均未超本用例上限。仅挂载封存证据及
  控制层时，本次与上次报告分别逐字节一致。该轮时点 171 个必需项仍未绑定开发用例，正式资格仍为 0。
- [PBEPLA 逐层证据及 ALP 条件后端复核](../results/m0-pbepla-progressive-20261118-r2/) 在禁网 `tsbench`
  只读复用既有集成构建。统一运行 `ed584b8ef6fd47879e4f1d1cad0b74f6` 通过 **54 项 Python 测试、20/20 个开发探针**；
  PBEPLA 的 29 份独立前缀共 8,781 字节，七份原始／恢复值记录共 52,872 字节，三份 replay 分别读取 1、3、3 遍。
  无构建及语料挂载时，新旧报告分别逐字节复算相同。ALP f64 AVX512BW 仍为已构建、当前主机运行时不可用；
  机器计划保留 `pending_supported_runtime`，等待支持 AVX512F/BW/DQ 的宿主验证，不计为失败或不适用。
  现在 165 个必需项尚无开发用例绑定，M0 未通过，正式资格仍为 0。
- [进程计时门槛与生命周期预检](../results/m0-process-measurement-20261118-r1/) 在禁网 Conda `tsbench`
  只读复用原生构建，**57 项 Python 测试、20/20 个开发探针**通过。外层运行 `eaf7c1b6fcb241e0870268dd8250d0e3`
  内的 M1 v2 候选运行 `c7e5695f4dd24d20ae5ff1552c837631` 按位复核 18/18 个完整产物，记录 36 次新进程
  encode/decode 的单调墙钟和实际后端，匹配为六个同输入诊断组，不作性能排名。已测量的操作终态和未启动的操作
  分开记录；删除实际启动操作的墙钟字段并重新封存，报告仍拒绝。仅挂载封存证据和控制代码时，本轮及上一轮的
  统一报告与 M1 报告均可逐字节复算。正式稳态／冷上下文边界、配对轮次、独占、缓存和正式直接对照仍未闭合。
- [ALP AVX512 保留定向复核](../results/m0-alp-avx512-retention-20261118-r1/) 使用禁网 Conda `tsbench`、只读复用
  既有构建，5 项原生计划合同测试及 1 个 ALP 探针通过。探针的 f64 AVX512BW 字段为已构建、运行时不可用、
  `pending_supported_runtime`；支持的 Linux x86-64 构建缺对象会报构建回归。此轮不重编、不授资格，也不替代兼容宿主实测。
- [XZ baseline worker](contracts/lzbench-native-operations.md) 新增 preset 6 原生批路线，四个产物与冻结库直调
  载荷相同，独立新进程恢复数据及 schema，十项越界／非法请求拒绝。禁网 `tsbench` 的
  [统一预检](../results/m0-xz-baseline-20261118-r2/) 运行 `f081de6161bd4039b94ef0f9f81750c7` 通过
  **57 项 Python 测试、21/21 个探针**；无构建、数据集或工作区配置挂载时，本轮和上一轮的统一报告及其
  M1 候选报告分别逐字节复算一致。复用与既有集成证据 SHA-256 相同的
  `liblzbench_native.so`；不重编 Unique 独立发布包。XZ 的会话／并行仍为原生直调，正式定义的 165 个必需项
  待绑定和 0/36 资格均不变；该轮结束时 CORAD 还未接 worker。
- [CORAD 冻结模型 worker](contracts/corad-native.md) 新增有序多列推理；复用两份已审计的模型资产，
  六份开发产物与冻结库原生载荷及独立恢复解析器一致，另拒绝 12 项错模型、错列序、超限及坏帧。
  [禁网统一预检](../results/m0-corad-worker-20261118-r1/) `6e52b16442144239b8c4bc8e321eb050`
  通过 **57 项 Python 测试、22/22 个探针**，不挂载构建和数据集时，本轮与上轮报告及 M1 候选报告均逐字节复算。
  C11 原生库迁到插件包构建一次，SHA-256 与此前相同；模型没有重训。首批 12/12 条目都有至少一条
  worker 路线，不代表组内能力全部接入或 M0／M3 正式资格。有损质量门槛、训练执行合同和完整绑定仍待补。
- [CORAD 推理证据绑定复核](../results/m0-corad-inference-bindings-20261118-r2/) 在单一禁网运行
  `bd70ddf64e014dbebe348e3e58e27bab` 冻结五个检查、八个开发用例，共留一份 1,608 字节原值与六份
  合计 4,302 字节的帧。复用原生构建，**59 项 Python 测试、22/22 个开发探针**通过；新旧统一报告
  和 M1 候选报告均不挂载构建、模型目录、数据集即可逐字节复算。验收定义尚有 160 项未绑定，
  不授正式资格或推理质量通过。
- [原生稳态／冷上下文批诊断](../results/m0-native-frame-batches-20261118-r2/) 在禁网 Conda `tsbench` 运行
  `832ed58e8ff74d46b46f45d8e33f367e`，**63 项 Python 测试、23/23 个开发探针**通过。raw-store、Zstd、ALP
  在两种生命周期下共执行 16 组、48 个配对轮（不含 32 次单操作校准），逐项核验 27,840 次计时编解码操作，
  封存 8 份共 4,373,437 字节的参考帧。48 轮均未做到两侧的两个方向同时达到 3 ms 批目标，保留真实时间，不把
  此次结果用作正式性能分布。无构建、数据集和项目配置时，本轮及上轮的统一报告和 M1 候选报告均逐字节复算。
  复用既有原生依赖，只新增编译相关探针；初次整合的构建日志保留在 `m0-native-frame-batches-20261118-r1/`。
  未授予阶段或算法资格，不改变原生需求绑定及服务分母。
- [Gorilla C11 原生功能绑定](../results/m0-gorilla-native-bindings-20261118-r1/) 新增九个检查/九个开发用例，
  使用现有 `gorilla_c`，不重新编译原生库。外层禁网运行 `7c0ef7934c6646d99e07c43f3d4241c6` 通过
  **65 项 Python 测试、23/23 个开发探针**，封存六份完整 TV 帧、snapshot 及两条原生 finish 帧，共 11,906 字节。
  不挂载构建、数据集或工作区配置时，本轮及上一轮的统一报告和 M1 候选报告均逐字节复算。篡改 seek 结果、
  续跑位数、独立恢复摘要、留存闭包或改写并重算载荷摘要均被拒绝。append/resume 实际扫描／复制和 iterator
  扫描量未完整绑定；不授资格，不把这些原生机制诊断记成通用流式插件接入。
- [ALP Auto 原生功能绑定](../results/m0-alp-native-bindings-20261118-r1/) 新增九个检查/九个开发用例，
  覆盖 f32/f64 的 Decimal/RD/Raw、异常位、跨行组切换、后端及两方向舍入模式拒绝。复用已锁定原生库，不重编。
  在 `tsbench` 禁网运行 `46bcb22d28ec4991a4dca7d618735074` 中，**65 项 Python 测试、23/23 个开发探针**通过；
  九份完整帧共 286,426 字节，气象尾块原值 8,232 字节；32 次新进程按位恢复、13 次预期后端不可用拒绝，
  另拒绝 27 个长度／尾部反例与 4 个真实异常位置变更。隔离复算不访问构建、语料或项目配置，且拒绝伪造
  dispatch、恢复摘要、错写输出的舍入记录、漏帧及已编译 AVX512BW 后端丢失。f64 AVX512BW 保留为
  `pending_supported_runtime`，待兼容宿主复核；不改变原生资格和服务分母。
- [Zstd/XZ 裸批与原生会话绑定](../results/m0-lzbench-native-bindings-20261118-r2/) 新增 11 个检查及用例。
  禁网运行 `018828e3e7764521ba30af19db08ef87` 通过 **67 项 Python 测试、23/23 个开发探针**；只重编
  `tsbench_lzbench_contract`，复用同版 `lzbench_native` 和 `feature_worker`。封存九份完整帧共 16,580 字节，
  记录 4,344 次原生 span 调用；Zstd/XZ 主编码样本均实测到零输入的结束阶段出数。本轮及上轮报告在
  不挂载构建或数据集时逐字节复算。篡改跨度、恢复摘要、Zstd 旗标及重算文件哈希、截断拒绝结果或留存闭包均拒绝。
  该版本尚未绑定字典和原生 worker；不授流式服务资格或正式性能成绩。
- [Zstd 字典和 Zstd/XZ 原生线程对照](../results/m0-lzbench-native-bindings-20261118-r3/native-report.json) 新增 10 个必需检查的开发用例绑定。
  禁网运行 `d019e11699c54869864e9ba20a4c8638` 复用现有构建，通过 **69 项 Python 测试、23/23 个开发探针**。
  Zstd/XZ 槽位封存 14 份帧和 1 份字典，共 14,702,136 字节；其中字典和依赖帧合计 2,568 字节。
  XZ 在同一两 worker 产物上用两种解码配置恢复，`threads=1` 仍实测一个 worker，不满足同步对照。
  本轮和上一轮的统一报告及嵌套 M1 报告均在不挂载编译产物、语料、项目配置时逐字节复算一致。
- [XZ 裸批及会话的块、过滤器和内存预算](../results/m0-lzbench-native-bindings-20261118-r4/native-report.json)
  新增 8 项必需检查的开发用例。禁网运行 `2526bc15e6aa4aa7a005c715cda1a0b2` 通过 **71 项 Python 测试、23/23 个开发探针**；
  仅重编 TSBench 探针，复用冻结库与 feature worker。Zstd/XZ 槽位共封存 20 份产物、14,711,664 字节，
  其中四份新增成功帧、一个 60 字节解码预算负向帧。运行验证了裸批 256 MiB 和会话 64 MiB 的拒绝、
  裸批输入块上限，以及会话逐块 Delta → LZMA2 和 CRC64。当前及上一版的统一与 M1 报告在无构建、语料或项目配置时
  逐字节复算一致。该轮仍缺 XZ 调用线程同步对照，不把一个后台 worker 当作同步。
- [pcodec 双批入口与分页](../results/m0-pcodec-batch-pages-20261118-r1/native-report.json) 新增 23 项必需检查的开发用例绑定。
  禁网运行 `a26f6f63a73445a6a7fbce6144128ce4` 复用冻结构建，通过 **73 项 Python 测试、23/23 个开发探针**。
  pcodec 槽位封存 25 份批帧、2 份共享元数据、4 份压缩页及 2 份 sidecar，共 8,258 字节。
  新进程验证两种批路线按位恢复及两条分页逆序恢复；分别验证逐页和累计限额、截短尾读及 C 页缓冲所有权。
  本轮和上一轮的统一报告及嵌套 M1 报告在不挂载构建、数据集或工作区配置时逐字节复算一致。
  这一版只绑定双批和分页，不授正式资格。
- [pcodec IntMult](../results/m0-pcodec-intmult-20261118-r1/native-report.json) 新增四项开发用例绑定，
  禁网运行 `13d79636f6ad4d1fa2d4adcbc4d74702` 通过 **75 项 Python 测试、23/23 个开发探针**，未重编算法库。
  三份新增裸帧均在新进程逐位恢复，合计 11,708 字节；pcodec 槽位共封存 36 份二进制产物、19,966 字节。
  复算直接读取码流的模式及整数基数，验证 `u32` 倍数输入发出 IntMult、高熵输入回退 Classic、
  `u64` 基数保留 `9007199254740993`，并核对三类非法输入的拒绝。新旧统一与 M1 报告均在禁网、
  不挂载构建产物、语料或项目配置时逐字节复算一致。pcodec 27 项均有开发用例，未授正式资格。
- [Sprintz-FIRE 原生批处理与查询](../results/m0-sprintz-native-bindings-20261119-r1/native-report.json) 将两组共十项绑定到冻结的开发用例。
  `tsbench` 禁网运行 `7037b22910624010bc80e7d2ecba7457` 通过 **77 项 Python 测试、23/23 个开发探针**，
  36/36 原生组有通过的开发探针。只重编直调探针，复用冻结库和 worker；封存 9 份原生 SFB1 和 4 份 worker
  封装，共 131,747 字节。原生 u8/u16 多形状均独立恢复；查询将实际 SIMD/标量结果与原数组的独立归约对照，
  u16 大消息的三条 lane SUM 均超过 `UINT32_MAX`。复算检查帧配置、CRC、RLE 结构和尾部、恢复与拒绝证据；
  新旧统一报告及嵌套 M1 报告均在无构建、数据集和项目配置的禁网环境中逐字节复算一致。
  worker 仍仅是 u16/4 lane 批处理，未获得查询或正式阶段/方法资格。
- [Titchy 原生批、packet 流与访问](../results/m0-titchy-native-bindings-20261119-r1/native-report.json) 新绑定 19 项，
  四组的 22 项必需检查均有开发用例。`tsbench` 禁网运行 `1cd3c4eb13e44b719b1d1c062aa36fd2` 复用原生构建，
  **79 项 Python 测试、23/23 个开发探针**通过，封存 12 份批封装、一份访问 TCHY 和两份流恢复依赖，共 299,009 字节。
  原生流实测 144 个 packet，143 个在 finish 前得到；首包在第 28 个样本后得到，末尾补三个零，配额包括 padding。
  离线独立解码批和流并核对冻结原值，区分懒访问和整容器验证；拒绝改写帧并更新哈希、偏移发包时机、伪造访问结果、
  漏掉负向状态或 TSC1。新旧统一报告及嵌套 M1 报告均在不挂载构建、语料或项目配置的禁网环境逐字节复算一致。
  批以外仍为直接原生诊断，未授正式服务、方法或阶段资格。
- [ZFP 原生 field、OpenMP 与固定率 array](../results/m0-zfp-native-bindings-20261119-r1/native-report.json) 新绑定四组 19 个必需检查。
  `tsbench` 禁网运行 `783af7c848ad4b92a95363de5713d10f` 仅更新了块观测探针、复用算法库，
  **81 项 Python 测试、23/23 个开发探针**通过。封存 32 份产物，共 392,085 字节。相同 f64 field 三档共处理同样的
  2,048 个编码块：serial 与 OMP 1 均一个实际线程，OMP 2 两线程各 1,024，三档均由一个调用线程解码且新进程按位恢复。
  有损 field 按冻结上限复算；array 恢复费用为 64 字节裸数据和 116 字节格式侧车，未触及块的压缩字节与恢复值不变。
  拒绝伪造工作线程、无效参数、改写 padding 或未改动块后再算哈希，以及遗漏 array 侧车。新旧统一报告及嵌套 M1 报告
  均在不挂载构建、源语料或项目配置的禁网环境逐字节复算一致。非串行可逆 field 仍为直调诊断，不授正式资格。
- [Huff0 FEC1 / ETB1](../results/m0-huff0-native-bindings-20261119-r1/native-report.json) 新绑定两组 11 个必需检查。
  `tsbench` 禁网运行 `97a0296f4a2649d29c75ad059c81300f` 复用冻结构建，**84 项 Python 测试、23/23 个开发探针**通过，
  36/36 原生组有通过的开发探针。封存 27 份产物，共 290,075 字节；FEC1 固定 4X，ETB1 才支持 1X/4X。
  单独的 portable 构建对照在同输入产生相同字节，FEC1 4X、ETB1 1X/4X 实际完成调用 3/4/4 次，
  两构建传入的 BMI2 参数分别全 `1`（默认）与全 `0`（portable）。独立复算拒绝漏留存、伪造入口、块长和 jump table，
  以及漏计模型、漏拒绝、伪造恢复摘要。新旧统一报告与嵌套 M1 报告均在禁网且不挂载构建、语料和项目配置时逐字节复算一致。
  当轮剩余 27 项未绑定：CORAD 12、SElf* 9、PBEPLA 3、Gorilla 2、XZ 1；当前 0/36 正式资格。
- [SElf* 顺序批处理与逐值增量](../results/m0-selfstar-native-bindings-20261119-r1/native-report.json) 新绑定两组 9 个必需检查。
  `tsbench` 禁网运行 `39be3783dff24ba2ae7bf63a60017502` 复用原生构建，**87 项 Python 测试、23/23 个开发探针**通过，
  36/36 原生组有通过的开发探针。封存 22 份产物，共 99,751 字节。f32/f64 的 512 值完整块及跨块短尾均由新 worker
  和独立 C 库 reader 进程逐位恢复；原生增量分别验证 1000 值、累计 1001 拒绝、容量失败后 reset 和终止符消费。
  气象窗第二块需回放 512 值（748 native 字节 + 4 字节块头）。复算拒绝伪造前缀、恢复摘要、字节费和 reader 完成状态；
  本轮与上一轮统一报告及嵌套 M1 报告均在不挂载构建、语料和项目配置的禁网环境逐字节复算一致。
  当轮剩余 18 项未绑定：CORAD 12、PBEPLA 3、Gorilla 2、XZ 1。M0 和正式资格状态不变。
- [CORAD C 与 Source 训练](../results/m0-corad-training-bindings-20261119-r1/native-report.json) 新绑定两组 11 项。
  `tsbench` 禁网运行 `a4cabc5f06f948e9bfe37b9a3ba7aeee` 复用冻结构建，**90 项 Python 测试、23/23 个开发探针**通过，
  36/36 原生组有通过的开发探针。训练槽封存 17 份、20,701 字节；C 固定 seed 两次同字节，但达到 6 次迭代上限仍未外层收敛，
  Source 两次保持默认 RNG、结果不同，分别绑定模型并实测独立留出恢复。复算拒绝伪造外层收敛、换桥、换矩阵、换字典、
  伪造恢复或少报 RMSE。本轮及上一轮统一报告和嵌套 M1 报告均在不挂载构建、语料或项目配置的禁网环境逐字节复算一致。
  剩余 7 项未绑定：PBEPLA 3、Gorilla 2、XZ 1、CORAD 正式质量界 1；未授任何正式资格。
- [XZ 调用线程同步对照](../results/m0-xz-synchronous-bindings-20261119-r1/native-report.json) 补齐 `xz-workers`
  的 `synchronous_control`。`tsbench` 禁网运行 `f961b3c1f2d04f7baf0694a69858a3e8`，**90 项 Python 测试、23/23
  开发探针**通过，36/36 原生组有通过的开发探针。只更新诊断、复用冻结算法构建；同步编码和 `threads=1/2`
  匹配配置，17 块的三份帧在固定输入上逐字节相同。同步和两个 MT 解码对照读取同一份双 worker 产物，均恢复原字节；
  同步无 MT hook，1/2 两档观察到不同 worker 数。复算拒绝用同字节的另一路径冒充共用帧、伪造 hook、配置、
  块大小或恢复摘要。新旧两轮的外层与嵌套 M1 报告均在禁网且不挂载构建、语料和项目配置时逐字节复算一致。
  剩余 6 项未绑定：Gorilla 2、PBEPLA 3、CORAD 正式质量界 1；M0 未通过，正式原生资格仍为 0/36。
- [Gorilla 原生工作量观测](../results/m0-gorilla-work-bindings-20261119-r1/native-report.json) 补齐 resume 扫描/复制与
  iterator 扫描/不回退两项。`tsbench` 禁网运行 `f644414469e447e8bf6de7046611dc16`，**91 项 Python 测试、23/23
  开发探针**通过，36/36 原生组有通过的开发探针。Gorilla worker、适配器与 C DSO 的构建锁与上一轮相同。
  恢复 23/512 行实扫 23/512 行并分别复制 184/3,733 字节；空块和尾校验失败不复制。前向 seek 实扫 51 行，
  随后的回退请求返回当前位置、零扫描；复算拒绝伪造扫描、复制、回退结果、终止调用或诊断构建身份。
  两轮的外层与嵌套 M1 报告均在禁网且不挂载构建、语料和项目配置时逐字节复算一致。剩余 4 项未绑定：
  PBEPLA 3、CORAD 正式质量界 1；M0 未通过，正式原生资格仍为 0/36。
- [PBEPLA 值层预算、非法输入与 replay 故障](../results/m0-pbepla-failures-bindings-20261119-r1/native-report.json)
  补齐两组剩余三项。`tsbench` 禁网运行 `d62bd811068b4562b0407330f522c7ae`，**92 项 Python 测试、23/23
  开发探针**通过，36/36 原生组有通过的开发探针。16 层的 131,072 值在限额处编码与独立解码成功，
  131,073 值编码及合法超限帧解码均以资源上限拒绝。四类 replay 故障均确认输出状态与临时文件释放；
  sink 失败保留 95 字节不完整头部，原生第 1 层也拒绝恢复。复算拒绝伪造状态、错误源摘要、漏关文件和故障头部篡改。
  两轮外层与嵌套 M1 报告均在禁网且不挂载构建、语料和项目配置时逐字节复算一致。只剩 CORAD 预声明质量界
  一项未绑定；M0 未通过，正式原生资格仍为 0/36。
- [CORAD 预声明原始域质量判定](../results/m0-corad-quality-gate-20261119-r2/native-report.json) 绑定最后一项开发检查。
  `tsbench` 禁网运行 `58994e073b3744ce8859e7c4682cf843`，**94 项 Python 测试、23/23 开发探针**通过。
  以 129 行冻结 train 的逐列均值基线计算误差界，对独立 67 行 test 的两份冻结部署实际判定：温度达标，
  气压和湿度超限，两条部署均为 `quality_rejected`。探针成功表示产物、观测和拒绝判定均有效，
  不表示质量通过；复算拒绝改宽边界、替代校准输入或把拒绝伪报为通过。两轮外层和嵌套 M1 报告均在
  无构建、语料或项目配置挂载的禁网环境逐字节复算。开发绑定 180/180，M0 未通过，正式原生资格仍为 0/36。
- [六项条件性原生工作](../results/m0-native-conditional-work-20261119-r1/native-report.json) 绑定同一计划和账本，
  `tsbench` 禁网运行 `3519053b31db49b3b075cf494705a285` 通过 **101 项 Python 测试、23/23 开发探针**，
  36/36 原生组有通过的开发探针。ALP AVX2、ZFP OpenMP、Zstd MT、XZ MT 四项观察到要求的实际工作；
  ALP AVX512BW 原生对象已构建，本宿主不可用；Huff0 BMI2 已实调，但缺同次 portable 构建对照。
  失败、跳过和取消不推断硬件条件。新旧两次外层及嵌套 M1 报告均在禁网且无构建、语料或项目配置挂载的环境
  逐字节复算。此次没有更换或重编原生内核，也未授正式资格：M0 未通过，正式原生资格仍为 0/36。
- [Huff0 同次 portable 解码对照](../results/m0-huff0-same-run-control-20261119-r2/native-report.json) 用两个现有
  构建，在单计划、单运行、单账本内解码同一份主输出。`tsbench` 禁网运行 `81703af8dede4590ae70411d6bd05f89`
  通过 **106 项 Python 测试、24/24 开发探针**，36/36 原生组有通过的开发探针。5 份 FEC1 载荷和 14 份 ETB1 块
  用 4 个主模型完成独立恢复；两侧实际调用均为 3/4/4，分别传 `bmi2=1` 与 `bmi2=0`。
  不重编内核、不重训或重新编码生成对照产物。修正测试覆盖主探针未通过与 portable 自身启动失败的终态区别。
  本轮和上一轮的封存外层及嵌套 M1 报告均在禁网、无构建、语料或配置挂载的环境逐字节复算。
  六项条件中五项满足开发检查，ALP AVX512BW 仍待兼容宿主；M0 未通过，正式原生资格仍为 0/36。
- [比较合同与实际候选计划](../results/m0-comparison-contract-20261119-r1/native-report.json) 将 R/O 条件、
  四类恢复任务、固定 T/V、同资源预算、批/流访问、时间/字节边界、验证和留存纳入机器可读定义。
  `tsbench` 禁网运行 `cc89c7cb360b47b0a362d4ff0407a11a` 通过 **111 项 Python 测试、24/24 开发探针**，
  36/36 原生组有通过的开发探针。嵌套 M1 候选实际验证 raw-store/Zstd/ALP 的 **18 个产物**，
  共享六输入 × 两方向的 12 个冻结 O 轨道比较键；没有一项进入正式排名。CLI/API 一致，计划和复算
  拒绝比较 schema 或合同失配；R/O、资源及 stream 正反例不作为实测流式证据。新旧两轮外层及嵌套报告
  均在禁网、无构建/输入/项目配置挂载的环境逐字节复算。尚未冻结首批全部适用域、访问限额、资源执行与
  依赖留存政策；M0 未通过，正式原生资格仍为 0/36。
- [候选资源观测与验证后暂存回收](../results/m0-resource-retention-20261119-r1/replay/current-m1-report.json)
  接入 M1 候选 `artifact_each` 的同一计划和原有账本；每个 slot 实查结果文件系统的空间/inode 与主机
  `MemAvailable`，真实子进程用 Linux `wait4` 记录 CPU 和 `ru_maxrss`。禁网外层运行
  `10033f88242c43d9ab75d26a83765dc1` 通过 **115 项 Python 测试、24/24 开发探针**，36/36 原生组有
  通过的开发探针。候选 18 个独立帧均保留，36 次操作有子进程观测；逐项验证并写入账本后回收 36 个
  恢复暂存文件（419,331 逻辑字节）。集成负测注入低 inode 读数，18 个 slot 均阻断且未启动 worker；
  单独的真实非零退出保留两份暂存输入及失败证据，随后 17 个 slot 记取消。新旧外层及嵌套 M1 报告无
  构建、语料和项目配置挂载时逐字节复算。此结果不是硬资源隔离，仍缺正式资源/依赖闭包：M0 未通过，
  正式原生资格 0/36。
- [候选保留帧独立恢复](../results/m0-recovery-closure-20261119-r1/replay/restore-audit.json)：禁网外层
  `0a3771dd622e4c769579ac2dbaed6a49` 通过 **115 项 Python 测试、24/24 开发探针**，36/36 原生组
  有通过的开发探针。内层候选 `6ad456e550ce400db69bac7cc5c30acb` 以一套 11 文件、10,069,152 逻辑字节的
  解码闭包覆盖 18 个 verified slot，已回收 36 个验证暂存文件。搬迁后只挂载封存运行与控制层工具，
  每个解码子进程进一步做到仅挂载帧与封存依赖；**18/18 实际恢复**，shape 和值/schema 哈希一致。
  [实际负对照](../results/m0-recovery-closure-20261119-r1/replay/restore-negative-controls.json) 验证缺 ALP 共享库
  无法回退宿主，且有效同形异帧及错误 schema 哈希被拒。集成负测还覆盖篡改 seal 的文件集/slot 绑定、
  复制中故障不发布闭包且不删除已验证输出、规划后缺 worker 的完整终态。新旧外层与嵌套报告均独立
  逐字节复算。此闭包不扩展至其他首批路线，不是正式隔离、发布或阶段资格；M0 未通过，正式原生资格 0/36。
- [Gorilla 拆分开发实证](../results/m3-gorilla-roles-20261119-r2/recomputed.json)：`51205ca3db614db4bd55aa7bf04d6ba4`
  在禁网、搬迁路径、空构建下通过 **116 项 Python 测试与 4/4 定向 CTest**，其中原生 TV 回归与两个派生
  DSO 的角色差分均通过；同一 run **16/16** 派生帧与原生对应角色的 bit token 一致，16 个被预声明的错误输入/坏帧拒绝。
  [独立恢复](../results/m3-gorilla-roles-20261119-r2/restore.json)在不挂载项目构建、语料、TV oracle 或相反角色 DSO 时，逐帧
  恢复 16/16；报告不依赖原环境且逐字节复算。[角色合同](contracts/gorilla-derived-roles.md)不继承原生资格；固定 T/V 的
  实际组合、第二个 T provider 与完整四类任务仍未验收，不改变 12 项选择及 36 组原生分母。
- [完整对象 T+V 组合预检](../results/m3-tv-composition-20261119-r2/report.json)：迁移路径、空构建、禁网、`tsbench`
  运行 `afeb624b969443f5a16aa2a8bd129698`，**119 项 Python 测试、6/6 定向 CTest、15/15 完整对象**逐产物实测验证。
  [控制与拒绝证据](../results/m3-tv-composition-20261119-r2/controls.json)记录 4 组固定 T、4 组固定 V、3 组原生 TV/组合
  配对，固定支路实际帧一致，但各方法拥有独立执行会话和完整字节账。515 行、两 V 列用例实跑 512+3，并且每块仅
  存储一份 T。14 项配置/数据/坏帧负测通过。报告可独立逐字节复算，[审计](../results/m3-tv-composition-20261119-r2/restore.json)
  在不挂载原构建或语料、只挂载该方法的解码闭包时实际恢复 15/15。证据为 O 轨开发诊断，不授正式资格，
  不代替 M0 退出门槛或 M3 的 f64→u16、跨格式、其他管线和组合资格。细节见 [组合合同](contracts/tv-composition.md)。
- [固定 T 的 TVVVVV 位片对照](../results/m3-tv-limbs-20261119-r2/report.json)：同一台机器、同一 `tsbench` 环境，
  迁移路径、空构建、禁网 run `3819701a69b843e5bb893a17d127b562` 通过 **120 项 Python 测试、5/5 定向 CTest**
  （含原四通道插件回归）。固定 Gorilla-T，比较直接 ALP f64 与 5 V → 20 u16 通道的 Sprintz-FIRE；真实交通与特殊位型
  两个 515 行对象各跑两方法，**4/4** 完整对象位级验证。[控制证据](../results/m3-tv-limbs-20261119-r2/controls.json)
  核对独立编码的 T 字节相同、512 行块实际含 packed blocks、3 行尾为 60 个 literal u16、完整 bundle 计费；12 项负测通过。
  [方法闭包隔离恢复](../results/m3-tv-limbs-20261119-r2/restore.json) **4/4**，新旧报告从各自封存目录逐字节复算。
  该证据补实 M0 要冻结的分组方法合同和 M3 的完整位片开发对照，不替代跨格式、资源隔离和阶段验收，不增加原生资格。
  见[位片合同](contracts/tv-limb-comparison.md)。
- [M3 跨格式 T+V 候选](contracts/tv-cross-format-ingress.md)：`tsbench` 单次禁网迁移构建，run
  `8329e182834e4615a7dc1c0efc108608`，通过 **152 项 Python 测试、5/5 CTest、12/12 实际产品验证及独立恢复**。
  两个 515 行对象各有 CSV、NPY、TXT 三种原字节身份，但每组只计一份规范化身份与逻辑权重；两条固定 T 方法分别在
  三格式产物间逐字节相同。[主报告](../results/m3-tv-cross-format-20261119-r2/report.json)将 6 个来源解析计时与 worker 时钟分开，
  [控制](../results/m3-tv-cross-format-20261119-r2/controls.json)核对 24 个独立操作会话、CLI/API 同计划及重新封存后仍拒绝错误绑定。
  [恢复](../results/m3-tv-cross-format-20261119-r2/restore.json)不挂载原始数据或构建，重算恢复对象 ID；报告逐字节复算。
  r2 不拼接 r1。覆盖明确的非空值 i64/f64 入口、负零、NaN payload、非整除时间拒绝及真实尾块；不覆盖独立 T-only/V-only、
  通用源文件端到端计时或有损转换，不提高正式资格或有效服务计数。
- CORAD、PBEPLA-RR 随包 NOTICE 记录未声明授权的上游快照；Huff0 头文件引用的上游
  LICENSE/COPYING 未作为独立文件出现在冻结包内。此处只记录本地核对事实，不推导
  重新分发资格。归档可构建和发布授权、依赖闭包是分开的验收项。

- [M1 v3 执行时文件隔离](contracts/m1-lossless-candidate.md#v3原始运行即隔离不仅是事后恢复)：空构建
  `8eec7da8e6d743739f86c33b02a8d9cf` 真实运行 raw-store/Zstd/ALP，18/18 独立验证和搬迁恢复，报告逐字节复算。
  锁定依赖的启动器在同次运行隔离每个 encode/decode，记录逐操作挂载身份；另有完整错误、崩溃、超时、运行中取消
  与缺依赖终态对照。启动器墙钟及直接子进程资源只作诊断。本证据不改变 M0 阶段、原生分母或 M1 正式验收状态。

- [M2 绑核批测量开发候选](contracts/m2-frame-timing.md)：将既有直接/框架批探针接入统一 CLI/Python 计划、
  协作锁和单次账本。两个同计划 run 各 128/128 verified、48 对完整轮次，均可在禁网无原构建条件下逐字节复算。
  保留锁竞争、取消、缺库及校准失败证据。未建设正式独占资源、缓存外案例和中断恢复，不改变阶段状态与覆盖分子。

- [M4 原生剖析开发候选](contracts/m4-native-profile.md)：独立无插桩/关 trace/开 trace 三臂，28/28 真实
  roundtrip，禁网复算逐字节一致。ALP 有融合 L2、Zstd 有两 worker 的实际重叠区间、XZ L2 为 opaque；
  容量压力实测丢失，cycles 缺测保持 null。结果不替代主计时、完整 pipeline 或正式阶段验收。

**现在先补 M0，不启动 M5 服务建设或 M7 扩量。** 后续阶段状态必须由相应完整冻结计划、
实际执行和阶段结论推进，不能由当前源码构建审计或静态测试代替。
