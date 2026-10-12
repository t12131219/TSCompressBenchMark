# 新获取精确版本源码 authority 的独立复核

[upstream-independent-review-r1.json](upstream-independent-review-r1.json)为 `PASS_EXACT_PIN_SOURCE_AUTHORITY_GAPS_RESOLVED`。本次用独立的 [check_acquired_authorities.py](check_acquired_authorities.py)重新读取 Git 对象，不调用被审 acquisition driver 或旧 source audit。

| 源码根 | 精确 commit | 跟踪 blob 记录数 | 字节数 |
| --- | --- | ---: | ---: |
| Elf | `386d69348e6c30475761d3519ee0bfe10ed473d3` | 152 | 15,286,522 |
| Dipperstein lzss | `65b6882ff1cc225f9c6fcd947def7b1adb21d578` | 15 | 138,082 |
| Dipperstein bitfile | `2e6132f75cbe16842a9ab81af7756ed9ac1cdbe0` | 187 | 882,687 |
| Dipperstein optlist | `c921d0f8f7b2fc3d454ba897a3bf04beecb6899a` | 9 | 69,271 |

共 363 条跟踪 blob 记录、16,376,562 字节。独立重算所有唯一 blob／tree／根 commit 的 Git object ID，重新计算逐路径 blob 的 SHA-256，完整路径／类型／mode／OID／字节数／SHA 与原补证一致；4 根 `git fsck --full --no-reflogs --no-dangling` 均退出 0。lzss 的 bitfile、optlist 两个 gitlink 精确绑定相应 commit，子模块树均没有进一步 gitlink；四树均没有 symlink。

Elf authority pin 来自既有 UPSTREAM_PROVENANCE source lock，20 条旧锁 SHA 全部匹配真实原版本。Dipperstein lzss／bitfile pin 来自既有注册 identity，optlist pin 来自已校验的原 lzss Git tree。注册的 12 文件 vendor 全部与独立原版本字节相同；进一步重算旧协议 `RELATIVE_PATH_NUL_FILE_BYTES_V1` 的摘要与数量，匹配既有 `ce81296d3b2269d8ee2adf2d6964f156b31d013a6742e2c7c21486785d91fb9a`、12 文件。

被审 acquisition driver 的 vendor 路径集合来自当前 vendor 枚举，其字节 expectation 来自独立 pinned Git，具有独立性；单项 `exact_set` 只能证明该次枚举的集合一致。本复核额外检查既有注册摘要与固定数量，补足原选集完整性证据。

这些证据足以补齐旧报告中 **Elf 旧 commit 的完整 Git tree 缺失**与 **Dipperstein 原 lzss／bitfile 独立 authority 缺失**两项源码来源缺口。旧报告与旧失败反映当时状态，保留原样；本次新增复核不倒改历史结果。

完整主源 tree 与递归 Git 子模块 tree 不等于外部依赖、编译／链接／工具链闭包或功能域语义一致性。此结果没有授予外部依赖闭包、上游作者签名认证、语义差分、全部 N/G/CAP 或 FORMAL 性能资格。本次无网络、无生产模块导入、无 codec／build／性能执行，测试前后全部引用与旧索引 SHA 相同。

[upstream-independent-index-r1.json](upstream-independent-index-r1.json)冻结本次独立复核证据与审计程序；已有源码和 FORMAL 索引不改。

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/formal_static_review/check_acquired_authorities.py --output /tmp/tscb-upstream-independent-new.json
```

输出拒绝覆盖已有证据。
