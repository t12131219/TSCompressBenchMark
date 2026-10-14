# Native API 与完整 object wire 边界实验

本实验让 Zstd／LZSS 的三条路径使用相同的实际输入字节，并把完整对象成本与最小 native API 区间分别记录。固定 seed 的小字母表 fixture 用来诊断调用边界，不作为真实语料的 codec 排名。

入口为 [boundary_experiment.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/benchmark/tools/boundary_experiment.py)，独立 C 对照复用 [reference.c](/home/fzg/PycharmProjects/TSDataCompressBenchMark/benchmark/tests/native/reference.c)。C helper 原有 `encode_ns`／`decode_ns` 和输出语义保留，只增加 prepare／postprocess 字段。没有将 codec 内部 timer 伪装为独立 C 基准。

## 执行

必须先已有 codec 构建。本工具不会重编或更换 codec binary，只编译独立 C helper。正式实验与其他计时任务串行运行。

```bash
PYTHONPATH=benchmark/src python benchmark/tools/boundary_experiment.py \
  --output-dir runs/boundary-final-20261013 \
  --preload /usr/lib/x86_64-linux-gnu/libstdc++.so.6 \
  --preload /home/fzg/anaconda3/lib/libgcc_s.so.1 \
  --sessions 3 --rounds 7
```

默认 codec 为 `zstd-frame`、`lzss-raw`；长度为 **0／1／257／4096／65536／1048576 bytes**。对象是连续一维 `uint8` 数组，元素个数恰等于 byte 数，0／1 两种输入无需 padding。fixture 使用 NumPy `default_rng(20261013)` 生成 `0..15` 符号；原始 bytes、dtype、shape、layout、seed 和 SHA-256 全部保存。codec params 采用卡片解析后的默认配置，并明确禁用 native timer instrumentation。

每个 codec／长度有 3 个独立 Python subprocess session，每个 session 7 rounds；三条路径在 round 内按 session／round 轮换顺序。每次操作只执行一次，`loops=1`；没有 auto batching、空循环校正或 overhead subtraction。每个 direct C round 又启动独立 standalone executable。

## 边界

| 路径 | Encode 计时 | Decode 计时 | 主计时外工作 |
|---|---|---|---|
| `direct_c` | `CLOCK_MONOTONIC` 包围 `compress` ＋成功时的 `finalize` | 包围单次 `decompress` | library load、input file IO、create/reset、bound、分配、输出合并、destroy、核对与写盘 |
| `python_native_api` | `perf_counter_ns` 包围 prepared ctypes `compress` ＋成功时的 `finalize` | 包围 prepared ctypes `decompress` | source buffer copy、handle create/reset、bound、所有分配和 ctypes pointer 准备、status checking、输出 materialize、destroy、核对与写盘 |
| `object_wire` | 生产路径 `ObjectScheme.encode_once` 返回完整 wire | 生产路径 `decode_once` 返回完整 typed object | fixture 构建、`prepare`、返回后的最终核对和写盘 |

Python prepared API 使用与生产 bridge 相同的 native library、config JSON 和 `Buffer` ABI，在工具内部准备 handle／buffer／pointer，不修改 core bridge。compress 和 finalize 各自通过真实 ctypes 调用；该区间自然包含 Python dispatch、参数 marshaling、status branch 及 timer 成本。C 路径在独立进程内调用相同 ABI，不经过 Python FFI。两者都对每次 encode／decode 创建、reset、destroy 独立 handle，encoder 与 decoder 无状态共享。

`object_wire` 包含 registry/schema 检查、复制／partition、native session 创建与销毁、bound、分配、实际 native API、input／payload 身份计算、descriptor JSON／checksum／prefix、完整 wire，以及 decode 的 descriptor／payload 核对和对象分配。`prepare_ns` 单独记录 `ObjectScheme` 构造与 `prepare`；库缓存可以延续至同 session 的其他 rounds，codec handle 不延续。

C 的 `encode_prepare_ns` 从 raw bytes 已读入内存后开始，涵盖 descriptor／handle／bound／allocation；`decode_prepare_ns` 涵盖独立 decoder／reset／output allocation／descriptor。Python 对应 prepare 还包括 ctypes storage copy／pointer 构造。prepare 区间本身并非严格相同工作量，因此不把它们的差额视作单一 FFI 成本。postprocess 字段包含输出 materialize／status check／destroy，C decode postprocess 还包含 helper 的 bitwise verification；这些原始字段用于解释工作边界，不参与 matched API 比率。

## 身份与验证

