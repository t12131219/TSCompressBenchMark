# 首批 Unique 构建对账

范围：首批 **12 条 selection、11 个来源工程**（Zstandard / XZ 共用一个）。本表登记**哪些源码与构建条件被保留、哪些仅编译、哪些实际运行**。来源方的历史功能测试见[证据索引](first-batch-unique-evidence.md)，不是本工程的正式计时或阶段验收。

## 版本与比较方法

- 选版以基线表“发布包 SHA256”、Unique manifest 的 `archive_sha256`、来源锁 `sources.*.archive.sha256` 和实际归档为准。
  `selection_note` 是原文溯源字段，不参与归档定位；ALP、pcodec、Titchy、ZFP、Huff0、CORAD 的备注嵌有历史哈希，不能用来替换结构化归档锁。
- 比较了 Unique `fix_ReWrite` 的实际源码树（含 CMake、README、功能报告及随包依赖），以及 `fix_Release/<工程>/unique-v1/` 的源码包、文件清单和验证 JSON。11 个工程的 **1,385 个归档成员文件**在 `fix_ReWrite` 与各自发布包内逐字节一致，无额外文件；11 个归档、源码清单及发布验证与 TSBench 本地锁定原件一致。邻接工程只用于本次查阅，正常构建不访问它。
- Unique 总表 `docs/VALIDATION.json` 的 `isolated_builds` 中，**ALP、pcodec、Sprintz、Titchy、ZFP、Huff0、CORAD** 的摘要归档哈希不是当前选版；以逐包 `validation.json` 为准，Sprintz 另有同哈希的 `docs/validation/sprintz-simd-query-20261110.json`（含 SIMD、标量及 sanitizer）。Capability fixes、旧 source audit、能力矩阵、后端检测用于区分变更和已知限制；无归档身份的检测记录不视为当前 TSBench 运行。尤其是 Unique 根 README 的“pcodec Rust 默认关闭”与当前逐包 `PC_SOURCE_BACKEND=ON` 冲突，以冻结 CMake 为准。
- 基准证据：[同一次禁网审计](../../results/m0-native-plan-20261118-r1/)的 `abi-build/`、`abi.log` 与 `release-builds/`。两边都是 Linux x86_64、CMake 3.22.1、GNU 11.4.0、Rust/Cargo 1.94.0、Release（本次 C/C++ 的 `-O3 -DNDEBUG`）。对锁定目标及其实际编译的 C/C++ 库依赖比较 `compile_commands.json` 的源文件、编译器及有序参数；归一化解包根和对象输出路径；SElf* 单独比较生成的 `flags.make`、`build.make`。**287 个库翻译单元**的选项、宏及头文件搜索次序一致。另核对主要共享库的 `link.txt` 和 pcodec 的 Cargo 构建命令。链接输出位置和对象路径不同；这是同次构建的命令/依赖对照，不是二进制哈希、跨工具链或性能等价证明。来源报告未保存的历史 flags 也不据此补填。

## 逐工程构建闭包及窄化范围

