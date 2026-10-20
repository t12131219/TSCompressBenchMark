# ALP / ALP-RD 与独立 safe-v1 包的一致性核对

后续状态：用户已要求替换旧接入；本文保留替换前核对事实。当前safe-v1接入另见[接入报告](alp_integration/README.md)，旧源码已归档。

日期：2026-10-17。结论：**同源，但当前 Bench 接入与独立 safe-v1 包不等价；独立包尚未被当前构建配方消费。** 本文是源码核对与隔离数值实验记录，不是重新签署完整资格或正式性能结果。

本次完整阅读独立包 README.md、reports/QUALIFICATION.md，并核对 CONTRACT、SOURCE_DEFECTS、HANDOFF、SOURCE_LOCK、patches/INDEX 和 CMake/公开 API/实现；工程规则对应 V3.0 §114–116 及 V4 计划中的 ALP 身份、native_core 与计时边界说明。

## 1. 来源和实际消费路径

双方均来自 cwida/ALP 提交 `31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce`，MIT。Bench 的 `adapters/alp/vendor/alp` 共 14 个文件，逐文件比较均与独立包冻结的原版源码相同。其中 12 个与独立包 patched vendor 相同，encoder.hpp 与 decoder.hpp 不同。

Bench 实际配方 `benchmark/src/tsbench/_native_recipes.py::_alp_command` 将自己的 vendor 复制到构建目录，再依次应用自己的三个补丁。将这一过程在 `/tmp` 副本重放成功后，与 safe-v1 再次比较，仍然只有这两个头文件不同。

| 文件 | Bench 三补丁后的 SHA-256 | 独立 safe-v1 SHA-256 |
|---|---|---|
| include/alp/encoder.hpp | `9d4eb122b1a6f10191d89f258fa6877aed1c3debe3b62837a2175601400f1930` | `152c5eff98334f38aeaed9ec73e847496be81d85803e7d70bf8b44cdd50ea1f5` |
| include/alp/decoder.hpp | `33aace1b36f3371e7347017c3175421399124c4aa90491d0822be6a44df21afc` | `c4617f50894c11e2646385b14d6abe9e48e7bba20653ae53f95457240ac7745a` |
| include/alp/rd.hpp | `c3f9b2b6f4161b2f3f19341520e3de2976f045b82b4c0188156058fb7dc7e43a` | 相同 |

发布包 `alp-cwida-safe-v1-20261017.tar.gz` 中 `ReWrite/alp-cwida/` 下的 src、vendor、include、patches，以及 README、CMakeLists、QUALIFICATION.md 共 27 个选定文件，均与本次核对的工作目录文件相同。此处没有宣称核验了发布包内所有报告和二进制。

## 2. 行为与合同差异

| 方面 | 独立包 | 当前 Bench |
|---|---|---|
| `alp` | 自适应十进制 ALP / RD | forced decimal；采样选择 RD 就拒绝 |
| `alp-rd` | forced RD | forced RD，RD 核心源码相同 |
| dtype / 分块 | f32/f64；vector 1024，rowgroup 102400；采样前尾块补零 | 相同基本规格 |
| 十进制标量解码 | unsigned 模乘后恢复 signed，再转浮点 | 先转浮点，再乘 factor |
| 浮点转整数保护 | 舍入后再次检查准确边界 | 只有舍入前的浮点类型边界比较 |
| 十进制向量恢复 | generated FALP scalar 实现，来自 src/falp.cpp | UNFFOR 后逐值调用 patched decoder::decode_value |
| 完整格式 | `ALPRW001`，32 字节头、分组描述、CRC | `ALP1` / `ARD1`，不同头/描述，无对应 CRC |
| API | stateless `alp_port_*` | `tscb_*` 以及新增 `tsbench_core_*` |
| FP 条件 | 显式编译约束，入口检查舍入/flush/trap 环境 | 当前 ALP 配方未显式设置相同约束，入口无对应检查 |
| ISA | portable 和显式 AVX2 两种 profile；另有 ARM/QEMU 证据 | 当前 ALP 接入只开放 SCALAR |

当前 `direct_core.inc` 仍调用同一 `encode_typed/decode_typed`。它将物理 typed 输入视作一个序列，选中 RD 时同样拒绝 forced ALP；不能因增加了 direct API 就视作已接入独立 safe-v1。旧对象路径则保留自己的逐列容器。

两种完整格式不能直接互解；即使 RD 核心相同，完整对象字节数和比特率也不能据此视为相同。当前计时包含各自不同的封装、内存及校验工作，独立 CLI 时间不能直接充当 V4 native_core 的正式结果。

## 3. 本次实际执行的隔离探针

使用 clang++，针对 Bench 三补丁后的头文件及 safe-v1 头文件分别编译同一小程序，选项为：

```text
-std=c++17 -O1 -g -fno-fast-math -ffp-contract=off
-fno-strict-aliasing -fsanitize=undefined,float-cast-overflow
-fno-sanitize-recover=all
```

| 调用 | Bench 补丁版 | safe-v1 |
|---|---|---|
| `decoder<double>::decode_value(9007199254740993, 1, 1)` | `9007199254740992`，位模式 `4340000000000000` | `9007199254740994`，位模式 `4340000000000001` |
| `encoder<float>::encode_value<true>(2147483648.0f, 0, 0)` | UBSan：浮点转 int 越界，进程退出 1 | 返回安全 sentinel `2147483647`，退出 0 |
| `encoder<double>::encode_value<true>(alp::ENCODING_UPPER_LIMIT, 0, 0)` | UBSan：舍入后浮点转 int64 越界，进程退出 1 | 返回安全 sentinel `9223372036854775807`，退出 0 |

第一例乘法在 signed int64 范围内，证明两套算术在非溢出例上也不等价。后两例说明 Bench 当前补丁尚未覆盖 safe-v1 修复的转换边界；这不是只比较补丁文字得到的推测。

这些是直接调用真实内部函数的有限反例，不是从 Bench 完整公开入口发现的输入反例；没有据此宣称现有全部数据集回环失败，也没有重新运行独立包约千万值的完整验收。临时源码、探针二进制与原始结果位于 `/tmp/alp-consistency-99xnrk83/`，包括 `probe.cpp`、`probe-results.json` 及两个变体二进制。

## 4. 资格与后续处理

独立包的 N0–N5 结论限定于冻结 safe-v1 profile，不能自动授予当前 Bench。V3.0 §115.2/116.3 要求绑定实际 source、patch、ABI/frame、build/runtime 和输入配置后另行验证。

如后续要求统一，建议以冻结 safe-v1 包为明确消费边界接入，单独登记自适应 ALP 的身份；已有 forced decimal 实现及其历史结果保留原身份。ALP-RD 即使复用相同 RD core，仍需验证新绑定的完整格式、容量/失败、独立恢复、FinalBits 与 V4 的实际计时边界。

本次只新增此核对报告，未替换 Bench vendor、补丁、adapter、registry、构建配方或历史实验结果。
