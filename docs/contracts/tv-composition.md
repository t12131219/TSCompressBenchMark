# T+V 对象组合与控制变量预检（M3 开发证据）

此预检实现 §7.3 的两类受控组合和联合 TV 对照。正式资格、完整首批执行和阶段验收仍独立；这里不通过
组件成功推断组合资格。`raw-timestamp` 是 TSBench 的独立 `TimestampCodec` 基线，不计入 Unique 选集。
五 V 合并为一条 u16 整数编解码流的独立套件与专项验证见[固定 T 的位片合同](tv-limb-comparison.md)。

## 方法、作用域和计费

- 通用 `tsbench_tv_worker` 从配置和插件 manifest 解析已注册的 `timestamp`、`value`、`timestamp_value`
  路线，worker 不包含 codec 名单。分离布局对每个对齐块只编码一次 T，按 schema 顺序为每列 V 走一个
  ABI context；联合布局用一次原生双列调用，只接收一列 V。所有 context 按块重建，不共享 codec 状态或模型。
- `raw-timestamp` 仅支持 dense `i64(ms)` 单列的 0–512 行，直接保存原始 little-endian 字节加一个
  明确的 payload 标记；外层 `linear_frame` 包含 dtype、行数和 schema。没有转换、预测、索引或隐藏 fallback。
- [冻结套件](../../configs/suites/dev_tv_composition_v1/suite.json)绑定 `exchange-tail`（13 行）和
  `traffic-multi-value-tail`（两列 V，共 515 行，实际分为 512+3），以及空对象、重复/负/回绕时间、特殊 f64 位。
  真实 V 列须来自同一已锁分区、行窗和时间轴，不能只看行数。原 civil 秒坐标明确做 `s × 1000` 的 i64 检查；解码后
  逆变换验证原坐标，非整除、溢出和时间轴错配拒绝。不声称源坐标是 UTC，不接受 mask/缺失值列，也不提供流、索引访问。
- `fixed-t` 固定 Gorilla-T，比 Gorilla-V 与 ALP-V；`fixed-v` 固定 Gorilla-V，比 Gorilla-T 与 raw-T；
  `native-vs-composed` 在单 V 对象上比原生 Gorilla TV 与 Gorilla-T+Gorilla-V。固定支路身份绑定其 build、配置、
  格式和分块/reset；可变路线的身份属于 method，不进入对应的固定条件。在注册表禁用某路线时不 fallback。
- 执行一次冻结的 15 个不同 case×method，每种方法各自完整编码、解码和计费。方法产物可用于多个预声明视角，
  不重复计入独立样本；方法之间绝不复用 T 或 V 码流。按同一原对象的完整 bundle 记账，含目录、schema 和全部 payload，
  不按内容哈希免费去重。独立进程验证 ABI 输出、列顺序、dtype、形状和原始位；结果包含各次 `wait4` 的子进程观察。
- 当前比较键按方向冻结为 O 轨 `development_diagnostic` / `pipeline_service` / `process`。
  子进程墙钟包含启动、动态加载、原生 I/O、按列/按块路由、codec、容器和退出；冻结语料读取、秒→毫秒转换、
  临时输入文件准备和原值验证在区间外。不将该边界解释为裸 codec 时间或 `pipeline_full`，无正式 CPU 核/内存隔离，
  不提供正式排名、比较资格或 R 轨结果。

## Bundle v1

`BMKTVB` + 版本与保留位（共 8B），随后 6 个 little-endian u32：行数、列数、块行数、目录项数、
schema 字节数、schema CRC32，再附 64 个 ASCII hex 字节的 method ID，固定头合计 96B。
每项目录 40B，依次为 `first_row:u32`、`rows:u32`、`first_column:u32`、`columns:u32`、`offset:u64`、
`length:u64`、`crc32:u32`、`reserved:u32=0`。目录后是对象 schema 和连续的完整 codec 帧，偏移相对整个 bundle。
V 列引用 schema 中同一 `axis_id`，不因相同长度合并不同轴。目录按块行序与列序固定；对分离布局，
每个块第一流为 T、其余各一列 V。空对象明确包含一个零行块。上限为 8192 行、6 列、512 行/块、256 目录项、
2 MiB 完整帧；超限拒绝。目录错位、CRC 不符、不完整流和尾随字节在输出前拒绝。CRC 仅用于意外损坏；
运行 seal 另绑定 SHA-256 和完整目录记账，原值验证核对各列摘要，CRC 不等同于认证。

## 运行和独立复验

通过 `bmk lock-build` 锁定 `tsbench_tv_worker` 与配置中的插件，然后 `bmk tv-plan --build-lock <相对路径> --out <相对路径>`
和 `bmk tv-run --plan <相对路径>`。可选 `--suite` 指向本地 `bmk.dev-tv-suite/1` 配置。Python API 分别是
`plan_tv(root, build_lock, suite_path)`、`run_tv(root, plan)`。一次运行只有一个 `run_id` 与同一账本。
失败、超时、取消、缺依赖或磁盘阻断保留实际终态，报告不把它们算成验证通过。前置的完整配置和冻结输入不一致在计划或执行前拒绝。

```sh
# 已激活 tsbench 环境；Linux x86-64 / glibc / Bubblewrap
tools/probe_offline_tv_composition.sh "$CONDA_PREFIX" <空目录>
```

脚本从空构建目录完成禁网编译、同场执行和配置/坏帧负测。`bmk tv-report <run目录>` 只读封存物，可逐字节重算；
`bmk tv-restore-audit <run目录>` 逐项真正解码，不依赖原构建和原语料。恢复环境只挂载对应方法所选 DSO 的传递闭包、
worker、一个 bundle 和临时输出目录；不挂载其他 codec 或宿主共享库。具体文件清单随审计报告记录。
仍要求执行主机具备兼容 Linux/CPU 和 Bubblewrap，封存只供可信的内部复验。

### 同一真实单 V 投影：原生 C11 与可替换组合

[冻结计划](../../results/m3-tv-native-pair-20261120-r1/plan.json)以 ETTm1 的 HUFL 和 national-illness 的
% WEIGHTED ILI 各取同一原始行窗的 T 与一列 V（512+3 行）；与五列开发用例核对同源文件、行窗及所选列原域摘要，
不把单列和五列认作同一个完整对象。`whole_object` 对照 Unique C11 `gorilla-tv` 与 `gorilla-t-derived` +
`gorilla-v-derived`；另以固定 T 比较 Gorilla-V / ALP、固定 V 比较 Gorilla-T / raw-T。三种输入格式、两投影、
四方法共 24 个独立槽。[实跑](../../results/6a6e6d31e2bf43389b36e535db9e3b75/report.json)与
[控制审计](../../results/m3-tv-native-pair-20261120-r1/controls.json)验证 24 槽逐位恢复与完整 bundle 计费；只有原生
联合方法的解码闭包挂载 `libgorilla_c.so`。固定支路在每种方法内实际重新编码，两个块的帧摘要分别一致，不免费共享。

审计在不改仓库注册表的情况下测试逐个禁用实际注册项：5 个禁用项均在执行前拒绝，不回退。T-only 冒充联合角色、
给联合路线传五列真实 V、固定 T 未保持不变也在执行前拒绝。两组真实数据各用一份封存 CSV 产物验证 4 个错误解码方法，
包括联合/派生互换和替换 T/V 后误用旧方法；8 次均由禁网 worker 实际拒绝，无发布文件。
此结果仅覆盖选定投影的 batch 完整对象和控制变量，不据此授予原生流式、正式性能或阶段资格。
