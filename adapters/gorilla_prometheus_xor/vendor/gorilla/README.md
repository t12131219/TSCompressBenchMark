# Gorilla / Prometheus XOR C++17 独立重写

按《Compression Algorithm CPP Porting Standard v3.0》完成 G0–G6，状态
**REWRITE_DONE / FULL_PARITY**。范围：Prometheus EncXOR 完整 timestamp/value
chunk，Linux amd64 与 AArch64（QEMU user 运行验证）。

源码来自 `Compression_Source_Code/Source_Code/ValueCompress/Gorilla/code`，
锁定 prometheus/prometheus `8374d30cb3fe705773bbac72d7015eba17480557` 的
`tsdb/chunkenc/xor.go`、`bstream.go`；快照、独立 Go oracle 和工具链清单位于
`../../Source/gorilla-prometheus-xor`。这是 Prometheus 毫秒时间戳变体。

核心只依赖 C++17 标准库。支持 int64 时间戳与 binary64 原位模式、完整编解码、
增量追加、前向 Seek、reset、compact、finalize、并发独立句柄、迭代快照、
借用输入的零拷贝迭代，以及转移 vector 所有权的 reset。canonical 和 optimized
可强制选择，路径执行计数可查询；无 SIMD/GPU/内部并行。

## 构建和 API

```bash
cmake -S . -B build/local -DCMAKE_BUILD_TYPE=Release
cmake --build build/local -j2
ctest --test-dir build/local --output-on-failure
```

```cpp
#include <gorilla/gorilla.hpp>
std::vector<gorilla::Sample> x{{1000, gorilla::double_bits(1.25)},
                             {2000, gorilla::double_bits(1.25)}};
auto raw = gorilla::encode(x.data(), x.size(), gorilla::Path::Optimized);
auto restored = gorilla::decode(raw.data(), raw.size());

gorilla::Encoder encoder;
encoder.append(x[0]);
encoder.append(x[1]);
const auto& bytes = encoder.finalize();
const auto ledger = encoder.accounting();
```

生产恢复仅需要完整 raw chunk；首两字节是 big-endian uint16 样本数，最大 65535。
`Sample.value_bits` 避免浮点运算对 NaN payload 等的影响。公开 header 和
[contract.md](contract.md) 定义容量、所有权、错误、状态及 bitstream 合同。

CLI 输入 `GRI1`：4 字节 magic、LE uint32 chunk 数；每个 chunk 为 LE uint32
样本数及 N 个 LE int64 timestamp / uint64 value_bits。输出 `GRS1` 使用相同
批量结构，每个 chunk 为 LE uint32 raw 字节数与完整 EncXOR 字节。
这些批量 envelope 仅供独立驱动使用；FinalBits 按每个完整 raw chunk 计费。

```bash
build/local/gorilla_cli encode optimized tests/golden/input.bin /tmp/gorilla.raw
build/local/gorilla_cli decode canonical /tmp/gorilla.raw /tmp/gorilla.decoded
```

## 验证复现

227 个 case、489274 对样本，包含 ETTh1、exchange_rate、national_illness 全部
22 个数值列；完整 raw 字节一致、双向交叉解码、两侧自回环、逐样本状态 trace
和 FinalBits 闭合通过。两条路径均通过 ASan/UBSan/LSan、TSan、guard page、
canary、容量/状态边界和 100000 次 libFuzzer；AArch64 为实际 QEMU 执行。
两次干净构建的静态库与 CLI/API 测试/性能驱动逐字节相同。

```bash
# 如工具链尚未解包，按固定 URL/hash 只准备项目局部工具链：
python3 tools/bootstrap_toolchains.py
# 测试输入已经保留；重新从原始只读 CSV 准备可用：
python3 tests/datasets/prepare.py /home/fzg/PycharmProjects/材料/TSBench_Corpus
# 在普通终端运行，以免 ptrace 沙箱影响 LSan；setarch 仅作用于子进程：
python3 tools/qualify.py
```

`tools/reproduce.py` 的两个构建目录必须事先不存在；复现另一次时使用新的
目录名或新的解压工作区。测试源码及脚本不导入 Benchmark 框架。

源实现对部分字节结尾的序列化 chunk 执行 Reset 后继续追加存在恢复缺陷。
本包保留源行为，并提供 `decode-relaxed` 做源端行为对照；默认 strict decoder
拒绝多余尾部和非零 padding。正常增量追加和 live reacquire 均正确恢复。
借用输入必须保持地址及生命周期稳定；并发追加使用默认快照模式。

详细证据见 [validation/porting_report.md](validation/porting_report.md)、
[validation/dataset_validation_report.md](validation/dataset_validation_report.md)
及 [validation/validation_report.md](validation/validation_report.md)。独立性能仅为
QUALIFICATION；生产 Bench 接入及正式比较资格未签署。

许可：核心与 public header `Apache-2.0 AND BSD-2-Clause`；自编测试/驱动
`Apache-2.0`。原始版权与许可全文保存在 `LICENSES/` 和 source 快照中。
