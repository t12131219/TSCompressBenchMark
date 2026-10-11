# ABBA、fABBA、DeepZip、DZip 源语义与原生执行审计

审计日期：2026-10-11。范围为当前 `COMPLETED_REWRITE_CTYPES_V1` 注册的四个入口；不计已退出算法，simdcomp-u32 由另一份审计处理。未发现本项目及父路径适用的 AGENTS.md。此次未修改实现、注册、现有资格或历史产物；仅生成本审计材料、在 `/tmp/tscb-completed-audit-20261011` 构建原始 CKmeans oracle 与生成临时输入。

| 入口 | 当前 codec/model/entropy 核心为原生 C/C++ | 当前已接入配置是否重写成功 | 是否足以声称完整、未改变的上游算法能力 |
|---|---|---|---|
| ABBA | 是，保留上游 C++ CKmeans，其他流水线译为 C++17 | 是，已复跑默认阶段 oracle 74 例及 alternate capability 64 例 | 只能声明冻结确定性语义配置；Python 驱动与自定义完整帧不是原上游格式，合同仍标 PARTIAL_REWRITE |
| fABBA | 是，分段、聚类、反变换与帧均 C++ | **stable-norm2-scl1-v1 成功**，73 例及 partition stage 32 例 PASS | **否**：oracle 的零方差和 norm ties 定义改变了原作，且替代排序/字母表等明确排除；FULL_PARITY 不能读作全部上游功能 |
| DeepZip | 是，C++ 模型推理、频率转换、算术编码、模型帧 | 当前 CPU/四词表/17 冻结模型有支持：当前 17 模型 × 3 context 对归档源 TF oracle 概率全部 PASS，默认 ABI roundtrip PASS | 当前 17 模型是原 Keras 构造器随机初始化的 oracle fixtures，未训练；接入不包括 CUDA、HDF5 importer、官方 xor20 二词表训练 checkpoint；旧 GPU/全 pipeline oracle 的数组和原 runtime 已清理，不能把历史 FULL_PARITY 直接重新签成当前全能力 PASS |
| DZip | 是，C++ GRU、算术编码、libbsc 模型存储与 combined Adam | 当前显式 seeded-untrained 模型变体可运行；BOOTSTRAP 与 COMBINED 的当前 ABI N=193 exact roundtrip 均 PASS | 当前默认并非上游加载预训练 PRNN 的实验；没有训练成本或训练模型质量证明，未接入完整 bootstrap CUDA/HDF5 工作流；旧数值与训练 oracle 只剩归档部分证据 |

此处“原生”指真实执行 codec/模型/熵编码核心的机器码，不表示整个 benchmark 驱动由 C++ 编写，也不表示容器与原 Python 上游逐字节兼容。四项的 Python adapter 负责路由、列复制、descriptor、调用 ctypes 与组合帧；native core 不是 Python/Keras/TensorFlow 的回调、导出图或替代压缩器。

## 本次复跑与来源核验

1. 当前 `Compression_Rewrite/Source/<name>/upstream` 中所有保留文件逐一与用户指定 `/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos` 对应原仓库字节 SHA-256 比对：ABBA 16/16、fABBA 23/23、DeepZip 9/9、DZip 98/98，零缺失、零差异。此结果只证明当前保留参考文件，没有宣称被清理的原始完整闭包仍存在。
2. 从原始 `nla-group_ABBA/src` 的六份 C++ 文件编译 `/tmp/tscb-completed-audit-20261011/ckmeans_source_oracle`，当前 release `abba_cli` 对阶段 oracle：10 golden + 64 deterministic property = **74 PASS**。以原上游为 source-root 的 alternate capability **64 PASS**（有限正 scl KMeans、scl=inf、norm、incremental/weighted/symmetric 等）。
3. 当前 release `fabba_cli`：9 golden + 64 deterministic property = **73 PASS**；以原上游为 source-root 的 partitioned-compress capability **32 PASS**。73 例中，仅 **26** 例会调用未改动的 `AGG.aggregate` 并检查一致性，**46** 例含零方差或 norm ties 而使用 oracle 的稳定化 digitize，**1** 例只做 decode。零方差出现于 41 例，norm ties 于 10 例，重叠 5 例。这个统计由原请求和 oracle 条件直接计算，未对 numpy 或源码 monkeypatch。
4. 四项当前 release `binding_qualification` 均 PASS：ABI identity、bound/capacity/canary、输入不改动、独立解码、确定性、截断与短/空输入（按各合同）等。ABBA/fABBA 的该测试只要求输出长度及有限重建，不检验源语义；不能用它替代上述 differential。
5. DeepZip 的全部 17 个 current portable 模型 SHA-256 与归档 `Source/deepzip/golden/locked/<model>/model_inventory.json` 的未改动原 TF/Keras 模型导出 SHA-256 全部一致。使用 current native `deepzip_cli predict` 测试可以从 oracle 源脚本复原的前三个 context：64 个 0、64 个 3、`arange(64) % 4`。全部 **51** 个 context 输出满足预先冻结容差（FP32 3e-5、FP16 3e-3），最大全模型 FP32 误差 5.960464477539063e-8、FP16 误差 0.000244140625；全部模型概率非恒定均匀分布。不是本次重新运行 TF 1.8/Keras 2.2.2，也没有声称频率或压缩流逐位相等。
6. DZip 直接调用当前 `libtscb_dzip.so` 的 rw_bound/rw_encode/rw_decode，以排序二词表、seed=0、N=193 分别执行 BOOTSTRAP/COMBINED。两者独立 exact roundtrip PASS；COMBINED 有 129 个预测符号，生产代码在第 128 个预测后执行一次 online Adam，随后继续推理及解码。BOOTSTRAP native frame 12,260 bytes，其中模型存储 12,186 bytes；COMBINED native frame 25,546,675 bytes，其中模型存储 25,546,600 bytes。模型确实被写入并计入帧，不能读 `model_bits=0` 总账字段为“免费模型”。本次不是源模型/梯度差分。
7. 归档 `ReWrite/dzip/validation/native-finalized-gcc/report.json` 所列 22 份 C++/header/test/tool SHA-256 与当前 `Compression_Rewrite/ReWrite/dzip` 全部一致，可支持实现来源连续性；报告内旧 binary、原模型/轨迹/梯度数组并非当前可重放产物。

