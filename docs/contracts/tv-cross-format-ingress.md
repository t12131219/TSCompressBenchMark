# M3 开发合同：同一 T+V 对象的 CSV、NPY、TXT 入口

本合同落实设计 §6.1–6.3 的**定宽、不可空列、位无损**入口和跨格式诊断。不是正式计时、通用文件端到端榜或阶段收据。它不修改 Unique 版本、原生操作组或有效服务分母。

## 冻结输入和解析

[版本 2 套件](../../configs/suites/dev_tv_cross_format_v2/suite.json)引用 6 个[来源清单](../../datasets/fixtures/m3-ingress/)；每个清单冻结有序文件路径、角色、SHA-256、文件长度、形状、列名、类型、时间单位、epoch、时区语义、行序和解析参数。[本地来源注册表](../../catalog/source-loaders.json)与原生 codec manifest 分开，数据清单只能参照注册的 loader，不能提供可执行路径。loader 实现 `probe_source / resolve_schema / read_batches / close`，在当前开发执行器中用已校验的文件字节提供最多 256 行一批的独占、不可变小端列；每个来源最多 8,192 行、5 个 V 列、总输入 8 MiB。这个初版先读取有界的来源字节，并不声称在线接收或 mmap。

| 格式 | 接受的合同 |
|---|---|
| CSV | 显式 UTF-8、分隔符、是否有表头、双引号及成对转义、小数点、缺失 token 策略。仅一物理行一条记录；错误行拒绝。 |
| TXT | 显式 `delimited` 或 ASCII `fixed_width`、是否有表头。拒绝注释、空行、非法编码；定宽模式明确去除字段两侧 ASCII 空格。 |
| NPY | 有序的独立 i64 `[rows]` 时间数组和 f64 `[rows, V]` 值数组；明确轴、大小端和 C/F order。仅读 NPY v1/v2，`allow_pickle=false`，不支持 mmap、object、structured、complex；拒绝多余、缺失或截断数据。 |

时间戳只从十进制整数或 NPY i64 读取；不经过浮点。输入行序、重复和逆序坐标保持原样；进 codec 前向毫秒做精确有界换算，恢复后回到原单位核对。交通时间是原语料的民用时间坐标，不解释为 UTC。CSV/TXT 的缺失 token `""`、`NA` 都拒绝；普通 `NaN` 不臆造 payload。十进制 V 按 binary64 舍入并保留负零；非有限值、或要求指定 payload 的值用显式 `bits:<16 hex digits>`。拒绝十进制溢出和非零下溢为零。当前不处理 nullable/validity、字符串字段、日期文本解析和有损量化。

## 三层身份、权重和测量

1. **`source_file_hash`**：单文件为原文件 SHA-256；多文件为有序 `(role, bytes, sha256)` 列表身份。路径保留在文件来源清单，不掺入字节身份。
2. **`ingestion_id`**：绑定注册的解析器版本、实现与公共引擎哈希、参数 schema、解析选项和有序对象声明。
3. **`canonical_dataset_hash`**：按域标识、对象声明（包括形状、原时间语义和行序）及有序列字节摘要做长度前缀哈希；不包含路径、格式、解析器、来源文件大小。此合同只准定宽不可空列，逻辑字节为 `8 × rows × (1 + V 列数)`。`source_group_id` 来自同一规范化身份；三种格式各实跑一遍，但逻辑对象在报告只占一个权重。

**计时**：`ingress-setup.json` 单独记录每个来源的校验、解析和精确单位转换墙钟，绑定 `ingestion_id`、`source_file_hash`，且随运行封存。此后沿用原有 T+V worker：规范化列文件提前落盘，进程计时仍包含 worker 启动、打开规范化列文件、编解码、布局、容器及输出。没有声明预触页、隔离硬件或 `source_file` 全流程计时；恢复目标为 typed object，不是 CSV 原文。比较不将格式或源文件字节混入逻辑分母和比较身份。

## 运行与验收范围

[生成器](../../tools/generate_m3_ingress_fixtures.py)以 NumPy 独立写 NPY（运行时 loader 不需要 NumPy）。`--check` 从已有交通 held-out 的 5 列/515 行和已有同形特殊位型 fixture 重新生成并逐字节核对，不访问 Unique 邻接目录，不重导语料。实测每组都是 512+3 行块；固定同一 Gorilla-T，使用已有 ALP f64 与 Sprintz-FIRE 20-u16 两条完整方法。每条方法分别对三种格式实际编解码，核验三份产物逐字节一致、同一格式的两方法还原相同原始位型、固定 T 帧一致。不能仅靠解析器的哈希判断通过。

使用 `tsbench` 前缀复跑（输出目录必须为空）：

```bash
bash tools/probe_offline_tv_composition.sh /home/fzg/anaconda3/envs/tsbench \
  results/m3-tv-cross-format-repro --ingress
```

脚本在网络命名空间内迁移路径后从空目录构建。报告复算不挂载来源数据、原构建、原插件和源清单。逐产物审计只挂载 bundle、对应解码依赖及必要的命令参数，重新计算恢复后的规范化身份。原 `tv-composition` / `tv-limb-comparison` 仍使用 v1 套件、计划和快照，报告可逐字节复算。

尚不覆盖 `source_file` 端到端比较、可空/变长值、数值量化及异常旁流、单列文件/字符串时间和通用大语料调度；既有 T+V 验证不能替代 M3 要求的独立 T-only、V-only 和全部首批原生机制验证。ALP AVX512 构建和条件路线保留；本套件不把它标为已实跑。

实测记录：[主报告](../../results/m3-tv-cross-format-20261119-r2/report.json)、[独立恢复](../../results/m3-tv-cross-format-20261119-r2/restore.json)、[控制](../../results/m3-tv-cross-format-20261119-r2/controls.json)。同一 run 完成 12/12，报告字节复算一致，152 项 Python 测试和 5 项 CTest 通过；不与早期开发 run 拼接。
