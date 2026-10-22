# 构建与离线复验

工程在 `ReWrite/cameo-family`，冻结来源在同一资产根的 `Source/cameo-family`。独立生产构建要求Linux、C/C++17、CMake≥3.16、OpenMP；已执行GCC11.4、Clang14和AArch64/GCC11。默认从包内源码构建数值依赖，无网络、Python或Fortran生产依赖。C++ Config布局有扩展，应重新编译消费者；C ABI v1与CF01保持兼容。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j4
ctest --test-dir build --output-on-failure
cmake --install build --prefix stage
cc -std=c11 tests/c_consumer.c -Istage/include -Lstage/lib -lcameo_family \
  -Wl,-rpath,"$PWD/stage/lib" -o stage/consumer
./stage/consumer
c++ -std=c++17 tests/cpp_consumer.cpp -Istage/include \
  stage/lib/libcameo_family_static.a stage/lib/libcf_pocketfft.a \
  stage/lib/libcf_lapack.a -fopenmp -lm -pthread -o stage/cpp-consumer
./stage/cpp-consumer
```

`python3 tools/reproduce_build.py --label release-final` 在两个独立源码/构建目录运行Release构建、测试、安装C11/C++17消费者。`validation/reproducibility-release-final.json` 比较8个产物，包括完整源码数值库，逐字节一致。这不是跨编译器/跨架构字节一致承诺。最终解包审计再实际重建，并与这8个hash逐一比对。

参考程序仅用于验证：CPython3.11、Cython3.0.12、NumPy1.24.3、SciPy1.11.1、Zig0.15.2及离线wheels已冻结。分别执行 bootstrap_oracle.py、build_oracle.py、build_diagnostics.py、build_control_oracle.py、build_repaired_oracle.py；原版、CONTROL、repaired参考相互独立。原作和修复补丁的原始字节均验证hash，绝不覆盖原始源码。

```sh
python3 tools/verify_differential.py --repaired --native build/cameo_cli --output differential-new.json
CF_NATIVE_EXEC=build/cameo_cli python3 tools/verify_boundaries.py --repaired --output boundaries-new.json
python3 tools/verify_repairs.py
```

安全构建用 `-DCF_ASAN=ON -DCF_NUMERIC_DYNAMIC=OFF`，分别运行原生API、numerical_dependency和transform_parity测试。`-DCF_TSAN=ON`是独立Clang14构建，使用本地LLVM14 libomp和冻结ompt-tsan源码构建的Archer。完整参数、编译/执行日志保存在validation/final-*-*。ASan配置阶段的getarch在受ptrace限制环境中可用ASAN_OPTIONS=detect_leaks=0；真正LSan验证在无该限制进程、detect_leaks=1下执行。TSan使用setarch x86_64 -R、Archer和ignore_noninstrumented_modules=1，范围见NUMERICAL_DEPENDENCY.md。

libFuzzer构建使用 `-DCF_FUZZ=ON -DCF_ASAN=ON`，本次数值依赖复用已经ASan/UBSan插桩的源码基线归档。源码核心由Clang独立编译。45秒预算运行119160次，种子、日志和构建参数保留；run数量不要求可重复。`cf_transform_tests` 默认输出512例对照和3次预热/7次取中位计时；CTest传入--check跳过计时。`cf_performance`输出完整CF01编码/解码流水线计时，不签Bench FORMAL性能。

第二架构工具从冻结deb本地解包，不安装系统软件：

```sh
python3 tools/bootstrap_arm64.py
cmake -S . -B build-arm-source -DCMAKE_TOOLCHAIN_FILE=cmake/arm64.cmake -DCMAKE_BUILD_TYPE=Release
cmake --build build-arm-source -j4
ctest --test-dir build-arm-source --output-on-failure
python3 tools/verify_platform.py
```

分派验证工具归档在Source/dependencies，许可证随包保留，均为本地验证工具。`bootstrap_instruction_tools.py` 校验hash并在同级Toolchains本地解包QEMU11、Valgrind、Intel SDE；SDE可能需要调试其自行启动的测试子进程。`verify_numeric_dispatch.py --batch --output numeric-dispatch-new.json` 对全20路径比较独立参考。默认脚本使用build-source-final/cameo_cli和原参考运行时，必要时按实际新构建路径调整；不能将路径变化后的未知二进制自动视为已验。

最终包：`cameo-family-full-parity-20261021.tar.gz`。生成脚本先生成逐文件索引及外层SHA，再由audit_review_package.py实际解包、核验、编译、ctest、安装消费、比较8个产物。验证索引自身由外层PACKAGE_CONTENTS.json保护，后者再由归档SHA保护，避免循环hash。最终资格同时核对外层audit.json；旧BLOCKED候选及旧日志原样保留。材料和专有验证工具只供本地研究审阅，不声明公开再分发。

构建时NUM_THREADS固定为2以去除ProcessorCount对诊断对象的影响，实际数值库仍为单线程。validation/build-provenance.json记录编译器、链接器、CMake、CPU/平台及明确测试环境；final-build-recipes.tar.gz保留顶层compile_commands与数值子构建的实际flags/link/build配方，供独立审计编译命令。thread-config-impact.json及before-fixed-threads-*保留本次复现检查发现的问题。

Clang14使用本地解包的LLVM OpenMP运行时，重新链接和执行前应将Toolchains/cameo-native-tools/usr/lib/llvm-14/lib分别加入LIBRARY_PATH与LD_LIBRARY_PATH（相对资产根）。仅复用编译缓存不携带这些进程环境。一次缺失libomp搜索路径的链接失败保存在fixed-threads-clang-missing-libomp.log；设置本地路径后重新构建、执行CTest与598项源差分。默认GCC构建使用系统libgomp，无此本地路径要求。
