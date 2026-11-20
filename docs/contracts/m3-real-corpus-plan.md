# M3 更新版真实语料统一计划

`results/m3-real-r40-20261120/plan.json` 是当前 M3 的统一开发计划，绑定：

- `results/m0-real-corpus-acceptance-20261119-r1/receipt.json`
- `results/m1-real-r8-20261119/receipt.json`
- `results/m2-real-r8-20261119/receipt.json`
- `results/m0-native-corpus-definition-20261119-r8/plan.json`
- `results/m3-real-r8-20261119/build-lock.json`

计划分母为 23 个数据集、36 条路线、828 个文件—路线决定，其中 724 个适用输入
进入执行，74 个域外输入和 30 个未触发条件只登记状态，不执行。必需义务为 180
项，条件义务为 6 项。

计划已经把所有适用项放入同一提交、同一主账本的执行边界；执行器内部可以按资源
分批加载、受限并行或从检查点恢复，但不得产生分片收据，也不能从多个运行拼接
正式全量结果。

## 当前执行状态

已实现 `m3-real-corpus-run` 的真实 native preflight。它通过工程内
`tsbench_corpus_worker` 对实际复制到 `datasets/raw/` 的原始文件进行完整读取，
对适用的通用 roundtrip 路线执行 artifact_each 恢复校验，并在临时产物释放前记录
hash/size。当前已验证的 preflight：

- run `e90c45085d4e462e8cd26aa71deca94a`
- 23 个 `selection=9/auto-batch` 输入全部 verified；
- 23 个 `decode-backends` 输入分别用 `scalar-unfused` 和 `falp-auto` 在进程内回验；两条路线合计 46 个开发回验终态，未证明共帧或独立解码，见后文 r37/r39。

这只是开发预检，不是 M3 收据。剩余路线专用操作（页/流/范围/query、训练/模型、
字典/会话、TV snapshot/iterator、ZFP 写入、ALP 多后端等）必须继续通过其原生入口
完成后，才能签发新版 M3 全量收据。

## pcodec 原生页驱动（r12 开发预检）

- `results/m3-real-r12-20261119/plan.json` 在同一 M0–M2 与 828 项适用性分母上，另锁定
  `tsbench_pcodec_pages_control`、其同目录的 `libpcodec_c.so` 和 M3 页适配器的哈希。
  构建原生 control 的目标是 `tsbench_pcodec_pages_control`；运行不读取 Unique 工程。
- `source-pages` 调 `pcs_*`，`native-pages` 调 `pcn_*`。逐列按最多 65,536 值成组，组内
  用 4,096 值完整页和真实尾页，显式给出页序及长度。Source 解码限额按页，C Native
  解码限额按组累计；两条路线都验证原生拒绝 257 容量后，用符合 ABI 且未超过请求的
  256 容量排空。它们都是完整压缩页输入的增量解码，不是网络输入流。
- 恢复进程只收到 `PM3PAGE1` 框架封装，其中有页布局、共享元数据和页载荷；允许只有元数据
  而不需要页载荷的合法页。恢复后的 f64 原始位模式由控制层独立比较。主账本记录逻辑字节、
  页载荷、元数据、封装字节及独立恢复样本；每方向另记单次操作壁钟、进程 CPU、峰值 RSS
  与外层进程壁钟。该诊断未执行 M2 正式重复/资源协议，不作吞吐或排名准入。
- r10/r11 的开发账本保留了误拒零载荷页的失败记录；不将跨计划记录合并为全量结果。
- r12 预检 `results/m3-real-runs/c234bb4903254126a9a685d381e245c2/report.json`：两个页入口分别
  在全部 23 个文件执行，合计 46/46 验证通过、46 份封存样本复解成功；实际包含 4,842 个零载荷页。
  这是单次路线筛选预检，不能代替全量主账本或 180 项必需义务的对账。

## Titchy 原生访问（r13 开发预检）

- r13 不改 M0 定义或 Titchy ABI 插件清单。新增目标 `tsbench_titchy_corpus_access_control`，
  计划锁定该控制程序、同目录的 `libtitchy_c.so`、执行适配器和独立 TCHY wire validator；
  校验时逐条从已接纳 M0 定义重建路线、适用性决定和专项义务，不能仅靠重算计划哈希修改它们。
- `batch-range` 调 `titchy_c_range`，按 native 合同先验证整帧再返回中点窗口。
  `loaded-file-access` 分别真实调用内存 callback reader 和 `FILE` reader，各从同一 handle 读取首/中/末点、
  三个 MSB-first 位和中点窗口；按原始 f64 位模式核验。只对内存 callback 统计逻辑请求字节，不将其
  当成 `FILE` 的读量或物理 I/O。端到端进程壁钟与各原生调用的单次壁钟分开，不授计时准入。
- [本次报告](../../results/m3-real-runs/69b3bdb7337e428db156e5a9e202c4aa/report.json)：每条路线覆盖
  全部 23 个数据集的 V 列和 2,751 个实际编码块；合计 46/46 项逐位恢复。每块以独立进程仅用
  TCHY backing 和计划行数复解，46 份留样另由独立 Python wire decoder 重解并核对摘要。
  账本对账了完整 backing、头、索引及字典/页体字节；本次没有执行 `packet-stream`。
- IntMult 的 23 个实语料决定仍为 `outside_declared_domain`（无符号整数原生域，不以 f64 位片凑覆盖）。
  [历史 sealed-run 复核](../../results/m3-intmult-evidence-review-20261119-r1/restore.json)独立重放了
  三个整数产物和三个原生拒绝；这是专项历史证据复核，不替代当前合同的四项重跑义务。

## Titchy 原生包流（r14 开发预检）

- [r14 计划](../../results/m3-real-r14-20261119/plan.json)锁定 `tsbench_titchy_corpus_stream_control`、
  同目录 `libtitchy_c.so`、实际适配器、调用器与独立 TSTR 验证器。执行范围仍为 M0 声明的完整 V 列，
  读取可分批，但同一列只建立一个原生 packet session；不是截成多个 batch 块后再拼接。
- 使用 4 值/chunk、7 chunks/packet、1,000 chunks/split、72 B 活跃字典预算。主记录分开计费
  TSC1 配置、TSTR 封装和 packet payload；区分 push 首包与 finish 首包，也区分 finish 无新包、
  有未满 packet 与存在补零样本。负对照、reset 重放和文件 I/O 不进入单次内存主时钟。
- 每列以另一个原生进程仅用 TSTR 和 TSC1 复解，再与原始 f64 逐位比较；每项保留一组可供独立
  Python wire decoder 复解的双文件样本。开发测试覆盖空尾、补零尾、切换 split 时 finish 发出两包、
  背压重试、截断和配置篡改。不能替代路线的六项专项义务，也不构成 M2 计时或新版 M3 正式验收。
- [预检报告](../../results/m3-real-runs/201e174cdfb547ba9eabc21c0e40464e/report.json)：23/23 项通过，
  共 2,737 个整列 session、2,785,066 包。23 组留样另行复解并核对摘要，主账本与报告逐项一致。
  384 个 session 在 finish 时不再出包，385 个 session 有补零尾。本配置的完整产物共 900,402,840 B，
  大于 622,954,272 B 逻辑输入；实际膨胀照实记录，不用修改参数或剔除输入来覆盖该结果。

## pcodec IntMult 专项（r15 开发预检）

- [r15 计划](../../results/m3-real-r15-20261119/plan.json)根据 M0 的 case ID 与 bundle ID 重建 4 项义务、
  6 个专用 fixture，冻结全功能 pcodec 控制程序的独立 ELF 闭包和资源限额，不读取旧运行结果。
- [隔离预检](../../results/m3-real-runs/1f01d140d28d42c580201e721142446d/report.json)在同一个 run 的
  `ledger.jsonl` 记录 23 个浮点文件域外决定与 4 个 `specialized_obligation` 终态。三份无符号整数产物
  独立恢复通过，分别验证实际 IntMult、精确 64 位基数和 Classic 回退；三份预期拒绝均保留 native
  `PC_INVALID` 日志且不产生输出。已保留[外层沙箱不允许创建隔离网络命名空间的失败尝试](../../results/m3-real-runs/44b18241474d428d81557022aa336247/report.json)，
  不把隔离失败计为算法拒绝。
- `m3-intmult-audit` 核验报告与主账本封存摘要、域外决定、义务到 fixture 的映射、日志及产物；
  [独立重放](../../results/m3-real-r15-20261119/intmult-audit.json)再次验证闭包仅挂载压缩帧即可恢复，
  以及无产物预期拒绝。无路线过滤或工作项限额时，
  执行器同时登记全部文件—路线决定与义务；还未绑定的义务保留 `not_run`。这次仅为定向预检，不签发 M3 正式收据。

## Sprintz 压缩域查询（r16 开发预检）

- [r16 计划](../../results/m3-real-r16-20261119/plan.json)冻结 `tsbench_sprintz_corpus_query_control`、同目录
  `librepaired_codec.so`、适配器及 SFB1 验证器。加载器逐批将每个 f64 单元原样搬到对应列，每个值按位切为
  四条 little-endian 无符号 `u16`；每列每帧最多 8,192 行（65,536 B）。四 lane 是数据通道，不是四线程。
- 编码、查询和完整恢复在不同进程进行，查询进程只读取 SFB1；自动分派走 `upstream_simd`，强制标量供
  交叉对照。逐帧比较 COUNT/SUM/MAX 与原始位片的独立 oracle，并逐字节比较完整恢复。原生操作单次壁钟和
  包括 I/O 的进程壁钟分别记录；不是 M2 正式重复、资源测量或性能排名。
- [预检报告](../../results/m3-real-runs/fad90e05963a41c8ba557c37ef15e6a6/report.json)覆盖 23/23 个文件、
  2,737 列和 11,610 帧；622,954,272 B 逻辑输入对应 446,781,266 B 完整 SFB1（头 371,520 B、载荷
  446,409,746 B）。[留样复查](../../results/m3-real-r16-20261119/sprintz-query-audit.json)核对主账本封存、
  计费与全部 23 份留样的查询和恢复。查询范围不外推到原始 f64 数值；Sprintz 查询的 5 项专用义务仍待新版重跑。

## Gorilla C11 TV、快照续写和迭代（r17 开发预检）

- [r17 计划](../../results/m3-real-r17-20261119/plan.json)绑定与 Unique 原版一致的 `libgorilla_c.so`。
  按声明把源民用秒坐标乘以 1,000，先验 i64 范围与可逆性，保持源顺序，不解释成 UTC；V 使用原始 binary64 位。
  路线按列、每 512 行切独立块。报告分别记录唯一 T/V 逻辑字节、每列实际提交的重复 T、原生 XORChunk 字节、
  完整 GTV1 归集封装开销。GTV1 不改原生块，也不是公共 ABI 的 TV 帧。快照独立计费；传给 resume 的快照字节数
  不等同于物理 I/O 或 memcpy 计数。
- [隔离源参数的预检账本](../../results/m3-real-runs/04f80100ec4f4f878b6429fe4bc8ebb4/report.json)：
  16 个适用文件的 `tv-batch`、`iterator` 各 16/16，共各 153,713 块逐位恢复；iterator 逐块排空并核验
  前向 seek。`append-resume` 6/16（30,566 块逐位恢复），另 10 个文件在续写—batch 字节对照中失败，
  不算通过。7 个没有毫秒映射的源索引文件每条路线记域外；12 个专项义务仍为 `not_run`。
  [复查](../../results/m3-real-r17-20261119/gorilla-audit.json)验证完整账本、成功范围的逐块产物一致性及 44 份留样独立解码。
- [ETTh2 失败样本](../../results/m3-gorilla-resume-counterexample-r17/report.json)锁定第 3 个 V 列的
  零基行区间 `[7680,8192)`，快照 256 行。无 XOR 窗口时迭代器把 `lz` 初始化为 `0`，resume 继承它，
  将第一次非零 XOR 编成「复用窗口」。冻结同库能读回此非规范帧，但独立 wire decoder 以“未定义窗口”拒绝；
  不间断和原版 batch 的码流一致且均独立恢复通过。四行固定用例能复现同一故障。
- [候选差异](../../third_party/patches/gorilla-c11-resume-initial-window.candidate.patch)仅将初始窗口改为
  与原编码器一致的未定义哨兵。在另一个目录从 Unique 源归档构建，[诊断重跑](../../results/m3-gorilla-resume-repair-probe-r1/report.json)
  覆盖全部 16 个适用文件、153,713 个块，最终帧与原版 `tv-batch` 逐块完全一致，快照与最终帧均恢复通过。
  修补未进入正式来源锁或 r17 构建；候选结果不可覆盖既有失败或作为新版阶段收据。


## Gorilla 状态修补身份与专项复核（r19 开发预检）

- [Unique 基线记录](../../../Unique_Selected_Compression_Rewrite/docs/bench/Unique当前算法指向与运行基线.md)的第 7 项是
  `fix_Release/gorilla-native/unique-v1` 的 C11 `gorilla_c`。TSBench 的 C++ `adapter.cpp`、`corpus_control.cpp`
  分别是 ABI 适配器和语料控制程序，不是另一个 Gorilla 算法。r19 的 `tv-batch` 继续使用 r17 的原版 C11 库。
- 仅在 `m3-real-corpus-plan --gorilla-state-repair-lock <repair-lock.json>` 显式选用时，`append-resume`、`iterator`
  绑定 [修补身份](../../catalog/selections/gorilla-state-repair-v1.json) `gorilla-c11-unique-v1+tsbench-state-repair-v1`。
  构建使用原始归档重新展开，只应用冻结的窗口初值差异；原版归档、来源锁及 r17 的 10 项失败不变。专项原版 TV 和
  修补状态使用分开的隔离依赖闭包，同名 `libgorilla_c.so` 不互相覆盖，也不覆盖 IntMult。产品、义务及额外回归均进入
  本次 run 的同一主账本；隔离证据子目录不签收据，不产生另外的 run ID。
- [r19 主账本报告](../../results/m3-real-r19-20261119/runs/b12932165be749aba5274d53df132936/report.json)：
  三条路线各通过 16/16 个适用文件和 153,713 个块，各有 7 个文件保持域外。三条路线的最终帧与恢复位逐块一致。
  同一次预检中 12/12 项冻结专项通过（TV 4、续写 5、迭代 3），包括预期的资源限额拒绝、坏快照拒绝、续写扫描和复制计数、
  迭代前向查询与不支持的后退。额外四行回归复现原版失败，修补版的快照和最终帧均通过脱离原输入的原生恢复与独立解码；
  回归不替代 12 项义务。
- [独立审计](../../results/m3-real-r19-20261119/gorilla-audit.json)核验主账本、逐块哈希对照及 64 份原生帧/快照留样，
  并在 Bubblewrap 下重放专项恢复和预期拒绝。该报告只覆盖 Gorilla 三条路线，既不是 M3 全量验收，也不授予性能计时资格。


## Sprintz-FIRE 公共 ABI、压缩域查询和专项（r20 开发预检）

- 继续使用 Unique `fix_Release/Sprintz-family/unique-v1` 的 `repaired_codec`（归档 SHA256
  `18c47f8dd0dae6770b4147b1a2870dc9c73e8927efe9761e7fe9bd3c10fd6466`），沿用已有构建，不改核心或来源锁。
  复核了 `fix_ReWrite/Sprintz-family` 的强 ISA 构建选项和 SIMD query 修复报告。自动后端在此四条 u16 limb 通道
  走 generic SIMD；低维标量仅是 query 后备，不表示无 AVX2 的完整 codec 可用。
- `fire-batch` 按列每 8192 行（最多 65,536 B）提交四条小端 u16 limb。每件从实际公共 ABI 编码产物校验外层
  schema、SFB1 结构、CRC 和尾块，在新 worker 仅提交压缩帧恢复、逐位核对。本预检的语料子进程计时包含启动与 I/O，
  不是 M2 计时；合规隔离的专项另通过 Bubblewrap 在声明的 ELF 闭包下执行。`query` 保持直接原生压缩域归约及
  标量 oracle 交叉验证，不能当成原始 f64 数值统计或跨消息 stream。
- [r20 同一主账本的报告](../../results/m3-real-r20-20261119/runs/681dd43d54a94599be2504f95352ca01/report.json)：
  两条路线各 23/23 个文件、11,610 块；各自 622,954,272 B 逻辑输入。逐块校验两条路线的 SFB1 与恢复字节哈希一致。
  每条路线的 SFB1 共 446,781,266 B，公共 ABI 再计 1,369,966 B 封装，完整产物 448,151,232 B。
- 冻结的 10 项专项（batch 5、query 5）全部通过；20 个独立产品槽含 18 项恢复/查询验证和 2 项预期拒绝，全部进入同一
  run 的主账本。另逐项核对坏帧、原生限额、压缩输入专用挂载、低维后备、宽累加与尾部。
  [审计](../../results/m3-real-r20-20261119/sprintz-audit.json)重放语料留样 46 份，并在隔离下重放全部 20 个专项槽。
  该定向运行不是正式全量结果或计时准入。


## SElf* 全列有序 batch 与原生 add/finish（r21 开发预检）

- 继续使用 Unique 第 4 项 `elf-selfstar-native/unique-v1` 的 C11 `selfstar_c`（`SF_SELF_STAR=3`，F64），
  档案哈希 `0febcf79b0a42c1c58b042478ff476b2fcafbdfe4de5b1abc2e60c34839ba355`。
  复核了原构建的 `-ffp-contract=off -fno-fast-math` 及 stress/live 记录；没有沿用历史 V2 成绩或改动冻结库。
- `selfstar-batch` 走公共 ABI，`selfstar-incremental` 走原生 `begin/add/finish`、`read_begin/next`。
  每方向每个完整 V 列只建一个 native context：512 值原生块与尾块连续推进，换列才新建 context；
  解析和写出可按块完成，不改变原对象边界。读者仅接收已封存的 BMKSEL，必须消费哨兵才推进状态。
  本路线是已定块的增量读写，不声明未封块可读或跨消息在线 stream。双向子进程墙钟含启动和 I/O，不代替 M2 计时。
- [r21 定向报告](../../results/m3-real-r21-20261119/runs/119c8366170f4663b719cc48321b12de/report.json)：
  两条路线各 23/23 文件、2,737 完整 V 列、153,720 原生块，恢复位与全列帧哈希分别一致。
  每条路线 622,954,272 B 逻辑输入与 303,949,657 B 完整产物，拆为 302,927,800 B 原生码流、
  614,880 B 原生块长度记录、406,977 B 对象级封装和 schema。
- 同一主账本的 9/9 项冻结专项均通过（batch 5、incremental 4）。[独立审计](../../results/m3-real-r21-20261119/selfstar-audit.json)
  从冻结语料重算逐列原始摘要，复解 46 份完整列留样，并在 Bubblewrap 内重放 25 个专项槽（18 恢复、7 预期拒绝）。
  单独回归核对 10,017 行/20 块的跨 API 字节一致，证明第二块提前 reset 会改变块字节。仍为定向预检，不能替代 M3 全量运行。


## Titchy 公共 ABI 批处理、单列包流、访问及专项（r22 开发预检）

- 继续使用 Unique `titchy-native/unique-v1` 的 C11 `titchy_c`，不改冻结来源或构建。`batch` 按单列最多
  65,536 行提交公共 ABI，保留 f64 原始位模式，逐件核对 schema、TCHY 和封装，再由新 worker 只凭产物恢复。
  `batch-range` 和 `loaded-file-access` 使用同样的块边界，保留两种访问语义，不将请求字节数称为物理 I/O。
  `packet-stream` 以完整列为会话，校验包序、背压、finish 和重置；TSTR 与 TSC1 均计入恢复必需字节。
- [r22 定向报告](../../results/m3-real-r22-20261119/runs/439e95a65e32467b883072df07596d5e/report.json)：
  四条路线各通过 23/23 文件，各计 622,954,272 B 逻辑输入。`batch` 及两条访问各覆盖 2,751 块，
  三路原生 TCHY 和恢复哈希逐块一致；每条访问产物为 855,540,400 B，`batch` 再计 269,545 B 公共 ABI 封装。
  包流覆盖 2,737 个完整列和 2,785,066 个包，产物为 900,402,840 B。
- 22/22 项冻结专项全部通过；18 个专项产品槽为 15 个正向验证与 3 个预期拒绝，全部登记于同一主账本。
  [独立审计](../../results/m3-real-r22-20261119/titchy-audit.json)从冻结语料重算原文哈希，重放 92 份留样及
  隔离内全部 18 个专项槽。这是路线定向运行，不代替 M3 全量验收或 M2 正式性能计时。


## ZFP 全列 field 与 fixed-rate 数组窗口（r23 开发预检）

- 复用 Unique `zfp-native/unique-v1` 的 C11 `zfp_native_c`，沿用 OpenMP 开启、CUDA 关闭的 CPU
  冻结构建。r23 增加 `tsbench_zfp_corpus_control` 并绑定二进制、动态库和控制层代码哈希，不改来源锁。
- `field-baseline`、`field-modes` 和 `openmp-encode` 的语料主路径按完整 V 列执行 rank-1 f64 reversible。
  rate/precision/accuracy 的误差、跨类型、跨维度和 stride 边界依旧由专项覆盖，不能从语料可逆结果推断。
  OpenMP 路线以相同原始列独立编码 serial、OpenMP 1、OpenMP 2，每种产物在新进程串行解码并逐位核对；
  线程配置不代表两个线程都完成过块工作，实际 TID 分布仍须由单独冻结的观测专项证实。
- `fixed-rate-array` 逐列按冻结的平衡窗口（每窗 8–4,096 行）执行，不把有排除区间的 window 集称作整列编码。
  每窗使用请求 18、对齐 32 bit/value；真实点写、跨块范围写、flush 后分别重开初始和更新数组，
  并对原始窗口及精确写入后的参考值检查误差。未触及的块同时比对原生码流和恢复位。误差超限保留为
  `quality_rejected`，不调高 rate、不放宽误差门槛、不跳过未触及的窗口。
