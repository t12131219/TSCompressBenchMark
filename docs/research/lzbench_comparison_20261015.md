# LZ、Zstd、Snappy 与 lzbench 的比较核查（2026-10-15）

当前比较同时混入了完整对象封装、原生 API／生命周期、构建优化、输入与统计规则的差异。源码和字节对照已经确认这些差异存在；不能把完整对象吞吐直接解释为 codec 的原生吞吐，也不能只修改报表公式来得到原生速度。

本次新增的是**不计时的字节诊断**：ETTh1、weather、ILI 各取既有配置中的 128／512 行窗口，只比较 V 的连续 `<f8` 矩阵，不含 T／mask，不分列、不另切 chunk。共 6 个输入、18 个 codec/object 组合，以及 24 个直接原生编码／恢复组合，全部按位恢复成功。未构建或运行 lzbench，未测量新的 MB/s，未更换现有 codec binary。原始输入、payload、wire、源文件／binary hash 与逐项结果保存于 [results.json](../../runs/lzbench-payload-check-20261015/results.json)。

复现工具为 [lzbench_payload_check.py](../../benchmark/tools/lzbench_payload_check.py)。现存其他 codec 的历史性能 raw 已不在当前 checkout；本次没有重新验证旧文档表中的速度。

## 1. 同输入、同一个共享库，实际输出是否变差

ETTh1 的 128×7 个 float64 values 共 **7,168 bytes**，本次产物如下。压缩倍数统一为 `raw / compressed`：

| 路径 | 直接原生 API 输出 | 当前适配器 payload | 外层 header | 完整 wire | payload 压缩倍数 | wire 压缩倍数 |
|---|---:|---:|---:|---:|---:|---:|
| Snappy RawCompress | 4,332 | 4,332 | 1,491 | 5,823 | 1.655× | 1.231× |
| Zstd compress2，level 3、checksum 开启 | 3,151 | 3,151 | 1,525 | 4,676 | 2.275× | 1.533× |
| LZ4 raw block 对照当前 LZ4 frame | 4,458（raw block） | 4,485（frame） | 1,591 | 6,076 | 1.598×（frame） | 1.180× |

前两行可明确观察到同样的原生输出加上外层表示之后，整个对象的压缩倍数下降；没有证据表明移植把相同的原生输出压坏了。最后一行是两种格式，不能要求其 bitstream 相同。

- **Snappy：6/6 输入的 `RawCompress` 输出与生产 bridge／object 内的 native payload 逐字节一致。** 两条路径都直接使用当前 `.so` 中同一个 Snappy 实现。
- **Zstd：6/6 输入在 level 3、content size、checksum 设置一致时，`ZSTD_compress2` 输出与当前 streaming adapter payload 逐字节一致。** 关闭 checksum 后，每个输入恰好减少 4 bytes；所以本组输入上的巨大差距不能归因于 checksum 大小。这个相等结论只覆盖本次窗口，不推广成所有长度与参数下 streaming／one-shot 必然相同。
- **LZ4：ETT 128／512 和 ILI 128／512、weather 128 的 frame 比 raw block 多 27 bytes；weather 512 的 frame 为 37,561 bytes，raw block 为 38,489 bytes。** 后者超过 64 KiB，分块和 API 条件已不同，frame 甚至可以更小。不能用统一的“扣几个 header 字节”将 frame 结果换算成 raw block 结果。

本次 `wire_bytes = adapter_payload_bytes + header_bytes` 全部成立。header 包含框架 JSON descriptor、身份／校验字段和 wire prefix；它不等于 codec 自身 frame header。这些对象的外层 header 为 1,491–1,843 bytes，对短输入的影响很明显。本次是 V-only 诊断，与上一份 [Gorilla records 诊断](metrics_diagnosis_20261015.md)的 V＋T、逐列 128 点分块分母不同。

## 2. 各算法的已确认差异

### Zstd

[实际构建配方](../../benchmark/src/tsbench/_native_recipes.py:271)及已生成的 `build.json` commands 均含：

```text
-O3 -DNDEBUG -DDYNAMIC_BMI2=0 -DZSTD_DISABLE_ASM
```

这关闭了 Zstd 的动态 BMI2 分派与相应汇编路径。当前配方只列 `.c` 源，而作为参考的 lzbench Makefile还列入 `huf_decompress_amd64.S`。上游的 [portability_macros.h](../../adapters/zstd_frame/vendor/zstd/lib/common/portability_macros.h:93)在支持的编译器／x86 条件下允许动态 BMI2。是否实际启用／调用，仍取决于具体 binary、编译选项和 CPU；本次没有测定这些路径贡献了多少速度。

当前 [adapter](../../adapters/zstd_frame/native/tscb_zstd_frame.c:305) 使用 `ZSTD_compressStream2(continue)`＋`end`，解码使用 `ZSTD_decompressStream`。lzbench wrapper 使用 `ZSTD_compress2`／`ZSTD_decompressDCtx`，在测量之前创建 Cctx／Dctx，并在重复操作中复用 workspace。

