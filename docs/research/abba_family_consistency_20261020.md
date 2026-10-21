# ABBA / fABBA 与 2026-10-20 abba-family 的一致性检查

后续状态（2026-10-20）：本核对描述替换前快照；旧接入已归档删除，当前ABBA/fABBA/QABBA使用独立新包。见[接入报告](../abba_family_integration/README.md)，以下原对比证据不改签。

日期：2026-10-20。结论：**当前 Benchmark 未接入新版 abba-family，ABBA、fABBA 均不能认定与新版完整一致。已找到相同参数下重建值不同的反例。**

本次检查源码、注册、构建路径，并执行有限规模的原生差分；不重新签署任何一方的 G0–G6。未修改算法、注册或构建实现。

## 当前接入与新版的区别

| 项目 | 当前 TSDataCompressBenchMark | 新版 Compression_Rewrite/ReWrite/abba-family |
| --- | --- | --- |
| 实现目录 | adapters/completed_rewrites/vendor/abba、vendor/fabba | 合并的 abba-family/src |
| 构建 | benchmark/src/tsbench/build.py 的 _rw_build，复制旧 vendor 后添加 encode_only | abba-family 自身的 CMake 构建 |
| 编码入口 | binding.cpp 调用 abba::encode_only / fabba::encode_only | abba_family API / af_execute_v1 |
| ABBA 上游提交 | 614d56841cd2f1c2925cea4d2c2648a7b2ac791d | 相同提交，但 C++ 翻译实现不同 |
| fABBA 上游提交 | 4066a5fc778f50f4bee1c41d8f3ab3ee4a3ff6ad | d8727ecffd6232308898d7bcb2415187ab456c57，v1.5.3 |
| fABBA 默认 alpha | 0.1 | 0.5 |
| fABBA 排序 | stable_sort，以原始索引处理等范数 | 2-norm 等路径复现 NumPy argsort 的间接快速排序 |
| fABBA 标准差保护 | std <= binary64 epsilon 时替换为 1 | std == 0 时替换为 1 |
| fABBA scl | 注册与 binding 要求 > 0 | 支持 >= 0 |
| 原生格式 | ABBA / FABB，固定头、binary64 中心、uint16 符号、CRC | AFS1，JSON 模型元数据、符号负载、CRC |
| 声明输入规模 | 注册上限 16,777,216 元素 | 新版说明上限 1,048,576 输入值，另有工作量等限制 |

旧包 contract.md 的 RewriteConclusion 为 PARTIAL_REWRITE；旧 PORT_MANIFEST.yaml 同时含自身验证范围的 FULL_PARITY。两者均属于旧快照，不能作为新版接入证据。新版 porting_report.md 第 3 行明确不签署 Benchmark 集成，第 11 行说明早期 Benchmark vendor 未改变。当前 abba/fabba 的冻结清单分别核对 35 / 27 个文件，均无哈希不匹配。

## 原生差分结果

直接从当前 vendor 源码编译旧版自带 CLI，编译选项为 C++17、O2、-fno-fast-math、-ffp-contract=off、pthread，ABBA 包含保留的 CKmeans 源文件。新版使用现有 build/abba_family_cli，其哈希记录在配套 JSON 中。

输入包括常量、直线、交替序列、等范数、微小值和固定随机种子生成的 12 条随机游走，共 18 条；共比较 108 组配置和输入。ABBA 两个 tolerance 映射到新版 tol 数组，fABBA tolerance 映射到 tol。显式指定相同参数，并将新版字符符号映射回中心索引后比较。数值容差采用 Python math.isclose(abs_tol=1e-10, rel_tol=1e-12)。

| 算法与配置 | 两边均成功 | 分段、中心、符号、重建全部匹配 | 重建匹配 |
| --- | --- | --- | --- |
| ABBA，默认 CKmeans/scl=0/norm=2 | 18/18 | 18/18 | 18/18 |
| ABBA，KMeans/scl=1 | 18/18 | 18/18 | 18/18 |
| ABBA，INCREMENTAL/scl=0 | 18/18 | 14/18 | 14/18 |
| ABBA，norm=1 | 18/18 | 18/18 | 18/18 |
| fABBA，tol=0.1/alpha=0.1/scl=1 | 18/18 | 9/18 | 18/18 |
| fABBA，tol=0.1/alpha=0.5/scl=1 | 18/18 | 10/18 | 17/18 |

fABBA 部分中心/符号差异仅体现中心编号或顺序，不能一概视为重建差异；表格单列重建比较。抽查一致不能证明全域一致，重建反例则已排除完整语义等价。

具体反例保存在配套 JSON 的 counterexamples，包含完整输入、参数、双方阶段结果和重建值：

- ABBA：输入 [0,1,0] 重复 12 次，tol=[0.1,0.1]、scl=0、c_method=incremental。双方均产生 3 个中心，但中心与赋值不同；重建的最大绝对差为 0.9166666666666666。
- fABBA：random_walk_5，tol=0.1、alpha=0.5、scl=1、sorting=2-norm。双方分段匹配，旧版 8 个中心、新版 9 个中心；重建的最大绝对差为 0.7199999999999998。

源码中 ABBA 增量路径也存在排序差别：旧版 canonical/abba.cpp 使用 stable_sort，新版 clustering.cpp 的初始次序使用 argsort。fABBA 的 stable_sort 与 NumPy argsort 差别同样可影响等键次序及后续聚类。这里只据代码确认差别存在，不将所有数值差异归因于单一因素。

## 容器与历史结果的影响

对 [0,1,3,1,2] 使用相同显式参数进行编码：

| 算法 | 旧原生容器 | 新 AFS1 容器 |
| --- | --- | --- |
| ABBA | 124 字节 | 315 字节 |
| fABBA | 132 字节 | 307 字节 |

以上是该小样本的原生容器长度，未附加 Benchmark 外层开销，也不是整体压缩率评价。两个方向的交叉解码均因 magic 不匹配被拒绝。旧 CLI 出错时会留下未闭合的输出 JSON 前缀，配套证据保留原始 stdout 和退出码；新版 CLI 的错误由 ok=false 表示，即使进程退出码为 0。

因此，现有 Benchmark 的压缩率、性能和资格记录对应旧实现。若改为新版，需要同步处理 adapter、参数映射、资源合同、码流计费、来源与构建冻结身份，并重新取得接入资格及运行结果，不能直接沿用旧记录或将新版独立包的 FULL_PARITY 当作已接入结论。

机器可读证据：[abba_family_consistency_20261020.json](abba_family_consistency_20261020.json)。包括 108 组比较摘要、两个完整反例、交叉解码输出和本次所读关键文件及新版 CLI 的 SHA-256。

## 追查：哪一版更接近原仓库源码

随后将上述两个重建反例交给 abba-family/tools/oracle.py，实际执行新版所冻结的原仓库 Python 类。ABBA 增量聚类与 fABBA 的两个例子均接受输入；新版重建与源码的最大绝对差均为 0，旧 Benchmark 分别为 0.9166666666666666、0.7199999999999998。请求与原始源码结果已追加至配套 JSON 的 source_oracle_followup。

因此，以本次指定、冻结的源码版本为目标，新版 abba-family 更接近源码行为。这是两个反例的直接源码裁决及实现检查结论，不等于本次重跑全部 G0–G6；也不裁决旧 Benchmark fABBA 与其历史提交 4066a5f 的全部一致性。新版自定义 AFS1 仍属于新增存储格式，不能称为上游原生码流。
