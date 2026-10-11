# V3.2 需求覆盖与验收台账

机器文件为 [v32_requirement_ledger_20261010.json](v32_requirement_ledger_20261010.json)。它保存总计划的全部非示例代码正文、列表与表格条款，标记显式 MUST、继承 MUST 的子项、A–G 阶段、L0–L6 交付及 §10.6/§17.1/§17.4 完成门，并保留全部 117 项原章节审查和能力矩阵快照。源文件路径、行号与 SHA-256 支持定位和漂移检测。

这是需求覆盖和验收缺口文件，不是“全部通过”声明。`REQUIRES_ACCEPTANCE_EVIDENCE` 保留待审状态；只有实际当前身份、合法域、恢复、成本、资源与正式观测证据可以关闭对应条款。历史快照和 §23 首批实施说明属于上下文，不替代正式验收。

用户本轮要求使用已有算法完成 V3.2，故 L1–L6 的**新增算法成员**单独标 `DEFERRED_BY_USER`；长期规格原文完整保留，已有 DeepZip/DZip、Serf/zfp、字节算法与 NeaTS/LeaTS 的合同和能力义务继续适用。byte、f64、i16 与 ABS 核心任务仍保留两种不同方法、两个独立真实来源、固定成员与失败分母的要求。窗口、列、seed 和重采样不增加来源数。

设备/P3 对无依赖的 CPU 核心发布可标可选，并给出发布范围理由；此判断不表示机器没有设备，也不表示设备测试已经通过。当前声明的 stream/query/SIMD 能力必须在其适用 profile 中单独验收，不能因本轮不新增算法全部写 N/A。

率控制与摘要的独立验证接口位于 `src/tscompbench/validation/task_validators.py`。注册 ID、合同版本与任务类别须一致，未知注册或缺失合同失败关闭。摘要标量 validator 独立计算 COUNT/MIN/MAX/SUM/MEAN，率 validator 从实际工件、账本和 SHA 取码率，核对原分母、层次、块取整、容差与质量；PAYLOAD 目标仍披露完整 FinalBits。当前无登记摘要或率 codec，故接口 fixture 通过仅证明 validator 性质，不证明算法资格或比较组完成。

质量报告保留有效值、null、匹配非有限和非有限失配计数，失配的质量值为 null 并附原因。i64/u64 的逐点误差门使用精确整数/有理比较；描述性均值等使用已记录实际精度的 longdouble。每通道时间加权误差与导数采用时间戳单位；缺 T、重复/乱序/非有限 T、shape 不合、null 或特殊值样本给出具体 N/A 原因，MTS 不隐式合成通道权重。

重建和只读核验：

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/build_v32_requirement_ledger.py
/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/build_v32_requirement_ledger.py --check
```

重建会恢复初始待审状态；维护验收证据时应编辑机器台账的 `accepted_evidence`、`implementation_status` 与 `remaining_gap`，然后使用 `--check` 仅核对覆盖。规格原文或源 hash 变更须生成新的可审版本，不静默缩范围。
