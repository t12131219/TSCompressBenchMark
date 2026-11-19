# Titchy（selection 85）：批处理、原生 packet 流和索引访问

本轮只使用 `titchy-native` 的 `unique-v1`，归档 SHA-256
`e58fcb2d06b212d4b2d5e7ded20f8d5d02fc118ad5463bdfc72a299a2f69c62e`。
复用了 `Unique_Selected_Compression_Rewrite/fix_ReWrite/titchy-native/` 的 README、
原生运行工具和 `FUNCTIONAL_REPORT.md`；功能报告与冻结包内同名成员 SHA-256 一致。
[发布验证](../../third_party/provenance/titchy-native/unique-validation.json) 已记录
`stream_c`、`example` 在发布包和隔离环境通过，不把这两项外推为新 reader 的运行证据。
本轮只补 TSBench 封装、独立恢复和定向边界，不重跑旧性能表或全部历史参数。

| 原生操作组 | 冻结入口和本轮合同 | 验证边界 |
|---|---|---|
| `batch` | `titchy_bound` / `titchy_c_encode` / `titchy_c_decode` 生成、恢复 TCHY v2；注册 `titchy-batch` V-only。 | 输入是密集单列 unsigned 位模式，不是浮点数模型。四种宽度 8/16/32/64；每 chunk 4 样本，每 split 1,000 chunk，threshold 0.25，endian tag 0，活动字典不限；64 位配置是选定的 Unique 批基线。 |
| `packet-stream` | C11 `titchy_stream_push` / `pop` / `finish` / `reset`，配套 stateful packet decoder。 | 每个样本单独输入；可在结束前取得 packet，不是批算法外包流化。用例采用 target=7 chunk 和 72 字节逻辑活动 LRU，是区别于默认配置的定向用例。 |
| `loaded-file-access` | `titchy_reader_open`（不可变内存 `read_at` callback）/ `titchy_reader_open_file`（`FILE`）；复用 reader 做 sample / bit / range。 | `open` 只校验 header/index；查询校验使用到的 pair，不代表整份产物已校验。两条路径分别验证原始结果；`read_at` 计量仅针对内存 callback。 |
| `batch-range` | `titchy_c_range` 每次先做有界全容器校验，再重建相交 chunk。 | 同应用请求可与复用 reader 对照，但完整验证语义不同；不得把该核验开销混入复用 reader 的单次查询成本。 |

## 数据、恢复和资源边界

- [用例绑定](../../configs/suites/dev_titchy_v1/cases.json) 锁定交通 `channel_0` 的测试段首
  4,013 个 canonical f64 值。开发驱动显式 `f64 → u64` 位重解释，恢复时核对反向位模式，
  不量化、不做数值转换，不带 T。该 bitcast 目前是诊断驱动操作，尚不是生产 pipeline
  组件或已计量的比较方法。worker 拒绝直接 f64 输入；负零、NaN payload 等由明确的 u64 位样本验证。
- 批插件只收 rank-1、无 validity、little-endian 连续 U8/U16/U32/U64 单列；最多 1,000,000
  个值、64 KiB schema。ABI 内先把输入样本读入原生 `uint64_t` 数组，恢复时再写回对应宽度；
  不能忽略这两步的时间和缓冲成本。封装包括 32 字节 bench header、原始 schema 和原生 TCHY
  payload；先校验外挂类型/数量/配置与原生 header 一致和编码上界，再调用原生完整验证与恢复。
  `titchy_bound` 只是编码输出上界，不是总工作内存；本轮测试超过值数上限时拒绝，不代表
  已压力测试上限内所有输入。任意 1–64 位、chunk/split、endian 等额外原生配置还未正式覆盖。
- 原生流的结束尾部增加 3 个零至 4,016 个样本；新进程仅凭 TSTR v1 与 TSC1 元数据恢复，
  按真实计数裁剪。计入 21 字节 archive header、每 packet 6 字节记录和完整 32 字节 TSC1，
  不把外部配置或顺序状态当作免费。输出缓冲容量不足可重试，数据损坏或超会话配额后须 reset。
  本例编码活动字典只有 2 个基底，但共发布 1,004 个基底，解码器保存历史字典；72 字节不是
  解码字典上限或 RSS。没有宣称通用内存界、任意位置独立解码或在线到达延迟。
