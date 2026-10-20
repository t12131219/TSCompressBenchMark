# LZSS 排除记录（2026-10-17）

按用户明确要求，将下列两个 LZSS 登记设为 **EXCLUDED**，原因统一为：**算法接入异常，处于排除状态**。本次状态是当前 Benchmark 的执行准入决定；此前一致性审计与历史运行仍保留其原时点的结果。

| 登记 | 当前状态 | 标记 |
|---|---|---|
| `lzss-raw`（alexkazik EI10/EJ4/C32 C++ 重写） | EXCLUDED | 算法接入异常，处于排除状态 |
| `lzss-dipperstein-c`（Michael Dipperstein） | EXCLUDED | 算法接入异常，处于排除状态 |

`lzsse2-raw`／`lzsse8-raw` 是另外的实现，保持可用。当前默认可用真实 CPU codec 为 **42 个**，另加 `raw-store`；保留登记的真实 codec 共 44 个，其中 2 个被排除。

## 生效方式

两份 `registry/codecs` 卡片的 `admission` 保存状态、中文原因、日期和用户决定来源。`CodecSpec.require_enabled()` 是统一执行门禁，失败状态为 `excluded`、阶段为 `registry.admission`。

- `native_core`、`native_api`、`object_memory` 准入拒绝这两个 key；对象组件路由同样拒绝，不替换成其他算法。
- 显式构建、bridge 加载和编解码操作拒绝使用；校验发生在加载原生库／构建源码之前。
- `Registry.list()` 默认不选择排除项，`build --all` 和新实验生成器不选用它们。
- `python -m tsbench codecs` 仍显示两条登记，`status=excluded`，并显示完整中文原因；管理性参数／来源查询可保留。
- 当前可编辑示例已移除这两项；冻结实验配置和原始运行结果保留，重跑旧配置时准入门禁仍生效。
- 保留源码、原生库和历史工件，不提供配置参数绕过排除。此前针对 LZSS 的独立回放工具也会被当前 bridge 门禁拒绝。

原生算法二进制本身作为历史资产保留；本次门禁作用于 TSBench 的构建、加载、调度与操作入口，不修改压缩核心。

## 验证

`benchmark/tests/test_codec_exclusions.py` 验证两个 key 的登记状态、三边界拒绝、组件路由拒绝、构建／加载前拒绝、全量构建选择和 CLI 状态展示。原有通用执行测试改用仍开放的 Snappy／LZSSE2；通用 C ABI 交叉探针从 LZSS 改为 Snappy，不再调用排除项。现有 LZSSE 核心正确性检查继续运行。

专项回归 **142 passed**，日志见 [targeted.log](lzss_exclusion_20261017/targeted.log)。完整回归 **1255 passed，另有 4 个 subtest passed，无失败／跳过**，见 [full-suite.log](lzss_exclusion_20261017/full-suite.log)。
