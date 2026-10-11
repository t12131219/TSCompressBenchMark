# V3.2 阶段续跑：已有资格与 pilot 的只读复用

`tools/run_v32_comparison.py` 提供 plan、qualify、pilot、formal、report 单阶段命令。
`tools/run_v32_existing_comparison.py` 提供一命令完整执行及 formal no-op resume / report 证明。
两者采用同一个 stage helper，不修改普通 runner 的 stage API。

`--resume` 时，已有 `qualification.json` / `pilot.json` 必须通过其原有完整 validator：
校验 comparison / qualification / pilot identity、完整冻结单元 / 配置分母、真实恢复证据、
独立 development 内容以及适用测量协议门禁。通过后直接复用保存的 JSON，并核验文件 SHA
在只读验证前后不变；此路径不调用 qualify / pilot 测量函数。
资格验证不完整、证据被修改或实施闭包漂移时拒绝续跑，保留原文件，不用重测修补旧证据。

尚未产生证据的阶段执行一次，并写入新证据；pilot / formal 先验证前序资格。
formal 仍使用原 runner 的 trial 续跑逻辑。完整执行工具最后对已完成 RunSet 再 prepare resume、
execute 与 report，比较 raw trials SHA 和完整返回的 analysis identity，并写入不可覆盖的
`resume_verification.json`。

现有公共 `python -m tscompbench comparison qualify/pilot --resume` 只恢复 RunSet 准备过程，
对应 stage 函数仍会执行该阶段。需要复用既有资格 / pilot 时使用上述工具；工具输出明确
`evidence_reused=true`。新 source / runtime / registry 版本必须新建 RunSet，不能据这个开关
继承旧资格。

```bash
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/run_v32_existing_comparison.py configs/comparisons/g-quality-v32-20261010-v5.json \
  --output-root build/v32-evidence-20261010/current-r2 --run-set-id quality

# 同一冻结版本续跑：复用已有资格与 pilot，保留 completed trials。
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/run_v32_existing_comparison.py configs/comparisons/g-quality-v32-20261010-v5.json \
  --output-root build/v32-evidence-20261010/current-r2 --run-set-id quality --resume
```

6 项针对阶段恢复的单元测试通过：有效保存证据不会触发测量、无效证据保持原字节并拒绝、
已有证据要求显式 resume，以及缺少有效前序资格时不开始 pilot。Ruff 检查通过。
这些测试验证工具控制流程，不赋予任何 codec 资格或性能结论。
