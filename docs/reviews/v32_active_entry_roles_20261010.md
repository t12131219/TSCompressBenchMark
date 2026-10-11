# V3.2 当前 33 个活动入口：完整资格与四矩阵工具

活动分母读取 `registry/algorithm_scope.json:registered_codecs`，共 33 项。三个范围外旧残留、四个 oracle 和别名不增加活动分母。四个首批共同组的成员集合为 19 个不同入口；其余 14 项仍在当前实施范围，不因尚未入共同组而免除适用资格。

`tools/qualify_v32_active_entries.py` 读取当前 qualification 模板，从其已登记 fixture 和合法参数点中，为每个声明 Track 选择一个确定点。当前得到 41 个 Track case。该选择只授予明确的有限 fixture/边界资格，不能推出整个声明域、全参数网格或正式性能资格。

| 未入四个首批组的入口 | 当前角色 | 准入与比较条件 |
| --- | --- | --- |
| abba | 无通用逐点界的质量研究入口 | 冻结质量指标与域，保留结构、恢复和完整成本；不能代替 ABS 或无损组成员 |
| fabba | 无通用逐点界的质量研究入口 | 同上；与 ABBA 保留不同方法身份 |
| deepzip | 冻结模型/alphabet 的无损研究入口 | 原生 u8/alphabet 域与外部模型成本；typed byte 桥接须另冻结完整方案 |
| dzip | 冻结模型/alphabet 的无损研究入口 | 原生 u8、模型状态及依赖线程；typed byte 桥接须另冻结完整方案 |
| simdcomp-u32 | P0 原生 uint32 primitive | 独立 API 比较；完整 typed 对象须计入 descriptor、变换与尾部方案成本 |
| fse | 完整 byte 熵编码入口及组合子 codec | 验证长度/字节域限制、拒绝与完整方案成本；保留组件角色 |
| huff0 | 完整 byte 熵编码入口及组合子 codec | 同上；Sprintz 组合的 child 不替代独立入口资格 |
| sprintz-delta-u8 | UINT8 专用方法变体 | 原生 u8 UTS；与 i16 入口共享机制但保留独立域、配置和身份 |
| sprintz-fire-u8 | UINT8 专用方法变体 | 同上；不能将专用 fixture 结果当 i16 共同组结果 |
| deflate-zlib | byte 无损扩展入口 | 当前完整 typed byte 方案；加入冻结共同组后另执行 FORMAL；`lz77` 别名不增算法数 |
| brotli-stream | byte 无损扩展入口 | 当前完整 typed byte 方案；持续流需独立 profile 验收 |
| xz-stream | byte 无损扩展入口 | 当前完整 typed byte 方案；持续流需独立 profile 验收 |
| lzss-raw | byte 无损扩展入口 | 当前完整 typed byte 方案；保留来源和参数域 |
| lzss-dipperstein-c | byte 无损扩展入口 | 与另一 LZSS 保留实现来源差异及安全修补证据 |

工具分别生成 `SourceCapabilityMatrix`、`StandalonePortMatrix`、`BenchProfileMatrix` 和 `PipelineCoverageMatrix`，不合并为一个通过标记：

- Source：保存声明原始域、source identity、已有冻结文件的期望/实际 SHA、vendor 树实际文件 SHA，以及 aggregate hash 是否使用相同协议。无法证明等价的协议/子集继续为 UNKNOWN。
- Standalone：保存当前 build/artifact 实际 SHA、历史独立包 audit 的原始状态/准入域/限制、历史 raw 与 native log 实际 SHA。历史 PASS 不重签为当前 standalone PASS。
- Bench：调用普通 planning 和 `preflight_task`，须同时具备真实正确性、边界安全、完整账本、spawn 独立恢复和码流 SHA 绑定，才授予 `SCOPED_PASS`。缺证明不会因 `preflight.status=PASS` 而通过。
- Pipeline：记录该 case 实际 compatibility、preprocess、恢复和成本。其他未执行 recipe、query/stream 主 profile 和性能资格继续显示 NOT_RUN/UNKNOWN。

`preflight_task` 的现有 boundary suite 执行 source domain 的原子拒绝、bound/canary、输入不变性、重复 finalize/reset 与真实边界 roundtrip；拒绝记录单独保留，不视为编解码域通过。

使用 CompressBench14 Python（项目包含 Python 3.14 语法）：

```bash
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/qualify_v32_active_entries.py \
  --output /tmp/tscb-v32-active/plan-only --plan-only

# 源码、registry、正式构建冻结稳定后创建新的运行证据。
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/qualify_v32_active_entries.py \
  --output /tmp/tscb-v32-active/qualification --execute

# 同一冻结版本续跑或验证；已有证据不重跑、不重签。
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/qualify_v32_active_entries.py \
  --output /tmp/tscb-v32-active/qualification --execute --resume
```

执行使用默认全局 Linux host lease，按 case 串行占用冻结 CPU；不会另建命名空间绕过其他 RunSet。
普通入口保持模板的一线程预算，DZip 保留模板声明的三线程与 `[0,2,4]` 三个 CPU，
可通过 `--model-cpus` 事前指定三个不同 CPU。lease 的 affinity、线程与内存取同一冻结 profile，
不将后台线程预算降为一线程。case 保存模板请求、应用预算和 lease 内观察到的 owner affinity；
object preflight 不授予 worker 线程高水位合规或正式性能资格。
`--keys` 仅用于明确诊断子集，summary 会保留活动总分母并显示 `entire_active_scope_selected=false`。

每个 case 保存 task、原始预检、成本、spawn 恢复、lease 边界、时间边界及内容 identity。Resume 检查 plan identity、自身/src/registry、执行依赖、数据/template/historical audit 的 SHA 以及 case 内容与验收推导的一致性。任何冻结漂移要求新 output；已有历史运行保持只读。

截至工具交付，13 项针对冻结、防伪 PASS、活动分母与角色的测试通过，Ruff 通过；尚未据此签署实际 33 项资格。
早期静态规划保留了 SIMDComp 的 Python closure 漂移阻断。随后经官方 source/build/SDK audit
与 refresh 重新冻结，旧计划保留原状态，新计划才读取更新后的 AlgorithmID。
预算修正后相关三套工具单元测试合计 35 项通过，另逐项核对 33 入口的 qualification 模板：
只有 DZip 声明三线程，其余为一线程；全部请求线程原样保留，重复 model CPU 在执行前拒绝。
任何这些静态与工具测试都不代替实际 33 项 finite fixture 资格。
