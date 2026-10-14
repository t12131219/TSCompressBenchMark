# SIMDComp MASKED SSE4.1／AVX2 实现路径对照

现有 `simdcomp-u32` 真实支持相同 `MASKED` API 的 `SSE4_1` 与 `AVX2` 两个 native 配置；它们可以对同一 `<u4` 向量做完整对象对照。这里没有已有 scalar codec 路径，因此不称 scalar/SIMD 消融，也不把结果归因于单独的向量位宽。

## 配置与固定输入

```bash
PYTHONPATH=benchmark/src python benchmark/examples/generate_isa_experiment.py
# 仅在独占的正式计时窗口执行：
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/isa-paths/experiment.toml
# 不调用 codec 的产物／路径／配对统计审计：
PYTHONPATH=benchmark/src python benchmark/examples/generate_isa_experiment.py \
  --audit-run runs/simd-paths-final-20261013
```

generator 只生成 NPY、TOML 和 preparation evidence，不编译、不调用 codec、不执行计时。已有文件内容不同时拒绝覆盖，需选择新的 preparation directory。

长度为 **257／4096／65536／1048576 个 uint32**，raw bytes 为其四倍。使用 `default_rng(20261013)` 生成单一 20-bit u32 向量，并每128个元素显式置高位，四种长度均取该向量的 prefix。每个128／256元素的完整块及最后tail都具有20-bit宽度，避免全部32-bit输入退化成原始 copy 路径。此合成分布只用于路径实验，不代表跨语料排名或全 uint32 域验证；nested prefixes 不是四个独立来源。

三个 method 为完整 wire 的 `raw-store`、`simd-sse-mask`、`simd-avx2-mask`。SSE 与 AVX2 均显式使用 `api=MASKED`、`starting_point=0`、`native_timing=false`。共同 task 为 bitwise values，边界为 `object_memory / independent_object / natural`，同一个 native_threads=1／object_workers=1 profile。正式预算是3独立sessions ×7rounds ×4lengths ×3methods＝**252 trials**，每worker2 warmup objects、loops=1。

## 真实 dispatch 与 flags 证据

- [native configuration](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/simdcomp/native/tscb_simdcomp.c:105) 将 canonical JSON 的 `MASKED`＋`SSE4_1` 选为 PLAIN mode0，`MASKED`＋`AVX2` 选为 AVX_PLAIN mode4。CPU ISA 不满足时返回 unsupported，不静默fallback。
- [source_pack](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/simdcomp/native/tscb_simdcomp.c:208) 的 SSE full block调用 `simdpack`，AVX full block调用 `tscb_simdcomp_avx2_pack`；后者在 [AVX bridge](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/simdcomp/native/avx2_bridge.c:9) 的 MASKED 分支实际调用 `avxpack`。decode 对应 `simdunpack`／`avxunpack`。
- [block_size](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/simdcomp/native/tscb_simdcomp.c:83) 是 SSE128／AVX256；AVX尾块调用 SSE `simdpack_length`／`simdunpack_length`，SSE MASKED短尾调用 `simdpack_shortlength`／`simdunpack_shortlength`。257元素分别形成2个SSE完整块＋1tail、1个AVX完整块＋1tail。
- 实际 installed `build.json` 的 per-TU commands 为 SSE source `-msse4.1 -mno-avx -mno-avx2 -mno-avx512f`，AVX source `-mavx2 -mno-avx512f`。shim 使用baseline禁SIMD／自动向量化flags，不代表整个codec scalar。generator核对这些实际命令，并保存binary／build／source SHA-256。
- 原始 SBP1 frame保存 mode、block size/count、每block逻辑长度、width、layout和payload size。正式run后的audit读取每个saved wire、校验descriptor／payload hash，并验证mode0／128和mode4／256以及20-bit实际block记录。source dispatch＋实际flags＋本次wire模式共同提供路径证据；不把仅CPU支持某ISA当作执行证据。

原生内部 block 几何、目录开销、tail API、width scan、staging和checksum均随这两个真实实现路径变化。完整对象主表将这些成本全部计入；不要求两路径native payload bytewise相同。两条路径的canonical对象与实际送入codec的typed input identity必须相同，且每trial独立恢复并核对自己的wire。

## 统计与限制

audit仅纳入每个方法同一session／round的完整成功配对。每个session先取7个round的 SSE／AVX2 比率median，再对3个独立session median给出median／Q1／Q3／IQR。encode／decode的比率>1表示该实际对象边界下AVX2较快，stored bytes比率>1表示AVX2完整产物较小；它不是孤立向量位宽speedup或native kernel排名。

`preparation.json` 是事前输入、params、编译／source证据；正式manifest、observations、report与`path_audit.json`才是执行／结果证据。准备成功不能称已完成正式测量。运行缺少ISA／库或出现恢复错误时，保留其unsupported／unavailable／error，不用成功子集冒称完整请求矩阵。