上述模型输出、scope counts、DZip ABI frame hash 的机器记录见同目录 [completed_agent_evidence.json](completed_agent_evidence.json)。root 对全部 registry/factory/artifact 闭包另作全面核验，本文件不替代该结果。

## 为什么 fABBA 的 73 PASS 不是“不变上游语义”

`Compression_Rewrite/ReWrite/fabba/tests/oracle/fabba_oracle.py:40–76` 并未修改 `np.std` 或 `np.argsort`。它另写 digitize：第 43 行将 `std <= eps` 替换为 1；第 46 行用 `np.lexsort((原索引,norm))` 保证稳定排序；第 68–69 行仅在两个 std 都大于 eps 且 norm 无重复时调用原 `AGG.aggregate`。因此普通域有源聚类见证，其他域只有声明 stable profile 的见证。

原 `Compression_Source_Code/Source_Code/_repos/nla-group_fABBA/fABBA/fabba.py:1140–1146` 为不同的零标准差分支，increment std=0 仍可能除零；原 `fABBA/fabba_agg.py:42–44` 使用默认 `np.argsort`，没有原索引稳定 tie-break。`Compression_Rewrite/ReWrite/fabba/contract.md:14–17,40–49` 明确说明替代排序、字母表、multivariate、image 在配置外，并披露两项语义稳定化；`PORT_MANIFEST.yaml:25–44` 同样列出排除。故该变体实现可以成功，不能将名字 fABBA 与 `FULL_PARITY` 解读为全部原作能力与全部边界语义已保留。

## 原生执行的具体证据与边界

- `adapters/completed_rewrites/native/binding.cpp:67–93`：ABBA/fABBA 调各自 C++ encode/decode；DeepZip 从 portable 模型 load 后 compress/decompress；DZip 直接 load/create native network 后 compress/decompress。
- `Compression_Rewrite/ReWrite/deepzip/src/deepzip.cpp:153–192`：64 字符 uniform bootstrap 后实际调用 `Model::predict`，再生成累计频率并写/读 arithmetic；不是全部使用 uniform 编码。`src/model.cpp` 实现 embedding、GRU/LSTM、dense、batchnorm/activation 的机器码执行。`src/deepzip.cpp:240–244` 将模型完整序列化写帧与 ledger。
- `Compression_Rewrite/ReWrite/dzip/src/codec.cpp:143–164`：前 64 个符号 uniform，后续 Network::predict，combined 每 128 个 predicted symbols 调 adapt/Network::train；`src/nn.cpp:393–464` 实现 seed-native graph/initial weights，:424–425 明确初始化与 TF 的 initializer 不同。`:501` predict、`:521` train 均原生。
- `adapters/completed_rewrites/native/binding.cpp:63,81` 当前 DZip 在未给 model path 时调用 `Network::create`；`registry/codecs/dzip.json` 仅允许 `NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET`；`registry/onboarding/dzip.json:893` 明确 untrained native 模型和不作训练质量声明。原 `Compression_Rewrite/Source/dzip/upstream/encode-decode/compressor.py:96–97` 创建上游图后 `PRNN.load_weights(args.model_weights_file)`，当前默认行为并非这个训练模型实验。
- 当前 build driver `tools/build_completed_rewrite.py:99–102` 明确 `DEEPZIP_WITH_HDF5/CUDA=OFF`、`DZIP_WITH_HDF5/CUDA=OFF`。这不使 CPU core 非原生，但这些 deployed builds 不具备矩阵中的 HDF5/CUDA 完整能力。
- `registry/onboarding/deepzip.json:205` 的当前范围是 CPU、四词表 0..3，17 固定模型，无 byte remapping、CUDA、HDF5。`Compression_Rewrite/Source/deepzip/MODEL_MANIFEST.yaml:4–13` 的历史官方 xor20 checkpoint 是两个符号，当前模型的四词表 oracle fixture 不是该训练 checkpoint。
- 归档内 `Source/deepzip/golden/locked/model_inventory.json` 记录的 17 个构造命令均调用 `model_oracle.py --model-name <name>`，未传 `--checkpoint`；`Source/deepzip/run_model_inventory.py:24–25` 产生这些命令。`Source/deepzip/model_oracle.py:84–94,117–118` 固定 TF/NumPy seed 后直接构造模型，仅在显式 checkpoint 参数存在时 load_weights，否则把刚初始化的权重保存成 HDF5。17 个 deployed portable SHA-256 全匹配这些记录。因此部署模型确实来自原 Keras 架构且推理重写受检，但本身是**未训练权重**；它们的压缩率不能用于声称官方训练后的 DeepZip 效果。
- `Compression_Rewrite/INTEGRATION.md:3–9` 明确：Source 不是完整 oracle 快照、历史大模型/数组/二进制删除、旧 validation/release 不存在，历史 FULL_PARITY 不能等同当前框架接入资格。机器归档路径是 `docs/rewrite_cleanup/20261006-integration/historical_metadata.tar.gz`，本次只读取其报告及可重构概率参考，未恢复/重签旧资格。