每个 round 保留 typed object identity、实际 native input SHA-256／length、native payload SHA-256／length、decoded bytes SHA-256／length、完整 wire 与 header SHA-256／length、descriptor checksum、codec input aggregate identity、params、binary／build record 身份。header 包含完整 wire prefix 与 descriptor，满足 `wire == header + native_payload`。

每条路径的 decoded bytes 必须与原始 bytes 一致，typed 输入不能被修改；三条 native payload 必须 bytewise 相同。object bridge 记录的实际 input hash／length 必须匹配 standalone C 与 prepared Python 的 raw bytes。所有 retained artifacts 再次从磁盘读回，核对 length／SHA-256，并重组 header＋payload 验证 wire。产物按 SHA-256 在 `artifacts/` 中去重，round rows 仍逐条引用。

manifest 保存 tool／helper／ABI header／相关 core 文件、compiler／version、独立 executable 的 SHA-256 和完整编译命令。每个 Python session 保存 Python／NumPy／platform、PID、`LD_PRELOAD`、requested preload 的 resolved target／hash，以及 native library 加载后的 `/proc/self/maps` 实际运行库证据。C helper 在主计时外另外读取自己的 `/proc/self/maps`，返回实际 `.so` paths，由 worker 逐文件计算 SHA-256；C 的 runtime 证据与 Python 的 maps 分开记录，不从同一环境推定二者必然加载相同库。C/Python 的 Buffer／NativeTiming ABI size 与全部 field offsets 同时核对。

当前 Conda Python 在 NumPy import 时加载其 `libgcc_s`，仅 preload system `libstdc++` 时 standalone C 会选 system `libgcc_s`。上面命令将现有 Conda `libgcc_s` 也显式 preload，控制两条路径的重叠运行库身份；无需修改或安装任何库。每个 round 的 `runtime_overlap` 单独记录重叠库名、hash 相同性和具体差异，避免把不同 runtime 下的 API 比率当作单独 FFI 成本。独立 C 的 PID／parent PID 也进入原始 row。

session 层和 standalone C 调用层都有 timeout／returncode 检查。native crash 被隔离在 child，失败写成明确 error row；session timeout 杀死该 session 的 process group，包含仍运行的 C child。缺失 round 不计为成功。

## 结果文件与解释

输出目录包含：

- `observations.jsonl`：所有 round 的原始 ns、边界定义、配对 ratio、输入／产物身份和验证结果。
- `*-session-*.jsonl`：独立 session 日志，发生 crash 时已经完成的 rows 仍可追溯。
- `manifest.json`：完整执行和代码身份；`reference` 为独立 C executable。
- `summary.json`／`summary.md`：分 codec／length／boundary／operation 的 median、Q1、Q3、IQR。
- `artifacts/`：内容寻址的所有输入、payload、restored、header、wire。

统计主单位是独立 session：先在每个 session 内取 7 个 round 的 median，再对 3 个 session median 报告 median／IQR。所有 21 rounds 的 descriptive median／IQR 另存。3 个 session 的分布仍较小；原始数据保留供增加 session 后复算。

只有边界明确匹配的 **Python prepared native API / standalone C native API** encode 和 decode 区间计算 paired ratio。它是观测比率，受 Python／C 调度与 timer、进程／cache 状态、准备和内存状态等共同影响，不能视为单独的 FFI 因果估计。完整 object 与 native API 工作不同，其时间差不能全部称为 FFI overhead；本网格不为两者生成 matched ratio。

## 验证

[test_boundary.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/benchmark/tests/test_boundary.py) 覆盖 deterministic fixture、session 层统计、ratio 分类、完整产物核对、typed/raw identity 错配、artifact 损坏、subprocess 非零退出及 timeout。测试本身不编译 native、也不执行正式 benchmark。

## 本次正式结果（2026-10-13）

**252／252 paired rounds 成功，0 error**：2 codecs × 6 lengths × 3 独立 Python sessions × 7 rounds。保留 36 个不同 Python PID、252 个不同 C PID；全部 C parent PID 与对应 Python session PID 相符。252 rounds 的 C／Python 重叠运行库 SHA-256 全部相同，未发现 runtime difference。

结果见 [原始 JSONL](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/observations.jsonl)、[完整 median／IQR JSON](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/summary.json)、[统计表](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/summary.md)、[manifest](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/manifest.json) 和 [独立读回审计](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/audit.json)。审计重新核对 2520 条产物记录，实际去重为 40 个文件共 4,183,633 bytes；22 个源代码／binary／compiler／runtime 身份文件一致，204 组 session 统计从原始 rows 重算完全相同。

