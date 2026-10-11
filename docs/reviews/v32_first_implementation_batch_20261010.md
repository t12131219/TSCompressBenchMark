# V3.2 首批代码实施记录

2026-10-10，依据工程实施总计划、117项独立审查与能力支持矩阵，完成阶段A/B/D的一批基础修复。此记录描述代码与资格验证；没有生成新的FORMAL性能比较，也没有签署完整V3.2完成。

## 实施与证据边界

| 发现 | 已实施代码/产物 | 验收边界 |
|---|---|---|
| F12：CSV与旧scope版本冲突 | `registry/candidate_integration_ledger.json`、`tools/candidate_integration_ledger.py`、`tools/algorithm_scope.py` | 166条当前记录逐条连接163条旧记录，保留旧namespace、19项退出决定及明确去向；不依据新裸编号删除/恢复入口 |
| F02：逆恢复借用原输入 | `execution/recovery.py`、`preflight.py`、`repetition.py`、`validation/correctness.py`、`runner.py` | 编码侧冻结纯JSON恢复描述；spawn进程重建声明decoder，只接收完整码流、DecodeContext与公共decoder声明；原值仅由parent validator持有 |
| F02/§6.3：物化与恢复成本 | `.bin`、`.decode.json`、`.decoder.json`与raw diagnostics | 每次PIPELINE encode包含描述生成/记账，decode包含逆recipe和完整owned输出物化；decode sidecar的实际字节全部加入ExternalSideInformationBits，原始RawBits分母保持 |
| F06：预热worker与正式worker分离 | `execution/isolation.py`、`orchestrator.py`、`repetition.py`、`planning/resolution.py` | 每个测量worker先预热后采样，逐worker PID/时间/失败/退出可核对；新执行hash与比较键隔离旧结果，门槛仍按LEGACY_V2解释 |
| F15：摘要/率未实际验证 | `validation/correctness.py` | 专属validator缺失时分别返回UNSUPPORTED / OUTPUT_PROPERTY_VALIDATOR_UNAVAILABLE、RATE_VALIDATOR_UNAVAILABLE，不把记录参数视为验证通过 |
| F15：非有限失配掩盖质量 | `validation/lossy.py`、`tscb.loss-validation.v3` | 失配、匹配特殊值和有限对分母分列；失配通道质量指标null，有界校验失败；匹配NaN/Inf不作为零误差样本压低RMSE |

恢复上下文使用独立版本 `tscb.decode-context.v1` 和闭合Schema `schemas/recovery/decode-context.schema.json`，不升级canonical wire或native ABI。包含当前RoutedInput的buffer角色、dtype、shape、逻辑长度、单位、逆适配和配置；不包含源数组、timestamp_reference、路径或encoder session。现有无效或未实现的逆操作拒绝执行，validity不会继承数值转换。

`.decoder.json`属于明确声明的公共解码程序依赖，记录codec manifest和执行闭包身份。对象描述/参数已全部计入`.decode.json`；native帧已有头部仍照实计费，这是新增的显式外层恢复方案。该方案不声称格式开销最优，尤其小对象可能膨胀。已有codec外部模型费用仍由原账本负责，本批没有建立共享模型部署/摊销合同。

独立恢复预检与每次性能观测分开：前者证明该task工件能在无原输入的新进程恢复；后者对同次实际编码/解码/逆恢复输出验证和计费。raw的`qualification_evidence_scope=TASK_PREFLIGHT_FRESH_WORKER_ONLY`避免把一次冷恢复预检冒充每次冷启动性能观测。

## 验证

环境：`CompressBench14`（Python 3.14.5）。针对性回归包含真实spawn恢复、缺/坏描述与码流拒绝、完整物化、sidecar字节账本闭合、逐worker预热、独立重复与resume原始字节不变、特殊值与摘要/码率负例。

SIMDComp因控制面代码变化触发冻结执行闭包检查，已走原有SDK重新资格、独立audit及受控refresh流程。最终SDK报告为`build/source-audits/simdcomp-sdk-v32-recovery-20261010-r2/report.json`：504项全部通过，72个实际导入Python文件闭包包含新recovery模块；刷新过程保存旧/候选登记和r1报告，SourceArtifactID不变，执行相关AlgorithmID更新。此为SDK合同资格，不是新FORMAL。

新执行登记与历史run审核已分开：历史只读分支依赖当时保存的PASS审计、raw SHA、冻结manifest/source身份和runtime，独立标量解析旧码流；当前执行入口仍要求严格factory门禁和新decoder验证。不改旧raw、PASS/FAIL审计或历史FORMAL口径。原生接入清单通过生成工具重新应用scope并验证，保持176行和原范围；候选台账内登记身份仍是审核时快照，默认CSV映射不因新执行登记而失效。

全量测试首次发现本地LZSSE2/LZSSE8 release库缺失，已按现有`build_codec.py`构建后验收；未据此改变其活动范围。新执行集成测试逐实际`.bin`/`.decode.json`核对账本、哈希和worker证据，替换旧“外部恢复成本必为零”的断言。

最终固定版本全量回归：**1,744 passed，0 failed**（228.42秒）。152条既有fork/特殊值警告保留于日志；独立恢复使用spawn。改动代码与测试的Ruff检查、仓库`git diff --check`通过；候选映射验证为`PASS_PROVENANCE_MAPPING_ONLY`。全量日志和验证摘要保存在`build/source-audits/v32-first-batch-20261010/`。

复核命令（从项目根目录执行，使用Python 3.14环境）：

```bash
python -m pytest -q --tb=short
python tools/candidate_integration_ledger.py validate
git diff --check
```

## 后续门禁与范围

阶段A的候选版本映射已落地，但MethodID/ImplementationID、稳定比较组和去重后的多数覆盖分母仍待冻结。现有适配的恢复切片已实现，通用child/任意轴/T＋V/raw-tail/共享模型部署仍未完成。

下一条纵向交付为G-BYTE-LL：先冻结Task/Corpus/各方法ConfigPolicy、公共比较投影和期望矩阵，再补MeasurementProtocol/AnalysisPolicy、pilot与分块随机Schedule、基本CPU资源租约，最后取得多个独立真实来源的共同FORMAL和固定分母报告。当前固定task顺序、LEGACY_V2门槛及现有资源采样不能直接签署该组完成。

没有扩展codec源域、恢复退出算法、修改CSV或旧scope、修改native算法、重写历史Run。更详细的范围与worker证据分别见[候选台账说明](../candidate_integration_ledger_20261010.md)、[worker实施记录](worker_local_warmup_implementation_20261010.md)。
