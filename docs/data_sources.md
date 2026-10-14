# 三源 CPU study 的输入冻结与获取

本次固定三个本地 CSV 的**完整文件 SHA-256、上游获取路线、解析规则与开发／评价窗口**。[catalog.json](../registry/datasets/catalog.json)是机器记录，[fetch_datasets.py](../benchmark/tools/fetch_datasets.py)负责获取／验证和必需 acquisition manifest。三个远程单文件均已取得，并与本地文件逐字节哈希相同；本仓库不捆绑这些原始 CSV。

这三个来源是当前 CPU study 的固定输入集合，分别使用 transformer oil temperature、weather temperature 和 national illness count；它们不能代表各自整个领域，也不能因同源窗口、列、round 或 length 增多而获得额外独立 source 数。

## 精确文件版本

| Source | 文件／行数／字节 | 完整 SHA-256 |
|---|---|---|
| etth1 | `ETTh1.csv`；17420行；2589657 bytes | `f18de3ad269cef59bb07b5438d79bb3042d3be49bdeecf01c1cd6d29695ee066` |
| weather | `weather.csv`；52696行；7235425 bytes | `34ee981d07313e51da2a50bb600072c8ae4a69cb4b0651f4cb93a069d7a2ba63` |
| national_illness | `national_illness.csv`；966行；67620 bytes | `93601f64d2566dc796ca4305adad8b8560c2db1a1ff04543c3bd813a7263570a` |

本地原始取得时间未知，不能由本轮访问时间补写；本轮来源核查日期为2026-10-13。当前本地目录为 `/home/fzg/PycharmProjects/材料/TSBench_Corpus`。旧 catalog 的 bytes／SHA-256 与现文件全部一致，旧 catalog 自身 hash 也保存在新记录中。旧记录只写本地 URI、`UNSPECIFIED` 来源／许可，不能当成本轮上游核实证据。

