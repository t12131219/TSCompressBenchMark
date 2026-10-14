# GPU builder smoke 独立只读审计

[cuszp-builder-check-20261013](../../runs/gpu/cuszp-builder-check-20261013/manifest.json) 的4个ready case对应28个正式槽位；schedule、planned、started、terminal六字段键逐项一致，没有重复、缺失或foreign run。28个terminal全部ok，另有4次exact资格与8次预热，不混入正式分母。完整机器证据见[gpu_builder_smoke_independent_audit.json](gpu_builder_smoke_independent_audit.json)。

40个encode/decode结果均为strict质量通过、input_unchanged、violation=0，task bound 0.01、native requested bound 0.009。calling-thread adapter累计allocation/free 400/400、stream create/release 80/80、event create/release 160/160，每对encode/decode launch各1、live bytes始末0。这些是adapter计数，不是CUDA运行时全部分配或采样VRAM峰值。

实际核对源码closure、33个snapshot文件、native binary/build record、source/header/runtime/toolchain及两个fixture的字节hash；source ID为`sha256:1e37ea146c0e477862fc732278ab1394162c5c9cc5dcf7eb90a6ed63f4c56cd1`。4个wire恢复decoder PID全异且与两个worker PID不相交；保存的decoder provenance、实际profile与wire的descriptor/part/CSP1 metadata/payload、dtype、原生shape、实际bound一致。decoder恢复没有保存native diagnostics或process snapshot，不能用main worker计数补造。lossy restored object identity本来可以与原始不同，质量判据仍是原始域strict bound。

10份已保存actual profile一致：CPU affinity[0]、native thread1、object workers1、16GiB RLIMIT_AS、RTX2070／CUDA11.8。VRAM limit为null并明确不能实施。进程实际映射Anaconda C++/GCC runtime，与build记录的system runtime分别核对，不称两者相同。

run created UTC `2026-10-13T11:51:47.748636+00:00`，environment-after capture finished UTC `2026-10-13T11:51:51.383627+00:00`；前者晚于保存的installed validation output mtime `2026-10-13T11:48:06.238716Z`。这是run级窗口核查，没有per-trial绝对UTC。仅两个synthetic对象、一个session、两个独立boundary，证明修复后控制路径下的声明范围smoke成功；不据此声明新广域性能、设备重置/OOM恢复或普遍质量保证。本审计没有运行codec/native/CUDA、下载或新增测量，没有修改原run。
