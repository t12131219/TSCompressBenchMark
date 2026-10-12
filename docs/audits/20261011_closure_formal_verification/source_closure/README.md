# 2026-10-11 当前源码闭包独立核验

本轮核验现有 33 个活动入口的源码闭包，不构建、不加载、不执行 codec，不修改生产 src/tools/registry/configs，不新增算法。旧证据和旧失败全部保留。

当前安装源码的**限定集合与字节闭包 33/33 PASS**。它分别证明完整已冻结原生 package、登记的选定 vendor tree、独立原始 Git 对象对应的 native 编译选集，或明确的五文件 C++ 翻译 profile；**不等于 33 个完整原上游源码／依赖／能力域全部通过**。

原 `24 UNKNOWN_SELECTED_CLOSURE_OR_HASH_PROTOCOL_NOT_EQUIVALENT` 来自通用库存器缺少 API-file-lock、canonical-JSON、sha256sum-text 等协议，以及 selected 与完整 vendor 根的区别。它不能直接解释成“24 个算法没有原源码”。本轮提供更精确的新证据，保留旧库存结果。

## 新证据

- [主核验 r4](r4/report.json)：33 个 current installed scope PASS，输入快照前后相同；[driver](audit_sources.py) 可重放。
- [补充核验 r2](supplement-r2.json)：FSE、HUF 和 Sprintz＋HUF 三项既有摘要协议 PASS；真实 Chimp 六文件临时副本的 baseline 及改字节、删文件、增文件、路径逃逸、symlink 五项拒绝反例全部 PASS；[driver](verify_source_supplement.py) 可重放。预期来自已存在的 FROZEN_APIS.json，没有从临时副本生成新 expected。
- 17 个独立本地原始 Git authority 的完整 pinned root tree，共 **14,331 个 blob、1,619,641,728 bytes**，逐 blob 重新计算 Git object ID 和 SHA-256 全部通过。完整对象库存见 [authority reports](r4/authorities/)。这证明现有本地 pinned commit 内容完整性，没有网络来源认证或原作者签名结论。
- 原始源码的既有 SHA 清单对独立 pinned Git 对象逐项核验：fABBA 52、DeepZip 28、DZip 136 文件全部匹配；按这些既有 checksum 从原始 Git blob 恢复到新审计目录 [recovered-authority-r2](recovered-authority-r2/)，恢复的源快照逐文件、集合核验全部 PASS。DZip 136 文件等于完整主 repository pathset；fABBA 和 DeepZip 分别是选定源快照，未称完整原 repository。

## 当前仍未证明的范围

- Elf 的源码锁指定 `386d69348e6c30475761d3519ee0bfe10ed473d3`，本地原 repository 的可用 root 是 Elf＋使用的 `64e0d6004be322d9d8eaf9931e371df202f1a0eb`。保留的 Elf 原始源选集逐 SHA PASS，**指定旧 commit 的完整 Git tree 仍未证明**；没有换成 HEAD 或更改锁。
- Dipperstein LZSS 的登记 vendor 12 文件根摘要／数量 PASS，但独立原始 lzss＋bitfile authority 尚不在本地，本轮没有独立上游来源结论。
- ALP、ALP-RD、Brotli、LZ4、Snappy、Zstd 的历史 source_closure_sha256 序列化未声明，本轮保留该历史协议 UNKNOWN。新证据按独立 pinned Git 文件和明确 native profile 选集逐 SHA 与集合核验 PASS，不重签或猜测旧摘要。
- 两个 Sprintz `-u8` 登记保留旧 `1a2c…` 源摘要，而当前共享 vendor 是原 17 文件 expanded tree `8535…`。17 文件字节／集合与独立原始 Git PASS，expanded 的原 sha256sum-text 协议也 PASS；旧 u8 选集未声明，**未把 17 文件摘要冒充旧 u8 摘要**。
- FSE/HUF 的证明是现有 15 个 lib 文件＋LICENSE 的 **16 文件选集**。完整原 lib 还含 Archives、fseU16、debug.c、README 等未用于当前 profile 的文件，均保留在独立原 tree 库存；本轮不要求新增功能，不称选集等于完整 upstream lib。
- Benchmark 内旧 Compression_Rewrite/Source/{fabba,deepzip,dzip}/upstream 相对于其 SHA 清单仍分别缺 **29／19／38 文件**，已有文件无 SHA 漂移。[首次失败](supplement-r1.json)及 [r2 中的原 snapshot FAIL](supplement-r2.json)完整保留，新恢复源位于审计目录，旧快照没有修改。DeepZip biGRU.hdf5 的独立原 Git 内容已证实并恢复到新审计源；不意味着模型部署／训练或旧 TF/Keras 环境已验证。
- 完整 Git tree 不包含隐式生成物、源码外部包、工具链启动文件或链接 archives 的递归闭包。全部 N/G/CAP、FULL_PARITY、独立发布、FORMAL 性能资格由各自核验另行给出，本报告不授予。

## Git mode／子树／链接

17 个 pinned tree 没有 gitlink（mode 160000），所以本轮没有需要假装包含的 Git 子仓库。6 个 mode 120000 symlink 均按 Git blob 的链接文本核验完整性；没有将它们当成已解引用的文件内容。LZSS 的三个 LICENSE/README 链接及 lzbench Zstd 测试的两个链接目标存在于 tracked tree；Sprintz `communicate/figs → ../figs` 的目标不在该 tracked tree，因此不能把完整 root blob 验证当成 resolved transitive dependency closure。

## 逐入口限定结论

