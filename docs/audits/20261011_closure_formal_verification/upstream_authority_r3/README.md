# 精确 pinned 原始来源补证

本轮补充此前只在本地搜索时未取得的 Elf 指定旧提交，以及 Dipperstein LZSS 的独立原始仓库。公开 HTTPS 获取只写新的 `build/closure-formal-verification-20261011/upstream-authority-r2`，没有修改原仓库、来源锁、vendor、registry 或旧证据。

[verification.json](verification.json) 为 `PASS_EXACT_PIN_SOURCE_AUTHORITIES`。四个精确 pinned tree 的全部 blob 重新计算 Git object ID 和 SHA-256，`git fsck --full --no-reflogs` 均通过：

| 原始来源 | 精确 commit | 与当前源选集的关系 |
|---|---|---|
| Elf | `386d69348e6c30475761d3519ee0bfe10ed473d3` | 完整该 commit tree 可取得；20 个既有 source-lock 文件 SHA 全部匹配。 |
| Dipperstein LZSS | `65b6882ff1cc225f9c6fcd947def7b1adb21d578` | 与独立 bitfile pin 联合核验，当前未修改 vendor 的 12 文件集合和字节全部匹配。 |
| Dipperstein bitfile | `2e6132f75cbe16842a9ab81af7756ed9ac1cdbe0` | LZSS 的 `bitfile` gitlink 精确匹配，完整该子树已核验。 |
| Dipperstein optlist | `c921d0f8f7b2fc3d454ba897a3bf04beecb6899a` | 额外发现的 `optlist` gitlink；精确提交及完整子树核验。它未被当前 native library profile 消费。 |

两个子模块树没有进一步 gitlink。以上证明精确源码树、Git 子模块和已选 vendor 字节，没有授予来源树之外的包、工具链、生成步骤、完整 API、补丁合法流差分、N/G/CAP 或 FULL_PARITY。HTTPS 仓库取得与内容完整性不等于作者签名认证。

默认网络首次尝试失败，日志保存在 `upstream-authority-r1`；随后隔离环境外的公开只读 fetch 成功。首次补证 [r2](../upstream_authority_r2/verification.json) 严格要求只有一个 gitlink，因此对真实存在的额外 `optlist` 报告缺口；没有把它忽略或改为 N/A。随后取得该精确子模块，在本 r3 对两个 gitlink 逐项核验成功。r2 记录及当时核验脚本副本保留。

本报告是此前 [源码核验](../source_closure/README.md) 和 [门禁盘点](../gate_audit/README.md) 的新补充；这些历史文件中“未取得”的状态保持其当时日期与证据。当前指定旧 Elf tree 和 Dipperstein 原始 authority 的缺口由本补证解决，完整移植／重写资格仍单独验收。
