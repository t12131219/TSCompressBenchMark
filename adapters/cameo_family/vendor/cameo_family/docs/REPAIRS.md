# 原版失败修复记录

用户授权“适当修复上面的原版失败”。当前修复目标为 **cameo-family-repaired-v1**，TP边界语义名为 **tp-first-span-v1**。完整原版快照保持不变，修复代码在Source/cameo-family/repaired-v1，六文件差分和SHA见REPAIR_MANIFEST.json与PATCHES/0002-repaired-v1-cumulative.patch。补丁相对于冻结原版累积生成，不叠加旧CONTROL补丁。

| 原因 | 修复 |
|---|---|
| VW聚合用double大小分配long-double数组 | 两处分配改为sizeof(long double) |
| PIP用信号值判定是否继续，可能弹出端点 | 改为检查重要性cache，端点的无限重要性使循环正常停止 |
| TP首次转折访问selected_tp[-1] | 首段用起点和当前转折点插值，首段重要性除以当前段长；无虚构前驱 |
| TP初始误差超界时释放未初始化heap.values | 该分支只free已分配的heap结构；正常初始化后的释放不变 |
| SWAB奇数尾点、末端辅助窗先读越界再取min | 先对索引取min，再访问数组 |

TP修复仅修改首次跨度大于1的原未定义分支；首次转折为1以及后续有定义分支保持源公式。初次gap=2插值的值可手算为端点均值；gap=4按四等分计算。原生回归直接检查这些工作信号值、调用者输入不变和独立恢复，并非只让两个相同实现互相证明。80组差分另覆盖gap1/2/3/4/7、正负信号、kappa1/2和4种误差阈值。

历史CONTROL仍拒绝首段异常，仅用于旧诊断；修复参考位于oracle-repaired，可通过tools/build_repaired_oracle.py从冻结来源独立构建。tools/verify_repairs.py先核验原版哈希，再在临时副本中将六文件规范成LF并实际应用补丁，核对得到的源码与修复文件逐字节一致。没有对原始New_Source_Code或冻结upstream原地覆盖。

复验：

```sh
python3 tools/build_repaired_oracle.py
python3 tools/verify_differential.py --repaired --output differential-repaired.json
python3 tools/verify_boundaries.py --repaired --output boundaries-repaired.json
python3 tools/verify_repairs.py
python3 tools/audit_repaired_results.py
```

原598组合中先前25次源失败+34次C++拒绝的59个case，按同一输入与请求hash逐项核对全部转为PASS；先前12个边界源失败也全部转为PASS。VW聚合另外那些偶然exit0的UB用例，现在也使用正确容量，修复参考的全部598组通过。旧结果文件没有覆盖，不能把新结果回填成“原版本来就正确”。
