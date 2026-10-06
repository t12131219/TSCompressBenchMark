# Compression_Rewrite 接入准备清理报告

日期：2026-10-06。范围仅为 `/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite`。根据用户要求，将该目录整理为后续接入框架需要的源码、构建依赖和运行资源集。

## 空间与保留内容

清理前目录磁盘分配量为 64,225,787,904 字节（59.81 GiB），清理完成时为 2,304,544,768 字节（2.15 GiB）。目录分配量减少约 57.67 GiB；目录外的历史文本归档、清单及本次验证记录约占 99 MiB。上述为 `du` 的目录占用统计；共享硬链接等因素可能影响文件系统实际可用空间变化。

删除 296,398 个文件；保留原有 2,446 个文件，另移存 25 个必要模型和测试输入，并新增接入说明。

- 保留算法源码、头文件、CMake、第三方源码、依赖声明与补丁、许可证、合同和自测试。
- 保留 TEC-TT 两份原生 `.tctw` 模型、WaLLoC 两份 `.wlm` 模型，以及 DeepZip 的 17 个原生模型（其中 biGRU 原已在测试 fixtures 中）。这些运行资源占据剩余目录的主要空间。
- 将 DZip bootstrap 和 Histogram-ST oracle 测试输入移入 `tests/fixtures/`，更新 CMake；更新 WaLLoC 模型清单及使用示例。
- 保留 `Source/` 的参考源码和来源标识；FlexTEC 尚无 C++ 实现，其参考 Python core 与模型来源信息保留，原版大型 checkpoint 已删除，后续推进需重新获取。
- 删除旧发布包、预编译库、构建缓存、重复模型、训练快照、临时解码输出、大型验证数组及实验产物。

## 报告归档与可恢复范围

历史小文本报告、旧验证脚本及来源记录共 28,120 项已归档到 [historical_metadata.tar.gz](historical_metadata.tar.gz)，每项内容均核验 SHA-256。归档 SHA-256 为 `f3c706f219e7f268d99d3eb411a8dcab0f707783850a0376dcd3f4a0444886ea`。

报告可按归档内原相对路径提取。被删除的大型模型副本、数组、构建文件和发布包没有纳入备份，需重新获取或生成。旧清单中的历史 `validation/`、`release/` 等路径保留作参考，旧发布证据链已不能完整重放。

完整清理记录见 [cleanup_result.json](cleanup_result.json)，归档内容哈希见 [archive_inventory.json](archive_inventory.json)，逐项保留/删除清单见 [cleanup_plan.json](cleanup_plan.json)。清理目录和本地大型审计数据仍由 Git 忽略规则排除。

## 清理后验证

保留源码及运行模型的 SHA-256 核验通过；仅必要的构建测试路径、模型清单和 README 作了修改。

下列 13 个项目使用全新临时构建目录完成 CPU Release 构建及 CTest，全部通过：ABBA、CORAD、DeepZip、DZip、Elf+、fABBA、InfluxDB TSM Adaptive Timestamp、Histogram-ST、Prometheus XOR Chunk、Prometheus XOR2 Chunk、SElf*、TEC-TT、TRISTAN。

WaLLoC 使用已安装的 LibTorch 2.6.0+cu118 和 CUDA 11.8 完成 CMake 配置检查，通过；本次未重新编译和测试其完整运行链。DeepZip/DZip 的 HDF5 和 CUDA 变体未重建。所有本次临时构建产物已清除，命令和日志保留在 [build_verification.json](build_verification.json) 及同目录各算法 `*-build.log`。

本次验证检查源码清理是否破坏独立构建与现有自测试，不代表重新通过 FULL_PARITY 或完成框架接入。TEC-TT 的 G5/CUDA safety 阻断、FlexTEC 的 G2/oracle 一致性阻断维持历史状态。后续接入应生成新的 adapter、registry、构建身份及资格验证记录。

使用保留目录的方法见 [INTEGRATION.md](../../../Compression_Rewrite/INTEGRATION.md)。