下表 API encode／decode 为 ns 换算后的 µs；均为 3 个独立 session median 的 median。比率是每个 round 的 prepared Python API／standalone C API，先在 session 内取 median，再汇总；括号为 3 个 session median 的 IQR。完整各边界时间的 Q1／Q3／IQR 见统计 JSON。

| Codec | Bytes | C encode µs | Python/C encode（IQR） | C decode µs | Python/C decode（IQR） | Object encode µs | Object decode µs |
|---|---:|---:|---:|---:|---:|---:|---:|
| zstd-frame | 0 | 12.643 | 0.354 (0.043) | 15.041 | 0.152 (0.018) | 235.571 | 1607.113 |
| zstd-frame | 1 | 13.628 | 0.384 (0.036) | 14.154 | 0.167 (0.033) | 222.534 | 1535.480 |
| zstd-frame | 257 | 21.299 | 0.395 (0.051) | 14.237 | 0.336 (0.049) | 231.311 | 1528.605 |
| zstd-frame | 4096 | 75.830 | 0.377 (0.066) | 11.568 | 0.744 (0.033) | 266.247 | 1551.953 |
| zstd-frame | 65536 | 231.447 | 0.340 (0.038) | 75.047 | 0.558 (0.011) | 456.645 | 1647.695 |
| zstd-frame | 1048576 | 5561.606 | 0.940 (0.021) | 1153.641 | 0.819 (0.018) | 8397.383 | 3288.201 |
| lzss-raw | 0 | 4.223 | 0.607 (0.049) | 0.211 | 4.519 (0.730) | 194.529 | 1552.047 |
| lzss-raw | 1 | 5.051 | 0.616 (0.027) | 0.248 | 3.331 (0.710) | 210.200 | 1541.959 |
| lzss-raw | 257 | 138.359 | 0.963 (0.228) | 3.020 | 1.104 (0.093) | 272.292 | 1583.888 |
| lzss-raw | 4096 | 1699.255 | 0.904 (0.081) | 16.597 | 1.022 (0.069) | 1585.289 | 1645.239 |
| lzss-raw | 65536 | 22659.768 | 1.001 (0.001) | 223.056 | 0.968 (0.012) | 23072.226 | 1933.192 |
| lzss-raw | 1048576 | 364237.835 | 0.998 (0.002) | 3510.320 | 0.940 (0.026) | 366786.455 | 6141.458 |

Zstd 的若干 prepared Python／C 比率低于 1：这并不表示负 FFI 成本。C 每 round 重启独立进程，Python 在同 session 重复 7 rounds，process／library／cache 状态不同；实际测量同时包含这些效应。LZSS 0／1 byte decode 的比率较高，也只能按记录的边界和条件解释。若要因果分离 FFI，需要进一步控制同样的进程与 cache 生命周期，不能从当前比率直接减出单一开销。

| Codec | Actual input bytes | Native payload bytes | Wire header bytes | Full wire bytes |
|---|---:|---:|---:|---:|
| zstd-frame | 0 | 13 | 1378 | 1391 |
| zstd-frame | 1 | 14 | 1378 | 1392 |
| zstd-frame | 257 | 164 | 1389 | 1553 |
| zstd-frame | 4096 | 2138 | 1395 | 3533 |
| zstd-frame | 65536 | 32807 | 1401 | 34208 |
| zstd-frame | 1048576 | 541374 | 1412 | 542786 |
| lzss-raw | 0 | 0 | 1327 | 1327 |
| lzss-raw | 1 | 2 | 1327 | 1329 |
| lzss-raw | 257 | 263 | 1339 | 1602 |
| lzss-raw | 4096 | 3536 | 1345 | 4881 |
| lzss-raw | 65536 | 55224 | 1351 | 56575 |
| lzss-raw | 1048576 | 881308 | 1362 | 882670 |

每个长度／codec 的 21 rounds 产物 identity 和长度一致。空 LZSS 的 native payload 为 0 bytes，完整对象仍需 1327 bytes header；该差异属于可独立解码对象的完整表示成本，不能只报告 native payload 的比率。

| 原始证据 | SHA-256 |
|---|---|
| [manifest.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/manifest.json) | `61fe6919b717e0b209b9a575ae791846f2db88aaa4717ff0bc8f5347ed9e5895` |
| [observations.jsonl](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/observations.jsonl) | `9ec41dc92bd5692c09c201a831b35e177e8215529bd50977ab6093b503b66680` |
| [summary.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/summary.json) | `c048f3918859c01d59bb2a33a704104ba125a2b04fa742860ed76c0e02ff9789` |
| [summary.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/boundary-final-20261013/summary.md) | `744228cc13cb8fffe42fa98ff5579f3e378d3834247d9ddf146fc0b5a894ca72` |
