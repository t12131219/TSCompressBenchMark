# ABBA／fABBA／DeepZip／DZip／Gorilla direct core开发记录

状态：2026-10-15，接口研究、实现与专用测试源码已写入；中央构建进行中，尚未确认新增实现的构建、测试或正式测量结果。本记录由集成者归入[持续开发日志](../development.md)。

## 目标与当前问题

现有RW binding会复制输入与输出；DeepZip／DZip在bound及encode重复读取外部模型。Gorilla C1 binding会先构造Sample数组、编码vector后复制到ABI buffer；恢复同样有中间vector及复制。新增core入口应直接使用真实算法API，并明确prepared模型准备与每次算法工作边界。

ABBA／fABBA维持rank1 float64；DeepZip／DZip维持rank1 bytes及真实模型／符号域约束。Gorilla先支持UTS joint records，无mask，交错LE int64 T与f64位型V，每对16bytes；config为BYTES、rank2、shape=(rows,2)、C-order。原始有效分母为16×rows，compressed bytes为Prometheus原生EncXOR，不加入ABI envelope。

## 实际阅读与验证

已完整阅读现有`adapters/completed_rewrites/native/binding.cpp`／`binding.hpp`、`adapters/gorilla_prometheus_xor/native/tscb_gorilla.cc`及Gorilla公开C++头文件。后续算法实现、格式恢复依赖及新增代码逐项追加记录。当前没有本轮构建或测量结果。

## 五个入口实现已写入，等待统一集成

- `binding.cpp`按既有RW_KIND=1／2／7／8分别导出统一core接口。完整阅读了ABBA／fABBA canonical codec、DeepZip codec／model／internal header、DZip codec／network／CPU op入口及各自公开头文件和Python RW bridge。未修改冻结算法；新增core不再调用RW bound／encode／decode或生成RW列envelope。
- ABBA／fABBA直接读取原float64 buffer，分段、聚类／建模、符号生成与完整原生ABBA／FABB frame序列化在encode内，decode vector所有权直接转移。最初沿用原encode全部行为；后续只读审阅发现其`transform`会生成encode不消费的quantized decoder pieces及整份N点reconstructed。已追加下述build-local encode-only修正，不再把未使用恢复混入压缩主时钟。有限值／endpoint算术域属于准入检查，拆入`tsbench_core_validate_input`在主时钟外调用，避免原segmenter对无法表示的端点不推进；来源与已有RW拒绝规则相同。
- DeepZip prepared encoder只加载一次immutable Model；每次compress仍执行dictionary、上下文预测、算术编码、finish以及完整模型／字典／长度／CRC序列化，decoder从frame恢复模型。框架附加的alphabet准入scan移入`tsbench_core_validate_input`，真实compress自身字典转换和检查保持原样。原生API要求Bytes vector，必要输入materialization仍计入；避免的是RW额外输出复制。
- DZip默认模型依赖本次输入distinct alphabet，每次encode重新扫描、seeded初始化，再由真实compress复制独立网络并reset_optimizer、进行combined在线train、模型BSC存储及frame finalize。bound所需临时模型立即丢弃，不传入encode；显式固定外部模型才可在create准备。alphabet=9保持真实unsupported。prepared不预计算输入相关训练／模型。
- Gorilla完整阅读canonical codec及optimized bitops，直接逐对Encoder::append并finalize。结果owner持有原生Encoder，输出vector视图不复制且在context销毁后仍有效；release在时钟外。独立decoder使用Iterator Borrowed、strict尾检查并直接写LE pairs caller buffer，避免Snapshot及Sample数组复制。canonical／optimized为同一EncXOR格式，decoder params={}即可用canonical恢复，不免费依赖encoder参数。
- 四RW decoder均从完整frame恢复必要参数／模型，只以任务dtype／shape核对输出范围；Gorilla同样只核对任务rows。frame必要字节全收费；ABI／对象metadata不进入core输出。

仅完成实现与`git diff --check`，按集成安排未运行build、测试或benchmark。统一构建、独立恢复、跨入口产物及所有权生命周期验证由root执行，结果须另补，不声称已经通过。