ETTh1 的版本绑定为原作者数据仓库 [zhouhaoyi/ETDataset](https://github.com/zhouhaoyi/ETDataset)，提交 `1d16c8f4f943005d613b5bc962e9eeb06058cf07`、路径 `ETT-small/ETTh1.csv`。[固定 CSV](https://raw.githubusercontent.com/zhouhaoyi/ETDataset/1d16c8f4f943005d613b5bc962e9eeb06058cf07/ETT-small/ETTh1.csv) 的2589657 bytes与本地相同。[同提交 README](https://raw.githubusercontent.com/zhouhaoyi/ETDataset/1d16c8f4f943005d613b5bc962e9eeb06058cf07/README.md)说明作者与北京国网富达共同采集并捐赠 transformer 数据，OT 为 oil temperature；引用 Zhou et al., *Informer*, AAAI 2021。

weather／national_illness 的精确预处理 CSV 来自 [Autoformer 官方 README](https://raw.githubusercontent.com/thuml/Autoformer/51c7d416ae120b805fd5beef2f4ccf7de496a6ff/README.md)指向的 [Drive 分发目录](https://drive.google.com/drive/folders/1ZOYpTUa82_jCcxIdTmyr0LXQfvaM9vIy)。README 的代码提交固定为 `51c7d416ae120b805fd5beef2f4ccf7de496a6ff`，它固定的是分发说明；Drive file id 可变，**CSV hash 才是这里的数据版本**。引用 Wu et al., *Autoformer*, NeurIPS 2021。另核对 [LTSF-Linear 固定 README](https://raw.githubusercontent.com/cure-lab/LTSF-Linear/0c113668a3b88c4c4ee586b8c5ec3e539c4de5a6/README.md)也指向相同分发目录。

| 精确预处理文件 | 官方研究分发子目录 | 单文件 id |
|---|---|---|
| weather.csv | [weather](https://drive.google.com/drive/folders/1Xz84ci5YKWL6O2I-58ZsVe42lYIfqui1) | `1Tc7GeVN7DLEl-RAs-JVwG9yFMf--S8dy` |
| national_illness.csv | [illness](https://drive.google.com/drive/folders/1DasX30lzEwcVXYaNeyMlQ0PSmCQSow5h) | `1n4kDxT38rQEGmczIaYaaUWqRPWs-rtcH` |

目录列表显示的文件大小和实际下载 hash 均与上表一致。脚本使用 catalog 保存的 HTTPS 单文件下载地址，避免为了两个 CSV 下载整个约54MB语料归档。Drive 的 HTML、登录或 quota 页面不会因为 HTTP 200 被接受为数据，仍须满足完整文件长度、SHA-256和解析身份。

## 来源与许可的核实范围

| 文件 | 已核实的许可证据 | 未建立的主张／发布方式 |
|---|---|---|
| ETTh1 | 原作者**专用数据仓库**同提交 [LICENSE](https://raw.githubusercontent.com/zhouhaoyi/ETDataset/1d16c8f4f943005d613b5bc962e9eeb06058cf07/LICENSE)为 CC-BY-ND-4.0，README 说明其自己采集／捐赠数据 | 没有从第三方代码 license 推定 data license；本仓库只给原始文件链接、hash和引用，不发布修改后的数据集 |
| weather | MPI 官网 [Data Download](https://www.bgc-jena.mpg.de/wetter/weather_data.html)明确 `Terms of Use (as per Creative Commons CC-BY-4.0)`；数值和时间戳与其2020原始数据完全匹配 | 研究者预处理 CSV 包装的额外许可未找到；原始数据 CC-BY 证据与包装条款分别记录，不将 Autoformer 代码许可套用到数据。预处理 CSV 不捆绑再分发 |
| national_illness | 精确 CSV 的研究作者分发和 hash 已核实 | 原始 CDC 提取版本、转换脚本、该精确预处理文件的数据许可均为 unknown；不借通用“政府数据公有领域”假设补证，也不使用 Autoformer 代码许可。只提供取得路线和 hash，不再分发 CSV |

天气的 primary source 还做了直接内容核对：读取 MPI 官方 [mpi_roof_2020a.zip](https://www.bgc-jena.mpg.de/wetter/data/mpi_roof_2020a.zip)（SHA-256 `6a0be0552a2a26a04c3b41a5281d4a55ae251d4c65ce630971a8662f43b31f9f`）与 [mpi_roof_2020b.zip](https://www.bgc-jena.mpg.de/wetter/data/mpi_roof_2020b.zip)（`c37eca910ee2803b17b8c587f3194bc7625abf994576c50f32538dd7cb65ac77`）。各自唯一 CSV 按 a→b 拼接、以 Latin-1 读取、将 `dd.mm.yyyy HH:MM:SS` 日期解析后与本地行比较；21列数值经 `float`→little-endian float64 后逐位比较。**52696／52696行的所有21列数值和时间戳一致，0 mismatch**。源头标题 `Date Time`→`date`、`CO2 (ppm)`→`OT`、数个单位字符被替换以及 CSV 数字格式变化说明两个文件的原始字节不同；不能声称预处理 CSV 本身与官方 zip 内 CSV 字节相同。这里保留本地 raw header，不自动“修复”它。

本轮 [CDC ILINet 页面](https://www.cdc.gov/fluview/overview/ilinet.html)返回 HTTP403；GitHub REST API 返回403 rate limit。随后使用只读 `git ls-remote` 固定上述三仓库 main 提交并读取 pinned raw 文件。catalog 的 `evidence.public_access_probes`、`repository_ref_probes` 保存请求地址、时间、状态、响应长度／hash或错误理由。失败没有被改写成成功，当前访问成功也不保证未来 URL 永久可用。

## 冻结解析和 study 窗口

规则与 [study_design.json](../benchmark/experiments/cpu-study/study_design.json)对齐。UTF-8严格解码、标准逗号 CSV、完整列数检查；所选数值转 `<f8`，有限性检查，不做归一化、插补、重排或重采样。所选时间列格式为 `%Y-%m-%d %H:%M:%S`，按 naive 字符串相对 `1970-01-01` 的整数算术转 `<i8` nanoseconds。这是 benchmark 的时间表示约定，不声称原观测的实际时区已经核实。weather 全源有1个相邻重复 timestamp，保留该重复，未去重。

| Source | Values 列 | Development，stop-exclusive | Evaluation，stop-exclusive | 评价对象 |
|---|---|---|---|---|
| etth1 | OT | `[0,1024)` | `[1024,1536)` | `[1024,1152)`128点；`[1024,1536)`512点 |
| weather | T (degC) | `[0,1024)` | `[1024,1536)` | `[1024,1152)`128点；`[1024,1536)`512点 |
| national_illness | ILITOTAL | `[0,256)` | `[256,768)` | `[256,384)`128点；`[256,768)`512点 |

本次声明的开发与评价分区不重叠。开发区预留但当前固定网格未用它挑方法／参数；每个来源的128点是512点前缀，两个长度**相关**。national_illness 只有966行，不制造1024点对象、循环复制或padding。历史 pilot 均读取过 `[0,512)`：ETT／weather 的该区位于新开发区；**ILI 的 `[256,512)` 与新评价区重叠**，因而 ILI 当前评价不是从未观察的 holdout。新run是独立测量身份，数据重复使用仍须披露，不能因采用固定网格而称该部分为全新测试数据。source 是当前可用的最高重采样层；3 source 的分析只说明这些选定来源，不能取得广泛领域泛化。

catalog 冻结全源、开发区、评价区以及每个 nested 对象的 V／T little-endian C-order bytes hash、shape与长度。这些是**组件字节 hash，不是 `raw_object_id`**；后者还包含 tsbench object schema。六个评价对象的 V／T bytes 已与实际 core CSV loader 交叉核对，全部相同。重新获取不会自动改变实验配置、dtype 或 split，也不会重新运行 codec。

## 获取、验证与失败证据

获取脚本仅用 Python 标准库，`--manifest` 必需且不得覆盖已有 manifest。它保存开始／完成时间、脚本／catalog／freeze 身份、请求／最终 URL、可取得的 HTTP 信息、实际字节／hash、解析与窗口身份、逐数据源成功或失败。每个数据源开始和结束都更新 manifest；普通异常／中断也保留终态。网络失败、文件缺失、hash漂移、CSV／窗口违例使命令非零退出，不能生成一个貌似可用的新版本。

```bash
# 已有本地文件：只读验证，不改变 CSV 或运行 codec。
python benchmark/tools/fetch_datasets.py verify \
  --directory /home/fzg/PycharmProjects/材料/TSBench_Corpus \
  --manifest /tmp/tsbench-data-verify-01.json

# 可在另一环境新目录获取同一精确文件；manifest 使用新名称。
python benchmark/tools/fetch_datasets.py fetch \
  --directory /tmp/tsbench-corpus-reproduction \
  --manifest /tmp/tsbench-data-fetch-01.json

# 单源验证，也适用于从官方 Drive 页面手工下载后核对。
python benchmark/tools/fetch_datasets.py verify \
  --dataset national_illness --directory /path/to/downloaded-csvs \
  --manifest /tmp/tsbench-ili-verify-01.json
```

`fetch` 对已存在文件执行严格验证，绝不静默覆盖。新下载的接收上限为冻结文件长度+1 byte；超长立即拒绝。完全通过 hash、header、row count、typed parse和窗口检查后，才以同目录临时文件原子安装；错误／中断的临时文件删除，下载字节数／hash和错误理由仍留在 manifest。`--url source_id=https://...` 可替换故障获取路线，**不能替换 frozen hash**。需要新数据版本时，显式更新 catalog、重新冻结输入和实验身份。

本轮实际验证包括：三个现有文件全部通过；从三条上游 URL 新下载到 `/tmp` 后全部通过；六个评价窗口的核心 loader 交叉通过。另在明确标记的失败检查中，缺失文件、同长度单字节污染和 stale catalog freeze id 均被拒绝且保存真实失败 manifest。将ETTh1地址故意用于67620-byte illness请求时，脚本接收67621 bytes即停止，未安装错误文件，并保存实际已接收字节的hash；这些是获取器验证，不计为 benchmark codec failure。catalog 的 `evidence.acquisition_checks` 嵌入对应 manifest 内容与原始 manifest SHA-256，即使临时下载目录被清理，成功／失败证据仍可审阅。各manifest保留其执行时脚本／catalog／freeze身份，后续来源说明修正不回写旧身份。

该来源冻结完成了当前三源 study 的可获取性和身份约束。national_illness primary extraction／数据许可和天气预处理包装条款仍是明确缺口。[另一软件环境复跑](alternate_environment_results/README.md)已在同一主机的 Python3.14／NumPy2.5 中完成36个成员独立构建和924/924正式trial；这是软件环境复验，不能称第二台物理机器。现有CPU结果按已记录范围解释，不扩展成所有数据的许可或跨机器可移植性主张。
