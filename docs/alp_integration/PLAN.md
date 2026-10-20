# ALP safe-v1 Bench 绑定验证计划（2026-10-17）

消费发布包 `alp-cwida-safe-v1-20261017.tar.gz`，具体归档 hash 和 56 个文件 hash 冻结于 `adapters/alp/FROZEN_SOURCES.json`。保留独立 `NATIVE_PORT` / safe-v1 身份，不宣称 FULL_PARITY。不修改独立核心、frame、公开 API、patch 或既有独立证据。

当前仅开放 portable CPU、LP64 little endian、C++17、f32/f64、单调用线程。配置 `isa=SCALAR` 表示本次 portable 接入，不开放 AVX2/publication kernels 或 runtime dispatch。编译禁用 fast-math、FP contraction 和 strict aliasing；FP 环境由冻结 API 原样检查。资源上限为总计 2^24 个值，不宣称满上限实测。

`alp` 改为 adaptive ALP/RD；`alp-rd` 为 forced RD，不允许 RAW。原 forced decimal 接入删除，旧源码、未提交 direct 修改及 registry 原文保存为 `legacy-alp-before-safe-v1.tar.gz`；历史产物、结果与原 source manifest 保持原身份。

## 入口、所有权和计费

`native_core` 直接调用 stateless `alp_port_bound/encode/decode`，按输入 C/F 物理顺序处理单条标量流。context 只保存任务几何，bound 不采样；每次 encode 包含核心内部复制、分配、padding、sampling、建字典、exceptions、序列化和 CRC。caller 输出缓冲由 driver 在 prepared 主时钟外分配；fresh_request 按框架既定边界计入。完整 `ALPRW001` 输出逐字节计费，FinalBits=8*used；decoder 配置为空，只校验任务几何/方法并调用完整原生解码，不移出 CRC 或解码工作。两方向都是 caller buffer，release 仅清理 result，不释放 caller 内存。

对象 / C1 native_api 路径保留 TAI1 typed SOA 输入约定，但替换全部旧 codec 实现。新 APS1 完整容器：16 字节头，magic(4)、width(u8)、reserved=0(u8)、columns(LE u16)、rows(LE u64)，随后每列 LE u64 frame 长度与完整 ALPRW001 frame。列顺序与 SOA 输入一致，所有列 frame、目录和 header 均计入对象/C1 输出；不从大小中估算扣减。辅助 native_api 暂沿用框架对这类 C1 封装的保守政策：原生必要字节尚未与纯适配目录单独映射时，主空间指标保持 null；native_core 的完整 ALPRW001 字节数可直接核实。可选内部 timer 只环绕每列完整 alp_port 调用，外层 APS1 分配/拼装在 C1/API 时钟内，单独说明 timer 边界。

两入口均不得隐式 cast、RAW 或切换不同方法。短容量、overlap、损坏/截断/多余字节、dtype/count/method 不符时不发布部分输出；失败后支持重新调用/显式 reset。C1 单次 compress 后要求一次零字节 finalize；重复 compress/finalize 拒绝。C++ 异常不跨 C ABI。

## 验证范围与独立基线

1. 从本项目冻结 release 副本全新 CMake 构建 standalone reference；执行其合同/C consumer/OOM ctest。该基线不包含 Bench adapter。
2. 相同 dtype 和 canonical bits 下，与 reference 比较完整 ALPRW001 字节并双向解码。长度覆盖 0/1/2/31/1023/1024/1025/2049/102399/102400/102401；另含 NaN payload、sNaN、signed zero、Inf、subnormal、极值及自适应 RD。
3. C/F 布局、对象逐列完整码流、独立进程恢复、无编码器参数恢复；容量差一/精确、CRC/长度/身份损坏、未对齐、overlap、参数/资源/FP 拒绝及失败后重试。增补 binding 的 ASan/UBSan 验证。
4. 与 standalone 相同的七份真实 CSV（ETTh1/ETTh2/ETTm1/ETTm2/exchange_rate/national_illness/weather），全部数值列、全部行、原始顺序、显式 f32/f64，两个方法。使用冻结工具的 corpus/fixtures 选择规则，保留原文件、canonical bits、frame 和 actual library hash。只对比 safe-v1，不把本轮结果称原始 UB 源的一致性证明。
5. 两方法分别在 native_core/native_api、prepared/fresh_request 执行短批次，逐 warmup/正式操作进行计时外验证并独立恢复；这是路径资格，不是 FORMAL 性能。
6. 执行适用 targeted tests 和完整 Python suite；记录失败、未执行及范围限制，PASS 不从旧结果继承。

AVX2、AArch64/QEMU、TSan 和 50,000 次 fuzz 的已有结论仅是独立包历史证据，本轮不自动签署 Bench 上的对应验证。既有正式性能表和 RunSet 不改为新实现结果；新身份需另行正式实验。
