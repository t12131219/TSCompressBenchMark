# V3.2 异步与 ragged 通道集合合同

`tscompbench.pipelines.ChannelCollection` 为有序独立通道提供新的表达与恢复路径。
每通道保留已有 `LogicalObject` 的值 dtype/shape、axes/time_axis、单位、entity/feature、
独立 T、T 单位/epoch、validity 和 BITWISE/SEMANTIC null 恢复合同。
集合额外保存通道次序、timestamp_origin 与 topology；已有 canonical wire、
`LogicalObjectSchema` v1 和已冻结同步对象身份均保持原版本。

`ASYNCHRONOUS_MTS` 要求各通道具有自己的原始时间轴。
`RAGGED_CHANNELS` 保留不同长度，允许通道有 T 或无 T；无 T 通道保持无 T。
两种 topology 的 alignment 均为 `NONE`，T/V pairing 均为 `PER_CHANNEL`。
集合不会排序、对齐、补值、插值、重采样、丢尾或构造共享 T。
重复和乱序 T 按每通道原始次序保存；一个通道的长度不会成为其他通道的长度。

`ChannelCollection.buffer_views()` 给出每通道独立 `n`、原始值/时间/validity buffer。
该函数保留物理 stride，表达本身不执行 materialization。
`prepare_collection_raw()` 显式执行各原 buffer 的 C-order 序列化，validity 使用 LSB0 packed bits；
`import_collection_raw()` 验证有界 header/payload、canonical JSON、聚合 allocation 与 checked shape、
逐 buffer hash/长度/次序/所有者、无重叠 offset、mask padding、无后缀及完整内容身份后，
恢复 owned、只读的 per-channel buffers。
路径与物理布局不增加逻辑身份；通道次序、schema、T、validity 和有效值位模式增加逻辑身份。
SEMANTIC null 的未定义槽载荷不增加 content ID，其原始底层字节 hash 另存。

集合 `RawBits` 等于所有原通道的 `canonical_raw_bits` 之和。
BITWISE 包括原始值全部位、各自 T 和一个 bit/validity element；
SEMANTIC 只包括有效值位、各自 T 和全部 validity bits。
未按最长通道补零或按统一 dtype 计算分母。NaN 不自动成为 null。

`ChannelCollectionRecipe` 明确绑定每个原通道的已有 `PipelineRecipe`。
v1 集合只接纳 LOSSLESS 恢复合同，使用既有 P2 `encode_object/decode_object`，不增加压缩算法。
集合容器保存全部独立 P2 子帧和恢复指令。完整 FinalBits 包括 wrapper metadata、
每个 P2 子帧的 metadata/payload、mask、各自 T 和所有尾部，不将 child metadata 再重复相加。
`decode_collection_in_fresh_process()` 使用公共独立 spawn decoder；原输入和 encoder session 不进入 worker。
当前 standalone 执行 ABI 只有共享 n/T，`standalone_collection_rejection()` 在调用 codec 前明确拒绝，
需要显式集合 P2 recipe；该拒绝不声称算法 source 的原生能力。

独立 schema 位于 `schemas/pipelines/v1/channel-collection-*.schema.json`。
专属资格工具为 `tools/qualify_v32_channel_collection.py`，固定六个合成集合：
两种 topology 各自覆盖 BITWISE＋mask、SEMANTIC＋mask、BITWISE 无 mask；
每集合有三个不同长度通道、mixed dtype、非零 time_axis、非连续输入视图、
有效 NaN payload、独立 duplicate/OOO T 和 ragged 非空无 T 通道。
工具冻结 LZ4/Zstd 两个已有 child 方案，共十二个 cell，保存 raw/encoded artifacts、
源码/registry/source/build/runtime 闭包、原始和恢复 facts、公共冷恢复证据与完整 ledger。
资格仅覆盖这些明确 fixture，不能推出原 source 全域、原生集合支持或正式性能资格。

`validate_collection_qualification(path)` 默认重建冻结身份、原始 buffer、分母、完整 ledger，
并从保存制品执行只读独立冷解码审计；不会执行 encoder 或测量性能。
`decode_artifacts=False` 只授予 `STRUCTURAL_EVIDENCE_VALIDATED`，不能签署最终独立恢复资格。
已有资格 report 和 artifacts 不覆盖；新冻结版本使用新 output。

条款映射：V3.2 §3.1 无 T/不暗中同步；§3.5 null/validity 与 ND/async/ragged；
能力矩阵 validity、async/ragged、ND/time_axis/topology；独立审查 018、022。

当前已完成 33 项纯表达、parser、身份、分母、防伪资格与不可覆盖测试；Ruff 通过。
真实 LZ4/Zstd codec tests 和专属资格仍待统一执行窗口，不以纯测试签署实际资格。
