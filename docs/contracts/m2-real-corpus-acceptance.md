# M2 更新版真实语料计量收据

`results/m2-real-r8-20261119/receipt.json` 是在新版 M0/M1 输入锁上签发的 M2
协议收据。它不改写历史的 `m2-acceptance-20261119-r1` 收据，也不把诊断计量
提升为正式性能排名。

## 绑定关系

- `plan.json` 绑定 `results/m0-real-corpus-acceptance-20261119-r1/receipt.json`
  和 `results/m1-real-r8-20261119/receipt.json`。
- 计量计划继续复用已验证的 frame timing executor，但其身份、输入范围和
  predecessor receipt ID 都保存在新版 wrapper plan 中。
- 两个独立 run 各完成 144/144 个 verified 批次，合计 288 个批次。
- 每个 verified observation 同时记录 encode/decode 方向；计划覆盖 small、块边界、
  L3 内和 L3 外工作集，以及 steady/cold、dlopen/linked-entry 和匹配轮次。

## 资格边界

当前宿主的 `exclusive_cpu=false`，NUMA memory policy 为
`inherited_uncontrolled`，且外部 `parallel_batches=1`。因此收据只接纳计量、
重复、取消、依赖缺失、锁竞争和篡改拒绝协议，`timing_admitted=false`，不产生
正式性能排名。算法内部多线程仍可在 codec 内部运行；它属于被测实现的实际行为，
不会被外部批次调度器伪装成单线程，但本收据不把外部批次并行作为比较因素。

## 复核入口

```bash
conda run -n tsbench ./bmk --root . m2-real-corpus-acceptance-audit \
  --plan results/m2-real-r8-20261119/plan.json \
  --report-a results/m2-cache-formal-20261119-r2/recomputed-21d70ffa80554cd5909094ebf2c4277a.json \
  --report-b results/m2-cache-formal-20261119-r2/recomputed-f270cd6ac428487fbe4cfb3e7bc403ac.json \
  --repeat results/m2-cache-formal-20261119-r2/repeat-comparison.json \
  --controls results/m2-real-r8-20261119/controls.json \
  --out /tmp/m2-real-r8-receipt.json
```
