# 新鲜源固定权重差分（限定诊断）

当前 DeepZip `biGRU`、alphabet=4、3 个 64-symbol contexts 的源差分已实测完成。源 TensorFlow 1.8.0 / Keras 2.2.2 / NumPy 1.16.4 使用未修改的 pinned `models.py`。当前 DZMODEL1 被逐张量精确载入原构造器；原历史 exporter 重新导出的完整 portable bytes 与当前注册模型一致。相同 seed 未被用作相同权重依据，未训练。

当前注册 `.so` 由独立小 C++ harness 绝对路径链接；运行 `/proc/self/maps` 确认实际加载。TF `SOFTWARE_TRACE` 的 RunMetadata step_stats 记录 4 个 `CudnnRNN` 节点在 GPU:0 执行，设备 placement 日志只是附加证据。源 repeated prediction 与 traced prediction 逐位相同。

- 12 个概率全量逐元素比较：PASS；最大绝对误差 `1.4901161193847656e-08`，采用执行前冻结的原 `3e-5` 合同。
- 完全相同源概率输入的原 NumPy→当前 CDF 转换：15 个整数全量 EXACT PASS。
- 源与当前 CPU 独立预测的完整 CDF：FAIL，1/15 不同。第三个 `arange(64)%4` 上下文的最终 total，源为 `10000004`，当前 CPU 为 `10000003`；差 `-1`。全部 12 个概率、15 个整数、逐元素误差与差值都保留。

该 CDF 差异不得以概率容差、仅比较内部边界或小误差忽略。此次不授予源/CPU 独立 CDF 一致性、源码流一致性、17 模型全面 parity、HDF5/CUDA native 能力、完整 codec pipeline、N/G/CAP 全门禁或 FORMAL 性能资格。原 REQUIRED_PARITY 能力保留。

`r1` 已完成源预测/CDF输出，但附加 FULL_TRACE 请求缺失的 `libcupti.so.9.0` 后 abort(-6)。原计划、脚本、日志和失败 report 不变。`r2` 新计划保留原权重/contexts/容差，改用 SOFTWARE_TRACE＋device placement，3 条命令均 exit0。r1 属附加 profiler 导致的执行失败，r2 的独立 CDF 差异属于明确记录的语义结果，二者区分记录。

DZip 当前公共 `NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET` 使用原生 mt19937 与自定义 Gram-Schmidt 初始化，不能与原 TF/Keras 随机初始化或者原流程训练后 `BASE_biGRU_jump` PRNN checkpoint 按 seed 等同。公共 registry 未暴露 loaded model；C ABI `RwConfig.model` 确有显式 DZIPNN01 权重诊断分支，但它不能代表当前 seeded 参数。详见 `dzip_comparability_boundary.json`。此次没有执行 DZip 源模型/训练/codec。

输入计划、提取脚本的原 archive inventory digest 复核、执行后 frozen inputs 不变复核、完整输出引用、失败索引见 `summary-r2.json` 和 `final-index-r2.json`。模型和 GPU 进程已全部结束；后续只生成这些小型审计文件。生产源码、锁文件、既有 expected 和 CAP 分类没有改动。
