# Sprintz 原生发布包替换接入（2026-10-17）

已删除原有 Sprintz 活动实现与全部旧登记，接入 `sprintz-family-native-20261017` 的四个主算法；默认 `native_core`、辅助 `native_api` 和完整对象路径均已验证。该结论是限定原生移植的 Bench 绑定验证，未签全上游 FULL_PARITY 或新实现的 FORMAL 性能资格。

| 当前 key | 预测器 | 熵编码 |
|---|---|---|
| `sprintz-delta` | Delta | 无 |
| `sprintz-fire` | FIRE / xff | 无 |
| `sprintz-delta-huffman` | Delta | 作者 Huff0 组合 |
| `sprintz-fire-huffman` | FIRE / xff | 作者 Huff0 组合 |

两个同名主键已经更换 source／implementation／build 身份。旧 `sprintz-delta-u8`、`sprintz-fire-u8`、`sprintz-fire-huff0` 登记及别名均不保留；旧 `adapters/sprintz`、本地补丁、旧来源卡和活动 build indexes 已移除。当前注册 44 个真实 CPU codec，另加 raw-store。

## 来源与替换

已完整阅读本包 README、VALIDATION_REPORT、CONTRACT、FORMAT_AND_SAFETY、能力矩阵，以及前期完整阅读的 V3.0／V4.0；先写 [N0 计划](PLAN.md)。文档中“尚未接入 Bench”描述包交付时状态，本轮用户明确授权替换接入。

发布包 SHA-256：`757789b014f2e5f7804ea88b68ce22bc3b5f86b9121626861c2c7209f4e5e624`。Sprintz 来源 `dblalock/sprintz@a056cdb67d049669875ab5487359aca99ae873ea`；作者 Huff0 包装来源 `dblalock/lzbench@580c4f085381f31b1ad669525ed04e63cbc385f3`。核心已是 C++，路线是 NATIVE_PORT。

1593 个 runtime／build／测试／文档／原版 oracle 来源文件逐个与发布包成员对照，按普通文件冻结；消费核心无修改。构建前逐项校验 [FROZEN_SOURCES.json](../../adapters/sprintz_family/FROZEN_SOURCES.json)。API／绑定为 baseline x86-64 TU，native／dispatch 独立启用 AVX2、BMI1、BMI2、LZCNT、POPCNT，调用前执行完整 CPU 检查。当前不支持 ISA 回退。

旧目录（含未提交的 direct_core.inc 和 bounded 修改）、五张卡、三张旧来源卡及原构建配方均保存在 [替换前归档](legacy-before-replacement.tar.gz)，哈希见 [归档清单](legacy-archive.json)。历史结果与冻结设计仍绑定旧身份，不据新包回签。四份原 native-all 整数设计按设计 hash 原样保留；新请求放在独立的 [Sprintz 配置目录](../../benchmark/experiments/sprintz-native-20261017)，对应关系见 [迁移记录](configuration-migration.json)。其他当前可运行示例迁移到新主键和独立 output 名称。

## 输入与恢复合同

限定 Linux x86_64、GCC／Clang 支持的整数位模式、单线程、row-major；接受 unsigned／signed 8/16 位、rank 1/2、1–128 维、总输入 <=65536 bytes。每次重置预测器；不隐式浮点量化、扩宽、外部分块或更换算法。对象矩阵逐值按位恢复，并保留 signed dtype、shape 和 C/F 布局；原生 core 接受 C 布局，F 布局必须明确使用对象入口。C1 flat descriptor 也保留独立 API 已验收的不完整行能力。

`path=0` 自动 RLE，`1` 强制 general RLE，`2` 强制 lowdim RLE（8 位维度<=4、16 位<=2）；Delta 另有 `3` bitpack、`4` noRLE；FIRE 另有 `5` noRLE，限8位。非法组合在 Python 参数或原生几何检查拒绝；旧无效 block_size 参数不再开放。Query、历史1D／预测器 primitive、其他熵组合和 ARM 等不登记。

core 接收真实整数物理字节，调用发布包 `sz_bound/encode/decode`，两方向均返回 caller-owned 存储；内部仍有包原有暂存、初始化后缀、结构扫描和分配。**所有这些工作与 SZF1 序列化都在操作计时内。** C1 增加 SZI1 输入描述符，压缩输出与 core 相同；一次 compress + 一次零字节 finalize，失败 produced=0、输出不变，可重试／reset。

发布包 raw 需要配置与 expected_bytes；Bench core 冷 decoder 接收 `{}`，因此新增 24 字节 SZF1 恢复头，保存 width、predictor、Huffman、path、dimensions、decoded bytes、payload length 和零 reserved。其后为完全未改动的 native payload。完整输出（头、native metadata、尾部、Huff0 包装及填充）全部计入 codec_complete_bytes／FinalBits；外层对象封装另按对象实存计费。布局、逐字段定义、原子失败语义见 [绑定说明](../../adapters/sprintz_family/README.md)。

