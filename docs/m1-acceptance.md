# M1 阶段收据（2026-11-19）

M1 最小可运行无损纵向切片已由正式冻结计划和独立恢复审计接纳：

- 收据：`results/m1-acceptance-20261119-r1/receipt.json`
- 前置收据：`results/m0-acceptance-20261119-r2/receipt.json`
- 正式计划：`results/m1-formal-freeze-20261119-r3/plan.json`
- run：`e3cd0ecca7a44c66a27770fdeeda517b`
- 计划内容 ID：`dbe17811fd524d570d95b586f80937e343763212efe8057c12e45af809e4de95`
- 结果：18/18 slot `verified`，每个实际产物按 `artifact_each` 验证；独立 Bubblewrap sealed-files-only 恢复 18/18。

该收据只接受 M1 的 raw-store/Zstd/ALP 最小真实闭环，仍保持：

```text
stage_accepted = true
qualification_granted = false
timing_admitted = false
```

因此 M1 不授予首批原生算法资格，也不授予 M2–M4 的正式性能或 profiling 准入。报告中的 process-frame-preflight 时间仅用于闭环账本，不用于算法排序。
