# M4 阶段收据：原生剖析与测量对照

## 结论

M4 阶段验收已接纳，收据为：

```text
results/m4-acceptance-20261119-r1/receipt.json
```

本收据的状态保持：

```text
stage_accepted=true
qualification_granted=false
timing_admitted=false
```

M4 接纳的是原生 profiling、L0/L1/L2 分层、主计时与插桩对照、线程重叠观测及负对照协议；不把 profiling 时间当作正式性能排名，也不为首批算法签发正式资格。

## 绑定证据

- 计划：`results/m4-native-profile-20261119-r2/plan.json`
- 复算报告：`results/m4-native-profile-20261119-r2/recomputed.json`
- 控制证据：`results/m4-native-profile-20261119-r2/controls.json`
- run：`5694e57a4f6846d9bf8725df816e9276`
- 28/28 trials verified，覆盖 ALP fused、Zstd 多线程、XZ opaque；每项均有 encode/decode。
- plain/profile 两套构建身份绑定；profiled、trace-off、timing-only 三种执行臂均存在。
- L0 总操作、L1 阶段和适用的 L2 阶段均有记录；融合内核标为 `fused`，Zstd 原生 worker 标为 `measured`，XZ 内部阶段保留 `opaque/not_measured`。
- 逐字节恢复、重复匹配、插桩扰动、丢事件重标拒绝、越过 L0 的 worker 区间拒绝均被控制文件绑定。

## 边界

1. 该收据不授予 36 条原生路线的正式 qualification；M3 的候选证据及已知限制保持不变。
2. ALP AVX512/AVX512BW 路线继续保留；本机不支持时只能记录为 `pending_supported_runtime`，不能删除或伪装为通过。
3. 当前宿主的专核、NUMA、频率和外部干扰控制不足以开放正式 timing admission。
4. XZ 未暴露可验证的内部阶段，不能从缺少插桩推断内部耗时、线程数或并行行为。
5. 下一阶段是 M5：在 M4 收据之后，执行冻结的外置服务/组合矩阵；不能把 M4 profiling 结果直接替代 M5 的 204 展示格和 264 原子关系。

## 复核

```sh
PYTHONPATH=src /home/fzg/anaconda3/envs/tsbench/bin/python -B bmk m4-acceptance-audit \
  --plan results/m4-native-profile-20261119-r2/plan.json \
  --report results/m4-native-profile-20261119-r2/recomputed.json \
  --controls results/m4-native-profile-20261119-r2/controls.json \
  --out results/m4-acceptance-20261119-r1/receipt.json
```

复核必须使用 `tsbench` 环境，不使用 `base`。
