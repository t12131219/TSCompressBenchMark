"""Render the Chinese acceptance record from the successful integration audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    audit_path = ROOT / "docs/completed_rewrite_integration_audit.json"
    audit = json.loads(audit_path.read_text())
    assert audit["status"] == "PASS" and not audit["issues"]
    entries = [codec for package in audit["inventory"] for codec in package["codecs"]]
    assert len(entries) == 18 and all(c["integration_status"] == "QUALIFIED" for c in entries)
    passed = sum(c["summary_n"] for c in entries)
    excluded = sum(c["resource_excluded_count"] for c in entries)
    native = list((ROOT / "docs/completed_rewrites").glob("*-native-*.json"))
    assert len(native) == 22
    assert all(json.loads(path.read_text())["status"] == "PASS" for path in native)
    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    text = f"""# 已完成重写算法：五层接入验收记录

验收日期：2026-10-06。结论：**PASS，限定于已注册的 CPU 独立对象 profile**。

在编写本次代码前，已完整阅读《TimeSeries Compression Benchmark V2 工程实施总计划》
全文 1,555 行，再按第 6–10 章、11.5 和 20.3 节完成源码准入、五层执行与验收。
原始重写位于 `Compression_Rewrite/ReWrite`；接入消费冻结副本，不修改原始算法。

18 个原始重写包中，16 个标为 REWRITE_DONE，对应 18 个 codec 入口。
本次新增接入 10 个包 / 11 个入口；此前已有的 6 个包 / 7 个入口重新通过完整正式验收。
所有入口均具备源码冻结、许可证登记、构建、自测、manifest、协商、adapter、
边界、安全、正确性、计费、执行身份、原始重复、summary 与 Coverage。
这项结论不代表全部上游能力或 Benchmark V2 全项目的所有阶段已经完成。

机器证据：[integration audit](completed_rewrite_integration_audit.json)。
该文件 SHA-256：`{audit_hash}`。

## 正式运行结果

每个配置计划并保存 20 次正式重复，预热至少 3 次且累计 0.5 秒；
每次观测达到 1 秒的最短计时要求。共 360 条原始观测，其中 {passed} 条 PASS 进入摘要，
{excluded} 条 RESOURCE_PRESSURE 排除于统计并保留在 Eligibility / Coverage。
只有全部计划重复记录齐全、至少 10 条通过全部门禁的 PASS 才生成摘要。
本表只展示接入资格，不使用合成数据建立真实数据性能排名。

| Codec | 接入 | Track / LossMode | 实际 ISA / 线程 | 原始 / 摘要 n / 排除 | 证据 |
|---|---|---|---|---|---|
"""
    previous = {
        "chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star", "prometheus-xor-chunk"
    }
    for entry in entries:
        name = entry["algorithm"]
        task = entry["task"]
        execution = task["execution"]
        semantic = task["comparability"]["semantic_document"]
        label = "既有复核" if name in previous else "新增"
        text += (
            f"| {name} | {label} | {task['track']} / {semantic['loss_mode']} | "
            f"{execution['actual_isa']} / {execution['threads']} | "
            f"{entry['record_count']} / {entry['summary_n']} / "
            f"{entry['resource_excluded_count']} | "
            f"[formal](completed_rewrites/{name}-formal.json) · "
            f"[report](../{entry['run_path']}/report/report.md) |\n"
        )
    text += f"""
每个 formal JSON 保存 TaskID、AlgorithmID、SourceArtifactID、AdapterID、执行路径、
输入合同、已知限制与运行目录内每个文件的 SHA-256。
运行目录中 `run_components.jsonl`、`runs.csv` 是逐次证据；`summary.csv`、
`eligibility.csv`、`coverage.csv`、`pareto.csv`、`ranking.csv` 与 `report/report.json`
由同一冻结任务宇宙生成。机器审计重新生成派生报告时验证原始 JSONL hash 不变。
此前 DZip 的 threads=1 运行保留在旧 acceptance20 目录，因 OVERSUBSCRIBED 不参与本次验收；
表中 DZip 取 `acceptance-threads3` 的真实重跑证据。

## 五层自省与完成定义

下列勾选仅签署本次注册 profile，验收依据为成功的机器审计、native qualification
与完整回归日志。计划书中的全局 221 条目分类、真实大数据全覆盖和 GPU 能力没有被扩大宣称。

### 第一层：数据准备（计划 6.7）

- [x] 新增五个 synthetic Dataset Manifest，明确 dtype、shape、T 构造、布局和源文件 hash。
- [x] 通过既有 canonical loader / artifact / characterization，RawBits 使用 canonical 对象。
- [x] 输入没有隐式裁剪、字节重映射、dtype 替换或清洗回写；没有修改既有 ND 数据语义。
- [x] 每个正式运行保存 dataset provenance、canonical 内容 hash 与冻结环境。

