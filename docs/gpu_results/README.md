# GPU P4 实测与审计

Margin90 四轮正式运行 **840/840** 槽位全部通过，40 cases 各 3 sessions × 7 rounds；另有 40 个 exact-input 独立 decoder 与 240 个 warmup。

每个 case 的精确计划/started/terminal 覆盖、严格质量、输入未修改、artifact hash/字节/typed bound、adapter allocation/stream/event 回收和实际资源 profile 均重新只读核对。分析未运行 CUDA、未修改原始证据。

原始 equal-bound 的失败仍是独立结果：0.01 为168 ok /84 not_run，0.1 为210 ok /42 not_run；它们不并入 margin90 成功数。0.9 参数比例是观察失败后的固定敏感性政策，task 请求仍为0.01/0.1，不提供普遍误差保证或最优参数结论。详见 [机制与冻结配置](../gpu_margin90.md)。

| 运行 | Policy | Task | Codec 参数 | 正式覆盖 | 独立 decoder | Trace |
|---|---|---:|---:|---|---:|---|
| [cuszp-formal-0p01-20261013](../../runs/gpu/cuszp-formal-0p01-20261013/report.md) | original_equal_bound | 0.01 | 0.01 | 168 ok, 84 not_run | 8 | `sha256:f900ae325720aae252b5ac01799c8bf707d727d2076efd3bd94a9838017985c4` |
| [cuszp-formal-0p1-20261013](../../runs/gpu/cuszp-formal-0p1-20261013/report.md) | original_equal_bound | 0.1 | 0.1 | 210 ok, 42 not_run | 10 | `sha256:5bd5b77b145d5e00a1af01137a5cee9a7e08f96a8ef79fbd455d2895bce1544a` |
| [cuszp-margin90-0p01-20261013](../../runs/gpu/cuszp-margin90-0p01-20261013/report.md) | margin90_after_original_failure | 0.01 | 0.009 | 252 ok | 12 | `sha256:08c571949fc649f06ca3b0c873faef4cf8bffa3f4d2f96ee804f1eca8800a743` |
| [cuszp-margin90-0p1-20261013](../../runs/gpu/cuszp-margin90-0p1-20261013/report.md) | margin90_after_original_failure | 0.1 | 0.09 | 252 ok | 12 | `sha256:fd9667feb0b3bdace12532b8951cfc686f8676e05d9d00f49241b551bad54305` |
| [cuszp-real-f64-0p01-20261013](../../runs/gpu/cuszp-real-f64-0p01-20261013/report.md) | margin90_after_original_failure | 0.01 | 0.009 | 168 ok | 8 | `sha256:5c87468590f8a85a039d555322bad07c559608f427782f5df3f5a63acaedd723` |
| [cuszp-real-f64-0p1-20261013](../../runs/gpu/cuszp-real-f64-0p1-20261013/report.md) | margin90_after_original_failure | 0.1 | 0.09 | 168 ok | 8 | `sha256:ff9a24bb18094b29e99207636b015ba4146cc7b6f62d645848d4b5c158a6659c` |

下表为每个完整 margin90 case 的21轮 median；IQR、吞吐、native actual tolerance、11项 device 外围成本和 raw row/hash 链保留在 [summary.json](summary.json)。wall 是独立 Session 生命周期及各自完成边界，单位 ms。Ratio 为 raw bytes / full wire bytes，低于1表示 expansion。Host/device 值不可合并为同一个计时估计。

## cuszp-margin90-0p01-20261013

