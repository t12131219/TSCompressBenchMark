# ABBA / fABBA / QABBA 接入报告（2026-10-20）

已删除活动旧 ABBA/fABBA vendor、四个补丁、两张旧 source 卡及对应共享分支，替换为独立发布的 C++17 abba-family，新增 `qabba`。旧源码/配方/登记/测试和原 build indexes 已归档，历史设计与性能结果不改签。新绑定状态为 **BENCH_BINDING_QUALIFIED_LIMITED_SCOPE**；独立交付的 REWRITE_DONE / FULL_PARITY（SEMANTIC）继续仅属于原包。

完整阅读交付 README、porting_report、CONTRACT、FORMAT、SEMANTIC_AUDIT 和既有一致性核对，按工程 V3.0/V4.0 执行[接入计划](PLAN.md)。消费发布包 SHA-256 为 `ec70b59fd9e0a48303604596df43fa8e21090b6f577513f11894e727a6240b1e`；7830 个消费/参考成员逐哈希冻结，算法核心、CKmeans 和依赖零修改。Autotools 仅在构建私有副本中生成文件；实际 CMake 与 Autotools 编译依赖均进入 build.json（每库735项），包括系统头、生成配置、工具链及运行依赖。独立参考另行 CMake 编译，737项真实依赖固定于 [reference-build.json](reference-build.json)；不能把同一 Bench 库作为参考。

| 登记键 | 固定上游 | Bench 语义与默认配置 |
|---|---|---|
| abba | ABBA `614d56841cd2f1c2925cea4d2c2648a7b2ac791d` | tol=[0.1,0.1]、scl=0、min_k=1、max_k=100、seed=true；CKmeans/KMeans 或 incremental，norm1/2、weighted/symmetric |
| fabba | fABBA v1.5.3 `d8727ecffd6232308898d7bcb2415187ab456c57` | tol=0.1、alpha=0.5、scl=1；五种 sorting；Python/Cython 语义均在 C++ 执行 |
| qabba | QABBA v0.2.0 `abfd22739b8a2d625f1538a7de9abe3a55f04471` | tol=0.2、alpha=0.5、agg/norm、量化位宽8/16；支持三 digitizer、norm/pca、宽度1..64、九种非上下文符号编码 |

参数以 registry 卡为准。ABBA 的 min_k=1 是明确的 Bench 默认，独立包未指定时为2。ABBA `compression_tolerance`/`digitization_tolerance` 映射 source tol 数组，clustering 映射 c_method；fABBA/QABBA tolerance 映射 tol。max_len 默认1048576。只开放单 worker，每对象重新拟合；不开放 unseeded ABBA、缺失填充、图像、自定义字母表、模型复用、QABBA 共享多序列码本或 Huffman1。原包这些能力不等于本次 Bench 能力。

三者都是 P2 经验有损流水线，只支持 `empirical_quality`，不提供逐点绝对/相对界。输入为有限 little-endian binary64，2..1048576行，最多4096列、总值不超过1048576，完整对象帧不超过256MiB，并受发布包内部数值/工作预算约束。FE_TONEAREST、禁用 fast-math、关闭 contraction。core 支持 rank1；C1/native_api/对象支持矩阵独立列，不能把它宣称为 QABBA 跨列共享训练。

**QABBA 源码有重建长度变化：** 187组请求中43组的源码恢复长度与原网格不符。Bench 在编码操作内对完整 AFS1 做恢复检查，提交输出前返回 unsupported，不补点/截断/重采样；该额外检查计时。发布包 encode 本身也调用 fit 并计算源重建结果，保留该原始行为。不能把默认 QABBA 当作任意输入都能保持原网格的方案。纯数值有限仍可能因算术溢出、预算或恢复长度被拒绝。

native_core 直接调用发布 C++ owning API，结果跨 context 销毁继续有效，释放在验证之后。输入 staging、拟合/聚类、码本、符号编码、序列化、CRC、恢复检查，以及解码解析/重建/分配均位于操作内；bound 只做尺寸算术，禁止在计时外拟合/编码。C1 内部临时持有完整结果，最后一次 memmove 提交，容量失败不写输出、不消费状态；一次 compress + 零字节 finalize，reset 清理独立对象状态。这些是 Bench 绑定生命周期，并非虚构上游流式 API。

单列输出为原样完整 **AFS1**，包含全部码本、首值、量化参数、符号层模型和 CRC；冷 decoder 的 core params 为 `{}`、model=null。矩阵输出为计费的 **AFM1** 列容器：magic+version+rows+columns，逐列 length+完整AFS1，末尾整体CRC；详见[绑定说明](../../adapters/abba_family/README.md)。FinalBits 采用完整实际字节，理论 symbol/storage 估算不代替实物。对象层另外计入完整 Bundle 描述/路由等开销；完整方法输出与 source AFS1 不混淆。动态导出仅 tscb_* / tsbench_core_*，静态包含的 Zstd/zlib/bzip2/liblzma 与 CKmeans 不对其它 codec 产生符号覆盖。