## 2026-10-13 正式测量与审计结果

本次正式 run 为 [simd-paths-final-20261013](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/simd-paths-final-20261013/manifest.json)，12个ready cases完整执行 **252／252 primary trials，全部OK**。只读审计确认预定的3sessions ×7rounds ×4lengths ×3methods均有最早执行的primary attempt，得到 **84个完整三方法配对rounds**。raw-store、SSE与AVX2使用相同canonical raw typed对象；SSE与AVX2的实际codec input identity／bytes也相同。审计逐一重新读取各trial引用的wire，校验其SHA-256、descriptor和native payload hash，并检查所有SIMD frame的实际mode／block／width记录。

实际保存的native frame几何如下。frame bytes仅为SBP1 native payload；下一张统计表的stored bytes包含完整TSB对象产物，二者不混用。所有full block及tail的实际width均为20。

| 方法 | uint32元素数 | mode／block size | full calls／tail calls | native frame bytes |
|---|---:|---|---|---:|
| AVX2 MASKED | 257 | 4／256 | 1／1 | 720 |
| SSE4.1 MASKED | 257 | 0／128 | 2／1 | 728 |
| AVX2 MASKED | 4096 | 4／256 | 16／0 | 10416 |
| SSE4.1 MASKED | 4096 | 0／128 | 32／0 | 10544 |
| AVX2 MASKED | 65536 | 4／256 | 256／0 | 165936 |
| SSE4.1 MASKED | 65536 | 0／128 | 512／0 | 167984 |
| AVX2 MASKED | 1048576 | 4／256 | 4096／0 | 2654256 |
| SSE4.1 MASKED | 1048576 | 0／128 | 8192／0 | 2687024 |

下表比率均为 **SSE／AVX2**。median和IQR取3个独立session的配对round比率median；不是把21个round合并成独立样本。完整stored bytes的session IQR均为0。

| uint32元素数 | encode比率median | encode比率IQR | decode比率median | decode比率IQR | 完整stored bytes比率median |
|---:|---:|---:|---:|---:|---:|
| 257 | 1.019484 | 0.195055 | 1.031100 | 0.042213 | 1.004755 |
| 4096 | 1.004995 | 0.049049 | 0.998348 | 0.071232 | 1.011011 |
| 65536 | 1.050050 | 0.071135 | 0.976031 | 0.029127 | 1.012251 |
| 1048576 | 1.013328 | 0.037382 | 1.015632 | 0.018637 | 1.012340 |

这些数据说明本机上两个真实实现路径在完整对象边界的时间比率接近1，部分session差异足以改变时间比率方向；不能据此给出全局性能胜者或断言AVX向量位宽造成固定加速。AVX2产物在本输入上较小，与较少的256元素block记录一致。该尺寸结论只适用于这里固定的20-bit合成向量及其prefix，不能推广到其他分布。路径间block几何、记录数、tail API、staging等均同时变化。

执行与分析证据：

| 证据 | SHA-256 |
|---|---|
| [事前准备](/home/fzg/PycharmProjects/TSDataCompressBenchMark/benchmark/experiments/isa-paths/preparation.json) | `93449f435fec3763b783b54398d252eab4fe973314083fd7260c7924cd58430e` |
| [正式manifest](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/simd-paths-final-20261013/manifest.json) | `0103ab22bea1b484437071a55570e7df6cafbf3696000517594a2835772906ac` |
| [原始observations](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/simd-paths-final-20261013/observations.jsonl) | `238781eceff463ea2ae85051200567e1b3b47878a9afda7ac885359b74010777` |
| [路径与配对统计审计](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/simd-paths-final-20261013/path_audit.json) | `4576d650fc3ce7308fb77030822d86b88fee30ada4610269a55b46049893e501` |

正式准备后，审计代码修正了wire artifact定位：代表性row可直接使用`artifact_path`，其余row依据`artifact_hash`定位run内的content-addressed文件；同时加入完整schedule及raw对象一致性检查。这些是分析代码修正，未修改core、配置、fixtures或原始测量，也未重跑计时。原始generator已保存在 [generator_at_preparation.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/benchmark/experiments/isa-paths/generator_at_preparation.py)，其SHA-256 `e7f850db28631b6e32aa719c7e36c4d17e8eb0b0853d600e24405f72025941a4`与冻结`preparation.json`相符。当前 [generator／audit helper](/home/fzg/PycharmProjects/TSDataCompressBenchMark/benchmark/examples/generate_isa_experiment.py) 的SHA-256为 `e79a6ffd83f455eedb304361bad59bb77c83cdc4cd3159a1cb08203dc814f3d7`，单独记录在`path_audit.json`的`audit_code`字段。保持冻结的准备证据不变；重新生成实验应使用新的preparation directory与run输出路径。
