# Gorilla（Prometheus XOR）接入验收

状态：**INTEGRATED**。本次恢复了意外回滚丢失的 Gorilla 接入，并重新执行构建、测试、安全检测、独立安装及真实数据实验。核心源码来自已验收的 `gorilla-prometheus-xor-cpp-v1`，24 个冻结文件与 v1.0.0 发布包、独立重写目录逐字节一致。没有用旧测试日志代替本次验证；旧的 36 codec、308 项测试和既有性能结果继续保留历史范围。

完整机器证据见 [evidence.json](evidence.json)，正式 run 为 `runs/gorilla-real-records-20261015`，配置见 [records.toml](../../benchmark/experiments/gorilla/records.toml)，预先固定的输入、窗口及成本约定见 [design.json](../../benchmark/experiments/gorilla/design.json)。

## 来源与能力范围

独立重写根目录：`/home/fzg/PycharmProjects/Compression_Rewrite/ReWrite/gorilla-prometheus-xor`。发布包：`/home/fzg/PycharmProjects/Compression_Rewrite/Release/gorilla-prometheus-xor-v1.0.0.tar.gz`，SHA256 为 `bc0629a38448d6a3fb33fd622204c8f137a74730a23273388cc528109442d519`。Prometheus revision：`8374d30cb3fe705773bbac72d7015eba17480557`。

[FROZEN_SOURCES.json](../../adapters/gorilla_prometheus_xor/FROZEN_SOURCES.json) 保存 24 个文件的归档成员、相对路径和 SHA256。每次构建验证这些文件，保留实际每个编译单元的系统头文件依赖、编译器和运行库身份。核心许可是 Apache-2.0 AND BSD-2-Clause，Bench 绑定与测试使用仓库 MIT 许可。vendor 是接入所需的冻结子集，Bench 直接编译源码；其原 CMake 引用的独立测试工具并未全部复制。

| 层次 | 已验证／暴露范围 |
|---|---|
| 独立重写 | 原始 G0–G6 为 REWRITE_DONE / FULL_PARITY；原报告中的 227 用例、489,274 对样本、100,000 次 fuzz、跨架构等是独立交付证据，本次未重复宣称这些工作已重跑 |
| 原生 Bench 绑定 | 现有 C ABI v1，真实 timestamp/value_bits 对，输出完整 raw EncXOR；canonical 与 optimized；safe overread 0 |
| Bench 对象协议 | records、独立 chunk、显式逐列 MTS、原样 mask、完整目录与恢复信息；值和时间戳保持位级一致 |
| 框架任务 | CPU、object_memory、independent_object、单线程；stream、query、random access 均未暴露 |

上游“部分字节 chunk 序列化重载后追加”的恢复缺陷保留在冻结核心和独立报告中。Bench 创建全新的 one-shot chunk，未暴露该追加路径。独立 FULL_PARITY 不推导为整个 Bench 的全域能力。

## 输入与完整成本

原生输入为 N 个交错的 LE int64 timestamp / uint64 value_bits，共 16N 字节；N≤65535。输出为完整 Prometheus raw EncXOR，前两字节为 BE uint16 样本数，不添加原生信封。绑定显式装拆 LE 字节，不进行 float 运算、时间单位转换、排序、去重或隐式转换。失败不提交输出或 used_bytes，压缩后须 Reset 再编码，Finalize 返回零字节且可重复。

对象侧要求 T[N] int64 和 V[N] float64。V[N,M] 必须显式 `channelwise=true`；超过 65535 行须显式 `chunk_rows<=65535`。每列每块使用独立上下文，重复的 T、原样 bool/uint8 mask、pair packing、FFI、Finish、hash、chunk/channel 目录和完整 wire 均计入对应成本。`codec_input_bytes` 包含重复时间戳；`stored_bytes` 是完整 wire 长度。values-only、timestamps-only、float32、隐式 MTS、组件路由和变换均拒绝，不回退到其他算法。

新对象 schema 为 `tsbench.gorilla-records/1`，继续使用现有 wire v2 的 descriptor 校验和。解码在分配对象前验证角色、dtype/shape、2 GiB 恢复上限、65536 part 上限、chunk 样本计数、路径参数、payload hash、无缺口/重叠的行与字节覆盖；其他列必须携带与第 0 列完全相同的时间戳。每块解码使用新 session，恢复原 C/F 布局和完整 schema。常规对象 schema 保持原有处理方式。

