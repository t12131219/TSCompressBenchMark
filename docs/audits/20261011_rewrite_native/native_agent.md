# 直接 native 接入专项审计（2026-10-11）

本专项覆盖当前 registry 的 26 个直接 upstream/native codec，其中 bzip2-stream、lzsse2-raw、lzsse8-raw 是仍注册的 legacy，另 23 个属于当前主范围。四个 HARNESS_ORACLE 是测试器，不计入算法。rewrite_lossless 与 completed_rewrites 由另外的专项覆盖。

后续修正（2026-10-11）：下文发现的 NeaTS/LeaTS 说明性补丁已保存旧副本并改成可执行 unified patch。独立[重放核验](neats_patch_replay.json)从干净冻结上游在临时目录顺序执行 `git apply --check/apply`，172/172 文件与现有 vendor 字节一致；vendor 仍是已修改原生 scalar variant，未改代码行为。登记补丁身份已更新；本记录中的旧身份回归与历史正式实验不会自动升级为新身份资格。下文保留修复前发现及其证据，不再把“当前三份 `.patch` 只是说明”作为修复后状态。

结论：26 个接入的真实编码核心均为本地编译的 C/C++ 或 Rust，现有 adapter 回归本轮 1,369 项全部通过，无失败、无跳过。它们大多直接调用 upstream 核心，不能称为“完成了 C++ 重写”；`lzss-raw` 尤其仍是原 Rust 静态库。严格的“原始源码、原始输入和原始格式完全不改”不能统一判 PASS：显式安全补丁、frame、RAW 支路、signed normalization 和 forced scheme 都需要保留在结论中。

## 本轮证据

- [check_native_sources.py](check_native_sources.py) 只读取项目 vendor 与指定 Source_Code，逐文件记录映射路径和实际 SHA-256，检查当前 upstream commit 及工作树。18 个 vendor 组共 1,030 文件：1,013 个可与指定本地 upstream 逐字节匹配，2 个是 NeaTS/LeaTS 已修改头文件，3 个 void 依赖文件和 12 个 Dipperstein 文件没有在指定 Source_Code 中找到独立来源。
- [native_source_comparison.json](native_source_comparison.json) 保存完整清单；全部可用 authority 仓库仍为预期 commit 且 clean。Sprintz 17 个实现文件来自 `sprintz-lzbench@580c4f...`；LICENSE 单独对照 `dblalock_sprintz/LICENSE`。
- [native_adapter_tests.xml](native_adapter_tests.xml)：当前 26 codec 的 21 个 adapter test 文件，以及 shared native timing/streaming，`1369 passed in 24.47s`。本轮测试使用当前 release 库，并没有重新生成注册证据或性能产物。
- [native_simdcomp_audits.json](native_simdcomp_audits.json)：直接调用现有独立 auditor 的 `audit()`，source、AVX2、native、SDK 全部 PASS。auditor 不只读 PASS 标签，还核查真实对象/库、编译依赖、驱动 hash、original failure、补丁重放、guard 矩阵与 SDK 闭包。

复现回归命令：`/home/fzg/anaconda3/envs/CompressBench14/bin/python -m pytest -q tests/adapters/test_alp.py tests/adapters/test_brotli_stream.py tests/adapters/test_bzip2_stream.py tests/adapters/test_deflate_zlib.py tests/adapters/test_entropy_fse.py tests/adapters/test_lz4_frame.py tests/adapters/test_lzss_dipperstein.py tests/adapters/test_lzss_raw.py tests/adapters/test_lzsse2_raw.py tests/adapters/test_lzsse8_raw.py tests/adapters/test_neats.py tests/adapters/test_serf.py tests/adapters/test_snappy_raw.py tests/adapters/test_sprintz.py tests/adapters/test_sprintz8.py tests/adapters/test_xz_stream.py tests/adapters/test_zfp.py tests/adapters/test_zstd_frame.py tests/adapters/test_native_timing.py tests/adapters/test_native_streaming_codecs.py tests/adapters/test_simdcomp.py`。

## 逐组判定

表中“接入 PASS”限于当前已声明的类型、参数、ISA、错误界和能力；不是原始算法所有模式资格，也不是全数据集性能证明。

