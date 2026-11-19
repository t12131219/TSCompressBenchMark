# 首批原生执行候选：Gorilla #7 `tv-batch`

本切片执行 [36 组准入定义](native-admission-plan.md) 的一组，不更改其分母、资格状态或正式阶段收据。
插件仍链接 Unique `gorilla-native/unique-v1` 的 `gorilla_c`，不重新实现 XORChunk。执行层提供
`tsbench.api.{plan_batch_execution,run_batch_execution,report_batch_execution,audit_batch_execution}`，CLI 共用这些入口。

## 从冻结计划到一份账本

- 计划引用原准入计划 ID、路线合同、4 项义务 ID 及其已有用例。重叠用例共享产品槽，不重复编码或计样本。
  冻结 9 个槽：6 个既有原始域用例（含空块、单行和特殊 f64 位），以及 511/512/513 行边界三元组。
  三元组的 513 行必须由真实插件以 `BMK_RESOURCE_LIMIT=7` 拒绝，无输出帧。不能以框架预筛代替插件拒绝。
- 提交时重新验证输入、方法配置、控制代码、worker/插件/依赖锁和运行器字节身份，拒绝篡改后重新计算 ID 的计划。
  一次提交生成一个 `run_id`、一个 `ledger.jsonl`、一个封存清单；校验与恢复失败都保留终态。依赖打包失败在发布运行前拒绝。
- 编码器仅见声明的输入文件和 ELF 闭包。每个成功产物在原输入临时目录撤销后，启动仅能看到单个帧、声明 ELF 闭包和
  独立输出目录的解码进程；不将原始列、项目目录、构建目录或 `/usr` 挂进恢复子进程。核对输出 dtype、行数、
  时间戳和值两列的原始字节哈希及 schema 字节。独立 XORChunk 解析器另从 payload 验证原始域和填充位。
- 每次调用施加 128 MiB `RLIMIT_AS`、16 KiB `RLIMIT_FSIZE`、禁止 core、5 s 墙钟截止和撤销。输入行数、完整帧长度、
  输出形状和共享闭包预算另行校验。前两项分别是每进程地址空间、单文件写入限额，**不是** RSS、进程组内存或总磁盘硬配额。
  字节账分开列实际序列化帧、日志和共享解码闭包，不把闭包复制为每案成本，也不把元数据和文件系统开销算入上述预算。
- `report` 由计划、账本及封存产物重算，不需要原始输入；`restore` 实际重新执行 decoder，不能以报告复算代替恢复。
  封存清单用于检测本地可信证据误改，不是签名或对不受信任 native 插件的安全承诺。

```sh
# 使用已激活的 tsbench；BUILD 是项目内的相对路径。
cmake -S . -B "$BUILD" -DTSBENCH_PLUGINS=gorilla-tv -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"
cmake --build "$BUILD" --target tsbench_cpu_worker tsbench_gorilla_tv tsbench_gorilla_batch_control
./bmk lock-build --worker "$BUILD/tsbench_cpu_worker" \
  --plugin "gorilla-tv=$BUILD/plugins/codecs/gorilla-tv/libbmk_gorilla_tv.so" --out /tmp/gorilla-build.lock.json
./bmk batch-execution-plan --build-lock /tmp/gorilla-build.lock.json \
  --direct-control "$BUILD/plugins/codecs/gorilla-tv/tsbench_gorilla_batch_control" \
  --out /tmp/gorilla-batch-plan.json
mkdir -p results/gorilla-batch-candidate
./bmk batch-execution-run --plan /tmp/gorilla-batch-plan.json --results results/gorilla-batch-candidate
./bmk batch-execution-report results/gorilla-batch-candidate/<run_id>
./bmk batch-execution-restore results/gorilla-batch-candidate/<run_id>
```

## 直接 C 双向对照