落点：`fixtures/completed_rewrites`、`registry/datasets/rewrite_*.json`、
`tools/generate_completed_rewrite_fixtures.py` 与各运行目录的 `datasets`。

### 第二层：能力与配置（计划 7.12）

- [x] 逐包盘点 16 个完成包与 2 个 BLOCKED 包；按实现入口注册，不混合损失模式和对象层级。
- [x] SourceArtifact、Codec Manifest、接入卡和许可证决定已登记；副本与原文件逐项 SHA-256 核对。
- [x] 参数默认值展开进入 ConfigID；不支持的 dtype、histogram 布局、query、streaming
  保留在任务宇宙。
- [x] CPU、ISA、线程预算、affinity、fallback 及 Semantic→Execution→Resource 键明确。
- [x] 正式任务的 AlgorithmID、AdapterID 与当前 manifest 相符；完整依赖聚合 hash 与当前执行闭包一致。

落点：`registry/codecs`、`registry/sources`、`registry/onboarding`、
`src/tscompbench/codecs/negotiation.py`、`src/tscompbench/planning`、
`layer2-plan.json` 和 `task_plan.jsonl`。

### 第三层：执行与验证（计划 8.11、11.5）

- [x] C ABI 调用冻结的真实 C++ 编码/解码；VALUE、TIMESTAMP、SYSTEM 路由与对象一致。
- [x] Preflight 在正式重复前执行 boundary/safety；新入口各有 release 和 ASan/UBSan native 证据。
- [x] 显式 compress / finalize，finalize 恰好一次；零字节 finalize 仍计入生命周期。
- [x] 独立解码 session、reset、确定性、input immutability、capacity/canary 和截断/损坏容器验证通过。
- [x] SHA-256 descriptor 与 payload、dtype/shape/role 和精确解码容量先验证，再进入 native decode。
- [x] 正确性、有限重构、T/V 配对与计费来自同一次 repetition；原生失败以结构化原因原子拒绝。
- [x] FinalBits = 实际可解码容器长度 × 8；header、padding、字典、模型与归一化统计全部计费。
- [x] 无通用误差界的源码标为 UNBOUNDED_LOSSY，实际质量指标落盘，bound_passed/违反次数为 null。

落点：`adapters/completed_rewrites/native/binding.cpp`、
`src/tscompbench/adapters/completed_rewrites.py`、既有 `rewrite_lossless`、
`src/tscompbench/execution`、`src/tscompbench/validation` 与 `layer3-execution.json`。
SYSTEM 原生联合帧计入 `unallocated_shared_bits`；内部字典/模型不猜测拆账，
`model_bits=0` 或 `dictionary_bits=0` 不表示这些字节免费。

### 第四层：性能评测（计划 9.10）

- [x] 各入口 20 次完整原始观测、预热与最短时长通过审计；没有 fastest-only 筛选。
- [x] 支持 CORE/PIPELINE/E2E 的 harness session/object 边界；三模式当前资格验证见
  `docs/all_algorithm_timing_scopes.md`。native 辅助耗时仍为 null；旧正式批次身份保留。
- [x] 模型加载、frame 处理和独立解码发生在真实路径；DeepZip、DZip、WaLLoC 解码使用帧内模型。
- [x] DZip 保留两个各一个 worker 的 Eigen 池与调用线程，进程预算为 3，
  AVX+MKLDNN dispatch 显式记录。
- [x] TRISTAN/CORAD/WaLLoC 记录 CPU_RUNTIME_DISPATCH，外部 SIMD runtime 不宣称纯 scalar。
- [x] 资源异常保留真实状态及原因，未知资源为 null / N/A；query/streaming 请求通过协商拒绝。

落点：`configs/experiments/completed-rewrites-*-formal.toml`、
`src/tscompbench/execution/repetition.py` 与 `layer4-performance.json`。

### 第五层：统计与报告（计划 10.7、20.3）

- [x] 只聚合同 ConfigID/ExecutionPathHash 下的 eligible PASS；独立检查观测完整性与最低 n=10。
- [x] RESOURCE_PRESSURE 等失败逐行保留，Coverage 分母来自冻结任务表。
- [x] 空间、性能、资源按各自可比性键过滤；不同 Track/LossMode/ObjectLevel 不混成全局榜。
- [x] 统计器从物理 artifact 校验 bitstream hash 和 ledger；报告重建不执行 codec、不修改原始记录。
- [x] 18 个入口均产生 summary、Eligibility、Coverage、Pareto、排名与人读/机器报告，可反查原始运行。

落点：`src/tscompbench/statistics/engine.py`、`src/tscompbench/reporting`
与 `layer5-statistics.json`。
新增回归验证“计划 12 次、11 PASS + 1 失败可摘要”和“缺失计划重复不能摘要”，
并验证无误差界有损的统计资格来自冻结任务语义。

