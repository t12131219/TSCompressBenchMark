# ALP / ALP-RD 独立 C++ 原生移植包

基于 cwida/ALP `31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce`（MIT），按
《Compression Algorithm C/C++ Porting Standard v3.0》第 114 章的
**NATIVE_PORT / N0–N5** 路线交付，派生版本 `safe-v1`。两个算法共享一份
核心；`alp` 自动选择十进制 ALP 或 RD，`alp-rd` 强制使用 RD。

支持 binary32/binary64、任意 IEEE 位模式、空输入/尾块、独立冷解码。
包含容量上界、原子失败 C ABI、CLI、CRC 和完整恢复元数据；没有 RAW
回退。上游数值安全修复保存在可重放补丁中。当前资格限定于本包声明的
原生 profile；**不宣称上游 FULL_PARITY、跨语言重写或 Benchmark 已接入**。

## 构建与使用

需要 CMake >=3.22、GCC 11 或 Clang 14、C++17；默认构建无需联网。

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release -j4
ctest --test-dir build/release --output-on-failure
build/release/alp_cli info
build/release/alp_cli encode f64 alp input.raw output.alp 1
build/release/alp_cli decode f64 alp output.alp restored.raw 1
build/release/alp_cli encode f32 alp-rd input32.raw output.rd 1
cmake --install build/release --prefix "$PWD/dist/x86_64-portable"
```

CLI 输入 raw 是小端 IEEE 数组，长度必须为元素字节数的整数倍。CLI 的
最后一项是 API 内重复次数（1..100）；计时包含临时分配、拷贝、补零、
采样、编码/解码和 CRC，排除文件读写、bound 与调用者输出分配。日志仅
作功能诊断，不能用于 FORMAL 性能排名。C API 见 `include/alp_port.h`；
输入输出借用，可接受未对齐字节地址。缓冲区及结果指针别名合同见
`docs/CONTRACT.md`。最大 2^24 个值；这是资源上限，不是全规模实测声明。

## 复验

原版位于同级 `../../Source/alp-cwida/upstream`。若只复制本包，默认构建
和测试仍可运行；源 oracle 与 patch 重放另外需要这份冻结快照。

```bash
python3 tools/replay_patch.py
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release -DALP_PORT_ORACLE=ON
cmake --build build/release -j4
python3 tools/verify.py --out reports/replay
# 七份真实 CSV 的所有数值列、所有行、两个精度和两种方法：
python3 tools/verify.py --out reports/replay-real \
  --corpus /home/fzg/PycharmProjects/材料/TSBench_Corpus
```

正式证据使用 `reports/verification-qualified/verification.json`，原始
输入、原版/移植版流和完整命令同目录保存。源码 oracle 是独立驱动和
独立原版编译单元，不链接 `alp_port`。新增外层 frame 由驱动承载；raw
比较包含全部向量元数据、字典、FFOR 字和异常。原版的非法 factor=10
流单列为预期拒绝，并保留最初发现时的失败报告。

```bash
cmake -S . -B build/avx2 -DCMAKE_BUILD_TYPE=Release -DALP_PORT_AVX2=ON
cmake --build build/avx2 -j4
ctest --test-dir build/avx2 --output-on-failure
cmake -S . -B build/asan -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_C_COMPILER=clang \
  -DALP_PORT_SANITIZER=address,undefined
cmake --build build/asan -j4
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 \
  ctest --test-dir build/asan --output-on-failure
```

AVX2 是显式编译配置，运行前必须确认 CPU 支持；没有 runtime dispatch。
本机 sanitizer 映射冲突用 `setarch x86_64 -R` 仅关闭测试进程的 ASLR；
LSan 需在允许 ptrace 的环境运行。TSan 用 `ALP_PORT_SANITIZER=thread`；
测试命令 `build/tsan/alp_tests concurrency`。TSan 的强 new/delete 符号与
测试分配注入冲突，该注入由 release/ASan 验证，不放入 TSan 构建。

Fuzz 配置额外加 `-DALP_PORT_FUZZ=ON`，编译器选 Clang，sanitizer 同上。
复制 `reports/fuzz-seeds` 到新的可写 corpus，运行：

```bash
build/fuzz/alp_fuzz /tmp/alp-fuzz-corpus -runs=50000 \
  -seed=1095520305 -max_len=20000 -timeout=10
```

AArch64 使用项目局部工具链（不随生产包安装），设置
`ALP_ARM_TOOLCHAIN` 后以 `-DCMAKE_TOOLCHAIN_FILE=tools/arm64.cmake` 配置。
实际执行经过 QEMU，系统库和 QEMU 自身不在 sanitizer 插桩范围。

## 审阅入口

- `docs/CONTRACT.md`：输入域、FP、资源、wire、失败与验证计划。
- `docs/NATIVE_CAPABILITY_MATRIX.yaml`、`docs/MATRICES.md`：完整源能力与本次范围。
- `docs/SOURCE_DEFECTS.md`、`patches/INDEX.json`：四类源 UB、补丁与差异。
- `reports/QUALIFICATION.json`、`reports/QUALIFICATION.md`：N0–N5 结论与证据索引。
- `reports/BUILD_LOCK.json`、`docs/SOURCE_LOCK.json`、`SBOM.json`：实际闭包及许可证。
- `HANDOFF.md`：独立消费入口和后续 Bench 绑定的验收边界。

上游声明的 AVX-512、publication 的 AVX2/NEON fused decoder 等能力保留
在 inventory，但本次 profile 未开放。当前 AVX2 build 使用上游 `src`
路径及其编译器向量化，不冒称调用 publication 中的另一套 intrinsic 内核。
