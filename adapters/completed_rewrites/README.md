# 完成重写算法的 Benchmark 接入

这里消费独立 C++ 重写包的冻结副本，原始 `Compression_Rewrite/ReWrite` 保持不变。
`FROZEN_SOURCES.json` 同时记录原文件、副本及上游 provenance 的 SHA-256。
每个入口都有 source artifact、codec manifest、接入卡、运行配置和测试；
`AdapterFactory` 将它们送入现有五层 Runner。

| 包/入口 | Track | 输入与限定 |
|---|---|---|
| abba / fabba | VALUE | binary64；保留原分段、聚类和重建；没有通用逐点误差保证 |
| tristan / corad | VALUE | binary64 矩阵、完整窗口；字典学习、归一化统计和反归一化均包含在路径中 |
| influxdb-tsm-adaptive-timestamp | TIMESTAMP | int64；原 STREAM/BATCH 编码选择逻辑 |
| prometheus-xor2-chunk | SYSTEM | T+binary64；ST 为显式参数配置的对象内常量；完整联合码流 |
| prometheus-histogram-st / prometheus-float-histogram-st | SYSTEM | 独立 T 和六个 uint64 位字段；gauge、schema 0、一个正桶；普通 scalar CSV 不符合该合同 |
| deepzip | VALUE | uint8；17 个冻结模型均为 4 符号词表，只接受 0..3；模型加载计入编码 |
| dzip | VALUE | uint8；输入的排序字母表决定原生初始模型；显式 seed、未训练 bootstrap / combined profile；9 符号字母表拒绝 |
| walloc-1d | VALUE | 源码约定的归一化 float32 双声道；官方 stereo_5x / stereo_20x 模型 |

这些是明确注册的 CPU、独立对象 profile。完整 standalone 实现保留，但 GPU、训练任务、
查询、原生随机访问及 Benchmark 增量 streaming 不在本次注册能力中；协商阶段拒绝相应请求。
DZip 要求 AVX，包含 MKLDNN dispatch，并保留两个各一个 worker 的 Eigen 线程池，进程预算为 3。
TRISTAN/CORAD 与 WaLLoC 以 `CPU_RUNTIME_DISPATCH` 声明实际依赖路径，避免把内部 SIMD 称为 scalar。

Python session 负责显式布局、窄 C ABI 和带 SHA-256 的 descriptor/container。
解码使用独立 session；DeepZip、DZip 和 WaLLoC 的模型状态在 native frame 中，
解码不依赖外部 checkpoint 或原始数据。FinalBits 等于实际最终容器字节数 × 8：
原生 header、字典、模型、归一化统计、payload、padding、校验都包含在完整 native frame 费用中。
当前账本不对这些内部字节做猜测拆分，`model_bits`/`dictionary_bits` 为 0 不代表模型免费。
SYSTEM 的不可分离 native frame 进入 `unallocated_shared_bits`，不猜测 T/V 各占比例。

ABBA、fABBA、TRISTAN、CORAD、WaLLoC 使用 `UNBOUNDED_LOSSY`。
dtype、形状、有限重构、T/V 配对等仍是正确性门禁，MAE/RMSE/MaxAE/PSNR/Temporal Fidelity
进入 raw 与 summary；`bound_passed` 和违反次数为 null，避免虚构误差界。
源码不能安全处理的有限端点算术、未完成窗口、常量列、归一化溢出等原子拒绝，
不做裁剪、填补、改值或 raw fallback。

构建（使用 CompressBench14）：

```bash
python tools/build_codec.py abba --profile all
python tools/build_codec.py dzip --profile all
python tools/build_codec.py walloc-1d --profile all
PYTHONPATH=src python tools/qualify_completed_rewrites_native.py
PYTHONPATH=src python tools/onboard_completed_rewrites.py
PYTHONPATH=src python tools/qualify_completed_rewrites.py --mode QUALIFICATION --suffix local-qualification
PYTHONPATH=src python tools/qualify_completed_rewrites.py --mode FORMAL --repetitions 20 --suffix local-formal
```

其他入口按相同 `build_codec.py <key> --profile all` 构建。
`TSCB_REWRITE_BUILD_JOBS` 可设为 1..16，默认 2。
MKL 使用冻结依赖锁指向的本地 runtime。WaLLoC 默认查找
`/home/fzg/anaconda3/envs/CompressBench/lib/python3.11/site-packages/torch`，
可用 `WALLOC_TORCH_ROOT` 指定其他位置；所有锁定依赖必须 SHA-256 匹配，否则失败。
runtime 的动态依赖、内部 dispatch 所需库、模型、build record 和 binding 源码进入执行身份。

ASan/UBSan 验证 framework binding 与冻结 C/C++ 源码，外部 MKL/LibTorch 二进制没有重新插桩。
sanitizer executable 禁用 PIE 以避免此环境的 ASan 地址布局冲突；leak detection 关闭，
因此不声称“所有外部依赖或泄漏检测均通过”。
PIPELINE/E2E 包含布局、容量查询、frame/model 处理，CORE 不支持；原生耗时字段为 null。

每个 FORMAL 配置预热至少 3 次/0.5 秒，保存全部 20 次重复，每次累计至少 1 秒。
至少 10 条通过所有门禁的 PASS 且全部预定重复记录齐全时才汇总。
RESOURCE_PRESSURE、OVERSUBSCRIBED、unsupported 等始终保留在 Coverage；不转成 PASS。
五种新 fixture 明确标为 synthetic，只证明接入闭环，不建立真实数据上的性能/质量结论。

最终验证及各入口证据见 `docs/completed_rewrite_integration_audit.json` 和
`docs/completed_rewrite_integration_review.md`；可用下列命令复核当前交付：

```bash
PYTHONPATH=src python tools/verify_completed_rewrite_integration.py --refresh-reports
```

许可证按实际冻结资料登记。TRISTAN、CORAD、DZip、WaLLoC 保留 NOASSERTION，
只依据已有用户决定及当前接入请求执行本地工作，没有产生上游授权或外部发布声明。