- [r23 冻结计划](../../results/m3-real-r23-20261119/plan.json)四条路线各有 23 个适用文件。
  本次为语料路线定向预检；ZFP 的 19 项必需专项、1 项 OpenMP 条件专项和正式 M3 全量验收均不由 r23 自动授予。

- [r23 封账报告](../../results/m3-real-r23-20261119/runs/549c4634ae9e4ada9518e66873b0040e/report.json)：
  三个完整列路线各通过 23 个文件、2,737 列；数组 20,520 个窗口全部执行，17 个文件通过，6 个文件共 26 个窗口
  超出所冻结的误差界（17 个初始和更新重开均超界，9 个仅更新重开超界）。
  [r23 审计](../../results/m3-real-r23-20261119/zfp-corpus-audit.json)按锁定原件复算输入范围、核对主账本和计费，
  重放 92 份样本，每个拒绝文件至少重放一个超界窗口。拒绝不反授质量资格；不调整已有误差界或 rate。

## ZFP 专项绑定（r24 开发预检）

- 复用相同 Unique 库及其冻结直接控制。r24 绑定 19 项必需义务和 1 项条件义务：11 个公共 ABI 正向产品
  （i32/i64/f32/f64、IEEE 位型、尾块和字对齐）、3 个输入预期拒绝、4 个 rank/stride/模式产品、
  1 个同字段 OpenMP 实际线程观察、1 个原生数组缓存/重开产品。有效率/精度与请求值、有损误差、未触及 padding/块
  和坏输入均在对应产品中核对。编译成功不计作实际观测。
- [r24 独立审计](../../results/m3-real-r24-20261119/zfp-audit.json)核对同一主账本的 92 个文件—路线项：
  86 个通过，6 个数组文件共 26 个窗口保持 `quality_rejected`。20 项专项均通过；Bubblewrap 重放 20 个产品（含 3 个预期拒绝）。
  同一 8,192 值字段中，serial / OpenMP 1 / OpenMP 2 分别有 1/1/2 个线程执行原生编码块，OpenMP 2 的两个线程各处理
  1,024 块；三种码流相同，解码仅用调用线程。不授予全量或计时资格。

## PBEPLA-RR 多级前缀和有限源 replay（r25 / r26 开发预检）

- 原生渐进和回调 replay 使用 Unique `tba_native` 的 PBEPLA-RR 固定移植；`cmake/pbepla-corpus.cmake` 单独构建语料控制程序，
  不改历史构建身份。两条路线使用相同的锁定原始 f64 窗口，每条路线每个源文件仅加载一次；每个 PBEP 前缀由只持有该前缀的
  独立进程恢复。冻结绝对误差为 `[16, 4, 1]`，回到原始 f64 域精确验证。有限源回调记录实际遍数、重试、首写和逻辑临时 I/O；
  不是在线 push，也不是物理磁盘 I/O 剖析。
- [r25 封账报告](../../results/m3-real-r25-20261119/runs/e42ef13201c94efe995113e03347d286/report.json)有 46 个文件—路线项：
  42 个通过，4 个失败。两条路线各 20,524 个窗口，其中 20,521 个通过，`bitcoin-dataset-without-missing-values-1` 的
  V 第 0 列 `[0,2291)`、`[2291,4581)` 和 `bitcoin-dataset-without-missing-values-3` 的 V 第 0 列 `[0,4021)` 为原生 `RrGrid`
  30 位分辨率上限错误；保持 `failed`，不放宽门槛、不缩窗、不改判域外。[独立审计](../../results/m3-real-r25-20261119/pbepla-audit.json)
  核对成功窗口的逐层一致性并重放 42 份留样（126 个前缀）。r25 是纯语料预检，9 项专项均 `not_run`。
- [r26 冻结计划](../../results/m3-real-r26-20261119/plan.json)另绑定 9 项必需义务、33 个命名用例、13 个产品槽。
  正向与预期拒绝在 Bubblewrap 下执行；回调与 batch 的对照须来自同次运行。专项产品先于对应义务终态进入同一主账本，
  不另签收据。[r26 封账](../../results/m3-real-r26-20261119/runs/9db2f2bcf58a42e08f53ce81e22ee643/report.json)通过 9/9 项专项
  （11 个正向产品、2 个预期拒绝），语料仍是 42 个通过和 4 个失败。[r26 独立审计](../../results/m3-real-r26-20261119/pbepla-audit.json)
  对账 46 个文件—路线决定、13 个产品和 9 项义务，复核 20,521 对成功窗口的逐层一致性并重放 42 份三层语料留样，
  另在 Bubblewrap 下重放全部 13 个专项产品。专项结果不能覆盖语料失败或替代正式 M3 验收。
- [三个语料反例的单窗口复现](../../results/m3-real-r25-20261119/pbepla-rrgrid-counterexamples.json)：对应首层初始步长
  在 30 位下约为 46.05、23,282.04、68.35，均大于允许的 `2 × 16 = 32`，不是重试或前缀恢复导致的错误。

## Zstd/XZ 原生字节会话与 Zstd 字典（r27–r29 开发预检）

- 复用 Unique `lzbench-native/unique-v1` 的 `liblzbench_native.so` 和公开 `lzbench_extended.hpp`；不改 baseline 插件构建身份。
  真实语料 session 在完整交错 V 逻辑对象上调用 `lzbench_native::session::process`，307 B/521 B 为调用方缓冲，不是独立帧。
  逐对象独立进程只用帧和恢复上限解码，再与原始 V 逐字节比较。观测首次输出、部分消耗、满输出和重复 finish；
  首次输出墙钟含驱动文件 I/O，不能当作纯 codec 时间，也不由配置线程数推断实际并行。
- [r27 语料审计](../../results/m3-real-r27-20261119/session-audit.json)中两条路线各通过 23/23 个文件、622,954,272 个逻辑 V 字节，
  10 项专项均 `not_run`。[r28 审计](../../results/m3-real-r28-20261119/session-audit.json)保留同等 46/46 语料结果并重放 30 帧留样；
  同一主账本新增 10/10 项 session 义务，分别测两种 codec 的独立复位、finish、坏输入拒绝、隔离恢复等，2 个产品均经 Bubblewrap 重放。
  r28 字典控制的路径未绑定，23 份语料决策保留 `pending_driver`；后续 r29 冻结的是控制工具正确绑定后的独立字典路线，不回写 r28。
- 字典只向原生训练器提供同文件冻结 `train` 前缀，按预先锁定的短档/标准档一次训练，不窥视 `development` 或 `test` 来选择档位。
  留出按 65,536 B 的最大输入范围分别生成帧，每帧由另一个原生进程只用帧和序列化字典恢复。首个通过帧保存字典缺失、错误 ID 的拒绝，
  并保留一份帧及共同字典供独立审计；完整恢复的帧字节和只计一次的共享字典字节分列。字典命名专项和 worker 路线不由此自动授予资格。
- [r29 语料封账](../../results/m3-real-r29-20261119/runs/a7312feab5f7409390aa3e838abd84fb/report.json)通过 23/23 个字典文件：
  标准档 16 个文件、1,910 帧，短档 7 个文件、7 帧。[r29 独立审计](../../results/m3-real-r29-20261119/dictionary-audit.json)
  从原件复算各训练前缀及所有留出帧的输入身份，重放 23 组帧与序列化字典，并重放 46 次预期拒绝。
  本次只有字典语料，5 项命名专项保持 `not_run`；不授予正式全量或计时资格。

## Zstd/XZ worker 和字典专项（r30 开发预检）

- [r30 审计](../../results/m3-real-r30-20261119/profile-audit.json)复核一个主账本的 69 个决定：7/7 个适用 Zstd worker 文件、
  9/9 个适用 XZ worker 文件及 23/23 个字典文件通过。另 16 个 Zstd 和 14 个 XZ worker 输入未达到冻结门槛，保持
  `condition_not_triggered`，不填充。字典仍是 16 标准档、7 短档、1,917 个独立恢复的留出帧。
- 观测依据是冻结 `liblzbench_native.so` 实际 job hook 上的不同后台线程，而非设置值。Zstd 编码同步/两 worker 实测 0/2，
  两种产物各用新进程解码均无后台 worker。XZ `threads=1` 仍使用 MT API：显式另列 `lzma_block_encoder` 与
  `lzma_stream_decoder` 的调用线程对照。128 KiB Block、preset 1、CRC64 和 128 MiB 预算匹配；三路编码实测 0/1/2，
  另三路解码使用同一个 `threads=2` 帧，实测 0/1/2。9 个 XZ 文件三路编码帧逐文件一致，不将其推广到其他输入；
  独立恢复均返回完整原始 V 字节。本次只判定诊断覆盖，没有正式性能比较。
- 11 项必需与 2 项条件专项在同一主账本通过，包括 5 项字典命名专项。审计重放 3 个 Bubblewrap 专项产品、
  11 份 worker 留样和 23 组字典留样，未将样本与语料文件数合并计数。

## Huff0 ETB1 原生共享表（r31 开发预检）

- 复用 Unique `FiniteStateEntropy/unique-v1` 的 `libreference.so`。每文件冻结 `train` 前缀最多 32 KiB；不读取 development 或 test
  训练。1X 和 4X 各训练一份序列化模型，以一个 native `TableCodec` 上下文分别编码和恢复该 lane 的完整留出块序列，每块不超过 32 KiB。
  独立解码进程只获得自己的模型与 ETB1 块序列，逐字节核对交错 V 原域。ETB1 本身不含模型身份或 CRC；控制层以 SHA-256 绑定
  模型和块序列，另计该资产大小，不把错模型拒绝归为 native 校验，也不免除共享表字节。
- [r31 封账](../../results/m3-real-r31-20261119/runs/6e737af3fab8431a942b6f142a4260eb/report.json)通过 23/23 个文件。
  两种配置各处理 3,818 个留出块，1X 全部为 Huffman，4X 有一个 raw fallback。每个文件均检查两个不同合法模型不能代替彼此。
  [独立审计](../../results/m3-real-r31-20261119/table-audit.json)从原件重算训练前缀身份并核对留出、分块及完整计费，重放 32 组留样。
  5 项共享表命名专项保持 `not_run`；FEC1 独立帧和 BMI2 条件需要另验；预检不授予阶段或计时资格。

## Huff0 FEC1 与 ETB1 同账本语料（r32 开发预检）

- [r32 封账](../../results/m3-real-r32-20261119/runs/ae419223ce0a487290ecc3bd639b7ce3/report.json)
  覆盖两条路线各 23/23 个文件。FEC1 使用已冻结的 ABI 插件与 `libreference.so`，不回退到通用进程内 roundtrip。
  以最多 4 MiB 为进程调度单位，仍按 64 KiB 一帧、32 KiB 一原生子块处理，不改变独立帧边界，不添加批调度封装。
  编码与解码进程分离；解码只挂载串接的完整 ABI 帧和封存 ELF 运行闭包，不挂载原值、单独的输入 schema 或编码工作目录。
- [FEC1 独立审计](../../results/m3-real-r32-20261119/fec1-audit.json)重算 9,519 个帧和 19,027 个原生子块的
  原域几何、CRC、模式及字节账。165 次隔离解码覆盖全部语料，审计另在隔离内重放 35 个首尾帧留样。
  FEC1 的 486,775,171 字节含 ABI 头、内嵌 schema、FEC1 头、子块头与各模式 body。
  语料实测为 19,026 个 Huffman 子块和 1 个 RLE 子块；raw 由定向回归用例覆盖，不能记成语料观测。
- [同次 ETB1 审计](../../results/m3-real-r32-20261119/table-audit.json)核对两条表流配置各 3,818 个留出块，重放 32 组留样。
  两份审计是同一次主账本的路线视图，不是分片收据。11 项必需专项及 1 项 BMI2 条件专项仍为 `not_run`。
  已用 `prove_build_pair` 核对既有 `build/m0-huff0-portable-v1` 与 `build/m3-real-r8` 的提取源码及归一化编译、链接配方，
  差异仅是 BMI2 选项；此检查只确认可用对照构建，未在 r32 运行 BMI2 对照，不授予功能、计时或阶段资格。

## Huff0 两条语料路线、专项和 BMI2 条件（r33 开发预检）

- 经 `m3-real-corpus-plan --huff0-portable-build build/m0-huff0-portable-v1` 显式绑定 OFF 构建。
  两个闭包固定实际 ELF 字节和归一化配方，主工具与 FEC1、ETB1 语料驱动使用同一冻结 `libreference.so`。
  不提供 portable 构建时，必需专项仍可运行，条件保持 `not_run`；CPU 不支持 BMI2 时，有实际等字节 portable 恢复证据也不将条件标绿。
- [r33 主账本封账](../../results/m3-real-r33-20261119/runs/4311d97448d64a1f82fcc0017aa68b68/report.json)
  包含 46 个通过的文件—路线项、11 个专项产品（9 个有效产品、2 个预期输入拒绝）及 12 个通过的义务（11 必需、1 条件）。
  `fec1_fixed_4x_etb1_stream_boundary` 同时引用原生 FEC1 4X 和 ETB1 1X、4X 产品；ETB1 的错误资产绑定与原生坏长度拒绝分别验证。
- [专项审计](../../results/m3-real-r33-20261119/specialized-audit.json)逐条对账并独立重放 9 对正向产品。三类原生入口按 FEC1 4X、
  ETB1 1X、ETB1 4X 顺序，各构建完成调用 3/4/4 次。主构建实测 `bmi2=1`，portable 实测 `bmi2=0`；对照使用同一份 payload 或同一模型及块，
  不重训、不重编码、不挂原输入。另见同次的 [FEC1 语料审计](../../results/m3-real-r33-20261119/fec1-audit.json)
  及 [ETB1 语料审计](../../results/m3-real-r33-20261119/table-audit.json)。这些是同一账本的审计视图，并非独立收据或正式性能结论。

## CORAD 多 cohort 单次读取准备（未执行训练或推理）

[输入预检](../../results/m3-corad-ingress-20261119-r1/input-audit.json)核对 13 个适用文件的 346 个训练 cohort，
以及每个生产者对应的 587 个留出帧；三条路线的字节数与工作单位与冻结定义相等。新增 M3 提取器在每文件一次源扫描中按冻结的列序和
不相交行段收集各 cohort，保留原始 f64 位串、负零、分离训练与留出区间、文件结束时的完整源校验，并排除已声明的哨兵值。
回归测试与旧单 cohort 路径逐字节比较跨批结果，且复算 r6 两个真实 cohort 的既有输入绑定；未修改 M0 定义冻结的读取代码。
本次只核对 Source 桥和 `tsbench` 依赖、输入范围及质量门槛所用训练字节，不据此判定 CORAD 的训练、推理、质量或计时资格。

## CORAD 两个生产者及留出推理（r34 开发预检）

- [r34 主账本封账](../../results/m3-real-r34-20261119/runs/a57b736bf4254eb0ae1ef3cc307a7599/report.json)按冻结列序、训练分区和留出区间执行三条路线，保留 69 个决定中的 30 个域外项。
  每个适用文件只执行一次生产者/消费者组：C11 只挂载训练窗，Source 只挂载锁定桥和训练向量，留出编码绑定该生产者同次模型；恢复进程只挂载完整 CRD1 帧和冻结运行库。
  训练记模型和部署清单，训练诊断资产另列；留出帧只在推理路线计费，并包含帧内模型，不在训练路线重复记账。
- 两个生产者各完成 346 个拟合，各自 587 个 CRD1 帧均成功恢复。每个生产者 48 帧通过预声明的 train-only 门槛，539 帧超限，未重训或调参。
  每个适用文件—路线至少含一个超限帧，39 个终态均为 `quality_rejected`；不将模型生产成功或结构恢复成功等同于质量通过。
  不从两路通过/拒绝计数相同推断模型或恢复数值等价。17 项命名边界专项仍是 `not_run`；本次诊断不授阶段验收或计时资格。
- [独立审计](../../results/m3-real-r34-20261119/corad-audit.json)重算所有 cohort 的输入绑定、同次部署、精确质量与帧字段计费，确认 1,174 个帧合计 112,171,214 字节；
  对每个适用文件及生产者各抽取一帧，共 26 帧以仅挂 CRD1 和运行闭包的禁网进程重放。
  [审计负测](../../results/m3-real-r34-20261119/audit-negative-controls.json)拒绝伪改质量终态、交换模型部署、恢复挂入原输入、少计帧内模型以及篡改 Source 打包数组身份。

## CORAD 同账本语料与命名专项（r35 开发预检）

- [r35 封账](../../results/m3-real-r35-20261120/runs/877a4e8f1ebf4f95b245fe4c999532fc/completion.json)覆盖 69 个文件—路线决定（30 个域外），
  并将 20 个冻结用例映射到同次的原生推理、C11 训练、Source 训练 3 个专项产品；未复用 r34 账本条目。
- [独立审计](../../results/m3-real-r35-20261120/corad-audit.json)重算 1,174 个语料帧的完整字节成本，合计 112,171,214 B，禁网重放 26 份语料留样与 3 个专项产品。
  两个生产者各完成 346 个拟合、587 个恢复，各 48 帧通过与 539 帧超限，39 个语料终态均为 `quality_rejected`。
- 3 个专项产品均完成其功能验证，17 项命名义务中 16 项通过，`bound_predeclared_before_formal_run` 仍为 `quality_rejected`：
  两套模型的留出压力和相对湿度均超过预声明门槛。专项和语料均不授正式阶段或计时资格。

## ALP Auto 与解码后端的命名专项（r36/r37 开发预检）

- ALP 专项复用同一冻结构建的 C ABI worker、独立 ALN1 后端对照和直接舍入探针；锁定两个原生控制工具及其 ELF 闭包。
  15 个 ABI 产物与 9 个裸 ALN1 产物绑定 12 项必需、2 项条件，实际比较逐位恢复、边界和原生内核工作，不将 dispatch、已编译能力或性能混为一谈。
- [r36 封账](../../results/m3-real-r36-20261120/runs/2853cb7161c84f0b89e82f6ed5b25365/completion.json)中 46 个语料项通过，但 24 个专项产品均被执行器拒绝：
  首版计划错误使用 2 MiB 文件限额，高于当前隔离入口的 1 MiB 上限。保留原封账，不把这次失败解释为 ALP 原生实现失败。
  r37 纠正冻结限额，并在计划绑定阶段验证限额；没有采用 r36 的语料账本补齐 r37。
- [r37 同账本审计](../../results/m3-real-r37-20261120/alp-audit.json)核对 46 个语料决定全部 `verified`，并独立禁网重放全部 24 个专项产物。
  9 个裸 ALN1 产物的五种后端请求共 32 次逐位恢复、13 次预期不可用拒绝；两个混合位模式产物各复核两种异常侧信息拒绝。
  1,029 值真实尾块的原生舍入探针在 `FE_DOWNWARD` 下拒绝编码及解码且无输出，随后恢复原舍入模式。
  12 项必需全部通过；AVX2 条件对同一 f64 混合帧实际处理 1 个 decimal vector 并逐位恢复；AVX512BW 已编译、当前宿主不可用，
  保留 `pending_supported_runtime`，Auto 在本机实际选择 AVX2。未授予正式 M3 或计时资格。

## pcodec Auto/Pages 和 Zstd/XZ 批基线（r38 开发预检）

- [r38 冻结计划](../../results/m3-real-r38-20261120/plan.json)复用 Unique 的同构建共享库，并绑定已有原生直调控制及有界的 ABI/页用例。
  [按义务 ID 重算盘点](../../results/m3-real-r38-20261120/plan-driver-coverage.json)为 180 项必需、6 项条件全部有驱动，绑定不等于执行或资格。
- [r38 专项独立审计](../../results/m3-real-r38-20261120/batch-specialist-audit.json)在同一 run 的账本复核 34 项专项，并独立重放 42 个专项产品。
  pcodec 为 27 个有效产品、1 个预期终态（C-native f16 拒绝，Rust Source 接受）；Zstd/XZ 为 12 个有效产品、2 个 65,537 B 超限拒绝。
  页恢复依赖原生元数据，乱序恢复的每页按原值验证；输出分段 drain 不是在线输入流。Zstd 上游帧与 XZ 的 preset、线程、check 和字典上限分别验证。
- [r38 主账本复算](../../results/m3-real-r38-20261120/ledger-census.json)保留 138 个开发回验终态，但发现 ETTm1、ETTm2 的两条 pcodec Auto 路线
  各把 69,680 行整列交给 codec，未遵守冻结的 65,536 行/单元；4 个决定的精确数与原因单列，不计正式通过。
  [r37 账本复算](../../results/m3-real-r37-20261120/ledger-census.json)在两条 ALP 路线对同两文件也发现 4 个单元不符；
  ALP 语料的现有 `decode-backends` 为分别重编码、进程内回验，未证明从同一产物独立解码。ALP r37 的独立后端专项证据保持原结论。
  现有 Zstd/XZ 批语料回验也尚未替代分方向独立恢复和 M2 测量，以上不合并为正式全量。

## ALP、pcodec Auto、Zstd/XZ 的冻结单元与独立恢复（r39 开发预检）

- [r39 冻结计划](../../results/m3-real-r39-20261120/plan.json)只更新六条语料路线的执行绑定，保留 M0 定义、828 个文件—路线决定和 186 项义务不变。
  新驱动冻结原生 worker、插件和 ELF 依赖、启动器与文件/内存/超时限额。ALP/pcodec Auto 按每列 65,536 行，Zstd/XZ 按交错 V 的 65,536 字节调用；二者都严格提交尾块。
- 每个单位只编码一次。独立禁网进程仅挂载完整帧与冻结解码依赖，验证原值位模式和单位 schema；ALP 后端对照为同一帧分别启动 `scalar-unfused` 与 `falp-auto`。
  主账本记录精确范围、原值/schema/产物摘要、挂载清单、独立进程终态与实际后端。进程壁钟和资源仅供诊断，不是 M2 计时口径。
