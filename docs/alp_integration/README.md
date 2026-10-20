# ALP / ALP-RD safe-v1 接入报告

日期：2026-10-17。**原有 ALP / ALP-RD 已从活动源码和构建中删除，替换为独立验收发布包 `alp-cwida-safe-v1-20261017`。当前两个入口均已完成本机 portable profile 的 Bench 接入验证。** 路线为 `NATIVE_PORT`；本报告签署当前绑定的限定范围资格，不签署上游 `FULL_PARITY` 或正式性能结论。

## 来源、替换与身份

消费用户指定的同级独立工程发布包，经完整归档 SHA-256 和逐文件校验后冻结。上游为 cwida/ALP `31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce`，MIT；发布包 SHA-256 为 `e5766bc2ffbcbb4f9d503058632b56bc81c85225876646b5a495678c38650ec7`。

- [冻结清单](../../adapters/alp/FROZEN_SOURCES.json)记录实际消费的 56 个文件、归档成员及 hash；[vendor 副本](../../adapters/alp/vendor/alp_safe_v1/README.md)中的公开 API、codec、FastLanes、文档和测试保持发布包原字节。既有 `safe-v1.patch` 已应用，不在 Bench 构建时再次应用。
- [原接入归档](legacy-alp-before-safe-v1.tar.gz)保存替换前 `adapters/alp`、两张 codec card 和旧 source manifest，包含当时未提交的 direct 修改；SHA-256 为 `48da6ed2649d41163fdb551d7a75ac31ed3fb95b0be5e343cf74ce6d6533b05b`。旧 vendor 与三个旧补丁已退出活动目录。
- [新来源登记](../../registry/sources/alp-cwida-safe-v1.artifact.json)与 [alp](../../registry/codecs/alp.json) / [alp-rd](../../registry/codecs/alp-rd.json) card 使用新来源、绑定及格式身份。source ID 为 `v2:source-artifact:sha256:26e61e9379e9be7911d5d2eb10cabcef2b72e40868b055a06326e8c204c2d118`。
- Python bridge 校验新实现 manifest，拒绝从其他 build root 加载同 key 的旧库。旧源登记、构建与正式结果保留历史身份；不会自动升级为新实现结果。原[一致性核对报告](../alp_consistency_20261017.md)描述的是替换前状态。

| 当前入口 | 实际行为 | 默认完整原生输出 |
|---|---|---|
| `alp` | safe-v1 自适应十进制 ALP / RD | `ALPRW001`，包含 header、恢复参数、字典、exceptions、padding 和 CRC |
| `alp-rd` | safe-v1 强制 RD | 同格式，method 为 RD |

核心不再采用旧 `ALP1` / `ARD1` 格式，也不保留旧 forced decimal 语义。历史 wire 需使用原身份解码环境，本次新绑定不提供旧格式兼容解码。

## 入口与成本

[绑定源码](../../adapters/alp/native/tscb_alp.cc)及 [direct 入口](../../adapters/alp/native/direct_core.inc)只调用冻结的 `alp_port.h` C API，不修改独立核心。详细几何、容量和计时合同见[验证计划](PLAN.md)。

`native_core` 按任务 f32/f64 的 C/F **物理顺序**处理一条标量流，不声称联合多变量预测；直接返回完整 `ALPRW001`。`tsbench_core_storage()=3`，编码和解码均写 caller buffer。每次编码仍包含冻结 API 内部分配、复制、padding、sampling、建模、编码、序列化与 CRC；解码保留完整格式检查及 CRC。prepared 仅将合法 context/bound/caller 容量准备移出主时钟，fresh_request 沿用框架规定的首次请求边界。输出按真实 used 全量计费，`FinalBits=8*used`，无免费外部模型或 RAW fallback。

