# 最终原生资格网格（2026-10-13）

最终迁移构建和六组正式测量完成后，36 个 codec 在全新 Python 子进程中完整重跑原始资格网格：**848 案例＝834 成功＋14 预期源域拒绝，0 非预期拒绝、0 错误**。按 codec 分组共有 **62 个唯一参数配置**，覆盖 DeepZip 的全部 **17 个 model_key**。

完整身份、参数配置、运行环境、实际映射库和逐 codec 计数见 [最终汇总 JSON](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/native_qualification_final_summary.json)；逐案例输入／payload／decoded SHA-256 见 [原始 final grid](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/tsbench/native_qualification_final.json)。本次是正确性资格验证，`elapsed_seconds` 不能作为 benchmark 性能结果。

## 执行与证据

```bash
env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libstdc++.so.6 PYTHONPATH=benchmark/src python benchmark/tools/qualify_native_assets.py --output build/tsbench/native_qualification_final.json
```

| 字段 | 本次记录 |
|---|---|
| Python | `3.11.5 (main, Sep 11 2023, 13:54:46) [GCC 11.2.0]` |
| Executable | `/home/fzg/anaconda3/bin/python` |
| NumPy | `1.24.3` |
| Platform | `Linux-6.8.0-101-generic-x86_64-with-glibc2.35` |
| LD_PRELOAD | `/usr/lib/x86_64-linux-gnu/libstdc++.so.6` |
| 独立子进程 | 36 个不同 PID |
| 公共桥接身份 SHA-256 | `50d2d69db7397deca355e65a0ab208c5f24b789faf5f8e0df373f29c3f988e24` |
| raw final grid SHA-256 | `1142fa5f967e9d955f292942b2edc18420038963403c9b1baa01f13d90b64d7a` |

每个 codec 的 child 在 native bridge 加载后调用 `loaded_runtime(build.runtime_dependencies)`，直接读取 `/proc/self/maps`。36 个 child 均实际映射 `/usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.30`；requested preload 的 literal path、resolved target 和 SHA-256 另外记录。Conda 的 `libgcc_s.so.1` 等其他实际运行库也逐条保留。这里的 runtime 证据来自运行中的 child，不是 `ldd` 推断。

汇总时再次核对了 120 个唯一文件的当前 SHA-256，包括 binary、build record、codec card、资格脚本、bridge 和实际 runtime；36 个 build ID／binary path 均与当前 index 相符。桥接身份包括 registry、runtime、errors 和全部 bridge Python 文件。每个原始 codec record 另存规范 JSON SHA-256。

## 逐 codec 覆盖

