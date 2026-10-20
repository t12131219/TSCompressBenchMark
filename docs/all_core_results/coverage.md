# 全注册表原生覆盖

每个请求始终计入请求分母；资格失败与未执行请求不产生吞吐数字。一个完整案例要求其所有计划批次成功且执行源未改变。CSV 的 raw_object_id、raw_bytes、dtype、shape 和 layout 描述冻结请求；actual_raw_object_id、actual_raw_bytes 与 input_geometry_verified 区分实际加载证据，数据缺失时不冒充已验证输入。

| codec | prepared 请求／ready／完整／成功批次 | fresh_request 请求／ready／完整／成功批次 |
|---|---:|---:|
| abba | 1 / 1 / 1 / 14 | 1 / 1 / 1 / 14 |
| alp | 9 / 7 / 7 / 98 | 9 / 7 / 7 / 98 |
| alp-rd | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| brotli-stream | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| bzip2-stream | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| chimp | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| chimp128 | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| deepzip | 2 / 2 / 2 / 28 | 2 / 2 / 2 / 28 |
| deflate-zlib | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| dzip | 3 / 3 / 3 / 42 | 3 / 3 / 3 / 42 |
| elf | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| elf-plus | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| elf-star | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| fabba | 1 / 1 / 1 / 14 | 1 / 1 / 1 / 14 |
| fse | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| gorilla-prometheus-xor | 2 / 2 / 2 / 28 | 2 / 2 / 2 / 28 |
| huff0 | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| leats-lossless-i64 | 2 / 2 / 2 / 28 | 2 / 2 / 2 / 28 |
| lz4-frame | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| lzss-dipperstein-c | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| lzss-raw | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| lzsse2-raw | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| lzsse8-raw | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| neats-lossless-i64 | 2 / 2 / 2 / 28 | 2 / 2 / 2 / 28 |
| raw-store | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| self-star | 9 / 9 / 9 / 126 | 9 / 9 / 9 / 126 |
| serf-qt | 4 / 4 / 4 / 56 | 4 / 4 / 4 / 56 |
| serf-xor | 4 / 4 / 4 / 56 | 4 / 4 / 4 / 56 |
| simdcomp-u32 | 1 / 1 / 1 / 14 | 1 / 1 / 1 / 14 |
| snappy-raw | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| sprintz-delta | 3 / 2 / 2 / 28 | 3 / 2 / 2 / 28 |
| sprintz-delta-u8 | 1 / 1 / 1 / 14 | 1 / 1 / 1 / 14 |
| sprintz-fire | 3 / 2 / 2 / 28 | 3 / 2 / 2 / 28 |
| sprintz-fire-huff0 | 3 / 2 / 2 / 28 | 3 / 2 / 2 / 28 |
| sprintz-fire-u8 | 1 / 1 / 1 / 14 | 1 / 1 / 1 / 14 |
| xz-stream | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |
| zfp-accuracy-1d | 4 / 4 / 4 / 56 | 4 / 4 / 4 / 56 |
| zstd-frame | 5 / 5 / 5 / 70 | 5 / 5 / 5 / 70 |

## 每个请求的状态