- ETTm1、ETTm2 原先不符的 8 个决定均有新的真实输入预检证据：每文件每路线 7 列、14 帧，每列分为 65,536 和 4,144 行。
  [ALP Auto](../../results/m3-real-r39-20261120/runs/d22d4e7b11cc4b2bbc94e6fc4a7ab836/report.json)、
  [ALP 共帧](../../results/m3-real-r39-20261120/ett-preflights/abc236b43ee1472582d824f7b49d2dcf/report.json)、
  [pcodec Source Auto](../../results/m3-real-r39-20261120/ett-preflights/06e0211765194b7f966e46bd2655f130/report.json)、
  [pcodec C Native Auto](../../results/m3-real-r39-20261120/ett-preflights/cf2f5c5b49184cb495427e16a82ea2b9/report.json)分别封账。
  ALP 的两种解码请求在上述两文件共用 28 个帧，`falp-auto` 均选择 AVX2，其中 3 帧的原生计数器记录到共 74 个 AVX2 向量；AVX512BW 的条件状态不因此改变。
- [Zstd](../../results/m3-real-r39-20261120/ett-preflights/87114a9580f34326b9ef4decb2a6870f/report.json)和
  [XZ](../../results/m3-real-r39-20261120/ett-preflights/bd0f560ed3084ca18f66a3f0f12989fd/report.json)各完成四个 ETT 文件逐帧独立恢复；
  ETTm1、ETTm2 每条路线每文件各 60 个单位，其中最后一块为 35,456 字节。
- 历史账本保持不变。r39 各定向运行独立复算，不拼成全量收据。定向结果证明运行时的逐帧恢复，不宣称释放的帧仍能复审；正式运行仍需冻结留样和重放策略，再按 M2 口径测量。

## 冻结批处理留样、独立重放与双入口构建（r40 开发预检）

- [r40 计划](../../results/m3-real-r40-20261120/plan.json)按每个真实文件—路线保留首块和首个不足上限的块（与首块重合时只保留一次），不按压缩比、耗时或后端表现挑样。对每个实际帧仍执行逐位验证。留样按完整帧 SHA-256 共用文件；账本逐项记录引用和释放的非留样帧逻辑字节，另由审计复算实体留样字节。非留样帧释放后不再可逐字节复审。
- [同次主账本](../../results/m3-real-r40-20261120/runs/730d9a2e201a45e4af16046681be1c24/report.json)经 `m3-real-corpus-run --dataset` 选定 ETTm1、ETTm2、Economics-17，覆盖六条路线，18 个文件—路线决定全部通过。指定数据集是显式定向预检，保留原分母且不执行命名专项，不能作为正式收据。
- [独立留样审计](../../results/m3-real-r40-20261120/retention-audit.json)校验封账、样本和 ELF 闭包。30 个留样引用对应 25 个实体帧（1,549,608 字节），328 个非留样帧验证后回收（17,665,712 字节）。用仅挂载完整帧及冻结解码器的禁网进程完成 35 次重放，ALP 共帧样本的两个后端分别重放。审计的重放范围只包括按策略保留的样本。
- `native/measurement/paired_batch` 是独立的计时 worker 构建入口，`TSBENCH_CODEC_BUILD` 指向本次功能闭包使用的 `build/m3-real-r8`，不覆盖原构建，不改变旧 CMake 控制及其锁。`build/m3-batch-timing-r2` 复用 M2 的 C++ 计时内核，为五个插件构建 `linked_entry`，另有通用的 `dlopen`。两个入口都仅加载经功能闭包 SHA-256 校验的插件及原生依赖。
- [双入口实测预检](../../results/m3-real-r40-20261120/timing-lane-probe.json)用原始冻结范围和 schema 重新取样，验证 30 个留样引用、35 个样本/后端组合在 `steady` / `cold` 与 `linked_entry` / `dlopen` 两组维度下的 140 次编码和解码调用；参考帧逐字节等于留样。预检只保留正确性和配置观察，不保留计时样本、不给排名或测量准入。

## 真实语料批处理匹配测量（诊断 r1）

- [测量计划](../../results/m3-fixed-batch-timing-r1-20261120/plan.json)只覆盖 r40 的三个真实文件、六条路线、30 个封存引用与 35 个样本/解码请求组合。每项冻结原始范围、原值与 schema 摘要、完整参考帧、ABI 模块和原生依赖、双入口程序及 r40 独立重放证据。各组合分 `steady`（reset 计入）和 `cold`（上下文构建/析构计入，不含进程启动），共 70 个比较组。
- 复用 M2 批内核：每个新进程预热 2 次；每组两个单次 pilot 给出共同有界循环数；按固定种子随机匹配 `linked_entry` / `dlopen` 三轮。每个循环的新编码产物均与参考帧逐字节相同，解码输出逐位核对原值和 schema。ALP 比较的是相同帧字节的解码后端；测量进程为每批重新生成这些字节，功能审计则独立用同一封存文件重放。输入加载、验证、释放不计入两个方向的原生钟；进程壁钟、CPU 时间和峰值 RSS 另列，是包含两个方向的子进程指标，不能当作某一方向的成本或来源文件端到端时间。内循环不计独立样本。
- 同一计划两次分别封账：[第一轮](../../results/m3-fixed-batch-timing-r1-20261120/runs/d25677a74f6142a3a91d3af43f877e20/report.json)、[第二轮](../../results/m3-fixed-batch-timing-r1-20261120/runs/ad5d8fa03c384241a2dbee086e11de21/report.json)。每次 560 批（140 校准、420 测量）全部核验，210 个完整匹配轮。复制只有封存计划、日志及账本的目录后可复算相同报告；修改记录中解码 CPU 端点并重新计算文件摘要，复算仍拒绝。完整帧计入 ABI header、schema 和实际 codec 载荷，吞吐分母仅用原域逻辑值字节。
- [复测审计](../../results/m3-fixed-batch-timing-r1-20261120/repeat-audit.json)不混合两次运行的样本；按生命周期、入口和方向，组间相对变化绝对值的中位数约 0.48%–1.59%，最大约 41.78%（ETTm1 的 pcodec C Native Auto 首块，steady/dlopen 解码）。核绑 CPU 4，串行执行并取得 TSBench 协作锁，但没有系统级独占或 NUMA 控制；已有观测不能因果归因，不设通过阈值，也不报算法排名。未覆盖其他合法工作负载、全语料、其他原生路线或 M4 剖析。

## 全量入口与账本指标明细

使用 `tsbench` 环境从工程的 `bmk m3-real-corpus-run --plan <冻结计划> --results <结果目录> --summary` 提交，
正式全分母候选不传路线、数据集或数量筛选。`--summary` 只减少终端输出，不改变执行或账本；完整报告仍写入 run。
不能从 `python -` / stdin 直接提交函数：CORAD 并行控制器使用 Python `spawn`，必须能重新加载主入口文件。
[启动尝试记录](../../results/m3-real-r40-20261120/launch-attempt-note.json)保留已中断、未封账的 stdin 尝试，
标准入口使用同一计划以新 run 独立执行，不继承或拼接中断账本。

`tools/m3_metric_details.py --plan <计划> --run <已封账运行> --out <新目录>` 按主账本逐条生成 `decisions.jsonl` 和
可复算 `summary.json`（不要求把整个账本和报告同时载入内存）。每行绑定源决定、配置、表示、账本行号，分别列出可核实的
逻辑字节、完整产物、原生操作或进程诊断钟、后端、CPU 和峰值 RSS；缺项附原因，不能从进程耗时反推缺失的裸 codec 时间，
首输出的 driver 事件也不当作完整编解码计时。每个块或列的观测分布不当作 M2 匹配重复；ALP 共用帧只计费一次，
多个解码后端分别记账。尚未归一的驱动及未通过结果仍保留主账本行引用，不补零、不混入已验功能吞吐。
输出为同一运行的诊断视图，不是分片收据、独立恢复审计、M2 计时准入或 M3 阶段通过。

### 指标适配器回算（开发检查）

[适配器覆盖检查](../../results/m3-metric-recomputations-20261120-r2/adapter-coverage.json)在 12 份封存定向账本上
分别生成详情和汇总；33 条路线有可复算字节或专项指标。另从老 r12 封存的报告检查 46 条 pcodec 页记录（两路线）；
该旧封印没有 `ledger_sha256`，不把它升格为账本证据。IntMult 在当前全量浮点语料为域外，整数用例仍由专项义务处理。
各目录绑定原 run、seal、计划与归一代码摘要，不能将重复路线或不同运行的记录相加作为全量完成数。

共享字典、Huff0 表按每个独立恢复变体只计一次，训练字节不进入留出压缩比；不同 worker 配置和 ZFP 模式分别记账。
PBEPLA 的逐层前缀费用不累加成一个帧，失败窗口不使用全覆盖压缩比；CORAD 每个生产者的模型/训练和留出帧费用分开，
质量拒绝仍保留其状态。Titchy 回调读字节不等同于文件 I/O；XZ/Zstd 首输出和 PBEPLA 首 sink 不等同于全程双向时间。
这些回算不新增 M2 匹配重复样本，未观测的钟或计数保持缺测。

### pcodec 原生页：代表性双向独立重复诊断

[诊断计划](../../results/m3-pcodec-page-timing-20261120-r2/plan.json) 绑定 r40 两条页路线与 r12 封存功能报告；两版的输入定义、页执行器、库、驱动及所选 work-item ID 一致。r12 缺主账本哈希，仅用其功能报告绑定各工作单元与参考帧，不当作新版全量证据。
固定 ETTm1 第 0 值列的整块 `[0,65536)`、尾块 `[65536,69680)` 和 Economics-17 第 0 值列的短块 `[0,193)`；每例、每路线、每方向两次预热、七轮匹配测量，按冻结种子交换路线次序，每次一个新隔离进程。编码逐次与本路线的固定帧逐字节比对，不假定两条路线的帧相同；解码只读挂载本路线的同一帧，恢复与规范 f64 位逐次比对。

[原始试验账本](../../results/m3-pcodec-page-timing-20261120-r2/runs/1f37a15db7684d1eaf32bffb6b6de352/trials.jsonl) 与 [可复算报告](../../results/m3-pcodec-page-timing-20261120-r2/runs/1f37a15db7684d1eaf32bffb6b6de352/report.json) 核对 108 次调用（24 次预热、84 次测量）。报告分别给出页载荷/元数据/组封装字节、压缩比、原生页操作与受监督进程两套时钟、CPU/RSS，以及不含预热的重复分布。进程时钟含隔离启动和工具的对象 I/O，不含源文件解析。CPU 3 亲和性由父进程设置并继承；没有在工具内采集线程数或 CPU 端点。取得 TSBench 计时协作锁，但 r40 全量功能作业当时尚未封账，不控制 SMT、NUMA、缓存或机器其他负荷。因此仅作诊断，不授予正式计时资格、性能排名或全语料覆盖。

使用 `tsbench` 环境运行 `tools/m3_pcodec_page_timing.py verify --run <诊断运行目录>`，从固化的计划、独立日志、产物及试验账本复算，不重跑 codec 或读取源语料。

### Zstd/XZ：原生整对象会话与 XZ worker 双向重复

[诊断计划](../../results/m3-lzbench-timing-20261120-r2/plan.json) 将 r40 的 `zstd-session`、`xz-session`、`xz-workers` 绑定到 r28/r30 的封存主账本、同一原生工具及同一规范 V 输入。前两条用 ETTh1 的完整交错 V 对象（975,520 B）；XZ worker 用 ETTm1 的完整 V 对象（3,902,080 B），编码比较显式调用线程、原生 MT API `threads=1` 和 `threads=2`。三个解码配置只读挂载同一份两 worker 帧，编码各自对照本路线的固定帧。每试验在禁网新进程中运行；CPU 12、13、14 是三个物理核心，由启动进程设置并继承，未逐线程测量 CPU 端点，也不声称系统独占。

[账本](../../results/m3-lzbench-timing-20261120-r2/runs/db8d59e2cd9a4dd9a2476f89cdc18f75/trials.jsonl) 与 [报告](../../results/m3-lzbench-timing-20261120-r2/runs/db8d59e2cd9a4dd9a2476f89cdc18f75/report.json) 记录 90 次验证（20 次预热、70 次测量）。XZ worker 每个方向分别实测 0/1/2 个后台 worker；设置某个线程数不视作实测，异步 job 总数按原样保留、不强制等于历史单次样本。完整压缩字节、进程墙钟、CPU、峰值 RSS 和适用的首次输出延迟分列；首次输出是含 span I/O 的驱动循环钟，不代替原生全操作钟。旧工具没有原生全操作钟，worker 工具亦没有首次输出钟，均明确记缺测。正式 M3 功能运行当时未封账，此处只作本机诊断，不作排名或资格；Zstd worker 路线也不在本次范围。

`tools/m3_lzbench_timing.py verify --run <诊断运行目录>` 从封存输入、参考帧、原始日志与试验账本复算。每次输出先核对字节、再释放，只留核对后的摘要；复算不声称重新恢复所有试验产物。

### Zstd worker 整对象重复与全量留样审计入口

[Weather 诊断计划](../../results/m3-zstd-worker-timing-20261120-r1/plan.json) 使用完整 8,852,928 B 交错 V，不截断输入以迁就通用隔离工具的 8 MiB 上限。仅对冻结 Zstd worker 工具允许较大的输入与输出，`RLIMIT_FSIZE` 仍按每次实际冻结输出预算设置；禁网子进程只挂载一个输入对象及锁定 ELF 闭包。两个编码配置分别验证自己的原生帧；每次解码各自挂载该路线同一份帧，实际解码均为 0 个后台 worker。编码分别观测到 0、2 个后台 worker；[报告](../../results/m3-zstd-worker-timing-20261120-r1/runs/69b21848c8794ab6a6590da7916c36d5/report.json)完成 36 次验证（8 预热、28 测量），只含进程墙钟/CPU/RSS，仍不补造旧工具没有的原生全操作钟。r40 运行当时活跃，不用于排名。[七个适用文件的计划](../../results/m3-zstd-worker-seven-files-20261120-r1/plan.json)在全量功能结束后另行运行：先前释放的大帧只允许在第一预热用未变更的输入及原生配置重建，摘要与原封存记录一致后方可作为固定解码帧，不能把新帧冒充旧留样。

`tools/verify_m3_corpus_custody.py` 从有主账本及报告哈希的单次封账复查 `retained/`、`fixed-batch-samples/` 的全部物理对象，禁止遗漏、额外文件、符号链接和冲突摘要；同一内容寻址对象只计一次物理占用。`--replay-pages` 在禁网进程复解两个原生页路线的固定首块，解码只挂载页帧，外层核对规范值。已在 [两个真实文件 × 两路线的 r40 定向运行](../../results/m3-corpus-custody-preflight-20261120-r1/pcodec-replay.json) 验证 4 个留样及 4 次复解。其他路线的专项产物和已释放的原生帧不由该留存清单证明。

封账后使用 `tools/audit_m3_full_run.py --plan <M3 冻结计划> --run <同一个完整运行> --out <新目录> --replay-pages`，检查全部决定与义务、逐项复算指标、核对物理留样及 pcodec 复解，输出互相绑定到同一个 run/plan/seal 的审计明细。不接受定向预检、不拼账本、不把失败、条件待验或覆盖结果改写为阶段通过。其他路线的样本重放及缺失计时仍按各自的合同补验。

## r40 完整原生语料：一次运行封账及审计（非阶段通过）

[r40 标准入口主账本](../../results/m3-real-r40-20261120/full-runs/26626570ffeb4ba79905b9eb7dd612ea/ledger.jsonl) 已封账；[全量审计](../../results/m3-real-r40-20261120/full-audit-20261120-r1/summary.json) 从同一个运行核对 828 个语料决定、186 项专项义务、200 个专项产物及 1 条实现回归记录。724 个适用项中，675 通过、CORAD 39 与 ZFP 6 项质量拒绝、PBEPLA-RR 两路线合计 4 项原生失败；其余 74 域外、30 未触发条件。必需义务为 179 通过、1 项 CORAD 留出质量拒绝；条件义务为 5 通过、1 项 ALP AVX512BW 缺宿主待验。专项产物中的 26 个预期拒绝与质量拒绝分开，不回写历史失败。

逐窗口核对上述 PBEPLA-RR 失败：两条路线在相同的 3 个输入窗口失败。`bitcoin-dataset-without-missing-values-1` 第 0 值列的 `[0, 2291)` 与 `[2291, 4581)`，以及 `bitcoin-dataset-without-missing-values-3` 第 0 值列的 `[0, 4021)`，均由原生控制程序报告 `RrGrid: no resolution up to 30 bits gives a block narrow enough`；同窗在两条路线中的输入 SHA-256 一致。此为原生编码报错，不是因输出未达到冻结质量门槛而拒绝。

将 r40 的窗口坐标、输入摘要及两条路线的失败原因对账到 [r25 单窗口复现](../../results/m3-real-r25-20261119/pbepla-rrgrid-counterexamples.json)，三窗全部一致。用该复现记录的首层网格跨度和 `2 × 16` 带宽复算，三个窗口所需**最低首层分辨率**依次为 **31、40、32 位**。经来源锁校验的 `tsbenchmark-algorithms-native` 归档中，`rr_grid.cpp` 的网格构造/自动选择及 `pbepla_rr.cpp` 的 PBEP 解码解析都限制为 30 位，因此仅改执行器配置、强制给出更大分辨率或只改编码器都不能保留 Unique v1 格式兼容性。保留原窗和 `[16, 4, 1]` 门槛下，这是当前选定实现的能力边界；另立兼容性不同的格式，或显式外部划分并计费，是不同的方法，不回填 r40。Unique 基准的按范围比例门槛也不是这次冻结的绝对误差档。

[指标明细](../../results/m3-real-r40-20261120/full-audit-20261120-r1/metrics.jsonl) 与 [留样清单](../../results/m3-real-r40-20261120/full-audit-20261120-r1/retained-corpus.json) 检查全部物理语料留样：1,105 份、65,284,562 B（内容寻址文件只计一次），两条 pcodec 页路线各 23 份首块均在只挂载页帧的禁网进程独立恢复。未声明其余 1,059 份留样已全部复解、未释放全部功能/计时门槛，也不将指标复算当作 M2 重复测量。

先行的 [Titchy 原生包流重复](../../results/m3-titchy-stream-timing-20261120-r1/runs/d33a945ce2ad4168a1b8e8daa900cc4e/report.json) 使用 ETTm1 和 Economics-17 的第一个完整值列；没有把列分块、批处理或通用外置缓冲冒充原生流。两例共独立验证 36 次调用；解码始终只读挂载同一 TSTR 归档与 TSC1 配置。内存驱动双向计时、首次输出、受监督进程墙钟与计费分别记录。进程时间包含原生工具自己执行的复位和背压验证，不与原生动作钟混排。该两例与 r40 功能运行重叠；另有冻结的 23 文件首列计划，明确不代表测量所有列或正式排名。

### 同封账固定批处理复解与串行重复诊断

`tools/verify_m3_fixed_batch.py --full-ledger --replay` 检查 r40 封印中的主账本和报告哈希，顺序扫描完整输入决定及义务，不在内存中加载明细报告，不从定向预检组装新运行。它复用原留样策略、恢复运行时闭包及逐位恢复断言。

[固定批处理复解审计](../../results/m3-real-r40-20261120/fixed-batch-retention-audit-20261120-r1.json) 覆盖六路线的 138 个文件—路线决定、170 个留样引用、145 个独立实体帧（4,306,700 B）。ALP `decode-backends` 的两后端读同一个编码帧；共用帧按实体只计一次，但逐引用、逐后端恢复，共 195 次相互独立的禁网调用，每次只挂载帧和冻结运行时。与原生页首块合计覆盖 191 个实体留样。这不包括其他 914 个留样、专项产物或已释放的帧。

功能全量与留样普查完成后，先执行 [Zstd worker 七文件报告](../../results/m3-zstd-worker-seven-files-20261120-r1/runs/b20d44735ed846318c626d46e35a591f/report.json)（252 次：56 预热、196 测量），再执行 [Titchy 23 文件报告](../../results/m3-titchy-stream-23files-20261120-r1/runs/04b2c018ad994df68c13d68057171549/report.json)（414 次：92 预热、322 测量）。两工具各以 `verify --run` 从各自封存账本复算一致。Zstd 的两编码配置使用完整 V 对象，各自的独立解码只挂载对应固定帧，旧工具仍缺原生全操作时钟；Titchy 的单位是每个文件的第一个完整值列，解码只挂载固定 TSTR 和 TSC1。串行不等于主机独占，这些结果不与先行样例合并成正式测量分布，不授予阶段或服务资格。

### 同封账 Titchy 四路线语料留样复解

`tools/verify_m3_titchy.py --full-ledger` 不加载全量明细报告，直接核对封印后顺序扫描主账本，检查整份语料与义务分母，并对 Titchy 四条语料路线复算首列/首块对应的源哈希、全文件行列范围和产物分项；原生 batch 与两种访问路线的底层 TCHY 帧逐块核对一致，原生包流仍单列。
[r40 Titchy 语料审计](../../results/m3-real-r40-20261120/titchy-corpus-replay-20261120-r1.json) 重放 23 × 4 = 92 份样本。batch/访问进程只挂载各自帧，包流进程只挂载 TSTR 和 TSC1；禁网进程的结果与独立解码器结果及规范输入摘要核对。92 个进程共读取 115 个实体留样，和固定批处理及 pcodec 页复解无重叠，将同一 r40 封印下的三份独立复解审计合计覆盖提高到 306/1,105 个实体留样（333 次调用）。此视图不复验 Titchy 专项产品，也不是全量帧再次解码或性能测量。

### pcodec 两条页路线：所有适用文件的第一完整值列

