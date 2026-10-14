# 真实对象与方案消融

本目录冻结 ETT / weather 的同步多变量、真实时间戳、完整记录和同单位温度 ABS 实验。生成器只解析输入、检查参数及声明能力，不执行 codec 或计时。准备时 152/152 请求通过声明能力预检；正式 admission 还必须执行边界资格、独立 wire 恢复和原域质量验证，预检不是通过这些检查的证据。

| 配置 | 对象 | 方法/方案 | 请求 | 3 sessions × 7 rounds 名义试次 |
|---|---:|---:|---:|---:|
| real-mts-lossless | 8 | 7 | 56 | 1176 |
| real-timestamps-lossless | 4 | 5 | 20 | 420 |
| real-records-lossless | 8 | 5 | 40 | 840 |
| real-temperature-abs-0p01 | 6 | 3 | 18 | 378 |
| real-temperature-abs-0p1 | 6 | 3 | 18 | 378 |
| 合计 | 32 任务/配置对象描述 | — | 152 | 3192 |

所有对象使用新窗口 `[2048,2176)` / `[2048,2560)`。长度 128 是 512 的前缀，C/F 布局和 task projection 共用原始观测；32 条对象描述对应 26 个精确 canonical object ID，ABS 两个界限复用同一输入。开发区 `[0,2048)` 包含先前 pilot `[0,512)` 和旧 CPU 测量 `[1024,1536)`，本实验窗口不与这些已知性能窗口重叠。全源已解析和画像，不能将它称为盲测或独立的总体抽样。

MTS/records 保留 ETT 全部 7 通道和 weather 全部 21 通道。ABS 保留 ETT 的 OT、weather 的 T/Tdew/Tlog，均为 degC；不对压力、温度、风速等不同单位混用同一个语义误差尺度，不做隐式缩放。原 CSV header 中的 replacement characters 和 weather 的 `OT` 名称保留，数据来源目录已记录其与官方 CO2 列的对应。

MTS 包含 raw-store、完整矩阵 Zstd、Chimp128，以及 Zstd 的 channelwise、chunk_rows=64、chunk_rows=256、channelwise+chunk_rows=64。chunk 是独立 codec reset，目录/描述符和每个子流的完整开销均应计入 wire；chunk256 对 n128 没有分块，仍作为明确声明的方案保存。

时间戳为原始 int64 纳秒，日期按 naive wall clock 相对 epoch 的整数算术表示，不主张源时区。T 实验采用 raw-store、Zstd、raw+integer_affine_gcd、NeaTS+integer_affine_gcd、LeaTS+integer_affine_gcd。归一化的 bias/scale 进入 wire，恢复后验证原始纳秒位。它不声称修复了历史直接输入 epoch-ns 的 NeaTS/LeaTS 限制。Records 分别使用 raw、Zstd，以及 Chimp128 V 搭配 Zstd/归一化 NeaTS/归一化 LeaTS T。输入没有缺失，不构造虚假的 mask 或伪造缺失观测。

本实验只有 object_memory / independent_object / natural 边界、CPU 单 native thread、单 object worker。CSV 解析和画像在计时外，Python layout、分块/变换、FFI、校验身份及完整容器在对象时钟内。ABS 禁用 native-only timing。C/F 是相同逻辑组件在不同 canonical 布局下的配对干预，raw_object_id 有意不同，不能并为同一个精确对象排行榜。

从仓库根目录准备或复核配置：

```bash
PYTHONPATH=benchmark/src python benchmark/tools/generate_real_objects.py
PYTHONPATH=benchmark/src python benchmark/tools/analyze_real_objects.py freeze-components
PYTHONPATH=benchmark/src python -m pytest benchmark/tests/test_real_objects.py -q
```

生成器拒绝覆盖任何不同的冻结 design/config/preflight/characterization。`preflight.json` 是准备时源码/卡/配置/安装实现的快照；后来核心实现的修改不回填这份历史预检。需要为改变的设计或预检建立新的准备目录，正式运行的 manifest 独立保存其实际源码与实现身份。

以下命令是正式执行入口，需在核心检查完成、其他正式测量停止后顺序执行；本目录准备过程尚未运行它们。输出已存在时选用新的 `--output`，不要给旧记录换实现标签。

```bash
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/real-objects/real-mts-lossless.toml
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/real-objects/real-timestamps-lossless.toml
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/real-objects/real-records-lossless.toml
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/real-objects/real-temperature-abs-0p01.toml
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/real-objects/real-temperature-abs-0p1.toml
```

正式完成后，可只读生成全部状态和配对表：

```bash
PYTHONPATH=benchmark/src python benchmark/tools/analyze_real_objects.py analyze \
  runs/real-mts-lossless-20261013 \
  runs/real-timestamps-lossless-20261013 \
  runs/real-records-lossless-20261013 \
  runs/real-temperature-abs-0p01-20261013 \
  runs/real-temperature-abs-0p1-20261013 \
  --output docs/real_object_results
```

默认 lossless 基线是实际声明的 `zstd-frame`，每个 ABS run 的基线是 `zfp-accuracy-1d`；`--baselines` 接受 manifest experiment name 到 method id 的 JSON 映射。每条 scheme 比较保持同 raw_object_id、完整 task/error/profile/boundary、相同 schedule session/round、资源和实际实现条件；C/F 行同时保存两个 raw_object_id 和冻结的 C-order bitwise component hashes。完整 schedule、全部 attempt/status、最早已执行失败和精确 observation line 保留在 summary。假定全部 admission 和 scheduled trials 完整时，将有 120 scheme pairs 和 60 C/F pairs。只有两个来源，表述仅限条件性探索性描述，不给总体优胜者、显著性或人口总体推断。
