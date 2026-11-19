# Huff0（selection 29）：独立帧与共享熵表

锁定 `FiniteStateEntropy/unique-v1` SHA-256
`10fd2afb4c8cab1983fd19b148f58b2cd9632831a0a9c1b57d850ff417299055`，使用共享库
`reference` 中的 `Algorithm::Huff=2`，不把 FSE/ZLIBH 的路线归给 Huff0。
`fix_ReWrite/FiniteStateEntropy/FUNCTIONAL_REPORT.md` 与冻结归档内文件逐字节一致；
[发布验证](../../third_party/provenance/FiniteStateEntropy/unique-validation.json) 记录
`test_features` 历史和隔离 PASS，本轮不重跑 Unique 全套。
旧基线条目写 `DYNAMIC_BMI2=0`；同一归档实际 CMake 默认 `ENTROPY_DYNAMIC_BMI2=ON`。
不改写历史，开发默认路线采用冻结包的 ON；显式 `OFF` 为另一个二进制构建身份，不是运行时调参。

| 操作组 | 入口和归因 | 产物与恢复依赖 |
|---|---|---|
| `huff0-reference` | `Codec(Huff).encode(..., true)` 与 `decode`；每 32 KiB 独立块，尾块单独处理。native 按内容实际写 raw/RLE/Huffman 三种记录；其中 Huffman 固定由 `HUF_compress2` 写 4X，不提供 FEC1 1X 参数。 | `FEC1` 24 字节帧头、每块 13 字节记录头（含 CRC32）、native payload；TSBench `BMKHUF` v1 外层 32 字节加 schema 计入总量。没有外置模型。 |
| `huff0-shared-table` | `TableCodec(Huff, train, 0, streams)` 用 `1..32768` 训练字节、add-one 全符号计数。分别序列化 1X 和 4X 资产，重载并复用 CTable/DTable。训练、加载和块编解码是不同生命周期。 | `ETB1` 模型与每块 9 字节头及数据分开计费。块不携带模型身份或 CRC；必须按 SHA-256 绑定模型。区分按块字节与含一次模型的总字节，不能把复用当成免费。 |

只有 FEC1 批路线已接入 `huff0-reference` ABI：V-only、单列连续 `u8`、无 validity、固定
选项 `{}`，支持空数组；逻辑上限 64 MiB，schema 上限 64 KiB。使用原生帧，不替换库内分块或
CRC；外层绑定 dtype/count/schema，核对 FEC1 完整记录，最终仍由 native 检查解码 CRC。
缓冲复制、前置检查与封装都是适配工作，不能从端到端成本中事后扣除。
ETB1 是原生直调开发诊断，尚未接成框架模型资产服务。

## 数据、独立恢复与拒绝

[用例清单](../../configs/suites/dev_huff0_v1/cases.json) 包含空、raw、RLE、混合帧和 v2 气象
`co2` 测试段。气象按冻结的 canonical little-endian f64 字节解释为 `u8`，不是原生浮点压缩。
训练只读取 train 首 4,096 值的 32,768 字节；held-out 首 4,103 值是 32,768+56 字节，
两者绑定独立分区 ID。训练接口不能取 test，原 M1 读取接口仍拒绝 train；越界请求拒绝。

- 5 个 FEC1 对象与直接调用字节一致；独立解析器逐块核对记录和原始 CRC。删除 staged 输入与
  schema 后由新 worker 精确恢复；28 个异常封装、块图或 CRC 拒绝。FEC1 CRC 不是认证，
  不把对结构和 CRC 的检查宣称为对任意外部码流的通用安全验证。
- ETB1 共 4 个 profile（两种流数 × 合成/真实划分）。加载序列化模型后在同一上下文编码多个块；
  删除训练输入和待测原值，新进程只用模型和块数据反序恢复 **14 块**，证明样本不依赖上一块。
  覆盖实际压缩、raw fallback、空块、单字节；拒绝缺模型、错误 stream 字段、截断 model/块。
  另一份同 profile 的合法模型由外层 SHA-256 契约拒绝，不指望 native header 替代身份检查。
  对 raw 块修改一个字节，native 仍返回数据，但独立原值校验失败，说明不能继承 FEC1 的 CRC。
- 气象 held-out 例的模型均为 52 字节，有效 `table_log=11`；计入模型和两个块头，1X/4X
  分别 18,417 和 18,433 字节。这是已定向实测的字节账，不是性能排名或泛化结论。

## 实际入口与 BMI2

[原生直调探针](../../tests/native/huff0_control.cpp) 仅在诊断进程拦截冻结库的公开 Huff 入口，
不更改参数，记录成功返回完整输出的 `HUF_decompress4X_hufOnly_wksp_bmi2`（FEC1）和
`HUF_decompress1X/4X_usingDTable_bmi2`（ETB1）调用及实传 BMI2 参数；ETB1 同时核对
对应 `HUF_compress1X/4X_usingCTable`。CPU 检测和编译开关单列，原始/重复记录不计 Huff 内核
工作。BMI2 是条件标量指令集扩展，1X/4X 是码流组织，不是 SIMD、硬件线程或性能样本。

