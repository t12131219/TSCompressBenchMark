# 全 registry 的直接原生实验设计

生成器为 `benchmark/tools/generate_all_core_experiments.py`，配置与冻结清单在 `benchmark/experiments/native-all/`。新输出名称全部以 `native-all-` 开头，没有新增版本后缀，也没有覆盖旧六组 native／API／对象实验或其原始结果。

当前 registry 共 38 个 key（含 raw-store）。生成器读取 registry，并断言配置覆盖与 registry 完全一致；每个 key 都有 prepared 与 fresh_request 请求。此处覆盖表示静态 dtype／几何／质量／线程／模型 alphabet 声明满足，实际 build、内容资格、拒绝状态与逐产物正确性仍必须由正式运行给出。

`expected_declared_domain=eligible` 仅表示 registry 声明满足，不表示直接原生入口接受。矩阵 Sprintz 的直接入口只接受 C 布局，因此 int16 F × 3 方法 × 2 lifecycles 的 6 个请求预期为 unsupported，仍保留在 352 请求分母与原配置中；不进行隐式转置。声称正式覆盖前，每个 key 的每种 lifecycle 仍须至少有一个通过逐产物验证的成功请求。

| 配置组（均有 prepared／fresh） | 每种 lifecycle 请求数 | 输入与方法 |
| --- | ---: | --- |
| real | 100 | 原 core 的 5 个原始真实数据对象，12 个通用 byte 方法（含 raw）与 8 个浮点 lossless 方法 |
| entropy | 10 | 4 个 float32／float64 C／F fixture 与 uint8 fixture，FSE／Huff0 |
| floats | 32 | 4 个 float32／float64 C／F fixture，8 个浮点 lossless 方法 |
| integer-models | 4 | int16 C／F fixture，NeaTS／LeaTS |
| integer-matrix | 9 | int16 C／F 与 uint8 fixture，3 个矩阵 Sprintz 方法 |
| integer-u8 | 2 | 原 uint8 fixture，Sprintz delta-u8／fire-u8 |
| integer-u32 | 1 | 原 uint32 fixture，SIMDComp LENGTH／SSE4.1 |
| bounded | 12 | 4 个浮点 fixture，Serf-QT／Serf-XOR／ZFP，ABS 0.01 |
| empirical | 2 | 原 ILI 前 512 个 OT 值，ABBA／fABBA，empirical_quality |
| deepzip | 1 | 原 symbols4 fixture 前 64 个符号，默认 biGRU，单线程 |
| dzip | 1 | 相同前 64 个 symbols4，BOOTSTRAP，显式 caller + 2 Eigen workers |
| records | 2 | ETTh1 OT／weather T 各 512 行，与其真实 T[N] 组成一次 T/V 输入，Gorilla optimized |

真实数据组保留旧窗口：ETTh1 rows `[2048,10240)`、原 7 列的 C／F；weather rows `[2048,34816)`、原 3 温度列 C／F；ILI rows `[0,512)`、原 OT 单列。FSE／Huff0 的声明单对象上限为 131072 bytes／8192 rows，故置于合法 fixture 组，不缩短这些真实对象，也不偷偷分块来改变比较任务。

每组固定 2 sessions × 7 rounds，通常每轮 8 个原生测量操作和 2 个原生 warmups。DZip 预先按其模型计算／完整网络输出成本设每轮 2 个测量操作、2 warmups、1024 MiB batch budget 与 600s timeout；DeepZip 仍为 8 loops、600s timeout。普通组为 256 MiB batch budget／120s timeout。所有 profile 均为单 object worker／4096 MiB address-space limit；DZip 单独三线程 profile，并显式选择系统 libstdc++。选择在运行前冻结，未使用结果调参。

总计 24 份 TOML、352 请求、4928 名义正式 trial、39256 名义测量操作；warmups 不计为正式 trial。每个请求的原 dtype、shape、order、有效 raw bytes、value／timestamp count 与 object_id 固定在 design.json。Gorilla 分母为真实 T bytes + V bytes，T 只计一次；不复制为多列，不生成替代时间轴，不混入 padding 或 ABI envelope。

生成器已实际执行完成：仅加载原数据并解析配置、校验 registry 声明和 alphabet，未构建、资格测试、执行 codec 或计时。名义请求数不是成功结果数。正式运行须保留全部请求、状态、失败原因，不能只汇总成功子集后声称全覆盖。

## 神经路径的短流限制与独立补充设计

只读源码审查确认：原 24 配置中的 DeepZip／DZip 都只用 `symbols4.npy` 前 64 个符号。DeepZip 默认 `lanes=1`，`deepzip.cpp` 的 `encode_group`／`decode_group` 先用均匀概率处理前 `min(64, length)` 个符号，仅 `j=64` 起调用 `Model::predict`；DZip `codec.cpp` 的 `encode_raw`／`decode_raw` 同样从 `i=64` 起预测。因此原短流每次 encode／decode 均为 64 个 uniform 符号、0 次神经预测、0 次在线训练；其结果只覆盖完整模型／容器与均匀概率短流成本。两份冻结 contract 明确原 source pipeline 要求至少 65 符号，较短输入属于具名 native 安全扩展，不能凭原短流性能声称神经网络性能。