`tools/m3_pcodec_page_timing.py plan --all-files-first-column` 从同一 r40 封印和完整主账本冻结两条页路线共同适用的文件。仅投影第 0 值列，但覆盖其全部原生页组，不按速度或压缩比筛选；读取原件到 EOF 校验来源身份，不将这段准备成本计入原生耗时。23 个文件共 25 个组，其中 ETTm1、ETTm2 各有 `[65536,69680)` 的尾组。主账本中已释放的尾组产物只可在首预热以冻结配置重建，与各路线的原封存大小和 SHA-256 一致后，才可作为各自固定解码输入；重建不是历史留样。

[封存报告](../../results/m3-pcodec-page-first-columns-20261120-r1/runs/f1ffaaf6f9a846409d03b4cf2e035454/report.json) 的 **900 次**独立禁网调用已完成 `verify --run` 复算（200 预热、700 测量）。每组每路线两个方向各 7 个独立测量样本，解码只挂载该路线的固定帧。原生操作的墙钟/CPU、受监督进程墙钟/CPU/RSS、载荷/元数据/组头计费分列；进程钟包括隔离启动和控制程序文件 I/O，不是原始文件至最终产物的全链路计时。CPU 12 继承亲和而非系统级独占；本结果不代表所有值列、正式排名或阶段验收。

### r40 固定批处理：同 ABI 双入口重复覆盖全部冻结留样

[双入口预检](../../results/m3-fixed-batch-r40-samples-20261120-r1/lane-probe.json)与[测量计划](../../results/m3-fixed-batch-r40-samples-20261120-r1/plan.json)使用 `--full-ledger`，从 r40 同一封印投影 23 个文件的六条固定批处理路线，而不是以定向预检代替。170 个冻结单元引用按其实际解码后端展开为 195 个配置；逐项绑定已有 frame-only 独立复解的原值摘要、完整帧和后端。链接入口及 `dlopen` 入口必须先在相同 ABI、原生设置和生命周期下重现冻结帧，共验证 780 个入口预检记录。

[独立复算一致的封存报告](../../results/m3-fixed-batch-r40-samples-20261120-r1/runs/4df81a6f8c714389b8d66b3d5cb37452/report.json)记录 3,120 个通过的进程批次（780 校准、2,340 测量），390 组均完成三个匹配轮次。原生 encode/decode 分向取时，整批子进程资源另报；内循环不当作独立样本，录得的过程开销也不能当作文件 ingress 到最终产物的端到端开销。计时保留原有有界进程策略、单 CPU 亲和及协作锁，不声称禁网测量、系统级独占、全量帧重复或正式排名。独立禁网复解是另行绑定的功能证据。

### ALP 融合剖析同单元：原生双向与文件路径成本分开

`tools/m3_profile_alp_comparison.py` 绑定 r40 完整封印、M4 真实剖析封印及已核对的 ALP 同 ABI 两入口运行时。ETTm2 第 5 值列（从 0 起算）`[0,65536)` 不在原固定留样中；[重建记录](../../results/m3-alp-m4-exact-20261120-r1/anchor.json)从原始值和 schema 重新编码并逐摘要核对 r40 的完整帧，两个独立禁网解码分别核对 `scalar-unfused` 和实际 `falp-avx2`（51 个融合向量）。不改历史留样表或主账本。随后[原生双向报告](../../results/m3-alp-m4-exact-20261120-r1/runs/d8e060da99564a3ba2ffccfcae6ae5a7/report.json)的 32 个进程批次（8 校准、24 测量）全部通过并复算一致，解码时钟单列，内循环不计独立样本。

`tools/m3_alp_profile_pipeline_timing.py` 另行在 `falp-auto` 上测[文件路径诊断](../../results/m3-alp-m4-exact-20261120-r1/pipeline-runs/5a44ce1e0ed44a95a74d9fc4bedd16c3/report.json)。编码父进程的外层单调钟含读取和验证整个锁定源文件、f64 物化、选定列窗、独立编码、输出文件及其目录 `fsync`、独立 frame-only 复解及原值核验；解码外层钟从完整 BMK 帧起，含独立恢复、同摘要的数据与 schema 验证、文件和输出目录 `fsync`。解码进程不挂原件，临时试验目录清理及记录写入在外层钟之外。编码源文件物理读取规模 9,677,236 B 与逻辑任务值 524,288 B 分列；不会用文件大小计算数值吞吐。两个方向各 2 次预热及 7 次测量，共 18 个方向试验、27 个独立禁网进程，封账后复算一致。进程 CPU/RSS 单列，未观测的协调器与进程组全路径 CPU/RSS 写 `null` 并注明原因。此为单列窗文件路径诊断，且编码含独立复解验证，不与纯编码成本或其他边界混排；不替代全文件、全路线或正式排名。

### Sprintz-FIRE：冻结 SFB1 留样及 17 个整文件的编解码与查询重复

- [`m3_sprintz_query_timing.py`](../../tools/m3_sprintz_query_timing.py) 从 **r40 完整主账本**冻结查询路线，保持原有 SFB1 驱动、四条 little-endian `u16` limb、每列最多 8,192 行/帧和单原生线程。按每例、每操作一次预热和三次测量，方向随机次序预定；每次独立进程、CPU 6 亲和、TSBench 协作锁、Bubblewrap 禁网。编码逐帧对账完整 SFB1 摘要；解码只挂 SFB1，逐列逐块核验恢复位。准备阶段以恢复位或锁定源文件重建独立 COUNT/SUM/MAX oracle。原生 `upstream_simd` 与 `scalar` 分项记录，但同进程每帧先自动、后标量；不能用整段进程钟计算两种后端的独立查询性能，也不能把位片查询当成 f64 查询。
- [留样报告](../../results/m3-sprintz-query-repeats-20261120-r1/retained-runs/917d2fc9105948a1aa8240ff960b7088/report.json) 覆盖 23/23 文件各一份第 0 列首帧，276 次方向试验。 [整文件报告](../../results/m3-sprintz-query-repeats-20261120-r1/whole-bounded-runs/388d455603064417aeaabfc9ee455b44/report.json) 覆盖 17/23 文件的全部行、全部 V 列（340 个 SFB1 单元、19,267,376 B 逻辑值），共 204 次方向试验。LD2011–2014、Electricity、Traffic 的整文件产物超过隔离驱动的单文件限额，只有首帧诊断；后续应改用适配此规模的受限整文件运行，不能把首帧当成整文件。整文件归档为重建且逐帧对 r40，不增加历史留样数；这两次也不替代 `fire-batch` 公共 ABI 路线的独立重复。
- 原生 codec/查询调用、禁网进程和父进程从**已准备输入**发起到核验结果的壁钟分开。源文件读取、列物化、重建准备和产物持久化不在外层试验钟内。`wait4` 统计对应受监督的进程包装器及其执行路径，不是 codec 内部 CPU/RSS，也不证明系统级独占。两份报告独立重算一致，不签发阶段或性能准入。

### Huff0：FEC1 原生帧与 ETB1 共享表分开核算

- [封存报告](../../results/m3-huff0-corpus-repeats-20261120-r1/runs/b328886785c5461bb395d764468e7191/report.json) 对账 23 个文件的 **35 份 FEC1 首/尾实体留样**，及 16 个文件的 **32 个 ETB1 完整留出变体**（1X/4X 各自独立）。每份留样先做禁网独立恢复，另做各操作一次预热、三次测量。FEC1 只用 ABI 帧复解并对照原始摘要、schema 及块 CRC，按 ABI 头、schema、FEC1 头、记录头与各模式载荷计费；不将首/尾帧当作全文件。ETB1 从锁定原件独立读取训练前缀和留出值，禁网训练进程只挂载训练前缀，编码只挂载对应模型和留出值，解码只挂载模型和块流；SHA-256 sidecar 在进程外校验并随模型、块流完整计费一次，训练输入不计入留出压缩比。14 个没有历史完整留样的 ETB1 变体明列缺测。
- 共 **731** 次隔离调用（67 次额外复解、166 次预热、498 次测量），报告从试验账本独立重算一致。沿用 r40 的原生控制程序，其输出没有原生 wall clock，因此 `native_wall_ns` 为 `null`，不以子进程钟填充；只报告隔离进程及从已准备输入开始的监督和输出核验成本。没有测量原件到持久产物的全链路、无正式排名。
- 两条新诊断合计复核 r40 语料实体清单中 **154 份不重复文件**（Sprintz 23；FEC1 35；ETB1 32 × 模型、块流、sidecar 三件）。按物理路径、字节和摘要对账，和既有 pcodec 页、固定批处理、Titchy 审计不重叠：累计 **460 / 1,105**，还剩 645 份语料留样不在这些复解范围内。专项产物、全部时序帧及阶段正式验收另计。

### Sprintz 公共 ABI 与 Huff0 FEC1：23 文件全值域的双向原生重复

[测量计划](../../results/m3-abi-whole-corpus-20261120-r1/plan.json) 从 r40 同一主账本投影 `fire-batch` 和 `huff0-reference` 的 46 个已验证决定，绑定锁定原件、canonical 身份、每个原生单元的原值/schema/完整帧摘要，以及原 ABI 模块和库。单独构建 [`tsbench_abi_corpus`](../../native/measurement/abi_corpus)，不重编两种 codec、不修改历史驱动和封账。两个路线均覆盖全部 23 个文件的全行、全 V 列；本测量不是 TV，也不替代 Sprintz `query` 或 Huff0 `huff0-shared-table` 的操作成绩。

数据和帧序列按不跨原生单元的边界做有界传输（每组≤6 MiB）。整文件每方向每轮仍只启动一个禁网进程，每个原生单元构建单独的 ABI context；组切分只控制 I/O 和挂载，不改变帧、插件选项或成本，不计为独立样本或分组收据。不计入数据暂存用的长度字段；归档传输仅串接实际 ABI 帧。编码先从锁定原件重建，逐帧大小及摘要核对 r40 后固定为解码输入；每次编码逐组复现该归档，每次解码只挂该归档，恢复的值和 schema 逐组核对。另只挂原来保留的 23 份 Sprintz BMK 首帧独立复解，不把重建文件算作历史留样。

[试验主账本](../../results/m3-abi-whole-corpus-20261120-r1/runs/3fa247541278416292faa56a3de4da43/trials.jsonl) 与 [封存报告](../../results/m3-abi-whole-corpus-20261120-r1/runs/3fa247541278416292faa56a3de4da43/report.json) 经独立复算一致。共 437 次禁网调用：46 重建、23 历史留样复解、92 预热、276 测量。每文件每方向 3 个独立进程样本；每条路线的输入都是 622,954,272 B。Sprintz 的 11,610 个 ABI 帧合计 448,151,232 B，按 ABI 封装与内部 SFB1 分列；FEC1 的 9,519 个 ABI 帧合计 486,775,171 B，按 ABI 头、schema、FEC1 头、记录头与块载荷分列。本次实测 FEC1 解码全部选择 `runtime-bmi2`。仅按该路线计费，不合并成跨方法压缩排名。

CPU 6 亲和、协作锁和自然文件缓存；不声称系统独占。ABI 钟是串行单元中各公开 ABI 调用的墙钟和，含该调用内部封装、内存及算法操作，context create 单列；不把它称为纯算法内核时钟。受监督进程与 `wait4` CPU/RSS（非 codec 专属计数）另列；外层从准备好的输入开始，含启动及输出摘要，不含原件 ingress 和最终 `fsync`，不是耐久端到端时间。三个时钟不可混合或简单相减。本次未授正式计时或阶段资格。原有 Sprintz SFB1 查询对六个超限大文件尚缺整文件重复；ETB1 训练及共享表仍缺原生计时。

按 r40 同一物理清单校验路径、长度和摘要，这 23 份公共 ABI 首帧与此前 460 份互不重叠，累计 **483 / 1,105**，未覆盖 **622** 份。语料留样与专项产物分账，不改变 r40 的终态或出具阶段收据。

### Sprintz SFB1：23 文件全值域和耐久文件路径

[计划](../../results/m3-sprintz-durable-corpus-20261120-r1/plan.json)与[封存报告](../../results/m3-sprintz-durable-corpus-20261120-r1/runs/80ce0d15d38f4e429d7713fc1b6d4181/report.json)绑定 r40 的 `query` 路线、每帧摘要和原 Unique Sprintz DSO。新驱动对同一个完整文件仍只建一个 native codec context，每列仍按 8,192 行/帧访问；只是按完整列边界，把原顺序 SFB1 字节写入多个有界文件（每个≤6 MiB）。不增加归档头、不切原生帧、不按文件分组计算独立样本。新增证据包括此前隔离限制下缺整文件重复的 LD2011–2014、Electricity、Traffic；r40 的全部 23 个文件、11,610 个 SFB1 单元均覆盖，逻辑 622,954,272 B、完整产物 446,781,266 B。重建归档逐帧核对 r40，不增加历史留样数。

每文件每操作 1 次预热、3 次测量，276 次独立禁网进程试验（207 次测量），一份账本，复算结果一致。编码外层从锁定原件读取、校验与列物化开始，到逐帧核验、输出文件和目录 `fsync` 为止；解码外层从挂载已核验的完整 SFB1 归档开始，到原域位校验、列文件及目录 `fsync` 为止。完整源文件字节数与原任务逻辑 V 字节分列。原生、受监督进程、端到端时钟各自报告；端到端不含未计时参考重建和试验目录清理，`fsync` 不被描述成已通过崩溃恢复。查询还是四路 `u16` 的 COUNT/SUM/MAX，所有帧均对独立原位 oracle；同进程每帧顺序跑 SIMD、标量，报告两路 native latency、共同顺序扫描的 SFB1 字节，物理读量不填零。进程资源是 `wait4` 路径口径；无协调器／整路径 CPU/RSS，无系统独占或排名资格。

### Huff0 ETB1：全部 46 个留出变体的原生训练、建表与双向计时

[计划](../../results/m3-huff0-etb1-timing-20261120-r1/plan.json)与[封存报告](../../results/m3-huff0-etb1-timing-20261120-r1/runs/47264af273894c98abdbb04e092b79a6/report.json)从 r40 对账 23 个文件 × 1X/4X 的 **46 个完整留出变体**，包括之前释放完整产物的 14 个变体。独立构建计量驱动、链接冻结 `libreference.so`，保留旧功能驱动。每个训练进程只读已冻结训练前缀；编码只读对应模型与留出值，解码只读模型与绑定的块序列。训练/留出原值摘要、模型摘要、块序及逐块摘要均对 r40。I/O 分组不改变块划分、全变体单表复用或计费；完整计费为模型、块头、载荷与 binding sidecar，训练前缀不计入留出压缩比。每个配置覆盖 124,595,936 B 留出值；重建资产不增加历史留样数。

共 552 次隔离试验（138 预热、414 测量），报告独立复算一致。训练计原生 `TableCodec` 构建；编码、解码分别计一次原生表加载与全块调用之和，两者分列。另报受监督进程资源及从准备好输入到核验、输出 `fsync` 的壁钟。原件解析与训练/留出切分仍在 ETB1 计时外，模型、块、binding 尚未作为一个耐久交付事务端到端计时。无正式性能／阶段准入。

### SElf*：r40 历史首列及专项重新验证

[独立复解审计](../../results/m3-real-r40-20261120/selfstar-full-ledger-replay-20261120-r1.json) 从完整封账投影 `selfstar-batch` 和 `selfstar-incremental`，对 23 个原件重新读取完整范围、计算第 0 值列原域摘要；每条路线各 23 份历史首列帧，以该路线的禁网恢复入口只挂载帧，核对逐位恢复、schema 和完整帧记账。不是把新编码文件当成留样。另重放 25 个专项终态（18 通过、7 预期拒绝），对账 9 项必需义务。按物理路径、长度、摘要和既有审计查重，r40 的实体留样复核累计 **529 / 1,105**，仍有 **576** 份未被这些审计覆盖；专项不进入此分母。这是历史留样与专项的独立审计，不是新增双向计时、阶段验收或性能准入。

### Huff0 ETB1：原件到耐久模型与留出块，以及独立耐久恢复

[计划](../../results/m3-etb1-durable-corpus-20261120-r1/plan.json)与[封存报告](../../results/m3-etb1-durable-corpus-20261120-r1/runs/a06b2a4bfebd42c3a41df828da20167b/report.json)绑定上述 ETB1 原生诊断与 r40。23 个文件 × 1X/4X 全部通过：每变体每方向 1 次预热、3 次测量，总计 **368 次端到端试验**（276 次测量），内含 **552 次**独立禁网子进程调用（不计参考制备）。`tools/m3_etb1_pipeline_timing.py verify --run` 从封印、账本和固定参考摘要复算，与已写报告一致。

编码总钟从完整锁定原件开始，含源解析、互斥训练/留出切分、训练、留出编块、摘要及绑定校验；在模型、全部块文件和 sidecar 逐文件 `fsync`、发布目录 `rename`、父目录 `fsync` 后结束。解码总钟从同一个已验证固定参考开始，校验模型/块绑定；禁网解码进程只挂载模型与块，不挂载 sidecar、源或参考值；外层验证恢复的规范留出值并以同样的耐久目录协议发布。不计参考重建和试验目录清理；耐久协议不代表已经做过断电/崩溃恢复。每配置原始留出为 124,595,936 B；完整计费 1X 为 98,488,904 B，4X 为 98,518,227 B（模型、块头、载荷、绑定字节）。重建参考不计入历史实体复解覆盖。

CPU 6 亲和与协作锁不是系统独占。分列整个路径、子阶段、原生调用和子进程 `wait4` 资源；无协调器或进程树总 CPU/RSS。不能和准备好输入后的 ETB1 原生计时混为同一边界，不授正式排名或阶段资格。

### SElf*：两条原生路线的 23 文件全值域双向重复

[计划](../../results/m3-selfstar-timing-20261120-r1/plan.json)和[封存报告](../../results/m3-selfstar-timing-20261120-r1/runs/2344b4b666b64af68af7965fbdabaf24/report.json) 从 r40 冻结 23 个文件 × `selfstar-batch`／`selfstar-incremental`，无排除。复用锁定的 C 标量 SElf* 构建；仅在逐列确认两路线原值、schema、帧和几何等事实一致（生命周期分列）后，共用一个定值参考归档。每值列使用独立 context，每文件每路线每方向每轮使用独立禁网进程；解码只挂帧。两路线各覆盖 622,954,272 B 规范值、153,720 个原生块和 303,949,657 B 完整帧。编码产物、解码规范值和 schema 均逐次核对锁定摘要。每方向一次预热、三次测量，共 **368 次**（276 次测量，不含参考制备）；`verify --run` 独立复算与报告一致。参考重建不算 r40 历史留样复解。

批量计时覆盖内存输入上的公开 ABI encode/decode 调用；增量计时覆盖有序 begin/add/finish 或 finalized-read 的控制循环及内存封装，包含调度成本，并非纯 C 调用总和。两者都分列 context 创建、方向调用、受监督进程墙钟／`wait4` 和从已准备输入发起到摘要核验的外层钟；不含原件解析、最终 `fsync`，也不据此计算两路线的同边界原生速度差。CPU 6 亲和并非主机独占；本次不授正式计时、排名或阶段资格。

### r40 历史留样：ZFP 和 PBEPLA-RR 独立复解

- [ZFP 审计](../../results/m3-real-r40-20261120/zfp-full-ledger-replay-20261120-r1.json)复用既有校验器，从同一封账重读 23 个原件和 92 个文件—路线决定，核对 field/array 的全工作域与字节账，再用新进程复解/重开历史选样；核验 **299 份**实体帧及元数据。定率数组仍有 6 个文件级质量拒绝（26 个窗口），按原门槛复算，不改判。另在禁网专项入口复核 20 项义务、20 个终态（17 通过、3 预期拒绝）。OpenMP 的语料配置与专项实测 worker 证据分开。
- [PBEPLA-RR 审计](../../results/m3-real-r40-20261120/pbepla-full-ledger-replay-20261120-r1.json)重读两路线的规范源窗口，核对逐层计费、批与 replay 同窗产物与恢复状态。42 份历史选样各独立复解 3 个前缀，核验 **126 份**实体留样；相同 3 个 Bitcoin 源窗口在两路线均保留原生失败。另在禁网专项入口复核 9 项义务、13 个终态（11 通过、2 预期拒绝）。
- 两项语料复解使用新控制进程，仅传入相关帧/前缀及必要参数，**不将它描述为通过禁网隔离资格**；专项复解单独用锁定的禁网闭包。[累计对账](../../results/m3-real-r40-20261120/retained-replay-coverage-20261120-r1.json)以同一 r40 封印和原实体清单按路径、字节与摘要查重：**954 / 1,105** 份历史实体已复核，**151** 份待复核。未把专项、新重建参考或同一实体的重复引用计入分母，不改变原阶段终态。

### r40 历史留样：原版 C11 Gorilla TV 与状态修复路线

[Gorilla 审计](../../results/m3-real-r40-20261120/gorilla-full-ledger-replay-20261120-r1.json)绑定原 Unique C11 的 TV 批量实现；append/resume 与 iterator 仍绑定同一 C11 来源的已登记状态修复构建，不改换为 C++ codec。23 个源上三条路线共 69 个决定：每条 16 个合法文件、7 个因非秒坐标域外，三路最终帧与恢复摘要对账。独立 XORChunk 解析器复解第 0 值列首块的 48 份历史帧和 16 份前缀快照，将恢复的时间与 f64 位和从原件重新读取的首块逐字节比较；另复核 12 项禁网专项义务及独立修复回归的帧。此结果不替代派生 T/V、整语料重新解码或重复计时。[更新后累计对账](../../results/m3-real-r40-20261120/retained-replay-coverage-20261120-r2.json)：**1,018 / 1,105** 份历史实体已复核，剩 **87** 份；按同一清单对路径、字节和摘要查重，专项不计入分母。

### r40 历史留样：Zstd/XZ 独立复解与语料留样对账闭合