本机默认构建中，FEC1、ETB1 1X、ETB1 4X 分别完成 **3、4、4** 次带 `bmi2=1` 的实调；
显式 portable 构建完成同样的调用数，参数全为 `0`。两种构建的 FEC1/封装、ETB1 模型和块字节
在这些用例上均一致，各自通过恢复。这不等于动态构建已在缺 BMI2 的主机上执行过。

## 统一预检绑定与复算边界

将原要求名 `fec1_1x_4x` 修订为 `fec1_fixed_4x_etb1_stream_boundary`：保留对 1X/4X 的验证，
但只在 ETB1 比较这两种组织，避免要求 FEC1 执行不存在的参数。两组共 **11 个必需检查**有开发用例绑定，
BMI2 比较继续作为独立的正式条件义务。

统一运行内封存五份 FEC1 封装、四份主模型、两份有效替代模型、十四份 ETB1 块和两份气象原值，
共 **27 份、290,075 字节**。复算从原值重建 FEC1 原始块 CRC、raw/RLE 内容及完整字节账，
检查 FEC1 的权重与 4X jump table，检查 ETB1 模型头、块长、实际入口、模型哈希及含模型的字节账。
恢复位级正确性由删除暂存输入后的新进程实测；离线复算核对该结果和码流结构，**不重新做 Huffman 解码**。
本次 [统一报告](../../results/m0-huff0-native-bindings-20261119-r1/native-report.json)、
[构建对照](../../results/m0-huff0-native-bindings-20261119-r1/huff0-build-comparison.json) 和
[负向复算](../../results/m0-huff0-native-bindings-20261119-r1/huff0-verifier-negative.json) 分开记录证据。

用 `ctest --test-dir <build> -R huff0.profiles --output-on-failure` 运行
[验证器](../../tests/isolation/huff0_control.py)；`huff0-control.json` 绑定构建、用例、模型、
字节及实调证据。如需单独复测 portable，在新的构建目录指定 `-DENTROPY_DYNAMIC_BMI2=OFF`，
构建目标 `tsbench_cpu_worker tsbench_huff0_reference tsbench_huff0_control`。**不授阶段或服务资格。**


### 在统一预检内复用实际产物的 portable 解码对照

主构建保持 `ENTROPY_DYNAMIC_BMI2=ON`，两边均使用 `Unix Makefiles`。如需构建第二份，只需在已激活的 `tsbench` 环境用独立目录生成
`tsbench_huff0_control` 及其依赖库；已有匹配构建可以直接复用。不用为对照重新编译全部 codec：

```sh
cmake -S . -B build/huff0-portable -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=ON -DENTROPY_DYNAMIC_BMI2=OFF -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"
cmake --build build/huff0-portable --target tsbench_huff0_control
```

对 `native-plan` 和 `native-run` 同时指定 `--huff0-portable-build build/huff0-portable`，仍只提交一份计划。
计划比对已解包源码摘要和两份 Unix Makefiles 的 Huff0 编译标志、链接命令：除根路径和预期 BMI2 宏外必须一致，
并锁定实际 portable 观察程序与 DSO 的哈希。它不会从历史 CTest 产物导入结果，也不是完整构建再现性证明。

portable 探针等待主 Huff0 探针通过，使用主探针同一次留下的 FEC1 原生载荷、ETB1 主模型及块，
在独立进程中解码，不传原始输入、不重新训练或编码。原帧及模型不重复留存；账本记录独立恢复摘要、
实际 native 调用及其 BMI2 参数。主探针未通过时不启动对照；portable 自身启动/执行失败也另记终态。
离线复算核对运行内的引用、摘要、实际调用数与恢复结果；不重做熵解码。该对照是功能与忠实性诊断，**不报告性能**。

[同次封存报告](../../results/m0-huff0-same-run-control-20261119-r2/native-report.json) 中，两边各实际完成 FEC1 4X /
ETB1 1X / ETB1 4X 共 3 / 4 / 4 次 Huff 解码；主构建实传 1，portable 实传 0。对照独立恢复 5 份 FEC1 载荷及
14 份 ETB1 块（配 4 个主模型）。这不等于在缺 BMI2 的主机上验证过动态构建，也不代表正式资格。

## `extended-v7`：同一执行计划中生成、验证并独立恢复

[执行政策](../../configs/suites/m3_first_batch_native_v2/entropy-batch-execution.json)将 #29 的两条路线加入原生执行候选，
与前 12 路线使用同一冻结计划、单次提交和一份主账本。按槽位冻结输入、ABI/工具、操作顺序、进程限额、留存上限及恢复闭包。
空构建使用锁定的 `unique-v1`，ABI 插件与独立直调工具使用同一 `libreference.so`；不导入 CTest 的产物或 PASS。