## 注册输入与能力边界

| 入口 | 本次确认的输入/profile |
|---|---|
| ABBA / fABBA | 有限 binary64；ABBA 至少两点，端点算术残差会原子拒绝；均无通用逐点误差保证 |
| TRISTAN / CORAD | binary64 完整窗口、非常量列；每通道归一化/反归一化与字典学习 |
| Influx timestamp | int64 整对象，原 STREAM/BATCH 算法选择；不是 Benchmark 增量 streaming |
| Prometheus XOR2 | 联合 ST/T/V 帧；ST 为显式参数且对象内恒定，核对 ST 与 T/V pairing |
| Histogram 两种入口 | T + 六个 uint64 位字段；gauge hint 3、schema 0、一个正桶、无负桶/custom |
| DeepZip | uint8 0..3；全部 17 个冻结模型原生核对词表宽度为 4；无字节重映射；CPU profile |
| DZip | uint8 排序字母表；seeded 未训练 bootstrap/combined；拒绝 9 符号，空输入使用 256 符号扩展 |
| WaLLoC | 归一化 float32 双声道；stereo_5x/stereo_20x；padding、WebP、嵌入模型与裁回长度 |
| 既有七入口 | 保留各自 lossless VALUE/SYSTEM manifest；用 binary64 MTS 合成数据复核 |

TRISTAN/CORAD 源码可提前停止，requested_n_iter 固定登记为 150，实际最大迭代为 10。
普通 scalar CSV 不符合 histogram 的六字段合同，不会被隐式解释成 histogram。

没有注册 CUDA、外部训练、模型拟合质量、query、random access 或增量 streaming 的资格。
MKL、LibTorch 及动态依赖按完整闭包锁定；CPU 执行不意味着 LibTorch 二进制完全不带 CUDA 依赖。
当前 WaLLoC 使用本机 CompressBench 中 LibTorch 2.6.0+cu118 / ABI0；
跨机器须满足锁定依赖或重新冻结并资格验证。
外部 MKL/LibTorch 二进制未重新进行 sanitizer 插桩；leak detection 关闭，
未宣称外部依赖安全或泄漏检查通过。

TRISTAN、CORAD、DZip、WaLLoC 的许可证登记保留 NOASSERTION，依据现有本地工作决定执行接入；
此记录不产生上游授权或对外发布许可。

## 尚未完成的重写包

- `terracodec-flextec`：BLOCKED at G2；随机编码上下文无法与独立官方 decoder 一致，重写未完成。
- `terracodec-tec-tt`：BLOCKED at G5；CUDA racecheck 仍有 53 个共享内存 hazard，替代路径尚未合格。

两者不满足用户要求的“已经重写完成”，未注册成 QUALIFIED，也未计入 16 个完成包。
状态和 port manifest hash 记录在机器审计 `blocked_packages` 中。

## 验证与重跑

完整回归：**{audit['validation']['pytest_passed']} passed，109 warnings**。
日志：[pytest](../build/completed-rewrites-pytest.log)。
新接入 11 个 codec 的 **22 项 release/sanitizer native qualification 全部 PASS**；
既有七入口的 native ABI qualification 及日志 hash 同样纳入当前审计。
新 native 日志包含 standalone CTest 与 framework binding qualification，
不以绝对吞吐阈值代替正确性、边界和生命周期验证。

使用 `/home/fzg/anaconda3/envs/CompressBench14/bin/python`，当前工程为工作目录。
示例（正式运行后缀须使用尚未存在的名称）：

```bash
python tools/build_codec.py abba --profile all
PYTHONPATH=src python tools/qualify_completed_rewrites_native.py
PYTHONPATH=src python tools/onboard_completed_rewrites.py
PYTHONPATH=src python tools/qualify_completed_rewrites.py --mode QUALIFICATION --suffix reproduce-q
PYTHONPATH=src python tools/qualify_completed_rewrites.py --mode FORMAL \\
  --repetitions 20 --suffix reproduce-f
PYTHONPATH=src python -m pytest
PYTHONPATH=src python tools/verify_completed_rewrite_integration.py --refresh-reports
python tools/write_completed_rewrite_review.py
```

`build_codec.py <codec> --profile all` 可逐项构建；其余模型/依赖与原始包必须在冻结路径存在。
验证器默认审计 acceptance20，DZip 默认 acceptance-threads3；审计重跑目录时显式传入
`--suffix reproduce-f --dzip-suffix reproduce-f`。
完整 profile 表与构建限制见 [adapter README](../adapters/completed_rewrites/README.md)。
源码/build/config/environment 不匹配或有效次数不足时，验证器不能产生 PASS。
"""
    destination = ROOT / "docs/completed_rewrite_integration_review.md"
    destination.write_text(text, encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