[Zstd/XZ 全账本审计](../../results/m3-real-r40-20261120/lzbench-full-ledger-replay-20261120-r1.json)直接读取同一封印主账本，复用既有独立复解入口，核对 5 条路线 × 23 个输入的 **115** 个决定。`zstd-session`、`xz-session` 与 `zstd-dictionary` 各 23 通过；worker 路线为 Zstd 7 通过、16 未触发，XZ 9 通过、14 未触发。分别复解 30 份会话留样、11 份 worker 帧、23 组 Zstd 帧与字典（独立复跑缺字典／错误字典拒绝），合计 **87** 份实体。语料历史帧用新的本地 native 解码进程；5 个专项产物另用禁网闭包重放，覆盖 23 项义务。未将未保留的大帧重新编码后冒充留样。

[累计对账 r3](../../results/m3-real-r40-20261120/retained-replay-coverage-20261120-r3.json)核对同一清单的路径、长度、摘要和按实体去重，**1,105 / 1,105** 份历史语料实体全部有独立复核；可用 `tools/verify_m3_retained_replay_coverage.py` 复算。分母不含已释放帧、重建参考和专项资产；这不是 M3 的逐路线双向正式计时、未通过义务或阶段验收的替代证据。

### 同入口更换输入：首批 12 项补充机制复验

[输入清单](../../datasets/manifests/m3-input-switch-synthetic-v1.json)、[补充执行计划](../../results/m3-input-switch-20261120-r1/plan.json)、[封存运行](../../results/m3-input-switch-20261120-r1/runs/620c38a0386c4eb2aa6307a3e414c438/report.json)和[独立对账](../../results/m3-input-switch-20261120-r1/audit.json)验证更换清单不需要修改原生执行器或 codec。样本由固定生成器产生，是新的合成 civil-second 三值列输入，共 4,099 行；并非新增真实来源或原件抽样，不能加到 23 个真实原件的分母。三段 `[0,2048)`、`[2048,3072)`、`[3072,4099)` 不重叠；CORAD 和字典/共享表路线仍用各自冻结的训练与留出规则。计划检查与基准 23 原件和已锁定旧语料清单的身份冲突（ID、来源簇、源字节以及可用的规范值/对象摘要），不靠重命名产生新输入。

标准执行器用同一个 `bmk m3-real-corpus-run`，不另建 codec 入口；Python 对应 `tsbench.api.plan_m3_input_switch` 和原 `run_m3_real_corpus`。补充计划绑定 r40 已检查的前置收据、构建、原生路由和配置，不改 M0 的首批原件合同，不重跑或重签 186 项专项。36 个决定为 **33 适用且通过、1 域外**（pcodec IntMult 不能把 f64 当无符号整数）、**2 未触发条件**（Zstd/XZ worker，输入不够大，不补零）。12 项选型各有实际执行和验证通过证据；两个 CORAD 训练器与同次留出均按原门槛通过，**不改判 r40 真实输入拒绝**。对账复算身份、主账本全人口及留样字节摘要，不是另一次独立解码或 §8 的正式计时。

```sh
# 进入 tsbench；以下写入位置必须为新文件/新运行，禁止覆盖上述证据。
python bmk native-corpus-plan --manifest datasets/manifests/m3-input-switch-synthetic-v1.json --out results/<new>/definition.json
python bmk m3-real-corpus-plan --switch-from results/m3-real-r40-20261120/plan.json --native-definition results/<new>/definition.json --out results/<new>/plan.json
python bmk m3-real-corpus-run --plan results/<new>/plan.json --results results/<new>/runs --summary
python tools/verify_m3_input_switch.py --plan results/<new>/plan.json --run results/<new>/runs/<run_id> --out results/<new>/audit.json
```

### Zstd/XZ 的整语料原生调用时钟（独立观测）

[冻结计划](../../results/m3-lzbench-corpus-clock-20261120-r1/plan.json)直接从 r40 全量封存账本投影：`zstd-session` 23、`xz-session` 23、`zstd-workers` 7、`xz-workers` 9，共 **62 个适用决定**；另外保留 Zstd 16、XZ 14 个未触发决定。独立构建 `native/measurement/lzbench_corpus`，历史控制程序、r40 计划与账本不变。两个时钟工具链接同一锁定的 `liblzbench_native.so`；XZ 同步解码入口与原控制一样，使用该构建的 vendored `libln_kernels.a` 中的 `lzma_stream_decoder`（共享库本身不导出此符号）。冻结 ELF 闭包、静态链接输入、头文件及源代码摘要。

- 会话方向使用 307/521 B 游标及全对象单一原生会话。Worker 编解码保留原读写 span，Zstd 两编码配置各自对应独立的零 worker 解码，XZ 三个解码 lane 比较同一 lane-2 帧。历史已释放帧在预热和测量之外重建，验证与 r40 已封存字节数和摘要一致；在测量中固定帧不变。
- 原生计时分为初始化、推进、封装、释放四个不重叠的调用墙钟区间之和。同步 XZ 编码包含 Block、fallback、Stream header/footer 和 Index 等原生调用，不仅是 `lzma_code`。并行等待可能包含在调用墙钟中，不能换算为多线程 CPU 时间。驱动第一输出对同步 XZ 编码是 12 B Stream header，不等于首次有效载荷。
- 单列驱动墙钟、`wait4` 进程墙钟/CPU/RSS，以及从已经落盘的规范输入或固定帧，经隔离启动到输出文件及父目录 `fsync` 的路径墙钟。最后一条**不包含从最初 CSV/TXT 的解析，也不替代全管线计时**。每次检验相同配置、worker hook 的实际工作、输入挂载摘要和结果字节；输出逐字节核对后回收，保存固定帧、原始日志与账本。
- 同一 UID 的协作资源锁，绑定两个不同物理核；不宣称系统级独占或冷缓存。每个 lane 预热一次、测量三次；不授予 M3/M4 阶段或排名资格。

```sh
# 在 tsbench 中；以下为一份全量诊断，不要按文件拆提交。
cmake -S native/measurement/lzbench_corpus -B build/m3-lzbench-corpus-clock-v1 \
  -DCMAKE_BUILD_TYPE=Release -DTSBENCH_FROZEN_LZBENCH="$PWD/build/m3-real-r8/plugins/codecs/zstd"
cmake --build build/m3-lzbench-corpus-clock-v1
python tools/m3_lzbench_corpus_clock.py plan --source-plan results/m3-real-r40-20261120/plan.json \
  --source-run results/m3-real-r40-20261120/full-runs/26626570ffeb4ba79905b9eb7dd612ea \
  --build build/m3-lzbench-corpus-clock-v1 --cpu 12 --cpu 13 --out results/<new>/plan.json
python tools/m3_lzbench_corpus_clock.py run --plan results/<new>/plan.json --runs results/<new>/runs
python tools/m3_lzbench_corpus_clock.py verify --run results/<new>/runs/<run_id>
```

原生计时首轮 r1 在 297 次已逐字节核对的试验后停止，未封账：ETTh1 的 XZ 会话解码实际 1 个后台 worker，但 hook 调用 81 次，历史功能运行 91 次。冻结 vendored 解码器的 hook 位于工作线程的分段 Block 解码调用前，而非每 Block 只触发一次；线程唤醒及到达 span 可改变次数。因而 [r2 独立全量计划](../../results/m3-lzbench-corpus-clock-20261120-r2/plan.json)继续严格匹配配置、后台线程数、caller hook、帧和恢复字节，仅将 XZ MT 解码的实际 hook 次数作为重复分布观察，而非强制等于历史一次运行。r2 不复用 r1 的中间试验或把其当成通过证据；每个规范 V 对象只解析一次，进程与输出同步诊断仍逐试验测量。

### 同入口更换 NOAA/USCRN 独立真实输入

[上游原件与派生血缘锁](../../datasets/raw/m3-uscrn-tucson-v1/lineage.json)与[公开格式说明快照](../../datasets/raw/m3-uscrn-tucson-v1/hourly02-README.txt)一起固定 NOAA NCEI USCRN Tucson 11 W（WBAN 53131）2020 年逐小时观测。该来源不是上述 23 个文件或旧候选中的重封装来源。保留 8,784 行原件；小时均温原件在 0-based 第 6,916 行有缺测标记，入库转换按**与 codec 无关**的规则选最长连续完整窗口 `[0,6916)`，不跨缺测拼接、不补值、不重采样。只保留三个原生温度列 `T_HR_AVG`、`T_MAX`、`T_MIN`，不冒充全年度、全列数据。采用原件 LST 小时结束坐标，保留 civil 时钟语义，不将其重解释成 UTC；原件 LST 与 UTC 的固定偏移另作来源校验。

[真实输入清单](../../datasets/manifests/m3-input-switch-noaa-uscrn-tucson-v1.json)按 `[0,3072)`、`[3072,4608)`、`[4608,6916)` 冻结训练、开发和留出；`datasets/generators/prepare_m3_uscrn_tucson_v1.py --verify` 从锁定原件独立复算投影、行数、列、规范摘要和各分区摘要。[补充计划](../../results/m3-input-switch-noaa-uscrn-20261120-r1/plan.json)复用上一节所用的同一公共入口与 r40 构建。结果覆盖只适用于此投影，不改 r40 原件分母、原始质量终态或专项义务。

[禁网运行账本](../../results/m3-input-switch-noaa-uscrn-20261120-r1/isolated-runs/9a43863f741a4ca49e2709e345027ea5/ledger.jsonl)及[对账](../../results/m3-input-switch-noaa-uscrn-20261120-r1/audit.json)确认 36 个决定：**31 通过、2 质量拒绝、1 域外、2 未触发**；12/12 选型均有原生运行与校验证据，11/12 至少一条路线通过，核对 59 份实体留样。PBEPLA-RR 渐进与 replay 使用相同冻结窗，值列 1 的 `[0,3458)` 第一层实际误差为 `9007199254740993/562949953421312`，略高于阈值 16；浮点显示虽为 `16.0`，精确判据仍为拒绝。保留较早的 [外层沙箱不支持网络命名空间的运行](../../results/m3-input-switch-noaa-uscrn-20261120-r1/runs/5c3e82a67d9b436f9b08029a7751a67e/report.json)，不将两次运行拼接或将环境失败当成 codec 失败。

### Zstd/XZ 原件到已验证耐久产物的路径

新增 `tools/m3_lzbench_durable.py`，仅从**已封账且复算通过**的整对象原生计时运行派生计划，严格复用其 62 个适用决定、30 个未触发决定、固定帧、lane 和重复计划。计时每次编码重新打开并读完冻结 CSV/TXT 原件，含解析、规范化、物化 V 和同规范摘要核对，不把其他运行的原生时间与 ingress 拼接。编解码完成均要求实际文件与运行目录内父目录 `fsync`，以及产物的 frame/原始域验证；随后写入统一账本才回收临时产物。这不是断电或崩溃恢复证明。

解码 workers 只挂载一个相应固定帧；XZ worker 三 lane 读相同 lane-2 帧，Zstd worker 各自读本 lane 的帧。输出是原始域交错 f64 V，而非重新生成上游文本，也没有把 T 当作本路线的恢复产物。记录阶段墙钟和单段验证后完成墙钟；控制器 CPU 和隔离子进程的 `wait4` CPU/RSS 分离，不推算本次路径的全局峰值 RSS。输入和产物字节、输出同步与校验均从原始试验记录复算，不将缓存命中或主机级独占视为已测。`tests/isolation/lzbench_durable_original.py` 在 ETTh1 上跑过真实源进入和只挂载固定帧的 Zstd 会话双向隔离检查；这是功能检查，不替代全量耐久计时。

```sh
# 在 tsbench 中；native_run 必须已有 completion.json 且能独立复算。
python tools/m3_lzbench_durable.py plan --native-run "$native_run" --out "$new/plan.json"
python tools/m3_lzbench_durable.py run --plan "$new/plan.json" --runs "$new/runs"
python tools/m3_lzbench_durable.py verify --run "$new/runs/<run_id>"
```

[整对象原生时钟 r2 报告](../../results/m3-lzbench-corpus-clock-20261120-r2/runs/e024fe67fcbd4436b3451dc1809dad38/report.json)已封账并独立复算一致：**696 次已验证方向试验**（174 预热、522 计时采样），对应 62 个适用文件—路线决定，并保留 30 个未触发决定。46 个已释放帧引用在观测前恢复到 r40 冻结的完整帧摘要；未作为历史留样计数。完整运行沿用各路线原生 span、worker 及解码锚点，报告仍只作为独立诊断，不改写 r40。

[全量耐久试验计划](../../results/m3-lzbench-durable-20261120-r1/plan.json)已由上述封存测量派生，并在 M4 多尺度计时退出后启动；完整耐久计时的报告以该运行最终封账及独立复算为准，不能拿 r2 的规范文件时钟替代。

### Gorilla C11：全文件固定帧重复诊断（r2）

[r2 冻结计划](../../results/m3-gorilla-corpus-clock-20261120-r2/plan.json)从 r40 封存账本逐行投影 Gorilla 的 **69** 个决定（每路线 16 个适用、7 个域外），不加载详细总报告。每条适用路线共有 **153,713** 个列块，按原账本每 512 行分块；不因隔离上限而截断大文件。`tv-batch` 的隔离闭包只绑定 Unique C11 原版，`append-resume` 和 `iterator` 绑定同源状态修复版；两份同名 `libgorilla_c.so` 不同挂载。C++ 文件是调用 C11 的控制器，不是替代算法。

每个文件—路线一次固定帧/必要快照的重建及逐块对账，再做 1 次预热和 3 次测量。每次编码重新读取完整锁定 CSV/TXT 原件、追踪到同一规范 TV，编码产物匹配固定帧和快照摘要；状态进度逐块核对 r40。每次解码只挂载其固定 GTV1，校验完整恢复位模式或快照位模式，迭代独立校验每块 seek。该工具专用的 128 MiB 上限是**单文件**上限，不放宽通用执行器。

- 原生钟分别记录批量双向、状态五段和独立快照复解、迭代创建/遍历/seek；不把历史控制器未计的 encoder 创建/释放、reset 和内部批量字节对照算入原生调用钟。监督进程另列墙钟及 `wait4` CPU/RSS。
- 落盘钟从准备好的输入开始；验证后落盘总钟则在编码方向从读取原件前起步，在解码方向从准备挂载固定帧前起步，截止产物及目录 `fsync` 与语义校验完成。不把验证后的产物回收计入，也不声称断电恢复。无冷缓存、系统级独占或正式性能资格主张。
- 字节账本用一次共享 T 和全部 V 记逻辑分母，把 native 的逐列 TV 输入另列；计费完整 GTV1，状态快照单列且记录实际总写入量。迭代 seek 与扫描开销分列，不把整段带查询的路径称作纯扫描。

[r1](../../results/m3-gorilla-corpus-clock-20261120-r1/plan.json)未启动，只计规范输入开始的路径；r2 不复用其试验或改写旧计划。ETTh1 三路线文件隔离冒烟使用同一执行与校验函数，不签发阶段证据。

```sh
# 在 tsbench 中；先让仍占有协作资源锁的现有计时运行结束。
python tests/isolation/gorilla_corpus_clock_smoke.py results/m3-gorilla-corpus-clock-20261120-r2/plan.json
python tools/m3_gorilla_corpus_clock.py run \
  --plan results/m3-gorilla-corpus-clock-20261120-r2/plan.json \
  --runs results/m3-gorilla-corpus-clock-20261120-r2/runs
python tools/m3_gorilla_corpus_clock.py verify --run results/m3-gorilla-corpus-clock-20261120-r2/runs/<run_id>
```

### r40 的计量证据覆盖清单（不是验收收据）

[`audit_m3_measurement_inventory.py`](../../tools/audit_m3_measurement_inventory.py) 将各诊断原始试验重新复算，再按 r40 的计划/封印、工作项、有效配置及输入实际范围登记链接。[清单 r1](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r1.json) 保留全部 **828** 个决定及原有终态、未通过义务，引用 **7** 个已封账诊断；不将这些诊断合并为新的 M3 主运行。以同样的 `--plan`、`--run` 和 `--evidence MODE RUN` 参数加 `--verify` 可复算清单。每种模式至多一个已封账诊断；清单中的 seal 路径的父目录是对应 `RUN`。

675 个功能已验证决定中，当前清单链接了 **220 个完整冻结范围**及 **164 个投影/留样范围**的原生重复证据；验证后耐久总钟有 **46 个完整冻结范围**。`not_inventoried` 仅表示本次清单未链接，不是「未测」。例如 pcodec first-column 的 46 个决定中，20 个确实覆盖了原计划的全部值列，26 个仍是列投影；固定批路线的留样证据不升格为全范围。Titchy 的已封账 first-column 诊断使用 r22 功能封印，不在这份严格 r40 清单中；要链接需单独对账输入、帧、构建、配置与范围，不能只凭相同文件名或 r40 主计划引用。冻结但未封账的 Gorilla 等运行也不作为覆盖证据。没有授予阶段或正式计时资格。

[覆盖清单 r2](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r2.json) 通过严格对账补登记 Titchy 的旧诊断。诊断的 414 次方向试验仍绑定原 **r22** 封印；对 23 个文件，逐项确认 r22/r40 工作项、构建、隔离 ELF 闭包、列和行范围、恢复位摘要、TSTR/TSC1 两个实体、原生调用观测和计费完全匹配（时钟不作跨功能运行的恒等约束）。r2 单列跨封印桥接及各列的事实摘要，不改写两个历史账本。10 个单值列文件确为完整范围，13 个多值列文件仍为首列投影，未测列不获覆盖。清单合计 **230 个完整范围、177 个投影/留样范围**的原生重复证据；耐久完整范围仍为 46 个。阶段和正式计时资格不变。

[Zstd/XZ 耐久报告](../../results/m3-lzbench-durable-20261120-r1/runs/c249cc83f14141e3928cbb35f2a41f03/report.json)已由同一运行封账并独立复算。62 个适用决定内有 696 次方向试验（174 预热、522 测量）；另有 30 个条件未触发决定。编码方向从锁定原件开始，解码从同一固定帧开始；验证、产物文件和目录同步都在该耐久边界内。新增至[覆盖清单 r3](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r3.json)后，完整冻结范围的耐久计时由 46 增至 **108**，原生完整/投影计数仍为 230/177（不因两次证据覆盖同一原生决定而加倍）。

Gorilla r2 在 Zstd/XZ 封账并复算、M4 r4 复测退出后，用 Bubblewrap 文件隔离完成 ETTh1 三路线冒烟：每条 245 列块，合计 7 个验证后的方向端点（包括独立快照复解）。外层沙箱中的首次 `sandbox_failed` 是命名空间启动失败，不记作算法失败，不把失败那次拼入冒烟。在允许内层隔离后，[全量运行](../../results/m3-gorilla-corpus-clock-20261120-r2/runs/3ec8705f65ae41a8b1f4cd9204f140bf/trials.jsonl)已以 r2 开始；须封账和独立复算后才扩大覆盖数字。

### pcodec 页：全值列计量驱动的分组 I/O 功能预检

新增 `native/measurement/pcodec_pages_grouped/`：在新构建目录内对冻结 r40 控制器的 I/O seam 应用 overlay，使用原 `libpcodec_c.so`。旧源文件和冻结控制程序不改。PGF1 只为隔离与测量把原文件的各列页组按顺序封装；不改变原 65,536 行/组、4,096 行/页、每组原生状态和 `PM3PAGE1` 产物，也不把不同页组当独立重复。该驱动可用一个进程完成一个文件—路线—方向，避免为每页组反复启动工具。

`tests/integration/pcodec_pages_grouped.py` 用**两列、65,537 行**的功能 fixture 对照旧 Source 与 Native 控制器，分别核对每组帧字节、原生观测语义、完整恢复位以及短输入和尾随输入拒绝。从锁定闭包直接加载，不是 Bubblewrap 或正式计时。全量计划须覆盖 r40 的 **23 文件、每路线 2,751 组和 622,954,272 逻辑值字节**，绑定原件、对每组摘要与语义、记录 PGF1 额外字节、分别测原生和验证落盘边界。该功能预检不填补 pcodec 的全量计时缺口。

### Zstd 字典：分开训练、编码、恢复的分组 I/O 功能预检

[`zstd_dictionary_grouped`](../../native/measurement/zstd_dictionary_grouped/) 是独立辅助构建，直接复用 r40 锁定的 `liblzbench_native.so` 和原 `feature_io.hpp`，不重编或替换历史插件。训练按冻结样本宽度把一个连续前缀拆成独立样本，调用同一训练入口；编码与恢复使用 level 3、307/521 字节流式缓冲，每 64 KiB 留出块各建一个新原生会话。一个方向只启动一个分组进程。`ZDG1` 是外层封装，不改变任何 Zstd 帧；完整恢复计费为原生帧字节 + `ZDG1` 字节 + 共享字典一次。

[功能预检](../../tests/integration/zstd_dictionary_grouped.py) 使用 r40 的 ETTh1 标准档（128 个训练样本、3 帧）与 Dominick-1121 短训练档（21 个训练样本、1 帧）：两份字典以及全部四帧均与锁定旧程序和 r40 账本逐字节对账；删除留出原值和旧 roundtrip 输出后，使用 ZDG1 与字典复原全部位。两个输入各验证截断帧、尾随数据、缺字典、错字典、训练前缀尾随数据五个拒绝。该测试使用同一 ELF 运行闭包，但**不是** Bubblewrap 隔离试验或性能结果。

后续计时计划须从同一 r40 主账本冻结 **23 个文件、3,244,160 B 训练前缀、1,917 个完整留出帧 / 124,595,936 B 留出值**。宿主解析原件完成身份校验；[隔离入口](../../src/tsbench/supervisor/zstd_dictionary_grouped.py) 已对操作分别限制挂载和文件大小：训练只挂载前缀，编码只挂载留出值与固定字典，恢复只挂载固定 ZDG1 与固定字典，不挂载原件或训练样本。挂载合同测试已通过，仍需真实 Bubblewrap 冒烟。训练时间分列，不摊作编解码时间；阶段级耐久钟、分组工作钟、隔离进程资源与最终产物校验分别报告。缺少隔离重复、封账和独立复算前，不提高计量覆盖计数。

