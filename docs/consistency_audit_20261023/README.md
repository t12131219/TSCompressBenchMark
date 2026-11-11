# TSBench → Compression_Rewrite → 原生源码一致性核验

核验日期：2026-10-23（Asia/Shanghai）。结论：**不能认定全部一致**。30 个活动 CPU key 的消费包与当前重写源码逐字节相同；ELF 四个 key 仍是旧包，DeepZip/DZip 当前重写来源路径缺失。重写与原生的一致性也分为原始码流一致、限定域语义一致、显式修复版本一致，不能互相替代。

本轮只新增本目录的诊断脚本、报告和运行证据，没有修改算法实现、登记、构建配方或既有实验结果。使用任务开始时的工作区状态；原有 forecasting 工作保留。

## 范围和判断标准

- 当前 CPU registry 有 55 个 key，其中 `lzss-raw`、`lzss-dipperstein-c` 的 `admission.status=EXCLUDED`，活动真实 CPU codec 为 53 个；`raw-store` 是基线。另检查独立 GPU 扩展 `cuszp-fixed-1d`。`lz77` 是别名，不另计算法。
- “源码相同”指消费文件 SHA-256 相同，不推断两个适配器 API、默认参数、完整帧和全部能力相同。
- “与原生一致”按各包声明的目标判断：原生 payload/交叉解码，或分阶段与恢复数值的语义对照。有损恢复不必等于原输入；无损不能以数值容差代替按位恢复。
- 本轮重新执行接入回归、Gorilla/Chimp/ELF 源码对照和 ELF 新旧包比较。ABBA、ALP、Sprintz、CAMEO 的完整独立验收沿用已保存证据，并重新验证其索引中的哈希；没有重新运行全部平台、全部历史数据、sanitizer 或正式性能实验。

## 第一段：Bench 与当前重写目录

| Bench key / 家族 | key 数 | 当前源码比对 | 判断 |
|---|---:|---|---|
| `abba`、`fabba`、`qabba` | 3 | 7830/7830 项记录相同 | 已同步到 abba-family 发布包；Bench 能力范围比独立包小 |
| `alp`、`alp-rd` | 2 | 56/56 相同 | 已同步 safe-v1；Bench 只开放 portable |
| `cameo`、`vw`、`pip`、`tp`、`swab`、`sim-piece`、`pmc-mean`、`swing-connected`、`dft`、`dwt-dct-ii` | 10 | 1692/1692 相同 | 已同步 repaired-v1 |
| `chimp`、`chimp32`、`chimp128`、`chimpn`、`chimpn32`、`chimp128-no-index`、`pmc-mr`、`swing-filter`、`swing-filter-disjoint`、`swing-filter-disjoint-quantized` | 10 | 62/62 相同 | 已同步 chimp-family；Chimp128 是 ChimpN(128) 配置 |
| `gorilla-prometheus-xor` | 1 | 24/24 相同 | 已同步完整 Prometheus XOR chunk 重写包 |
| `sprintz-delta`、`sprintz-fire`、`sprintz-delta-huffman`、`sprintz-fire-huffman` | 4 | 1593/1593 相同 | 其中 438 项 reference-source 映射到 `Source/sprintz-family`，其余映射到 `ReWrite/sprintz-family` |
| `elf`、`elf-plus`、`elf-star`、`self-star` | 4 | 旧包 34 项记录自身锁定正常，但不是当前 shared implementation | **未同步**；见下文的实际码流对照 |
| `deepzip`、`dzip` | 2 | Bench 冻结副本分别 38/38、1115/1115 正常；当前 `ReWrite/deepzip`、`ReWrite/dzip` 不存在 | **当前来源不可对照**；不能认定当前重写版相同，也不能据路径缺失断言 Bench 算法损坏 |
| Brotli、bzip2、DEFLATE、LZ4-frame、LZSSE2、LZSSE8、Snappy、XZ、Zstd | 9 | 共 606 项 vendor 文件，与 `ReWrite/lzbench` 及原始 `inikep_lzbench` 均相同 | 原生库消费，不是另行翻译；Bench 增加 API、帧和参数约束 |

以上覆盖 45 个活动 CPU key。剩余 8 个使用直接原生资产，当前 `Compression_Rewrite/ReWrite` 没有对应独立重写包，不能强行建立不存在的第二段路径：

