# 独立逻辑对象与 P2 列/块管线 v1（2026-10-10）

实现位置：`src/tscompbench/pipelines/`。本接口不修改既有 canonical wire、DatasetID、历史记录或源算法原生能力域；RecipeID 是现有编解码器的有序组合身份，不新增 AlgorithmID/算法登记。

## 公开接口

```python
from tscompbench.pipelines import (
    ChildSpec, LogicalObjectSchema, LogicalObject, PipelineRecipe,
    encode_object, decode_object, decode_in_fresh_process, validate_restored_object,
)

schema = LogicalObjectSchema.from_document(schema_document)
original = LogicalObject(schema, ordered_value_arrays, timestamp_array, validity_arrays)
recipe = PipelineRecipe(
    value_children={name: ChildSpec(existing_codec_key, params) for name in original.values},
    timestamp_child=ChildSpec("lz4-frame", {}),
    mask_child=ChildSpec("zstd-frame", {}),
    block_size=8, tail_policy="RAW_TAIL", loss_contract={"kind": "LOSSLESS"},
)
artifact = encode_object(project_root, original, recipe)
# 仅将 artifact.stream 保存到文件；其他编码状态不属于 decoder 输入。
restored, spawn_evidence = decode_in_fresh_process(project_root, artifact.stream)
validation = validate_restored_object(original, restored, loss_contract=recipe.loss_contract)
```

完整可执行例子：`examples/pipelines/standalone_roundtrip.py`。运行：

```bash
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  examples/pipelines/standalone_roundtrip.py \
  --output-directory /tmp/tscb-p2-roundtrip-20261010 --n 17
```

输出为真正持久化的 `standalone.p2` 和 `diagnostic.json`。示例使用 NeaTS 的既有精确扩宽恢复路径处理 i16、ALP 原生 f64、LZ4 TIMESTAMP、Zstd bitmap；没有把 int codec 改名为全类型原生能力。诊断 elapsed 包含控制面和 spawn，明确不作为 FORMAL codec 时间。

## 独立语义与有序恢复

`LogicalObjectSchema` 保存显式有序的值缓冲名称、canonical dtype、完整 shape、每个 axis 名称、任意合法 `time_axis`、unit、entity、feature；T 单独保存 present/dtype/unit/epoch 和 `SHARED_TIME_AXIS` pairing。每个值缓冲可以有不同 dtype 和 ND shape，但其时间轴长度必须一致。异步、ragged 和原始 SYSTEM 文件工作负载属于未支持合同。

`LogicalObject` 包含 schema、按 schema 排列的值数组、可选公共 T、可选逐缓冲同形 boolean validity。`RestoredObject` 重新物化这全部内容；数组独立拥有内存，返回后设为只读。验证同时比较完整 schema、validity、准确 T 和选定值恢复合同，不能只借用外部 decode descriptor 给输出补标签。

固定 stage 顺序为 `TIME_AXIS_TO_FIRST → LEXICOGRAPHIC_COLUMNS → INDEPENDENT_BLOCKS → TAIL_ENCODE`。使用 `moveaxis` 恢复任意时间轴；非时间轴按 C 顺序列化。每列实际执行所有完整块；不足 B 的末块使用 frozen `RAW_TAIL` 或 `COMPRESS_TAIL`。T 按同一 B/start/true count 分段，bitmap 独立保存 LSB0 位序。没有把短尾 padding 后伪装成完整源域输入，也没有隐藏 raw fallback。N=0保留有意义的 schema，无假数据 children。

同 T 子块会实际计算 duplicate、negative delta、out-of-order，并保存兼容计划；公共解码器重新协商 plan、核对真路径和 inverse，再对恢复 T 复核这些属性。T 的 unit/epoch、V 的 unit 和 bitmap 的 BOOLEAN 都进入付费恢复上下文。

`ChildSpec` 与 `PipelineRecipe` 使用不可变 canonical bytes snapshot；caller 传入的 dict 和 getter 的 copy 不能在运行中重写 RecipeID。原逻辑值顺序来自 schema array，JSON map 键排序不会重排原对象。

## 空值、内容身份与误差