当前 [Python session](../../benchmark/src/tsbench/bridges/c_abi_v1.py:160) 每次 create→reset→操作→destroy。`tscb_create` 已创建并配置 CCtx，reset 再配置；**解码也先经过这条编码 CCtx 创建路径，然后 `tscb_decompress` 才另建真正的 DCtx**。这些工作均进入完整对象耗时，与 lzbench 的计时边界不同。复用合法 workspace 能降低独立对象开销，但不允许继承上一对象的字典历史。

当前 checksum 默认开启，lzbench 常规 zstd wrapper 新建 context 的默认 checksum 关闭。它还存在校验计算成本；本次只验证其输出大小差，未测时间贡献。

### Snappy

[构建配方](../../benchmark/src/tsbench/_native_recipes.py:311)与实际 commands 显式设置 `SNAPPY_HAVE_SSSE3=0`、`SNAPPY_HAVE_BMI2=0`、`SNAPPY_HAVE_X86_CRC32=0` 等宏。`-O3` 不能恢复被预处理条件排除的实现路径。CRC32 指令路径也用于实现内部操作，不能把宏名理解成当前 raw format 启用了额外 frame checksum。

[adapter 解码](../../adapters/snappy_raw/native/tscb_snappy_raw.cc:213)先执行：

```text
GetUncompressedLength → 精确容量检查 → IsValidCompressedBuffer → RawUncompress
```

lzbench wrapper 直接执行 `RawUncompress`。当前路径在正式解压前多做一次完整压缩流结构验证；这不等于完整解压两次，但确实增加扫描和解析成本。现有 native 内部 timer只包住 `RawUncompress`，object timer还包括预验证，二者不能同名混报。

Snappy 当前编码 payload 已与直接原生 API 完全一致，优先要处理的是外层大小计费、计时边界和实现构建条件。**不能据此断言任意 lzbench binary 默认启用了全部 SIMD。** 所读 Makefile 中 `-march=native` 是可选项；SSSE3／BMI2 是否启用须检查具体编译宏与 binary。

### LZ4／LZSS／LZSSE

本项目的 `lz4-frame` 使用 `LZ4F_compressBegin/Update/End`，默认独立 64 KiB blocks、level 0、内容 checksum 开启，并保存 content size。lzbench 的 `lz4` 使用 `LZ4_compress_default`＋`LZ4_decompress_safe`，是 raw block，压缩产物不带相同 frame 信息。`lz4hc`、`lz4fast` 又是不同入口，需按实际算法参数逐一对应。

此外，当前 LZ4 的 create 建 compression context，[reset](../../adapters/lz4_frame/native/tscb_lz4_frame.c:218) 又释放重建；decode session同样先创建编码 context，再在实际解码中创建解码 context。frame、checksum、生命周期与外层对象成本叠加后，完整对象速度不能代表 raw LZ4 的热循环速度。

`lzss-raw` 则是 [alexkazik LZSS 的固定配置 C++ 重写](../../adapters/lzss_raw/README.md)：EI10／EJ4、1,024-byte window、17-byte lookahead，匹配候选逐一扫描、位级输出。已检查的 lzbench codec 表没有这个具体实现；不能拿 LZ4／Snappy 的 GB/s 作为它的原生预期。`lzss-dipperstein-c` 是另一实现；`lz77` 在本项目只是 `deflate-zlib` 别名；`lzsse2-raw`／`lzsse8-raw` 是单独的 SSE 系列。它们应按实现和参数匹配，不能仅凭名称都含 LZ 就互作基准。当前 LZSSE 配方已有 `-msse4.1`，不能将所有 codec 一概描述成关闭 SIMD。

## 3. 源码来源、版本与公开表也必须对应

本次读取完整 wrapper／Makefile 的只读参考仓库为：

`Compression_Source_Code/Source_Code/_repos/inikep_lzbench@fa871e66b3543a70fd4d060f7c12719343ff4ac3`。

当前 vendored Zstd 62 个文件、Snappy 10 个文件、LZ4 10 个文件，与该参考仓库中对应文件 **82/82 字节相同**，逐文件双侧 SHA-256 保存在 results.json。这验证了当前所保存文件的来源一致；不代表当前构建选项、二进制、wrapper或完整上游文件集合相同。

其 codec 表标注 LZ4 1.10.0、Zstd 1.5.7、Snappy 1.2.2；Snappy 保存的 public header自身仍写 1.2.1，版本字符串存在来源内的不一致，应以源文件身份为准。该仓库 README 的旧性能表另写 Snappy 1.2.1／Zstd 1.5.6，不能把 checkout 的 codec 表版本自动套到 README 历史测量。

