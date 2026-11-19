# 原生资格证据审计合同 v1

`bmk native-qualification-audit <sealed-run>` 根据[资格 schema](../../schemas/qualification.schema.json)
重核**一份**冻结的统一原生候选运行：Python 入口为
`tsbench.qualification.native_evidence.audit_native_qualification`。这是 M0 的准入证据合同，**不是 M3 的正式资格签发器**。
它不接受仅有范围计划、其他 run 的汇总、历史 PASS、手填的恢复报告或散装产品代替同一运行原始证据。

1. 锁定同一 `run_id`、计划、封存、ledger 摘要、准入定义、构建、执行绑定和恢复闭包。每个槽关联实际输入域、
   解析后的配置、driver、原有 ledger 终态及 ABI/原生工具身份；Huff0 的 portable 恢复与主闭包不会混为一项。
2. 使用同一实际入口重算原始报告，再从封存产物及声明的恢复闭包重新执行独立恢复。报告不只检查一个 `restored`
   计数，而是要求每个成功产物的槽 ID 都有唯一的恢复观察，且负样本重放必须属于该账本的拒绝槽。
   产物恢复、按原预期拒绝、失败终态、条件未实证和质量拒绝分别保留；原账本拒绝并不等于本次隔离环境已重放拒绝。
3. 记录 `validation_protocol_id`，覆盖资格 schema、执行计划锁定的 Python 校验材料摘要、新审计代码及 launcher 锁。
   校验代码变化不能用晚生成的报告替代原协议；本版检测到冻结校验文件漂移时要求原版本或新的校验协议。
4. 逐个操作组展示必需义务及条件义务，不把 200 个产品槽当成 186 项义务的数量，也不把恢复出的产品误当合格：
   恢复成功的 CORAD 帧仍可因预先冻结的原域误差阈值失败；本机缺少 ALP AVX512BW 运行条件仍保留该项待验。

当前 schema 不允许 `qualification_granted`、`stage_accepted` 或 `timing_admitted` 为真。正式资格需要在提交前绑定
前置阶段验收、正式工作量/资源限额及留存政策，用锁定的验证器执行**新正式运行**；不能给旧候选报告改名升格。
命令返回成功只表示审计完整，而非全项通过。既没有新增运行账本，也没有历史 PASS 拼接。

## 实证

[禁网审计](../../results/m0-native-qualification-audit-20261119-r2/qualification-audit.json) 仅读取原 `extended-v20`
封存目录和校验代码，不挂载 Unique、语料、原构建目录或历史派生报告。锁定的 86 个 Python 文件逐一核对，
在 200 个槽中重解 **174** 个，并隔离重放其中 **6 个**原输入拒绝（pcodec C f16、IntMult、PBEPLA）。
**另 20 个**拒绝只核对原账本，不虚构重新执行。36 个操作组、180 项必需义务、6 项条件义务分母保留；
179 项必需和 5 项条件有候选证据，CORAD 1 项质量拒绝，ALP AVX512BW 1 项待兼容主机。
[漂移负测](../../results/m0-native-qualification-audit-20261119-r2/stale-validator.stderr) 在原封存不变时覆盖一个旧版锁定校验文件，
在重解前拒绝，且没有输出审计报告。原生正式资格仍为 0/36。

```bash
bash tools/probe_offline_native_qualification.sh "$CONDA_PREFIX" <封存运行目录> <空输出目录>
```
