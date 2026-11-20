# Gorilla T/V 派生角色合同

本合同记录 M3 的两个开发实现，不是正式组件资格，也不授予组合资格。两条路线从编号 7
`gorilla-native / gorilla_c` 的原生 TV 内核派生；不改原归档或 `gorilla-tv`，不添加 Unique selection
或原生操作组，不涉及编号 8 Gorilla XOR2。[来源映射](../../catalog/selections/gorilla_role_derivations.json)
锁定原 selection、归档和 `src/gorilla.c` 成员。构建时只从项目内已锁定归档提取位读写原语；
[派生源码](../../plugins/codecs/gorilla-derived/column.c)分别编译 T、V 分支，两个 DSO 均不链接 `libgorilla_c.so`。
插件 manifest 锁定派生源码、提取器和公共 ABI，运行计划另外锁定 manifest、配置及实际 worker/DSO 摘要。

| 独立路线 | 输入和恢复对象 | 有效码流 |
|---|---|---|
| `gorilla-t-derived`（`gorilla.t.derived`） | 单列 dense i64 毫秒、0–512 行；schema 需为 `{"time_unit":"ms"}`（允许 JSON 空白且原样恢复）；不排序、不换算，允许重复与逆序 | `gorilla.t.delta-column.v1`，第一值 ZigZag uvarint、第二值模 2⁶⁴ 差 uvarint，其余按原 XORChunk 的 delta-of-delta 桶编码（前三个小桶为非对称有符号区间）。 |
| `gorilla-v-derived`（`gorilla.v.derived`） | 单列 dense f64、0–512 行；按 `binary64` 原位恢复，包含 NaN payload、无穷、负零、subnormal。schema 作为不透明字节原样恢复，调用方负责声明 V 语义。 | `gorilla.v.xor-column.v1`，第一值 64 原始位，其余为零 XOR、复用窗口或新窗口；不存在时间戳或质量误差分支。 |

每次编码只传入一列，不填虚拟另一列，也不以 TV 费用相减推导 T/V 成本。两端 ABI v1、options `{}`，
整个消息独立 reset，无跨消息状态、模型或字典。不继承父路线的 append/snapshot/resume/iterator，
不声称索引访问或流输出。不接受带有效性 mask 的 view、类型或 stride 不匹配、超出 512 行、T 时间单位错误、
两列联合输入。兼容环境为当前 Linux x86-64 小端 CPU。

完整帧为 32 字节 `linear_frame` 头（不同 magic、dtype、行数、schema 长度和 payload 长度）+ schema +
本角色 payload；payload 含 2 字节大端行数、MSB-first 角色 token 和末尾零填充。判定字节包括完整帧，
输入分母仅为本列 `8 × rows`。不与 TV 或相反角色互解。校验长度、内外行数、窗口定义/位宽、varint 溢出和
尾随/非零 padding 等结构；没有添加 CRC，结构检查不承诺检测任意比特翻转。

## 执行与证据

`tsbench.worker.gorilla-derived.differential` 在一次 run 固定八个输入 × 两个角色，含真实交通 512 行、
汇率 13 行、空块、负时间单行、重复/时间回绕/特殊 f64 位、小桶边界和高位宽 512 行。独立 Python 解析器
从同输入的原生 C11 TV 裸块读取 T/V token 各自的起止位，按角色投影后逐字节对照派生 payload；生产派生
编解码不调用这个对照入口。16 项拒绝覆盖错角色/类型、超限、错误时间单位、非法选项和坏帧，其中还验证
拒绝后无输出文件。每个成功帧用另一个进程验证 shape、schema 和原始位，再封存在同一 run；报告可以离开
工程和数据逐字节复算。

```sh
# 激活 tsbench 后，在支持 Bubblewrap 的 Linux x86-64 主机执行：
tools/probe_offline_gorilla_roles.sh "$CONDA_PREFIX" <空结果目录>
```

脚本在禁网、搬迁路径和空构建目录下编译并执行；再隔离原构建、语料、配置及原生 TV oracle DSO，
只通过封存 worker、loader、运行时库和单个角色 DSO 实际解码保留帧。每次解码只挂载该角色的帧、
允许的程序/库及临时输出；另一个角色的 DSO 不挂载。审计不写原 run，不是性能样本或分发声明。

独立 T、V 可进入 [T+V 组合预检](tv-composition.md)。固定 T/V 与完整对象组合另有实跑证据，
其资格独立判定；本篇的两条组件路线不自动授予 `shared_t_controlled` 或 `whole_object` 的资格。

### 真实源独立轴（M3 开发诊断）

[轴任务 r2](../../results/m3-real-axis-20261120-r2/replay-audit.json)取 ETTm1 与 national-illness 各 515 行的真实投影，
以 CSV/NPY/TXT 三种输入重建相同对象。T-only 与 raw-T 对照，并从毫秒精确逆变换到原始秒坐标；V-only 用 Gorilla-V
对照 ALP，每列逐位验证。512 行与 3 行块分别启新进程，恢复顺序和原域摘要均需匹配。计费包括每个完整帧
（含头、schema、原生载荷）及对象清单，分母为当前角色原始逻辑字节。结果不等于原生 TV 或正式计时。

`tools/m3_real_axis_roles.py` 的 `plan` 冻结真实投影与构建，`run` 生成单一封存运行，`audit --replay` 在独立禁网进程
里挂载帧和所需解码闭包，不读取原始输入。r2 从冻结的 T/V 首块及已封存帧复算预期拒绝挂载；重放用已恢复的首块
构造原始拒绝调用，核对插件、操作、状态、无发布产物，以及由同一首 tick 衍生的不可精确换算探针。
仅静态审计不证明原生调用复现；`--replay` 才执行重放。r1 保留历史存档，不由 r2 重写。
