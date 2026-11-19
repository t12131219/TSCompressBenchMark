# pcodec（selection 11）：原生入口与 M0 定向用例

本合同绑定 `pcodec-native` 的 `unique-v1` 源码（归档 SHA-256
`a62b4ca351fd6975b7eaf06df6d49b6c6175b541a8cea2df7af9ce09dcc3120d`）。
先读取 Unique `fix_ReWrite/pcodec-native/FUNCTIONAL_REPORT.md`：与冻结包内同名文件
SHA-256 一致；[发布验证](../../third_party/provenance/pcodec-native/unique-validation.json)
也记录 `test_core`、`test_native_ext`、`native_negative`、`pcodec-source-c-consumer` 历史通过。
不重跑整套历史矩阵，也不以历史通过代替当前测试。旧 README/能力字典中的“默认关闭 Source、
不支持 f16”不适用于当前默认编译：可执行依据为冻结 CMake、公开头文件、`src/pcodec.c`、
`src/native_ext.inc` 和 `source-backend/src/lib.rs`。CUDA 编译字段不构成 pcodec 的 GPU 证据。

| 原生组 | 实际入口与身份 | 本轮绑定与判定 |
|---|---|---|
| `source-auto` | `pc_compress` → `pcs_compress`；`pc_decompress_bounded` → `pcs_decompress`。插件 `pcodec-source-auto`。 | V-only；11 种原生整数/浮点类型的位级 fixture（含 binary16 特殊位），以及空 f64 和真实交通 f64 窗口；原生 payload 差分与独立恢复。 |
| `c-native-auto` | `pc_compress_native` 是明确的 C NativeAuto **编码**；同一完整构建下的 `pc_decompress_bounded` 仍是 Rust Source **解码**。插件 `pcodec-c-native-auto`，不是纯 C 编解码。 | 与 SourceAuto 同一输入、配置和验证，唯 f16 必须拒绝，分别在直接 C 入口及 worker 实测。两个插件格式 ID 不同，不互认 bench envelope；不据此断言裸流不兼容。 |
| `source-pages` | `pcs_chunk_*`、`pcs_wrapped_*`、`pcs_read`；`pcs_buffer_free(data,size)`。 | 773 行真实 f64，以 `[513,260]` 分页、每次最多读 256 个值。使用共享元数据反序选页，在新进程从独立页恢复；原生 `max_values` **按页**限制。 |
| `native-pages` | `pcn_chunk_*`、`pcn_wrapped_*`、`pcn_read`；`pcn_buffer_free(data,size)`。 | 相同数据与页切分，各自使用 C NativeAuto；原生 `max_values` **按 decoder 会话累计**。同一份当前数据上恰好编码一致，不证明选模等价或一般兼容性。 |
| `intmult` | 完整构建的 `pc_compress_intmult` 是 **Source TryIntMult**，不是强制只用 IntMult。 | u32 精确公因子输入检查 emitted chunk 的 IntMult；高熵反例检查体积保障退回 Classic；u64 基数 `9007199254740993` 从 chunk 元数据验证无 double 转换。拒绝整数零基数、越位宽和浮点输入；本轮不声明 reduced C-only 编码路线。 |

### 执行域、恢复及成本

- 两个插件绑定同一冻结 `pcodec_c` 库。Release 配置使用 `PC_SOURCE_BACKEND=ON` 和
  `PC_NATIVE=ON`；Rust 组件从包内 vendor 用 `cargo build --offline --locked` 构建。
  C 路线的 `-march=native` 限于同一支持环境，不从编译开关推断使用了某个 SIMD 分支。
  两种批入口单调用串行。未实测的 Auto 内部选择和 fallback 以 `null` 输出，不用名字推断。
- 两个插件只收一个连续、little-endian、无 validity 的 rank-1 V 列；输入上限 64 MiB、
  schema 上限 64 KiB。方法选项为 `{}`，使用 `pc_default_config()`（level 8、
  mode/delta Auto、chunk 262144）。不转换类型或浮点位。新进程只拿封装产物与已绑定模块；
  恢复预算先按封装 count 限制 `pc_decompress_bounded`，再验证 actual count。
  这是逻辑/传输限制，不是总 scratch、进程 RSS 或时间合同。大块上限尚未进行本轮压力确认。
- 批格式计费拆为裸 `pc_*` payload、32 字节封装、逐字节保留的 schema。25 份成功帧全部留存；
  临时原始和恢复副本清理。SourceAuto 的编码产物与同库 `pcs_compress` 直调逐字节一致，两种路线的产物
  均另由 `pcs_decompress` 直调恢复，并由新 worker 验证原始位模式与 schema。过小输出上限、缺 payload、
  截断、尾随和跨插件封装错配等反例均被拒绝。
- 页编码需先持有并对整 chunk 建立共享统计；页解码需先提供完整压缩页，再从本地状态
  增量输出，尾批必须 drain。缺共享元数据、非法读取容量、尚未结束时开始下一页、
  超配额和尾部多余字节均有直接检查。独立页恢复的计费必须包含类型、两页长度/计数、
  边界与共享 meta。本开发探针以实际 sidecar JSON 字节量记录依赖，不声明正式容器格式。
  留存两份元数据、四份页和两个 sidecar，逆序在新进程逐页恢复。两种路线的截短页均在 drain 时
  报错，不能把成功启动或取得部分输出当作页已完成。`pcn` 还实测覆盖调用者页缓冲后，已启动的
  decoder 仍逐位恢复。没有外部流式服务，也没有网络 push、逐值在线训练、任意点查询或随机访问延迟资格。

