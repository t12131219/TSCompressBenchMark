# Sprintz C/C++ 独立移植

依据 V3.0 §114，从作者原生 C++ 实现移植构建、C ABI、容量和所有权，
修复已复现的长度、内存及整数未定义行为。四个主算法共享同一核心：

| AlgorithmID | predictor | huffman |
|---|---:|---:|
| sprintz-delta | 0 | 0 |
| sprintz-fire | 1 | 0 |
| sprintz-delta-huffman | 0 | 1 |
| sprintz-fire-huffman | 1 | 1 |

输入为 row-major 的 8/16 位整数位模式，ndims=1..128，每次最多65536字节；
每次调用重置预测器。支持空输入、不完整行和尾块；不隐式量化浮点。
已验平台为 Linux x86_64，GCC11.4/Clang14，AVX2/BMI1/BMI2/LZCNT/POPCNT。
C ABI 与 ISA 核心分开编译，入口在调用原生指令前检查 CPU 能力。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j4
ctest --test-dir build --output-on-failure
cmake --install build --prefix "$PWD/install"
```

公开头为 `include/sprintz_port.h`，安装产物含 shared/static 库及 CLI。
CLI 参数：`enc|dec width predictor huffman path ndims input output expected_bytes`。
例如16位四维 FIRE + Huffman：

```sh
build/sprintz_cli enc 16 1 1 0 4 input.u16 output.sz 0
build/sprintz_cli dec 16 1 1 0 4 output.sz restored.u16 32768
```

`expected_bytes` 在编码时不使用，解码时是原始字节数。
path0自动派发、1强制general RLE、2强制lowdim RLE（8位1..4维，16位1..2维），
3仅bitpack、4 Delta去RLE、5历史8位FIRE去RLE。3/4要求predictor0，5要求1。
所有入口都有编码和解码；输入输出可重叠，失败时输出不变且produced=0。

原生16位返回长度可能截掉最后一个字节，本包输出完整 raw 码流；作者
Huffman 包装的 `reported_elements*2+1` 规则保留。兼容结论按该修复区分，
不能笼统宣称原版所有 raw 输出 BYTE_IDENTICAL。

`tools/experiments.py` 验证历史1D、仅预测器和原地恢复；这些为研究驱动，
不安装或暴露为安全 C ABI。query probe 只证明可构建及一个 materialize
用例，不证明 SUM/MAX 数学结果。其它 FSE/Zstd/Bzip2 组合、不完整 kayak、
online/search 辅助能力的来源和范围均在矩阵中保留，没有并入四个主算法资格。

完整报告见 `docs/VALIDATION_REPORT.md`；逐能力范围见 `docs/MATRICES.json`。
这是限定范围的原生移植验收，不是 REWRITE_DONE、FULL_PARITY 或 Bench 接入。

可复现检查：

```sh
python3 tools/extract_oracle.py
python3 tools/offline_replay.py
```

第二条在临时新目录重放补丁、构建未修改原版 oracle 和移植库，执行差分、
冻结数据、独立解码与安装消费者验证；不需要 Benchmark 源码或网络。
ASan/UBSan/LSan、TSan、libFuzzer 的构建及运行脚本和原始日志保存在
`tools/`、`tests/`、`evidence/`；原生目录通过补丁与原件保持可审计关系。
