# PeMS 原生三维 values 正式结果

48个请求：36 ready、12 Chimp128 rank3 unsupported；36/36可执行case、756/756正式trial全部ok。请求网格对应1008个nominal slots，实际schedule仅包含36个ready case × 3 sessions × 7 rounds = 756个槽位；预热与资格不加入正式分母。

756个正式结果均通过原始域bitwise恢复与input_unchanged验证，实际terminal与预定756个schedule槽位逐项一致；12个unsupported请求仍在完整请求分母中，性能为null。36个可执行case还各完成一次exact-input wire-only恢复：decoder实际由新subprocess启动，只接收wire和实现roots，保存returncode=0、恢复验证、artifact hash和decoder_runtime。恢复记录没有保存decoder_pid、execution_provenance、native_diagnostics或effective_profile，不能补造或声称这些字段已逐项核验。case的admission记录affinity `[0..15]`、1 native thread、1 object worker和4GiB RLIMIT_AS；它不等于每轮或独立decoder都保存了同样的profile观测。

来源为同一 Caltrans PeMS／作者 ASTGNN 发布体系的四份 NPZ，保留 `<f8`、C-order、time/sensor/feature 三轴及原始 shape。未构造 T、mask 或采样频率；所有 0 bits 按原样恢复。128／512 是8192窗口的前缀，已有历史暴露，不能称盲测或四个独立采集总体。原始数据及派生 wire 不进入默认复现导出包。

原始证据：[manifest](../../runs/current-pems-20261013/pems-values/manifest.json)、[observations](../../runs/current-pems-20261013/pems-values/observations.jsonl)、[完整描述表](../../runs/current-pems-20261013/pems-values/report/README.md)、[机器报告](../../runs/current-pems-20261013/pems-values/report/summary.json)。输入冻结与精确来源见 [preparation](../../benchmark/experiments/pems-values/preparation.json) 和 [来源核查](../research/additional_data_sources.md)。

以下为8192行大窗口的 object_memory 中位数。Stored fraction为`stored_bytes / raw_bytes`；stored_bytes是完整持久化wire的实际长度，包含格式前缀、descriptor和payload，不能把Finish或关闭耗时称为存储字节。

encode计时覆盖本次`encode_once`生成完整wire的操作；原生路径包括创建session、压缩、Finish/finalize及关闭，Finish若实际输出字节也进入payload。decode计时覆盖同一worker中本次`decode_once`的wire解析、输出分配、原生session恢复与关闭、原始对象重建。独立subprocess恢复是额外的计时外资格验证，其启动和文件I/O不加入表中decode速度。数据解析、输入指纹前置检查、质量/bitwise验证及资格也在计时外；计时范围见[CPU executor](../../benchmark/src/tsbench/executors/cpu.py)、[ObjectScheme](../../benchmark/src/tsbench/schemes.py)与[C ABI bridge](../../benchmark/src/tsbench/bridges/c_abi_v1.py)。cache policy为natural。四份大输入逻辑bytes均超过本机20MiB共享L3容量；未主动干预cache，不由容量比较推导性能原因。

manifest记录本次run窗口为UTC `2026-10-13T11:52:44.479456`–`12:02:02.915135`，`execution_source_unchanged=true`。它晚于[安装构建测试](../research/installed_build_verification.json)日志结束UTC `11:48:06.238716`，两者窗口无重叠。保存的raw没有per-trial绝对UTC；这里用run级窗口核对，不推定每个trial的绝对开始/结束时刻。

| File / shape | Method | Raw MiB | Stored fraction | Encode MiB/s | Decode MiB/s |
|---|---|---:|---:|---:|---:|
| pems03-native-n8192 / 8192×358×1 | raw-store | 22.375 | 1.00006 | 236.72 | 1078.4 |
| pems03-native-n8192 / 8192×358×1 | zstd-frame | 22.375 | 0.226511 | 119.778 | 360.09 |
| pems03-native-n8192 / 8192×358×1 | deflate-zlib | 22.375 | 0.210998 | 18.5472 | 302.936 |
| pems03-native-n8192 / 8192×358×1 | chimp128 | 22.375 | — | — | — |
| pems04-native-n8192 / 8192×307×3 | raw-store | 57.5625 | 1.00003 | 210.547 | 711.019 |
| pems04-native-n8192 / 8192×307×3 | zstd-frame | 57.5625 | 0.256345 | 103.537 | 394.965 |
| pems04-native-n8192 / 8192×307×3 | deflate-zlib | 57.5625 | 0.263287 | 24.1527 | 268.472 |
| pems04-native-n8192 / 8192×307×3 | chimp128 | 57.5625 | — | — | — |
| pems07-native-n8192 / 8192×883×1 | raw-store | 55.1875 | 1.00003 | 187.056 | 640.493 |
| pems07-native-n8192 / 8192×883×1 | zstd-frame | 55.1875 | 0.22945 | 102.978 | 352.483 |
| pems07-native-n8192 / 8192×883×1 | deflate-zlib | 55.1875 | 0.219482 | 17.0418 | 279.684 |
| pems07-native-n8192 / 8192×883×1 | chimp128 | 55.1875 | — | — | — |
| pems08-native-n8192 / 8192×170×3 | raw-store | 31.875 | 1.00005 | 227.85 | 1073.87 |
| pems08-native-n8192 / 8192×170×3 | zstd-frame | 31.875 | 0.2448 | 103.462 | 379.906 |
| pems08-native-n8192 / 8192×170×3 | deflate-zlib | 31.875 | 0.257281 | 24.4658 | 244.225 |
| pems08-native-n8192 / 8192×170×3 | chimp128 | 31.875 | — | — | — |

Chimp128没有原生rank3接口，此处保留unsupported与null性能；没有flatten、降精度或更换算法。不用两个byte codec的不同大小／速度取得一般总体赢家。

```bash
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
python -m tsbench report runs/current-pems-20261013/pems-values
```

该命令只读raw重生成描述报告，不运行codec。新测量可用冻结配置与新build/output root调用 `replay_environment.py`；精确数据许可、传感器映射与单位未知项继续保留。[获取与校验路线](../pems_acquisition.md)提供固定URL和hash；本机formal使用已有本地数据，不证明新获取器已成功下载远程四份NPZ。
