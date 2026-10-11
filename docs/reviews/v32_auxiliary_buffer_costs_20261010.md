# V3.2 独立缓冲区成本观察

`tools/audit_v32_buffer_costs.py` 补充总计划 §6.1–6.3、§17.1(5) 的输入和内存观察合同。它从冻结 comparison / workload / P2 输入重建 CPU 准备，从实际保存工件核对存储长度，并绑定计划、原始试验文件、输入、工件、当前控制闭包和工具自身 SHA-256。

输出 `buffer_cost_audit.json` 和 `buffer_cost_audit.md`。状态固定为 `AUXILIARY_COST_AUDIT`，`formal_eligible=false`、`codec_invoked=false`、`performance_remeasured=false`。这些是独立的辅助观察，不能并成原性能 Trial 的同次观测、补写正式重复或产生 FORMAL 资格。原 Run、原始试验文件和工件内容保持原值。

| 观察 | 证据方法 | 范围 |
|---|---|---|
| 原始逻辑 bits、shape/dtype、adapted/codec 载荷、可见 backing storage | INSTRUMENTED | 本次独立 CPU 准备；共享 backing 不能逐视图相加 |
| 适配器复制数、可见输出 allocation count/bytes、显式 safe-overread padding | INSTRUMENTED | 可见 NumPy 输出；排除 Python、验证、hash 与 native 临时对象 |
| adapter read/write bytes 与计划成本 | ESTIMATED | 一次复制/填充模型与 frozen CompatibilityPlan；不是硬件访问计数 |
| 实际 stream/context/P2 child slice、frame/tree 与 FinalBits | MEASURED | 已保存工件的字节长度与散列；每个物理子帧只计一次 |
| native 实际提交字节、内部 read/write/allocation/peak、未保存 output capacity | UNAVAILABLE | null＋逐指标原因；不从 codec 字节、ndarray 大小或码流长度猜测 |

P2 从实际 frame 的有序 metadata tree 重建每个 column/block/tail 的原始输入及 child CompatibilityPlan；不调用子压缩器编码/解码。检查节点数、slot 顺序、dtype/count、offset、长度与散列，RAW 节点还检查实际内容。保留原始对象 ND 形状、非零 time_axis、各 dtype、T 与 validity ；mask 的逻辑 bit 和 packbits 的实际 byte 分列，避免改变原始分母。框架 assembly/hash 的完整流量与峰值未观测时同样保留 null＋原因。

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
python tools/audit_v32_buffer_costs.py <冻结Run目录> --lane comparison
# workload / pipeline 分别选择对应 lane；重新核对已有证据加 --check。
```

发布验收可调用 `validate_buffer_cost_audit(run_path, lane)`；该函数从当前冻结输入与实际工件完整重建文档后比较，不能靠一个 PASS 标签或重新计算伪造文档的 audit_id 绕过。

验证：22 个单元测试通过，Ruff 通过；另外只读核查历史 byte 96、f64 320、i16 224 个 retained artifact 的存储成本接口。该历史 smoke 只验证接口，不升级其身份或资格。当前正式 Run 的辅助成本工件随新的冻结发布目录独立生成。