SZF1 没有 CRC；完整结构和输出长度经安全 API 检查，结构合法的内容修改仍可能成功解码。本接入不宣称内容认证或任意损坏检出。冷恢复不依赖编码器参数；解码器校验库身份及请求几何，参数从实际帧恢复。

## 实际验证

| 本轮执行 | 结果 |
|---|---|
| 冻结包独立 CMake 重建及 ctest | 2/2；80,448 往返案例及 negative／allocation campaign |
| 新构建未修改原版 oracle、独立发布库与 Bench 绑定差分 | 774 例；722 字节一致，52 为 raw16 尾字节截断修复 |
| 原版截断流送入安全 API／Bench C1 | 52 全部拒绝，输出不变；未计 source→port 成功 |
| standalone 与 Bench payload 精确比较、双方解码 | 774 例，C1 含不完整行；direct 单独验证完整行前缀 |
| 冻结 canonical／真实整数数据 | 18 份 canonical ×4 + national_illness 原始三计数列 ×4，共76例 |
| C1/direct 专项 Python 测试 | 297 passed；覆盖 signed、高位、路径、空／短／尾、64KiB、超界、容量重试、故障、畸形、冷参数恢复 |
| 完整 Python 回归 | **1259 passed**，无失败或跳过 |
| 对象 C/F × u8/i16 ×整块／分列分块 ×4算法 | 32 对象，由独立新进程 CLI 恢复 |
| core/API × prepared/fresh × u8/i16 ×4算法 | 32组合、96实际产物，逐份核验与独立冷恢复；完整大小逐项核对 |
| ASan＋UBSan＋LSan | 96绑定案例，detect_leaks=1，最终stderr为空 |

52 个原版 raw16 长度差异由新 oracle `enc16plus` 补回其已写出但未计入的尾字节后，与发布包输出一致；发布包 payload 可由未修改原版 decoder 恢复。作者 Huffman 的 `reported_elements*2+1`（含偶数长度零填充）规则原样保留。不能把截断源流和修复流笼统称 BYTE_IDENTICAL。

真实数据仅冻结 `AGE 0-4`、`AGE 5-24`、`NUM. OF PROVIDERS` 三个原始整数计数列，逐值确认 u16 范围，不是浮点量化或整个 CSV 的资格。本轮76例中的真实数据为一个原始三列布局 ×4；独立包报告中的12配置不是本轮另做12例。

证据：[源码差分](source-qualification.json)、[逐例哈希](source-cases.jsonl.gz)、[对象与原生产物](object-native-qualification.json)、[sanitizer](sanitizer.json)、[完整测试日志](full-python-suite.log)、[证据与当前构建索引](evidence.json)。包外审计原件另存 [standalone-package-audit.json](standalone-package-audit.json)，不将其跨编译器／TSan／fuzz 资格冒充本次绑定重跑。

初轮导出符号隐藏导致加载失败的日志保留；已修正绑定可见性，native 核心仍隐藏。Sanitizer 首次 harness 错把无 scratch 分配的短拷贝路径当作必然触发故障注入，随后按真实分配路径修正断言；没有修改核心。沙箱 ptrace 导致 LSan 自身退出的记录也保留，最终同一 instrumented 二进制在无 ptrace 环境启用 LSan 通过。[初始诊断](initial-diagnostics)不作为通过证据。

## 复验

```bash
PYTHONPATH=benchmark/src python -m tsbench build sprintz-delta sprintz-fire sprintz-delta-huffman sprintz-fire-huffman
cmake -S adapters/sprintz_family/vendor/sprintz_family -B build/sprintz-family-integration/reference -DCMAKE_BUILD_TYPE=Release
cmake --build build/sprintz-family-integration/reference -j2
ctest --test-dir build/sprintz-family-integration/reference --output-on-failure
cmake -S adapters/sprintz_family/vendor/sprintz_family -B build/sprintz-family-integration/baseline -DCMAKE_BUILD_TYPE=Release -DSZ_CORE="$PWD/adapters/sprintz_family/vendor/sprintz_family/reference-source/upstream/core"
cmake --build build/sprintz-family-integration/baseline --target sprintz_oracle -j2
PYTHONPATH=benchmark/src python benchmark/tools/qualify_sprintz_family.py
PYTHONPATH=benchmark/src python -m pytest benchmark/tests/test_sprintz_family.py -q
PYTHONPATH=benchmark/src python docs/sprintz_integration/qualify_objects.py build/sprintz-family-integration/products-new
PYTHONPATH=benchmark/src python docs/sprintz_integration/run_sanitizers.py
PYTHONPATH=benchmark/src python -m pytest benchmark/tests -q
```

LSan 需要无 ptrace 执行环境；不要关闭 detect_leaks 来将环境失败改记成功。提供 [四算法示例](../../benchmark/examples/sprintz-family.toml)；`path` 是显式实验配置，不在测量后自动选择。本轮未运行新实现 FORMAL 吞吐排名，不继承旧版本性能。