DZip 只有 `mode=COMBINED && predicted % 128 == 0` 才调用 `adapt`，一次组装 128 个重叠 64-wide context 与 128 个 label，随后 `Network::train` 执行一次完整 forward／backward 和一次 Adam 更新；默认 `BOOTSTRAP` 在任何长度都不在线训练。训练默认标量 TensorFlow Adam：lr=5e-4、beta1=.9、beta2=.999、epsilon=1e-8、microbatch=0。DeepZip 的模型训练是外部模型作者工具，不是 codec 内执行工作。DZip 此处默认输入相关 seeded／untrained 初始模型，也不能称为导入已训练 checkpoint。

独立补充生成器为 `benchmark/tools/generate_neural_core_experiments.py`，冻结清单在 `benchmark/experiments/native-neural/design.json`。保留原 24 配置、其请求分母及全部短流证据；新增 4 配置、6 请求：DeepZip biGRU prepared／fresh 各 1 请求，DZip prepared／fresh 各包含 BOOTSTRAP 与 COMBINED 两方法。统一使用现存原 fixture 的完整 257 个 uint8 符号，不截断、不补齐、不复制；该选择由源码阈值在正式运行前决定，没有依据性能结果调参。

对每个完整 encode 和每个完整 decode，N=257、lanes=1 得到 64 个 uniform 符号和 193 次神经预测。DZip COMBINED 在 index 191 的第 128 次预测后执行 1 个 128-window 训练批／1 次 Adam 更新，随后还有 65 次预测使用更新后的权重；其余 65 个 predicted tail 不触发部分训练。N=192 虽能触发一次训练，却恰好在最后一个符号之后，故这里采用完整 257 验证更新状态进入后续码字。BOOTSTRAP 和 DeepZip 均为 0 个在线训练批。上述次数来自源码推导，未增加运行时计数器，不能冒充已测分支次数。

补充配置均为 2 sessions × 7 rounds、2 warmups、600s timeout；DeepZip 每轮 8 loops／256 MiB batch budget／单线程，DZip 每轮 2 loops／1024 MiB／显式三线程与系统 libstdc++。共 84 个名义正式 trial、336 个名义测量操作；资格与独立解码不包含在此名义分母。生成阶段仅静态加载数据、解析 registry／配置并固定 hash，不执行 codec。正式运行与逐产物验证由中央执行，补充设计与原短流分开保存和解释。

源码依据：`adapters/completed_rewrites/vendor/deepzip/src/deepzip.cpp:153`（group 预测循环）、`:230`（lane 划分），`adapters/completed_rewrites/vendor/dzip/src/codec.cpp:67`（adapt）、`:142`／`:155`（对称编解码预测／训练），`adapters/completed_rewrites/vendor/dzip/src/nn.cpp:501`（forward）、`:521`（train）与`:572`（单个 Adam step），`dzip_nn.hpp:13`（默认训练参数）。补充 design.json 固定这些实际阅读源码的 hash。

正式运行前，ABBA／fABBA 的 direct encode 被修正为 build-local `encode_only`，去除原 `transform` 中不被编码消费的整份 reconstructed 及 quantized decoder pieces。DeepZip／DZip 与这两个 codec 共用 `adapters/completed_rewrites/native/binding.cpp`，所以即便神经算法、输入、参数和阈值不变，补充设计固定的完整 TU hash 也必须更新。初版清单原样保留为 `benchmark/experiments/native-neural/design-before-symbolic-fix.json`（SHA256 `ababbaab6ad10e3b3342e659b6d94f3a8a6ffa5e1be2221ca36c12c187986cd0`），现行 `design.json` 为 `f9eb9aa302b6a34b7c62c82235c7ead890c00291b167406023e24ed79e690310`。唯一内容差异是该 binding 源参考从 `5740e843351292d4d3fed50cef535a47ec01a985b18ffb2e5d5b0597f590bbea` 更新至 `8e446c2fc322dc82e959b0fad7429af9d53a96346b6f8d92ac4eaf4997dd9330`；全部请求与协议字段逐项相同。

这次重新生成只执行静态输入／registry 校验与 hash 固定，对已存在的 4 份补充 TOML 只比较内容、不写入；原 24 份及补充 4 份 TOML 的 SHA256 和修改时间均逐一确认不变。旧源码身份的 257 符号短诊断继续单独保留，仅用于问题诊断，未纳入现行身份的正式性能结果；新源码的构建、资格、测试及正式运行仍由中央串行执行。
