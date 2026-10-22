# cameo-family

2026-10-21 · **REWRITE_DONE / FULL_PARITY**，资格目标为用户授权的 `cameo-family-repaired-v1`，须与匹配的最终归档审计共同生效。

所有实现位于本目录，包含 CAMEO/SIP、VW、PIP、TP、SWAB、Sim-Piece、PMC-Mean、connected SWING、DFT、**DWT(DCT-II)**。稳定标识为 `dwt-dct-ii`，原版 `DWTCompressor` 实际执行正交 DCT-II。

已实现独立 C++17/C11 API、JSON-lines/二进制文件 CLI、完整 CF01 帧及独立恢复。生产端无 Python 或 Benchmark 依赖。Linux x86_64 已完成源语义差分；AArch64/QEMU 已完成 API/安全及跨架构独立恢复。构建依赖 C++17、CMake、OpenMP 及随包冻结的源码数值库。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j3
ctest --test-dir build --output-on-failure
cmake --install build --prefix stage
printf '%s\n' '{"algorithm":"DWT(DCT-II)","operation":"encode","values":[1,2,3,4],"config":{"fraction":0.5}}' | build/cameo_cli
```

- [完整验证报告](docs/VALIDATION_REPORT.md)
- [修复补丁与TP边界语义](docs/REPAIRS.md)
- [原版缺陷历史](docs/UPSTREAM_DEFECTS.md)
- [接口与帧格式](docs/API.md)
- [源码映射](docs/SOURCE_MAP.md)
- [来源与许可](NOTICE.md)
- [离线复验](docs/REPRODUCIBILITY.md)

主参考来自 Apache-2.0 的 damslab/reproducibility `edbt2026-CAMEO`；PMC/SWING/Sim-Piece 使用 CAMEO 引用的 TerseTS 数值核心。原始 cmcuza/cameo 只用于发现与数据定位。原版文件未被修改，安全修补参考程序单独保存在 `oracle-control`，对应差分位于 `Source/cameo-family/PATCHES`。

最终验证包括 GCC/Clang 各598项源差分、194项边界、80项TP回归、20个实际数值内核的460项差分、1196次跨架构冷解码，以及ASan/UBSan/LSan、TSan与119160次fuzz。50项必需能力全部PASS，零waiver；原版失败和旧BLOCKED历史保留。

DWT(DCT-II)默认使用O(N log N)快速变换，保留强制标量路径；512项对照及131072最大长度恢复通过。默认生产从源码构建OpenBLAS C LAPACK，不依赖Python、GFortran或Quadmath。C ABI v1/CF01保持兼容；C++ Config布局变化，消费者须重编译。

双目录8产物逐字节复现及最终包实际解包重建/安装消费记录见离线复验文档和外层audit.json。源语义资格针对修复参考与x86_64匹配CPU模型；ARM为模拟执行的API/恢复范围，不承诺跨架构编码字节相同。安全插桩范围与原生汇编边界见NUMERICAL_DEPENDENCY.md。本包不含Bench接入或FORMAL声明。