- 复用 reader 必须保持 backing bytes/文件不可变且存活；同 handle 非并发。
  流与 file reader 都在新进程恢复，原始值未作为入参。当前的 49,486 字节 TCHY 输入上，
  内存 `read_at` 打开实际请求 86 字节（38 + 两条 24 字节索引）；后续点请求 58 字节、
  跨 split 的 9 点范围 174 字节、四次 bit 请求各 26 或 27 字节。包含重复请求，不是唯一偏移数、
  `FILE`/内核实际 I/O、冷缓存或延迟。请求的结果位数和偏移/长度均在诊断 JSON 留存。
  构造另一个坏 split 验证：复用 reader 请求完好区间不读取坏 split，读到坏 split 时拒绝；
  stateless range 即使只取完好区间也先拒绝坏容器。读取失败、越界和容量不足单独验证。

## 冻结用例与留存

沿用同一个[隔离验证器](../../tests/isolation/titchy_control.py)、同一冻结 C11 构建和一个统一运行账本；
不需要重复提交。四组共 22 项必需检查已有开发用例绑定，其中三项是既有访问绑定：

- **批处理**：空输入、四种整数宽度、显式浮点特殊位模式，以及 3/4/5 值 chunk 边界和 3,999/4,000/4,001 值
  split 边界。除 5 值合成用例外，边界输入取同一交通留出窗口的前缀。每份 worker 封装与 C11 直接编码的
  TCHY 逐字节一致；删除输入与 schema 后新进程恢复类型、计数、原值位和 schema。
  留存 12 份封装并区分输入域、未知选项、超限、原生输出 capacity 与解码 quota 拒绝。
- **原生 packet 流**：留存一份 TSTR v1 和配套 TSC1；记录首次及后续各 packet 的实际 push 位置，区分
  pop/decoder 输出容量可重试、损坏/累计 quota 后须 reset、finish 才输出的尾部。不使用 72 字节逻辑 LRU
  作为进程内存上限。
- **两类访问**：复用 reader 打开一次执行两轮相同请求，另有新进程 `FILE` 对照；记录首次打开和每次请求的
  逻辑读量，含重复区间。继续使用此 4,013 值用例的 **96／64／192／32 字节**开发上限（打开／点／范围／bit）。
  坏索引在打开时拒绝；索引完好且后一个 split 损坏时，复用 reader 还能读前一个 split，却拒绝触及坏 pair；
  无状态 range 即使请求第一个 split 或 EOF 空区间也拒绝整帧。分别记录越界、输出容量和输入配额状态。

`ctest --test-dir <build> -R '^tsbench.worker.titchy.recovery$' --output-on-failure` 可单独调试。
同目录生成 `titchy-control.json`、公共 `access.tchy`、两份流恢复依赖和批封装。统一预检从封存证据独立解码
TCHY 和 TSTR/TSC1，比较冻结原值位摘要，核对读账、变异位置、独立进程恢复与拒绝结果；不依赖源语料或 native DSO，
也不将 callback 字节解释为 `FILE`/内核物理 I/O。

**只有批接口接入 benchmark ABI**。`extended-v9` 将两类访问接入统一执行候选，`extended-v10` 再接入
原生 packet 流。访问和流均经独立驱动直接调用冻结 C11 内核，不登记为外置服务。没有正式性能样本、服务资格或 M0 通过结论。

## `extended-v9`：复用索引与无状态范围进入同一冻结执行计划

[执行政策](../../configs/suites/m3_first_batch_native_v2/titchy-access-execution.json)复用既有交通留出窗口、
请求和读预算。从原值位模式为两条路线分别编码 TCHY v2；即使 backing 字节一致，也分别在账本中保留并计入
完整 backing 和各自的回答文件。驱动直接调用冻结 `libtitchy_c.so`，没有换库，也没有把访问注册成通用 ABI 服务。
每个访问新进程只挂载本路线的 backing；独立的 Python TCHY reader 对原值摘要、合法 split 元数据和所请求的位/值核验。

