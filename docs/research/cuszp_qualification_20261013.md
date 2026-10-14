# cuSZp 真实 GPU 资格检查（2026-10-13）

新增 GPU 扩展 `cuszp-fixed-1d` 已在实际 RTX 2070 上完成正确性资格检查；它独立于
36 个原有 CPU key。[原始报告](../../runs/cuszp-qualification-20261013-v2/qualification.json)
的 SHA-256 为 `36332d353cbf3643515878fd6f24cdd80a48ce05596346d36aa9e7111c68b387`。
[审计摘要](cuszp_qualification_20261013.json) 逐项绑定 binary、source card、脚本和
历史失败证据，不包含正式吞吐或延迟结论。

| 检查 | 实际结果 |
| --- | --- |
| 普通样例 | 48 个，float32/float64 × 8 个 N × zero/grid/offgrid |
| N | 1、31、32、33、257、32767、32768、32769 |
| host/device | 所有 native wire 完全一致，原始 host/device 输入不变 |
| 独立恢复 | 48 个 fresh process，只从 persisted wire 初始化 decoder |
| 严格 ABS | 最大误差 0.00092518329620361328，actual/requested bound 0.0009765625 |
| 失败子进程 | 30 个：10 源域拒绝、8 native rate 拒绝、8 native owner 配置/kind 拒绝、4 wire 损坏拒绝 |
| 失败阶段 | 预检或已分配 CUDA input/payload/stream 后的 native owner match；均未启动 kernel |
| 意外错误 | 0 |
| 父进程真实 kernel 启动 | encode 96、decode 48 |
| 父进程资源计数 | allocations/releases 720/720；streams 144/144；events 288/288；live bytes 0 |
| 子进程资源和 binary | 78 个 PID 各自计数平衡，实际 mapped native library 均为同一 SHA-256 |

最终 build identity 为 `a61617a03e2e244a9ac87ecf83178d2feb3580ea4b43d3d088cdfc94e0da6498`，binary SHA-256 为
`22cd81dae3542b57fbb89c936197f750849e112a1be085fe45e090ef78ee756f`。CUDA runtime 为 11.8，driver API 为 12.2，device compute
capability 为 7.5；实际 loaded driver 为 `libcuda.so.535.288.01`，其 hash 在 raw
report 的 process maps 中保存。编译使用固定上游提交的原版 1D FIXED kernels；
[来源审查](cuszp_integration_review.md)、[契约](../../adapters/cuszp/contract.md) 和
[独立能力卡](../../registry/gpu/cuszp-fixed-1d.json) 记录选择范围与约束。

资格过程中发现单 tile 的上游 global size offset 未写入：初次运行完成一个全零
样例后，在非零 N=1 对象的长度校验处失败。保留了
[原运行 partial checkpoint](../../runs/cuszp-qualification-20261013/qualification.partial.json)
和 [独立真实失败重现](../../runs/cuszp-qualification-20261013/single-tile-failure.json)。
重现进程的 encode launch=1、allocation/release=5/5、stream=1/1、event=2/2、live=0；
它证明该 host-wrapper 失败路径释放了 checked objects，不是 CUDA context fault
恢复证据。wrapper 改为单 tile 读取 `locOffset[1]`，未改动上游 kernel。原进程退出
时尚未保存完整失败 report，因此不补造当时未捕获的状态；新版资格工具在异常时
保存 stage、build/script/source hashes、diagnostics 和 worker stderr。

另一个差异由独立 Python 3.14 / NumPy 2.5 检查发现：NumPy 2 标量比较可能将
Python requested bound 下转换为 f32，掩盖向上取整。bridge 使用 `float(actual)`
比较后，两个环境的 wire tests 均为 19/19 通过。当前真实 GPU 资格运行使用
`/home/fzg/anaconda3/bin/python`、NumPy `1.24.3`；不会把纯 wire tests 表述为第二环境的
实际 GPU 执行证据。

进程 `/proc/self/status` 在 device init 后观察到 VmSize
5,063,950,336 bytes，所有 parent/child 观测中的最大
VmSize 为 5,508,485,120 bytes，VmPeak 为
5,602,312,192 bytes，VmRSS 为 174,600,192
bytes。此结果用于 GPU executor 选择大于实际 CUDA 虚拟地址占用的 finite host
RLIMIT_AS（16 GiB 可作后续配置）；这些值不是设备 VRAM、allocator peak 或完整
系统内存测量。后续实验必须读回实际 host limit，严格 GPU 分配上限目前未提供。

这些是有限数据域的实际正确性证据。特殊值、N、量化量级和 ABS 参数仍按能力卡
逐输入预检，完整恢复仍需逐 trial 验证 requested bound。OOM、kernel execution
fault 和失败 context 的恢复没有注入资格检查，不能依据 counters 平衡声称其已
验证。所有 device_event_ms 仅保留作路径证据，本文件不将其汇总为正式性能。
