# M2 受控测量协议与阶段收据

M2 阶段已接纳“测量与调度协议”范围，但**没有开放正式性能排名**。阶段收据为
[`results/m2-acceptance-20261119-r1/receipt.json`](../../results/m2-acceptance-20261119-r1/receipt.json)，其中
`timing_admitted=false`。本阶段只证明计划、进程 session、校准、匹配重复、逐批验证、取消/依赖/锁竞争终态和复算链路可审计。

## 正式冻结范围

- 5 种 f64 工作集：31 行、8,192 行（64 KiB）、102,401 行（ALP 行组及 1 行尾）、
  524,288 行（4 MiB，L3 内）和 4,194,304 行（32 MiB，超过当前 20 MiB L3）。
- raw-store、Zstd、ALP Auto 合法方法；`steady` / `cold` 两种生命周期；`dlopen` / `linked_entry` 两种入口。
- 共 18 个组、144 个 pilot/计时终态。每个已运行批次只贡献一个批观察；loops 不扩大独立样本数。
- 每组先执行两路单 loop calibration，再选择共同 loops；匹配轮次按冻结种子随机排列入口顺序。
- 编码/解码结果和原始位逐批验证；验证在 codec 时钟外，封存 reference 不冒充计时产物。
- 计划冻结时核验 outside case 大于所选 CPU 的 L3；这只表示输入工作集关系，不宣称可控清空或预热硬件缓存。

## 已完成证据

- 计划：[`results/m2-cache-formal-20261119-r2/timing-plan.json`](../../results/m2-cache-formal-20261119-r2/timing-plan.json)
- 运行 A：`21d70ffa80554cd5909094ebf2c4277a`，144/144 verified
- 运行 B：`f270cd6ac428487fbe4cfb3e7bc403ac`，144/144 verified
- 同计划复算：两份 `timing-report` 均逐字节完成，`samples_pooled=false`
- 负对照：[`negative-controls.json`](../../results/m2-cache-formal-20261119-r2/negative-controls.json)
  覆盖 CLI/API 同计划、锁竞争拒绝、取消后无错误启动、缺依赖终态和篡改 loops 拒绝。
- 两次运行的重复比较保留各自分布、CPU tick 和频率端点，不合并样本、不作跨硬件因果归因。

## 明确保留的限制

- 当前宿主只提供 TSBench UID 内的 host-local `flock`，计划记录 `exclusive_cpu=false`；没有系统级专核或兄弟核隔离。
- NUMA 内存策略为 `inherited_uncontrolled`；CPU 频率与 `/proc/stat` 只作观测，不能解释成无干扰保证。
- 本轮 `parallel_batches=1`，没有把外部并行整体墙钟与 codec 内部多线程拆成正式比较组。
- 因此 M2 收据不授予正式 timing admission、不产生算法排名；正式 profiling 仍属于 M4。