| key | 本轮直接来源核验 | 需保留的区别 |
|---|---|---|
| `fse`、`huff0` | vendor/lib 15/15 与 FiniteStateEntropy 原始仓库相同 | 熵编码原语加 Bench envelope |
| `neats-lossless-i64`、`leats-lossless-i64` | 168 项相同、2 项改动、2 项非原路径文件 | 改动为 NeaTS.hpp/LeaTS.hpp，已有 GCC11/scalar 兼容与 LeaTS 序列化补丁；不是原版所有 SIMD/持久化能力的完整复制 |
| `serf-qt`、`serf-xor` | 原始 vendor 35/35 相同 | 构建再应用显式安全/误差补丁；XOR 严格界修正可能改变近似值，非有限/不表示域有计费 raw exception，不能称运行语义全面等于未修补上游 |
| `simdcomp-u32` | vendor 27/27 相同 | 运行构建有明确边界修补；仅 uint32 primitive，不等于 FastPFOR SIMDBinaryPacking |
| `zfp-accuracy-1d` | vendor 94/94 相同 | 仅 serial 1D fixed-accuracy 的 f32/f64 列路径 |

GPU `cuszp-fixed-1d` 的 7 项 vendor 文件与原始 cuSZp 仓库相同，属于 CUDA kernel 加 checked host wrapper，非该目录中的重写包。本轮未重新执行 GPU 运算。

### ELF 的实质差异

当前入口映射为 `elf → ReWrite/elf-original`，其余三个 → `ReWrite/elf-family`。Bench 仍使用 `adapters/rewrite_lossless/vendor/<key>` 中旧的独立 API；锁没有损坏，但版本未同步。当前重构报告也明确写明没有更新 Benchmark adapter/registry。

实际抽查 4 key × f32/f64 × 3 组输入，共 24 组：

| key | 完整帧相同 | 去掉各自封装后的原始 block payload 相同 |
|---|---:|---:|
| `elf` | 0/6 | **0/6** |
| `elf-plus` | 0/6 | **0/6** |
| `elf-star` | 0/6 | 6/6 |
| `self-star` | 0/6 | 6/6 |

例如 f64 `[0.23]`：Bench ELF raw=`9303fcd40100d4`，当前 ELF raw=`c981fe6a008068`；Bench Elf+ raw=`c981fe6a008068`，当前 Elf+ raw=`c981fe6d004035`。这是 payload 差异，不仅是容器 header 差异。

旧完整帧 magic 为 `ELF1`/`ELP1`/`ESF1`/`SST1`，当前为 `ELFORG\x01\x00`/`ELFCPP\x01\x00`。24 组 Bench 自身均按位恢复成功，说明“自行往返成功”不能证明版本/码流一致。Elf*/SElf* 的 6 组 payload 相同仅为抽查结果，不证明所有状态、跨块、边界与全域一致。

另有计时 API 差异：Bench 构建对旧 Elf/Elf+ 添加 `compress_unchecked`，直接 core 不执行独立包 `compress()` 内部的 decode/memcmp 自检；Bench 在资格和计时外另验恢复。不能把两个 encode API 的错误行为或耗时直接当作相同。

证据：`elf_bench_vs_current.json`、`elf_comparison_summary.json`，复跑脚本 `compare_elf.py`。

## 第二段：当前重写版与原生

| 重写家族 | 对原生的判断 | 本轮/现有证据及边界 |
|---|---|---|
| Gorilla / Prometheus XOR | **冻结对象范围内原始字节一致** | 本轮 Go↔C++ 227 case、489274 对 T/V，raw、四向解码、状态 trace 与计费均通过；原生序列化 partial-byte reset-and-append 缺陷仍保留，Bench 使用 fresh 独立 chunk |
| ABBA / fABBA / QABBA | **合同内语义一致，非原生 frame 逐字节承诺** | 独立验收 `FULL_PARITY / SEMANTIC`；本轮校验其 24 项证据引用全部匹配，接入回归通过。Bench ABBA `min_k=1`，独立源码默认 2；比较时必须显式对齐参数。独立包的模型复用/多序列等能力并非均由 Bench 暴露 |
| Chimp 家族（含 FPC、PMC-MR、Swing） | **合法无损域码流一致；有损为源语义一致** | 本轮 Java↔C++ 263 case，255 对照通过、8 预期拒绝，零意外差异。源 reserved EOF、非有限值及 Swing 质量问题仍需拒绝/限制。Research validated，未宣称完整无条件 FULL_PARITY |
| ALP / ALP-RD | **safe-v1 限定原生移植，非全域原版等价** | 原版 f32 FACT[10] 越界、浮点到整数转换/采样溢出等 UB 已明确修复；定义良好路径保留，UB 路径不宣称原版决策/字节相同。24 项验收证据引用匹配；独立状态为 NATIVE_PORT_QUALIFIED，不是 full upstream parity |
| Sprintz 家族 | **限定原生移植；存在明确输出差异** | 现有差分 774 case 中 722 原版完整字节一致，52 属原版 raw16 奇数尾字节截断；移植版保留完整实际字节。因此这 52 不能称与“被截断的原版返回流”逐字节一致。60 项证据引用本轮全部匹配 |
| CAMEO 十算法 | **与授权 repaired-v1 语义一致，不等于未修改原版** | 六个 Cython 修复文件，包含 TP first-span 规则；最终 FULL_PARITY 目标是 repaired-v1。原始状态仍 BLOCKED，历史598组记录有539 PASS、25 SOURCE_FAILURE、34 NATIVE_FAILURE；本轮校验最终21项证据引用全部匹配，并跑接入回归 |
| 当前原始 ELF | **合法源域原始码流一致，原生自身有缺陷** | 本轮82组：68 PASS、11 SOURCE_DOMAIN_FAILURE、3 SOURCE_ROUNDTRIP_DEFECT。缺陷包括 NaN/EOF 和 power-10 恢复；状态仍 BLOCKED，不能推广为全域无损 |
| 当前 SElfStar/ELF family（含消融、ElfHuff） | **限定源域一致，f32 含显式原生构建修复** | 本轮702组：359原始构建PASS、193 REPAIRED_BUILD_SOURCE_PASS、123源域失败、27源往返缺陷。原生 f32 缺少变量声明需补丁；ElfHuff 原生缺失真实 Huffman 状态切换，正式状态仍 BLOCKED |
| DeepZip / DZip | **当前目录无法核验** | 当前 Rewrite/Source 都无对应活动独立目录；Bench 保留历史冻结实现及来源资料。其历史资格不能证明当前不存在目录的同步或完整原生一致 |
| lzbench | **原生源文件复用** | 选中606项 Bench/Rewrite/original 三方相同；它是原生压缩库集合，不能视为独立算法翻译验收 |

