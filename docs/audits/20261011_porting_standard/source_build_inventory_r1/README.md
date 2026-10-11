# 当前源码与构建库存审计

`audit_current.py` 从 `registry/algorithm_scope.json` 读取已有活动入口，逐项调用当前 `SourceRegistry`、`CodecRegistry`、`source_evidence()` 与真实 `adapter_artifacts()`。它检查登记身份及已声明执行依赖的当前哈希，并保存源码库存、构建记录、依赖文件与独立资格报告引用。登记在读取期间发生变化会拒绝生成最终快照；已有输出文件不会覆盖。

源码库存中的 `LOCKED_HASHES_VERIFIED` 仅说明已锁定文件哈希一致。完整树摘要缺失或摘要协议不等价时，闭包状态仍保持 `UNKNOWN`。`adapter_artifacts()` 接受当前依赖也仅代表真实入口的已声明哈希校验通过；本脚本不补造未声明的编译闭包。

独立 native 资格工具负责核验真实编译依赖清单、测试程序与动态库、非空 CTest 清单、完整执行结果以及运行前后的闭包一致性。源语言差分报告保留各自的有限范围，包括 ABBA/fABBA 的阶段组合 oracle 与 fABBA 的稳定化 profile。库存脚本不会把文件哈希、C++ 回环或部分源语言差分提升为完整上游语义一致性、完整 G0–G6、`REWRITE_DONE` 或正式性能资格。

最终快照在构建、资格与登记全部稳定后生成，并引用新的原始报告；旧资格、旧源码参考与旧正式结果保持原样。

当前最终结果为 `inventory-final-r2.json`：33 个活动入口的当前实际 adapter 声明依赖检查全部通过，源码闭包为 8 项 vendor tree 哈希通过、1 项 selected closure 哈希通过、24 项摘要协议或完整闭包未知，没有 `DRIFT`。未知状态不表示完整源码资格已获批准。`inventory-final.json` 保留为 DeepZip 模型目录层级修复前的冻结库存。

快照关联 completed 四族 release/sanitizer 的 8 个 profile、32 个真实 CTest；generic native v4 的 62 个构建记录与 60 个有限 native 测试；SIMD SDK r4 的 504 个测试与实际导入的 77 个项目 Python 文件；以及六个无损入口 admission r2 新登记的 12 个 native profile 和独立源差分。SDK r4 重新执行测试并绑定修复后的共享 Python 源码，admission r2 重新校验未变的有效 native/source 证据及当前 production factory 依赖。所有先前 SDK、登记和库存原件保留。无损源差分包含 613 个合法样例、2 个 END 样例、8 个历史源失败对应的 native 拒绝样例，另有 6 个 network 样例。Elf+ 的 82 个合法样例和 2 个 END 样例实际执行原 Java，8 个历史失败样例未重新执行原 Java，登记分别保存计数与来源。

LZSS source oracle 实际测量的旧路径与当前登记库路径不同。快照记录两库字节 SHA-256 一致，以及 core、header、shim 的已声明编译闭包与当前源码一致；它不会把该关联写成直接对当前登记路径执行过 oracle。
