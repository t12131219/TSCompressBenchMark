# 活动算法登记与 CSV 对照（2026-10-10）

以当前根 manifest 为“登记入口”，不把别名、源码库存、候选行或历史 PASS 当作独立已运行算法。用户本次退出决定优先于原 CSV 建议。

当前 40 根项：33 个范围内真实入口、3 个范围外旧残留、4 个框架 oracle；另有 1 个别名。每种变体可能共享 CSV 行，组合未必有同名单独行。

## 范围内的 33 个真实入口

| Codec key | CSV 记录与算法名 | 对照说明 |
|---|---|---|
| [`abba`](../registry/codecs/abba.json) | V19 · ABBA | 对应算法行；执行 profile 以 manifest 为准 |
| [`alp`](../registry/codecs/alp.json) | V68 · ALP | 对应算法行；执行 profile 以 manifest 为准 |
| [`alp-rd`](../registry/codecs/alp-rd.json) | V69 · ALP_RD | 对应算法行；执行 profile 以 manifest 为准 |
| [`brotli-stream`](../registry/codecs/brotli-stream.json) | V8 · Brotli | 对应算法行；执行 profile 以 manifest 为准 |
| [`chimp`](../registry/codecs/chimp.json) | V62 · Chimp | 对应算法行；执行 profile 以 manifest 为准 |
| [`chimp128`](../registry/codecs/chimp128.json) | V63 · Chimp128 | 对应算法行；执行 profile 以 manifest 为准 |
| [`deepzip`](../registry/codecs/deepzip.json) | V90 · DeepZip | 对应算法行；执行 profile 以 manifest 为准 |
| [`deflate-zlib`](../registry/codecs/deflate-zlib.json) | V1 · LZ77；V4 · DEFLATE | V4 为完整 DEFLATE，V1 为其中 LZ77 机制；不另称独立原始 LZ77 |
| [`dzip`](../registry/codecs/dzip.json) | V91 · DZip | 对应算法行；执行 profile 以 manifest 为准 |
| [`elf`](../registry/codecs/elf.json) | V65 · Elf | 对应算法行；执行 profile 以 manifest 为准 |
| [`elf-plus`](../registry/codecs/elf-plus.json) | V66 · Elf+ | 对应算法行；执行 profile 以 manifest 为准 |
| [`elf-star`](../registry/codecs/elf-star.json) | V67 · Elf* / SElf* | V67 中的 Elf* 变体 |
| [`fabba`](../registry/codecs/fabba.json) | V20 · fABBA | 对应算法行；执行 profile 以 manifest 为准 |
| [`fse`](../registry/codecs/fse.json) | V120 · FSE | 对应算法行；执行 profile 以 manifest 为准 |
| [`huff0`](../registry/codecs/huff0.json) | V119 · Huff0 | 对应算法行；执行 profile 以 manifest 为准 |
| [`leats-lossless-i64`](../registry/codecs/leats-lossless-i64.json) | V100 · NeaTS / LeaTS | V100 中的 LeaTS 变体，当前登记 lossless-i64 |
| [`lz4-frame`](../registry/codecs/lz4-frame.json) | V5 · LZ4 | 对应算法行；执行 profile 以 manifest 为准 |
| [`lzss-dipperstein-c`](../registry/codecs/lzss-dipperstein-c.json) | V2 · LZSS | V2；不同实现来源，无额外同名独立行 |
| [`lzss-raw`](../registry/codecs/lzss-raw.json) | V2 · LZSS | V2；实现来源为 alexkazik/lzss |
| [`neats-lossless-i64`](../registry/codecs/neats-lossless-i64.json) | V100 · NeaTS / LeaTS | V100 中的 NeaTS 变体，当前登记 lossless-i64 |
| [`self-star`](../registry/codecs/self-star.json) | V67 · Elf* / SElf* | V67 中的 SElf* 变体；无另一个独立行 |
| [`serf-qt`](../registry/codecs/serf-qt.json) | V85 · Serf-Qt | 对应算法行；执行 profile 以 manifest 为准 |
| [`serf-xor`](../registry/codecs/serf-xor.json) | V86 · Serf-XOR | 对应算法行；执行 profile 以 manifest 为准 |
| [`simdcomp-u32`](../registry/codecs/simdcomp-u32.json) | T53 · SIMDComp | 保留原始 bit packing；Delta/FOR 组合已退出 |
| [`snappy-raw`](../registry/codecs/snappy-raw.json) | V6 · Snappy | 对应算法行；执行 profile 以 manifest 为准 |
| [`sprintz-delta`](../registry/codecs/sprintz-delta.json) | V55 · Sprintz-Delta | 共享算法行的 dtype/预测配置；CSV 无此 key 的单独行 |
| [`sprintz-delta-u8`](../registry/codecs/sprintz-delta-u8.json) | V55 · Sprintz-Delta | 共享算法行的 dtype/预测配置；CSV 无此 key 的单独行 |
| [`sprintz-fire`](../registry/codecs/sprintz-fire.json) | V56 · Sprintz-FIRE | 共享算法行的 dtype/预测配置；CSV 无此 key 的单独行 |
| [`sprintz-fire-huff0`](../registry/codecs/sprintz-fire-huff0.json) | V56 · Sprintz-FIRE；V119 · Huff0 | V56＋V119 组合；CSV 无此组合的同名单独行 |
| [`sprintz-fire-u8`](../registry/codecs/sprintz-fire-u8.json) | V56 · Sprintz-FIRE | 共享算法行的 dtype/预测配置；CSV 无此 key 的单独行 |
| [`xz-stream`](../registry/codecs/xz-stream.json) | V9 · LZMA / xz | 对应算法行；执行 profile 以 manifest 为准 |
| [`zfp-accuracy-1d`](../registry/codecs/zfp-accuracy-1d.json) | V87 · zfp | 对应算法行；执行 profile 以 manifest 为准 |
| [`zstd-frame`](../registry/codecs/zstd-frame.json) | V7 · Zstandard (Zstd) | 对应算法行；执行 profile 以 manifest 为准 |

## 本次未要求删除的 3 个旧残留登记

| Codec key | CSV 对照 | 当前限制 |
|---|---|---|
| `bzip2-stream` | **CSV 无对应保留记录** | 本地构建产物缺失；有登记不等于可运行，不计入 33 个范围内入口 |
| `lzsse2-raw` | **CSV 无对应保留记录** | 本地构建产物缺失；有登记不等于可运行，不计入 33 个范围内入口 |
| `lzsse8-raw` | **CSV 无对应保留记录** | 本地构建产物缺失；有登记不等于可运行，不计入 33 个范围内入口 |

## 框架 oracle 与别名

`oracle-direct`、`oracle-lossless-adapter`、`oracle-lossy-adapter`、`oracle-native-nd-only` 均为框架测试入口，**CSV 无对应算法行**，不进入真实算法性能榜。

`lz77` 是 `deflate-zlib` 的保留别名，对应 V1/V4 的机制与完整算法关系，不增加一个 Codec 或覆盖分母。其他三个指向已退出 Prometheus 实现的别名已删除。

本对照记录入口和 CSV 关系，不宣称全数据、全参数、源码全域一致性或 FORMAL 性能资格。运行证据见[退出与回归记录](algorithm_retirement_20261010.md)，后续规范见[V3](../TimeSeries_Compression_Benchmark_V3_工程实施总计划.md)。
