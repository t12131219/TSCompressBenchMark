# ZFP（selection 31）：field、OpenMP 编码和固定率 array

锁定 `zfp-native/unique-v1`，归档 SHA-256
`97ad797ebe89ba9585a9cf49932caf15297c824765ba774bda4418b5cec4c34f`。
先复用 `Unique_Selected_Compression_Rewrite/fix_ReWrite/zfp-native/` 的 README、工具及功能报告：
`FUNCTIONAL_REPORT.md` 与锁定归档中同名成员字节一致。[发布验证](../../third_party/provenance/zfp-native/unique-validation.json)
记录 array、features、OpenMP field workers 的历史通过；CUDA 是构建通过、运行未验证。
本轮不重跑旧性能表，仅补当前 ABI、数据、实际 worker 和更新后恢复的证据。

| 原生组 | 实际入口和本轮判定 | 不可外推 |
|---|---|---|
| `field-baseline` | `zn_config_1d` / `zn_create` / `zn_encode` / `zn_decode`，串行可逆 i32/i64/f32/f64；`zfp-reversible` 插件。 | 不含空 field、浮点有损、OpenMP、多维或 stride ABI 服务。 |
| `field-modes` | `zn_create_ex` / `zn_get_info` / `zn_encode_field` / `zn_decode_field`，独立核对 stride、origin、padding；1D rate、2D accuracy、3D precision、4D reversible 直调测试。 | 请求参数、有效参数和误差分开；不是对所有类型、参数和输入的误差保证。 |
| `openmp-encode` | 同一可逆 f64 field 对照 serial、OpenMP 1/2；测试专用程序拦截实际 full-block encode / decode 宿主调用，按 Linux TID 统计块工作。 | 线程执行证据不是耗时、加速比、核占用率或所有形状/布局的 worker 保证；CPU decode 仍是串行。 |
| `fixed-rate-array` | `zn_array_*` 1D f64 代表用例：点改写、跨块范围、逐出、flush、export 和新进程 import。 | array 格式和缓存语义不属于 field。冻结实现只有一个脏块缓存；`zn_array_set_cache_size` 在 `src/array_c.c` 忽略请求大小并 flush，不可宣传为可调大小。 |

## 数据和位级恢复

[用例清单](../../configs/suites/dev_zfp_v1/cases.json) 锁定 v2 气象测试段的 `co2` 首 8,192 个
值，供四类型串行批对照中的真实 f64、1D rate 尾块（前 1,029 值）和 OpenMP 对照使用。
其余为显式 typed 边界及受控张量 fixture；不增加独立来源数。批路径另覆盖 3/4/5 与 4,095/4,096/4,097 值的单 field 边界。4,096 是选定外块规模，
当前用例不声称 worker 对任意输入自动外分块。批路径保留 f32/f64 的 ±0、
无穷大、subnormal、带 payload 的 NaN 位及 signed 整数边界；新 worker 只接收产物并恢复 schema，
不接收源数据。结果验证器同时对照直接 native payload，不推断跨平台字节一致。

`zfp-reversible` 只接收非空、连续、无 validity、little-endian 的 rank-1 V，最多 64 MiB
值数据和 64 KiB schema，选项封闭为 `{}`。在 ABI 边界按原类型对齐复制，不做尺度转换；
恢复时同样计复制成本。32 字节 envelope 加 schema，其中 magic 固定方法/模式版本，dtype 与 count
提供 raw ZFP 所缺的外部 shape/type。裸 payload 包含 native 64-bit 字对齐。先核对封装长度/类型/
容量，再进入 native decode。**只解码同一受信计划中生成并经完整性检查的产物。** 冻结公开头明确
要求 trusted stream；封装边界检查不是任意外来 ZFP 码流验证，不能开放作为外部上传解码器。
本轮仅验证进入 native 前的异常封装拒绝；不宣称 native 对任意畸形流安全或对近 64 MiB 已做压力测试。

## 实际参数、观察质量与数组成本

- 1D 气象 rate 请求 13.37、native 有效 13.25 bit/value，原值域最大误差约 0.325；
  2D 反向带 padding 的 accuracy 请求 0.1、有效 0.0625；
  3D permutation/负 stride 的 precision 请求/有效均为 13；实际最大误差分别约为 0.011963 和 0.036255；2D/3D 使用确定性的二进制有理数 fixture，不依赖 `sin` 或系统 libm 生成输入。
  4D i64 reversible 精确恢复。四项同时检查未覆盖 padding 保持原值、错误 origin 拒绝；
  还验证整数 accuracy、超过标量位宽的 precision、重叠 stride 和 CPU 构建中 CUDA 的拒绝。
  以上误差上限是对应 case 的预设判定，不是 rate/precision 的普遍保证；有效参数取自 `zn_get_info`。
- 原生并行测试固定 `OMP_DYNAMIC=FALSE`、`OMP_THREAD_LIMIT=2`，OpenMP 两档均采用 64 个
  block 的 chunk。2 线程配置下编码的两个 TID 各实际执行 1,024 个 full blocks；三个配置均由
  调用线程解码 2,048 个块，decode 后恢复原编码策略。同一测试输入三档 payload 一致，
  但插桩仅供功能归因，不进入正式性能时钟。当前依赖系统 OpenMP runtime，CUDA 构建关闭；
  既往 CUDA build 结果不能推出本机设备状态或资格，GPU 不在冻结的初版 CPU 平台范围内。