## 现有验证方式的缺口

`tools/build_completed_rewrite.py` 不传 `ABBA_SOURCE_ROOT/FABBA_SOURCE_ROOT`，vendor CMakeLists ABBA:120、fABBA:75 只有这些变量设置时才添加 golden/differential/capability tests。当前两个 release 的 generated `standalone/CTestTestfile.cmake` 仅有 unit、standalone preflight、C header smoke；加上 binding qualification 并不执行源差分。本审计单独补跑了相应 differential/capability；不能拿现有 qualification 的 PASS 自动推论源算法一致。

`tools/verify_completed_rewrite_integration.py` 主要核查 REWRITE_DONE 文本、当前源码/构建/资格 hash 和 benchmark 五层产物闭合，没有重新运行原始 source oracle，也不检验 FULL_PARITY 能力矩阵的完整性。原生/重写判定必须加上实际 source/变体语义证据，而 benchmark correctness roundtrip（ABBA/fABBA 本就无通用 error bound）只能证明所测 case 的框架集成。

## 可重复命令

在 `/home/fzg/PycharmProjects/TSDataCompressBenchMark`：

```bash
c++ -std=c++11 -O2 -fno-fast-math -ffp-contract=off \
  -I /home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/nla-group_ABBA/src \
  Compression_Rewrite/ReWrite/abba/tests/oracle/ckmeans_oracle_cli.cpp \
  /home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/nla-group_ABBA/src/{Ckmeans.1d.dp,dynamic_prog,fill_SMAWK,fill_log_linear,fill_quadratic,select_levels}.cpp \
  -o /tmp/tscb-completed-audit-20261011/ckmeans_source_oracle
python Compression_Rewrite/ReWrite/abba/tests/cross_decode/run_differential.py \
  --cpp-cli build/adapters/abba/release/cmake/standalone/abba_cli \
  --oracle Compression_Rewrite/ReWrite/abba/tests/oracle/abba_oracle.py \
  --ckmeans-cli /tmp/tscb-completed-audit-20261011/ckmeans_source_oracle \
  --vectors Compression_Rewrite/ReWrite/abba/tests/golden/abba_vectors.json
python Compression_Rewrite/ReWrite/abba/tests/capability/run_capability_validation.py \
  --cpp-cli build/adapters/abba/release/cmake/standalone/abba_cli \
  --source-root /home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/nla-group_ABBA
python Compression_Rewrite/ReWrite/fabba/tests/cross_decode/run_differential.py \
  --cpp-cli build/adapters/fabba/release/cmake/standalone/fabba_cli \
  --oracle Compression_Rewrite/ReWrite/fabba/tests/oracle/fabba_oracle.py \
  --vectors Compression_Rewrite/ReWrite/fabba/tests/golden/fabba_vectors.json
python Compression_Rewrite/ReWrite/fabba/tests/capability/run_capability_validation.py \
  --cpp-cli build/adapters/fabba/release/cmake/standalone/fabba_cli \
  --source-root /home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/nla-group_fABBA
build/adapters/abba/release/cmake/binding_qualification ''
build/adapters/fabba/release/cmake/binding_qualification ''
build/adapters/deepzip/release/cmake/binding_qualification \
  /home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/completed_rewrites/vendor/deepzip/tests/fixtures/biGRU.dzm
build/adapters/dzip/release/cmake/binding_qualification ''
```

Python 默认 base Anaconda 的 ctypes 加载 DZip 曾因其 libstdc++ 缺 `GLIBCXX_3.4.30` 失败；本次直接 ABI 双 profile 复跑使用 `/usr/bin/python3` 成功。这是调用环境的 native ABI 依赖问题，不是源算法失败；不要在未匹配部署环境时将该异常写成 DZip 非原生。
