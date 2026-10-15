# Validation report

**REWRITE_DONE / FULL_PARITY**。标准 v3.0、合同 v1、SOURCE_REWRITE /
TRANSLATED / BYTE_IDENTICAL / P1_STANDALONE_CODEC；Linux amd64 与 AArch64
LP64（后者 QEMU），仅冻结 EncXOR 完整 chunk。

| Gate | Evidence | Result |
|---|---|---|
| G0 | 唯一逻辑对象/别名去重，完整 T/V 码流 | PASS |
| G1 | 来源、哈希、许可、Go runtime、CI/capability inventory | PASS |
| G2 | contract、golden、10 项 required 与 dataset plan | PASS |
| G3 | fresh oracle；227×6 profiles；bit-exact/four-way/stage trace | PASS |
| G4 | 1051576 public API assertions；guard/canary/bound/生命周期 | PASS |
| G5 | forced optimized 实际计数；全量 differential；TSan | PASS |
| G6 | 文档、SBOM、qualification performance、双构建与封包 | PASS |

ASan/UBSan/LSan：全部生产编解码 TU 与两个 path、API/CLI 插桩通过。
TSan：独立 handles、读快照与追加并发通过。Clang analyzer 无 diagnostics。
libFuzzer：100000 runs，34 秒，seed=20261014，max_len=4096，
两个路径接受/拒绝及恢复一致，无 sanitizer 错误。另有每 path 10000 个固定
seed 的 malformed 输入及截断/长度/varint/window/padding 安全拒绝测试。

Golden expected 完全由源程序生成；full header/padding raw bytes 不裁剪。
source raw-reset-after-partial-byte 的已知缺陷由 state/results.json 独立证实；
重写保留 literal reset 输出/relaxed decode。strict decoder 的安全增强明确
拒绝额外尾部、非法 XOR width、超资源与非零 padding，不改变合法源流。

证据为当前 fresh source parity，不继承旧包/Bench 资格。AArch64 为 QEMU
实际运行，安全插桩覆盖 amd64；其他平台和正式性能不签 PASS。全部 logs、
输入、源输出、双向 decoded 输出、hash/命令保留；无 waiver、无接入变更。
