# 补充语料来源与许可核查（2026-10-13）

四个本地 PeMS NPZ 已建立作者固定发布身份：本地 Git blob SHA-1 与字节数均匹配 `guoshnBJTU/ASTGNN` 的冻结文件树。本地 electricity、traffic、exchange_rate CSV 已重新核对 SHA-256、header 和首末日期，并找到作者公开分发文件 ID／长度；本轮没有下载它们的远程数据正文，因此不声称完整远程 SHA-256 相同。机器记录见 [additional_data_sources.json](additional_data_sources.json)。本次只做来源／许可及文件元数据研究，没有 build、codec、资格或正式计时。

原始本地获取日期继续为 unknown，legacy catalog 的 `retrieved_at=UNSPECIFIED` 不由本轮网页访问日期补填。原始文件及现有 catalog 均未修改；只读检查结果可以为后续新配置提供 provenance，不能赋予历史 run 新身份。

## 本地文件身份与表示

文件均位于 `/home/fzg/PycharmProjects/材料/TSBench_Corpus`。以下 SHA-256 在本轮实际流式重算，7/7 与 `catalog_legacy/*.json` 相同。CSV 行数仅引用已绑定相同文件 hash 的 legacy 记录，本次未重做全文件 CSV 解析；header 及首两行／末行单独读取。NPZ 仅检查 ZIP 目录和内嵌 NPY header，没有把全数组展开来分析数值。

| 文件 | 字节数 | SHA-256 | 现有表示 |
|---|---:|---|---|
| electricity.csv | 95581762 | `7e45845d54c5219bad0ae6bc1b5316cf8ff9cead5d33fa998a5a51c2e4a497ad` | 26304行（legacy）；`date,0,…,319,OT`，321数值列 |
| traffic.csv | 136478119 | `cb06463d56fa17d87f47027cd9389ceae82a69eddee51cdb61480e120dab0b16` | 17544行（legacy）；`date,0,…,860,OT`，862数值列 |
| exchange_rate.csv | 637800 | `48b4d9d3d508f5104162e85b9a6042e3557fde11aa9f2944eba8c0d0efc89842` | 7588行（legacy）；`date,0,…,6,OT`，8数值列 |
| PEMS03.npz | 15800415 | `34859517425eded66a0014db63de54b95d0428c38890741a1710ed4d3b043de8` | `data.npy`，`<f8`，C-order，`(26208,358,1)` |
| pems04.npz | 32956284 | `95a3c9b720fffdb85f0330d09bfab41b0b3cad0ca86c0d7d5f3accacb4ac999a` | `data.npy`，`<f8`，C-order，`(16992,307,3)` |
| PEMS07.npz | 43705518 | `a07887e610aa986276209bc9384d14ed7858fdcad1ded67f53dca19eb828600b` | `data.npy`，`<f8`，C-order，`(28224,883,1)` |
| pems08.npz | 18525419 | `e1d03ce74e9fb79149e6e7c37c680214822c4a285baa2f42278cacabcd25c075` | `data.npy`，`<f8`，C-order，`(17856,170,3)` |

NPZ 均只有 `data.npy`，没有 T／mask 数组。本地 header 支持 dtype／shape／order，但不能单凭 filename 推定特征单位、传感器映射、缺失语义或真实日期。CSV 的 `OT` 是现有最后通道名；它在这些文件中不能自动解释成 ETT 的 oil temperature。

| CSV | 首两行日期／末行日期 | 明确解析格式与限制 |
|---|---|---|
| electricity | `2016-07-01 02:00:00`；`2016-07-01 03:00:00`／`2019-07-02 01:00:00` | `%Y-%m-%d %H:%M:%S`；可显式按 datetime64/ns 算术表示，源 timezone 与真实采集日期对应未知 |
| traffic | `2016-07-01 02:00:00`；`2016-07-01 03:00:00`／`2018-07-02 01:00:00` | 同上；不能把 CSV 日期直接当作作者声称的 2015–2016 原始测量时间 |
| exchange_rate | `1990/1/1 0:00`；`1990/1/2 0:00`／`2010/10/10 0:00` | `%Y/%m/%d %H:%M`；当前 loader 仅有 int／datetime64 parser，先做 V-only；需要 slash-date 时另行显式实现转换，不静默猜测 |

这些日期端点与作者 README 的数据年份存在差异。全部三份 CSV 的 timestamp 构造脚本、真实观察日期／timezone、实体／货币列映射和精确 values 单位仍未核实；先保留既有值与日期标签，不纠正、不重采样，也不把它们称为原始采集时间。

## CSV 作者分发与 primary 来源