[用例绑定](../../configs/suites/dev_pcodec_v1/cases.json) 锁定 v2 来源及 `channel_0`
测试段首 773 个值（V 不带 T、不进行数值转换）；[定向验证器](../../tests/isolation/pcodec_control.py)
包含各 fixture、边界和原生状态检查。运行 `ctest --test-dir <build> -R tsbench.worker.pcodec.recovery --output-on-failure`。
输出 `pcodec-control.json` 绑定 worker、插件模块、原生库、源码归档、冻结窗口和验证器的身份。
两种批方法、两种分页和 IntMult 共绑定 **27 项必需检查**。独立复算核对留存帧的批头和 schema、恢复摘要、
分页 sidecar、元数据和页的字节账及实际拒绝状态；不重新加载 pcodec 解码。
仅两种批方法接入 worker；分页和 IntMult 是冻结源码的原生直调，不是新增 ABI 服务。
后续仍需正式计划中的适用域（含 Dict、Conv1、跨选项与多 chunk）、资源与留存合同，以及实现忠实性与测量对照。

### IntMult 的三份码流和四项检查

- 固定 `pc_compress_intmult` 的 level 8、无 delta、chunk 上限 262,144。两份 `u32` 输入同用基数 4093，
  确定性倍数产物实际编码为 IntMult，高熵产物为 Classic。该冻结实现对 `TryIntMult` 只提交 IntMult 候选，
  允许在保证尺寸的检查中退回 Classic；不是改用 Auto，也不是性能比较。
- `u64` 测试的基数为 `9007199254740993`（`2^53 + 1`）。复算直接从 chunk 元数据以整数读取 mode 与基数，
  不从报告反推，也不经浮点转换。只改写基数一位并更新产物摘要，验证器仍会因整数基数错配而拒绝。
- 三份裸 `.pco` 帧均由新进程仅凭码流和冻结库逐位恢复；完成包含读取末尾标记的零输出调用。离线验证
  独立解析 standalone v3 / wrapped v4.1 的元数据前缀并核对报告，不自行解码熵码流。
- 零基数、超出 `u32` 位宽的基数和 `f64` 输入分别实测返回 `PC_INVALID`；输出指针为空、长度清零。

### 后续统一批执行

`extended-v3` 已在一个冻结批执行中绑定 #11 的 `source-auto`（六项）及 `c-native-auto`（五项），并与其他五个操作组一起执行；见[统一批执行合同](linear-batch-execution.md)。25 个完整 pcodec 产物分别留存并在新进程按原始位恢复；验证两个编码入口的差分和 Rust Source 解码。C f16 在相同运行中由 ABI 与直接 C 入口拒绝，迁移审计实际从 SourceAuto 的 f16 产物重建拒绝输入并重跑，不引用旧探针的 PASS。分页与 TryIntMult 的前述证据独立，未被并入该批报告。

### 后续统一 wrapped 分页执行

`extended-v4` 已把 `source-pages` 和 `native-pages`（各六项义务）都接到同一主账本。每路线留存两页、共享 native 元数据和计费侧车；页逆序以独立进程和精确依赖恢复，控制与恢复的 ABI/NativeAuto/SourceAuto 区分不变。区别于先前定向探针，本次在通用提交上验证了分页缺依赖、不完整 drain、累计配额区分及独立迁移恢复；参见[主报告](../../results/m0-pcodec-wrapped-20261119-r2/batch-report.json)及[执行合同](linear-batch-execution.md)。不把按页 drain 算作输入流；该次冻结计划不含 IntMult；后续 `extended-v11` 独立执行了包含 IntMult 的完整候选子集，未将两次账本拼接。

### `extended-v11`：TryIntMult 接入统一执行

[执行政策](../../configs/suites/m3_first_batch_native_v2/pcodec-intmult-execution.json)复用四项冻结义务，新增三个成功槽和三个拒绝槽。
[原生驱动](../../plugins/codecs/pcodec/intmult_control.cpp)以十进制参数无损传入 `uint64_t` 基数，调用完整构建的
`pc_compress_intmult`。请求政策是 Source TryIntMult（level 8、NoOp delta、chunk 上限 262,144）；实际模式由独立
元数据读取器和 Source decoder 同时核对，不把请求参数当成实测模式。

| 冻结用例 | 请求基数 | 码流实际模式 | 裸 `.pco` 全部字节 |
|---|---:|---|---:|
| `multiples`：2,048 个 u32 | 4,093 | IntMult，基数 4,093 | 2,852 B |
| `high-entropy`：2,048 个 u32 | 4,093 | Classic，无基数 | 8,217 B |
| `wide-base`：513 个 u64 | 9,007,199,254,740,993 | IntMult，基数精确保留 | 639 B |

裸帧自身提供类型，成功槽的恢复进程只挂载该帧与锁定 ELF 闭包，不挂载原值、schema、模型或模式侧车。
`pcs_file_open` / `pcs_read` 执行位级恢复，最多每次读 256 个值，并实际完成消费末尾标记的零输出调用；这不是在线输入流。
零基数、超出 u32 的基数、f64 都由实际原生入口返回 `PC_INVALID`，输出为空指针且长度为 0，不产生帧。
三帧独立计费，合计 **11,708 B**，不把不同输入的产物大小当作算法性能对照。

[同次运行](../../results/m0-pcodec-intmult-unified-20261119-r1/report.json) `fffd6b54b5ce49618b161d937ca889f1` 的
[隔离恢复审计](../../results/m0-pcodec-intmult-unified-20261119-r1/restore.json)在不挂载原构建、配置与语料的条件下
重新执行三份帧的原生恢复和三项拒绝（拒绝输入按冻结合同重建为单个零）。[重封存控制](../../results/m0-pcodec-intmult-unified-20261119-r1/intmult-reseal.json)
拒绝将大基数低位抹除、删掉零输出末尾读取、伪造拒绝输出指针、让 decoder 看见原值。无正式资格或性能结论。

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --intmult
```
