# PeMS 原生三维值对象实验

冻结 4 个作者 NPZ × 3 个窗口（128、512、8192），统一 `[1024,1024+n)`；保持原始 `<f8`、C order 和 `time/sensor/feature` 轴，只有 V，没有推定时间戳。raw-store、zstd-frame（level 3）、deflate-zlib（level 6）和 chimp128 各占一个请求；Chimp128 声明只支持 rank 1/2，本实验的 12 个 rank 3 请求应记为 unsupported，并保留在分母中。

正式协议为 bitwise、object_memory、independent_object、natural cache、CPU 单 native thread / 单 object worker、4096 MiB RLIMIT_AS、2 warmups、3 sessions × 7 rounds；共 48 请求 / 1008 名义轮次，其中 36 请求 / 756 轮次在声明能力内。生成器只读取原始数据、核验 hash、序列化/解析配置并检查声明能力；没有执行 codec、资格测试或计时。实际安装、内容资格、重建正确性和性能结果以独立正式运行目录为准。

`preparation.json` 保存本地 SHA-256、作者固定 ref/blob/raw URL、原生数组头、12 个 typed-byte hash、完整窗口 lineage、有限/特殊值计数、配置及解析依赖 hash、cpu0 sysfs 原文/hash。作者固定仓库文件的 Git blob SHA-1 和长度与本地相等；未下载远程 NPZ、未重算其 SHA-256。精确预处理文件许可证、单位及提取/插补历史未知；这些来源曾被历史工作观察，不是盲测 holdout。三个窗口嵌套，共用源观测；轮次只描述当前环境，analysis inference=none。

8192 行的逻辑输入逐个超过观测到的 cpu0 shared L3 容量。这里只比较输入字节数与 sysfs 容量；没有 cold/warm cache、内存带宽或缓存导致性能变化的结论。自然缓存策略和实际 worker 位置仍由正式 manifest 记录。

在项目根目录执行纯准备：

```bash
PYTHONPATH=benchmark/src python benchmark/tools/generate_pems.py
```

文件冻结后，重新生成若发现差异会停止并要求新输出目录；旧准备证据不会被覆盖。通过正式运行入口执行 `pems-values.toml`，或复制配置到新 replay 目录并显式设置新 `build_root` 和 `output` 后执行：

```bash
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/pems-values/pems-values.toml
```

正式运行不得与构建、测试或其他 codec 工作负载并发。复现时应保留配置内容、准备文件和 run manifest 的实际 build/source 绑定，不能把新的 build hash 写回历史 run。
