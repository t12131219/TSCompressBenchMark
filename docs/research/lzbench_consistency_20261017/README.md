# 当前字节压缩算法与 lzbench 的一致性审计（2026-10-17）

**结论：不能将这批算法整体认定为“与 lzbench 完全一致”。当前接入在本次实测范围内均可正确恢复，但源码同源、核心 payload 一致、完整格式一致、执行配置一致是不同结论。** 本次是只读实现审计；没有替换 codec、修改参数默认值或补签 FULL_PARITY／正式性能资格。

对照固定为本地 `inikep/lzbench@fa871e66b3543a70fd4d060f7c12719343ff4ac3`，工作区干净。当前 `/home/fzg/PycharmProjects/lzbench` 不存在，因此未将历史上该路径的另一提交当成本次 oracle。2026-10-15 的同库诊断报告保留原身份；本报告检查的是现在的 `native_core` 主路径，并另查 C1 辅助接口。

## 逐算法结论

下表完整输出计数均指 **native_core、当前解析默认参数、39 组输入**，不含框架旁置管理文件。LZSSE 的长度头是方法输出，不能从压缩大小中扣掉后仍称完整输出一致。

| 用户名称／当前 key | 与 lzbench 默认对照的完整字节 | 当前结论 |
|---|---:|---|
| zstd／`zstd-frame` | 0/39 | 同一 1.5.7 核心；Bench 默认 checksum=true，lzbench 默认关闭。显式关闭 Bench checksum 后 **39/39** 相同；两种配置均可双向解码。构建禁用 BMI2 动态路径和 ASM，执行能力仍有差异。 |
| lz4／`lz4-frame` | 0/39 | 同一 1.10.0 源码，但 Bench 是 **LZ4 frame**，lzbench 的 `lz4` 是 **raw block**；不能直接互喂完整格式。独立源码构建的相同参数 LZ4F 参考 **39/39** 一致并双向解码，证明 frame 接入有效。 |
| snappy／`snappy-raw` | 39/39 | 同源 RawCompress／RawUncompress，所测码流及双向解码一致；Bench 关闭若干 SIMD 路径，解码会检查长度和返回值，不能宣称所有执行／失败行为完全相同。 |
| deflate-zlib／`deflate-zlib` | 39/39 | 对应 lzbench 的 **`zlib`**，不是 libdeflate／zlib-ng。同源 zlib 1.3.2，默认 level6、window15；level1 也 39/39 一致。Bench 的 window9 变体与固定 window15 对照为 0/39，但双向解码通过，是参数差异。 |
| brotli／`brotli-stream` | 39/39 | 同源 1.2.0，native_core 与 lzbench 同为 BrotliEncoderCompress；quality5/window22、quality1、window18 三组各 39/39 一致。**C1 空输入例外**见下文。 |
| bzip2／`bzip2-stream` | 39/39 | 同源 1.0.8，同一 BuffToBuffCompress；默认 level9、另测 level1 均 39/39 相同。解码入口与严格消费检查不同。 |
| xz／`xz-stream` | 3/39 | 同源 5.8.3，均为 `.xz`／LZMA2／CHECK_NONE；Bench 用 easy_buffer_encode，lzbench 用 stream_encoder_mt。即使参考端只设 **1 线程**，非空用例仍不同；全部双向解码通过。独立相同 easy API 输出 **78/78** 一致。 |
| lzss／`lzss-raw` | 无对应项 | 是 alexkazik/lzss 的 EI10/EJ4/C32 C++17 重写，本提交的 lzbench 表中没有对应实现。另回放原作冻结向量 **282/282**：解码输入哈希正确、重编码完整 raw 字节相同；这不是 lzbench 一致性证明。 |
| lzss 的另一登记／`lzss-dipperstein-c` | 无对应项 | 来源 MichaelDipperstein/lzss，与上述实现不同；本次 lzbench 同样没有对应项。39 组主路径、10 组 C1 往返通过，不能据此签原作全范围一致性。 |
| lzsse2／`lzsse2-raw` | 0/39 | 同源 2019-04-18、OptimalParse level12；**去掉 Bench 的 8 字节原长头后 payload 为 39/39 相同**，重建／去除头后双向解码通过。安全补丁和只开放 level12 都应单独登记。 |
| lzsse8／`lzsse8-raw` | 0/39 | 与 LZSSE2 同样结论。对应 lzbench 的 `lzsse8`，不是 `lzsse8fast`；没有资格覆盖全部 level0–17 或 fast 入口。 |

