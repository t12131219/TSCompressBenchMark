# 独立门禁验收审阅 r1（2026-10-11）

本审阅完整对应 33 个活动入口、220 条适用门禁：22 个原生入口 N0–N5、11 个核心重写入口 G0–G6/CAP-GATE。结果为 **3 PASS、32 FAIL、185 UNKNOWN**。这不是重复把 220 项全部填 UNKNOWN；[机器报告](acceptance_review_r1.json) 的每条门禁记录已满足的合同／证据子项、明确未满足的子项及待补独立复核，所有输入均绑定当前 SHA。生成器只读取小型合同和 JSON 回执，未加载生产模块、重建、执行 codec、模型、训练或性能，也没有重哈希模型／binary／压缩档案。

3 个 PASS 仅授 ABBA、fABBA、DeepZip 的 **G0 资产身份／去重／对象门禁**：当前包自有稳定逻辑 AlgorithmID/ImplementationID、P2 分类、source 映射与重复 stage 决策已逐字检查。其历史 `PORT_MANIFEST` 中的 G1–G6、FULL_PARITY、REWRITE_DONE 不自动迁移。本报告不授任何完整 N/G/CAP 验收或独立发布。

**FAIL 表示完整验收条件未满足，不冒称未执行的压缩运行失败。** 32 是门禁行数量，绝不是 32 个算法编解码失败；报告 `recorded_codec_roundtrip_failure_count=0`。标准 §3 明确：任何 REQUIRED_PARITY 为 MISSING、FAIL 或 NOT_TESTED 时 CAP-GATE 失败；G6 又以完整 CAP 闭合为必需条件。四份既有矩阵原有 42 个 REQUIRED 项及历史 PASS 全部保留，新报告逐项说明当前完整范围尚未核验的子项。其余 7 个最小核心入口在本次已审输入中没有已接受的完整四态能力审阅／闭环，不因 Benchmark 单 profile 通过补签完整重写。11 个 CAP/G6 共 22 条据此 FAIL；此外 ABBA/fABBA/DeepZip/DZip 的完整 G3、DeepZip/DZip 的完整 G4、fABBA/DeepZip/DZip 的完整 G5，以及 DZip 的 G2 分别按确切功能/API/优化/分类缺口记录，合计 32 条。发布合同及独立消费证据的待复核缺口也逐项保留；DeepZip 的真实限定 CDF 差异另明确记录。

DZip 的历史 `REFERENCE_ONLY` 未改写或强行转为 `NOT_APPLICABLE`；它不属于标准合法四态，需要新证据审阅。原生路线允许事前冻结的当前 profile，但完整源能力与本次目标须分别保存。N0 的完整 source capability 调查、N1 的实际闭包、N2 合同与计划、N3/N4 独立 API/源对照映射、N5 独立消费交付仍为具名待复核子项；UNKNOWN 不能被当成通过。

## 已核实的有限证据与当前变化

- 当前 selected source tree 的 exact-set/逐字节回执为 33/33 PASS；源代码选集匹配不等同实际编译／生成／链接／运行闭包、源语义或完整门禁。
- 当前 `active33-r2` 为 41 个 SCOPED_PASS，独立恢复、边界／preflight、完整物理成本保持其原案例范围；ABBA/fABBA/DeepZip/DZip 当前 8 个 release/sanitizer profile 有 32 个非空 CTest。这些子项在每入口 N3/G3/G4 中保留，没有强行抵消完整 required 覆盖缺口。
- 新 r3 外部 authority 已恢复精确 Dipperstein lzss/bitfile/optlist Git 树及 gitlink，选定 vendor 字节匹配；Elf 正确 VLDB2023 完整 pinned Git 树也已核实。此前仅在本地未找到 authority 的快照保留，其当时限制不再冒称当前缺口。
- 新旧 oracle 恢复取得全部 71 个原 SHA/size 精确包（1,778,340,023 bytes），DeepZip TF1.8 和 DZip TF1.14 CPU/GPU 独立环境 import/device/runtime 探针 PASS。8170 base 代码／数据文件、DZip 3073 CPU 和 2934 GPU Python/ELF 成员 MATCH。普通 sandbox 的旧 `nvidia-smi exit9` 保留，真实 RTX2070 driver/GPU 可访问证据不被否认；环境探针不等于训练／模型／codec parity。
- **新鲜 DeepZip 限定差分**已经完成，引用 `learned_source_oracle_r1/summary-r2.json`：当前四符号 biGRU 固定权重 source exporter 重新导出 EXACT；3 个上下文、12 个概率在事前冻结的 3e-5 绝对容差内 PASS（maxabs 1.4901161193847656e-08）；source step_stats 确认 4 个 GPU CudnnRNN 节点；相同 source 概率的 15 个 CDF 整数转换 EXACT。独立 source/native 预测的完整 CDF **1/15 不同**，`arange(64)%4` 最终 total 为 source 10000004/native 10000003。报告原样记录这个执行比较结果，不以概率容差签 CDF／源码流一致性。r2 三命令 exit0，差异不是 crash；r1 附加 FULL_TRACE 因缺 CUPTI abort(-6) 的失败证据另保留。
- DZip 本次未执行源模型、训练或 codec。当前公开 native-seeded untrained profile 与原 TF initializer／训练后 PRNN 不等同；独立 C ABI 的 loaded-weight 诊断分支存在，但 registry 未开放对应模型参数，不能拿它替换当前参数身份。

