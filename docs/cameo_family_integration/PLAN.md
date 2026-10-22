# CAMEO 家族 N0 接入计划（2026-10-22）

消费已审计的 cameo-family-full-parity-20261021 发布包，不修改发布核心。兼容目标为获授权修复 cameo-family-repaired-v1；不把原版 BLOCKED 历史改签为通过。

登记 cameo（CAMEO/SIP）、vw、pip、tp、swab、sim-piece、pmc-mean、swing-connected、dft、dwt-dct-ii 共十项。与 PMC-MR、Chimp Swing 和小波变换明确区分。SIP 为名称别称，不重复统计算法。

binary64、隐式规则索引时间轴；主 native_core 单列 owning C++ API；C1/对象独立列。CF01 完整帧和多列封装全部计费，独立 decoder 不需要编码参数、原数据或模型。拟合/阶段变换、分配、源内部重构和帧序列化在时钟内；容量上界与有限输入检查不拟合。

ACF 停止误差、SWAB 拟合阈值、TerseTS float32 阈值/余量及频率裁剪均只开放 empirical_quality，不承诺通用逐点误差界。保留三种 SWAB、CAMEO LPC/FGC/ratio/聚合和 FFT/scalar DCT 参数。源资源预算和恢复长度变化需明确拒绝，不补点、不改算法。

数值库离线源码构建，保留20内核原生分派及上游FMA覆盖规则；不虚标SCALAR。ACF worker 参数与 native_threads 匹配，其余单worker。记录实际编译依赖、工具链及runtime身份。所有绑定仅导出ABI符号，避免数值库符号污染其它算法。

验证十项直接调用与独立CLI完整帧一致、新进程/空参数解码、来源参考数值、C1容量原子性/reset/finalize、列/块/C/F布局、坏帧和资源拒绝、native边界×生命周期、绑定sanitizer及全量Python回归。单独列出不继承的发布包资格；不运行FORMAL吞吐。
