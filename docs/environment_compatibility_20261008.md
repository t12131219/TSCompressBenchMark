# Conda 环境运行与降级可行性检查

检查日期：2026-10-08（Asia/Shanghai）。检查对象为当前源码、注册表、数据和现有原生工件。

**结论：`CompressBench14` 可以运行当前框架并完成代表性的正式实验与报告，但当前全量回归尚未全绿；`CompressBench` 不能直接运行完整项目，当前版本不能直接降级到该环境。**

## 环境与实际结果

| 检查 | CompressBench14 | CompressBench |
| --- | --- | --- |
| Python | 3.14.5 | 3.11.16 |
| NumPy | 2.5.3 | 1.26.4 |
| 项目版本约束 | 满足 Python >=3.14、NumPy >=2.5,<3 | 两项均不满足 |
| 298 个 Python 文件的语法解析 | 全部通过：控制面 100、tools 100、tests 98 | 4 个文件无法解析 |
| 完整 CLI 导入 / `--help` | 通过 | SyntaxError，CLI 无法启动 |
| Codec 注册表校验 | 67 个 Codec、118 个 SourceArtifact、4 个别名，PASS | 完整 CLI 不可用，未继续执行 |
| 数据集全表校验 | 22 个数据集，PASS | 完整 CLI 不可用，未继续执行 |
| 全量 pytest | **4506 passed、2 failed、0 errors、0 skipped**，约 380.8 秒 | **63 个收集错误**，退出码 2；测试执行未开始 |
| 单独的数据/身份模块测试 | 包含在全量测试中 | 8 passed；仅证明这些模块可用 |
| LZ4 资格实验与报告 | 1 个任务、1 条 PASS 记录；QUALIFICATION 不产生正式统计，符合预期 | 完整 CLI 不可用，未执行 |
| LZ4 正式实验与报告 | 20 次固定重复全部 PASS，20 条有效记录、1 行汇总，报告生成成功 | 完整 CLI 不可用，未执行 |

正式实验基于 `configs/experiments/lz4-frame-formal-smoke.toml`，将固定重复次数从 10 改为 20，副本保存在检查目录。采用 `national_illness`、VALUE、PIPELINE、CPU 单线程；预热至少 3 次 / 0.5 秒，编码和解码各方向最短时长均为 1 秒。全部 20 次分别通过空间质量、性能与资源资格过滤。最小累计编码时长为 3,633,494,215 ns，最小累计解码时长为 1,000,014,049 ns。

本次验证了数据准备、任务规划、Preflight、预热、正式重复、正确性/资源检查、原始证据与第五层报告的实际闭环。该单一正式配置不代表所有算法、数据域和配置已经完成正式资格验收。全量测试还消费已有专项审计资产，其成功不等于从干净克隆自动完成全部依赖安装。

## CompressBench14 中的两个现有回归失败

1. `tests/contracts/test_dataset_manifests.py:12` 仍断言数据集数量为 20；当前注册表已增加到 22。第 16 行的唯一 DatasetID 数量断言也仍为 20。数据文件核验与加载通过，需同步测试中预期的注册覆盖。
2. `tests/unit/test_native_integration_plan.py:132` 检查工作清单候选身份时失败。`registry/native_integration_plan.json` 中有 6 个旧 AlgorithmID 与当前 Codec Manifest 不一致，涉及 `simdcomp-u32`、`delta-simdcomp-u32`、`for-simdcomp-u32`、`simple9-u28`、`simple9hacked-u28`、`simple16-u28`。其 SourceArtifactID 比较没有发现漂移。需要根据当前身份和已审计证据同步工作清单，不能删除一致性检查或自动扩大资格声明。

全量测试另有 655 条 warning，主要是 Python 3.14 对多线程进程 `fork()` 的弃用提示；本轮未出现由此导致的测试错误。源码和注册表没有为使检查通过而改动。

`CompressBench14` 尚未安装 requirements 中的 PyYAML；它用于 `tools/verify_requested_lossless_delivery.py` 与 `tools/finalize_requested_lossless_rewrites.py`，不阻止本次主框架测试和 LZ4 实验，但这两个工具尚不具备完整依赖。ruff、pytest、setuptools 的已安装版本与 requirements 匹配。

## 为什么不能直接降级到 CompressBench

源码使用 Python 3.14 支持的无括号多异常捕获语法，例如：

```python
except OSError, ValueError, IndexError:
```

Python 3.11 会将其视为 SyntaxError。静态检查发现 4 个受影响文件、共 8 处：

- `src/tscompbench/execution/isolation.py:30`
- `src/tscompbench/measurement/resources.py:18`，该文件另有 4 处同类语法
- `src/tscompbench/statistics/engine.py:92`
- `tools/build_native_integration_plan.py:92`

CLI 导入最先在 `isolation.py:30` 中止；全量 pytest 因这些导入链在收集阶段失败。数据相关的 8 个单独测试虽通过，也无法证明整个项目兼容。

包元数据要求 Python >=3.14；固定依赖 NumPy 2.5.3 自身的 `Requires-Python` 为 >=3.12。因此只降低 `pyproject.toml` 的 Python 声明，或只给异常元组加括号，都不能使现有 requirements 在 Python 3.11 上成立。

若要支持 Python 3.11 / NumPy 1.26，需要做单独的兼容改造：调整语法和版本合同，验证 NumPy API、数据表示及位级恢复等行为，完成旧环境全量回归和真实运行，再刷新受源码/依赖身份影响的 SDK 与原生运行证据。本次没有执行该改造，也没有形成降级资格声明。建议当前控制面继续使用 CompressBench14；CompressBench 可保留用于其既有 Python 3.11 / LibTorch runtime 用途。

## 复现与证据

从仓库根目录执行：

```bash
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench --project-root . codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench --project-root . datasets verify
PYTHONPATH=src conda run -n CompressBench14 python -m pytest -q
PYTHONPATH=src conda run -n CompressBench python -m tscompbench --project-root . --help
PYTHONPATH=src conda run -n CompressBench python -m pytest -q
PYTHONPATH=src conda run -n CompressBench python -m pytest -q   tests/unit/test_ids.py tests/unit/test_canonical.py   tests/unit/test_characterize.py tests/unit/test_loaders.py
```

详细证据位于 `build/environment-check-20261008-150124/`，该生成目录通常不随 Git 分发：

- [机器可读汇总](../build/environment-check-20261008-150124/summary.json)
- [CompressBench14 全量日志](../build/environment-check-20261008-150124/pytest-compressbench14.log)与 [JUnit](../build/environment-check-20261008-150124/pytest-compressbench14.xml)
- [CompressBench 全量日志](../build/environment-check-20261008-150124/pytest-compressbench.log)
- [环境与语法探针](../build/environment-check-20261008-150124/probe-compressbench.json)
- [工作清单身份差异](../build/environment-check-20261008-150124/worklist-mismatches.json)
- [运行命令与退出码](../build/environment-check-20261008-150124/runtime-commands.json)
- [正式实验配置](../build/environment-check-20261008-150124/lz4-formal-20.toml)
- [LZ4 正式实验报告](../build/environment-check-20261008-150124/runs/lz4-formal-20/report/report.html)

运行命令文件保存了实际配置、输出目录、RunSetID、线程环境与退出码。重跑需使用新的 RunSetID；全部失败证据保留，不覆盖、不转为 PASS。