- 数组请求 rate 18，经字对齐后有效为 32 bit/value。缓存中写入精确，逐出重读按量化质量检查。
  `set_cache_size(16384)` 清空缓存，重新读取时报告仍为 2,048 字节，不是内存预留或 RSS。
  新进程仅用 64 字节 array 数据和 116 字节带格式标识的外部配置重开；按更新后的原数据验误差，
  并核对完全未改动的块与写入前的压缩字节和恢复值都逐位一致。不得拿 field payload 解读为可修改 array；
  带相同派生长度的错误配置不能靠裸流自行识别，必须校验外部方法身份和配置。

[验证器](../../tests/isolation/zfp_control.py) 与 [并行诊断入口](../../tests/native/zfp_omp_control.cpp)
从 `ctest --test-dir <build> -R tsbench.worker.zfp.recovery --output-on-failure` 运行。
`zfp-control.json` 随统一账本留存 11 份批封装、四组 field 的载荷/配置/恢复物理 span、三份 OpenMP 对照
裸流、array 更新前后产物及恢复值，以及一份共享气象原值。复算从冻结原值独立计算最大误差与 RMSE，
核对未触及 padding/块、原生工作线程、同一 field 三档载荷和实际拒绝状态；不把离线复算说成第二个
ZFP 解码器。原生解码实测在新进程中进行，只恢复受信产物。
**仅串行可逆批路径接入 ABI。** 高维/有损 field、OpenMP 和 array 都是选版原生直调诊断，
未接成公共流水线或服务，没有正式时间样本或资格结论。

## `extended-v16`：三条原生路线纳入统一账本

[运行 `86f4592cf3ec4975b401070518178ca9`](../../results/m0-zfp-native-unified-20261119-r1/report.json)
把上述三条定向诊断转成同一冻结计划中的可执行单元，绑定 15 项必需义务和一项 OpenMP 条件。
两种诊断程序都链接锁定的 `libzfp_native_c.so`；OpenMP 沿用 CTest 的原生整块调用观察器。
新计划使用 `bmk.native-batch-execution/1`，不把有损 field 或 array 算成无损；三条路线仍不是
公共 ABI 服务，也没有正式性能/资格。旧 `extended-v15` 的封存报告仍可逐字节复算。

| 操作组 | 本次运行观测 | 恢复和计费边界 |
|---|---|---|
| `field-modes` | 1D rate 请求/有效为 13.37/13.25，原值最大绝对误差约 0.325；2D accuracy 为 0.1/0.0625，误差约 0.011963；3D precision 为 13/13，误差约 0.036255；4D i64 可逆精确恢复。独立检验反向 stride、padding、origin 与无效配置。 | 按 `ZNFIELD1` 外部配置和裸帧新进程恢复。四份 payload 分别为 1,712 / 72 / 144 / 2,224 B，附 47 / 43 / 41 / 38 B 配置。保留物理恢复 span 和一份有损气象原值用于离线误差复算；原值和 span 都不是恢复输入。观察上限仅适用于冻结用例。 |
| `openmp-encode` | 同一 8,192 值 field 的 serial / OMP 1 / OMP 2 编码分别由 1 / 1 / 2 个 OS 线程执行；OMP 2 的两个线程各做 1,024 个整块。三个配置的解码都在调用线程完成，每次 2,048 块。 | 三份 56,504 B 裸帧在该 case 字节一致，共享 43 B `ZNFIELD1`。观察工具不在独立恢复闭包内；每档由另一个进程串行逐位恢复。脱离式审计另从恢复值重跑三档，按调用线程身份和工作数比较，不比较跨进程 TID 数字。 |
| `fixed-rate-array` | 请求 18、有 32 bit/value 有效对齐率；脏块切换后观察到量化，缓存大小请求触发清空而非可调容积；重开后再次做独立跨块读取，未触及的第 2 / 3 块（零起始）码流和值保持不变，更新后最大绝对误差约 3.78×10⁻⁹。 | 当前产物恢复需要 64 B 更新后 array 和 **18 B** `ZNARRAY1` 配置，合计 82 B。更新前 64 B 和两份恢复证据也在账本计费，但不冒充更新后恢复必需资产。该配置格式用于此版本的固定 f64 一维诊断，不等于上一版探针的 JSON 格式。 |

只有受信的同次产物能进入 native decode；字段、模式和长度的独立核验不构成任意 raw ZFP 输入验证。

`tsbench` 环境下禁网空构建、路径迁移，15/15 CTest 和 177 项 Python 测试通过。主报告逐字节复算，
[独立恢复报告](../../results/m0-zfp-native-unified-20261119-r1/restore.json)在不挂载工程语料与构建的环境
重跑六个 ZFP 槽；[专项重封存拒绝](../../results/m0-zfp-native-unified-20261119-r1/zfp-native-reseal.json)
验证以单线程工作记录冒充两线程、把原值偷挂给恢复进程及替换 array 率配置均不能成为候选证据。