项目此前保存的 [lzbench 研究 README](sources/codecs_open_source/lzbench/README.md:130) 属于另一快照 `9ca711ce574d1ac56b803db4292b8797283575b3`，其表是 lzbench 2.4 release binary、GCC 15.2、EPYC 9555P、Silesia tar，Snappy 条目标注 1.3.1。它不是本机 i5-13400F 上的匹配实验，也不是本次字节核查使用的 fa871e 源树。

## 4. 数字和测量协议的差异

所读 [lzbench print_speed](sources/codecs_open_source/lzbench/bench/lzbench.cpp:155) 定义：

```text
Ratio = compressed_bytes * 100 / original_bytes
MB/s  = original_bytes * 1000 / elapsed_ns
```

因此公开 Snappy 表中的 `47.85` 是 **47.85% 存储占比，约 2.09× 压缩**；不是 47.85×。当前框架 Markdown 显示 stored fraction，如 0.4785；JSON／CSV 另有互为倒数的 compression_ratio。压缩倍数、占比和节省率必须分开命名。

lzbench 吞吐使用十进制 MB/s；框架用 MiB/s，`MB/s = MiB/s × 1.048576`。单位差约 4.86%，不能解释数量级差距。

lzbench 在同一进程内重复使用预分配 buffer、预热后的 context／workspace；默认汇总选 FASTEST（最短时间），支持 `-p3` 选 median。当前框架取成功 object rounds 的 median，且计入 Python 分发、分块／复制、native session、分配、hash、JSON、完整 wire及解码对象重组。现代快速 codec 的单次工作很短，这些额外工作尤其明显。详见 [CPU executor](../../benchmark/src/tsbench/executors/cpu.py:66) 和 [上一份边界诊断](metrics_diagnosis_20261015.md)。本次没有测量各项开销的比例，不能把总差值全归因于 Python FFI。

同样，CSV／Silesia 文本／tar 与按位 float64 矩阵不是相同的输入字节。不同数据、长度、行列顺序和 chunk reset会改变匹配机会；通用字节 codec 没有固定的“应有压缩率”。同一个确定性实现的相同输入、参数与输出格式才应得到一致的大小。

## 5. 让主表能够公平对照 lzbench 的改造要求

1. **单列三种结果。** `native_core` 直接调用实际原生 API；`native_api` 测量完整适配器 ABI；`object_memory` 保留完整对象边界。分别报告 codec 输出、adapter输出、wire bytes；不要给旧 object 时间赋予 native 含义。
2. **匹配算法和构建。** LZ4增加具名 raw-block 比较入口；Zstd匹配 level／checksum／window／线程；Snappy核对实际源码。新增可追溯的优化构建身份与 CPU／ISA 条件，保留当前受限构建作为独立实现，不静默替换其标签。对已明确要求 bitwise fidelity 的浮点路径，不全局照抄 `-ffast-math`。
3. **用原生循环测原生。** Python继续负责数据、资格、隔离和报告；在原生进程内执行足够长的 C/C++ 重复循环。prepared context／buffer与 cold／fresh lifecycle分别报告；每次独立输入重置逻辑状态，复用空间不复用压缩历史。native core与 ABI driver必须真正调用各自接口，不通过计时相减估计。
4. **把审计和重复准备放到对应阶段。** 例如普通非raw part解码每次新建 Registry、重新读取全体 JSON，可在已冻结身份的 prepare 阶段做一次。验证可在 native 主计时外逐次核对并单列；完整 object 校验仍按其声明计费。不能跳过错误检查或取消损坏输入资格却沿用原有承诺。
5. **同机、同输入、同统计规则复测。** 固定 binary／runtime／源码、数据hash／dtype／order、chunk、参数、线程与CPU条件，分别报告延迟和批量吞吐。median对median，fastest另列；先核对字节、恢复和独立解码，再对照速度。原生压缩倍数用 `codec_logical_input_bytes/native_output_bytes`，吞吐用相同输入 bytes 除以对应原生时间；完整对象继续使用 task raw／wire与object时间。

上述 native 性能入口和优化构建仍是后续实施项；本次已交付源码核查及同库字节证据，不能称为已经复现 lzbench 原生带宽。

## 6. 本次执行

```bash
PYTHONPATH=benchmark/src \
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libstdc++.so.6:/home/fzg/anaconda3/lib/libgcc_s.so.1 \
python benchmark/tools/lzbench_payload_check.py \
  --output-dir runs/lzbench-payload-check-20261015 \
  --lzbench-source /home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench
```

工具拒绝覆盖已存在的输出目录；复测需要新的名称。显式 preload保持当前环境可加载既有库，不构建新实现，也不被解释成性能控制实验。54 个去重产物共 862,828 bytes，已回读核对 SHA-256；18 个 object 恢复、24 个 core 恢复以及适用的 18 个 raw／frame跨 bridge 解码检查通过，输入均未修改。
