# 门禁验收报告独立静态复核 r1

独立复核对象是冻结 `gate_acceptance_review/acceptance_review_r1.json`（SHA `ad144a41fdd88a38101b6eee16f8057d00b25b9bde7bafc23f828810205699cc`），规范 authority 是完整当前 v3.0 文档（6100 行、SHA `5d14f905261c5f6c4935a0015c0b93768f24615e2e87b7df187358b7767e95a2`）。本复核只判断验收报告的分母、逻辑身份、能力分类、证据语义与资格边界；不据静态阅读重签数值/格式/API/源码执行符合性。

20 项独立检查全部 PASS，保留一项非阻断措辞澄清。没有发现入口/门禁漏计、重复计数、required 降级、捏造编解码失败，或用有限 current 测试授完整 N/G/CAP/FORMAL 的情况。

- 对照真实 `registry/algorithm_scope.json`、已冻结 active33 plan、原 ledger 与路线文档，33 个唯一活动入口完整对应：11 个 SOURCE_REWRITE × 8 个 G0–G6/CAP-GATE ＋ 22 个 NATIVE × 6 个 N0–N5 = 220 个唯一非空行。独立重算 3 PASS / 32 FAIL / 185 UNKNOWN。
- 三个 PASS 确为 G0：当前包自有逻辑 ID 分别为 `abba/abba-canonical-cpp`、`fabba/fabba-canonical-cpp`、`deepzip/deepzip-cpp`，均 P2；source repository/完整 commit 已明确。ABBA 的 CKmeans 已有 C++ dependency 与整条 Python pipeline 分开，fABBA 重复 compression stage、DeepZip_RNN_Predictor 重复 P0 stage 没有增算算法。历史 G1–G6、REWRITE_DONE、FULL_PARITY 没有自动迁移。
- 32 FAIL 均有明确 `ACCEPTANCE_*` 与未满足/NOT_TESTED 子项；每行的 codec execution/roundtrip failure 均 false。DeepZip 当前实测 CDF 比较差异另以 `FAIL_SCOPED_SOURCE_COMPARISON` 记录；G3/G6/CAP 指向同一个差分证据，不是三个独立编解码失败。
- 四份原 NATIVE_CAPABILITY_MATRIX 的 51 个 capability ID、分类和历史 validation 全集对照一致；42 个 REQUIRED 保留（ABBA2、fABBA2、DeepZip24、DZip14）。DZip 的旧 `REFERENCE_ONLY` 原样保留且被明确标为尚需合法四态新审阅，没有静默改成 N/A。完整范围 NOT_TESTED 字段不等于撤销历史有限 PASS。
- 四层逻辑矩阵原 SHA 保持：SourceCapabilityMatrix/StandalonePortMatrix 各 33 行均 UNKNOWN，BenchProfileMatrix/PipelineCoverageMatrix 各 41 唯一案例仅 SCOPED_PASS，performance claim=false。没有反向扩充 codec 原生域或消除上游 required。
- DeepZip 原始小 JSON 的全量计数与报告一致：12/12 概率满足原3e-5，最大误差1.4901161193847656e-08；source实际4CudnnRNN GPU节点；同一source概率的15CDF整数转换EXACT；独立预测完整CDF仅1/15不一致，第三context total源10000004/native10000003。r2全部命令exit0，r1缺CUPTI的abort(-6)保留；不授bitstream/fullpipeline/CAP。
- build v5 与 FORMAL 以冻结时 pending 单列，G1/N1 无PASS；N5 独立消费交付不以 FORMAL 为前置条件。24份小文档/JSON输入的SHA和size均与冻结引用相符。

唯一澄清：DeepZip G5 的通用 finding 写“Required source/native GPU predictors ... are not executed ...”。该行的 id 是完整 required 集合，完整 G5=FAIL 的结论正确；但“not executed”易被误读为 source GPU 全未执行，同报告 G3/外部块已正确记录有限 biGRU GPU 实测。请只在新 supplement 精确说明：**完整 required source/native 集合尚未完成；source biGRU/alphabet4/三contexts的4CuDNN实际执行及有限概率/CDF转换PASS保留，native GPU/其余模型/完整pipeline未闭合。** 不修改冻结报告、不撤回有限PASS、不改变G5 FAIL。父任务已接受这一澄清。

独立检查器首次把原保留状态 `SOURCE_PROCESS_ABORT_MINUS6` 误以为应含字面 `-6`，产生一个 checker-label 假阴性。初次检查器和报告单独保留为 `*-initial*`；修正的是标签谓词，原结果/输入/门禁都没变。最终20检查全部PASS，不把检查器标签问题记成源/codec失败。

本轮没有执行 codec/model/training/build/performance，没有重哈希模型、二进制或档案，没有改原报告、生产或矩阵。新输出 `gate-acceptance-independent-review-r1.json`、本说明和小索引仅签本静态复核范围，不签完整 N/G/CAP/FULL_PARITY/REWRITE_DONE/FORMAL。