| Codec | 案例 | 成功 | 预期拒绝 | 错误 | 参数配置 | Build identity（前 12 位） |
|---|---:|---:|---:|---:|---:|---|
| abba | 3 | 3 | 0 | 0 | 1 | `949070c1adbd` |
| alp | 8 | 8 | 0 | 0 | 1 | `a02b3e0559c3` |
| alp-rd | 8 | 8 | 0 | 0 | 1 | `419786b4cf72` |
| brotli-stream | 42 | 42 | 0 | 0 | 1 | `60723f6c189e` |
| bzip2-stream | 42 | 42 | 0 | 0 | 1 | `571dcaa23339` |
| chimp | 10 | 8 | 2 | 0 | 1 | `9caa6a8ec555` |
| chimp128 | 10 | 8 | 2 | 0 | 1 | `7432b574247e` |
| deepzip | 22 | 21 | 1 | 0 | 17 | `390bad5b4c90` |
| deflate-zlib | 42 | 42 | 0 | 0 | 1 | `18ac2ee66c72` |
| dzip | 6 | 5 | 1 | 0 | 2 | `19e5e136d7ef` |
| elf | 10 | 8 | 2 | 0 | 1 | `db09805b5425` |
| elf-plus | 10 | 8 | 2 | 0 | 1 | `af12e793639d` |
| elf-star | 10 | 8 | 2 | 0 | 1 | `f4c71f1c1924` |
| fabba | 3 | 3 | 0 | 0 | 1 | `4d42aca15fc1` |
| fse | 42 | 42 | 0 | 0 | 1 | `fcce8e771aa7` |
| huff0 | 42 | 42 | 0 | 0 | 1 | `43d95c78c68b` |
| leats-lossless-i64 | 14 | 14 | 0 | 0 | 2 | `d32b40240784` |
| lz4-frame | 42 | 42 | 0 | 0 | 1 | `b6cb50343af6` |
| lzss-dipperstein-c | 42 | 42 | 0 | 0 | 1 | `66c08a767ba3` |
| lzss-raw | 42 | 42 | 0 | 0 | 1 | `12bc0bb8e828` |
| lzsse2-raw | 42 | 42 | 0 | 0 | 1 | `65153e18aab7` |
| lzsse8-raw | 42 | 42 | 0 | 0 | 1 | `64376bf33d9f` |
| neats-lossless-i64 | 14 | 14 | 0 | 0 | 2 | `54d03ead1ee7` |
| self-star | 10 | 8 | 2 | 0 | 1 | `257ff0565ddd` |
| serf-qt | 12 | 12 | 0 | 0 | 2 | `818cabd76d0d` |
| serf-xor | 12 | 12 | 0 | 0 | 2 | `22445ea960a0` |
| simdcomp-u32 | 48 | 48 | 0 | 0 | 5 | `ac571a87eb1b` |
| snappy-raw | 42 | 42 | 0 | 0 | 1 | `e56abdd55197` |
| sprintz-delta | 24 | 24 | 0 | 0 | 1 | `b06c6aa92616` |
| sprintz-delta-u8 | 4 | 4 | 0 | 0 | 1 | `12b04c9e9207` |
| sprintz-fire | 24 | 24 | 0 | 0 | 1 | `456962aef884` |
| sprintz-fire-huff0 | 24 | 24 | 0 | 0 | 1 | `972edbe35772` |
| sprintz-fire-u8 | 4 | 4 | 0 | 0 | 1 | `ca22b645af6f` |
| xz-stream | 42 | 42 | 0 | 0 | 1 | `362b2653d4bc` |
| zfp-accuracy-1d | 12 | 12 | 0 | 0 | 2 | `e697ceee3ca8` |
| zstd-frame | 42 | 42 | 0 | 0 | 1 | `c7aae2644e2e` |

参数 hash 只标识精确 resolved params；比较结果时还需一并使用 codec、build、binary、bridge 和 runtime 身份。配置规范化采用 `json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` 的 UTF-8 SHA-256，预期拒绝案例也计入配置统计。

网格覆盖各 codec 声明的 dtype、17/257 尾部长度、支持的三列矩阵／空输入，以及 byte codec 支持的 rank 3/4；SIMDComp 的五种合法 ISA/API、边界长度和 full-width u32；Sprintz 的 signed/high-bit pattern；DeepZip 的 17 个模型；DZip 的两种模式；Serf/zfp 的两个指定误差界。完整形状、case names、逐配置观测误差保留在 JSON。

## 适用范围与历史证据

本次 raw report 是完整重跑，没有合并旧 codec rows。历史 `native_qualification.json` 及历史 summary 未改写，final 文件独立保存。旧记录的阶段／路径／局限继续按原证据解释。

该网格只证明记录的输入、参数、binary 和 bridge；不证明通用输入域正确性、upstream parity、所有合法参数／ISA／长度／特殊浮点位模式，也不证明 streaming、query、GPU 或性能。ABBA/fABBA 的有限重建和经验误差不构成严格误差保证。

NeaTS/LeaTS 在大 i64 epoch／span 的 identity 时间戳输入上曾出现真实 bitwise mismatch，见 [专项分析](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/neats_timestamp_failure_analysis.md)。本网格未覆盖该域，不能用本次 0 错误推翻已有反例；timestamp affine GCD 方案的正式资格与结果由独立 run 记录。

本次没有重跑 wire-only decoder 或 build dependency drift 探针；相关旧证据保持历史属性，不绑定为本次完整重跑的一部分。

| 保留的历史文件 | SHA-256 |
|---|---|
| [native_qualification.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/tsbench/native_qualification.json) | `86cb911aff4ae6d0636e45db1c05f134cc1d7b0eaf8be3e313da5de6a8e6617a` |
| [native_qualification_summary.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/native_qualification_summary.json) | `b3f988005e7e611044c2e9d80fb67e42a13dd6e52b995e424dcac1d4a911420a` |
| [native_qualification_summary.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/native_qualification_summary.md) | `b55af50b882b7f29f4f8cd97ed845cd12e0759a12bf1c620eab4455cebe97d4e` |