辅助 C1 / 对象路径保留 `TAI1` typed SOA 输入，输出新的 `APS1` 列容器：16 字节头（magic、width、reserved=0、LE columns、LE rows），每列跟随 LE u64 长度和完整 `ALPRW001`。所有列成功后才发布输出；要求一次零字节 finalize，支持显式 reset，拒绝非法重复调用。对象完整 wire 包含 APS1 及恢复目录。**辅助 `native_api` 的空间主指标暂保持 null**，沿用框架对尚未单独映射纯 ABI 目录的保守政策；它的时间也包含整个 C1 操作。可选内部 timer 只环绕完整逐列 `alp_port` 调用，不包含 APS1 分配拼装，不能替代 API wall time。`native_core` 完整输出大小可直接核实。

本次开放 LP64 little endian、IEEE f32/f64、单调用线程、portable（registry 为 `isa=SCALAR`），总元素上限 `2^24`；不宣称已实测满上限。AVX2 profile 与 runtime dispatch 未开放，非法 dtype、参数、外部模型、FP 环境或资源请求明确拒绝。

## 本次实际验证

独立 reference 从冻结副本另行全新 CMake 构建，**不包含 Bench shim**。它与 Bench 使用同一 safe-v1 核心，因此本次对照证明绑定、构建与共同格式一致，不能作为未修改上游的全域一致性证明。原独立包 N0–N5、安全修补及其已有平台结果保留在[独立验收报告](../../adapters/alp/vendor/alp_safe_v1/reports/QUALIFICATION.md)。

| 验证 | 本次结果与覆盖 |
|---|---|
| 独立 reference ctest | 3/3 PASS：contract、C consumer、allocation failure |
| 针对性 Python 回归 | 155 passed；含新增 safe-v1 专项及现有浮点 direct 测试；无失败/跳过 |
| 完整 Python suite | **798 passed，0 failures/errors/skips**，76.70 s |
| 完整独立差分 | **284 case、10,004,036 个处理值**；完整字节相等、双向解码、全部 C1 列 frame 相等及逐位恢复 |
| reference CLI 冷恢复 | 28 个新进程通过，只消费完整 frame |
| 真实原生批次 | 2 方法 × core/API × prepared/fresh，共 8 组合；每组合 1 warmup + 2 操作，逐份计时外验证和独立恢复 |
| 绑定 sanitizer | 两方法各 22 个 dtype/长度 case，均 PASS；整个绑定和全部核心 TU 使用 ASan/UBSan/float-cast-overflow，并启用 LSan |
| 对象及 CLI | 16 组合全部通过：2 方法 × f32/f64 × C/F × 整块/分列分块；每个保存 wire 均由新进程 CLI 独立逐位恢复 |

差分语料采用冻结输入选择器的完整规则：ETTh1、ETTh2、ETTm1、ETTm2、exchange_rate、national_illness、weather 全数值列、全行、原顺序，显式 f32/f64，并含 synthetic / IEEE 位模式。两方法各处理 142 case、5,002,018 个值；总数包含两方法重复处理同一输入，不表示一千万个独立样本。自适应 `alp` 实际经过 4012 个 ALP vector 和 972 个 RD vector；forced RD 为 4984 个 RD vector，RAW 为 0。

边界覆盖 N=0/1/2/31/1023/1024/1025/2049/102399/102400/102401，NaN payload、sNaN、±Inf、±0、subnormal、任意 IEEE bits；另验证容量精确/差一、guard、未对齐、overlap、CRC/截断/多余字节、错误几何/方法/旧 magic、参数/模型/FP/资源拒绝、失败原子性及重试、reset/finalize 生命周期、旧同名库拒绝。对象分块用 257×3 输入、chunk_rows=127，每对象实际 9 个独立 part。

首次普通沙箱 sanitizer 执行在退出阶段遇到 **LSan 不支持 ptrace**，原失败日志保留。随后在非 ptrace 环境按相同二进制、`detect_leaks=1` 重跑，两方法均 exit 0，无 sanitizer 报告；未通过关闭 LSan 消除失败。绑定 sanitizer 不表示外部系统 runtime 全部插桩。