### Gorilla C11 r2 封账与 pcodec 隔离运行

[Gorilla r2 同一运行报告](../../results/m3-gorilla-corpus-clock-20261120-r2/runs/3ec8705f65ae41a8b1f4cd9204f140bf/report.json) 已封账并独立复算：`tv-batch`、`append-resume`、`iterator` 各 16 个合法全文件，共 **192 次试验、448 个隔离方向操作**；各路线另保留 7 个域外决定。TV 批量由 Unique C11 原版执行，续写与迭代由同源 C11 修复版执行。该封账不变更 r40 功能终态或正式资格。

Gorilla 封账和复算退出后，按 [pcodec 冻结计划](../../results/m3-pcodec-grouped-timing-20261120-r1/plan.json) 在同一协作锁下完成 ETTh1 的隔离功能冒烟：每路线 7 组，两条路线合计 4 个方向操作。冒烟通过后才开始全量计划；隔离未因外层沙箱的命名空间限制而降低。除非后续运行封账并复算，否则不将 pcodec 冒烟或中间账本计入整语料测量覆盖。

[pcodec 全列分组报告](../../results/m3-pcodec-grouped-timing-20261120-r1/runs/531ad64c81aa49ada337818241c6d2b5/report.json) 已封账并独立复算：两条路线各 23 个文件、各 2,751 个原生页组，合计 **368 个方向试验**（92 预热、276 测量）。验证按各路线 r40 的每个 PM3PAGE1 内帧；报告分别列原生页帧、PGF1 外封装及完整恢复成本，不把第一值列旧证据和全列证据重复计数。

[覆盖清单 r4](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r4.json) 对原有九份诊断加 Gorilla 和全列 pcodec 复算，仍绑定 r40 **828** 个决定。675 个通过决定中，**304** 个有完整冻结范围的原生重复、**151** 个有投影或留样的原生重复，**202** 个有完整范围的验证后耐久重复。pcodec 的 26 个原首列投影晋升为全范围，原已全范围的 20 个只新增耐久覆盖；Gorilla 新增 48 个适用决定的全范围双时钟。未签发阶段收据，r40 终态不变。

### Zstd 字典：23 文件三方向重复诊断（r2）

[冻结计划 r2](../../results/m3-zstd-dictionary-timing-20261120-r2/plan.json) 绑定上述全部 23 文件和 1,917 留出帧。每文件每轮随机排列训练、编码、独立恢复，1 个预热轮和 3 个测量轮，合计 276 个方向试验。`train` 和 `encode` 的耐久钟含同一注册解析器重读原件及产物验证；`decode` 只读固定 ZDG1 和字典。字典开销不摊入编码或恢复，原生调用、wait4 与耐久时钟分列。r1 冻结后增加了小输出的 stdout/stderr 限额下限，未发起 r1 试验，另冻 r2 而非覆盖旧计划。

ETTh1 与 Dominick-1121 分别通过标准档、短训练档的 [真实隔离冒烟](../../tests/isolation/zstd_dictionary_grouped_smoke.py)，合计 6 个验证方向；外层沙箱造成的首次 `sandbox_failed` 不是实现失败。全量诊断须完成封账与独立复算后才能记入 `--evidence zstd-dictionary RUN`，不改变整个 M3 的主账本或阶段结论。

### ZFP 可逆 field：同源整列分组功能预检

[ZFP 整列驱动](../../native/measurement/zfp_field_grouped/) 链接 r40 同一冻结 C11 库，每个完整列使用一个新 reversible field，上下文生命周期和原生 `zn_encode_field` / `zn_decode_field` 不变。ZFG1 为测量用容器，携带原始 f64 列的形状及各原生帧长度，封装字节需与原生帧分列；原 r40 JSON 形状成本仍可对账，不把两份重复形状都当恢复必需。驱动的原生 API 钟不含上下文创建/析构，OpenMP 的 process CPU 可累计多线程工作，不可解释为墙钟。

[功能预检](../../tests/integration/zfp_field_grouped.py) 在 ETTh1 两个完整值列（每列 17,420 行）上，对 serial / OpenMP 1 / OpenMP 2 的 6 个原生帧逐字节对照旧控制器，所有产物仅用 ZFG1 在新进程串行恢复，另验证截断和尾随数据拒绝。这不是全范围、文件隔离或性能样本。后续计划须使用相同冻结资源合同对比线程配置，分列已配置线程与观测的原生参与线程；`fixed-rate-array` 的窗口、写后重开和质量结果是另一条路线，不从可逆 field 推断。

### Zstd 字典 r2 封账与覆盖清单 r5

[Zstd 字典报告](../../results/m3-zstd-dictionary-timing-20261120-r2/runs/e6155a18d0d340429f0fb968274084ec/report.json) 已封账并独立复算：训练、留出编码、独立恢复各 **92 次**（23 预热、69 测量），完整 23 文件及 1,917 留出帧绑定同一 r40 封印。没有把训练字节列为留出编解码吞吐分子，也未把字典计为每帧重复开销。[覆盖清单 r5](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r5.json) 已复核 12 份诊断，完整范围的原生重复/验证后耐久重复分别为 **327/225** 个决定，原生投影或留样仍为 **151** 个。主账本的 828 个决定及原始状态不变。

### ZFP 可逆整列：匹配 CPU 预算与独立多线程观测

[冻结计划](../../results/m3-zfp-field-timing-20261120-r1/plan.json) 绑定 `field-baseline`、`field-modes` 的可逆语料主路径、`openmp-encode` 三条路线，覆盖 **23 文件，每条线路配置 2,737 完整值列**。后者分别测试 serial/OpenMP 1/OpenMP 2 编码；所有恢复显式为 serial。五个配置共用相同的双物理核预算（逻辑 CPU 6、8，同 NUMA 节点），各配置都记录完整文件、同一原件、每列新建上下文及随机匹配轮次；不把配置线程数当作参与线程数，不宣称系统独占或线程实际绑核。原生调用 API、隔离进程资源、原件/固定帧至验证后耐久边界分列。

[独立观测程序](../../native/measurement/zfp_field_grouped/observe.cpp) 在另一二进制中统计相同可逆工作实际执行完整块与尾块的 TID；不输出计时数据、不进入原生或耐久分布。必须核对与不插桩路径相同的帧及恢复位，按列验证块数及尾块，不从线程创建或 runtime 请求推断参与线程。[真实隔离冒烟](../../tests/isolation/zfp_field_grouped_smoke.py) 在 ETTh1（7 列 × 17,420 行）和 Dominick-1121（1 列 × 142 行）完成 **20 个方向路径和 12 个独立观测**：OpenMP 2 的 ETTh1 每列观察到两个参与线程，短列仅一个。全量计划包含 920 个方向试验和 138 个对应的独立观测操作；未封账及复算时不登记覆盖。

[整列封账报告](../../results/m3-zfp-field-timing-20261120-r1/runs/98124ddf0cec4b5182ec75c7bcf29d85/report.json) 的 **920 次方向试验、138 次独立观测**全部复算一致。[覆盖清单 r6](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r6.json) 给三条整列路线新增 **69** 个完整冻结决定的原生与耐久重复覆盖；总数分别为 **396** 和 **294**，原生投影和留样仍为 **151**。线程配置和独立观测不重复计入文件—路线分母，也不改变 r40 主账本或正式资格。

### ZFP fixed-rate-array：更新与两份独立重开的分组预检

[数组分组驱动](../../native/measurement/zfp_array_grouped/) 使用同一 C11 库、同样的请求/有效 rate 18/32，以及同样的点写、缓存读与逐出、跨块范围写和 flush。`ZAG1` 两份归档各自携带完整形状、窗口地址及速率；保留原数组位流和原始窗口，不用可逆 field 代替数组语义，也不把断开的接受区间说成全列。数组创建、初始导出、更新/flush、更新导出，以及两份归档的独立 import 和 range 读取分别采集调用时钟。可恢复最终状态的计费、为验证留存的初始状态和包装成本须分列。

[与旧控制器的功能预检](../../tests/integration/zfp_array_grouped.py) 对 ETTh1 与 Bitcoin-1 两文件共 4 个冻结窗口，逐字节核对两种快照及新进程的独立重开产物；截断、尾随、错速率均拒绝。Bitcoin-1 首窗仍是初始通过、更新后拒绝，未调整质量界。这只是后续 23 文件、20,520 窗的方向计量基础，并非真实隔离/计时或覆盖增加。

### ZFP fixed-rate-array：冻结三区分操作、逐窗质量和隔离测量

[数组计量计划 r1](../../results/m3-zfp-array-timing-20261120-r1/plan.json) 按原件和 r40 封印锁定 **23 文件、20,520 个接受域窗口**，其中 6 个文件的 26 个窗口保留质量拒绝。每个文件做更新、初始归档独立重开、更新归档独立重开；1 预热轮、3 测量轮，同轮操作顺序由固定种子生成，合计 **276** 个方向试验。不把原计划排除的越界/短区间算入窗口计量，也不缩窗、重分片、放宽质量或调整 rate。

更新重复从原件，经注册解析器和同样的初始/更新产物对账；两种重开各只挂载一份经过校验的 ZAG1，宿主在隔离进程外逐窗按原始域重新核验。报告分别列 native 阶段、隔离进程资源和验证后耐久边界，更新最终恢复实体与初始验证实体分账；逐窗复核不应改变未触及块和原始质量结论。6 个质量拒绝文件仍实跑全部操作，结果与通过文件分栏；[覆盖审计入口](../../tools/audit_m3_measurement_inventory.py)只给从同一 r40 核对通过的 17 个文件链接，明确列出被质量门槛排除的实测诊断。相关合同测试已通过；真实冒烟和全量只在可逆整列封账复算退出后串行启动。r1 冻结在单 CPU 2 的外层亲和掩码下，执行使用同样的 `taskset -c 2`。

[数组封账报告](../../results/m3-zfp-array-timing-20261120-r1/runs/884e3af373a84f06856b9f77ea20f412/report.json) 复算全部 **276** 次试验和 **20,520** 个窗口：17 文件的 204 次试验可作合格范围诊断，6 文件的 72 次试验仅作质量拒绝诊断，共保留 26 个拒绝窗口。[覆盖清单 r7](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r7.json) 独立复算一致，完整冻结范围的原生重复和验证后耐久重复分别为 **413/311** 个决定，原生投影或留样为 **151**。不改写主账本或授予正式资格。

### ALP 与 Titchy 原生批路径：从留样扩展到全列窗口

[完整输入与固定帧清单](../../results/m3-column-batch-20261120-r2/population.json) 从同一 r40 封印锁定 `auto-batch`、`decode-backends`、Titchy `batch` 三路线各 **23 文件 × 2,751 值列窗口**，保留 65,536 行上限；I/O 组只约束单个文件尺寸，不改变帧或上下文边界。复用冻结 DSO：ALP 编码为 Auto，`decode-backends` 的 scalar-unfused 与 FALP auto 共用完全相同的固定帧；逐轮对账实际分派与向量计数，不把 FALP auto 当作 AVX512BW 实测。Titchy 批按原合同位转为 u64，独立恢复后核对包括负零在内的原位。原生帧、ABI 包装分别计费，不把分组预备写头当成压缩帧。

[真实隔离冒烟](../../results/m3-column-batch-20261120-r2/smoke.json) 用 ETTm2 的含尾窗 ALP 两路线及 ETTh1 的 Titchy 批共 7 个方向验证固定帧、输出原位和实际后端。首个计量预检的报告因误用只接受整数的分布函数而未封账；修正后另冻 [r3 ETTh1 预检](../../results/m3-column-batch-20261120-r3/preflight-runs/b06bb4ef0f424bb3bb3083e2a0e0a7aa/report.json)，28 次方向试验全部封账并复算。[r3 完整计量计划](../../results/m3-column-batch-20261120-r3/plan.json) 按文件/方向用相同 CPU、一次预热和三次独立进程重复，合计 **644** 次。编码耐久钟从锁定原件重新解析开始，解码只挂载固定帧组，两者截至验证和文件/目录同步；ABI、上下文创建、隔离进程和耐久时钟分列。没有系统独占，也不把 Titchy 批处理计作包流或访问机制证据。全量只有封账并复算后可用 `--evidence column-batch RUN` 更新覆盖清单。

[全列封账报告](../../results/m3-column-batch-20261120-r3/runs/b7cf97d91dea4a20afd2161118b4eefa/report.json) 已复算全部 **644** 次（161 预热、483 测量），覆盖 69 个文件—路线决定。[覆盖清单 r8](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r8.json) 登记 **482** 个完整原生重复及 **380** 个完整验证后耐久重复；仅有原生投影或留样的决定从 151 减至 **105**，两条 ALP 路线的旧留样未重复计数。

### Titchy 原生包流、加载访问与无状态范围

[原生机制清单](../../results/m3-titchy-grouped-20261120-r1/population.json) 对账 **23 文件 × 3 路线，8,239 个原生单元**。包流按完整值列各建一个流，会话不跨列，不将加载访问和无状态范围的 65,536 行原生窗口用在包流上。访问输入来自同一份 TCHY 原生帧，与 ABI 批处理帧的裸载荷逐摘要对账，但不把其 ABI 外封装重复计入访问路线。每个压缩实体与恢复原位均对账 r40；每个访问请求的值和内存回调字节数也必须一致。

[ETTm2 / Dominick 预检](../../results/m3-titchy-grouped-20261120-r1/preflight-runs/324ddd18913d40bfaa71d1f3d616aae5/report.json) 已独立复算 **48** 次方向试验，覆盖完整列包流、尾窗、独立重开以及三类访问请求。原生首包、回调/文件打开、点/位/范围和额外全量恢复校验分别计量，物理文件读字节仍未知。绑定同一 `libtitchy_c.so`，复用原控制器而非重写编解码；[全范围计划](../../results/m3-titchy-grouped-20261120-r1/plan.json) 为 **552** 次配对方向试验，ALP/Titchy 批流程退出后串行启动。只有封账并复算后才可用 `--evidence titchy-grouped RUN` 计入覆盖。

### PBEPLA-RR 逐层计量接入

[同窗清单](../../results/m3-pbepla-grouped-20261120-r1/population.json) 绑定 r40 两条路线全部 **46** 个文件决定，**41,048** 个路线—窗口记录（每路线 20,524）。两路线共同保留三个分辨率失败窗，不伪造前缀或将原生失败当成无损/合法输出。新的[原生计量驱动](../../native/measurement/pbepla_grouped/) 链接同一 `libtba_native.so` 并复用原语料控制器；分别记录批编码、有限源 replay、参考批编码、逐层前缀生成和独立恢复的原生 API 边界。replay 的参考批编码是校验对照，不计入其原生编码时钟。固定帧、逐层误差、首次 sink 和实际逻辑临时文件流量按原口径保留。正例和已知失败的隔离预检在 Titchy 全量封账后串行执行；本清单和编译结果不是计量通过。

[逐层重复计量全范围计划](../../results/m3-pbepla-grouped-20261120-r1/plan.json) 与 [ETTh1 / Bitcoin-1 预检计划](../../results/m3-pbepla-grouped-20261120-r1/preflight-plan.json) 已冻结。每个文件—路线执行一轮预热和三轮独立重复，每轮按冻结顺序执行编码和三层独立恢复。至多 32 窗仅作为同一运行内的隔离进程输入批次；统计样本是完整的文件—方向轮，不把子批次、窗口或前缀数当成独立重复，也不发分片收据。每层解码只挂载该层固定帧，原值仅供宿主验证。在封闭的 r40 全量范围有 **736 个计划槽**，其中 4 个原生失败的文件—路线决定仍在编码方向实跑；无有效前缀的 48 个解码槽明确写为 `not_run_no_valid_prefix`，不填写零耗时或授予覆盖。输出区分独立的 PBEP 前缀开销与验证用打包开销；不会把跨层压缩字节或系统进程时钟加进原生调用耗时。执行顺序为 Titchy 封账 → 冻结 PBEP 正例及原生失败隔离冒烟 → 逐层预检封账复算 → 启动全量。未封账阶段只报告实际进度。

### pcodec Auto 与 Zstd/XZ 固定批基线路线

[全量计划](../../results/m3-fixed-batch-corpus-20261120-r1/plan.json) 从同一 r40 完整封账固定 pcodec `source-auto` / `c-native-auto`、Zstd `zstd-baseline`、XZ `xz-baseline` 各 23 个文件，即 **92 个文件—路线决定、736 个方向试验**（一轮预热、三轮独立重复）。pcodec 继续按值列切分，每帧最多 65,536 行；Zstd/XZ 继续使用行主序交错 V 字节，每帧最多 65,536 字节，分别使用 level 3 / preset 6。尾帧、逐帧摘要和实际后端信息逐项绑定原决定；不把 Zstd/XZ 的整对象会话或 workers 路线替代成固定批证据。驱动只重新构建计量入口，不重新编译冻结 codec。

I/O 组只用于加载/交付，每个原生帧仍有独立 ABI 上下文，预备头不计入压缩字节，不把内层帧当作独立测量样本。编码方向从原件重读和逐帧核验到产物与运行内目录 `fsync`；解码方向只给隔离进程挂载固定帧组，对完整恢复的原始位与 schema 核验后同步。原生 ABI、上下文创建、隔离进程、验证后耐久总钟分列，不承诺主机独占、冷缓存或断电恢复。每个文件—路线只保留一套核对原件和固定帧组，重复产物在账本落记录后回收；整个执行只有一个封账。

[ETTh1 预检计划](../../results/m3-fixed-batch-corpus-20261120-r1/preflight-plan.json) 的 32 个方向试验须在其他测量让出协作锁后执行。用 `tools/m3_fixed_batch_corpus.py run --plan PLAN --runs OUT` 执行，`verify --run RUN` 验证冻结来源、账本、分组原值/帧、资源记录和报告。仅在全量封账并复算后，才以 `--evidence fixed-batch-corpus RUN` 链接至 r40 覆盖清单。预检、构建或计划不计覆盖。

[固定批全量封账](../../results/m3-fixed-batch-corpus-20261120-r1/runs/d4d145adbb084e7c832d081e6c1ca186/report.json) 的 736/736 方向试验已独立复算。四条固定批路线各 23 个文件—路线决定纳入[测量覆盖 r11](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r11.json)，覆盖清单双次复算一致。主账本 675 个通过决定均有完整范围原生重复诊断，其中 583 个有完整范围验证后耐久重复；余 92 个耐久缺口属于下述 Sprintz/FEC1/SElf*。完整范围不意味着正式资源准入，不改质量或失败终态。

### Titchy 三机制封账与 PBEPLA-RR 预检

Titchy [全量独立复算报告](../../results/m3-titchy-grouped-20261120-r1/runs/c5dd352b9fcb46baa37d15d36f3b3953/report.json) 核对三条机制各 23 个文件，共 552 次方向试验。新增至 [r40 覆盖清单 r9](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r9.json) 后，完整范围原生重复为 541 个决定、完整范围验证后耐久重复为 449 个；清单用原证据参数独立复算一致，没有改变 r40 功能终态或授予正式计时资格。

PBEPLA-RR [禁网冒烟](../../results/m3-pbepla-grouped-20261120-r1/smoke.json) 与 [逐层预检](../../results/m3-pbepla-grouped-20261120-r1/preflight-runs/9459400e240f494180c58df7fb135ab6/report.json) 均通过原合同对账。预检的 64 槽中 40 个执行（含记录预期原生失败的编码槽），24 个没有有效前缀，未运行而不补零；预检不计全量覆盖。

[PBEPLA-RR 全量](../../results/m3-pbepla-grouped-20261120-r1/runs/7fb0e5ac342b484681e40e88208adad9/report.json) 共 736 槽，实际执行 688 槽，48 槽因无有效前缀未运行，不补零。封账和独立复算后，[覆盖清单 r10](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r10.json) 新增 42 个通过的文件—路线决定；完整范围原生重复 583 个、完整范围验证后耐久重复 491 个。4 个原生失败仍只作诊断，不用于覆盖通过数或正式排名。

复算了[历史账本复解中的三个失败窗](../../results/m3-real-r40-20261120/pbepla-full-ledger-replay-20261120-r1.json)：按规范入口从源文件取第 0 值列，逐窗字节摘要与渐进、replay 两路线均一致。首层请求 `eps=16` 时，原生 `layer_geometry` 的栅格宽度为 `ldexp(max(x) - (min(x) - 2*eps), -r)`，要求不超过 `2*eps`。三个窗口在首层第一次尝试就分别需要 **31、40、32 位**，超过原生 PBEP 的 **30 位**上限；不是数值收缩重试、回放路径或本机资源先触发的错误。

| 规范输入（第 0 值列） | 窗口（左闭右开） | 最小分辨率 | 保持 30 位时仅满足栅格宽度所需的 `eps` 下界（固定原栅格范围） |
| --- | --- | ---: | ---: |
| `bitcoin-dataset-without-missing-values-1` | `[0,2291)` | 31 | 23.02527 |
| `bitcoin-dataset-without-missing-values-1` | `[2291,4581)` | 40 | 11641.01902 |
| `bitcoin-dataset-without-missing-values-3` | `[0,4021)` | 32 | 34.17446 |

不提高原门槛、不删窗。若验证扩大栅格容量的新原生实现，须以独立版本同时验证编码、所有前缀恢复、流式 replay、旧帧兼容和超边界拒绝；若采用外部新分块，则另列适配路线，不能回写原生 r40。

[独立宽栅格候选](../../catalog/selections/pbepla-wide-grid-candidate-v1.json) 由同一 Unique 档案构建，锁定三个被补丁修改的源文件及版本段，不替换 `tba_native` 正式注册。栅格索引上限扩展到 52 位，使 `index + 0.5` 仍可由 binary64 精确表示；这不保证任意原始值的栅格仿射计算或恢复正确，仍逐前缀验证。分辨率在 30 位以内依旧写 PBEP v1；存在更宽层才写 PBEP v2，且 v1 解码器明确拒绝 v2。行范围、原始单位、`eps=[16,4,1]`、`max_delay=64` 与原生回放接口不变，无外部分块或 fallback。

