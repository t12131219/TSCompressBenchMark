# Gorilla / Prometheus XOR porting report

**REWRITE_DONE / FULL_PARITY**（冻结 XOR 对象；Linux amd64/AArch64 LP64）。
按 Compression_Algorithm_CPP_Porting_Standard_v3.0.md 完成独立交付。

## 来源、范围与路线

发现条目：Compression_Source_Code/Source_Code/ValueCompress/Gorilla，其 code
指向 prometheus_prometheus。锁定 revision 8374d30cb3fe705773bbac72d7015eba17480557。
算法核心实际为 Go 的 xor.go、bstream.go；它不是第三方已有 C++ Gorilla core。
TimeStampCompress 别名共享完整对象；不把 timestamp/value 拆开，不复制整个
Prometheus。XOR2、histogram、TSDB 系统容器及其它 Gorilla 格式为不同对象。

Gorilla 论文：https://doi.org/10.14778/2824032.2824078；算法合同以该源版本
为准。Prometheus 使用毫秒时间戳 14/17/20/64-bit DOD 桶，与论文秒级桶不同。
路线 SOURCE_REWRITE；方法 TRANSLATED；CompatibilityTarget BYTE_IDENTICAL，
比较完整 raw chunk；ObjectLevel P1_STANDALONE_CODEC。独立 slug
`gorilla-prometheus-xor`，implementation `gorilla-prometheus-xor-cpp-v1`。

## Closure、oracle、工具与许可

Source/SOURCE_MANIFEST.yaml 固定原始 source/audit 文件的 SHA-256；Go 核心
原样快照和原样编译。oracle bridge 仅提取 Chunk/Appender/Iterator 声明、提供
不被访问的 histogram opaque pointer types、导出只读 state trace；不提供替代
encoder/decoder。完整 Prometheus 依赖及官方 testify 测试套件未被编译；本次
执行的是锁定原始核心的独立 public-API driver 与双向 oracle。
Go 1.26.0 官方 archive hash 已验证、项目局部解包、GOPROXY=off，无核心补丁。
C++17 GNU 11.4.0；Clang 14.0.0 用于 analyzer/fuzzer；AArch64 GNU 11.4.0
和 QEMU 6.2.0 的发行版包验证 SHA-256 后局部解包，无系统安装。
源码翻译继承 Apache-2.0 AND BSD-2-Clause；Damian Gryski 2015/2016 和
Prometheus 作者版权、全文许可保留，工具/测试使用 Apache-2.0；SBOM.json
按文件/工具区分。文档规范、编译命令、环境/产物及许可证 hash 均绑定清单。

## 语义审计与机制映射

Go int/offset/capacity 在参考 linux/amd64 为 64 位；C++ count/index 用 checked
size_t，wire count 用 uint16，算术残差/位模式 uint64。所有 timestamp 加减、
DOD、zigzag 都明确 modulo 2^64；signed_bits 显式安全转回 int64。不会依赖
C++ signed overflow、负移位或 shift-by-64。Go 的 unsigned 超宽 shift/64-bit
mask 行为在 C++ 中以逐 bit/byte 安全路径重现；14/17/20-bit sign decoding
使用 `>` midpoint，保留特殊正边界。

输入一维 Sample(int64,uint64 bits)，alignment 合同显式；无按列假装原生
multivariate，无 int/float32 隐式 cast。值仅 XOR/memcpy，不作浮点运算；
NaN payload、signaling NaN、±Inf、±0、subnormal 都按位保留。rounding/FMA
不参与算法，禁止 fast-math，contraction off。原生 endian 不用于 wire；
header big-endian，payload MSB-first，varint 为源定义 base-128。

xorAppender.Append/bitRange/xorWrite → Encoder::append/put_value；
xorIterator.Next/Seek/xorRead → Iterator::next/seek/get_value；
bstream writes/reads → canonical bit loops 与 optimized byte batching。
优化路径含 regular timestamp+unchanged value 两零位 shortcut，实例计数证明
实际走优化；没有运行时 silent fallback。生成 expected 先于 C++ core。

## API、状态、计费及安全

公开 API/CLI 与 Bench 隔离，C++ typed Error exception、RAII、API v1；无 C ABI。
append/flush/compact/reacquire/reset/finalize 状态分离；样本上限 65535。
normal incremental/reacquire roundtrip，repeat-finalize 幂等、seal 后拒绝追加。
默认 Iterator 拷贝快照以保持 caller input 不变并安全并发；Borrowed mode
零拷贝，保留最后一字节副本；reset_owned 零拷贝转移 vector。借用内存需
caller 保证地址与生命周期，ownership 与 Go GC alias 的差异已显式记录。
没有 byte-fragment/backpressure、模型、字典、checksum 或随机访问索引。

Worst bound 2+ceil(157*N/8) 先做 checked 检查；buffer API bound-1 必拒绝，
失败不改 caller output。输入只读、typed natural alignment、raw 未对齐可用，
safe-overread=0；guard pages、canary、坏 width/length/varint/padding 和 fuzz
检验安全。源 raw Reset 会清空 free bits，部分字节结尾再追加有 upstream
恢复缺陷；literal 源行为保留并独立记录，不用修正版伪称源 parity。

header 16 + timestamp + value + padding = SerializedBits = raw bytes×8；
ExternalSideInformationBits=0；FinalBits=SerializedBits。批量测试 envelope
仅是驱动 framing，不是算法 chunk，也不充当解码必需的外部 side information。

## 验收证据与限制

validation_report.md 汇总 G0–G6；native_capability_validation_report.md 与矩阵
关闭全部 10 项 required。dataset_validation_report.md 给出 227 个 case 的
逐项 hash、大小与结论；六个 profiles/results.json 保存 fresh commands/binary
hashes、source/rewrite byte identity、四路恢复、每 append 的 state digest。
数据来自三份只读 CSV 的全列/全行；原始项目没有 datasets/ 目录，实际数据池
位于材料/TSBench_Corpus。无 UCR 标签或 TRAIN/TEST 合并，无训练/调参。

ASan/UBSan/LSan、TSan、Clang analyzer、100000 次 libFuzzer 均通过，独立
public API preflight 1051576 断言通过。AArch64 CLI/API 实际 QEMU 运行并与
amd64 编码双向互读；大端、386、Windows/macOS 与 AArch64 硬件/sanitizer
未验证、不开放。两个独立干净 Release 构建四个目标产物逐字节相同。
独立性能仅 QUALIFICATION：30 repetitions/5 warmups、固定 CPU affinity，
C++ E2E 与 Go NATIVE 并列记录，不签 FORMAL。未接入 Bench/registry/adapter。

发布源码、参考源码、goldens、canonical inputs、raw/cross-decoded artifacts、
原始日志、driver、build recipes 和 identities 保留；toolchain 缓存不作为 C++
生产依赖。后续改动依据依赖闭包重验，不能继承本次 PASS。
