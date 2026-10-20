# NeaTS／LeaTS 直接原生入口

`adapters/neats/native/direct_core.inc` 为两个现有模型 codec 增加直接入口，旧 C1／对象入口保留。直接入口不创建 `NTI1` 输入帧，也不调用 `tscb_compress`。

输入方法是 `physical-contiguous-stream`：原任务有符号 int8／int16／int32／int64 的 C／F 物理连续字节直接进入 native，整个物理数组作为一条标量序列。不得在 Python 中转置、扩展到 int64 或按列重新排列。源审阅限制保守保留为每条标量流 1..65536 个值，二维任务按全部有效元素检查上限；超过限制明确 unsupported。

encode 内扫描原 dtype 的有符号值、确定最小 bias、构造 int64 归一化输入；span 超过 INT64_MAX 时明确 unsupported。随后创建原生 Codec，执行完整 partitioning／模型搜索／残差编码，并调用原生 `serialize` 保存全部模型、索引、残差及必要状态。max_bpc 支持 16／32。准备好的 context 不包含预计算模型或数据扫描结果。

完整输出为 13 bytes 恢复前缀加原生完整 SDSL 序列化：`NDC1`／`LDC1` 标识 4 bytes、原 dtype width 1 byte、signed normalization bias 的 little-endian 8 bytes。max_bpc、有效元素数、残差 bits、模型参数与索引均由原生 serialization 自己保存。前缀只补充 serialization 没有保存但独立恢复原数据所需的信息；不含旧 ABI 集合目录、logical_storage_bits、实验 JSON、来源信息或实验 hash。

serialization 通过有界 streambuf 直接写入 driver 已分配的输出 buffer，不必额外复制到 ABI buffer。decode 通过只读 streambuf 从原生 serialization 加载全模型，恢复归一化 int64，再加 bias 并检查原 dtype 范围，写回同一物理次序的完整字节。decode context 参数是 `{}`，不从 encoder context 获取 max_bpc 或模型。encode 与 decode 不进行框架回读正确性验证；主时钟外逐产物 bitwise 验证仍是有效结果必要条件。

原始有效分母始终为原 dtype 的真实输入 bytes。模型内部 int64 归一化不会扩大分母；SDSL serialized 字节完整计入输出。此次没有修改 NeaTS／LeaTS vendor 或其已有兼容／持久化／预测精度补丁。

新增 `benchmark/tests/test_core_models.py` 使用中央构建库验证两算法、4 种原 dtype、C／F 布局、两个 max_bpc、完整独立恢复、偏移前缀、span 拒绝、空／超限拒绝和错误 count 在原生加载前拒绝。主任务统一构建、测试、测量；本实现日志不把未执行的检查写成已通过。
