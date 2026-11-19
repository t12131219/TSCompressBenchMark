# Sprintz-FIRE：原生批处理、逐通道归约与 typed V worker

对应首批 selection 19，来自冻结 `Sprintz-family` 的 `repaired_codec`。复用同一归档 SHA-256
`18c47f8dd0dae6770b4147b1a2870dc9c73e8927efe9761e7fe9bd3c10fd6466` 的
[Unique 发布验证](../../third_party/provenance/Sprintz-family/unique-validation.json)；记录也与
Unique `docs/validation/sprintz-simd-query-20261110.json` 对应。它记录 18,004 个来源侧查询测试
（15,364 SIMD、2,640 标量），覆盖 8/16 位、多通道、尾部、截断及宽整数归约，另有旧查询回归
和 sanitizer 通过；没有重测统一性能。测试程序不在交付树内。旧审计里“公开查询只走标量”的
结论不适用于现归档。我们不重复来源侧全套，只用直接入口对照与 TSBench 特有的适配断言补证。

| 操作组 | 当前冻结入口与归因 | 本地开发对照及尚缺 |
|---|---|---|
| `fire-batch` | `sf::Codec::{encode,decode}` + `sf::{frame,unframe}`。实现入口可处理 u8/u16、1–128 lanes，受 mode/path/width 条件和工作区约束；本 TSBench 方法**仅**注册 `sprintz-fire` typed V：`algorithm=1, width=16, ndims=4, path=0`，接受一个无 validity 的 little-endian 连续 `u16` 向量，最多 65,536 原始字节。4 表示按顺序循环分到四条预测 lane，不是四线程。 | 0、3、1,031、32,768 个元素：本地 ABI 产物里的完整 SFB1 与冻结原生入口逐字节一致；迁移二进制、删除暂存原文后新进程位级恢复。拒绝 f64、65,538 字节、外层尾随字节/错 dtype、SFB1 原长/原文 CRC/payload 错误。另在原生直调覆盖 u8 4/5/128 lanes、u16 2/3 lanes（包括 3 lanes 的显式大消息诊断），独立新进程按位恢复；拒绝 0/129 lanes、原生默认限额外及 u16 奇数字节。worker 仍不支持这些附加配置。 |
| `query` | 冻结 `Codec::query` 的 `Auto` 分支在 generic packing 走上游修复版 SIMD，在 u8 ≤4 或 u16 ≤2 lanes 的 lowdim 走标量；强制 `Scalar` 是不同对照。COUNT/SUM/MAX 是**无符号 lane** 归约，不是浮点原值查询。原生查询对已编码 payload 先检查语法和长度。 | 各配置单独编码；低维 `Auto` 实测 `Scalar`，generic `Auto` 实测 `UpstreamSimd`，均与显式标量及原数组逐 lane COUNT/SUM/MAX 一致。覆盖空块、不整行尾及 u16 三条 lane 的 SUM 均超过 2³²−1；两种模式均拒绝截断、尾随、原长不符与越消息限额，低维拒绝强制 SIMD。仅直接原生诊断，**未**在 TSBench ABI 声明查询服务。 |

插件仍由 TSBench worker 动态加载；进入编译为 AVX2/BMI/BMI2/LZCNT/POPCNT 的
原生入口之前由不带该组 ISA 编译选项的适配器检查本机，缺条件拒绝，不假造标量 codec。
查询的低维标量分支不是整个二进制可运行在无 AVX2 主机的证明。开发测试缺 CPU 条件标为跳过。

封装为固定 32 字节 TSBench 头 + 原样 schema + 完整原生 SFB1（含自身头、配置和 CRC）；
存储/比较时计入全部这些字节。恢复检查声明长度、类型、配置、码流校验和、精确输出长度及原文
CRC；无模型/字典/原文依赖。不因 CRC 或回归用例主张恶意输入安全。没有在该方法里做
`f64 -> u16` 位片、列合并、查询、外部分块或并行，也没有修改 Unique 源码。后续若比较 f64，
须登记独立可逆转换并计费，不允许看到输入 dtype 后静默强转。