这里的 3/39 XZ 相同项是三个空输入标签；不是三个非空输入意外等价。Snappy 的 lzbench 表标签为 1.2.2，冻结 public header 写 1.2.1；本次使用源码哈希判同源，不依赖版本标签。

## 源码、补丁与调用边界

9 个有 lzbench 对应项的 vendor 目录总计 **606/606 文件**逐 SHA-256 相同：Zstd 64、LZ4 11、Snappy 10、zlib 48、Brotli 110、BZip2 12、XZ 341、LZSSE2 5、LZSSE8 5。包含源码及各目录附带的许可证等文件；不等同于 606 个编译 TU。详见 [逐文件清单](source_inventory.json)。

LZSSE vendor 保持原字节，构建对派生源应用 `0001-allocation-unaligned-pointer-safety.patch`：分配空指针检查、memcpy 非对齐 load/store、避免安全区指针先于对象起点。故“vendor 相同”不能推导“实际编译源码完全无差异”。本次实际 patched 依赖进入 Bench build record，level12 所测 payload 保持一致。两个 LZSS 的来源、字典参数和独立补丁不冒充 lzbench 资产。

主路径使用 `benchmark/native/core.hpp` 中的直接 ZSTD_compress2／decompressDCtx、LZ4F Begin/Update/End／decompress、Snappy Raw API；其余调用各 adapter 的 `direct_core`。LZSSE workspace 在 prepared 建立，原生调用内仍完成查找状态重置和 optimal parse。zlib 主路径复用 context 并 Reset，lzbench compress2 每次内部新建／销毁 context。Brotli、BZip2、zlib、XZ 主路径 decoder 比 lzbench wrapper 更严格地检查输出长度／输入完全消费，XZ 还有 1 GiB 内存限额；损坏／拼接流的接受范围不能叫完全相同。

Zstd Bench 单线程、DYNAMIC_BMI2=0、ZSTD_DISABLE_ASM；独立参考启用 ZSTD_MULTITHREAD 和 amd64 汇编，但本次线程参数固定 1。Snappy Bench 显式关闭 SSSE3/BMI2/CRC 等路径；本次参考没有额外 `-march=native`，不证明任意 SIMD build 的字节／性能都相同。LZ4 frame 默认 independent64KiB、level0、content checksum、content size；raw LZ4 与 frame 中的 raw-block fallback 不构成相同完整格式。

## 独立参考和实测证据

本次直接编译未修改的上游 `bench/lz_codecs.cpp` 与 `bench/symmetric_codecs.cpp`，仅通过 BENCH_REMOVE_* 排除无关算法，连同上游压缩库独立生成 oracle；通过额外 C export 分派到这些原 wrapper。**没有用 Bench 的动态库充当 lzbench oracle，也没有运行 lzbench 性能主程序。** 全部编译命令、工具链、源文件／依赖和 oracle 二进制哈希保存在 build record。

XZ oracle 的库采用上游 CMake 配置，其他库采用 Makefile 风格 release 编译选项；因此它是“固定源码 wrapper 的独立对照构建”，不是声称逐项复制完整 lzbench Makefile 环境。LZ4F／XZ easy 参考是同源库的额外 API 探针，明确不冒称 lzbench 表登记的算法入口。空输入 LZSSE workspace 预留最小 1 字节，不测试上游零分配／分配失败行为。

最终主路径共 **702 组输入×方法×参数组合**：33 个合成案例（空、零值、确定性随机、重复模式；边界 0/1/15/31/32/63/64/257/4096/65536/65537/131073 bytes）与 6 个真实窗口（ETTh1、Weather、ILI，各 128/512 行）的物理 bytes。真实窗口逐哈希复用此前保存的原始输入，未把压缩产物当作输入。每组 prepared 执行 1 次 warmup 和 2 次正式操作，三份产物都在计时外精确验证，并由另一个进程冷恢复。这里的短时钟数据只用于执行检查，不形成吞吐结论。