| 当前 codec | vendor vs 本地 authority | 实际核心与本项目差异 | 接入/原生判定 |
|---|---:|---|---|
| alp、alp-rd | 15/15 一致 | 原 ALP/FastLanes C++；3 个 build copy 安全补丁；ALP 强制 decimal，ALP-RD 强制 RD；自定义完整 frame | 当前域接入 PASS；原生核心 PASS；不是 upstream 自适应入口的等同实现 |
| brotli-stream | 110/110 一致 | lzbench vendored Brotli C 的 stream API，本项目生命周期与容器 | 接入 PASS；原生核心 PASS；stream 参数/生命周期与 lzbench one-shot 不同 |
| bzip2-stream（legacy） | 12/12 一致 | 原 libbz2 C stream API；不是 Python bz2 编码 | 接入 PASS；原生核心 PASS；当前 release 库真实存在 |
| deflate-zlib | 48/48 一致 | 原 zlib C stream API；完整 RFC1950 zlib，不是单独 LZ77 | 接入 PASS；原生核心 PASS；原算法名只覆盖这一路径 |
| fse、huff0 | 16/16 一致 | 原 FSE/HUF C；本项目 9-byte mode/length 和 RAW/RLE 分支 | 接入 PASS；原生核心 PASS；RAW/RLE 对象不能说完整 payload 执行了熵核心 |
| lz4-frame | 11/11 一致 | 原 LZ4 frame C，lzbench entry 本身调用 raw block | 接入 PASS；原生核心 PASS；不是 lzbench raw LZ4 格式 |
| lzss-raw | 原 lzss 31/31；void 3 文件无本地独立来源 | `Lzss<10,4,0x20,1024,2048>::compress_stack/decompress_stack` 原 Rust 静态库，C++/C ABI 包装 | 接入 PASS；native Rust PASS；C++ 重写不适用；依赖来源需另核验 pinned crate |
| lzss-dipperstein-c | 12 文件在指定 Source_Code 无独立来源 | 原 C LZSS/bitfile；tree sentinel 安全补丁；空输入 special case；严格 token validator | 接入 PASS；native C PASS；指定 corpus 的 provenance 独立闭合尚缺，不判原始来源完全验证 |
| lzsse2-raw、lzsse8-raw（legacy） | 各 5/5 一致 | 原 C++/SSE4.1；生成副本 allocation/alignment patch；自带 raw/compressed 返回语义 | 接入 PASS；原生核心 PASS；当前库真实存在；不得宣称未改源执行 |
| neats-lossless-i64、leats-lossless-i64 | 170/172 一致；2 头文件已改 | C++ scalar model；signed per-column minimum shift、frame/model/index/checksum；vendor 本体已包含 scalar/serialization/precision edits | 当前域接入 PASS；native C++ PASS；严格原始源码纯执行 FAIL；“build-only patch replay”文档说法不成立 |
| serf-qt、serf-xor | 36/36 一致（35 core + README） | 原 C++ Qt/XOR；3 安全补丁、column/block frame；nonfinite/unrepresentable/overflow RAW records | 接入 PASS；原生核心 PASS；特例对象含已登记 RAW，不是纯 upstream 全块编码 |
| simdcomp-u32 | 27/27 一致 | 原 C SSE4.1/AVX2 pack/unpack；4 explicit fixes；bounded ABI、SBP1 和 scalar wire checks | 当前 5 个 plain API/ISA 组合接入 PASS；原生核心 PASS；独立 source/AVX2/native/SDK audit PASS；不是 FastPFOR SIMDBinaryPacking |
| snappy-raw | 10/10 一致 | 原 Snappy C++ raw API，scalar 无 dictionary/checksum | 接入 PASS；原生核心 PASS；外层 descriptor 属项目格式 |
| sprintz-delta、sprintz-fire、sprintz-delta-u8、sprintz-fire-u8、sprintz-fire-huff0 | 18/18 一致（17 core + LICENSE） | 原 AVX2/BMI2/LZCNT Sprintz；bounded staging/validation 和 build copy 安全补丁；FIRE+Huff0 为显式串联 | 接入 PASS；原生核心 PASS；FIRE+Huff0 是组合路径；低维 u8 与 full 8/16-bit 合同不同 |
| xz-stream | 341/341 一致 | 原 liblzma C/XZ-LZMA2 preset6、无 data-check，含 structural CRC | 接入 PASS；原生核心 PASS；不是 raw LZMA，也不是所有 XZ filters |
| zfp-accuracy-1d | 94/94 一致 | 原 serial C fixed accuracy 1D per-column；特殊 IEEE column RAW record | 接入 PASS；原生核心 PASS；不是 rate/precision/reversible/ND/CUDA；RAW column 非 zfp payload |
| zstd-frame | 64/64 一致 | 原 Zstd C single-thread frame；禁 asm、BMI2 dispatch、legacy/dict/MT 等 | 接入 PASS；原生核心 PASS；仅所声明 execution variant |

