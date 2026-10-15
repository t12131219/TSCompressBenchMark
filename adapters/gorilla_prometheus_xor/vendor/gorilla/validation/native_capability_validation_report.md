# Native capability validation

**FULL_PARITY**：冻结 Prometheus XOR 对象、Linux amd64/AArch64 LP64。10 项
REQUIRED_PARITY 全 PASS；无 waiver、未分类或静默 fallback。源能力与独立
公开能力由 NATIVE_CAPABILITY_MATRIX.yaml 对照；BenchProfile/PipelineCoverage
为 N/A（本次为独立包）。

| Capability | 源依据 | 实现/证据 | 结论 |
|---|---|---|---|
| chunk.codec | NewXORChunk / Append / Next | API preflight、state differential、six profiles | PASS |
| stream.append | xorAppender.Append | API preflight、state differential、six profiles | PASS |
| state.reset | XORChunk.Reset / xorIterator.Reset | API preflight、state differential、six profiles | PASS |
| state.compact | XORChunk.Compact | API preflight、state differential、six profiles | PASS |
| query.seek | xorIterator.Seek / At / AtT / AtST | API preflight、state differential、six profiles | PASS |
| thread.snapshot | XORChunk.Iterator comments / newBReader.last | API preflight、state differential、six profiles | PASS |
| thread.handles | per-chunk state, no mutable globals | API preflight、state differential、six profiles | PASS |
| memory.bytes | Bytes / NumSamples | API preflight、state differential、six profiles | PASS |
| scalar.fast_reader | Next/readValue fast paths; bstreamReader.readBitsFast/loadNextBuffer | API preflight、state differential、six profiles | PASS |
| memory.zero_copy_raw | XORChunk.Reset/Bytes, iterator/newBReader: borrow slice and capture last byte | API preflight、state differential、six profiles | PASS |

增量接口按 1 样本更新；不缓存原输入，独立 chunk 不共享 predictor。flush 不
seal，compact 后可追加；finalize 幂等、seal 后追加明确拒绝、reset 后复用。
source/rewrite 在重新获取 appender 后完整字节及恢复结果一致。

并发 handle 和创建后的默认快照通过 4 线程测试及 TSan；同一 writer 不承诺
线程安全。Borrowed reader/ownership-transfer reset 的零拷贝由指针 identity
直接证明，配合 immutable/guard-page 输入与末字节 snapshot 测试；其读取
字段逻辑与所有 dataset 验证共享。Borrowed backing storage 由 caller 维持。

优化 path 被显式强制，实例 execution_stats 校验 canonical bit 操作计数为 0，
优化字段与重复 timestamp/value shortcut 计数非零；canonical 反向检查。
上游未提供 ISA dispatch、GPU、HLS、内部并行、byte backpressure、dictionary、
random access/index、checksum 或原生矩阵/整数/float32 value 能力，逐项 N/A。

上游 API/build/CI 检查范围：xor.go、bstream.go、chunk.go、三个原始测试文件、
go.mod/go.sum、Makefile、ci.yml、fuzzing.yml。Go CI 另有 386；本包发布平台
合同为 Linux LP64 双架构，386/Windows/macOS/大端运行均未开放、不签 PASS。
AArch64 是 QEMU 执行，没有硬件性能或该架构 sanitizer 结论；amd64 ASan/
UBSan/LSan/TSan 插桩覆盖两个完整生产 translation units、API 测试和驱动。
