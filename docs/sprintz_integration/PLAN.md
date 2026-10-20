# Sprintz 原生发布包接入 N0 计划（2026-10-17）

用户授权：替换现有 Sprintz 对应接入，使用 sprintz-family-native-20261017 发布包。
已完整阅读两份总规范（既有工作）、本包 README、VALIDATION_REPORT、CONTRACT、FORMAT_AND_SAFETY 与能力矩阵；文档中的未接入/未授权说明是交付时状态，不覆盖本轮用户接入请求。

1. 归档旧 adapters/sprintz 全目录（包括未提交 direct_core.inc）、五张卡及对应来源卡、旧构建配方。
2. 以发布包 SHA 和逐文件 hash 冻结实际 runtime/build/tests/docs；消费核心不修改，独立 ISA TU 与基线 API TU 分开编译。保留修补及原版差分依据。
3. 四主键 sprintz-delta、sprintz-fire、sprintz-delta-huffman、sprintz-fire-huffman；用户后续明确要求删除全部旧 Sprintz 算法：不保留 fire-huff0 别名或两个 *-u8 登记；只登记四主键。删除旧实现及旧补丁。
4. 输入 row-major 整数位型（signed 按位等价）、1–128 维、总输入 <=65536 bytes，拒绝浮点/更宽整数；不自动分块、量化或回退。配置 path 明确限定 auto/general/lowdim/bitpack/noRLE。
5. native_core 直接调用 sz_* 安全 API，caller-owned 输出。核对 tsbench_core.h 后确认 decoder parameters={}，所以 core 与 C1/object 都输出 SZF1 自包含容器（24字节头 + 原样 raw payload），记录 predictor/huffman/path/width/ndims/count/length；全部容器字节计入 FinalBits。C1 使用 SZI1 输入描述符；core 仍接收原始物理整数数组。两种计时边界分别标注。
6. 重建 standalone 对照库/CLI；绑定字节、双向解码、canonical/真实整数、奇数16位尾字节、路径、所有权、容量、故障、畸形、native_core/API 两生命周期与新进程冷恢复；ASan/UBSan/LSan 和完整 Python 回归。
7. 更新 README、实现与开发记录、V4 进度、示例/生成器与来源身份；历史性能/证据保留，不给新身份继承排名或 FORMAL。

范围是限定原生移植 Bench 绑定验证，不继承全上游 FULL_PARITY；query/旧1D/其他熵组合、ARM 等不开放。ELF 前期核对待后续继续，未在本次 Sprintz 改动中替换。