`--direct-control` 将显式构建的 `tsbench_gorilla_batch_control` 字节身份及其 `DT_NEEDED` 写入同一计划。工具和插件必须链接**同一份**锁定的 `libgorilla_c.so`；C 工具不加载 ABI 插件。每个执行根只挂载自己的 ELF 传递依赖：普通 worker 不见对照工具，C 工具不见插件和 C++ worker。

对照覆盖 `native_payload_cross_decode` 冻结的 6 个用例。在同一槽先用 ABI 和 C 入口分别编码，隔离撤销原输入后：

1. 从 ABI 帧取出原生 payload，让独立 C 控制进程调用 `g_decompress`，核对原始时间戳和值的字节。
2. 用 C 入口的 `g_compress` 输出重新组装同版本 TV envelope，让 ABI 解码进程实际恢复两列和 schema。
3. 同时核对两边 XORChunk payload 逐字节相等，并保留独立格式解析器对 ABI 帧的原始域和语法验证。每个对照槽留存一份 `.xor`，不是另一个 benchmark 样本，不计进正式压缩比或计时。

两方向各有自己的子进程终态和日志，仍在原产品槽和同一主账本。重放报告必须看到完整操作序列、两个方向的输出身份和与原帧匹配的 `.xor`。独立恢复审计实际重跑两个解码方向。
未绑定 `--direct-control` 的旧计划仍能复算，但这项义务继续标记为不完整。

## 2026-11-19 实跑与边界

[含 C 对照的新提交](../../results/m0-gorilla-batch-cross-20261119-r1/batch-report.json) `049e62deef7944258666d32a99aa5585` 从新目录构建 Gorilla/worker/对照目标，**8 帧成功、1 项预期拒绝、6/6 组双向交叉恢复**，本组 4/4 项均有候选证据。共享 ELF 闭包共 5,920,800 B（含 C 工具），对照裸 payload 3,998 B 单列；普通帧仍是 11,799 B。
[新恢复审计](../../results/m0-gorilla-batch-cross-20261119-r1/restore-audit.json)在迁移后实际重跑 8 帧普通解码及 6 组双向恢复。新报告在未挂载原构建和语料的禁网环境中逐字节复算，旧报告也逐字节复算。
[新负测](../../results/m0-gorilla-batch-cross-20261119-r1/execution-negative-controls.json)即使重算封存清单也拒绝省略一个实际解码步骤或改动 C payload；资源负测复测通过。`tsbench` 下 127 项 Python 测试通过。

### 先前不含 C 对照的执行


[统一报告](../../results/m0-gorilla-batch-execution-20261119-r2/batch-report.json)记录 8 份产品位级验证、1 项预期拒绝；
8 帧共 11,799 B，同一次运行共享解码依赖 5,904,304 B。不挂载语料和构建的外层禁网环境逐字节复算报告；
[迁移独立恢复](../../results/m0-gorilla-batch-execution-20261119-r2/restore-audit.json)从封存拷贝 8/8 重新解码，每个解码进程使用单层禁网隔离。
本机另尝试嵌套 Bubblewrap 恢复，子命名空间未能建立，不作为通过证据。
[资源负测](../../results/m0-gorilla-batch-execution-20261119-r2/resource-negative-controls.json)在同一启动机制中观测到超额映射返回 `ENOMEM`、
超限写入到 16 KiB 后收到 `SIGXFSZ`、阻塞进程由监督器截止；超时负测专用 1 s，不更改正向运行的 5 s。
[执行负测](../../results/m0-gorilla-batch-execution-20261119-r2/execution-negative-controls.json)拒绝篡改限额和产物，另一次完整取消运行保留 9 个取消终态。
最初受外层沙箱所限的失败提交仍保留在 `r1`，没有与 `r2` 拼成新的运行。

旧版本只有 3 项候选义务证据完整，不能把旧格式阅读结果解释成直接 C 双向对照。新旧提交均未授正式资格，也不生成研究计时。
相同的执行、资源、直接入口对照与逐产物恢复机制已扩展至 [Zstd 与 ALP 的批路线](linear-batch-execution.md)；与本页报告属于不同提交，不合并分母或资格。
