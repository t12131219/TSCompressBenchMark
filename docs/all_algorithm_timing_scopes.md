# 全部已注册入口的 CORE / PIPELINE / E2E 接入验证（2026-10-08）

当前 **63 个原生算法入口、4 个框架 oracle、4 个别名**已通过三个模式的五层资格验证，共 **213 个模式用例**。
验证限定为每个入口的一组支持配置和对应数据域；不代表所有参数变体、数据集或正式性能排名已验收。

此前 18 个完成重写入口只声明 PIPELINE/E2E，CORE 在第二层被拒绝。本次补齐声明、明确计时边界，
同步 Gorilla / Delta-of-Delta / Second-order Difference 的别名身份及源码接入卡，并修正注册生成工具。
共享 warmup / measured inner-loop 现在传递有损 dtype 转换的误差界，避免预检通过后执行报 WARMUP_FAILED；
未声明误差界或实际转换误差越界仍明确失败。全部 SourceArtifactID 保留，原版及 vendored 算法源码未修改。

## 计时含义

| 模式 | 实际 harness wall-clock 边界 |
| --- | --- |
| CORE | 已准备路由输入、已创建 context、已分配 encode 容量上的 compress_update + finalize / decompress；包含 API 内部描述符、staging/copy、帧、模型工作和 decode 物化 |
| PIPELINE | 外层准备、context 创建、bound/allocation、CORE、独立 stream 物化、计费、telemetry、close；decode 还含逆兼容操作 |
| E2E | 内存 canonical routed view 到完整 encode/decode 对象的流水线及阶段间开销；不含文件 I/O 或计时后的正确性检查 |

每个 inner iteration 是新建、Finalize、独立解码并关闭的完整对象。context 新建实现 reset，在 CORE 外；finalize 在 encode CORE 内。
CORE 不是纯 native kernel 时间。18 个重写入口仍没有可选 native 内部 timer，native_* 为 null，未用 CORE 数据冒充 NATIVE。
三个 scope 进入不同 ExecutionComparabilityKey，不能跨范围混合排名。详见 [边界说明](native_codec_timing.md)。

## 验证及证据

- 最终相关回归测试：**341 passed**，0 failures/errors/skipped；覆盖有损转换正反例、源域、容量、别名、计费和三模式五层路径。
- 共享执行依赖变化后，真实重建 8 个代表库，执行 6 组原生 release/debug/sanitizer 验证及 6 组直接 SDK 验证（103 / 159 / 888 / 322 / 466 / 499 项），再刷新 19 个整数入口的注册证据；未放宽哈希门禁。
- 全量检查在 CPU 2 串行执行，逐算法独立进程；每配置为 QUALIFICATION、1 次 repetition，结果 eligibility=false，不进入正式排名。
- 原始失败批次保留：首个审计工具不正确地把系统动态库路径当成项目相对路径；有损 oracle 暴露误差界传递缺陷；同进程加载模型库也曾使 XZ 预检受虚拟地址空间上限影响。最终核对使用共享代码修复后的全量批次及 6 个依赖门禁条目的新补测目录；逐项验证当前身份与原始文件哈希，不覆盖原失败报告。ND oracle 的合成输入生成来源也使用新目录修正并重新验证。
- 本次没有重新测量正式性能。旧正式记录和 JSON 审查报告保留冻结身份；18 个计时声明及 12 个 SDK closure 的 AlgorithmID 变化，旧证据不能重签为新身份。

[最终独立核对](../build/timing-scopes-20261008/final-verification.json) · [完整模式矩阵](../build/timing-scopes-20261008/verified-mode-matrix.json) · [原生/SDK重新验证](../build/timing-scopes-20261008/requalification.json) · [注册证据刷新](../build/source-audits/native-sdk-registry-refresh-20261008-timing-scopes-1/report.json)

另有 [Simple8b-RLE / LittleIntPacker 的独立 SDK 审计与注册刷新](../build/source-audits/rle-littleintpacker-sdk-refresh-20261008-timing-scopes-1/report.json)，原生构建保持既有且通过当前独立审计，本次重测 466 / 499 项 SDK 用例。

## 逐项结果

