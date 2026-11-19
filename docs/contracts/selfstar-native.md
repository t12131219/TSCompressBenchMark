# SElf*（selection 4）：顺序批处理与原生逐值块

锁定 `elf-selfstar-native/unique-v1` 归档 SHA-256
`0febcf79b0a42c1c58b042478ff476b2fcafbdfe4de5b1abc2e60c34839ba355`。
`fix_ReWrite/elf-selfstar-native/FUNCTIONAL_REPORT.md` 与归档成员一致。
[发布验证](../../third_party/provenance/elf-selfstar-native/unique-validation.json) 记录 `stress`、`live`
历史通过；隔离实跑条目只列 `stress`。复用同版事实，不重跑 Unique 全套，不由测试名称推断首产出。
当前绑定 C11 `selfstar_c`、算法 ID `SF_SELF_STAR=3`。ELF、Elf+ 和 Elf* 是同源不同 ID，
本适配不把这些选择或其状态语义算给 SElf*。

## `selfstar-batch`：保留 Unique 的 512 值边界

- V-only，单列连续 f32/f64，little-endian，非空、无 validity、`FE_TONEAREST`；逻辑输入上限
  64 MiB，schema 上限 64 KiB。±0、无穷和 subnormal 保留位模式；输入 NaN 被拒绝，不自动做 mask
  或有损改写。此插件选项固定 `{}`，原生 `1..1000` 值/块的边界另以直接调用验证。
- 每个对象新建一个定向 `sf_c` 上下文（编码、解码分别建），用 `sf_c_encode` / `sf_c_decode`
  依次处理每 512 个值与短尾，**不在块间 reset**；批路径不跨对象共享学习状态。
  这与所选归档 `tools/bench.c` 的块边界及同向 context 复用一致。接入编译保留同一 C11 源码、
  `-ffp-contract=off -fno-fast-math` 与 libm，不引入原工程与 pcodec 同名的 `bench_c` 目标。
- 序列化为 `BMKSEL` v1 的 32 字节封装和 schema，加按序排列的 `u32le bit_length`、
  `ceil(bit_length/8)` 个 native 字节。格式版本绑定算法与 512 值边界，dtype、对象 count 决定
  各块值数；单独的裸 native 块不是完整对象。计费分别记录完整封装、块头、native 字节及有效 bit；
  不省略末字节填充。只有固定 v1 边界，本轮不提供任意块目录、随机访问、模型外部快照或其他格式译码。

## 原生 live、状态与独立恢复

`sf_c_begin` 绑定调用者缓冲，`sf_c_add` 会实际写位，SElf* 的 `deferred_values=0`；
`sf_c_finish` 写终止符、关闭该块并更新学习状态。`sf_c_read_begin` 需要完整的不可变块与
已知字宽、count 和有效 bit；`sf_c_next` 产出值后仍需继续读到 `has_value=0`，才消耗终止符
并进入可读取下一块的状态。定向用例另取 `finish` 前缓冲快照：在已有正确历史、已知 bit 长和
count 时，测试能暂读样本，但消耗终止符失败，无法完成该块或推进到下一块。**写入位数、暂读值、
完整块可消费是三个不同边界**；没有可追加的 reader，不把该结果称为低首值延迟或网络流吞吐成绩。

[用例清单](../../configs/suites/dev_selfstar_v1/cases.json) 绑定 f32/f64 的单值、恰好 512 值、跨块合成输入和
v2 气象 `co2` 测试分区首 1,543 个 f64 值（512+512+512+7；真实文件不做精度转换）。
[验证器](../../tests/isolation/selfstar_control.py) 用同一冻结库直接调用，逐字节核对 9 个 ABI
产物与直接构造的封装；删除暂存数据和 schema 后，由新 worker 和独立 C 库 reader 进程分别逐位恢复。
同一顺序中交替调用 batch 和 live，10 块的 bit 长、编码字节和恢复位一致；验 1/1000 值及短尾、
静默和信号 NaN、单次或累计超过 1000 值、容量不足后 reset。71 个异常产物、7 个非法 worker 请求
按预期拒绝且不留下产物。异常测试不构成任意外部码流的安全保证。

