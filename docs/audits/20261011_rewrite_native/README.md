# 已接入算法的重写与原生性审查（2026-10-11）

> 历史记录：本文审查发生在同日 `lzss-raw` C++ 迁移之前，保留当时的入口计数、原生语言判定和证据。当前 `lzss-raw` 已重写为 C++17，迁移后的实现与验证见[迁移报告](../../lzss_cpp_rewrite_20261011/README.md)。

结论：**33 个活动入口的当前 Benchmark 接入与原生核心执行证据成立；不能统一宣称“全部完整重写成功、全部是未经修改的原作 C++ 实现”。** 其中 10 个入口使用翻译后的 C++，22 个入口复用 C/C++ 实现，`lzss-raw` 复用 Rust 原实现。范围之外另有 3 个保留登记；4 个框架 oracle 和 `lz77` 别名不计为额外算法。

本次检查同时读取用户指定的 `Compression_Source_Code/Source_Code`、本项目 `Compression_Rewrite`、实际 adapter/vendor/build、registry 和物理 Benchmark 工件。没有修改算法、注册或旧验证记录，也没有重新测量性能。新增证据均在本目录。

## 判定口径

“重写成功”需要当前实现针对指定版本和声明输入域，与独立原作 oracle 的语义或原始流一致；自回环、编译通过和 Benchmark PASS 单独不足以证明。直接复用上游实现的算法应称接入成功，不应称完成了一次 C++ 翻译重写。

“原生执行”指压缩、解压和模型计算确实由编译后的 C/C++/Rust 核心执行，Python 可以负责控制、布局、容器和调用。它不自动表示源文件未经修改、原作的全部功能已接入、每个输出块都使用该算法，或 CORE/PIPELINE 是纯内核计时。下表中的“原生”采用这个执行定义；原作纯度与支持范围单列说明。

“完整上游一致性”是额外声明。有限配置、合法域、固定模型或已测平台通过，不能扩大为所有输入、参数、训练、设备与公共接口均 FULL_PARITY。无法重放的证据保留 UNKNOWN；明确排除的能力按部分接入处理。

## 逐入口结论

下列 33 个活动入口均通过本次 factory 加载、当前 artifact hash 及冻结资格计划核对。Benchmark 资格限既有 41 个 Track case 与冻结正式任务。表中的“支持域成功”包含合同声明的拒绝，不能解读为任意输入无损。

