# Sprintz 原生移植验收报告（2026-10-17）

四个主算法 Sprintz-Delta、Sprintz-FIRE、Delta+Huffman、FIRE+Huffman，
以及安全 API 中的强制general/lowdim、仅bitpack、Delta去RLE和8位FIRE去RLE，
完成 V3.0 §114 限定原生移植验收。源码原本就是 C++，采用 NATIVE_PORT，
未把直接复用原生核心称为重新翻译。说明标签：
`NATIVE_PORT_QUALIFIED(linux-x86_64-u8/u16-ndims1..128-max64KiB-API-v1)`。

本结论只适用于冻结合同和矩阵范围；未签 REWRITE_DONE、完整上游
FULL_PARITY、Benchmark 接入、BENCHMARK_READY 或 FORMAL。具体身份及源码映射
见 MATRICES.json、SOURCE_TO_PORT_MAP.json、Source/SOURCE_MANIFEST.json。

## 来源和修复

主核心：dblalock/sprintz，commit `a056cdb67d049669875ab5487359aca99ae873ea`。
作者配套基准：dblalock/lzbench，commit
`580c4f085381f31b1ad669525ed04e63cbc385f3`。
两个仓库的核心同名顶层文件中只有 online.cpp 不同，两个原件均保存。
Huffman 组合来自配套包装层，真正熵编码是 Huff0；entropy.cpp 是未完成的
kayak 实验。Apache/BSD 原有声明、lzbench GPL 程序上下文及 oracle 角色分开保存。

原件未应用补丁。可重放 native-safety.patch 及本地所有权层修复：

- 低维解码 header 的8字节展开写入超出原分配；16位general header向量读取范围不足。
- 原生 scratch 宽读取需要真实、初始化的后缀，而不是忽略 sanitizer 报告。
- 标量 zigzag 负数左移、FIRE乘法有符号溢出；使用无符号位运算与显式modulo32。
- 历史1D helper从8字节栈对象读16字节；改为真实8字节加载。
- 历史1D符号提取的带符号左移/宽度0右移，改为明确定义的位模式提取。
- 原生 malloc/calloc 未检查；增加线程本地跟踪、异常安全回收和故障注入。
- 16位返回值截断奇数末字节；独立raw接口按完整格式扫描计算长度。

Huffman 的作者 `reported_elements*2+1` 规则保留，包括偶数长度时的零填充。
未修改原版探针36例中4例恢复失败；完整差分774例中52例属于原版raw16
长度截断。补回原生已写出的未计入字节后，与移植输出逐字节一致；移植输出
可由未修改原版解码器恢复。原版已经截断的无效流由安全API拒绝，不能把它
计为 source->port 通过。其余722例原版字节一致并双向恢复；Huffman配置均一致。

## 当前执行证据

| 验证 | 实际结果 | 主要证据 |
|---|---|---|
| 全部维度1..128、8/16位、四组合、路径、空/短/尾块、零/斜坡/随机 | 80,448例通过 | final-api-cases.log |
| 未修改原版差分、双向解码和完整字节比较 | 774例；52例明确为源raw16截断修复 | differential.json |
| GCC11.4 / Clang14构建、接口及差分 | 通过 | final-*-build.log、clang-test.log、clang-differential.json |
| 共享 canonical 整数值 | 18份冻结payload、72例通过 | canonical.json、canonical_manifest.json |
| national_illness 原始整数计数 | 12配置精确恢复 | real-data.json、real_manifest.json |
| 畸形/截断/随机变异 | 27,218例，无越界；失败输出不变 | sanitizer-negative.log |
| 原生分配失败 | 2,334次注入，无泄漏，错误输出不变 | sanitizer-negative.log |
| 最大输入64KiB、长RLE/随机、边界参数、实际长度减一容量 | 404个最大输入用例及额外容量/参数断言通过 | test_negative.cpp、final-*-negative.log |
| ASan+UBSan+LSan | 通过，无禁用检查类别 | final-sanitizers.json |
| ThreadSanitizer / 4线程独立调用、重叠/非对齐缓冲区 | 通过 | tsan-test.log |
| 带覆盖率 libFuzzer | 50,000次通过 | fuzz.log |
| 历史1D及预测器/原地恢复研究入口 | 342原版/移植往返；81个sanitizer诊断通过 | experimental*.json |
| 冷解码（仅压缩流、配置、程序和库） | 30配置通过 | cold-decode.json、tests/golden |
| 安装后C11消费 | shared/static均通过 | install-consumer.json |
| 临时目录无网络重建、补丁重放、原版oracle、冻结数据 | 通过 | offline-final.json |
| 独立API时间/字节数 | 8配置，单独协议，非FORMAL | performance.json |

canonical 的 Sprintz 专用数据是合成数据，没有将其标成真实语料。真实数据
选取 AGE0-4、AGE5-24、provider 三个原始整数计数列，逐值检查0..65535后写入
u16 little-endian，不做浮点量化；未宣称压缩整个CSV、时间戳、ILI比例或其它列。
离线重放使用带hash的冻结提取，不依赖原始语料路径或 Benchmark Python。

## N0–N5

| Gate | 本次范围结论 | 证据 |
|---|---|---|
| N0 | PASS：原生C++、四稳定ID、去重、完整源inventory与目标范围分开 | SOURCE_CAPABILITY_INVENTORY.json、LZBENCH_REGISTRATIONS.json、MATRICES.json |
| N1 | PASS：冻结原件、许可证上下文、源闭包、未修改baseline及recipe | SOURCE_MANIFEST.json、oracle_extraction.json、baseline-build-final.log |
| N2 | PASS：实现前冻结输入/格式/状态/失败/资源/测试计划 | CONTRACT.md；实际修复偏差在本报告及patch中追加 |
| N3 | PASS：限定安全C ABI、容量/所有权/独立恢复/故障和sanitizer | public header、FORMAT_AND_SAFETY.md、final-sanitizers.json |
| N4 | PASS：原版差分、强制路径、真实整数、跨编译器 | differential*.json、real-data.json、canonical.json |
| N5 | PASS：可安装库/API/CLI、SBOM、hash、离线恢复与包闭包 | SBOM.json、EVIDENCE_INDEX.json、PACKAGE_INDEX.json、离线及包外审计 |

## 保留的限制与未签署能力

公开安全API仅限定Linux x86_64、上述ISA、8/16位整数、ndims1..128和64KiB。
更宽源签名、非AVX机器、ARM、大端、GPU、内部并行、流式和浮点量化未取得资格。
基线ISA入口与AVX dispatch分开，CPUID检查及反汇编均核验；未在非AVX模拟器实测。
原生packed scalar视图采用GCC/Clang aligned(1),may_alias扩展；不是ISO-only跨平台声明。

预测器/原地恢复和历史1D代码保留并修复了本次发现的UB，研究驱动通过所列样本，
但未提供各历史格式的完整不可信码流安全ABI。query仅有构建和单个materialize
探针，未验证完整SUM/MAX结果合同。FSE/Zstd/Bzip2组合仅登记源码，不纳入四个锁定ID。
这些项目不被改标为不存在，也不以主接口通过替代其完整源能力验收。

raw输出不是自描述frame。恢复需要相同配置和expected_bytes；sidecar实际字节与
native payload分别列账，golden的full_recovery_bits包含二者。安全结构检查不提供
内容认证；结构合法的修改可能成功解码。原始问题/初期构建失败/沙箱LSan的ptrace
日志作为历史证据保留，当前PASS由final索引所指向的新执行记录支撑。
