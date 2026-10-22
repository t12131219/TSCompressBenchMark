# CAMEO-family Benchmark 接入（2026-10-22）

接入目标为授权修复 `cameo-family-repaired-v1`，发布实现 `cameo-family-cpp17-repaired-v1-1.1.0`。独立包 `REWRITE_DONE / FULL_PARITY` 不自动等于 Bench 绑定资格，未修改原版的 BLOCKED 历史保留。本次绑定验证已完成，结果和复现证据保存在本目录。

| Benchmark key | 实际算法 |
|---|---|
| cameo | CAMEO / SIP，同一算法，不重复计数 |
| vw / pip / tp | 原源码 ACF 驱动算法及 repaired-v1 规则 |
| swab | sliding、Cython bottom-up、Python bottom-up 三种模式 |
| sim-piece | TerseTS SimPiece |
| pmc-mean | PMC-Mean，区别于 PMC-MR |
| swing-connected | connected SwingFilter，区别于 Chimp Swing 系列 |
| dft | 按幅值保留系数的 DFT |
| dwt-dct-ii | 正交 DCT-II，非小波 |

输入有限 binary64，规则隐式整数索引时间轴；总值 1–131072、最多4096独立列、完整帧最多64MiB。native_core 单列；native_api/object_memory 可矩阵独立列。ACF 在 N≥3 时要求 kappa 整除 N、聚合数≥8、0<nlags<聚合数/2、N²×nlags×min(hops,16)≤1e8；默认 nlags=4，因此默认长对象至少10点。SWAB/scalar DCT 有 N²≤1e8 预算，sliding 窗口至少2。1/2点为原发布的非空短对象扩展，空对象本绑定拒绝。算术域、安全预算或恢复长度变化对象明确 unsupported，不补点。

参数完整列于 registry 卡。CAMEO 提供 LPC/FGC、error/整数ratio停止及 aggregate kappa；ACF 的 threads=1–64，资源 profile.native_threads 必须一致。其余单worker。数值库源码构建为单线程 OpenBLAS ILP64，20内核内部原生分派；固定 isa=NATIVE_DISPATCH 是描述，不提供 ISA 切换。保持 FE_TONEAREST、无 fast-math、自有 C++ contraction=off；原生 SkylakeX/Cooperlake C reduction 的已验证 FMA 覆盖规则保留。

仅允许 empirical_quality。ACF 是平均每滞后 Pearson 相关误差，SWAB 是源拟合阈值，TerseTS 将阈值转换 float32 并保留 1e-7 余量；这些都不声明通用最大逐点界。DFT 的 fraction 是保留数量比例，DCT 的 fraction 是尾部清零比例，且 fraction=0 会清零所有 DCT 系数；范围外保持源 Python slicing。不得以同名 fraction 推断相同质量水平。

主路径直接调用 owning C++ encode/decode。暂存、阶段拟合/变换、分配、原 encode 内部恢复与完整序列化在时钟内，输出归属独立于 context；释放/质量验证在时钟外。bound 只算安全上界，不调用 analyze/encode。CF01 全部68字节恢复/CRC开销与点/系数/raw方法尾标记计费。多列 CFM1=24字节头+每列8字节长度和完整CF01+4字节CRC，全部计费。decoder 不依赖原信号、编码参数或外部模型，严格核对算法和原网格数量。

构建入口 `PYTHONPATH=benchmark/src python -m tsbench build cameo`（其余九key同理）。离线共享构建缓存核验源码/实际依赖/工具链/归档与十个产物，生产绑定只导出 tscb_* / tsbench_core_*，避免 BLAS/JSON 符号污染其它codec。消费文件哈希见 `adapters/cameo_family/FROZEN_SOURCES.json`；来源、许可证、修复原始材料见 `registry/sources/cameo-family-repaired-v1.artifact.json` 与本目录 provenance。

可运行示例：`benchmark/examples/cameo-family.toml`；未来全core设计生成器已纳入十项，历史冻结设计和 FORMAL 结果不改签。本轮只作正确性接入验证，不声称新的正式吞吐。

## 本次接入验证结果

状态：**BENCH_BINDING_QUALIFIED_LIMITED_SCOPE**（本地 Linux x86_64、GCC、已登记参数/输入域）。独立发布资格和本次绑定资格分开记录。

