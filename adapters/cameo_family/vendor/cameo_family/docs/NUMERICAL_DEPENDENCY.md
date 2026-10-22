# 数值依赖与平台证据范围

默认生产闭包是 C++17 核心、pocketfft C、从冻结源码构建的 OpenBLAS 0.3.21 C LAPACK、OpenMP 和系统 C/C++ 运行时。无 Python、GFortran、Quadmath、Benchmark 运行时。OpenBLAS 是单独登记的原生复用组件；本项目没有重写整个 BLAS 库的声明。

`cmake/source_lapack.cmake` 离线校验并解包 vendor/openblas 内的源码归档，构建 ILP64 静态库。x86_64 保留 DYNAMIC_ARCH 与 DYNAMIC_OLDER 全部20个内核名称，AArch64 使用 ARMV8。上游 CMake 的 double-only 动态构建存在结构/生成器不一致，因此 x86 动态构建保留所有精度；实际链接器仅拉入 DGELSD 所需闭包。AArch64 的上游交叉配置未生成 USE64BITINT，配方显式补上该定义，后端报告和实际调用验证64位接口。

冻结能力行 `swab/native-DGELSD-dispatch-closure` 保留为 REQUIRED_PARITY。验证的是 Python-SWAB 暴露的 m×2 最小二乘数值操作及其分派，不把无关 BLAS 函数、任意维度矩阵或整座上游库泛化为已验。全20个分派名称均保留，并记录 requested/actual/source_actual；仅有构建或回落不能证明目标内核执行。

初次在 i5-13400F 上强制全部分派的失败记录保存在 `validation/numeric-dispatch.json`：老Opteron需 FEMMS，Bulldozer系列需 FMA4，SkylakeX需 AVX-512。这些失败没有计为通过。最终分派验证使用本机、QEMU11.1.2、Valgrind3.18.1和Intel SDE10.13.1分别执行所需指令；Cooperlake使用SDE的CPX模型以核实实际内核，而非把Haswell回落算成Cooperlake执行。每条路径对23组完整自然/共享数据，与在同一执行环境中的原NumPy/OpenBLAS参考独立比较掩码、点、工作信号、恢复值。全路径最终逐例与实际内核记录见 `validation/numeric-dispatch-final.json`。早期 `numeric-dispatch-batch.json` 的 AVX-512 两例失败保留：将全局禁止收缩标志套到原生小矩阵 reduction 改变了FMA舍入。`cmake/openblas_native_fma.cmake` 仅为这两个原生内核恢复上游 contraction=fast；自有C++和其他基线仍为off。诊断的首个反例与参考掩码精确一致后，再重跑全部20路径与专项长度/并发测试。批量传输只避免反复导入：每次仍创建新数组并调用原 `oracle.execute`；598组基准差分另以独立冷进程执行。

ASan/UBSan/LSan 和 TSan/Archer 构建使用显式平台基线，插桩自有C++、pocketfft和源码C LAPACK/BLAS部分，含22种长度和80次Python-SWAB并发调用。源码汇编、libc、libm、OpenMP等运行时属于明示的原生边界；不声称汇编或整座系统运行时被插桩。无自有源码的race suppression。TSan排除强new注入，OOM由GCC/ASan独立验证。分派执行与基线插桩是互补证据，不冒称每个ISA都经过完整动态插桩。

AArch64/GCC11在QEMU6.2实际运行三个原生测试；`validation/platform-interchange-final.json` 覆盖598组双端编码、1196次跨架构冷解码。x86_64与AArch64的long double有效位分别64/113，libm和最小二乘临界排序也可不同，因此不承诺跨架构编码阶段或帧字节相同。原先跨架构对照x86源oracle出现8例差异的诊断保留在 `differential-arm64.json`，没有改容差或改成PASS。源阶段一致性签署范围是冻结x86_64参考；第二架构签署的是API、安全及相同物理帧的独立恢复。模拟执行不称为物理ARM、AMD或AVX-512硬件测试。

这些范围映射回原50项能力，未删除、降级或豁免必需行。未修改原作的UB历史和获授权的repaired-v1参考资格分别登记；后者才是本次完整交付的兼容目标。

最后复现审计发现，OpenBLAS的ProcessorCount会随构建环境变化，将MAX_CPU_NUMBER写入openblas_get_config的诊断分支。此前已验证目录与两份干净目录仅此一个归档成员不同，数值成员逐字节相同，见validation/thread-config-impact.json。配方现显式固定NUM_THREADS=2，USE_THREAD=OFF与USE_LOCKING=ON保持不变；重新执行默认Release及双目录构建、CTest、源差分和全20内核专项。不是把运行时变成双线程。原先两份干净构建成功及与既有目录比较失败的记录均保留。

原NumPy wheel对七个旧请求名使用其上游实际映射：Penryn/Dunnington/Opteron/Opteron_SSE3/Bobcat→Core2，Atom/Nano→Nehalem。报告保留这些source_actual，最终审核显式核对映射，不宣称源wheel实际执行了它未编入的内核。新源码依赖保留全部20名称并逐一核对native_actual=requested；对应23组源输出全部一致。其余13个请求的源actual与请求相同。
