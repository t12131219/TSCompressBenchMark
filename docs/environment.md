# 环境、限制与独立资源证据

[独立 collector](../benchmark/src/tsbench/environment.py)补齐计划§10／§11的环境字段。历史补充不修改旧manifest/raw或已测量身份；新runner在admission前及measurement结束后调用同一collector，另存相邻快照。它读取procfs／sysfs、Python安装metadata、编译记录及只读Git信息；不运行codec、GPU workload、perf、能耗采样，也不修改电源、NUMA、BIOS或cache。

```bash
# 对历史run生成只读补充。新JSON与原manifest/raw分开保存。
python -m tsbench.environment \
  --manifest runs/all-lossless-explicit-runtime-final-20261013/manifest.json \
  --output docs/environment/cpu-final-retrospective-20261013.json

# 新run可额外保存外层before/after快照；runner自身也保存计时外快照。
python -m tsbench.environment \
  --config benchmark/examples/minimal.toml \
  --run-output runs/minimal-environment-capture \
  --output docs/environment/minimal-before-after.json

python -m pytest benchmark/tests/test_environment.py -q
```

已有输出不覆盖。`--config` wrapper执行正常runner，前后capture在run外；它不提供每个trial的频率／资源采样，也不赋予run新的executor能力。

环境字段分成两种事实：historical部分保存原manifest的环境／effective profile和原raw的hash，并核对其引用build.json的hash；current部分仅描述collector运行当时的可见环境。旧manifest没有记录的物理拓扑、NUMA策略、频率／电源、cgroup bounds、Git dirty revision、完整安装包清单继续为**null及not_recorded_at_run理由**。后来读到的频率或governor不能倒填为benchmark运行时条件。pool supplement另外校验实际admission manifest的hash，保留已有父进程baseline／final资源字段；逐worker资源仍以pool raw为准。

current capture含在线CPU的package／core／thread sibling拓扑、可见物理core数量和SMT状态、各CPU共有ISA、recorder affinity、NUMA节点和允许节点；NUMA allowed set不是实际内存placement。频率给proc cpu MHz瞬时值和sysfs governor／driver／min／max／current／energy preference；powercap只读constraint和enabled值，不能当能量观测。GPU PCI存在／driver文件单独记录，显存／runtime／executor可用性未经真实接口验证则为null及原因。缺文件、无权限、空内容、拓扑不完整均保留具体理由。

cgroup v2只读当前暴露的cpu.max、cpuset、memory／swap／pids bounds。隐藏的ancestor可能另有限制，不能把可见leaf的`max`写成整台机器无限预算；cpu quota也不是native线程数。resource profile目前确实实施worker affinity及RLIMIT_AS；线程环境在NumPy/native前设置，而实际native thread支持仍由源实现／card和pool的Threads观测约束。NUMA／frequency／power不控制；RLIMIT_AS限制进程虚拟地址空间，不能称RSS预算，不能称对整个pool集合的共享限制。

Python环境记录解释器真实路径／hash、sys.version／prefix、OS版本、完整已安装distribution名称／版本及其内容身份，以及明确的编译器／线程／loader相关环境变量。没有读取任意环境变量或秘密。Git revision和dirty摘要通过禁用optional locks的read-only命令取得。安装包版本清单是环境inventory，**不是包含可下载wheel／来源hash的依赖lock**，不能保证重建或跨平台；实际build.json保存编译器hash／version、真实command flags、source closure、toolchain和runtime dependency身份。supplement按原hash核对这些记录，而不是用今日compiler重新解释旧结果。

[CPU最终run的回溯补充](environment/cpu-final-retrospective-20261013.json)核对了31个不同native build记录，全部与原manifest记录一致；[pool最终run补充](environment/pool-final-retrospective-20261013.json)核对了1个Zstd build及admission引用，全部一致。录制当时的可见环境为10个在线物理core／16个在线logical CPUs、SMT active、1个NUMA节点、16个cpufreq policy和2个可见powercap domain；这些是**补充录制时**的read-only事实。当前容器cgroup未暴露CPU／cpuset controller，对应budget为null及理由；memory.max为`max`只描述暴露leaf，ancestor有效预算未知。发现1个PCI display device不证明GPU可运行；后续[宿主范围只读探测](research/gpu_host_probe.json)已确认RTX2070可见，原rc9仅为沙箱surface不可见设备。CUDA运行能力仍须真实接入和资格证据。

六项测试验证完整／不完整拓扑、SMT和null理由、权限拒绝、cgroup隐藏父层、历史manifest不改写／编译记录漂移，以及实际Linux资源限制。资源测试在新的无codec进程中先调用既有apply_profile，再读回128MiB RLIMIT_AS和指定affinity，256MiB mmap确实被拒绝，NumPy尚未导入。这证明本机该机制可实施；它不能倒填每个历史worker未记录的getrlimit读回值。

既有profile pass以独立run读取resolved配置，Linux sampler覆盖runner及可观测后代。总RSS采样峰值是下界，共享页可能重计；CPU tick可漏掉短进程。进程lifetime ru_maxrss、per-run sampled peak、per-trial incremental峰值分别命名，不相互替代。新runner的collector只在所有trial时钟外执行，不进行trial内采样；resource pass的时间与主performance不是同一次观测；没有能量／GPU采样证据则相应指标为空。当前不凭相邻snapshots宣称资源因果、频率锁定或完整环境复现。

新manifest保存`execution_provenance`中具名runner／config／records／worker／measurement／bridge源码hash，并在`source/tsbench`保存实际源码字节快照。resume核对执行源码身份；report／study／trial_analysis代码只进入分析身份。末尾再次核对源码闭包，检测到运行中源码漂移时标记`execution_source_unchanged=false`及interrupted，完整性能报告不视为有效完整case。新worker在实际设置RLIMIT_AS后读回soft／hard bytes；该证据不能倒填旧worker。volatile frequency／power／NUMA快照与严格resume环境身份分开。
