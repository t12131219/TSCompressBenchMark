# Gorilla C11：原生 T+V 批处理与状态操作对照

对应首批 selection 7。冻结 `gorilla-native` / `gorilla_c` 归档 SHA-256 为
`0d9ce35f06b721db46b11f1de9006150a175eace61810b650b032502c0022f79`。
[Unique 发布验证](../../third_party/provenance/gorilla-native/unique-validation.json) 的 `test` 和
`stream` 都是来源侧 PASS，隔离记录只列 `test`；不重复历史套件或继承其未写明的边界、计时。
以下是新增的 TSBench 适配、数据绑定和直接调原生入口的诊断。

| 原生操作组 | 源码合同 | TSBench 当次验证范围 |
|---|---|---|
| `tv-batch` | `g_compress` / `g_decompress` 接收 `g_sample`（有符号 i64 毫秒，原始 binary64 位）；单个原生消息可有 0–65,535 行，本方法按选定基线限制为 512。第一 T 走 zigzag，后续时间差按原实现的模 2⁶⁴ 运算；不排序、插值或转换 V。 | [`gorilla-tv` ABI](../../plugins/codecs/gorilla-tv/plugin.json) 接收等长的两列 dense `i64(ms)`、`f64`，只登记 `timestamp_value`。空块、单行负时间、极端/重复时间和特殊 f64 位、交通 512 行、汇率 13 行均与直接原生入口的 payload 对照；删除暂存 T、V、schema 后由迁移后的 worker 新进程恢复位模式与 schema。 |
| `append-resume` | `g_encoder_append` 直接编码到有界压缩 workspace；`snapshot` 复制完整原生块而不结束；`finish` 幂等并关闭追加；`resume` 必须**扫描**已有块验证语法并恢复状态，还会**复制**压缩字节。不是零扫描或零复制。 | 用同一 512 行交通输入直接调用原生 API：追加前 23 行，记录压缩位数与 workspace，snapshot 与同前缀 batch 字节相同；超限拒绝无状态改变。继续追加、幂等 finish、坏 snapshot 拒绝后 reset、用新上下文恢复后追加，两个成功路径都与完整 batch 字节一致。不是 ABI 流式服务，未测首输出延迟。 |
| `iterator` | `g_iterator_*` 借用完整的不可变块；逐行产出，不建样本数组；forward seek 继续扫描并可返回当前值，不能倒退，且 first-at-or-after 需要非降序 T。全部排空才能验证尾随字节与 padding。 | 交通块逐位迭代 512 对；另用非降序五行的合成块，固定两个相同时间戳但值位模式不同，检查 seek 命中首个重复时间、next 取第二个、再次 seek 不后退。两块都复核边界、EOF、带尾随字节的终止与持续错误。不是原生索引随机查询。 |

## 数据和产物合同

- [`dev_gorilla_tv_v1` 数据绑定](../../configs/suites/dev_gorilla_tv_v1/cases.json) 锁定 v2 语料 ID；
  交通用测试分区 `channel_0` 起始 512 行，汇率用测试分区 `rate_OT` 末 13 行。联合窗口同一趟
  读出规范 `i64` 秒和 `f64`；调用者显式做 `s × 1000`，核对 i64 范围和可逆性。坐标仍是
  源民用标签，不声称 UTC；不是算法自带转换，也不把它计成 Gorilla 内核工作。
- `gorilla-tv` 不接受隐式时间换算。当前封闭 schema 仅允许 `{"time_unit":"ms"}`（可带 JSON
  空白并原样恢复），options 为 `{}`。列顺序固定 T、V；V 必须原样位级恢复。测试拒绝
  513 行、长度不等、错误时间单位、错误 T dtype，以及截断、尾随和头/码流行数冲突。
- 产物是 24 字节 TSBench 头（magic、schema 长度 u32、行数 u32、payload 字节数 u64，头内
  数字 little-endian）+ 原 schema + **未修改的**原生 XORChunk。报告区分原生字节和完整
  产物字节；逻辑输入是两列之和 `16 × rows`，不扣减 T 字节来制造 V-only 压缩比。原生块没有
  内容 CRC；结构拒绝不是对所有位翻转的检测承诺，位级验证依旧需要预先锁定的期望值或摘要。
- worker 新增内部 `encode-columns` / `decode-columns`，支持有界列数、聚合数据字节和各列布局
  检查；旧单列命令语义保留。两列是两个 ABI view，不把它们伪装成一列字节流。不包含跨块索引或 T+V
  组合。独立 T/V 派生插件另见[角色拆分合同](gorilla-derived-roles.md)，不继承本路线的资格。