用 `tsbench` 配置 Release 构建后，执行
`ctest --test-dir <build> --output-on-failure -R '^tsbench.worker.sprintz-fire.recovery$'`。
`<build>/sprintz-native-control.json` 和同目录的 9 份 SFB1、4 份 worker 封装是诊断证据；
统一预检将它们收入同一个运行账本。复算核对原始位模式生成规则、完整 SFB1 配置和 CRC、
RLE 长度及裸尾字节、worker 内层逐字节一致性、实际恢复摘要与逐 lane 归约；不把结构检查当作
第二份预测解码器。不采集性能样本，不替代任何阶段正式运行。M1 的 f64 候选套件保持原 6 输入 × 3 方法，不把
选定域不同的 Sprintz 插入原候选。

## `extended-v8`：独立批恢复与压缩域查询

[冻结执行政策](../../configs/suites/m3_first_batch_native_v2/sprintz-batch-execution.json)保留编号 19 的两个原生操作组。
工具和插件依赖同一冻结的 `repaired_codec / unique-v1`，不更换原生库。两组对相同的九个有类型与形状的冻结输入各自编码，
不是把批组的产物或探针结论转账给查询组；执行序列、输入、实际进程、每件产品和拒绝都进同一份主账本。

| 组 | 入口及隔离 | 验证与保留 |
|---|---|---|
| `fire-batch` | 九份 SFB1 由 `Codec::encode` 生成，新进程 `unframe` + `Codec::decode` 恢复；四个四通道 u16 用例另从公共 ABI 独立编码和恢复。 | ABI 用例保留完整封装、schema 和原生帧；内层与直接原生编码逐字节一致。其余保留完整 SFB1。核对 SFB1 长度、双 CRC、RLE 结构、裸尾及原位字节；实际测试通道数/消息长边界、非法字节宽度、外层和原生畸形帧。 |
| `query` | 新进程只挂载 SFB1，不挂载原列、原语料或 ABI 插件；调用原生 `Codec::query`，同时运行强制 Scalar 对照。另一个新进程才做全量解码恢复，不把这一步混同为查询方法。 | 保留完整查询输入 SFB1、规范化 COUNT/SUM/MAX 输出及实际操作日志。逐通道核对 oracle、低维回退与 generic 分派、非整行、消息超限和 malformed 拒绝；检测超过 32 位的无符号累加。 |

原生 `upstream_simd` 是查询后端，不代表线程并行；空或只有裸尾的用例不声称完成 SIMD packed-block 工作。
低维 `scalar` 标签只说明扫描方式，不取消整个冻结库的 AVX2/BMI1/BMI2/LZCNT/POPCNT 运行前置条件。
查询结果是 u8/u16 整数域归约，不能当作 f64 原值查询。不授通用 ABI 查询、计时样本或正式资格。
文件上限同时考虑 SFB1 头、RLE 值和组头、padding 与输出侧的完整封装/归约文件；宽用例的原生消息限额为 524,288 字节，
不修改四通道 ABI 的 65,536 字节原值上限。

[联合报告](../../results/m0-sprintz-unified-20261119-r2/report.json) run `31f35aada0f7444b8901530452bdbe3f`，
151 槽、130 个产品独立恢复、21 项预期输入拒绝。Sprintz 在其中新增 9 份批产品、9 份查询产品、2 项 ABI 输入拒绝；
[独立审计](../../results/m0-sprintz-unified-20261119-r2/restore.json)在不挂载原构建或语料的环境重跑全部 9 项查询，
报告逐字节复算。默认查询后端记录 2 个 `scalar`、7 个 `upstream_simd`，后者含两个无 packed block 的边界用例；
宽用例首 lane SUM 为 4,325,375,535（66,001 值），另外两 lane 各 66,000 值，不丢非整行尾。
[重封存负测](../../results/m0-sprintz-unified-20261119-r2/sprintz-reseal.json)拒绝将 SUM 截为 32 位、
伪造原值挂载依赖和省略查询输出。首轮 r1 的错类型负例把 16 位改为 32 位，在 ABI 上限处先触发大小拒绝；
r2 改用同宽错类型从空目录完整重跑，不读取 r1 的产物、样本或通过结果。

复跑（结果目录需为空）：

```sh
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --sprintz
```
