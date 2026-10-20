# ALP / ALP-RD 原生移植验收（2026-10-17）

结论：**NATIVE_PORT_QUALIFIED（冻结的 safe-v1 限定 profile）**；N0–N5
全部通过。上游已经是 C++，本任务按 V3.0 §114 完成原生移植与安全修复，
不签署跨语言 REWRITE_DONE 或上游 FULL_PARITY。

七份真实 CSV 的所有数值列/所有行，另含边界与 IEEE fixtures，共 284 个
精度×方法案例、10,004,036 个处理值，全部逐位恢复，RAW 分支数为零。
原版与移植版独立双向解码，并比较完整 raw 对象：272 个字节一致；10 个
原版 float32 factor=10 非法流按安全合同拒绝；另 2 个 IEEE adaptive
原版编码因事前冻结的源 UB 域不运行。拒绝与未执行不计作原版编码成功。

Clang 全部 284 案例、AVX2 全部 284 案例与基线字节一致；AArch64/QEMU
验证 56 案例、1,371,908 值，字节一致且双向解码通过。ARM 子集为全部
synthetic 和每个真实数据集第一数值列的所有行、两精度和两方法。

完整合同集包含 360 个长度×值域×类型×方法回环、容量/guard/未对齐/
畸形/资源/FP 拒绝、240 次 8 线程并发调用，以及 C consumer 和 OOM
注入测试。GCC/Clang/AVX2/ARM、ASan+UBSan+LSan、AVX2 sanitizer、
TSan 和最终 50,000 次 libFuzzer 均通过。逐字节 guard 检查计数不作为
独立测试案例数。外部系统库/QEMU 不在插桩覆盖声明中。

源码原版保留，四类 UB 有独立 UBSan 反例；两个上游头文件的安全修改
具备 exact pre/post hash 和可重放 patch。没有修改 RD 核心。新外层
frame 单独版本化，含完整恢复元数据、字典、exceptions、padding 和 CRC；
FinalBits 为完整文件字节数×8。

独立解压后重新构建、原版驱动、28 个 synthetic 差分、C ABI/失败合同、
补丁重放、安装后的新进程冷恢复通过，libalp_port.so 与 CLI 安装二进制
均逐字节可复现。源/工具链/动态依赖/实际 TU、headers、binary 和证据
hash 见 BUILD_LOCK、SOURCE_LOCK、SBOM、EVIDENCE_INDEX 与发布 manifest。

AVX-512/publication intrinsic decoder、物理 ARM 与上游可变 state 的
公开封装未开放；不宣称 FULL_PARITY。Benchmark 绑定及正式性能比较
是独立后续验收，本任务没有修改其 adapter、registry 或实验结果。