| 算法入口 | 重写/接入结论 | 原生核心 | 必须保留的限定 |
|---|---|---|---|
| chimp | 冻结原作支持域内重写成功 | C++ 翻译 | binary32/64；canonical NaN 是 END；112 例本次原作流重放 |
| chimp128 | 冻结原作支持域内重写成功 | C++ 翻译 | 历史长度为 128；canonical NaN 是 END；112 例重放 |
| elf | VLDB2023 版本支持域内重写成功 | C++ 翻译 | 所选原作 386d6934，不能错比当前 dev/Elf+；109 例重放 |
| elf-plus | 冻结原作支持域内重写成功 | C++ 翻译 | NaN/部分数值源域拒绝；82 个有效无损例重放，10 个拒绝/END 例不计成功编码 |
| elf-star | 冻结原作支持域内重写成功 | C++ 翻译 | 独立块 Huffman；109 例重放；原 Java reference 有编译 overlay |
| self-star | 冻结原作支持域内重写成功 | C++ 翻译 | 跨块自适应状态被保留；89 例重放；历史报告两处文件 hash 过期 |
| abba | 已验证配置的语义重写成功 | C++ 翻译 | 有限 f64；74 阶段＋64 capability 例通过；合同仍标 PARTIAL_REWRITE，不据此授予全部 API/参数资格 |
| fabba | **稳定化 profile 的部分重写成功** | C++ 翻译 | 原合同仍为 PARTIAL_REWRITE；alternate sorting/alphabet 等排除；部分 oracle 重实现稳定化 digitization |
| deepzip | 固定模型 CPU 编解码接入成功 | C++ 翻译与模型推理 | uint8 0..3、17 个随机初始化未训练的冻结测试模型，51 context 对归档 TF 概率通过；不代表官方训练 checkpoint/CUDA |
| dzip | 已声明 seeded profile 接入成功；当前完整原作语义未证实 | C++ 翻译与模型推理 | bootstrap/combined 未预训练模型，当前双向回环与在线更新通过；本次没有原模型/梯度差分，不能替代原作重写证明 |
| alp | 既有 C++ 核心接入成功 | C++ | 强制 decimal ALP；完整对象可使用显式 SOURCE_REJECT_RAW 组合；f64 组 16/32 次含 RAW |
| alp-rd | 既有 C++ 核心接入成功 | C++ | 强制 ALP-RD；声明 dtype/rowgroup 域；不与 ALP 混称 |
| brotli-stream | 上游实现接入成功 | C | known-length streaming；完整容器/FFI 成本与纯库 API 区分 |
| deflate-zlib | 上游实现接入成功 | C | 是完整 DEFLATE；`lz77` 是来源/机制别名，非独立纯 LZ77 |
| lz4-frame | 上游实现接入成功 | C | LZ4 frame；完整容器、已知长度 streaming/P2 组合按各合同验收 |
| snappy-raw | 上游实现接入成功 | C++ | Raw Snappy profile；typed object 来自显式字节表示 |
| zstd-frame | 上游实现接入成功 | C | Zstd frame；完整容器、已知长度 streaming/P2 组合按各合同验收 |
| xz-stream | 上游实现接入成功 | C | XZ profile、所选 preset/check；非上游全部 MT/CLI 变体 |
| lzss-raw | **原 Rust 实现接入成功；没有 C++ 翻译重写** | Rust 静态库＋C ABI | 31 个原库文件匹配；void 三文件的权威来自另行 acquisition provenance |
| lzss-dipperstein-c | 有限 profile 接入成功 | C | 生成副本上应用安全修补；所需原仓不在指定 Source_Code 内，来源需另查保留获取记录 |
| fse | 上游熵编码核心接入成功 | C | frame 允许 RAW/RLE/FSE 分支；不能把每个 PASS 都称为 FSE 编码 |
| huff0 | 上游熵编码核心接入成功 | C | frame 允许 RAW/RLE/Huff0 分支；不能把每个 PASS 都称为 Huff0 编码 |
| neats-lossless-i64 | **修改后的原生实现接入成功** | C++ | vendor 原作已直接修改；标量/有符号整数/列独立 profile 与 bias 归一化；原作纯度证明不通过 |
| leats-lossless-i64 | **修改后的原生实现接入成功** | C++ | vendor 已恢复 serialization 并修正 predictor；文档所称外部补丁重放与实际构建不符 |
| serf-qt | 上游核心加适配 frame 接入成功 | C++ | 固定误差 profile；存在声明 RAW 分支，非所有输出都由 SerfQt 编码 |
| serf-xor | 上游核心加适配 frame 接入成功 | C++ | 固定误差 profile；存在声明 RAW 分支，不能由名称推断全域无损 |
| simdcomp-u32 | 有限 primitive/SDK 接入成功 | C | 已哈希的生成补丁；SSE4.1/AVX2；P0 uint32，不是完整 int64 时间戳方案 |
| sprintz-delta | 上游核心接入成功 | C++ | uint16 原位模式、联合矩阵、明确 ISA/尾部；安全修补变体 |
| sprintz-delta-u8 | 上游核心接入成功 | C++ | uint8 独立入口；不由其资格推断其他位宽 |
| sprintz-fire | 上游核心接入成功 | C++ | FIRE、uint16 原位模式、联合矩阵与声明 ISA/尾部 |
| sprintz-fire-u8 | 上游核心接入成功 | C++ | FIRE uint8 独立入口；不由其资格推断其他位宽 |
| sprintz-fire-huff0 | 真实组合方案接入成功 | C++＋C | Sprintz FIRE→Huff0；组件、容器及 RAW 分支不能冒称单一纯 Sprintz |
| zfp-accuracy-1d | 上游核心加适配 frame 接入成功 | C | 1D fixed-accuracy；特殊值、范围或压缩率分支可 RAW；不是全部 ZFP 模式 |

`bzip2-stream`、`lzsse2-raw`、`lzsse8-raw` 属于范围外旧登记。本次三个 release 库**实际存在、可加载且 build artifact SHA 匹配**；不能沿用旧对照文档中“本地构建产物缺失”的描述。它们不计入 33 项当前活动资格与正式范围，存在二进制不授予当前活动验收。

## 需要修正的结论与证据问题