[禁网预检及独立复算](../../results/m3-pbepla-wide-grid-20261120-r4-isolated/report.json) 的 38 个进程覆盖 3 个冻结失败窗、1 个旧格式对照和越界反例。原版两入口均重现 30 位上限错误；候选的两个原生入口生成相同的 3 层前缀，且每层由只挂载前缀的批恢复和回调恢复分别执行，恢复字节一致、精确误差均不超门槛。三窗的第 3 层完整帧为 **3,339 / 4,688 / 23,121 B**。ETTh1 对照的 v1 帧与恢复字节仍匹配 r40；超过 52 位需求未产出帧。用 `tools/m3_pbepla_wide_grid.py --verify RUN` 重算输入摘要、封账、传入文件和误差。预检不覆盖全部原生语料、NOAA 的第一层舍入误差或正式计量，不改历史结果。

[宽栅格＋精确误差候选](../../catalog/selections/pbepla-wide-grid-exact-bound-candidate-v1.json) 使用独立构建身份，在两个原生编码入口及其序列化复验中补上 binary64 误差边界判断：只在舍入后误差与门槛相等时计算精确差的舍入残量，从而区分精确相等和实际略超限；不改原请求门槛或重试规则。[禁网复验](../../results/m3-pbepla-exact-bound-20261120-r1-isolated/report.json) 的 80 个进程覆盖原 4 个窗口及 NOAA 的全部 6 个 PBEPLA 窗口，双原生入口、全部前缀均通过，封账已独立复算。原 NOAA 失败窗仍复现旧帧的 `9007199254740993/562949953421312 > 16`；候选在一次原有数值收缩重试后以有效门槛 `15.984` 编码，实际最大误差为 `8998192055486251/562949953421312`，旧版解码器也能恢复该 PBEP v1 新帧。其余 5 个 NOAA 已通过窗和 ETTh1 对照的三个前缀字节不变。不替换正式注册或 NOAA 原日志。

[候选真实语料执行器](../../tools/m3_pbepla_candidate_corpus.py) 按 r40 的两条原生路线冻结 **23 文件、20,524 个窗口**，绑定旧帧全集、宽栅格＋精确误差构建及 NOAA 预检。每个窗口分别调用原生渐进、replay 编码；全部前缀以对应的批／回调模式独立恢复，并复算原单位精确误差。旧帧未变时核对历史摘要；改变时实际交叉恢复 v1，或核对旧解码器拒绝 v2。每次候选验证仅一份账本和一个顺序打包产物，不分片签收；最多 32 窗分组，组内相同字节只存一次。先用 ETTh1 全部 35 窗预检，成功后同入口执行全量；全量结果须封账并独立复算，不吸收为正式 r40 或性能证据。

[候选全量](../../results/m3-pbepla-exact-corpus-20261120-r1/full/report.json) 已封账，由 `tools/m3_pbepla_candidate_corpus.py verify --run RUN` 独立复算一致：5,286 个隔离进程，两个原生入口均通过 20,524/20,524 窗，三个历史失败的 Bitcoin 窗口在两路线均通过。按窗和层计、同字节的两个入口不重复计数，61,563 个 v1 前缀帧及恢复字节均未改变；旧版解码器明确拒绝 9 个新增 v2 前缀。此结果可作为下一版构建的功能对照，不是正式注册、计量或验收。

[新版 M3 公开入口计划](../../results/m3-pbepla-entry-20261120-r4/plan.json) 用 `--pbepla-repair-provenance` 显式绑定 PBEPLA 派生库、候选全量已实测的分组控制器、独立 PBEP v1/v2 验证与禁网恢复闭包。`tools/stage_m3_pbepla_repair.py` 从封账证据单独分发构建，不覆盖 Unique 档案、r40 执行器或原构建；工作进程及其他插件保持不变。新版分母仍为 23 文件、36 路线、180 项必需及 6 项条件义务。原失败的三个 Bitcoin 窗口已从同一公开入口在两条路线逐层恢复通过（[前两窗及 v1 对照](../../results/m3-pbepla-entry-20261120-r4/bitcoin-preflight/435b87e8f8e8429cb404501392461eb4/report.json)、[第三窗](../../results/m3-pbepla-entry-20261120-r4/bitcoin-preflight-additional/350c600f11604d6bbe6fc094fd97ab26/report.json)）；[NOAA 换输入计划](../../results/m3-pbepla-entry-20261120-r4/noaa-plan.json)使用相同构建和路由。这些定向证据不是正式主测。

### Sprintz FIRE、Huff0 FEC1、SElf* 的验证后耐久重复

[全量计划](../../results/m3-whole-durable-20261120-r1/plan.json) 将已有封账原生计量的 Sprintz `fire-batch`、Huff0 `huff0-reference`、SElf* `selfstar-batch` / `selfstar-incremental` 绑定到同一 r40 冻结范围，保留原 worker、编解码几何、已验证帧摘要和匹配轮次，**92 个文件—路线决定，共 736 次方向试验**。这是重新实测，不拼接旧的原生时钟和新的 I/O 时钟。Sprintz 使用原 f64 位片语义，Huff0 保留 FEC1 原生存储模式，SElf* 增量仍按原有序 add/finish 与 read-next/drain；不把增量编解码的内部计时改称批 ABI 计时。

编码每轮重新读取锁定原件并分组核对规范值；解码每轮只有固定帧挂载，产物须匹配原始位和 schema，之后同步产物文件及运行目录内的所有父目录。各文件—路线保留一份规范值和固定帧组，不保留每轮重复输出。`.jsonl`、配置、运行环境和报告绑定同一封账。[ETTh1 预检](../../results/m3-whole-durable-20261120-r1/preflight-runs/6de5812be3d943b08dcf0eee8f88ac31/report.json) 的 32 次方向试验及[全量](../../results/m3-whole-durable-20261120-r1/runs/199b60436700455b8c16afba9e35bffb/report.json)的 736 次方向试验已分别封账并独立复算。用 `tools/m3_whole_durable.py run --plan PLAN --runs OUT` 与 `verify --run RUN` 执行并复算；覆盖清单只接入已封账复算的全量 `--evidence whole-durable RUN`。

[计量覆盖清单 r12](../../results/m3-real-r40-20261120/measurement-inventory-20261120-r12.json) 保留 828 个决定，19 份封账诊断；独立复算一致。r40 的 675 个通过决定现在均有完整范围的原生重复和验证后耐久重复。独立诊断不合并为正式主运行，不改变未通过项，不授予正式计量资格。

### CORAD 留出质量定位（不改判）

按 r40 专项保留的两份 `held-out.bmk` 独立解码，并按 CRD1 的稀疏记录/列引用标记对原始位计算误差。两种训练器各有 4 个引用记录：压力引用覆盖 4 点，其最大绝对误差为 21.43 / 21.48 mbar，同列非引用段为 0.54 / 0.17 mbar；湿度引用覆盖 12 点，其最大绝对误差为 155.02 / 156.43 个百分点，同列非引用段为 1.39 / 1.75。这里的顺序为 C LARS / Source sklearn。严重误差集中在引用段，不能归为两条训练后端碰巧出现同样的稀疏近似误差。冻结原版在 tricklet 上用 Pearson 判定是否引用，而独立恢复直接使用被引用列的标准化重建值，再用目标列的训练统计反变换；高相关不保证两个标准化序列的水平和幅度相等。这一定位不改模型、门槛、帧或 r40 结论；候选诊断需先限定为独立版本/原生参数对照，并保持留出不参与调参。

[CORAD 列引用误差保护候选](../../catalog/selections/corad-reference-error-guard-candidate-v1.json) 按源档案的前后哈希将单文件补丁应用到独立 C11 构建，不注册或替换 `corad-frozen`。候选保留原 Pearson 阈值、字典、统计、OMP 与 CRD1 格式；只有引用采用原解码算术后，在目标列原始单位上逐点不劣于该列自身的稀疏重建，才写列引用；两个不同的重建值若浮点误差比较打平则保守拒绝引用。此规则没有新增可调参数；模型和校准门槛保持原值，编码时的逐块判断不访问其他留出窗口。

[独立候选报告 r2](../../results/m3-corad-reference-guard-20261120-r2/report.json) 对 6 个输入完成 24 个禁网隔离进程，原版对照逐字节重现 r40 两份留出原生帧。C LARS / Source sklearn 的候选留出都通过原有训练校准门槛；每帧从 1,264 增至 1,336 字节，引用从 4 降至 0。相同列的控制例仍使用引用且逐位恢复；完全正相关但整体偏移 100 的控制例不再错误复制。候选帧由原版 C 解码器在仅挂载 CRD1 的隔离进程中恢复，并与独立解释器对账。`tools/m3_corad_reference_guard.py verify --out RUN` 重算计划、原版门槛、独立恢复和报告。首个尝试仅因隔离启动器的通用上限参数设置无效而退出，未产生合格记录。

以上表明候选能修复原专项反例，不表明 13 个真实文件 cohort、其他原生机制、性能或 M3 已通过。候选推广须冻结新配置/源码/构建身份，保持原代码与失败记录可复现，另对真实语料验证并按阶段合同提交新的全量运行；不把这 6 个输入的诊断拼入 r40。

[CORAD 候选真实语料复核计划](../../results/m3-corad-guard-corpus-20261120-r1/plan.json) 覆盖 r40 的全部 **13 个适用文件、346 个列 cohort、692 个冻结模型、1,174 份留出帧**，保留另外 30 个域外文件—路线决定。按原文件重建同一训练/留出范围并独立核对 train-only 门槛，不重新训练或选模。用原语料控制程序和专用候选 C11 库编码，再用同一个 r40 原版库在独立的只读帧挂载中恢复；独立解释器复算每项原始域误差。报告列出原版和候选状态迁移、完整帧字节与实际引用数；同一个诊断 run 一份账本，没有分片收据。不是性能诊断或阶段替代。

[ETTh1 预检](../../results/m3-corad-guard-corpus-20261120-r1/preflight/report.json) 的两帧已经完成禁网编码/恢复和独立复算。两个候选均将引用记录从 2,269 降到 0，完整 CRD1 由 93,564 增至 134,406 字节。所有列通过原 MSE 门槛，但 `HUFL`、`MUFL` 的最大绝对误差仍超原门槛，两帧均保留 `quality_rejected`；不可由专项反例的通过推及真实语料。

[候选全量封账报告](../../results/m3-corad-guard-corpus-20261120-r1/full/report.json) 记录 13 文件、346 个列组及两种训练器的 1,174 份原生帧，涉及 2,348 个独立禁网进程。`tools/m3_corad_guard_corpus.py verify --out RUN` 已独立复算，结果一致。按封账计划和逐帧账本另行核对：422 帧由质量拒绝转为通过，96 帧保持通过，656 帧仍拒绝，无通过转拒绝；两种训练器都只有 `national-illness` 的全部帧通过。完整 CRD1 总字节由 112,171,214 增至 152,256,872（**+35.74%**），原生列引用数从 2,227,657 下降至 676。仍拒绝的帧全部至少有一列最大绝对误差超限，266 帧同时有列 MSE 超限，537 帧没有任何列引用。因而单独修复列引用不能使候选满足全量门槛；进一步定位稀疏恢复误差需保持训练/开发/留出界限，不能用这些留出帧挑模型或放宽门槛。该对账不改 r40，也不把候选直接注册为正式路线。

[无引用帧的全量残差归因](../../results/m3-corad-guard-corpus-20261120-r1/sparse-residual-full-20261120-r1.json) 在 1,174 帧分母中独立解释 978 帧（441 通过、537 质量拒绝），另列 196 帧不在无引用分析范围内。按冻结窗重新取原件、重建并核对源与恢复摘要；点误差从原始 binary64 值判定，舍入相等时用有理数精确比较。共 713,688 个值超逐点门槛，其中 703,118 个落在相应训练列的最小值/最大值之外，仍有 10,570 个落在训练范围之内；194,738 个包含超限点的稀疏段全用了档案声明的最大非零系数数目。原生 raw 尾段逐位恢复。非零项用满和范围外分布是诊断观察，不是已证明的因果关系，不说明放宽非零限额可通过。若评估额外的稀疏求解策略，只能在 train/development 上确定并冻结，留出不可用于选参；之后按原门槛独立复验、计入完整字节成本。

[原生 CORAD 开发集对照](../../tools/m3_corad_sparse_development.py) 预先锁定 OMP 非零项预算 `2 / 3 / 4`。保留两种冻结训练产物、4 点段、相关阈值和原质量门槛，只改变传给原生公开接口的求解预算，不新增补偿流。执行器只解析 train/development 前缀并核对分区摘要；编码进程仅挂模型及开发窗，解码进程仅挂完整帧，原 C 恢复结果与独立解释器一致才判定质量。全量开发中，仅所有计划窗通过的预算有资格入选，再按完整 CRD1 字节最少、同数时取较低预算作决定。ETTh1 投影不选参；开发集产物不能替代留出或正式性能证据。

[ETTh1 禁网开发集预检](../../results/m3-corad-sparse-development-20261120-r3/preflight/report.json) 的 6 项试验均成功恢复并复算；预算 2 的两项都被原质量门槛拒绝，预算 3、4 的各两项均通过。后续开发运行出现 301,328 B 的 CRD1 帧，超过旧恢复控制器的 256 KiB 输入缓冲，不能把该恢复失败归为原生算法质量拒绝。[新诊断构建工具](../../tools/build_m3_corad_sparse_restore.py) 仅把恢复控制器的缓冲与已冻结编码控制器对齐为 512 KiB，原生解码库及其依赖逐摘要不变；单独记录构建和新运行，不改旧预检或 r40。

[512 KiB 版本 CORAD 开发集全量](../../results/m3-corad-sparse-development-20261120-r5/full/report.json) 封账覆盖 13 个文件。预算 2、3、4 各 1,176 项，分别有 535、705、1,052 项通过，余项都是质量拒绝，无原生编解码失败。没有预算满足所有开发窗，未选择预算、未执行留出。预算 4 仍有 124 项质量拒绝，不能用 ETTm1 的 8/8 通过替代全量。

[预算 4 拒绝归因](../../results/m3-corad-sparse-development-20261120-r5/rounding-attribution.json) 在 124 个真实开发帧中重算全部 184 个拒绝列，均为训练常量列、门槛确为零。保持原 CRD1 字典、系数和引用记录，对完整反标准化做一次精确舍入，仍是 184 列全部拒绝（最大误差超限点从 449,808 变为 440,960，两种算术的超限点均无列引用）。已独立复算；只收紧解码算术不足以让当前记录通过，既不改判，也不据此选用预算 4 或读取留出。

预先定义的 CRD1 引用保护与 OMP 预算对照分开。`tools/stage_m3_corad_guard.py` 将保护库与已确认的 PBEPLA 修复组合到新构建：CORAD 语料控制器、C LARS 和推理专项共用同一库，保持两种训练、冻结预算 2、原门槛、CRD1 和独立恢复。新版以 `--corad-repair-provenance` 锁定保护库及范围；下一次运行必须原样报告仍拒绝的语料，不把通过的命名专项外推至全部列或文件。

[组合构建 CORAD 三路复算](../../results/m3-pbepla-corad-entry-20261120-r1/corad-audit.json) 重新计算 13 个适用文件的原单位误差和计费，并在隔离进程重放留出样本。69 个决定中 30 域外、36 质量拒绝；只有 `national-illness` 的推理与两种训练三项由 r40 的拒绝转为通过。每种训练的 587 个留出帧中，C LARS 有 265 个通过、322 个拒绝，原版 sklearn 训练有 253 个通过、334 个拒绝；r40 两种训练各有 48 个通过。此为两个封账观察的对照，不把非确定性训练的差异全部归因于保护库。17 个命名义务为 11 通过、6 失败：推理专项的已冻结留出样本不再同时覆盖稀疏和引用两条原生分支，产品核验停止，包括 `bound_predeclared_before_formal_run` 在内的六项均未通过；这项失败与 36 个语料质量拒绝分别列账。不改变质量门槛，也不把独立的引用保护正、负对照替代推理专项。

[CORAD 同 ABI 分支诊断](../../results/m3-corad-specialist-branch-20261120-r3/probe/report.json) 用组合构建中同一 guarded 插件分别复跑原专项的两个冻结模型和留出输入，第一帧摘要与原失败账本一致。独立 CRD1 解析和仅挂载帧的恢复均显示各 48 个稀疏记录、0 个引用、72 B 原样尾部；两帧按原先训练期冻结的最大误差和均方误差界均通过。原运行因分支断言中止，仍保留原来的 6 项失败，不能回填这两项诊断。另在同 ABI、预算 2 下预先冻结两种相同几何的机制对照：完全相同的列保留一次引用，尺度不同但完全正相关的反例不引用；两个结果均逐位恢复。下一版计划须分别绑定真实留出质量与机制正反例（含坏引用拒绝），而不是要求同一个录得的留出窗凑齐分支。须先走 M0 合同变更，不改原门槛、不替代 36 个全语料质量拒绝。

[M0 CORAD 合同修订](../../results/m0-corad-guard-amendment-20261120-r1/amendment.json) 是对原 M0 定义的有作用域补充，保留原 M0 收据与 186 个义务 ID、828 个决定、两种训练、冻结模型、输入和原单位质量界。只为 CORAD 推理的 6 个义务更新证据绑定：真实留出验证有理数误差及原样尾部；冻结的 `safe-reference`、`unsafe-correlated-reference` 分别验证安全保留与不安全抑制；坏引用构造来自正例帧，将有效引用改成自引用后须由实际解码返回明确拒绝且无输出。两种对照均要求独立的仅帧恢复和逐位一致。原版其它拒绝、独立原生对照、pinned 解码及采样不删除。`tools/freeze_m0_corad_guard_amendment.py --verify` 已独立复算修订；[新版 M3 计划](../../results/m3-corad-amendment-20261120-r1/plan.json) 仅增加 `--corad-specialist-amendment` 绑定，未改其它计划字段（除内容身份）。无已绑定原生引用保护的构建不能套用修订。换输入计划引用新版基线及同构建，但不携带原专项义务或原计量分母，也不声称重跑 17 项命名义务。

[新版 CORAD 公共入口封账](../../results/m3-corad-amendment-20261120-r1/preflight/ce0904ebf5fb4509856cf0b5b973d667/report.json)：17 个命名义务全部通过，两份原留出按未变门槛通过，安全/不安全对照分别为 1/0 个引用，自引用触发插件状态 5、进程状态码 3 且无输出。69 个语料决定仍为 3 通过、36 质量拒绝、30 域外；[独立审计](../../results/m3-corad-amendment-20261120-r1/corad-audit.json)逐项复算原单位质量、分支、拒绝及计费，重新启动隔离解码检查专项帧和 26 个语料留出样本。不以任何专项或补充输入改判语料，且不签发阶段或性能资格。

[同构建 NOAA 补充运行对账](../../results/m3-corad-amendment-20261120-r1/noaa-audit.json) 引用上述新版全量计划作为基线，仅替换输入清单。36 个决定中 33 通过、1 域外、2 条件未触发，12/12 选型均有通过的换输入证据。此结果不覆盖原 23 文件的质量拒绝，也不作为主测计时。

### 同一主账本的独立双向计量预检

[计量计划](../../results/m3-in-run-measurement-20261120-r1/plan.json) 由公开入口的 `--measurement-cpu` 冻结，登记全部 828 个决定的状态，其中 46 个 PBEPLA-RR 决定有全文件适配器、其他 678 个适用决定明确标记缺适配器，74 域外、30 条件未触发。独立复用同一运行生成并核对的前缀，不读 r40 的时钟或帧。每个通过的 PBEPLA 决定包含一轮预热、三轮测量，轮内随机匹配编码与三层 frame-only 恢复；组不计作独立重复。包括原生调用、验证后耐久墙钟、CPU/RSS 及完整前缀计费。[公开入口 Bitcoin 封账复算](../../results/m3-in-run-measurement-20261120-r1/bitcoin-audit.json) 验证两路线共 32 个独立方向试验（8 预热、24 测量），原始观察和汇总均在功能主账本的工作决定中。协作锁和亲和性不等于系统级独占，此为计量接线诊断，不能授正式主测资格。

第二版用 `--measurement-cpu CPU --measurement-fixed-batch-worker WORKER` 绑定四条固定批路线及同一构建锁中的 codec，保留第一版计划和复算路径。[第二版计划](../../results/m3-in-run-fixed-batch-20261120-r1/plan.json) 仍冻结 828 个决定：92 个固定批、46 个 PBEPLA 有适配器，586 个适用决定缺适配器，74 域外、30 未触发。四条路线是 pcodec `source-auto`、`c-native-auto`、XZ `xz-baseline` 和 Zstd `zstd-baseline`，不包含 ALP 解码后端或 Zstd/XZ 会话和后台 worker 模式。固定批帧组由本次运行的锁定原件重建，逐帧核对同次功能记录的 SHA-256、schema 和尾帧；编码方向每轮重读原件，解码方向只挂载核对过的帧组。只保留每个决定的一套原值组和帧组以独立复算，不保留逐轮重复产物。编码与解码同轮随机配对，原生 ABI、上下文创建、进程资源、验证后耐久总钟和帧字节分别登记。锚点缺失或某轮失败不会生成通过数据，剩余方向显式记为未运行。

[ETTh1 公开入口封账复算](../../results/m3-in-run-fixed-batch-20261120-r1/etth1-audit.json) 的六个功能决定全部通过，主账本共保留 64 个独立方向试验（16 预热、48 测量）。其中固定批四路共 32 个，PBEPLA 两路共 32 个；审计核验 96 个隔离进程身份，分组不作为运行轮次。此为非独占的定向预检，不能计作 138 个决定均已测量，也不改变 r40 的任何观察。