- `loaded-file-access` 调用 `titchy_reader_open` 并在同一不可变 handle 上执行两轮 point/range/bit，
  另外新进程走 `titchy_reader_open_file`。单列记录打开、每次请求和失败的回调，并核对容量、越界、EOF 空请求、
  缺文件与配额。输入先载入内存，预算只约束 `read_at` 逻辑字节（包括重复偏移），不约束整体装载、`FILE` I/O 或延迟。
- `batch-range` 调用 `titchy_c_range`，逐次走整容器验证。对两路线使用同一后段 split 损坏：复用 reader 仍能读前段，
  触及损坏 split 时才拒绝；无状态 range 即使请求前段或合法 EOF 空区间也先拒绝。该路线没有 `read_at` 字节证据，
  不复用索引 reader 的读量，也不将缺测填零。

[联合运行](../../results/m0-titchy-unified-20261119-r1/report.json) `dd4258f0e77c43d886490844730165d9` 的每份
backing 为 49,486 B。打开一次读 86 B；两轮各自的点请求 58 B、九点范围 174 B、单 bit 26–27 B；
相应回答文件为 286 B 与 230 B。两份 backing 的全量原始位都由独立 reader 核验；
[脱离原构建和语料的审计](../../results/m0-titchy-unified-20261119-r1/restore.json)重跑两个访问产品，
[重封存负测](../../results/m0-titchy-unified-20261119-r1/titchy-reseal.json)拒绝改写读账、隐藏范围外损坏、改写回答及加入未声明输入。
`packet-stream` 不在 `extended-v9` 的冻结计划内；不将后续流式运行补记到该次账本。

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --titchy-access
```

## `extended-v10`：原生 packet 流进入同一冻结执行计划

[执行政策](../../configs/suites/m3_first_batch_native_v2/titchy-stream-execution.json)在同一交通窗口复用六项
`packet-stream` 义务。输入是首 4,013 个 f64 的原始位显式重解释为 u64（32,104 B），不含时间戳。
新增槽的编码进程只挂载原值；在首包可弹出时检验阻塞的 push/finish 和小缓冲 pop 不改状态，随后按原生协议排空。
恢复进程只挂载 TSTR 与 TSC1 两件产物及封存的 C11 库、驱动和 ELF 依赖，不挂载原值或 ABI 插件。
原生恢复与独立 Python 格式读取器均核对 4,013 个原值位的冻结摘要；两者都检查三项零填充，不留存原值副本充当恢复依赖。

[联合运行](../../results/m0-titchy-stream-unified-20261119-r2/report.json) `21e5b977d5ee46009d28ddb14fba6f83` 中，
第 **28** 次 push 后排出首包，finish 前排出 **143/144** 包，finish 时输出补齐到 4,016 值的最后一包。
小输出容量可重试；截断或累计额度不足后必须重置；编码器 reset 的归档逐字节相同。逻辑 LRU 上限 72 B，
实际最多 **2** 个活动基；流中公布 **1,004** 个字典基，解码器保留已公布基。该上限不是总字典、RSS 或延迟保证。
完整留存 **50,549 B**：原生 packet payload 49,632 B + TSTR 头与记录 885 B + TSC1 32 B；不是只计 payload。
[脱离原构建和语料的审计](../../results/m0-titchy-stream-unified-20261119-r2/restore.json)实际重跑了包恢复，
并复核原生 decoder 的拒绝/重置记录。[重封存负测](../../results/m0-titchy-stream-unified-20261119-r2/titchy-reseal.json)
拒绝改写配置、截断尾包、伪造首次排包位置、将原值加入 decoder 输入。首试 `r1` 留有驱动误传空原生配置指针的失败终态，
未纳入 `r2`。`r2` 的验证脚本对照分派修正后对同一个 seal 补做对照与恢复，没有重新提交或改写账本。
这是线上 push/pop 语义和离线产物恢复的验证，不是端到端在线吞吐、首输出时延或 M5 通用流服务的证据。

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --titchy-stream
```