5 条多块序列验证 reset 后重编码一致、无原始数据从头回放恢复；把第二块当成首块均失败。
这不是所有乱序都必然拒绝或任意块能自证历史。气象例恢复第二块前需重放首块 512 值，
对应 748 native 字节和 4 字节块头，不含对象封装与 schema；没有原生跳转或检查点序列化入口。

运行 `ctest --test-dir <build> -R tsbench.worker.selfstar-batch.ordered --output-on-failure`。
`selfstar-control.json` 绑定实际构建、用例、产物哈希、拒绝原因、可观察输出与回放成本。
原生逐值路线仍为直调开发诊断，未接通框架 stream 服务；**无正式时间样本或阶段资格**。

## 统一预检与复算

统一预检绑定两组 9 项必需检查，留存 9 份批封装、5 份未 finish 前缀、5 份新上下文编码的第二块、
2 份原生 1000 值块及 1 份气象原值，共 22 份、99,751 字节。复算核对原始窗口及逐块恢复摘要、
BMKSEL 长度与 padding、有效位前缀、学习状态对照、终止符消费前后的阶段和实际回放字节。
离线复算不再执行 SElf* 解码；新进程逐位恢复是原运行证据。`incremental_state_bounds` 的开发用例
检查零延后值、调用者提供的 workspace、累加计数上限与超限后状态，不把它当成运行库 heap/RSS 的测量。
详见[统一报告](../../results/m0-selfstar-native-bindings-20261119-r1/native-report.json)与
[负向复算](../../results/m0-selfstar-native-bindings-20261119-r1/selfstar-verifier-negative.json)。

## `extended-v6`：同一执行账本与脱离来源的复验

在[统一执行器](linear-batch-execution.md)中新增两个已冻结的候选操作组，不更改 `selfstar_c` 库源码、归档或算法 ID。批路线用原 ABI 插件调用 `sf_c_encode/sf_c_decode`；原生逐值路线通过[直接 driver](../../plugins/codecs/selfstar-batch/ordered_control.cpp)调用 `sf_c_begin/add/finish/read_begin/next`，恢复不加载批插件。二者各自实际执行并分别保留完整 `BMKSEL` 对象，不互用产物。直接 driver 由 C++ 编写，只是控制层，调用同一个冻结 C11 库。

- 批与逐值各 9 个 f32/f64 对象；同一输入上的两个封装逐字节一致，每个对象都与一次 `sf_c_encode` 直接调用核对。保留负零、subnormal、Inf 和短尾。批路线核验 7 项输入拒绝；两个 1,591 值对象各实跑 7 个变造帧拒绝。
- 跨块对象从首块重放并核对 reset 后字节和原位型；从新上下文直接读取第二块拒绝。气象数据的 `512+512+512+7` 中，读取第二块前须重放首块 512 值、748 个原生字节及 4 个块头字节。选定第二块截于 `finish` 之前时可暂读 512 值，消耗终止符失败且下一次读取报告失败状态；按已完成块重新回放恢复。这不意味着任意乱序都会拒绝，也不提供索引、在线网络流或外部状态快照。
- 两种字宽分别验证 1,000 值原生上限、超过上限、空块、NaN、单字节 workspace 容量失败和 reset 后恢复；该容量探针不是进程 RSS 实测。1,000 值边界在控制调用内验证，不把它误计为另一个已封存产品。解码以 `has_value=0` 为完成条件，而不是以最后一个值出现为准。

2026-11-19 的[主报告](../../results/m0-ordered-selfstar-20261119-r1/report.json)来自一个冻结计划和主账本。[恢复审计](../../results/m0-ordered-selfstar-20261119-r1/restore.json)不挂载原输入、原源码和原构建，实际重跑全部 18 个 SElf* 产物的解码、直接批对照、适用的状态/容量和坏帧检查；报告逐字节复算。[绑定负检](../../results/m0-ordered-selfstar-20261119-r1/controls.json)确认不能用批插件替换逐值 driver。只授本轮候选证据，不等同正式资格或计时成绩。