## NeaTS/LeaTS 的可核查问题

这是 provenance 表述错误和补丁可重放缺口，不是本轮 roundtrip 失败。

1. `adapters/neats/vendor/neats/include/NeaTS.hpp:335` 将 `std::to_underlying` 改成 cast；`:428` 直接从 upstream `simd_make_residuals(begin)` 改为 `make_residuals(begin,end)`。同时移除 `<stdfloat>`、替换 diagnostic float64 casts。完整差异：[native_NeaTS_vendor.diff](native_NeaTS_vendor.diff)。
2. `adapters/neats/vendor/neats/include/LeaTS.hpp:94` 删除 upstream SIMD loop；`:95` 将 predictor 提升到 double evaluation；`:486`、`:614` 启用 upstream 注释中的 serialize/load，并去除 LeaTS 不存在的字段。完整差异：[native_LeaTS_vendor.diff](native_LeaTS_vendor.diff)。
3. `tools/build_codec.py:992` 的 `_neats_command` 直接把 vendor/include 加入编译，不复制原始 upstream，不应用 patch。三份 `.patch` 是解释性文字，不能用 `git apply` 或 `patch` 重放。
4. `docs/neats_leats_admission_review.md:24` 声称“三个 build-time patches ... replayed outside immutable vendor closure”，与当前真实构建不符。当前 `source_closure_sha256=71c668...` 确实匹配**已经改过的** 172-file vendor，故当前 identity 自洽，但不能当成未改 upstream closure。

建议修正证据说明：明确这两项是 `PATCHED_NATIVE_SCALAR_VARIANT`；若要保留“immutable vendor + build-only replay”的承诺，应保存原始 vendor 和真正 unified patches，再用相同 oracle 重新资格。当前 qualified int roundtrip 可保留其受限含义。

## “原生”与产物解释边界

`CORE` 包括 harness session 调用和 API 内部 descriptors、staging、copies、frame/model work，不是纯 native kernel 时间。`NATIVE` 要按实际边界看：Serf、ZFP、NeaTS 是 frame/model boundary；ALP `encode_typed` 包含 native frame serialization；Sprintz bounded API 包含分配、padding copy 和 validation。单纯有非空 native 时间不能证明“只有 upstream kernel”，也不能把 wrapper 成本或 RAW 比例忽略。

ALP 还有 `create_adapter(..., source_reject_fallback=True)` 路径：工厂返回 `SourceRejectCompositeAdapter`，Python 按 block 处理 SourceDomainError 并储存 RAW。它有独立 composite AdapterID/RecipeID 和显式账本，设计上可审计；有该 flag 的产物只能称“ALP + source-reject RAW composition”，不能称整个对象都由原生 decimal ALP 执行。默认 factory 为 false；实际产物应读 frozen config/recipe 和 block encoding 逐一判断。

多数 direct factory 没有 SIMDComp 那样逐份强制核验 compiler dependency、源码、对象和 Python closure；它们的 build-record/artifact 哈希匹配证明库与记录相符，不能单独证明当前源码就是该二进制完整输入。独立 source 比对、真实 ABI 回归和已冻结产物的关联需结合主审计使用。五层 PASS/统计完整性证明的是该实际流在测试域上的接入、计费和测量；不自动成为 upstream byte-equivalence、所有参数、所有数据或未使用 RAW 的证明。

本轮不扩大 sanitizer 声明：1,369 项是当前 release adapter 回归；SIMDComp auditor 核查既有三档安全证据；其他 native ASan/UBSan 历史报告只作为受限支持证据，未在本专项重新构建全部 sanitizer codec。