实际验证：

- [187组源码/参考/Bench对照](qualification.json)，26670输入值，144组成功：ABBA 58/58、fABBA 61/61、QABBA 25成功/43预期拒绝。120个原交付数据对象（ECG5000、Chinatown、Coffee、shared-float64）全部纳入分母，99成功/21 QABBA网格拒绝。另67组参数/旧incremental反例，45成功/22网格拒绝。
- 每个成功对象 Bench core 与独立 CLI 完整字节一致、双向恢复且 C1 相同；恢复数值与重新执行的原 Python 源码在 abs/rel 1e-10 内一致，所有43个拒绝亦对照源码长度。没有把 rejected 计为恢复 PASS。源类/CKmeans/oracle 实际文件和 Python 动态依赖另固定于 [source-oracle-identity.json](source-oracle-identity.json)。旧 ABBA incremental 反例现在跟随新源码。
- 12组 key×native_core/native_api×prepared/fresh_request，每组1 warmup+2测量操作，全部36份完整产物计时外验证，并各自新进程恢复、核对 bits/value。24组 key×C/F×整矩阵/分列×整块/17行分块对象由全新 CLI 仅凭 Bundle 恢复；不将这些短诊断作为正式性能。
- 容量 N/N−1、失败输出不变/状态可重试、reset/finalize、重复对象、跨 context 所有权、dtype/形状/算法错配、坏CRC/截断/附加字节、CRC有效的样本数篡改、非有限/尺寸限制及极小正参数下溢，均有专项回归。独立 native_safety ctest 1/1。
- 新绑定加重新编译的发布核心的 ASan/UBSan/LSan **147个案例通过**，detect_leaks=1、halt_on_error=1，宿主 stderr 0字节。该 sanitizer 控制使用共享发布核心，生产库静态链接闭包另外核验；不冒称是生产二进制本体启用 sanitizer。沙箱内首次 LSan 被 ptrace 阻断，原错误保留；最终在非 ptrace 宿主进程重跑通过。
- 最终完整 Python 回归 **1387 passed、4 subtests passed，0 failure/skip，88.78s**，见[日志](logs/full-suite-final.log)、[JUnit](logs/full-suite-final.xml)与 [evidence.json](evidence.json)。本次不继承独立包跨架构、fuzz、11757次OOM或二进制可复现资格，不宣称新绑定已完成这些验证。

许可证：本包包含 **LGPL >=3 的 CKmeans 组件**，并非纯 MIT。源码、原生复用安全补丁及 JSON 补丁、全部许可证/通知和离线重建配方保留；合并库分发须保留检查/修改/重链接权利。组件登记和完整哈希见 [source artifact](../../registry/sources/abba-family-20261020.artifact.json)、[冻结清单](../../adapters/abba_family/FROZEN_SOURCES.json)。

当前为43个可用真实CPU codec+raw-store，45个真实登记中的两项LZSS仍因“算法接入异常，处于排除状态”被禁止。未来设计生成器和新示例已加入QABBA；已冻结正式设计和历史输出保持原身份。新[示例](../../benchmark/examples/abba-family.toml)的ETTh1 256值三个方法已实际编码/恢复；其中QABBA显式max_len=1保证此示例采用单位分段，不能当默认配置效果。**新实现正式性能未重跑**。

复验命令（在仓库根目录，Python 环境需具备 numpy/pytest）：

```sh
PYTHONPATH=benchmark/src python -m tsbench build abba fabba qabba
cmake -S /home/fzg/PycharmProjects/Compression_Rewrite/ReWrite/abba-family -B /tmp/abba-family-reference -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/abba-family-reference --target abba_family_cli af_native_tests -j2
ctest --test-dir /tmp/abba-family-reference --output-on-failure
PYTHONPATH=benchmark/src python benchmark/tools/qualify_abba_family.py --cli /tmp/abba-family-reference/abba_family_cli --oracle /home/fzg/PycharmProjects/Compression_Rewrite/ReWrite/abba-family/tools/oracle.py
PYTHONPATH=benchmark/src python -m pytest -q benchmark/tests
bash docs/abba_family_integration/build_sanitized.sh
c++ -std=c++17 -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie -I native/include docs/abba_family_integration/binding_safety.cpp -ldl -o /tmp/abba-binding-safety
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 /tmp/abba-binding-safety /tmp/abba-family-sanitized
```

参考 CLI 可用 ABBA_REFERENCE_CLI 指定其它位置。源码 oracle 使用已交付的 Python3.11隔离依赖；如缺失，按原包 README 离线 bootstrap。asan 需要非 ptrace 运行环境。

过程诊断保留：初次外层缺 find_package(Threads)；首次 Autotools 重生成14个 distribution 文件导致锁拒绝（已恢复并改私有副本）；资格工具最初以 Unicode splitlines 拆 JSON 导致解析失败，现仅按 LF 拆分；旧 QABBA测试误以为任意输入保持网格；完整suite首次两处旧42键数量断言。以上失败不计PASS，详见 logs。