- 702/702 主路径往返及独立进程恢复通过。
- 624/624 有参考的组合通过独立 oracle 自恢复及双向恢复。其中 **585 组**对照真正 lzbench wrapper（LZSSE 必须适配长度头）；另外 **39 组 LZ4 是补充 LZ4F 对照**，不是 raw `lz4` 的跨格式成功。
- 主路径完整字节相同 357/624；LZSSE 去头后相同另有 78。不能把跨解码成功数报告成字节相同数。
- 110/110 C1 往返通过；90 组有对应参考，全部双向恢复。LZ4 的 10 组仍是补充 LZ4F 对照。
- 282/282 alexkazik 原作冻结向量回放通过。
- 现有 `test_core_bytes.py`、`test_native_measurement.py`、`test_native_bridge.py`：**127 passed，无失败／跳过**。

### C1 与主路径的额外差别

10 个默认参数 C1 案例覆盖空输入、257/4096/65537-byte 合成输入及上述 6 个真实窗口。Zstd／LZ4／Snappy／zlib／BZip2／XZ 的 C1 与主路径输出在这 10 组内相同；两种 LZSS 和 LZSSE 的 C1 输出为 raw payload，而主路径多 8 字节原长。

Brotli 空输入 C1 stream API 输出 `3b`，主路径／lzbench one-shot 输出 `06`，**两者均为 1 字节且可正确恢复空输入**；其余 9 组相同。这是有效但不同的空流编码，不是恢复错误。不能将 native_core 的 Brotli 字节一致结论扩大为所有接口一致。

## 证据与重放

- [最终汇总](../../../runs/lzbench-current-audit-20261017-final/summary.json)、[702 组明细](../../../runs/lzbench-current-audit-20261017-final/results.json)、[39 组输入身份](../../../runs/lzbench-current-audit-20261017-final/inputs.json)。
- [独立 oracle 构建](../../../runs/lzbench-current-audit-20261017/oracle/build.json)、[当前 Bench 构建快照](../../../runs/lzbench-current-audit-20261017-final/bench_builds.json)。702 组各自目录保留 Bench 三份产物／冷恢复、reference 码流和交叉进程命令／输出。
- [C1 汇总](../../../runs/lzbench-current-audit-20261017-final/c1/summary.json)、[C1 明细](../../../runs/lzbench-current-audit-20261017-final/c1/results.json)、[LZSS 向量回放](../../../runs/lzbench-current-audit-20261017-final/lzss-fixtures/results.json)、[127 项测试日志](../../../runs/lzbench-current-audit-20261017-final/pytest.log)。
- 初轮 594 组合成检查另保留于 `runs/lzbench-current-audit-20261017`，没有覆盖／混写。最终检查补入真实窗口，oracle 保持同一二进制身份。
- [审计工件索引](evidence.json)。本轮重新调用现有 content-addressed 构建以核实当前源码依赖和二进制身份；历史运行和冻结设计未修改。

在仓库根目录使用已有 NumPy／pytest 环境，选择一个尚不存在的 output 目录：

```bash
PYTHONPATH=benchmark/src python benchmark/tools/audit_lzbench_current.py --output runs/lzbench-audit-new
PYTHONPATH=benchmark/src python benchmark/tools/audit_lzbench_api.py --campaign runs/lzbench-audit-new
PYTHONPATH=benchmark/src python benchmark/tools/audit_lzss_reference_vectors.py --output runs/lzbench-audit-new/lzss-fixtures
PYTHONPATH=benchmark/src python -m pytest benchmark/tests/test_core_bytes.py benchmark/tests/test_native_measurement.py benchmark/tests/test_native_bridge.py -q
```

若全新构建没有 `oracle_reference.json`，C1 重放工具会使用同目录 `oracle/liblzbench_oracle.so`；也可通过主工具 `--reuse-oracle` 指向已有、哈希核实的 oracle。实际运行使用 Python 环境 `/home/fzg/anaconda3/envs/CompressBench14`。

本次没有重新执行 sanitizer／fuzz／ARM64，也没有覆盖所有 level、超大资源上限、任意损坏流或全部 ISA。不能把有限实测升级为“所有可能输入 FULL_PARITY”；同源且通过正确性检查的接入也不会因为有明确的 framing／checksum／API 差异自动变成“移植失败”。
