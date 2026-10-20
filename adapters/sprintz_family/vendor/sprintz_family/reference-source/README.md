# Sprintz 原版冻结

原生 C++ 核心来自 dblalock/sprintz，commit
`a056cdb67d049669875ab5487359aca99ae873ea`，Apache-2.0。
FIRE 在源码中名为 `xff`。主入口为 `upstream/core/sprintz.cpp`。

论文配套 dblalock/lzbench，commit
`580c4f085381f31b1ad669525ed04e63cbc385f3`，在
`upstream/lzbench/_lzbench/compressors.cpp` 定义 Delta/FIRE + Huff0 组合，
`lzbench.h` 注册主算法、去 RLE、仅 bitpack、预测器、历史 1D、查询等路径。
实际 Huffman 是该仓库附带的 Zstd Huff0（BSD-2-Clause），不是 Sprintz
`entropy.cpp` 中未完成的 kayak 实验。

本目录原件不应用补丁。逐文件哈希见 SOURCE_MANIFEST.json。
可重放补丁、独立 API、四矩阵及验证在 `../../ReWrite/sprintz-family`。
采用 V3.0 §114 NATIVE_PORT，保留 AVX2/BMI2 核心，不冒充重新翻译。