| 配置／案例 | dtype／shape／布局 | 任务／生命周期 | admission | 成功批次／计划 | 状态计数 | 原因 |
|---|---|---|---|---:|---|---|
| native-all-real-prepared.toml / etth1-values-c/raw-store/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/brotli-stream/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/bzip2-stream/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/deflate-zlib/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/lz4-frame/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/lzss-dipperstein-c/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/lzss-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/lzsse2-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/lzsse8-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/snappy-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/xz-stream/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/zstd-frame/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/alp/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | unsupported | 0/0 | {} | rowgroup selects ALP-RD; forced ALP forbids fallback  |
| native-all-real-prepared.toml / etth1-values-c/alp-rd/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/chimp/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/chimp128/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/elf/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/elf-plus/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/elf-star/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-c/self-star/cpu-single | <f8 / [8192, 7] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/raw-store/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/brotli-stream/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/bzip2-stream/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/deflate-zlib/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/lz4-frame/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/lzss-dipperstein-c/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/lzss-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/lzsse2-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/lzsse8-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/snappy-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/xz-stream/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/zstd-frame/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/alp/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | unsupported | 0/0 | {} | rowgroup selects ALP-RD; forced ALP forbids fallback  |
| native-all-real-prepared.toml / etth1-values-f/alp-rd/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/chimp/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/chimp128/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/elf/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/elf-plus/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/elf-star/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / etth1-values-f/self-star/cpu-single | <f8 / [8192, 7] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/raw-store/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/brotli-stream/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/bzip2-stream/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/deflate-zlib/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/lz4-frame/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/lzss-dipperstein-c/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/lzss-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/lzsse2-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/lzsse8-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/snappy-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/xz-stream/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/zstd-frame/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/alp/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/alp-rd/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/chimp/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/chimp128/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/elf/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/elf-plus/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/elf-star/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-c/self-star/cpu-single | <f8 / [32768, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/raw-store/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/brotli-stream/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/bzip2-stream/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/deflate-zlib/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/lz4-frame/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/lzss-dipperstein-c/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/lzss-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/lzsse2-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/lzsse8-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/snappy-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/xz-stream/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/zstd-frame/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/alp/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/alp-rd/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/chimp/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/chimp128/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/elf/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/elf-plus/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/elf-star/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / weather-values-f/self-star/cpu-single | <f8 / [32768, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/raw-store/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/brotli-stream/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/bzip2-stream/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/deflate-zlib/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/lz4-frame/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/lzss-dipperstein-c/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/lzss-raw/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/lzsse2-raw/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/lzsse8-raw/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/snappy-raw/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/xz-stream/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/zstd-frame/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/alp/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/alp-rd/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/chimp/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/chimp128/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/elf/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/elf-plus/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/elf-star/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-prepared.toml / ili-values-c/self-star/cpu-single | <f8 / [512] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/raw-store/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/brotli-stream/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/bzip2-stream/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/deflate-zlib/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/lz4-frame/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/lzss-dipperstein-c/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/lzss-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/lzsse2-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/lzsse8-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/snappy-raw/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/xz-stream/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/zstd-frame/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/alp/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | unsupported | 0/0 | {} | rowgroup selects ALP-RD; forced ALP forbids fallback  |
| native-all-real-fresh.toml / etth1-values-c/alp-rd/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/chimp/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/chimp128/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/elf/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/elf-plus/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/elf-star/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-c/self-star/cpu-single | <f8 / [8192, 7] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/raw-store/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/brotli-stream/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/bzip2-stream/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/deflate-zlib/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/lz4-frame/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/lzss-dipperstein-c/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/lzss-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/lzsse2-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/lzsse8-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/snappy-raw/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/xz-stream/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/zstd-frame/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/alp/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | unsupported | 0/0 | {} | rowgroup selects ALP-RD; forced ALP forbids fallback  |
| native-all-real-fresh.toml / etth1-values-f/alp-rd/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/chimp/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/chimp128/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/elf/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/elf-plus/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/elf-star/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / etth1-values-f/self-star/cpu-single | <f8 / [8192, 7] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/raw-store/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/brotli-stream/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/bzip2-stream/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/deflate-zlib/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/lz4-frame/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/lzss-dipperstein-c/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/lzss-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/lzsse2-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/lzsse8-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/snappy-raw/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/xz-stream/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/zstd-frame/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/alp/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/alp-rd/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/chimp/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/chimp128/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/elf/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/elf-plus/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/elf-star/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-c/self-star/cpu-single | <f8 / [32768, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/raw-store/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/brotli-stream/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/bzip2-stream/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/deflate-zlib/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/lz4-frame/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/lzss-dipperstein-c/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/lzss-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/lzsse2-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/lzsse8-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/snappy-raw/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/xz-stream/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/zstd-frame/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/alp/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/alp-rd/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/chimp/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/chimp128/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/elf/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/elf-plus/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/elf-star/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / weather-values-f/self-star/cpu-single | <f8 / [32768, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/raw-store/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/brotli-stream/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/bzip2-stream/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/deflate-zlib/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/lz4-frame/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/lzss-dipperstein-c/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/lzss-raw/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/lzsse2-raw/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/lzsse8-raw/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/snappy-raw/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/xz-stream/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/zstd-frame/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/alp/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/alp-rd/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/chimp/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/chimp128/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/elf/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/elf-plus/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/elf-star/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-real-fresh.toml / ili-values-c/self-star/cpu-single | <f8 / [512] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float64-c/fse/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float64-c/huff0/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float64-f/fse/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float64-f/huff0/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float32-c/fse/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float32-c/huff0/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float32-f/fse/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / float32-f/huff0/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / uint8-c/fse/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-prepared.toml / uint8-c/huff0/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float64-c/fse/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float64-c/huff0/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float64-f/fse/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float64-f/huff0/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float32-c/fse/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float32-c/huff0/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float32-f/fse/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / float32-f/huff0/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / uint8-c/fse/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-entropy-fresh.toml / uint8-c/huff0/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/alp/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/alp-rd/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/chimp/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/chimp128/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/elf/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/elf-plus/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/elf-star/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-c/self-star/cpu-single | <f8 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/alp/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/alp-rd/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/chimp/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/chimp128/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/elf/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/elf-plus/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/elf-star/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float64-f/self-star/cpu-single | <f8 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/alp/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/alp-rd/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/chimp/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/chimp128/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/elf/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/elf-plus/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/elf-star/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-c/self-star/cpu-single | <f4 / [257, 3] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/alp/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/alp-rd/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/chimp/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/chimp128/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/elf/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/elf-plus/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/elf-star/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-prepared.toml / float32-f/self-star/cpu-single | <f4 / [257, 3] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/alp/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/alp-rd/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/chimp/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/chimp128/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/elf/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/elf-plus/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/elf-star/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-c/self-star/cpu-single | <f8 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/alp/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/alp-rd/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/chimp/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/chimp128/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/elf/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/elf-plus/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/elf-star/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float64-f/self-star/cpu-single | <f8 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/alp/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/alp-rd/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/chimp/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/chimp128/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/elf/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/elf-plus/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/elf-star/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-c/self-star/cpu-single | <f4 / [257, 3] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/alp/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/alp-rd/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/chimp/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/chimp128/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/elf/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/elf-plus/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/elf-star/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-floats-fresh.toml / float32-f/self-star/cpu-single | <f4 / [257, 3] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-prepared.toml / int16-c/neats-lossless-i64/cpu-single | <i2 / [257, 2] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-prepared.toml / int16-c/leats-lossless-i64/cpu-single | <i2 / [257, 2] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-prepared.toml / int16-f/neats-lossless-i64/cpu-single | <i2 / [257, 2] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-prepared.toml / int16-f/leats-lossless-i64/cpu-single | <i2 / [257, 2] / F | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-fresh.toml / int16-c/neats-lossless-i64/cpu-single | <i2 / [257, 2] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-fresh.toml / int16-c/leats-lossless-i64/cpu-single | <i2 / [257, 2] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-fresh.toml / int16-f/neats-lossless-i64/cpu-single | <i2 / [257, 2] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-models-fresh.toml / int16-f/leats-lossless-i64/cpu-single | <i2 / [257, 2] / F | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-prepared.toml / int16-c/sprintz-delta/cpu-single | <i2 / [257, 2] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-prepared.toml / int16-c/sprintz-fire/cpu-single | <i2 / [257, 2] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-prepared.toml / int16-c/sprintz-fire-huff0/cpu-single | <i2 / [257, 2] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-prepared.toml / int16-f/sprintz-delta/cpu-single | <i2 / [257, 2] / F | values/bitwise/prepared | unsupported | 0/0 | {} | Sprintz requires C uint8/uint16 rank1/2 with 1..128 channels  |
| native-all-integer-matrix-prepared.toml / int16-f/sprintz-fire/cpu-single | <i2 / [257, 2] / F | values/bitwise/prepared | unsupported | 0/0 | {} | Sprintz requires C uint8/uint16 rank1/2 with 1..128 channels  |
| native-all-integer-matrix-prepared.toml / int16-f/sprintz-fire-huff0/cpu-single | <i2 / [257, 2] / F | values/bitwise/prepared | unsupported | 0/0 | {} | Sprintz requires C uint8/uint16 rank1/2 with 1..128 channels  |
| native-all-integer-matrix-prepared.toml / uint8-c/sprintz-delta/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-prepared.toml / uint8-c/sprintz-fire/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-prepared.toml / uint8-c/sprintz-fire-huff0/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-fresh.toml / int16-c/sprintz-delta/cpu-single | <i2 / [257, 2] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-fresh.toml / int16-c/sprintz-fire/cpu-single | <i2 / [257, 2] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-fresh.toml / int16-c/sprintz-fire-huff0/cpu-single | <i2 / [257, 2] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-fresh.toml / int16-f/sprintz-delta/cpu-single | <i2 / [257, 2] / F | values/bitwise/fresh_request | unsupported | 0/0 | {} | Sprintz requires C uint8/uint16 rank1/2 with 1..128 channels  |
| native-all-integer-matrix-fresh.toml / int16-f/sprintz-fire/cpu-single | <i2 / [257, 2] / F | values/bitwise/fresh_request | unsupported | 0/0 | {} | Sprintz requires C uint8/uint16 rank1/2 with 1..128 channels  |
| native-all-integer-matrix-fresh.toml / int16-f/sprintz-fire-huff0/cpu-single | <i2 / [257, 2] / F | values/bitwise/fresh_request | unsupported | 0/0 | {} | Sprintz requires C uint8/uint16 rank1/2 with 1..128 channels  |
| native-all-integer-matrix-fresh.toml / uint8-c/sprintz-delta/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-fresh.toml / uint8-c/sprintz-fire/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-matrix-fresh.toml / uint8-c/sprintz-fire-huff0/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-u8-prepared.toml / uint8-c/sprintz-delta-u8/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-u8-prepared.toml / uint8-c/sprintz-fire-u8/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-u8-fresh.toml / uint8-c/sprintz-delta-u8/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-u8-fresh.toml / uint8-c/sprintz-fire-u8/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-u32-prepared.toml / uint32-c/simdcomp-u32/cpu-single | <u4 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-integer-u32-fresh.toml / uint32-c/simdcomp-u32/cpu-single | <u4 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float64-c/serf-qt/cpu-single | <f8 / [257, 3] / C | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float64-c/serf-xor/cpu-single | <f8 / [257, 3] / C | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float64-c/zfp-accuracy-1d/cpu-single | <f8 / [257, 3] / C | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float64-f/serf-qt/cpu-single | <f8 / [257, 3] / F | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float64-f/serf-xor/cpu-single | <f8 / [257, 3] / F | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float64-f/zfp-accuracy-1d/cpu-single | <f8 / [257, 3] / F | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float32-c/serf-qt/cpu-single | <f4 / [257, 3] / C | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float32-c/serf-xor/cpu-single | <f4 / [257, 3] / C | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float32-c/zfp-accuracy-1d/cpu-single | <f4 / [257, 3] / C | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float32-f/serf-qt/cpu-single | <f4 / [257, 3] / F | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float32-f/serf-xor/cpu-single | <f4 / [257, 3] / F | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-prepared.toml / float32-f/zfp-accuracy-1d/cpu-single | <f4 / [257, 3] / F | values/bounded_abs/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float64-c/serf-qt/cpu-single | <f8 / [257, 3] / C | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float64-c/serf-xor/cpu-single | <f8 / [257, 3] / C | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float64-c/zfp-accuracy-1d/cpu-single | <f8 / [257, 3] / C | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float64-f/serf-qt/cpu-single | <f8 / [257, 3] / F | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float64-f/serf-xor/cpu-single | <f8 / [257, 3] / F | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float64-f/zfp-accuracy-1d/cpu-single | <f8 / [257, 3] / F | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float32-c/serf-qt/cpu-single | <f4 / [257, 3] / C | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float32-c/serf-xor/cpu-single | <f4 / [257, 3] / C | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float32-c/zfp-accuracy-1d/cpu-single | <f4 / [257, 3] / C | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float32-f/serf-qt/cpu-single | <f4 / [257, 3] / F | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float32-f/serf-xor/cpu-single | <f4 / [257, 3] / F | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-bounded-fresh.toml / float32-f/zfp-accuracy-1d/cpu-single | <f4 / [257, 3] / F | values/bounded_abs/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-empirical-prepared.toml / ili-values-c/abba/cpu-single | <f8 / [512] / C | values/empirical_quality/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-empirical-prepared.toml / ili-values-c/fabba/cpu-single | <f8 / [512] / C | values/empirical_quality/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-empirical-fresh.toml / ili-values-c/abba/cpu-single | <f8 / [512] / C | values/empirical_quality/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-empirical-fresh.toml / ili-values-c/fabba/cpu-single | <f8 / [512] / C | values/empirical_quality/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-deepzip-prepared.toml / symbols4-c-n64/deepzip/cpu-single | \|u1 / [64] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-deepzip-fresh.toml / symbols4-c-n64/deepzip/cpu-single | \|u1 / [64] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-dzip-prepared.toml / symbols4-c-n64/dzip/cpu-dzip-three | \|u1 / [64] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-dzip-fresh.toml / symbols4-c-n64/dzip/cpu-dzip-three | \|u1 / [64] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-records-prepared.toml / etth1-records-c/gorilla-prometheus-xor/cpu-single | <f8 / [512] / C | records/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-records-prepared.toml / weather-records-c/gorilla-prometheus-xor/cpu-single | <f8 / [512] / C | records/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-all-records-fresh.toml / etth1-records-c/gorilla-prometheus-xor/cpu-single | <f8 / [512] / C | records/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-all-records-fresh.toml / weather-records-c/gorilla-prometheus-xor/cpu-single | <f8 / [512] / C | records/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-neural-deepzip-prepared.toml / symbols4-c/deepzip-biGRU/cpu-single | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-neural-deepzip-fresh.toml / symbols4-c/deepzip-biGRU/cpu-single | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-neural-dzip-prepared.toml / symbols4-c/dzip-bootstrap/cpu-dzip-three | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-neural-dzip-prepared.toml / symbols4-c/dzip-combined/cpu-dzip-three | \|u1 / [257] / C | values/bitwise/prepared | ready | 14/14 | {"ok":14} | {} |
| native-neural-dzip-fresh.toml / symbols4-c/dzip-bootstrap/cpu-dzip-three | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
| native-neural-dzip-fresh.toml / symbols4-c/dzip-combined/cpu-dzip-three | \|u1 / [257] / C | values/bitwise/fresh_request | ready | 14/14 | {"ok":14} | {} |