BITWISE保留所有原始值底层字节、T和bitmap，包括无效槽载荷。SEMANTIC只承诺有效值、dtype/shape、validity、T；无效载荷编码前规范化为零。相应 content identity 和 CanonicalRawBits 使用相同语义，另外保存原始底层字节 hash。validity 是否存在也进入内容 hash；NaN 从不自动形成 null。

LOSSLESS 时 decoder 自己复核保存的原始逻辑内容身份。ABS 合同必须是 finite nonnegative decimal string；T/mask 始终 lossless，值 child 只能是 LOSSLESS 或真实 ERROR_BOUNDED_LOSSY，actual ABS budget 不超过对象合同。最终 validator 对全体原始域值做 strict bound gate，同时 BITWISE null byte gate。i64/u64 使用既有精确整数/有理 bound comparator，匹配的非有限值不稀释有限指标，非有限失配无条件失败。

ND ABS 报告将真实 `time_axis` 映射为独立的 lexicographic logical columns，输出 buffer、非时间轴坐标与 unit 映射。每列调用现有时序质量剖面：time-weighted RMSE、derivative RMSE、lag1 ACF；无隐式跨列权重。乱序/重复 T、空值、非有限样本或不足长度返回 N/A 与具体原因。时序剖面不是额外误差门禁。当前不允许将整数原 schema 的输出隐式舍入回整数；若有损子路径输出不同 dtype，则明确拒绝，待新合同显式描述 reconstructed dtype。

## 实际格式、依赖与账本

frame 为 `<8sIQ`：magic `TSCBP2V1`、canonical JSON header byte length、child payload byte length。header 保存 schema、原始内容/hash/RawBits、完整 recipe/RecipeID、validity presence 和每个真实 node。node 保存角色、owner/column/start/count/dtype、offset/length/SHA-256、RAW/CODEC、实际公共 manifest/AlgorithmID、归一化参数、DecodeContext、实际兼容计划和 child accounting。decoder 拒绝未知字段、缺失/重复/重排 child、截断、overlap、隐藏 raw、实际 codec/参数与 recipe 不同、恢复单位不同、编解码路径或 ledger 重标。

FinalBits = `8 * len(finalized artifact.stream)`；PhysicalPayloadBits 包含每个子算法实际最终流的模型、header、尾部等全部物理字节；MetadataBits 包含 outer frame 和 canonical JSON。两者精确闭合，不另猜 child 成分或重复记总数。子账本仍逐项披露现有 model/header/padding等责任。当前格式直接保存公共 child 元信息，会造成较大 metadata 成本；报告使用真实成本，不省略它。

清洁解码使用 multiprocessing `spawn`，进程参数仅为 project root、保存的 artifact bytes、可选允许使用的公共 child key 集合。原值和 encoder session 不传入。缺少实际使用的 child key 失败；结果跨 IPC 为 owned copy；退出后重新确认只读标志。cold spawn evidence 与正确性 oracle 分离。

外部 side information 尚无 artifact bundle 合同：发现非零 external_side_information_bits 时 fail-closed；不会填零或凭编码进程缓存恢复。流内的 NeaTS model/ALP metadata 属于已计费 child stream。此限制以及 arbitrary channel regroup、联合MTS、异步/ragged、索引/随机访问/查询/P3支持均保留为未完成资格。

## Schema 与验收范围

`schemas/pipelines/v1/` 四份独立 Draft 2020-12 schema：logical-object-schema、pipeline-recipe、pipeline-ledger、pipeline-artifact-header。JSON Schema检查字段/版本/基本域；runtime独立检查 axis 与 shape 的关系、同步 time count、slot/recipe/path身份、实际位账本及全部恢复依赖。实际三类生成对象（BITWISE mixed+T+mask、SEMANTIC mixed+T+mask、N=0）已通过12份 schema 正例，额外字段/版本/必填字段的36份反例被拒绝。

针对性 tests 覆盖 N=0/1/2/B−1/B/B＋1/2B±1、time_axis=1的[2,N,3]、混合dtype、两种null合同、raw/compressed bitmap、完整T＋V、真实NeaTS/ALP/zfp、严格原域ABS、干净spawn、缺公共child、truncated frame、树/参数/axis/inverse/accounting篡改。单次小样本正确性或pytest通过不代表 §17 的CPU/V3.2组验收全部完成。