## 构建与复验

在仓库根目录执行；`python3` 使用本次 Python 3.11 环境。更换环境须使用新的构建/运行身份。

```bash
PYTHONPATH=benchmark/src python3 -m tsbench build alp alp-rd

cmake -S adapters/alp/vendor/alp_safe_v1 \
  -B build/alp-safe-v1-integration/standalone \
  -DCMAKE_BUILD_TYPE=Release -DALP_PORT_AVX2=OFF -DALP_PORT_ORACLE=OFF
cmake --build build/alp-safe-v1-integration/standalone -j2
ctest --test-dir build/alp-safe-v1-integration/standalone --output-on-failure

PYTHONPATH=benchmark/src python3 -m pytest -q \
  benchmark/tests/test_alp_safe_v1.py benchmark/tests/test_core_floats.py
PYTHONPATH=benchmark/src python3 -m pytest -q benchmark/tests

# --out 必须是新目录；corpus 原文件只读。
PYTHONPATH=benchmark/src python3 benchmark/tools/qualify_alp_safe_v1.py \
  --corpus /home/fzg/PycharmProjects/材料/TSBench_Corpus \
  --reference-build build/alp-safe-v1-integration/standalone \
  --out build/alp-safe-v1-integration/corpus-recheck
PYTHONPATH=benchmark/src python3 docs/alp_integration/qualify_objects.py \
  --out build/alp-safe-v1-integration/object-recheck
```

sanitizer 使用[专用 harness](binding_sanitizer.cc)，两方法分别以当前 `_alp_command(output,'sanitizer',key)` 配方去掉 `-shared`、加入 harness TU 后调用 `tsbench.build._compile_native`，最终执行 `ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 <binding_test>`。实际每个 TU 的完整命令、依赖及二进制 hash 保存在下述证据中的 `sanitizer/<key>/build.json`，可按原命令重放；LSan 运行需要可用的非 ptrace 环境。

| 当前 release | BuildID | 二进制 SHA-256 |
|---|---|---|
| alp | `41f8b9a556c172ced97b4c9d6165b349017b9d34544f9d18e27a918e1b70badd` | `719d1aae54c6559d4360644d1a6b77b54242c28cc431b2c6274de6ab9997ea38` |
| alp-rd | `f3f772b58bb0f7edd5cee5a4670c66a4c5e7447d00d4c3ea1c7dafe9948e398c` | `ccb26e3503ac6999d802583daec542ef283e101ce982d5a6c5b09d66df0307dd` |

独立 reference SHA-256：`633bc478e458a65706b82d3d593e998f7791d2bc838bdb05ea73ff9415d5d959`。默认 `build/tsbench/{alp,alp-rd}.index.json` 已指向新库；完整 source、实际编译依赖、工具链、runtime 解析记录随 build.json 保存。

[证据索引](evidence.json)绑定本次日志、JUnit、284-case 明细、16-case 对象明细、构建记录、验证脚本与当前源码的路径和 SHA-256。原始产物位于 [build/alp-safe-v1-integration](../../build/alp-safe-v1-integration)，包含 canonical 输入、完整 frame、wire、CLI 恢复输出和实际运行日志。

## 结论范围

当前 `alp` / `alp-rd` 已使用 safe-v1 并取得本次限定 profile 接入资格。测试与短批次是资格验证，**没有重跑正式吞吐实验**，旧 4872-trial 表不代表这次替换后的性能。独立包已有 AVX2、AArch64/QEMU、TSan、50,000 次 fuzz 和可复现构建结论不能自动继承给 Bench；本轮未执行这些 Bench 扩展验证，也不声明新的 Bench 字节可复现构建。更换核心、绑定、编译器、ISA 或 runtime 后按实际依赖重验并生成新身份。
