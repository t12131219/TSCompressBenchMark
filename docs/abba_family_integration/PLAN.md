# ABBA family 接入计划（N0，2026-10-20）

用户授权删除旧 ABBA/fABBA，替换为 abba-family-20261020-v1 并新增 QABBA。已完整阅读发布 README、porting_report、CONTRACT、FORMAT 及既有一致性报告；V3.0/V4.0 按当前工程约束执行。文档中的独立 G0–G6 结论不是本次绑定资格。

1. 先归档旧 vendor、四补丁、登记卡、共享 shim、锁和构建配方；历史设计和结果不改签。
2. 从指定发布包逐成员复制 CMake/include/src/vendor/tools/tests/docs/LICENSES 源码和必要审计材料，记录包及所有消费成员 SHA-256；核心零修改。仅绑定新增，保留 LGPL CKmeans 补丁与完整许可证。
3. abba/fabba/qabba：P2、binary64、有限值、2..1048576 样本；core 单列，API/对象矩阵独立列，总值 <=1048576、列 <=4096。原生 owning API，禁止在 bound/预检中拟合；FE_TONEAREST、无 fast-math、关闭 contraction。完整 AFS1（矩阵为计费的 AFM1 列容器）计入 FinalBits。冷解码参数为空，不免费保存码本。
4. 只开放每对象拟合、确定性 ABBA seed=true、fABBA 单 worker、QABBA 单序列单 worker；独立包模型复用、图像、缺失填充、批次共享码本、非确定随机、上下文 Huffman1 不列为 Bench 能力。容差仅 empirical_quality，不声称逐点误差界；源恢复长度变化明确拒绝，不补点。
5. 离线独立发布 CLI 对照、真实数据/默认和参数路径、冷解码、坏帧/容量/原子失败/reset/所有权与双生命周期，绑定 sanitizer；专项后完整回归。原独立跨 ISA/fuzz/OOM 等证据单独引用，不继承。正式性能本次不重跑。
6. 更新登记、构建、桥接、生成器、当前文档/开发日志、实施计划和证据索引；LZSS 排除保持。