| 入口 | 类型 | CORE | PIPELINE | E2E | 数据集 / 冻结配置 |
| --- | --- | --- | --- | --- | --- |
| `abba` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/abba/runs/abba-core/frozen_config.json) |
| `alp` | NATIVE | PASS | PASS | PASS | [exchange_rate](../build/timing-scopes-20261008/matrix-final/alp/runs/alp-core/frozen_config.json) |
| `alp-rd` | NATIVE | PASS | PASS | PASS | [exchange_rate](../build/timing-scopes-20261008/matrix-final/alp-rd/runs/alp-rd-core/frozen_config.json) |
| `brotli-stream` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/brotli-stream/runs/brotli-stream-core/frozen_config.json) |
| `bzip2-stream` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/bzip2-stream/runs/bzip2-stream-core/frozen_config.json) |
| `chimp` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/chimp/runs/chimp-core/frozen_config.json) |
| `chimp128` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/chimp128/runs/chimp128-core/frozen_config.json) |
| `corad` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/corad/runs/corad-core/frozen_config.json) |
| `deepzip` | NATIVE | PASS | PASS | PASS | [rewrite_byte_uts](../build/timing-scopes-20261008/matrix-final/deepzip/runs/deepzip-core/frozen_config.json) |
| `deflate-zlib` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/deflate-zlib/runs/deflate-zlib-core/frozen_config.json) |
| `delta-maskedvbyte-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/delta-maskedvbyte-u32/runs/delta-maskedvbyte-u32-core/frozen_config.json) |
| `delta-simdcomp-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/delta-simdcomp-u32/runs/delta-simdcomp-u32-core/frozen_config.json) |
| `delta-varint` | NATIVE | PASS | PASS | PASS | [etth1](../build/timing-scopes-20261008/matrix-final/delta-varint/runs/delta-varint-core/frozen_config.json) |
| `delta-zigzag-streamvbyte-modern64` | NATIVE | PASS | PASS | PASS | [etth1](../build/timing-scopes-20261008/matrix-final/delta-zigzag-streamvbyte-modern64/runs/delta-zigzag-streamvbyte-modern64-core/frozen_config.json) |
| `delta-zigzag-streamvbyte64` | NATIVE | PASS | PASS | PASS | [etth1](../build/timing-scopes-20261008/matrix-final/delta-zigzag-streamvbyte64/runs/delta-zigzag-streamvbyte64-core/frozen_config.json) |
| `dzip` | NATIVE | PASS | PASS | PASS | [rewrite_byte_uts](../build/timing-scopes-20261008/matrix-final/dzip/runs/dzip-core/frozen_config.json) |
| `elf` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/elf/runs/elf-core/frozen_config.json) |
| `elf-plus` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/elf-plus/runs/elf-plus-core/frozen_config.json) |
| `elf-star` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/elf-star/runs/elf-star-core/frozen_config.json) |
| `fabba` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/fabba/runs/fabba-core/frozen_config.json) |
| `fast-differential-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/fast-differential-u32/runs/fast-differential-u32-core/frozen_config.json) |
| `fastpfor-simple8b-rle-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-six-fixed/fastpfor-simple8b-rle-u32/runs/fastpfor-simple8b-rle-u32-core/frozen_config.json) |
| `for-simdcomp-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/for-simdcomp-u32/runs/for-simdcomp-u32-core/frozen_config.json) |
| `fse` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/fse/runs/fse-core/frozen_config.json) |
| `huff0` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/huff0/runs/huff0-core/frozen_config.json) |
| `influxdb-tsm-adaptive-timestamp` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/influxdb-tsm-adaptive-timestamp/runs/influxdb-tsm-adaptive-timestamp-core/frozen_config.json) |
| `leats-lossless-i64` | NATIVE | PASS | PASS | PASS | [sprintz_i16_mts](../build/timing-scopes-20261008/matrix-final/leats-lossless-i64/runs/leats-lossless-i64-core/frozen_config.json) |
| `littleintpacker-bmi2-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-six-fixed/littleintpacker-bmi2-u32/runs/littleintpacker-bmi2-u32-core/frozen_config.json) |
| `littleintpacker-horizontal-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-six-fixed/littleintpacker-horizontal-u32/runs/littleintpacker-horizontal-u32-core/frozen_config.json) |
| `littleintpacker-pack32-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-six-fixed/littleintpacker-pack32-u32/runs/littleintpacker-pack32-u32-core/frozen_config.json) |
| `littleintpacker-sc-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-six-fixed/littleintpacker-sc-u32/runs/littleintpacker-sc-u32-core/frozen_config.json) |
| `littleintpacker-turbo-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-six-fixed/littleintpacker-turbo-u32/runs/littleintpacker-turbo-u32-core/frozen_config.json) |
| `lz4-frame` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/lz4-frame/runs/lz4-frame-core/frozen_config.json) |
| `lzss-dipperstein-c` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/lzss-dipperstein-c/runs/lzss-dipperstein-c-core/frozen_config.json) |
| `lzss-raw` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/lzss-raw/runs/lzss-raw-core/frozen_config.json) |
| `lzsse2-raw` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/lzsse2-raw/runs/lzsse2-raw-core/frozen_config.json) |
| `lzsse8-raw` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/lzsse8-raw/runs/lzsse8-raw-core/frozen_config.json) |
| `maskedvbyte-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/maskedvbyte-u32/runs/maskedvbyte-u32-core/frozen_config.json) |
| `neats-lossless-i64` | NATIVE | PASS | PASS | PASS | [sprintz_i16_mts](../build/timing-scopes-20261008/matrix-final/neats-lossless-i64/runs/neats-lossless-i64-core/frozen_config.json) |
| `oracle-direct` | ORACLE | PASS | PASS | PASS | [etth1](../build/timing-scopes-20261008/matrix-final/oracle-direct/runs/oracle-direct-core/frozen_config.json) |
| `oracle-lossless-adapter` | ORACLE | PASS | PASS | PASS | [etth1](../build/timing-scopes-20261008/matrix-final/oracle-lossless-adapter/runs/oracle-lossless-adapter-core/frozen_config.json) |
| `oracle-lossy-adapter` | ORACLE | PASS | PASS | PASS | [etth1](../build/timing-scopes-20261008/matrix-final/oracle-lossy-adapter/runs/oracle-lossy-adapter-core/frozen_config.json) |
| `oracle-native-nd-only` | ORACLE | PASS | PASS | PASS | [timing_scope_native_nd](../build/timing-scopes-20261008/nd-provenance-fixed/runs/oracle-native-nd-only-core/frozen_config.json) |
| `prometheus-float-histogram-st` | NATIVE | PASS | PASS | PASS | [rewrite_histogram_float](../build/timing-scopes-20261008/matrix-final/prometheus-float-histogram-st/runs/prometheus-float-histogram-st-core/frozen_config.json) |
| `prometheus-histogram-st` | NATIVE | PASS | PASS | PASS | [rewrite_histogram_int](../build/timing-scopes-20261008/matrix-final/prometheus-histogram-st/runs/prometheus-histogram-st-core/frozen_config.json) |
| `prometheus-xor-chunk` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/prometheus-xor-chunk/runs/prometheus-xor-chunk-core/frozen_config.json) |
| `prometheus-xor2-chunk` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/prometheus-xor2-chunk/runs/prometheus-xor2-chunk-core/frozen_config.json) |
| `self-star` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/self-star/runs/self-star-core/frozen_config.json) |
| `serf-qt` | NATIVE | PASS | PASS | PASS | [exchange_rate](../build/timing-scopes-20261008/matrix-final/serf-qt/runs/serf-qt-core/frozen_config.json) |
| `serf-xor` | NATIVE | PASS | PASS | PASS | [exchange_rate](../build/timing-scopes-20261008/matrix-final/serf-xor/runs/serf-xor-core/frozen_config.json) |
| `simdcomp-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/simdcomp-u32/runs/simdcomp-u32-core/frozen_config.json) |
| `simple16-u28` | NATIVE | PASS | PASS | PASS | [simple_uint28_uts](../build/timing-scopes-20261008/matrix-final/simple16-u28/runs/simple16-u28-core/frozen_config.json) |
| `simple9-u28` | NATIVE | PASS | PASS | PASS | [simple_uint28_uts](../build/timing-scopes-20261008/matrix-final/simple9-u28/runs/simple9-u28-core/frozen_config.json) |
| `simple9hacked-u28` | NATIVE | PASS | PASS | PASS | [simple_uint28_uts](../build/timing-scopes-20261008/matrix-final/simple9hacked-u28/runs/simple9hacked-u28-core/frozen_config.json) |
| `snappy-raw` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/snappy-raw/runs/snappy-raw-core/frozen_config.json) |
| `sprintz-delta` | NATIVE | PASS | PASS | PASS | [sprintz_i16_mts](../build/timing-scopes-20261008/matrix-final/sprintz-delta/runs/sprintz-delta-core/frozen_config.json) |
| `sprintz-delta-u8` | NATIVE | PASS | PASS | PASS | [sprintz_u8_uts](../build/timing-scopes-20261008/matrix-final/sprintz-delta-u8/runs/sprintz-delta-u8-core/frozen_config.json) |
| `sprintz-fire` | NATIVE | PASS | PASS | PASS | [sprintz_i16_mts](../build/timing-scopes-20261008/matrix-final/sprintz-fire/runs/sprintz-fire-core/frozen_config.json) |
| `sprintz-fire-huff0` | NATIVE | PASS | PASS | PASS | [sprintz_i16_mts](../build/timing-scopes-20261008/matrix-final/sprintz-fire-huff0/runs/sprintz-fire-huff0-core/frozen_config.json) |
| `sprintz-fire-u8` | NATIVE | PASS | PASS | PASS | [sprintz_u8_uts](../build/timing-scopes-20261008/matrix-final/sprintz-fire-u8/runs/sprintz-fire-u8-core/frozen_config.json) |
| `streamvbyte-modern-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/streamvbyte-modern-u32/runs/streamvbyte-modern-u32-core/frozen_config.json) |
| `streamvbyte-u32` | NATIVE | PASS | PASS | PASS | [streamvbyte_u32_uts](../build/timing-scopes-20261008/matrix-final/streamvbyte-u32/runs/streamvbyte-u32-core/frozen_config.json) |
| `tristan` | NATIVE | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/tristan/runs/tristan-core/frozen_config.json) |
| `walloc-1d` | NATIVE | PASS | PASS | PASS | [rewrite_audio_stereo](../build/timing-scopes-20261008/matrix-final/walloc-1d/runs/walloc-1d-core/frozen_config.json) |
| `xz-stream` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/xz-stream/runs/xz-stream-core/frozen_config.json) |
| `zfp-accuracy-1d` | NATIVE | PASS | PASS | PASS | [exchange_rate](../build/timing-scopes-20261008/matrix-final/zfp-accuracy-1d/runs/zfp-accuracy-1d-core/frozen_config.json) |
| `zstd-frame` | NATIVE | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/zstd-frame/runs/zstd-frame-core/frozen_config.json) |
| `delta-of-delta` | ALIAS | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/delta-of-delta/runs/delta-of-delta-core/frozen_config.json) |
| `gorilla` | ALIAS | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/gorilla/runs/gorilla-core/frozen_config.json) |
| `lz77` | ALIAS | PASS | PASS | PASS | [national_illness](../build/timing-scopes-20261008/matrix-final/lz77/runs/lz77-core/frozen_config.json) |
| `second-order-difference` | ALIAS | PASS | PASS | PASS | [rewrite_float_mts](../build/timing-scopes-20261008/matrix-final/second-order-difference/runs/second-order-difference-core/frozen_config.json) |

## 重跑

```bash
PYTHONPATH=src taskset -c 2 /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/verify_all_timing_scopes.py --output build/timing-scopes-new
```

输出目录必须是新目录，避免覆盖证据。只验证某些入口时可添加 `--keys chimp gorilla`；验证工具仍会执行三种 scope。
正常实验在 TOML 的 `[profile]` 中设置 `timing_scope = "CORE"`、`"PIPELINE"` 或 `"E2E"`，其余数据域、ISA、线程预算和资源上限保持对应算法的已注册要求。
DCT、DWT、PCA 按此前用户决定继续跳过，未注册或 BLOCKED 的候选不在此矩阵中。
