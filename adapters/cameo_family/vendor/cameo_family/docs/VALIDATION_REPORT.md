# CAMEO family 最终验证报告

2026-10-21 · **REWRITE_DONE / FULL_PARITY**，目标为用户授权的 **cameo-family-repaired-v1**（TP：tp-first-span-v1）。全部50项REQUIRED_PARITY通过，零waiver。最终资格须与匹配的外层归档审计共同生效，机器可读证据为 validation/final_qualification.json 与 PORT_MANIFEST.json。

十算法位于同一cameo-family目录：CAMEO/SIP、VW、PIP、TP、SWAB、Sim-Piece、PMC-Mean、connected SWING、DFT、DWT(DCT-II)。源码、参数、边界、路径合同见CONTRACT.md、SOURCE_MAP.md与REPAIRS.md。原作缺陷及旧BLOCKED资格原样保留；这里没有签署未修改原作的FULL_PARITY。

| 最终执行项目 | 结果 | 证据（相对家族根目录） |
|---|---|---|
| GCC与Clang数据/配置差分 | 各598/598 PASS | validation/differential-release.json、differential-clang-release.json |
| 边界与TP定向回归 | 194/194、80/80 PASS | validation/boundaries-release.json、repair-regressions.json |
| GCC/Clang独立API与安全 | 各3/3测试通过，GCC21715项检查 | validation/final-native-tests.log、final-clang-tests.log |
| ASan/UBSan/LSan | 3/3测试通过 | validation/final-asan-tests.log |
| Clang TSan+Archer | 3/3测试通过，20814核心检查 | validation/final-tsan-tests.log |
| libFuzzer+ASan+UBSan | 119160次/46秒，无错误 | validation/final-fuzz.log |
| 快速DCT-II/III | 512对照PASS，最大绝对差6.316890112076756e-12；131072长度恢复通过 | validation/fast-dct-release.json |
| 实际数值内核分派 | 20个内核、460源差分PASS；各22种长度、80次并发PASS | validation/numeric-dispatch-final.json |
| AArch64/QEMU | 3/3测试；598对编码、1196次跨架构冷解码PASS | validation/arm-source-tests.log、platform-interchange-final.json |
| 完整物理帧 | 598帧，合计6199760 bits，全部冷进程恢复长度闭合 | validation/differential-release.json |
| 两独立目录可复现构建 | 8产物逐字节一致；安装C11动态/C++17静态消费者通过 | validation/reproducibility-release-final.json |
| 最终发布包 | 实际解包、清单hash、构建、CTest、8产物比较、安装消费者 | Release/cameo-family/cameo-family-full-parity-20261021.audit.json（资产根下） |

| 算法 | 差分 PASS / 完整帧数 | FinalBits 合计 | 最大绝对误差 |
|---|---:|---:|---:|
| CAMEO / SIP | 161 | 1501600 | 444.66 |
| VW | 46 | 294464 | 302.927 |
| PIP | 46 | 464192 | 200.276 |
| TP | 46 | 586304 | 376.766 |
| SWAB | 69 | 821536 | 195.474 |
| Sim-Piece | 46 | 484976 | 0.499636 |
| PMC-Mean | 46 | 452144 | 0.5 |
| SWING | 46 | 412336 | 0.5 |
| DFT | 46 | 563008 | 285.867 |
| DWT(DCT-II) | 46 | 619200 | 262.178 |

DWT(DCT-II)默认已改用O(N log N) FFT实现，保留可强制的O(N²)标量对照。n=512/2048/8192 的analyze中位提速约259/655/1111倍，数据见fast-dct-release.json；这是单机独立计时，不能当作源算法或Bench正式比较。十算法完整CF01编码/解码流水线另见performance-release.json。

默认生产依赖从冻结OpenBLAS0.3.21源码离线构建，使用C LAPACK ILP64及全20内核，不链接旧NumPy wheel/GFortran/Quadmath，不需要Python或Benchmark运行时。原来统一禁止FMA会改变两个AVX512小矩阵核的舍入，现仅为原生SKYLAKEX/COOPERLAKE C核恢复原生FMA；自有C++及数值基线仍保持严格浮点设置。失败与修复日志见NUMERICAL_DEPENDENCY.md。

平台与安全范围：x86_64匹配CPU模型验证源语义；QEMU/Valgrind/SDE实际执行宿主缺失指令。AArch64为QEMU的API/安全和跨架构恢复资格，不承诺跨架构编码决策或frame字节相同。首次ARM源差分590PASS/8DIFFERENCE保留。插桩覆盖自有C++/pocketfft/源码C数值基线，汇编和系统运行时为原生边界；不声称所有ISA完全插桩。最终FMA覆盖仅影响两个AVX512核，已重跑全部20路径；未影响的基线/ARM安全证据按明确影响分析沿用。

原版539一致/25源失败/34安全拒绝、旧CONTROL、修复前报告和所有中间失败均保留在validation及docs/history。此前59个失败/拒绝数据case、12个失败边界均以相同输入/request hash复验；没有改变预期或放宽容差。全部逐点误差、RMSE、完整FinalBits及原始输入身份可审阅。CF01与C ABI v1保持兼容；C++ Config增加字段，须重新编译消费者。本资格不表示Bench接入或FORMAL性能资格。