当前重写目录还包含未注册的 `fpc-chimp`、`elf-original` 独立来源入口、`elf-huff`、Elf* 消融及 no-huff 入口等。它们复用上述家族，不应按目录数量推断 Bench 已接入算法数量；`elf-original` 本身是当前 `elf` 的实际实现目录。

## 本轮证据和复跑

哈希证据见 `source_identity.json` 和较小的 `hash_summary.json`：

- 12,444/12,444 项 Bench 冻结文件记录匹配自身 lock；这是文件记录数，包含 vendor 依赖及参考资产，不是算法数。
- 11,257/11,257 项对应当前重写包的记录相同，覆盖上述30个活动 key；ELF 34项和神经两包1153项单列为版本/路径问题。
- 六个消费发布归档的 SHA-256 全部匹配锁（包括 CAMEO full-parity 归档）。
- 905/905 项 `Source` 原件同时匹配来源清单和原始仓库路径；606/606 项选中 lzbench 文件与原始仓库相同。验证来源身份不等于验证算法全域正确。
- ABBA 24、CAMEO 21、Sprintz 60、ALP 24 项现存验收证据引用全部匹配；保留历史通过范围，不冒称本轮重新执行这些完整验收。
- 六家族接入回归 **945 passed，0 skipped，67.50秒**；见 `pytest.log`、`pytest.xml`。本轮不是全仓回归。

在仓库根目录执行：

```bash
python docs/consistency_audit_20261023/audit_sources.py
PYTHONPATH=benchmark/src:benchmark/tests /home/fzg/anaconda3/envs/CompressBench14/bin/python docs/consistency_audit_20261023/compare_elf.py
```

源码对照实际使用各包 `tools/verify.py`，本轮产物：

- `gorilla_source_fresh/results.json`：原生 Go 与 C++，包括真实 fixture。
- `chimp_source_fresh_retry/verification.json`：fresh Java 编译，synthetic-only，含 FPC 和独立 filter2。首次 CLI 路径少了 `bin/` 的运行失败保留在 `chimp_source_fresh.log`，重跑成功不覆盖该记录。
- `elf_original_source_fresh/verification.json`、`elf_family_source_fresh/verification.json`：fresh Java 编译，synthetic-only，源域/源缺陷未从分母删除。
- `elf_bench_vs_current.json`：实际登记 Bench 产物与当前独立 CLI 的帧、payload 和恢复。

所有对照使用当前已有 C++可执行文件和 Bench 构建产物；本轮未独立重建整个 C++/数值依赖闭包。二进制路径/hash及 Java 命令由各验证报告记录。ABBA/CAMEO 的 SEMANTIC、ALP/Sprintz 的安全移植以及 ELF/Chimp 的研究资格，应继续按各自合同解释。

## 需要处理的事项

1. ELF 四入口若要与当前重写库保持同步，需要单独替换消费包/适配器、更新 source/build 身份并重做资格；历史性能不能直接改签到新版本。
2. 明确 DeepZip/DZip 当前独立包的保留位置，恢复可追溯来源，或正式指定 Bench vendor 为保留实现。
3. 论文/报告分别写明 repaired-v1、safe-v1、限定原生移植与合法源域；不要将回归通过、原件哈希一致或 FULL_PARITY 标签扩大成所有原生输入与能力无条件一致。
