# V3.2 当前活动入口的 stage、方法等价与共同组映射

本表只连接现有 33 个入口的声明角色与冻结 GroupSpec；不授予资格或正式完成。
未入选组的入口保留待冻结条件，alias、参数、build/ISA 和 child 调用不新增方法分母。

台账身份：`v2:active-stage-role-ledger-v32:sha256:1df496a8d93f0b57aba5ce35cc402bc92178b248c757b596b77bc1f2868ad1c4`。

当前 CSV 166 条（SHA `bd0ad832d0a97d939e04ef3eb44039bceb89439336864a1821eeee667c1304a2`）；
旧 scope 163 条（清单 SHA `536dda0cdb068da2014b1a0638d6cca7e7f1cb92a750d4528ead272d5e1b665c`）。
163 条旧记录保留明确名称/来源/变体映射，3 条新记录不获准入；历史退出关系与合并来源保留在 JSON。
使用清单 SHA + 记录 ID 连接命名空间，不用重编号后的裸 V/T ID 解释退出决定。

33 个活动 key 对应 28 条候选记录；
选定 10 组涉及 28 个入口。候选记录、不同方法、实现入口与完成组是不同口径。
长期多数候选的适用方法/角色分母仍未冻结，本表不声明长期多数集成完成。

| 入口 | 当前 / 旧候选 ID | stage 声明 | 方法等价类 / 状态 | 冻结组角色 |
|---|---|---|---|---|
| abba | V16/V19 | APPROXIMATE_REPRESENTATION, CODEBOOK_AND_RECONSTRUCTION_FRAME | abba | G-QUALITY:CORE |
| alp | V53/V68 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | alp | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| alp-rd | V54/V69 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | alp-rd | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| brotli-stream | V8/V8 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | brotli-stream | G-TIMESTAMP:CORE; G-STREAM-LL:CORE |
| chimp | V47/V62 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | chimp | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| chimp128 | V48/V63 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | chimp128 | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| deepzip | V68/V90 | MODEL_PROBABILITY, ENTROPY_CODING, MODEL_RECOVERY_FRAME | deepzip | G-BYTE-MODEL:CORE |
| deflate-zlib | V1/V1, V4/V4 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | deflate-zlib | G-TIMESTAMP:CORE; G-STREAM-LL:CORE |
| dzip | V69/V91 | MODEL_PROBABILITY, ENTROPY_CODING, MODEL_RECOVERY_FRAME | dzip | G-BYTE-MODEL:CORE |
| elf | V50/V65 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | elf | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| elf-plus | V51/V66 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | elf-plus | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| elf-star | V52/V67 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | elf-star | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| fabba | V17/V20 | APPROXIMATE_REPRESENTATION, CODEBOOK_AND_RECONSTRUCTION_FRAME | fabba | G-QUALITY:CORE |
| fse | V78/V120 | ENTROPY_BACKEND, COMPLETE_BYTE_FRAME | 共同任务未冻结 | 未入选定组，仍需适用资格 |
| huff0 | V77/V119 | ENTROPY_BACKEND, COMPLETE_BYTE_FRAME | 共同任务未冻结 | 未入选定组，仍需适用资格 |
| leats-lossless-i64 | V39/V100 | INTEGER_MODEL_AND_EXCEPTIONS, INDEXED_RECOVERY_FRAME | leats-lossless-i64, neats-related-query-implementations | G-INT-LL-I16:CORE; G-QUERY-LL-VARIANTS:CORE |
| lz4-frame | V5/V5 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | lz4-frame | G-BYTE-LL:CORE; G-FLOAT-LL-F64:REFERENCE; G-INT-LL-I16:REFERENCE; G-BYTE-MODEL:REFERENCE; G-TIMESTAMP:CORE; G-FLOAT-LL-F32:REFERENCE; G-STREAM-LL:CORE |
| lzss-dipperstein-c | V2/V2 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | lzss-family | G-TIMESTAMP:CORE |
| lzss-raw | V2/V2 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | lzss-family | G-TIMESTAMP:CORE |
| neats-lossless-i64 | V39/V100 | INTEGER_MODEL_AND_EXCEPTIONS, INDEXED_RECOVERY_FRAME | neats-lossless-i64, neats-related-query-implementations | G-INT-LL-I16:CORE; G-QUERY-LL-VARIANTS:CORE |
| self-star | V52/V67 | LOSSLESS_NUMERIC_VALUE_CODING, RECOVERY_FRAME | self-star | G-FLOAT-LL-F64:CORE; G-FLOAT-LL-F32:CORE |
| serf-qt | V65/V85 | BOUNDED_LOSSY_VALUE_CODING, RECOVERY_FRAME | serf-qt | G-FLOAT-ABS:CORE |
| serf-xor | V66/V86 | BOUNDED_LOSSY_VALUE_CODING, RECOVERY_FRAME | serf-xor | G-FLOAT-ABS:CORE |
| simdcomp-u32 | T37/T53 | UINT32_BITPACK_PRIMITIVE | 共同任务未冻结 | 未入选定组，仍需适用资格 |
| snappy-raw | V6/V6 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | snappy-raw | G-BYTE-LL:CORE; G-TIMESTAMP:CORE |
| sprintz-delta | V42/V55 | INTEGER_PREDICTION_RLE, INTEGER_FRAME | sprintz-delta | G-INT-LL-I16:CORE |
| sprintz-delta-u8 | V42/V55 | INTEGER_PREDICTION_RLE, INTEGER_FRAME | 共同任务未冻结 | 未入选定组，仍需适用资格 |
| sprintz-fire | V43/V56 | INTEGER_PREDICTION_RLE, INTEGER_FRAME | sprintz-fire | G-INT-LL-I16:CORE |
| sprintz-fire-huff0 | V43/V56, V77/V119 | FIRE_PREDICTION_RLE, HUFF0_ENTROPY, PIPELINE_FRAME | sprintz-fire-huff0 | G-INT-LL-I16:CORE |
| sprintz-fire-u8 | V43/V56 | INTEGER_PREDICTION_RLE, INTEGER_FRAME | 共同任务未冻结 | 未入选定组，仍需适用资格 |
| xz-stream | V9/V9 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | xz-stream | G-TIMESTAMP:CORE; G-STREAM-LL:CORE |
| zfp-accuracy-1d | V67/V87 | BOUNDED_LOSSY_VALUE_CODING, RECOVERY_FRAME | zfp-accuracy-1d | G-FLOAT-ABS:CORE |
| zstd-frame | V7/V7 | BYTE_BACKEND, COMPLETE_BYTE_FRAME | zstd-frame | G-BYTE-LL:CORE; G-FLOAT-LL-F64:REFERENCE; G-INT-LL-I16:REFERENCE; G-BYTE-MODEL:REFERENCE; G-TIMESTAMP:CORE; G-FLOAT-LL-F32:REFERENCE; G-STREAM-LL:CORE |

stage 是 manifest/规格支持的角色，不是从时间差推导出的实测子阶段。
共享 family/source 不自动等价；ALP/ALP-RD、ABBA/fABBA、NeaTS/LeaTS、Sprintz predictor/entropy
按实际 GroupSpec 保留不同类。u8 Sprintz 入口不增加 i16 任务的方法数量。两个 LZSS 实现
遵循各任务 GroupSpec 冻结的方法等价规则，不自动以两个入口计为两个方法；
未入选共同任务的快照不声明它们已有冻结的共同等价关系。

默认选定 bundle 的 revision 与 SHA 均保留在 JSON；新冻结版本需显式 --bundles 并生成新台账。
该工具不读取本地 build 成败推断活动，也不把既有历史 parity 转成 fresh PASS。