第三版 `--measurement-column-batch-worker WORKER` 使两条 ALP、Titchy 原生批三条路线按完整值列进入同一主账本，共新增 69 个计划决定（计量适配范围 207 个，仍有 517 个适用决定未接）。ALP `decode-backends` 每轮从同一帧组分别解码 `scalar-unfused` 和 `falp-auto`，实记分派及向量计数；Titchy 批不作为包流或访问证据。沿用 Unique `fix_ReWrite` 的 ALP 与 Titchy 原生功能报告，未替换算法库。[ETTh1 九路线预检](../../results/m3-in-run-column-batch-20261120-r1/etth1-audit.json) 的 92 个方向试验（23 预热、69 测量）通过并复算；ALP Auto 在该样本报告 AVX2 分派，但有效 FALP SIMD 向量为零，不能据此声称 AVX2 内核已执行或 AVX512BW 已验证。未授主测资格，第二版原审计仍可原样复算。

第四版 `--measurement-gorilla` 将 Unique 选型 #7 的 `tv-batch`、`append-resume`、`iterator` 接入同一主账本。批路线仍使用 `gorilla-native/unique-v1` 的 C11 库 `gorilla_c`，后两路使用[同源 C11 状态修复构建](../../catalog/selections/gorilla-state-repair-v1.json)，`.cpp` 文件是 TSBench 适配和控制层，不是算法替换。[冻结计划](../../results/m3-in-run-gorilla-20261120-r1/plan.json)新增 48 个计量适用决定（每路 16 个），全计划共 255 个已接、469 个待接。计量逐块核对同一次运行的帧和原始 TV 位模式；解码只挂载固定帧，快照恢复另计，迭代器核对前向 seek。原生段、进程资源、验证后耐久总钟和字节账本分别记录。

[ETTh1 与 National Illness 公共入口预检](../../results/m3-in-run-gorilla-20261120-r1/etth1-and-national-illness-audit.json)复算 6 个计量决定、56 个独立方向试验（14 预热、42 测量），每列分别含 12 行和 454 行的尾块。前一次[外层沙箱预检](../../results/m3-in-run-gorilla-20261120-r1/etth1-constrained-audit.json)的 3 个功能决定通过，但 Bubblewrap 在计量锚点阶段启动失败，28 个方向槽均未执行；该记录未被重跑覆盖。成功预检保留禁网和最小挂载，仍为协作锁而非系统级独占；不授正式主测资格。失败账本保留了终态，但临时目录回收导致原生 stderr 路径失效，正式主测前须保留可复核的失败日志。

第五版 `--measurement-pcodec-pages-tool TOOL` 复用既有隔离控制器和冻结的 `libpcodec_c.so`，为 `source-pages` / `native-pages` 增加各 23 个适用决定。[第五版计划](../../results/m3-in-run-pcodec-pages-20261120-r1/plan.json)已接 301/724 个适用决定，423 个待接；功能、输入、构建锁和 CORAD 专项绑定不变。按同一次功能执行的逐组 PM3PAGE1 摘要及页语义核验编码，独立解码只挂载固定 PGF1，恢复全部值位。分别登记原生页组 API 时间、进程资源、验证后耐久总钟、原生帧与 PGF1 外封装字节。Unique `fix_ReWrite/pcodec-native/FUNCTIONAL_REPORT.md` 是接口功能基线，不代替计量，也未将原 `source-auto` / `c-native-auto` 的固定批路线算作页路线。

[ETTh1 与 ETTm1 预检](../../results/m3-in-run-pcodec-pages-20261120-r1/etth1-and-ettm1-audit.json)独立复算 pcodec 两条页路线的 32 个方向试验和 Gorilla `append-resume` 的 24 个方向试验；pcodec 每条路线分别消费 7 组及 14 组，ETTm1 每列跨 65,536 行边界并验证尾组。第五版同时在 Gorilla 与 pcodec 页路线回收失败目录前保留监督器日志，[隔离启动失败对照](../../results/m3-in-run-pcodec-pages-20261120-r1/retained-failure-audit.json)复算 3 个计量失败、28 个方向槽未执行，stderr 实文与摘要可查。旧运行未覆盖；本机记录的亲和性及同 UID 协作锁仍不证明系统级独占，两份第五版预检均不授正式资格。

第六版 `--measurement-abi-corpus-worker WORKER --measurement-selfstar-corpus-worker WORKER` 增加 Sprintz `fire-batch`、Huff0 `huff0-reference`、SElf* `selfstar-batch` 和 `selfstar-incremental` 四路，每路 23 个适用决定。[冻结计划](../../results/m3-in-run-whole-20261120-r2/plan.json)共 393/724 个已接计量、331 个待接，功能配置和构建锁不变。不读取历史观测作为计时；从本次功能记录和原件重建、验证固定帧组，解码不挂原件；每轮记录独立方向进程，分开计费、原生、进程与验证后耐久时钟。SElf* 按整列保持原生 add/finish 或 read-next/drain 次序，不将增量路径视为批 ABI。

[ETTh1 四路预检](../../results/m3-in-run-whole-20261120-r2/etth1-audit.json)复算 32 次独立方向试验（8 预热、24 测量）；不是这四条路线 92 个决定均已实测。剩余 17 条有适用决定的路线中，ZFP 92 个、Titchy 69 个、Zstd/XZ 85 个、CORAD 39 个、Sprintz 查询 23 个、Huff0 共享表 23 个。验收仍需一次冻结计划和一本完整账本；质量拒绝、失败和缺测应分别保留，而非计入通过样本。

第七版 `--measurement-zfp FIELD OBSERVER ARRAY --measurement-zfp-cpus CPU1 CPU2` 将 ZFP 的 `field-baseline`、`field-modes`、`openmp-encode`、`fixed-rate-array` 接入主账本，每路 23 个适用决定。[冻结计划](../../results/m3-in-run-zfp-20261120-r1/plan.json)达到 485/724 个已接计量，剩余 239 个。复用 Unique 冻结本机库及已有文件隔离控制器；可逆场按当前功能行验证全列原始位、逐帧字节，并为串行、OpenMP 1 和 OpenMP 2 使用一致的双物理核预算。线程参与情况来自独立同工作量观察进程，不把插桩结果混入主时钟。定率数组按旧合同的平衡窗记录原生修改、初始和更新状态分别重开；质量拒绝仍单列诊断时钟，不能作为通过样本，也不把窗口当成整列恢复。

[ETTh1 与 Bitcoin 1 的定向预检](../../results/m3-in-run-zfp-20261120-r1/zfp-preflight-audit.json)核对 8 个决定、104 个计量方向进程（26 预热、78 测量），另有 12 个不计时的线程观察进程。7 个决定通过质量，Bitcoin 1 的定率数组有 1/2 个窗口拒绝，三类操作的 12 个方向进程只记录诊断。在两输入的独立 `omp2` 编码观察中，分别有 7 列和 1 列实见两线程执行块工作；这不是每个计时进程的线程观测。该预检不授系统级独占或正式性能资格。

### 第八版：Titchy 原生包流与两条文件访问路线

[第八版计划](../../results/m3-in-run-titchy-20261120-r1/plan.json)增加 `packet-stream`、`loaded-file-access`、`batch-range`，每路 23 个适用决定。三路复用锁定的 C11 库，但保持原生接口与计量边界：包流首包延迟与整程分列，加载后查询按打开及点/位/范围分别记录，无状态范围不复用加载状态；两条访问路线的完整恢复仅用于独立核验，不代替查询计时。每个决定一轮预热、三轮计量，每轮两个方向。固定产物从本次功能决定和锁定的源数据核对，不读历史账本。

[ETTh1 与 ETTm1 同账本预检](../../results/m3-in-run-titchy-20261120-r1/preflight-measurement-audit.json)复算一致：6 个决定，48 个方向试验（12 预热、36 计量）。ETTm1 两条访问路线均验证每列 `[65536,69680)` 尾组；包流首包正时钟受原生编码总时钟约束。`loaded-file-access` 的回调计数是请求字节，实际文件读取字节保持 `null`，不从回调量推断。该预检不授正式资格。

### 第九版：Zstd 字典训练、留出编码与独立恢复

[第九版计划](../../results/m3-in-run-zstd-dictionary-20261120-r3/plan.json)仅扩充计量绑定，保留第八版功能矩阵、Huff0 对照与 CORAD 修订。新增 23 个 `zstd-dictionary` 决定，累计 577/724。每轮分别独立启动 `train`、`encode`、`decode`，按例冻结随机次序，一轮预热、三轮计量。训练只挂载冻结前缀，编码挂载留出数据和固定字典；恢复只挂载同一运行核验的 ZDG1 和字典。原生组帧成本、监督进程成本、从原件或固定产物到核验及同步的成本分列。ZDG1 包装与序列化字典分别记账，字典在完整留出恢复中只计一次；留出值不反馈选参。

[公开入口预检](../../results/m3-in-run-zstd-dictionary-20261120-r3/preflight/1fe333c79b464d71873a4dc0d7feff9f/report.json)核对 ETTh1 的标准训练窗口与 Economics-17 的短窗口，两项功能和计量终态均通过，共 24 个独立禁网操作试验（6 预热、18 计量）。固定归档分别覆盖 3 个、1 个原生帧，不使用 r40 产物或时钟。[主账本计量审计](../../results/m3-in-run-zstd-dictionary-20261120-r3/preflight-measurement-audit.json)从同一次运行复算。

### 第十版：Zstd/XZ 原生会话与匹配 worker 计量

[第十版计划](../../results/m3-in-run-lzbench-20261120-r1/plan.json)新增 `zstd-session`、`xz-session` 各 23 项，`zstd-workers` 7 项、`xz-workers` 9 项，共 62 项，未触发条件的 30 项不生成试验。均为完整 V 对象；编码逐试验重开锁定原件，恢复仅挂载固定帧。会话每方向连续一个原生 session，首输出驱动钟不代替完整操作。Zstd `workers=0/2` 编码各有固定帧，两路各自用零后台 worker 恢复；XZ 同步块、一个 worker、两个 workers 的恢复均用两个 workers 生成的同一帧。计时按独立操作进程分样本，不把调用或 XZ worker 的重新进入钩子次数当额外样本、实际块数或线程数。

[ETTh1 与 Weather 主账本预检](../../results/m3-in-run-lzbench-20261120-r1/preflight-measurement-audit.json)独立复算 72 个通过试验（18 预热、54 计量）和 2 个条件未触发决定。Weather 的 Zstd 两种编码配置实见 0/2 个后台 worker，两种恢复均为 0；XZ 同步、1、2 worker 三路的两个方向均实见 0/1/2。匹配组全部共享三颗同 NUMA 节点的物理核预算，普通会话用独立的单 CPU 亲和预算；仍不等同系统级独占。

### 第十一版：Sprintz 整文件压缩域查询

[第十一版计划](../../results/m3-in-run-sprintz-query-20261120-r2/plan.json)增加 `query` 的 23 个适用决定，执行整文件 SFB1 编码、独立恢复和原生查询。固定归档从本次功能帧摘要重建，在整列边界划分每组不超过 6 MiB 的运输文件；没有二次切分原生帧，没有将运输组当独立 session 或样本。以锁定原件重建四路 `u16` 位片约简 oracle，不把位片结果当 f64 约简。`upstream_simd` 与 `scalar` 在同一进程、同一次归档读取中分开计原生调用，无可观测的单后端进程路径则不填值。

[ETTh1 与 Electricity 主账本预检](../../results/m3-in-run-sprintz-query-20261120-r2/preflight-measurement-audit.json)复算 24 个试验（6 预热、18 计量）；Electricity 完整验证 1,284 帧、27,054,500 B 产物，五个运输组跨越旧单文件诊断上限。不将历史留样、旧上限下的缺项或该预检代替正式全量。

### 第十二版：Huff0 ETB1 两种原生共享表配置

[第十二版计划](../../results/m3-in-run-huff0-table-20261120-r1/plan.json)接入 `huff0-shared-table` 23 个决定。每个决定在相同训练前缀和留出范围执行 1X/4X 两组 `train`、`encode`、`decode`；一轮预热、三轮计量，按例配对随机次序。训练子进程只挂载冻结前缀，留出编码含锁定原件的独立入料，恢复只挂载同一次运行重建并核验的表与完整有序块，验证独立 SHA 模型—块绑定。表生成/加载时间与块操作时间分列；分组只约束运输文件大小，不重建 codec 上下文、不额外载入表。表、绑定、块头、载荷四类字节非重叠计费。

[ETTh1 与 Economics-17 预检复算](../../results/m3-in-run-huff0-table-20261120-r1/preflight-measurement-audit.json)覆盖 1X/4X 各自的多块留出与单块尾部，共 48 个独立禁网操作（12 预热、36 计量），均通过。仅 CORAD 39 个适用决定尚缺同运行计量接入；阶段全量尚未执行。

### 第十三版：CORAD 推理与两种原生训练

[第十三版计划 r2](../../results/m3-in-run-corad-20261120-r2/plan.json)接入 `corad-inference`、`corad-c-training`、`corad-source-training`，每路 13 个适用决定。冻结分母仍为 828：724 已排程、74 域外、30 条件未触发；专项义务和功能构建锁不变。前一尝试 r1 误把小数吞吐率送入整型观测汇总，未封账；r2 将率与整数计量分开并保留原目录。

计量由本次运行的冻结训练组、模型及留出帧驱动：C11 定种训练逐字节对照同次模型，Source 保留原有随机源，只计原始 `DictionaryLearning.fit` 的调用时间，另记原生模型打包；逐轮核对训练矩阵摘要、模型数组和序列化成本，重复训练的模型不替换推理使用的冻结模型。恢复子进程只挂 CRD1 帧，不挂原值或外置模型。每个方向一轮预热、三轮计量，整决定为样本，组和帧是轮内工作单元；原件解析与组物化在试验外，不作源文件端到端申报。

[ETTh1 与 Weather 禁网预检](../../results/m3-in-run-corad-20261120-r2/preflight-measurement-audit.json)复算六个决定、32 个独立方向试验（8 预热、24 计量）及其 208 个子进程记录。六个决定均为 `measured_quality_rejected`，其中训练决定保留其留出质量终态，并非训练进程报错。ETTh1 每生产方 1 帧拒绝；Weather 每生产方 9 帧中 3 通过、6 拒绝。计量和产物核验完成，但没有合格性能样本；这不是 39 个 CORAD 决定或 724 个适用决定的全量实测。

### 第十四版：CORAD 留出编码的原件到产物计时

[第十四版计划](../../results/m3-in-run-corad-raw-encode-20261120-r1/plan.json)由公共入口 `--measurement-corad-raw-encode` 冻结，只扩展 CORAD 推理的编码时钟，不改 v13 的功能配置、构建、分母或历史记录。每个编码试验重新穷尽执行一次冻结原件解析与 SHA 核验，按源轴及 V 的绝对行范围复核已验证留出片段。C11 与 Source 两个生产方共用这次输入读取，但各自执行相应冻结模型的编码；共享总墙钟从原件读取量到两方产物验证、同步及证据发布完成。原生调用、原件解析及总墙钟分别报告；总吞吐的逻辑字节明确为两方实际消费量之和，不是两方的独立端到端对照。训练时钟保持已准备的训练矩阵口径，恢复仍只挂载 CRD1 帧，无原件 ingress 计时。

ETTh1 与 Weather 已核对原件重新物化分别命中 1、9 个唯一留出跨度，并逐字节匹配同次功能材料。测试覆盖重复生产方去重、批边界、篡改原件、训练区误入和 ingress 失败后不启动原生操作。这里只验证输入链与计划，v14 禁网方向计量尚未执行；不与正在运行的 v13 全量诊断争抢计量资源。

### 正式主测的资源证据边界

本阶段的公开计量预检只使用同 UID 协作锁和 CPU 亲和性，不能开具正式独占收据。正式计划冻结前，按设计 §12.6 与项目目标 §4 绑定可审计的宿主资源预留：记录测量与后台集合、物理核心及 SMT 同胞、NUMA 策略、单线程与多线程配置的预算和实际线程；专用主机也须有预留记录，不能只用空闲率或命令行参数推断独占。各匹配对照使用相同预算，指定恢复、校验或调度工作是否在测量边界内；不得将原生 worker 或 SIMD 禁用后冒充算法原生模式。剖析、构建与无关的功能验证不在正式测量窗口并发运行。

封账时同时保留预留有效区间、实际亲和/迁移和环境干扰观测，说明权限不足与不可观测项。若资源预留或预冻结的干扰检查无法核验，则结果只作诊断；确认干扰后按预冻结规则整轮匹配重跑，保留原观测，不挑选单个 codec 的最好样本。本机本轮仅从应用进程作用域看到只读 cgroup 视图、CPU 4 的 SMT 同胞为 5，未核实宿主级隔离；未调整系统配置或重标历史运行。

已用 [宿主资源探针](../../tools/probe_m3_host_reservation.py)从当前启动环境读取 [cgroup v2 快照](../../results/m3-primary-full-v13-20261120-r1/host-probe-controller.json)。v13 的单核、ZFP 双核与 Zstd/XZ 三核预算合计使用逻辑 CPU 4、6、8、10；物理核预留还应约束 SMT 同胞 5、7、9、11。当前根隔离集合为空，启动进程未观测到有效隔离分区；探针只读，不检查预留有效期、分区内其他任务、IRQ、运行时迁移或干扰，因此即使单点快照通过也不自动授予正式性能资格。

已用 v13 r2 一次提交[完整主账本诊断运行](../../results/m3-primary-full-v13-20261120-r1/6676d9e3459b40f993fa5351cdfaa351/ledger.jsonl)，无路线、数据集或数量过滤。记录仍按同一 `run_id` 追加；封账后同时复算计量账本和 186 项专项义务。此次用于验证全分母执行与原始证据，不代替具备独占和干扰合同的正式主测。

执行中用 `tools/check_m3_live_ledger.py --plan PLAN --run RUN --pick DATASET ROUTE` 只读抽查已写完的记录；固定打开时的账本长度，检查完整行和冻结顺序，不将正在写入的尾行视为终态。[首次抽查](../../results/m3-primary-full-v13-20261120-r1/live-spot-check-r1.json)用同一计量复算器检查 ETTm2 的 ALP 双后端、ETTh1 的 pcodec C NativeAuto 和 Source 页路线，共 28 个方向试验（7 预热、21 计量）。该工具不接管运行、不处理账本尾部义务、不核验封存，也不会修改汇总或授予资格。

新全量运行封账后，用 `tools/audit_m3_primary_closeout.py --plan PLAN --run RUN --out CLOSEOUT` 从同一封印独立复算；用 `--verify CLOSEOUT` 检查派生结果。它在生成汇总前联查功能、计量和专项义务，强制保留 724/74/30 个决定及 180/6 项义务的完整分母；预检、未封账和减分母计划均拒绝。质量拒绝的计量、功能失败导致的缺测及计量自身失败分栏，保留原因；本工具不授正式性能资格，也不代替完整留样复解。

ZFP 封账留样可用 `tools/verify_m3_zfp_full_ledger.py --plan PLAN --run RUN --out AUDIT --isolate-corpus` 做禁网复解。它复用封账计划指定的语料控制器和 `libzfp_native_c.so`，对每个留样帧启动独立的 Bubblewrap 进程，只读挂载该帧；核对恢复值、形状、数组对齐率、日志摘要和进程会话。数组的更新前、更新后帧分两次重开。该复解不是全窗重放或计量；未指定此选项时维持旧审计口径，不能把历史语料复解标为禁网。

固定率数组另有全窗复解入口 `tools/verify_m3_zfp_array_anchors.py --plan PLAN --run RUN --out AUDIT`。它从同一封账按 23 个文件逐项读取初始及更新后的分组锚点，以两次新的禁网进程各只挂载一份锚点。原值只由父进程用于逐窗误差、恢复摘要和未修改块的复算，不重新编码或更改阈值。计量缺测且无锚点的项明确保留，不计入已复解窗口；原生复解成功不改变质量拒绝或测量失败终态，也不采纳复解时钟为计量样本。

`tools/audit_m3_primary_retained_replay.py --plan PLAN --run RUN --proof AUDIT ... --out COVERAGE` 复查同一封印下的实体留样与各原生复解报告。新版 ZFP 报告必须绑定计划里的控制器、原生库和隔离启动器，并为每个留样帧给出不同的进程会话、唯一只读帧挂载、实际形状及数组的有效率；元数据可计入已校验文件，但不算作禁网进程输入。旧版 ZFP 语料审计仍不视为禁网，不能与新版重复计数。没有成功恢复的留样继续列为未覆盖；分组计量锚点、专项和外部重建产物不计入这份实体留样覆盖。

### 新版 M3 / M4 退出证据对账

[退出证据审计 r2](../../results/m3-real-r40-20261120/current-exit-audit-20261120-r2.json) 绑定唯一 r40 主账本的计划及封账、M0–M2 前置收据、两类换输入运行、r12 覆盖清单和 M4 成本对照 v2，保留[审计 r1](../../results/m3-real-r40-20261120/current-exit-audit-20261120-r1.json)原件。在 724 个适用决定中保留 49 个未通过（45 质量拒绝、4 原生失败）；180 项必需义务中保留 1 项 CORAD 留出拒绝，ALP 的 AVX512BW 条件仍为 `pending_supported_runtime`。合成换输入 12 项通过；独立 NOAA 换输入 12 项有执行和验证证据，11 项通过，PBEPLA-RR 不在后者的通过数中。675 个通过决定的两类完整范围诊断仅证明 r40 诊断覆盖，不能替代新正式主运行。M4 三类代表成本及 1,008 次多尺度 ABI 方向试验单独复算，不补主账本计时、不授予阶段资格。

已用 `tools/audit_current_m3_m4.py --plan PLAN --run RUN --inventory INVENTORY --switch SWITCH_PLAN SWITCH_RUN --switch SWITCH_PLAN SWITCH_RUN --m4-cost COST --verify AUDIT` 独立复算审计 r2，结果一致。M3 与 M4 都未签发新版阶段收据。