## 后续证据与独立交付

本冻结报告记录 build trace **v5 仍 pending**，不得用旧 v1 静态库存或 r1 两份成功构建样本补签完整 toolchain/link consumption 闭包。DeepZip 有限 fixed-weight 诊断已完成，完整必需 source/native GPU、trained checkpoint、codec／真实数据差分与保留 CDF 差异仍未闭合。父任务另行完成 FORMAL 新协议结果及 aux/reference 成本；这些证据不能自动授源语义、完整 CAP 或独立发布。

**N5 不以 FORMAL 为前置条件。** 每个原生入口需独立消费者只用已声明源码/public API/driver/依赖/恢复资产完成冷构建、测试和恢复，并核验可重放 patch、产物、SBOM、许可及报告索引；已有 Bench 接入不可替代。G6 同样需当前独立 release，以及适用 correctness/portability/security/performance/license/docs/reproducibility、dataset report 与 CAP 闭合。

主能力矩阵、旧 gate_audit、旧 220 UNKNOWN ledger、历史 expected/report 与原 REQUIRED 分类均未修改。新结果到来应创建 **新 supplement**，引用本冻结报告 SHA，逐门禁补充身份与范围；不要修改此报告或抹除 CDF 差异。

## 33 入口结果

| 入口 | 路线 | 逐门禁当前完整验收状态 |
| --- | --- | --- |
| `abba` | SOURCE_REWRITE | G0=PASS；G1=UNKNOWN；G2=UNKNOWN；G3=FAIL；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `alp` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `alp-rd` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `brotli-stream` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `chimp` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `chimp128` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `deepzip` | SOURCE_REWRITE | G0=PASS；G1=UNKNOWN；G2=UNKNOWN；G3=FAIL；G4=FAIL；G5=FAIL；G6=FAIL；CAP-GATE=FAIL |
| `deflate-zlib` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `dzip` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=FAIL；G3=FAIL；G4=FAIL；G5=FAIL；G6=FAIL；CAP-GATE=FAIL |
| `elf` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `elf-plus` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `elf-star` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `fabba` | SOURCE_REWRITE | G0=PASS；G1=UNKNOWN；G2=UNKNOWN；G3=FAIL；G4=UNKNOWN；G5=FAIL；G6=FAIL；CAP-GATE=FAIL |
| `fse` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `huff0` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `leats-lossless-i64` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `lz4-frame` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `lzss-dipperstein-c` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `lzss-raw` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `neats-lossless-i64` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `self-star` | SOURCE_REWRITE | G0=UNKNOWN；G1=UNKNOWN；G2=UNKNOWN；G3=UNKNOWN；G4=UNKNOWN；G5=UNKNOWN；G6=FAIL；CAP-GATE=FAIL |
| `serf-qt` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `serf-xor` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `simdcomp-u32` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `snappy-raw` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `sprintz-delta` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `sprintz-delta-u8` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `sprintz-fire` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `sprintz-fire-huff0` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `sprintz-fire-u8` | NATIVE_PORT | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `xz-stream` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `zfp-accuracy-1d` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |
| `zstd-frame` | NATIVE_REUSE | N0=UNKNOWN；N1=UNKNOWN；N2=UNKNOWN；N3=UNKNOWN；N4=UNKNOWN；N5=UNKNOWN |

复核驱动：[build_review.py](build_review.py)。输入及报告索引：[file_index.json](file_index.json)。驱动拒绝覆盖冻结结果，其内部检查入口／门禁数量、唯一已授 G0、当前 finite receipt 状态及输入前后 SHA；没有新增 codec 测试。[静态完整性核对](static_integrity_check_r1.json)由 [check_review.py](check_review.py)检查 33/220 唯一非空门禁、标准四态、三个 G0 当前逻辑 ID、四份原能力矩阵逐 ID/分类与 42 个 required 保留，以及小型输入回执 SHA。该检查仅证明报告完整性，不签源语义或完整验收。