| 选项 / 锁定目标 | TSBench 保留的构建细节（实查本次生成命令） | 运行边界与不能推出的结论 |
|---|---|---|
| 9 ALP Auto · `alp_native`（8 单元） | 原 CMake：FastLanes 四个单元和 fused scalar；独立 AVX2 及 AVX512BW/DQ/F 对象；各 fused x86 对象及 scalar 保留 `-fwrapv`，普通 dispatch 单元不带强制 ISA，保留 `-fno-strict-aliasing`、禁 fast-math/FMA contraction。NEON/SVE 为条件 ARM 对象，本次没编。 | 本机 f64 AVX2 decimal 有实际调用，f64 AVX512BW 对象已构建，但当前宿主未提供 AVX512F/BW/DQ，显式请求按预期拒绝；该条件原生路线保留、待兼容宿主实际验证；不把 f32、RD/raw 或 ARM 路径算作已实跑的该向量内核。 |
| 11 pcodec · `pcodec_c`（1 C 单元 + Rust） | 显式 `PC_NATIVE=ON`（C 侧 `-march=native`）、`PC_SOURCE_BACKEND=ON`，静态 Rust 后端 + `dl` / `pthread` / `m`；两边 Cargo 均为 `build --offline --locked --release`，随包 `.cargo/config.toml` 以 `vendor/` 替换 crates.io，`pco`、`better_io` 是本地 path；需要实际的 `cc` 和 Rust/Cargo，不从 Conda base 或远程补组件。 | CNativeAuto 与 SourceAuto 分别调用；CNativeAuto 在全构建中共享解码器，不等于另做 C-only 构建或关闭 Rust；`pthread` 链接或 `-march=native` 不证明多线程或实际某种 SIMD。历史 CUDA 编译不纳入当前 CPU 构建。 |
| 19 Sprintz-FIRE · `repaired_codec`（22） | 原 CMake：`selected_sprintz` + vendored `selected_huff`，含 `query_simd_delta.cpp`、`query_simd_fire.cpp`；保留 `-mavx2 -mbmi -mbmi2 -mlzcnt -mpopcnt -fno-strict-aliasing`。 | 强 ISA 是整个冻结 codec 的运行前提；lowdim/tail 标量查询不是无 AVX2 整库回退。`repaired_worker` / `sprintz_query` 是同包 CLI，所选库审计不是重跑 CLI 或 18,004 条来源查询。 |
| 85 Titchy · `titchy_c`（4） | 原 C11 库含 `common.c`、`titchy_c.c`、`stream_c.c`、`reader.c`，不是删掉 packet/reader 的纯批构建。 | 当前批 worker 和原生 packet/file reader 直调分开验证；不从 reader 的逻辑读量推断物理 I/O，不将 `titchy_stream_bench` 当运行依赖。 |
| 7 Gorilla · `gorilla_c`（2） | 原 C11 库同时编译 `gorilla.c` 与 `stream.c`，链接 `m`；`gorilla_c_cli` 不是选定共享目标的依赖。 | T+V worker 与 append/snapshot/resume/iterator 直调；不由同库构建推断衍生 T/V 或通用 seek。 |
| 31 ZFP · `zfp_native_c`（36） | 显式 `ZN_WITH_OPENMP=ON`、`ZN_WITH_CUDA=OFF`；原 `native_zfp`（编码、解码、bitstream）保留 `ZFP_ROUNDING_MODE=ZFP_ROUND_NEVER`，`-fopenmp`、`libgomp` 可见；C 包装同时编译 field 与 `array_c.c`，保留上游 C++ array headers/接口目标。 | worker 基线仍串行；OpenMP 是指定原生 field 的独立直调证据；上游 C++ array 专用 CLI 不属于本次选定库构建，CUDA 未编入本次 TSBench，也没有 GPU 运行。 |
| 40 Zstandard / 39 XZ · `lzbench_native`（154，共享） | 原 `vendor/sources.cmake`、随包配置头及 `ln_kernels`；`HAVE_BUILTIN_CTZ`、`ZSTD_MULTITHREAD`、`BROTLI_EXPERIMENTAL` 和 `Threads::Threads` 未删除；库包含 `api.cpp`、`extended.cpp`、`trace.cpp`。Zstd 插件与 XZ 直调复用同一个库；TSBench 明确为直调诊断额外构建 `feature_worker`。 | 仅指定 Zstd/XZ 路径计入覆盖；库含其他 codec 不表示那些 codec 已接入。编译线程能力不等于每次调用启用；实际 worker 证据见对应合同。 |
| 4 SElf* · `selfstar_c`（1） | 集成侧不直接引入整个 CMake，避免其 `bench_c` 与 pcodec 同名冲突；用冻结 `src/selfstar.c` 建同名库。已对照 C11、PIC、禁 fast-math/FMA contraction、公共和私有 include、`--no-undefined`、`m`。 | 不导入其 `bench_c`；若更新归档，须重新核对这处手写目标，不能自动假定新发布 CMake 的依赖/flags 已继承。 |
| 29 Huff0 · `reference`（11） | 原 CMake 构建 `reference_core` 和 `reference`，保留默认 `ENTROPY_DYNAMIC_BMI2=ON`；没有给整个目标加 `-mbmi2`。 | 另有 `OFF` 的便携对照，不当成同一个构建；BMI2 走实际分派，不能从 `ON` 推断任意主机/用例实际进入该路径。 |
| 87 PBEPLA-RR · `tba_native`（44） | 原库保留 `pbepla_rr`（包括 `swing_stream.cpp`）和同包的 `kangaroo`、`actsd`、`selected_zstd`；该 Zstd 属于此归档闭包并以 `ZSTD_DISABLE_ASM` 构建，不能用 lzbench 的 Zstd 产物随意替换。 | 只接 PBEPLA-RR；回放接口非空样本三遍输入，不因编译了 `swing_stream.cpp` 就记为在线单遍流，也不把同库兄弟算法视为已接入。 |
| 80 CORAD · `corad_c`（4） | 原共享库含 model、codec、C ABI、training，链接 `m`；`corad_native`/`corad_train` 是包内 CLI，不是库依赖；Source 桥依赖由已准备的 `tsbench` 提供，不是 C 库编译依赖。冻结包含历史 `train.cpython-311.pyc`，直调显式以 `python -I -B` 执行原样 `train.py`，传本地解包根，不使用打包缓存或邻接 Unique。 | `BUILD_TESTING=ON` 用于原生 C 推理、C 训练和独立 Source 桥对照，尚没有 worker 插件；原生训练与 sklearn 不能视为同一数值实现。 |

