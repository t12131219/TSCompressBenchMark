# 算法接入验证输入库

本目录统一保存 1,409 个无扩展名的 `tscb-canonical-v1` 数据文件。用于数据类型、形状、源域、边界行为和编解码恢复验证；合成样本不能代替真实语料的性能排名或训练评价。

```text
Dataset_Verify/
├── README.md
├── index.json                 唯一索引：路径、大小、哈希、样本参数与来源
├── verification.json          本次目录整理后的完整性校验记录
└── data/
    ├── with_timestamp_univariate/       332 个
    ├── with_timestamp_multivariate/     376 个
    ├── without_timestamp_univariate/    302 个
    ├── without_timestamp_multivariate/  346 个
    ├── boundary_n2/                      40 个两行边界样本
    └── special/                          13 个源域／特殊形状样本
```

前四类按 `<数值类型>/<测试组>/<样本名>` 组织。类型包含 int8/16/32/64、uint8/16/32/64、float32/64；多变量另有 mixed10，保留不同列的原生类型。

| 测试组 | 数量 | 用途 |
|---|---:|---|
| main | 640 | 4KiB／64KiB／1MiB／16MiB 载荷档位，constant／slow／periodic／random |
| length_extrema | 560 | 0、1、7、8、9、31、32、33、127、128、129、1023、1024、1025 行与数值极值 |
| ieee_special | 8 | Infinity、NaN payload、正负零等浮点位模式 |
| timestamp_cases | 60 | 不规则间隔、重复、乱序时间戳，保留原顺序 |
| channel_counts | 80 | 2／4／16／32 通道 |
| mixed_dtypes | 8 | 每份 10 列，各用一种原生数值类型 |
| boundary_n2 | 40 | 10 种类型 × 1／8 通道 × 有／无时间戳，均为两行 |
| source_domain / native_nd | 12 / 1 | 算法适用域样本及原生多维数组 |

例如 `4KiB__constant__regular__n256__c1` 表示约 4KiB 原始载荷、常量数值、规则时间戳、256 行、1 个通道。档位计算数值与时间戳的原始载荷，按完整行取整；实际容器文件还包含元信息。

容器包含固定文件头、JSON 描述和具名数组 buffer，不能将整个文件当裸数组读取。常规样本的时间戳为 int64、单位 ms；special 样本保留自己的时间单位、类型和形状。同类型的一维 SoA 列可无损组装为矩阵，异构列保留独立组件，不统一转为浮点数；无时间戳时不合成时间轴。

## 当前入口

读取与全算法配置验证使用 [run_dataset_verify.py](../benchmark/tools/run_dataset_verify.py)，说明见 [运行文档](../docs/dataset_verify_run.md)。其 `load_canonical(path, expected_hash)` 读取并检查文件／buffer 哈希，保留 dtype、shape 和只读属性；`discover_datasets()` 读取本目录的唯一索引。

```bash
cd /home/fzg/PycharmProjects/TSDataCompressBenchMark
/home/fzg/anaconda3/envs/CompressBench14/bin/python \
  benchmark/tools/run_dataset_verify.py \
  --output runs/dataset-verify-clean-20261015 --plan-only
```

删除 `--plan-only` 才执行算法回环；结果保存在所选 `runs/` 目录。已有输出不得覆盖，新实验使用新的目录。`verification.json` 只证明本次保留文件的完整性与去重检查通过，不表示所有算法或所有质量任务通过。

## 2026-10-15 整理规则

- 将原 `v3/data/`、`v3/boundary_n2/`、`v3/special/` 合入 `data/`，统一索引使用相对本目录的 `data/...` 路径。
- 634 对单变量样本保留逻辑 shape 为 `[N]` 的新版，移除 `[N,1]` 的旧容器变体；逐对确认具名 buffer、类型、物理描述、原始字节账单与 framed 数组载荷一致。基础测试组合和全部补充样本仍保留，共 1,409 个文件。
- `v3/registry/` 的必要来源、许可、split 和预期信息并入索引，移除逐文件注册表和旧版算法 fixture 映射。索引中 `content_sha256` 来自保留容器的声明；旧注册索引的语义哈希单列 `legacy_semantic_content_sha256`，不混同两种历史身份口径。
- 移除依赖已删除 `tscompbench` 的 generate.py、fixtures.py、verify.py 和 Python 缓存，使用当前框架入口。生成 seed、参数、版本与生成器哈希保留在索引中。
- 用本次结构校验替换旧 verification.json。`previous_paths`、`supersedes` 和 consolidation 保存路径／身份变更；原控制文件与被替换容器的头部恢复材料暂存位置也在索引中登记。

历史 run 的 manifest／observations 没有改写。旧 run 引用的 v3 路径和旧容器身份已迁移，不能直接对整理后的输入续跑旧矩阵；新运行须使用当前索引和新输出目录。