1. **ABBA/fABBA 的配置成功不能理解为整个上游无缩范围完成。** 两者合同仍标 `PARTIAL_REWRITE`。fABBA 的 [contract.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/completed_rewrites/vendor/fabba/contract.md:6) 在14行开始限定 `stable-norm2-scl1-v1` 并排除其他 sorting/alphabet 等路径；能力矩阵却写 FULL_PARITY。本次73例中，26例 digitize 与原始 AGG 比对、46例走自定义稳定化 digitization、1例只测 decode。后者不能证明原作未经修改的 digitization。稳定 tie 排序和零标准差替换是已公开的语义变体，应该按该 profile 命名结论。
2. **NeaTS/LeaTS 来源描述与构建事实不符。** 172 个 vendor 文件中 170 个与指定原仓一致，两个主要头文件不同。注册的 `71c668...` 闭包恰好包含当前已改源码，因此本次没有随机源码漂移；但 [接入审查](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/neats_leats_admission_review.md:24) 所称“在 immutable vendor 之外重放三个 build-time patches”不成立：[实际构建](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/build_codec.py:992) 直接编译 vendor 头文件，三份 `.patch` 是说明文本。必须将其表述为已修改 variant，或以后重建未改 vendor＋可应用补丁＋重新冻结验证，不能声称纯原作。
3. **RAW 输出必须按组合方案解释。** 本次读取 ALP 64 个实际正式 composite frame，并核对 stream SHA：f32 为 32 次 all-CODEC；f64 为 16 次 all-CODEC、16 次含 RAW。它们在冻结计划中已经登记 SOURCE_REJECT_RAW，因此是已声明方案的 PASS，并非伪造编码；但不能全部作为强制 decimal ALP 纯核心压缩效果。详见 [物理分支证据](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/alp_formal_branches.json)。
4. **历史 parity 记录的重现能力不同于当前接入资格。** `Compression_Rewrite/INTEGRATION.md` 已说明清理了大型训练/数组/发布产物，Source 仅为参考集。Java oracle 的历史 `/tmp` runtime/JAR 已失效；SElf* differential header/CMake 两处 hash 过期。当前代码回放通过支持核心正确性，不能补签为本次重新运行全部原作 oracle/G0–G6。
5. **模型域和原生语言应如实表达。** DeepZip/DZip 的原生 CPU 推理并非 Python 模型替代，但两者本次部署的默认模型均未预训练。DeepZip的17个portable模型与原Keras导出fixture SHA一致，可核查的export命令没有 `--checkpoint`，模型由seed后直接构造并保存随机初始权重；DZip明确使用 `NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET`。这些profile的恢复与推理通过，不能代表官方预训练模型的压缩效果，也不能替代训练/梯度差分。Rust LZSS是原生Rust；其C ABI和C++ shim不会使核心变成C++重写。

上述问题没有复现当前受支持任务中的编码/解码错误。它们影响“原生原作、完整重写、可重放 FULL_PARITY”的论断；不应通过更改旧 PASS、删失败或手改历史 hash 解决。

## 本次验证与产物

- 全部 36 个真实登记入口 factory 加载成功；33 个活动入口冻结计划源码、注册、执行及历史引用校验通过。70 个现存 build profile 的 artifact hash 匹配；本轮通用脚本另核对 781 条 build dependency hash 与 1,322 条所提取 source 文件记录。通用 source extractor 对七个源码族没有足够记录，返回 UNKNOWN；独立 upstream 逐文件检查补充了实际证据，不能把 UNKNOWN 当作自动 MATCH。
- 直接原生适配组执行 **1,369 项现有回归，全部通过**，没有 fail/skip。SIMDComp 的 source/AVX2/native/SDK 独立审计实际重核均 PASS，范围继续限定 uint32/SSE4.1/AVX2。
- 无损翻译组 **613 个有效用例**重新编码/解码并比对原 Java 存档流，全部通过；5 个包的当前 standalone preflight 全部通过。本轮没有重新启动 Java oracle。
- ABBA阶段74＋capability64例、fABBA阶段73＋partition32例及四项release binding资格本次全部通过；DeepZip 51 context 对归档 TF 概率通过、17 模型的原导出SHA一致；DZip 两个seeded变体当前ABI回环通过。详见 [completed_agent.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/completed_agent.md) 与 [机器记录](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/completed_agent_evidence.json)。这些验证的原作独立性/域各不相同，不能把总通过数当作同一种 parity 证明。
- V3.2 **完整产物审计实际重跑通过**，重建验收对象与既有 `completion-final.json` 完全相等，acceptance ID 为 `v3:v32-current-scope-acceptance:sha256:e81208534b3adfd827e81323088faf9eabc1749857a1839aba40f282172084ec`，引用 431 个工件。其校验覆盖当前源码/配置、41 个活动资格 case、独立恢复、真实流与成本、SDK/回归引用、普通/workload/P2 正式证据；该状态本身明确不升级 SOURCE_PARITY UNKNOWN。

第一次完整审计在未设置相同线程变量时正确拒绝，原因是环境身份不同；日志保留为 `completion_recheck.log`。设置冻结批次使用的四个线程变量为 1 后，environment ID 完全一致，只有不进入 identity 的当前可用内存和 swap 观测变化。第二次完整审计通过，未修改环境门禁或旧冻结文件。

可复现命令（在项目根目录，以独立新文件名输出；完整审计不重新测量性能）：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  /home/fzg/anaconda3/envs/CompressBench14/bin/python tools/audit_v32_completion.py \
  build/v32-evidence-20261010/current-r2 \
  --declaration build/v32-evidence-20261010/current-r2/declaration-release-r4.json \
  --output /tmp/rewrite-native-completion-reproduce.json
```

逐包证据与当前检验详情：

- [当前 registry/build/source 检验](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/current_checks.json) 与 [检验脚本](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/check_current.py)。
- [六项无损翻译审查](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/lossless_agent.md) 与 [613 例逐项回放](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/lossless_replay.json)。
- [四项学习/逼近重写审查](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/completed_agent.md)。
- [直接原生组审查](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/native_agent.md)、[逐文件上游对照](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/native_source_comparison.json)、[当前回归 JUnit](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/native_adapter_tests.xml)。
- [完整产物重新审计](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/completion_recheck.json) 与 [成功日志](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/completion_recheck_threads1.log)。