## 何时重建、何时复用

1. **日常禁网预检**：`tools/probe_offline_m0.sh` 从空构建目录对 TSBench 集成目标编译一次，保留全工程编译数据库，然后在这次构建上执行统一原生预检和应用回归。无需再构建一套相同的来源库来运行同一组探针。
2. **来源包独立性核验**：确需证明所选源码包在 TSBench CMake 工程之外能独立配置并构建其锁定目标时，使用 `tools/probe_offline_m0.sh --release-builds-only`（参数、禁网迁移和空输出要求相同）。该模式只跑来源包核验，不构建 TSBench、不运行原生套件；它不声称构建 release 的全部默认 CLI 或运行来源方测试。新增/替换归档、改变受支持工具链/平台或依赖闭包，或交付合同明确要求时，按变更范围补验。未变更的归档和适用构建条件可引用[已有审计](../../results/m0-native-plan-20261118-r1/release-builds/audit.json)。
3. 旧合并脚本每次在集成构建之后又执行了一遍全部 11 个独立构建；历史日志中这部分 configure/build 合计 **45.62 秒**（仅该次开发构建）。现在按要验证的主张分别运行，**不移除**独立发布验证，也不共享构建产物来假装验证独立性。改动不影响 codec 配置、运行线程/ISA、功能计划、正式计量或验收范围；不同身份的变体不可复用为同一证据。

调整后的[集成禁网验证](../../results/m0-build-review-integrated-20261118-r1/)通过 35 项 Python 测试和统一预检的 19 个探针（36 组均有结果），没有生成 `release-builds/`。新编译数据库包含之前仅在 `flags.make` 留证的 SElf*；再与已有独立构建的编译数据库比较，全部 287 个库单元的规范化选项仍一致。此处未为生成新记录再运行同样的独立构建，也未改动正式资格。

v3 数据集成的[复核记录](../../results/m0-corpus-v3-20261118-r1/build-command-recheck.json) 绑定同一个来源锁和原发布审计。按已有对象筛出来源独立构建实际编译的目标，以“目标＋归档内路径”对照；仅归一化源码根、对象输出位置和共享库输出位置，不重排 flags/库依赖。**287 个 C/C++ 库单元、11 个选定共享库的链接命令，以及 pcodec 的 Cargo 命令均匹配**。新增 TSBench 诊断目标与所选库分开记录；此轮没有重编 11 个独立发布包。该记录不是二进制等价、来源方功能重跑或 TSBench 正式运行资格的证明。
