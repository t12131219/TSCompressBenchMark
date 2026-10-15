# Gorilla records experiment

固定 ETTh1（7 列）、weather（21 列）、ILI（7 列），每源两个嵌套窗口 128/512 行；起点分别 2048/2048/256。CSV 与既有 catalog hash 一致，具体列名以 UTF-8 原始 header 为准。显式把 date 解析为 int64 ms；不与历史 ns 输入混为同一对象。

canonical/optimized 两路径都 channelwise、chunk_rows=128，另用 raw-store 与 Zstd level 3 作完整 records 对照。24 cases，3 sessions × 7 rounds = 504 trials，单对象执行，每轮验证 bitwise 恢复及输入未改。设计及源文件 hash 在 design.json 中，禁止据本次性能结果调参或泛化排名。

```bash
PYTHONPATH=benchmark/src python -m tsbench build gorilla-prometheus-xor zstd-frame
PYTHONPATH=benchmark/src python -m tsbench inspect benchmark/experiments/gorilla/records.toml
PYTHONPATH=benchmark/src python -m tsbench run benchmark/experiments/gorilla/records.toml
PYTHONPATH=benchmark/src python -m tsbench report runs/gorilla-real-records-20261015
```

重新运行用 `--output` 指定新的目录，保留历史 run。验收见 docs/gorilla_integration/README.md。