Autoformer 的 [固定 README](https://raw.githubusercontent.com/thuml/Autoformer/51c7d416ae120b805fd5beef2f4ccf7de496a6ff/README.md)（commit `51c7d416ae120b805fd5beef2f4ccf7de496a6ff`，README SHA-256 `885424e599e692e4ac13c5b8b94913925dc770f09e2387832bcd4865b473c217`）把六种预处理 benchmark 指向[作者 Google Drive 目录](https://drive.google.com/drive/folders/1ZOYpTUa82_jCcxIdTmyr0LXQfvaM9vIy)。本轮只读取目录元数据，得到以下文件 ID 与大小，均与本地长度相同：

| 文件 | 已观察作者文件 URL | 对应目录 |
|---|---|---|
| electricity.csv | [1jinfTAApPyuyvW1P1hUDpI3rl0Jq8in1](https://drive.google.com/file/d/1jinfTAApPyuyvW1P1hUDpI3rl0Jq8in1/view) | [electricity](https://drive.google.com/drive/folders/1ZhaQwLYcnhT5zEEZhBTo03-jDwl7bt7v) |
| traffic.csv | [1U3BZ3Wvuvd9HVAx5Nl3bHYG9rsh5-yZX](https://drive.google.com/file/d/1U3BZ3Wvuvd9HVAx5Nl3bHYG9rsh5-yZX/view) | [traffic](https://drive.google.com/drive/folders/1M3gTc1DSvnUFMI57p70VFH5MHhZh3wC8) |
| exchange_rate.csv | [1EBLfP2Dx2K7LsSZybX4JJes-wEcTJbz-](https://drive.google.com/file/d/1EBLfP2Dx2K7LsSZybX4JJes-wEcTJbz-/view) | [exchange_rate](https://drive.google.com/drive/folders/1nuMUIADOc1BNN-uDO2N7zohLgpLDgl-Z) |

Drive 文件 ID 不是不可变内容版本；固定的是本轮观察到的 URL／页面 hash 和本地 SHA-256。后续完整获取必须核对 expected hash，不能靠 filename／长度证明字节相同。Autoformer 的代码 LICENSE 不被用来授权这些外部分发的数据文件。

LSTNet 作者维护的 [multivariate-time-series-data 固定 README](https://raw.githubusercontent.com/laiguokun/multivariate-time-series-data/7f402f185cc2435b5e66aed13a3b560ed142e023/README.md)（commit `7f402f185cc2435b5e66aed13a3b560ed142e023`，README SHA-256 `fa5e75b4638f607e3a0ac1de6c8b3862dd5883ad5eb26441c59e3449ef626253`）提供对应历史数据路线：

- Electricity：原始 UCI 15分钟数据，作者称删除2011和零维后取2012–2014的321客户、转为小时 consumption。固定发布对象为 [electricity.txt.gz](https://raw.githubusercontent.com/laiguokun/multivariate-time-series-data/7f402f185cc2435b5e66aed13a3b560ed142e023/electricity/electricity.txt.gz)，Git blob `df158a9fff65428ece107200432a72c992d5e4e9`，17993794 bytes。
- Traffic：指向 Caltrans PeMS，作者称 San Francisco Bay freeway occupancy，值在0–1；原 README 同时写“48 months (2015-2016)”，该月份／年份矛盾保留，未替作者校正。固定发布对象为 [traffic.txt.gz](https://raw.githubusercontent.com/laiguokun/multivariate-time-series-data/7f402f185cc2435b5e66aed13a3b560ed142e023/traffic/traffic.txt.gz)，Git blob `63ddb74bf7602568f36056a0b1a47aa407f0a6fe`，29310512 bytes。
- Exchange rate：作者称八国1990–2016 daily rates。固定发布对象为 [exchange_rate.txt.gz](https://raw.githubusercontent.com/laiguokun/multivariate-time-series-data/7f402f185cc2435b5e66aed13a3b560ed142e023/exchange_rate/exchange_rate.txt.gz)，Git blob `d72d0d7a5d5d06ecd1cf4c79396180b2962be101`，177142 bytes；未提供可核实的 primary 金融数据商／quote convention／货币列顺序。

这三份作者文本 gzip 也未在本轮下载／展开；它们与现有 CSV 的数值内容／添加日期流程尚未建立 exact comparison。固定树中未发现数据专用 LICENSE。因此这些路线是来源证据，不能单独变成精确预处理 CSV 的许可或质量单位保证。

## PeMS 作者固定发布身份

ASTGCN 的 [固定 README](https://raw.githubusercontent.com/guoshnBJTU/ASTGCN-2019-pytorch/2e7a4faa2a6f89da8d1cb37acb7e267c9bc87296/README.md)明确把 PEMS04／08 数据指向同作者 ASTGNN data 目录。ASTGNN 当前 main 固定为 commit `9c2e19b98c4cedf1f35214d8789685b6381b3aad`；[完整 Git 文件树](https://api.github.com/repos/guoshnBJTU/ASTGNN/git/trees/9c2e19b98c4cedf1f35214d8789685b6381b3aad?recursive=1)含四份 NPZ。本地按 Git 对象规则计算 `SHA1("blob " + byte_length + NUL + file_bytes)`，四份均与固定树中的 blob SHA-1 和 size 相同。独立本地 SHA-256 见前表。

| 本地文件 | 作者固定 raw URL | 已匹配 Git blob SHA-1 |
|---|---|---|
| PEMS03.npz | [data/PEMS03/PEMS03.npz](https://raw.githubusercontent.com/guoshnBJTU/ASTGNN/9c2e19b98c4cedf1f35214d8789685b6381b3aad/data/PEMS03/PEMS03.npz) | `b4487154fc9611a3bf9856b0aad34efa610ea8ae` |
| pems04.npz | [data/PEMS04/PEMS04.npz](https://raw.githubusercontent.com/guoshnBJTU/ASTGNN/9c2e19b98c4cedf1f35214d8789685b6381b3aad/data/PEMS04/PEMS04.npz) | `a1a39eac4b86963b1ac22874fd1cc693eb642cd2` |
| PEMS07.npz | [data/PEMS07/PEMS07.npz](https://raw.githubusercontent.com/guoshnBJTU/ASTGNN/9c2e19b98c4cedf1f35214d8789685b6381b3aad/data/PEMS07/PEMS07.npz) | `28c547f80eb8804d3e378168c80f77f82db2680a` |
| pems08.npz | [data/PEMS08/PEMS08.npz](https://raw.githubusercontent.com/guoshnBJTU/ASTGNN/9c2e19b98c4cedf1f35214d8789685b6381b3aad/data/PEMS08/PEMS08.npz) | `f5f3e84a00417573aa8487fe1e9e8cd13c6026c8` |

该核查使用已存在的本地文件和远程小型文件树，没有下载 NPZ，也未重新计算远程正文 SHA-256。Git blob identity 是发布对象关联；它不证明作者所有预处理步骤、primary 原始采样日期、传感器／feature 单位或所有论文复现过程。

另核实 STSGCN [固定 README](https://raw.githubusercontent.com/Davidham3/STSGCN/3f825f6421afb84fb69ef560179bf799fbf4481c/README.md)及四份 `config/PEMSxx`（commit `3f825f6421afb84fb69ef560179bf799fbf4481c`）。作者给出 [STSGCN_data.tar.gz 的百度分发入口](https://pan.baidu.com/s/1ZPIiOM__r1TRlmY4YGlolw)，代码 `p72z`；本轮未获取该包，不能把其 package 与本地 NPZ 字节相同作为已验证事实。ASTGNN 固定树中未发现 LICENSE，GitHub API license metadata 为 null；这表示本轮未建立数据专用许可，不以 README 的可下载性替代授权范围。

## Primary 数据许可与保留的未知项

[UCI ElectricityLoadDiagrams20112014](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014)，DOI `10.24432/C58C86`，页面明确数据许可证为 **CC-BY-4.0**。primary 页面写每15分钟数值单位是 **kW**，转换为 kWh 需除4，并描述 Portuguese hour／DST处理。LSTNet README 则写 kWh／hourly consumption；本地 CSV 没有单位与转换记录，本轮未做 primary 内容匹配，因此精确本地 values 单位继续 unknown，不能直接共用物理 ABS 尺度。

[Caltrans PeMS primary](https://pems.dot.ca.gov/)可访问；其 [Terms of Use](https://pems.dot.ca.gov/?view=tou) 的 Ownership 段写：

> In general, information presented on this web site, unless otherwise indicated, is considered in the public domain. It may be distributed or copied as permitted by law.

同段还明确非 State-owned／created 内容需向原持有人取得许可。这是有条件的一般网站声明；未建立确切 traffic CSV／四份作者加工 NPZ 的数据专用许可、State ownership 和完整加工来源，所以它们的 exact packaged data license 仍为 unknown，不填造 SPDX，也不从“政府网站”推定全部公有领域。exchange_rate 的精确 primary 来源、数据许可及 quote 单位仍为 unknown。

新增研究不捆绑原始文件或派生窗口。后续研究应保留 local hash／作者固定 ref／许可状态，允许在明确的已存在本地数据范围执行实验；发布包只附获取路线、来源证据与 hash，不据此宣布所有数据可再分发。

## 下一批有限对象与资源预算

PeMS 优先采用 values／bitwise，保留 `<f8`／rank3／C-order；T缺失保持缺失，0值按原 bits 保留，不把图学习代码的0-as-missing策略移植为 benchmark mask。源原数组解压 raw bytes约75／125／199／73 MB，解析可能分配全源数组；512-row窗口 raw bytes分别1466368／3772416／3616768／2088960，额外 Python／NumPy／envelope／native 暂存峰值仍需实际资源证据，不能用这些裸大小宣称RSS或峰值保证。

限定网格采用每源 `start=1024`、长度128／512／8192的12具名对象；4方法请求 raw-store／zstd-frame／deflate-zlib／chimp128，共48请求，3sessions×7rounds。Chimp128的rank3请求应明确unsupported并保留分母，不通过flatten绕过能力限制。预计36个可执行请求、756个正式slot，但这只是准备预算，codec资格或正式结果须另行记录。既有历史源码／结果曾读取过这些来源，窗口的 prior exposure 也不能由新run身份抹去；不称本批为盲测／未观察holdout。