| 入口 | 当前安装源码 proof | 原来源／剩余范围 |
|---|---|---|
| `abba` | PASS — 完整已冻结原生 package（35 文件） | 原 Git root 完整可用；当前 frozen native package 全集。 |
| `alp` | PASS — 独立 Git 对应 native 编译选集（14 文件） | 独立 pinned Git 选集字节／集合 PASS；历史摘要序列化未声明。 |
| `alp-rd` | PASS — 独立 Git 对应 native 编译选集（14 文件） | 独立 pinned Git 选集字节／集合 PASS；历史摘要序列化未声明。 |
| `brotli-stream` | PASS — 独立 Git 对应 native 编译选集（110 文件） | 独立 pinned Git 选集字节／集合 PASS；历史摘要序列化未声明。 |
| `chimp` | PASS — 完整已冻结原生 package（6 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `chimp128` | PASS — 完整已冻结原生 package（6 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `deepzip` | PASS — 完整已冻结原生 package（38 文件） | 恢复 28 文件原 source／checkpoint 选集；旧副本缺 19；旧源环境／训练未跑。 |
| `deflate-zlib` | PASS — 独立 Git 对应 native 编译选集（48 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `dzip` | PASS — 完整已冻结原生 package（1115 文件） | 恢复完整 136 主 source 文件；旧副本缺 38；训练／外部环境另验。 |
| `elf` | PASS — 完整已冻结原生 package（7 文件） | 指定旧 commit 完整 tree 未证明；旧原 source lock 选集 SHA PASS。 |
| `elf-plus` | PASS — 完整已冻结原生 package（10 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `elf-star` | PASS — 完整已冻结原生 package（7 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `fabba` | PASS — 完整已冻结原生 package（27 文件） | 恢复 52 文件原 source 选集；旧副本缺 29；完整原 package parity 另验。 |
| `fse` | PASS — 独立 Git 对应 native 编译选集（15 文件） | 16 文件 runtime 选集原协议 PASS；不等于完整 upstream lib。 |
| `huff0` | PASS — 独立 Git 对应 native 编译选集（15 文件） | 16 文件 runtime 选集原协议 PASS；不等于完整 upstream lib。 |
| `leats-lossless-i64` | PASS — 登记完整选定 vendor tree（172 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `lz4-frame` | PASS — 独立 Git 对应 native 编译选集（11 文件） | 独立 pinned Git 选集字节／集合 PASS；历史摘要序列化未声明。 |
| `lzss-dipperstein-c` | PASS — 登记完整选定 vendor tree（12 文件） | 登记 12 文件 vendor 根已锁；缺独立原 lzss／bitfile authority。 |
| `lzss-raw` | PASS — 明确五文件 C++ profile（5 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `neats-lossless-i64` | PASS — 登记完整选定 vendor tree（172 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `self-star` | PASS — 完整已冻结原生 package（10 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `serf-qt` | PASS — 登记完整选定 vendor tree（35 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `serf-xor` | PASS — 登记完整选定 vendor tree（35 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `simdcomp-u32` | PASS — 既有 SOURCE_LOCK 27 文件选集（27 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `snappy-raw` | PASS — 独立 Git 对应 native 编译选集（10 文件） | 独立 pinned Git 选集字节／集合 PASS；历史摘要序列化未声明。 |
| `sprintz-delta` | PASS — 独立 Git 对应 native 编译选集（17 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `sprintz-delta-u8` | PASS — 独立 Git 对应 native 编译选集（17 文件） | 当前 shared 17 文件树与原 Git 一致；历史 u8 摘要／选集未声明。 |
| `sprintz-fire` | PASS — 独立 Git 对应 native 编译选集（17 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `sprintz-fire-huff0` | PASS — 两组件完整选定源码树 | 两个独立 Git 选集及既有组合摘要 PASS；完整组件能力域另验。 |
| `sprintz-fire-u8` | PASS — 独立 Git 对应 native 编译选集（17 文件） | 当前 shared 17 文件树与原 Git 一致；历史 u8 摘要／选集未声明。 |
| `xz-stream` | PASS — 登记完整选定 vendor tree（341 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `zfp-accuracy-1d` | PASS — 登记完整选定 vendor tree（94 文件） | 独立完整 pinned Git root 可用；完整上游依赖／能力域另验。 |
| `zstd-frame` | PASS — 独立 Git 对应 native 编译选集（64 文件） | 独立 pinned Git 选集字节／集合 PASS；历史摘要序列化未声明。 |

## 失败保留和重放

初次审计 harness 缺 PyYAML，随后移除该依赖；r1 因 provenance 的 commit 字段位于另一份 manifest 而报 KeyError；r2 误把 FSE runtime profile 解释成全部 upstream lib；r3 使用字符串排序与旧 Path-component 排序不一致而得到两个摘要不符。均属于新审计 harness 的映射／协议问题，记录和当时 driver 保留，未改生产代码。主终态 r4 修正这些映射并全部 PASS。supplement-r1 的旧源快照缺失是实际当前副本缺口，r2 恢复只到新的审计目录并同时保留旧副本 FAIL。

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/source_closure/audit_sources.py --output-dir /tmp/tscb-source-closure-new
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/source_closure/verify_source_supplement.py --source-report /tmp/tscb-source-closure-new/report.json --output /tmp/tscb-source-supplement-new.json --recovered-source-dir /tmp/tscb-recovered-source-new
```

驱动拒绝覆盖现有输出。最终入口、脚本和 JSON 哈希见 [final_index.json](final_index.json)。当前生产代码／登记保持未修改；后续若修改受影响源文件，须重新运行对应 source proof。