- 最终全仓回归 **1632 passed + 4 subtests passed**，零失败、零跳过；其中本家族245项，覆盖所有26参数组合、owning结果跨context生存、C ABI N−1容量原子性/reset/finalize、CRC有效但几何非法的帧、跨算法/截断拒绝、有限值与工作预算拒绝、变换 slicing 与 DCT fraction=0、独立列 C/F 矩阵及80个对象组合的新进程恢复。五个线性/FFT路径实际完成131072值上限编码/冷恢复并拒绝超限。
- **598组、114816值**：最终生产 core 与独立 CMake CLI **完整CF01逐字节相同**；C ABI也同帧；Bench空参数decoder和独立CLI双向恢复。另启动 repaired 源参考进程逐对象新建数组，598组恢复值均在 abs/rel 1e-10 内一致。此处是恢复数值对照，不将其描述为所有内部阶段重新验收。参考CLI独立编译C++/pocketfft，数值静态归档与生产闭包共用；不声称独立重建第二份BLAS。六个修复Cython源hash及55项参考身份另存。
- 两原生边界 × prepared/fresh_request × 十项 = **40组/120份产物**，完整帧、bits/value、每次操作校验及独立恢复均通过；产物与详细驱动记录见 native_matrix。80个对象组合覆盖列/块划分和C/F布局，未以重排输入替代原布局的原生能力。
- 独立参考 CTest **3/3**；十项生产库符号隔离检查通过，仅导出ABI符号，无动态Python/GFortran/Quadmath/OpenBLAS依赖。每个生产库记录**13555项**实际编译/归档/工具链依赖；算法ID映射文件参与构建身份，热缓存全闭包核验通过。
- 绑定与未修改发布C++/pocketfft另行ASan/UBSan插桩，**361探针/十绑定**通过宿主 ASan/UBSan/**LSan detect_leaks=1**，无sanitizer诊断。生产源码数值归档是明示未插桩边界；不继承独立数值库插桩资格。沙箱首次退出因ptrace无法完成LSan，失败日志原样保留，不计为通过。
- 示例真实ETTh1原始256点窗口十项均完成编码/恢复；这是正确性与经验误差观察，非相同点误差水平或正式吞吐比较。未来全core设计生成器在新目录完成54个活动key（含raw-store）的静态覆盖检查，未运行这些设计的正式测量。

诊断保留：首轮专项229通过/1失败是非整数ratio配置报通用codec错误，现参数层明确拒绝；首轮全仓1614通过/3失败来自新增 families.py 构建来源项后旧测试预期和模拟安装包fixture未更新，修复后专项8/8及最终全仓通过。所有日志保留，不删除失败分母。首次生产构建后补充ID映射依赖与适配器说明，随后全十项按最终身份重新构建、重新跑598对照与40组原生矩阵。

**不继承**独立包Clang/AArch64、20强制内核专项、fuzz、分配失败注入或双目录二进制复现资格；本次未执行FORMAL吞吐。记录的本机默认数值后端为 OpenBLAS0.3.21 ILP64 SINGLE_THREADED、actual_core=Prescott；未设置 OPENBLAS_CORETYPE，不据此宣称其它ISA已在本次绑定复验执行。原版BLOCKED/修复版FULL_PARITY的边界保持不变。

复验：先构建十个key；独立参考可按冻结源码的CMake构建（或使用本次记录的静态归档显式设置CF_LAPACK_LIBRARY）。运行 `benchmark/tools/qualify_cameo_family.py --cli /tmp/cameo-family-reference/cameo_cli --oracle /home/fzg/PycharmProjects/Compression_Rewrite/ReWrite/cameo-family/tools/oracle.py`；`CAMEO_REFERENCE_CLI` 可覆盖测试参考路径。原生矩阵脚本为本目录 run_native_matrix.py，sanitizer配方/探针一并保留；全仓命令为 `PYTHONPATH=benchmark/src /home/fzg/anaconda3/envs/CompressBench14/bin/python -m pytest benchmark/tests -q`。

完整索引见 [evidence.json](evidence.json)、[qualification.json](qualification.json)、[build_identities.json](build_identities.json)、[reference_identity.json](reference_identity.json) 与 logs。