| Dataset | Boundary | Encode ms | Decode ms | Wire bytes | Ratio | max_abs |
|---|---|---:|---:|---:|---:|---:|
| f32-tail-33 | host_to_host | 1.787929 | 0.974259 | 1836 | 0.071895 | 0.0084209442138671875 |
| f32-tail-33 | device_resident | 0.438168 | 0.189741 | 1836 | 0.071895 | 0.0084209442138671875 |
| f32-medium-32769 | host_to_host | 2.974533 | 1.950961 | 51114 | 2.564385 | 0.008998870849609375 |
| f32-medium-32769 | device_resident | 0.661188 | 0.445504 | 51114 | 2.564385 | 0.008998870849609375 |
| f32-large-1048576 | host_to_host | 26.900276 | 15.796996 | 1603594 | 2.615565 | 0.0090007781982421875 |
| f32-large-1048576 | device_resident | 1.666992 | 0.959406 | 1603594 | 2.615565 | 0.0090007781982421875 |
| f64-tail-33 | host_to_host | 1.768624 | 1.193646 | 1821 | 0.144975 | 0.0088790299500161041 |
| f64-tail-33 | device_resident | 0.437865 | 0.230441 | 1821 | 0.144975 | 0.0088790299500161041 |
| f64-medium-32769 | host_to_host | 2.764526 | 1.838340 | 51107 | 5.129473 | 0.0089998116719058885 |
| f64-medium-32769 | device_resident | 0.680214 | 0.425590 | 51107 | 5.129473 | 0.0089998116719058885 |
| f64-large-1048576 | host_to_host | 29.651506 | 16.932182 | 1603583 | 5.231165 | 0.008999991961598397 |
| f64-large-1048576 | device_resident | 1.750102 | 1.111521 | 1603583 | 5.231165 | 0.008999991961598397 |

## cuszp-margin90-0p1-20261013

| Dataset | Boundary | Encode ms | Decode ms | Wire bytes | Ratio | max_abs |
|---|---|---:|---:|---:|---:|---:|
| f32-tail-33 | host_to_host | 1.852328 | 1.031317 | 1803 | 0.073211 | 0.089792251586914062 |
| f32-tail-33 | device_resident | 0.503114 | 0.269607 | 1803 | 0.073211 | 0.089792251586914062 |
| f32-medium-32769 | host_to_host | 2.410968 | 1.548605 | 36365 | 3.604455 | 0.089994430541992188 |
| f32-medium-32769 | device_resident | 0.674759 | 0.335932 | 36365 | 3.604455 | 0.089994430541992188 |
| f32-large-1048576 | host_to_host | 25.732437 | 14.382173 | 1180717 | 3.552336 | 0.090002059936523438 |
| f32-large-1048576 | device_resident | 1.617361 | 0.918199 | 1180717 | 3.552336 | 0.090002059936523438 |
| f64-tail-33 | host_to_host | 1.554478 | 0.947031 | 1788 | 0.147651 | 0.086973375411556475 |
| f64-tail-33 | device_resident | 0.487275 | 0.218614 | 1788 | 0.147651 | 0.086973375411556475 |
| f64-medium-32769 | host_to_host | 2.709734 | 1.892545 | 36346 | 7.212678 | 0.089999841208975084 |
| f64-medium-32769 | device_resident | 0.662950 | 0.417486 | 36346 | 7.212678 | 0.089999841208975084 |
| f64-large-1048576 | host_to_host | 25.190764 | 14.286878 | 1180682 | 7.104883 | 0.089999916138300051 |
| f64-large-1048576 | device_resident | 1.623116 | 0.993496 | 1180682 | 7.104883 | 0.089999916138300051 |

## cuszp-real-f64-0p01-20261013

| Dataset | Boundary | Encode ms | Decode ms | Wire bytes | Ratio | max_abs |
|---|---|---:|---:|---:|---:|---:|
| etth1-single-f64-n128 | host_to_host | 1.852588 | 1.149428 | 2997 | 0.341675 | 0.0089999542236256502 |
| etth1-single-f64-n128 | device_resident | 0.508088 | 0.222249 | 2997 | 0.341675 | 0.0089999542236256502 |
| etth1-single-f64-n512 | host_to_host | 1.803688 | 1.119568 | 3569 | 1.147660 | 0.0089999542236256502 |
| etth1-single-f64-n512 | device_resident | 0.526800 | 0.226691 | 3569 | 1.147660 | 0.0089999542236256502 |
| weather-single-f64-n128 | host_to_host | 1.972752 | 1.190435 | 3030 | 0.337954 | 0.0080000000000008953 |
| weather-single-f64-n128 | device_resident | 0.458712 | 0.231468 | 3030 | 0.337954 | 0.0080000000000008953 |
| weather-single-f64-n512 | host_to_host | 2.089935 | 1.312153 | 3518 | 1.164298 | 0.0080000000000008953 |
| weather-single-f64-n512 | device_resident | 0.510214 | 0.245597 | 3518 | 1.164298 | 0.0080000000000008953 |