新增`benchmark/tests/test_core_model_records.py`共29个专用正确性case：ABBA／fABBA两种长度的完整header／center／symbol账单及无参数独立恢复；DeepZip零／短／多lane输入、逐字节portable模型嵌入、外部模型副本删除后独立恢复；DZip两模式在同context连续处理2／4个distinct alphabet并核完整model／payload长度，防止默认输入相关模型被缓存。所有五个encoder结果及四模型decoder的owner均在context销毁后读取，再释放。ABBA／fABBA／DeepZip非法源域断言独立准入hook拒绝，不将验证scan混入encode。

Gorilla专用测试对canonical／optimized两路核对全部36份归档上游完整stream，另覆盖0／1／2／7／65535行、极端有符号时间戳、重复／逆序T、正负零／无穷／NaN payload／subnormal等全部给定位型、65536行拒绝和错误count头拒绝。测试源码不执行构建，不提供性能证据；按中央集成安排尚未执行。

中央首次完整suite实际为688 passed／3 failed，日志见`build/verification/all-core/pytest.log`及`junit.xml`。三个失败均是本文件DZip两mode与decoder参数拒绝case在当前Conda pytest进程加载动态库时，已映射旧libstdc++缺`GLIBCXX_3.4.30`；不是codec测试断言或新编译失败。修订仅影响测试：读取既有`benchmark/examples/dzip_runtime.toml`的显式system libstdc++ preload profile，为这三个nodeid分别启动一次全新pytest子进程，child标记阻止递归，检查实际`/proc/self/maps`已映射请求runtime后执行原断言。父测试要求child returncode=0且确实1 passed，不允许skip；不更改主pytest环境、不修改codec／build实现。profile／preload列入JUnit user properties，child不继承父`PYTEST_ADDOPTS`，避免覆盖父suite JUnit。该修订尚未重跑，由root统一运行三项及全suite。

后续中央全suite实际达到691 passed（69.74s），DZip三项明确runtime子进程均通过。该结果早于下述encode-only修正，不能当作修正后的验证。

## ABBA／fABBA encode-only修正：等待中央重建

最后只读审阅完整跟踪`encode → transform`，确认`transform`生成的expanded centers、quantized pieces与N点reconstructed全部不被native encoder序列化消费。分段与digitize决定符号／codebook，完整frame只保存原参数、count、codebook、symbols和CRC；恢复质量不需要在压缩主时钟里重建一遍数组。

新增`adapters/completed_rewrites/patches/abba_encode_only.patch`与`fabba_encode_only.patch`，仅在构建目录副本追加`encode_only()`：调用同一`compress`与`digitize`，逐字段复制原完整序列化逻辑，不构造未使用的decoder pieces／reconstructed，不改变任何冻结vendor或public header。原`encode`、`transform`及RW／object入口仍调用原函数，行为保留。direct binding通过局部forward declaration调用新增函数。当前仓库对应构建函数实际名为`_rw_build`，已在其ABBA／fABBA两个key分支先核冻结hash、复制至build-local `patched-source`、应用对应patch，再让CMake引用派生树。`_source_files`原有递归闭包包含新增patch，compiler dependency closure同时保存实际派生源码。

新增24个逐字节对照case，覆盖两codec各四组合法参数、2／17／65点，包含ABBA KMEANS／INCREMENTAL、norm1／2、scl、零／非零容差、max_len与fABBA alpha。direct完整stream与仍调用原native encode的RW binding输出逐字节比较，再在编码之后用空参数独立decoder及旧native decoder比较恢复，核有限值与输入不变。该测试不编译或测性能，尚未执行；root将统一重建受影响模型库并重跑专用及完整suite。

同时只读确认DZip：core每次默认`input_alphabet → Network::create`；`encode_raw`按值持有独立网络并`reset_optimizer`清m／v与step，COMBINED在64符号context之后每128次prediction调用相同`adapt`。decoder从完整frame的initial model恢复，先reset，再按同一位置和训练窗口重放；257符号会触发一次在线train。未发现Gorilla／SIMD新的完整必要输出或尾部遗漏。本次未运行codec、构建或测试，正式测量尚未开始。
