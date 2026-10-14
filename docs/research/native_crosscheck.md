# V4 直接 native 与 Python bridge 交叉核对

实施日期：2026-10-13。代码：[C reference](../../benchmark/tests/native/reference.c)、[复跑驱动](../../benchmark/tools/native_crosscheck.py)。实测证据：[native_crosscheck.json](native_crosscheck.json)。本次 Zstd / LZSS 各运行 empty、single byte、257-byte tail 三项；6 项完整 payload 与恢复 bytes 全部逐字节相同，C/Python buffer 与 native timing 结构体的大小、逐字段 offset 一致。

C reference 通过 `dlopen` 调用本次构建的真实 `tscb_*` 函数，接收显式原始 byte 文件和与 Python bridge 相同的原生 config JSON。`bound`、input/output allocation、encoder create/reset 均在计时外；编码计时段是 compress + finalize，两个实际输出区间计时后紧凑拼接。解码使用独立新 handle，prepare 在计时外，计时段只包含 decompress；输出 byte 数与 memcmp 在计时后核对。所有 handle 随后销毁。Zstd 的非零 Finish tail 被单独保存和核对，LZSS 的零输出 finalize 也实际调用。

这些时间是 `CLOCK_MONOTONIC` 的具名 **native API 诊断**，包括原生 checksum 等实际 API 内工作。它们排除 Python/FFI、外层 descriptor、create/reset/destroy、bound、分配、文件 IO 和 verifier；不能直接与 `object_memory` 排名或将二者差值全部归因于 Python。每项仅一次操作，目的在于核对 bridge 输出、容量/长度和边界，未提供性能分布或科学性能结论。

复跑从仓库根目录执行：

```bash
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
python -m tsbench build zstd-frame lzss-raw
python benchmark/tools/native_crosscheck.py
```

证据保存实际库 hash、reference source hash、输入/payload hash、bound/compress/finalize/payload 长度、结构体大小和原始时间。工具重新编译 reference 并执行两个真实库，不借用 encoder handle 给 decoder。它只验证这两个 byte API 及本次输入范围，不将结果推广到其他 dtype、codec、上游实现或第二环境。