## cuszp-real-f64-0p1-20261013

| Dataset | Boundary | Encode ms | Decode ms | Wire bytes | Ratio | max_abs |
|---|---|---:|---:|---:|---:|---:|
| etth1-single-f64-n128 | host_to_host | 2.038340 | 1.237615 | 2944 | 0.347826 | 0.089999542236327557 |
| etth1-single-f64-n128 | device_resident | 0.487196 | 0.223759 | 2944 | 0.347826 | 0.089999542236327557 |
| etth1-single-f64-n512 | host_to_host | 1.787954 | 1.246929 | 3340 | 1.226347 | 0.089999542236327557 |
| etth1-single-f64-n512 | device_resident | 0.470615 | 0.235014 | 3340 | 1.226347 | 0.089999542236327557 |
| weather-single-f64-n128 | host_to_host | 1.881789 | 1.421418 | 2969 | 0.344897 | 0.089999999999999858 |
| weather-single-f64-n128 | device_resident | 0.533350 | 0.274278 | 2969 | 0.344897 | 0.089999999999999858 |
| weather-single-f64-n512 | host_to_host | 1.944261 | 1.421540 | 3305 | 1.239334 | 0.089999999999999858 |
| weather-single-f64-n512 | device_resident | 0.498769 | 0.260998 | 3305 | 1.239334 | 0.089999999999999858 |

## 资源证据与范围

实际设备为 NVIDIA GeForce RTX 2070，compute 7.5，CUDA runtime 11080 / driver API 12020。四 run 源 ID `sha256:742ab710be4354a9bcc393cb1b02388606bf39f7c7423c4303d6cb076bca7074` 和 native build `a61617a03e2e244a9ac87ecf83178d2feb3580ea4b43d3d088cdfc94e0da6498` 一致；Python/native 来源末尾均未变。

实际 host affinity `[0]`，object worker1，adapter algorithm host parallelism1。实际 RLIMIT_AS soft/hard 均17179869184 bytes（16GiB）；这是host地址空间，不能称RSS预算。VRAM effective limit为null，理由是当前adapter没有可强制cap。进程 Threads 另包含CUDA/runtime helpers。

| Run | 审计成功对象对（资格+warmup+formal） | Allocation/free | Stream create/release | Event create/release |
|---|---:|---|---|---|
| cuszp-margin90-0p01-20261013 | 336 | 3360/3360 | 672/672 | 1344/1344 |
| cuszp-margin90-0p1-20261013 | 336 | 3360/3360 | 672/672 | 1344/1344 |
| cuszp-real-f64-0p01-20261013 | 224 | 2240/2240 | 448/448 | 896/896 |
| cuszp-real-f64-0p1-20261013 | 224 | 2240/2240 | 448/448 | 896/896 |

每个已审计对象对的calling-thread native counters始末live bytes为0，增量含1次encode、1次decode、2个独立stream及4个event。该证据证明这些被计数的adapter对象回收，不能证明driver/context缓存为零；native Info owned peak是source申请capacity accounting，非整device实测VRAM峰值。CUDA events包含control/zeroing/必要传输，不能称纯kernel时间。

40个formal资格decoder均有全局唯一且不同于16个encoder worker的独立PID、exact artifact hash、相同执行/build/device身份、实际资源读回和通过的原始域质量。formal independent_recovery未保留各decoder的allocation/event/stream counters或process_snapshot，因此机器结果将这些字段置null并附原因；不能给这些进程补填计数或线程快照。独立native qualifier的48个fresh decoder有其自己的清理证据。每trial新建Session；新worker解释器的边界是session，不是每个trial。

ETT OT精确物理单位未核实；weather T以列名记录degree Celsius。两个source分别描述；同源128是512前缀，已有CPU窗口暴露，不能视作更多独立source或blind holdout。小数组的最小rate table和完整schema/provenance header会产生expansion。没有CPU基线，不能把device_resident与CPU object_memory的时间直接解释为speedup。

全部原始trace集合ID：`sha256:91968563430644d68b3cc0a3f515642f5304d7a0916a24353fc80678ee8212cd`；[summary.json](summary.json)给出每个manifest/observation/config/report/artifact SHA和case对应JSONL行索引。
