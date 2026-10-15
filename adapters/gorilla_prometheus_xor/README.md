# Gorilla / Prometheus XOR — TSBench binding

核心是冻结的 `gorilla-prometheus-xor-cpp-v1` C++17 实现，来自已验收的 v1.0.0 发布包。`FROZEN_SOURCES.json` 记录归档、上游 revision 和每个文件的 SHA256，构建时强制检查；核心文件未改动。`vendor/gorilla` 仅包含接入所需源码、许可、golden vectors 及独立验收文档，原 CMake 引用的独立工具未全部复制，Bench 通过自己的配方直接编译。

`native/tscb_gorilla.cc` 遵循现有 `tscb_adapter_v1.h`。输入为 N 个交错的 LE int64 timestamp / uint64 value_bits，16N 字节；N ≤ 65535。输出是完整 Prometheus raw EncXOR chunk，前两字节是 BE uint16 样本数，无额外原生信封。canonical/optimized 都使用独立新上下文。输出容量至少为核心最坏界；失败不提交输出，Finalize 返回零字节且可重复；Reset 仅支持 mode 0。显式 LE 装拆无 float 运算，不转换时间单位，不修改输入，不允许缓冲重叠，safe overread = 0。

Python joint scheme 要求真实 T/V：T[N] int64、V[N] float64，或显式 `channelwise=true` 的 V[N,M]；更大 N 显式声明 `chunk_rows<=65535`。每列每块独立压缩，重复 T、原样 mask、chunk 目录、hash 和完整 wire 都计费。无 values-only fallback、float32 cast、隐式时间戳、排序和插值；stream/query/random access 未暴露。独立实现的 FULL_PARITY 与 Bench 接入资格分别记录。

上游部分字节 chunk 序列化重载后追加的恢复缺陷已保留在核心及原验收报告。Bench 只调用 fresh one-shot chunk，不暴露该追加路径。原始核心许可 Apache-2.0 AND BSD-2-Clause；本绑定及安全测试 MIT（仓库 LICENSE）。

```bash
PYTHONPATH=benchmark/src python -m tsbench build gorilla-prometheus-xor
PYTHONPATH=benchmark/src python -m pytest benchmark/tests/test_gorilla.py
```

接入验收见 `docs/gorilla_integration/README.md`；真实输入方案见 `benchmark/experiments/gorilla/records.toml`。
