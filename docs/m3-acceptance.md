# M3 阶段收据（2026-11-19）

M3 的首批原生功能与数据管线覆盖已接纳，收据为：

```text
results/m3-acceptance-20261119-r1/receipt.json
```

本收据绑定以下同次或独立恢复证据：

- M0 原生候选主账本：200 个产品，174 个 verified，26 个预期拒绝；36/36 路线、180 项必需义务已绑定。
- Gorilla T/V 派生路线：16/16 独立恢复。
- TV 组合：15/15 独立恢复，固定 T、固定 V、原生 TV 和拒绝条件均有证据。
- 跨 CSV/NPY/TXT 格式 T+V：12/12 独立恢复，源文件解析计时在 worker 时钟外。
- 固定 T 的四位片路线：4/4 独立恢复，包含缺少兼容 transform 的拒绝。

M3 收据仍保持：

```text
stage_accepted = true
qualification_granted = false
timing_admitted = false
```

其中 CORAD 质量拒绝和 ALP AVX512BW 当前宿主不可运行的条件状态均原样保留；本收据不将候选证据升级为首批原生资格，也不替代 M5 的 204 展示格和 264 原子关系验收。