| 路线 | 同次执行验证 | 恢复与计费 |
|---|---|---|
| FEC1 `huff0-reference` | 5 份完整帧的 payload 与原生直调编码逐字节相同；覆盖空、raw、RLE、4X 混合与气象字节，包括两项 ABI 输入拒绝。检查每条 record 的 CRC、长度、分支和 4X jump table；实际运行坏帧拒绝。 | 原生 payload 与完整 ABI 帧用不同新进程解码，验证原位字节与 schema。计完整封装、schema、FEC1 头、record 头和各分支 body。 |
| ETB1 `huff0-shared-table` | 1X/4X 各有合成和按时间切分的气象 profile；训练、加载 CTable 编码、加载 DTable 解码分别运行。气象仅用冻结 train 分区首 4096 个 `co2` f64 的小端字节训练；held-out 独立取 4103 值。 | 4 模型、14 块；每个 profile 以一次加载反序恢复各块。计一次主模型、各块含 9 字节头的完整长度及必需的模型/块 SHA-256 绑定侧车。另计留存的四份 alternate 控制模型，不摊入主恢复产品。 |

FEC1 是独立字节帧、固定原生 4X。ETB1 的 1X/4X 是 Huffman 位流几何，不是线程数，也不是流式 API。真实 `co2` 路线将
规范化 f64 位串显式作为 u8，不能报告为原生 f64 模式。ETB1 块本身不携带模型 ID 或 CRC：同流数的替代模型可由原生
加载但不满足主产品的绑定；合成路线改写 raw 字节可通过原生解码，却无法通过原位字节 oracle。缺模型、坏模型头和坏块
长度另由原生进程拒绝。侧车由执行器在调用原生解码前检查，不声称是 ETB1 原生认证机制。

[联合报告](../../results/m0-huff0-unified-20261119-r2/report.json) run `0d6a25fb310c419199172a26ff51e612`：
131 槽、112 个产品独立恢复、19 项预期输入拒绝，14/36 组的 75 项必需义务有同次候选证据。Huff0 的 11 项必需义务在内；
直接工具实际观测到 FEC1 4X / ETB1 1X / ETB1 4X 分别 3 / 4 / 4 次解码且均传入 `bmi2=1`。本套件未绑定同次 portable
构建，不能引用上述独立开发对照来补本次的条件义务。[恢复审计](../../results/m0-huff0-unified-20261119-r2/restore.json)
只挂载封存运行及控制代码，不挂载原语料、原构建或项目配置；报告逐字节复算。[计划负测](../../results/m0-huff0-unified-20261119-r2/controls.json)
拒绝把 ETB1 driver 换成 FEC1 ABI、漏掉侧车预算；[产品重封存负测](../../results/m0-huff0-unified-20261119-r2/huff0-reseal.json)
拒绝替换模型、删除绑定、重签侧车后的 raw 数据变更及假报原生调用数。仍仅为开发候选，不授正式资格。

复跑（结果目录需为空）：

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --entropy
```

## `extended-v20`：在主账本绑定同次 BMI2／portable 对照

`batch-execution-plan --suite extended-v20 --huff0-portable-build <项目内独立构建目录>` 要求两套构建都来自锁定的
`FiniteStateEntropy/unique-v1`。计划核验解包成员摘要、主构建 ON／对照 OFF 及归一化编译和链接配方；比较过程中不修改原包
或重命名 SONAME。两个 `libreference.so` 各在自己的封存加载闭包，观察进程只挂载所选闭包；两套实际文件都列入共享解码器字节预算。

五个 FEC1 成功槽挂载同一份原生 payload，四个 ETB1 成功槽挂载各自同一份主模型和同一组块（共 14 块）；对照不挂载原值、训练样本或
替代模型，不重编码、不重训练，不额外收费一份帧。每对进程单独记录实际挂载摘要、终态和 Huff 调用。主解码输出经原位字节 oracle，
便携输出再与主输出逐字节相等。独立恢复重新执行两套解码，不引用历史诊断结果。1X/4X 仅表示码流组织，不是 SIMD、线程数或流接口。
CPU 不可用时须仍有合法的逐位恢复和 `bmi2=0` 调用证据；条件记为 `pending_supported_runtime`，不能以编译 ON 代替运行。

[同次禁网报告](../../results/m0-huff0-bmi2-unified-20261119-r1/report.json) run `9dcdf17300f0404abdf742b454f52a23`：
FEC1 4X、ETB1 1X、ETB1 4X 分别观察到 **3 / 4 / 4** 次原生调用，主构建传入 `1`、对照传入 `0`。
[独立恢复](../../results/m0-huff0-bmi2-unified-20261119-r1/restore.json)用两套封存闭包重跑全部九对，未挂载原构建或语料。
[重封存负测](../../results/m0-huff0-bmi2-unified-20261119-r1/huff0-reseal.json)拒绝以主 DSO 替换 portable DSO、
替换对照使用的熵表或块、以及伪报零次原生调用。这是功能候选证据，不授予计时或正式资格。

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --huff0-bmi2
```