`ctest --test-dir <build> --output-on-failure -R '^tsbench.worker.gorilla-tv.recovery$'`
生成 `<build>/gorilla-tv-control/report.json`，附六份完整 TV 帧、原生 snapshot、不中断与 resume 后的
原生 finish 帧。统一预检把 11 个用例绑定到 11 条必需检查，封存输入摘要、用例、窗口血缘、后端和构建。
对 snapshot 另启一个进程，以文件和锁定的 C 库直接恢复 23 行；不传入原始列文件。复算用独立位读取器解析
留存帧和 snapshot，不加载 codec 动态库或语料；检查每列的位级摘要、实际 token 位数与 padding、续跑字节一致性
及冻结的 seek 序列。独立位读取器只是验证器，不是另一条 benchmark codec 路线。

## 扫描与复制工作量

开发探针 `tsbench_gorilla_work_control` 在独立进程中观测原样 `libgorilla_c.so` 的 ELF 调用：计数实际进入的
`g_iterator_next`、其中成功返回的行，以及以源压缩块起始地址为输入的 `memcpy` 调用与逻辑字节。这不是
从 append 位数、workspace 或输入长度推测实际扫描，也不计 CPU 指令、缓存流量或物理 I/O。探针核对
原生调用来自迁移后的同一 DSO；生产 worker、适配器和 C 库不链接探针或替换符号。

| 操作 | `next` 调用 / 扫描行 | 压缩源整块复制 |
|---|---:|---:|
| resume，23 行前缀 | 24 / 23 | 1 次，184 字节 |
| resume，512 行完整块 | 513 / 512 | 1 次，3,733 字节 |
| resume，空块 | 1 / 0 | 0 |
| resume，23 行前缀带尾随字节 | 24 / 23，尾部校验失败 | 0 |

成功恢复后覆盖调用者源缓冲，snapshot 仍与原输入逐字节相同。交通块首次 seek 扫描 51 行；随后请求
游标之前的时间戳，仍返回当前记录，不回退、不调用 `next`。请求末尾之后会扫描剩余 461 行并额外调用一次
`next` 验证 EOF；再次 `next` 不扫描新行。重复时间戳用例也记录逐次工作量。复算从留存帧及冻结脚本
独立计算期望行数、EOF 调用和复制字节，核对观测记录及探针二进制身份。

以上为 M0 开发诊断，不构成正式测量、流式插件接入、随机访问服务或阶段资格。

## `extended-v12`：原生续写、逐行迭代与工作量进入同一执行计划

[执行政策](../../configs/suites/m3_first_batch_native_v2/gorilla-state-execution.json)绑定原有的八项候选义务：
`append-resume` 五项，`iterator` 三项。这四个产品槽使用冻结的 `libgorilla_c.so`，没有切换到 C++ 内核。
[生命周期驱动](../../plugins/codecs/gorilla-tv/state_control.c)与 ELF 工作量观察器分别运行；不把观察器插桩数据当作性能样本。

- **续写**：交通窗口前 23 行生成 184 B snapshot；另一进程只挂载 snapshot 和后 489 行的原始 T/V，
  不挂载原始前缀或不中断产物。中间状态被复制保留，覆盖调用者的 snapshot 缓冲后仍能续写。不中断、续写、批入口的最终裸帧
  逐字节一致，前两份各 3,733 B 并分别留存。验证超限不改变进度、finish 幂等、坏 snapshot 必须 reset、以及独立恢复 snapshot 和两份终帧。
- **逻辑工作量**：恢复 23 行 snapshot 实际扫描 23 行，调用 `g_iterator_next` 24 次（含结束探测），并复制 184 B；
  完整帧扫描 512 行并复制 3,733 B；带尾随字节的 snapshot 扫描 23 行后拒绝，未复制；空帧只有终止探测。
- **逐行迭代**：真实交通帧和重复时间戳帧各自编码封存。交通第一次 seek 实扫 51 行，随后向后请求返回当前位置、
  不额外扫描，也不倒退；另一个越过末尾的 seek 扫完剩余 461 行。重复时间戳的两个值保留各自的原始位模式。
  含尾随字节的帧可返回前缀，但排空时拒绝，错误持续到 reset。这里证实的是前向扫描，不是索引随机访问。

[联合报告](../../results/m0-gorilla-state-unified-20261119-r2/report.json)的 `9a412996b2ee48ae951d6121bc8cfe30`
为唯一主 run。首试的根目录观察器因非本地 RUNPATH 在计划生成前被拒绝；修正为同目录构建后，新 run 仍按原闭包约束执行，
没有沿用首试产物或放宽校验。
[独立恢复审计](../../results/m0-gorilla-state-unified-20261119-r2/restore.json)不挂载原构建或语料，重新恢复全部
Gorilla 状态产物，并从已恢复的不中断帧取得尾部，重跑 snapshot + tail 的续写。所有工作量记录都重新调用原生观察器核对。
[重封存控制](../../results/m0-gorilla-state-unified-20261119-r2/gorilla-state-reseal.json)拒绝删除实际复制、改写向后
请求的扫描数、为 resume 挂载原始前缀和改写恢复后的进度。

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --gorilla-state
```