## 本次重新验证

| 检查 | 结果 | 证据 |
|---|---|---|
| 全部 CPU 构建 | 37/37 成功 | [build-all.json](build-all.json) |
| 完整回归 | 343 passed，0 skipped | [日志](tests-full.log)、[JUnit](tests-full.xml) |
| Gorilla 专项 | 35 passed，包括 36 组归档 Go golden 的两路径完整字节比较 | [日志](tests-focused.log)、[测试源码](../../benchmark/tests/test_gorilla.py) |
| 第二软件环境 | Python 3.14 / NumPy 2.5，35 passed | [日志](tests-alternate.log)、[JUnit](tests-alternate.xml) |
| 原生资格 | 两路径 × 0/1/2/17/257/65535，共 12/12 | [native-qualification.json](native-qualification.json) |
| ASan/UBSan/LSan | 16 次核心/ABI 往返，20,000 个随机畸形 chunk 拒绝，无越界或泄漏诊断 | [sanitizer.json](sanitizer.json)、[日志](sanitizer.log) |
| 独立安装 | wheel 安装后重新构建；34 个 Python 文件一致；移除编码端源码后新进程恢复成功；原生库与主构建字节一致 | [installed_verification.json](installed_verification.json)、[验证脚本](verify_installed.py) |
| 真实 records 实验 | 24/24 case，504/504 trial；24 个新进程精确输入恢复；6 组两路径完整 chunk 列表逐字节一致 | [run-audit.json](run-audit.json)、[run report](../../runs/gorilla-real-records-20261015/report/README.md) |

测试覆盖长度 0/1/2/6/7/8/65534/65535/65536、负数和极端时间戳、乱序/重复、NaN payload（含 signaling bits）、正负无穷、正负零、subnormal、C/F、多列掩码、自定义角色名、输出容量不足及 canary、重复 Finalize、Reset、截断/尾随字节、重新计算校验和后的目录损坏及跨列时间戳不一致。原生 sanitizer 使用两路径各 10,000 个长度 0..512 的随机字节；该范围区别于独立重写的原 fuzz 报告。

LSan 不能在 ptrace 沙箱中完成退出检查，本次安全驱动在已授权的宿主环境执行，具体编译命令、环境和二进制 hash 保存在 sanitizer.json。两个 Python 环境与独立安装均在同一台物理主机，不作第三方或第二台机器验证声明。

## 固定真实输入与限制

ETTh1 全 7 列、weather 全 21 列、ILI 全 7 列；每源 128/512 行两个嵌套窗口，起点分别为 2048/2048/256。CSV hash 与现有 catalog 一致，时间轴显式解析为 int64 ms，值为 float64。输入身份与历史 ns 实验不同。两路径显式 `chunk_rows=128`、`channelwise=true`；对照为 raw-store 和 Zstd level 3。固定 seed 20261015，3 sessions × 7 rounds，warmup 2，单对象顺序执行。

全部构建、回归和安全检测完成后才执行正式测量，每轮计时外检查 bitwise 恢复和输入未修改。调度无缺槽、额外槽或重复终态，执行源码身份在 run 前后保持一致。此实验只说明选定三源和窗口上的完整对象行为；目录成本、重复时间戳和小对象开销均保留，不作通用算法排名。

## 复现

在仓库根目录执行：

```bash
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
python -m tsbench build gorilla-prometheus-xor zstd-frame
python benchmark/examples/generate_fixtures.py
python -m tsbench inspect benchmark/examples/gorilla_records.toml
python -m pytest benchmark/tests/test_gorilla.py -q
python benchmark/tools/qualify_native_assets.py --codec gorilla-prometheus-xor
python -m tsbench inspect benchmark/experiments/gorilla/records.toml
python -m tsbench run benchmark/experiments/gorilla/records.toml --output runs/gorilla-records-reproduction
python -m tsbench report runs/gorilla-records-reproduction
python docs/gorilla_integration/audit_run.py runs/gorilla-real-records-20261015
```

复跑须指定新的 output 目录并保留历史 run。独立安装检查脚本使用新的、尚不存在的 `build/gorilla-installed-check-final` 目录；重复运行前应更改脚本中的目录名，以保留旧安装证据。
