# 本地研究重写与验证结果

全部所列算法已在独立 C++17 包中实现。原仓库 panagiotisl/chimp，冻结提交320d397157c7e0696b3c64dc1711fc17a3add3da。用户批准的研究验证豁免记录在 WAIVER.json；未声明新获再分发许可或正式 REWRITE_DONE。

最终共13481案例、6,628,856处理值：13473源码等价通过；8案例单独登记（5原始固定缓冲区损坏反例、3Swing单点未定义输入）。无损原始流逐字节一致、四路解码通过；有损分段边界/系数与重建float一致。四份真实CSV全部数值列/全部行，另有共享验证语料及合成边界。FPC再验证362,296值的连续预测器历史/奇数块补位/源帮助函数。

源有损缺陷：Swing41个案例、Quantized82个案例超过给定epsilon；Quantized3个单点案例非有限。全部由严格 ABS 模式拒绝；兼容模式保持原行为。PMC、Disjoint及filter2在本次案例中未超限，但这不等于数学普适保证。

GCC/Clang构建、ASan+UBSan+LeakSanitizer、OOM、独立对象TSan、静态分析和50,000次libFuzzer通过。Clang重放13473案例；AArch64/QEMU重放2196案例/994,361值（全部synthetic/shared及每份真实CSV首数值列全部行）。ARM仅量化单点源缺陷的NaN符号不同；非NaN字段与格式/冷恢复严格核对。

容量/resource、空输入、小长度、ring wrap、EOF、重复finalize、reset、失败原子性、原始输入不变、畸形/截断/校验/超限、FP模式均验证。owning-vector API没有调用方输出容量，bound-1/canary槽位要求不适用；无overread。

source/build/runtime/license、FP/Java语义、数据hash、raw/frame/decoded gzip证据、矩阵、命令日志、性能（setup包含的本地API测量）完整保留。最终精确归档的独立解包/原始oracle重建/补丁重放/安装后C++消费与冷解码/库和CLI字节可复现结论，见Release/chimp-family-research-20261017.validation.json外部签署。封包使用tar hardlinks内容去重，保留全部原始路径及hash；不要在证据快照中原地编辑共享inode。
