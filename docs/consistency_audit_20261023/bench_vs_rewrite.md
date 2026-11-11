# Bench 已接入算法与当前重写包逐项对照

日期：2026-10-23。重写目录基准：`/home/fzg/PycharmProjects/Compression_Rewrite/ReWrite/`。

活动 CPU 算法共53项：30项与独立重写包一致，9项与 lzbench 中原生源码一致，4项 ELF 未同步，10项缺少对应独立重写包。这里的一致是接入消费源码一致，不代表与未修改原生全域等价。

lzbench 是原生库集合，对应9项原生源码确实存在；独立包缺失的 FSE/Huff0 等不会因为其它工程中有同名底层源文件而被视为已有对应验收重写包。

| 序号 | Bench key | 当前重写包/实现路径 | Bench 与重写版对比 | 重写版与原生对比 |
|---:|---|---|---|---|
| 1 | `abba` | `abba-family` | 一致：消费文件与当前重写包相同  合同内语义一致；不承诺原生帧字节相同 |
| 2 | `alp-rd` | `alp-cwida` | 一致：safe-v1 消费文件相同  限定原生域一致；safe-v1 含安全修补，不声明全上游等价 |
| 3 | `alp` | `alp-cwida` | 一致：safe-v1 消费文件相同  限定原生域一致；safe-v1 含安全修补，不声明全上游等价 |
| 4 | `brotli-stream` | `lzbench/lz/brotli` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 5 | `bzip2-stream` | `lzbench/bwt/bzip2` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 6 | `cameo` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 7 | `chimp` | `chimp-family` | 一致：消费文件与当前重写包相同  合法源域原始码流一致；reserved EOF 等输入除外 |
| 8 | `chimp128-no-index` | `chimp-family` | 一致：消费文件与当前重写包相同  合法源域原始码流一致；reserved EOF 等输入除外 |
| 9 | `chimp128` | `chimp-family` | 一致：消费文件与当前重写包相同  合法源域原始码流一致；reserved EOF 等输入除外 |
| 10 | `chimp32` | `chimp-family` | 一致：消费文件与当前重写包相同  合法源域原始码流一致；reserved EOF 等输入除外 |
| 11 | `chimpn` | `chimp-family` | 一致：消费文件与当前重写包相同  合法源域原始码流一致；reserved EOF 等输入除外 |
| 12 | `chimpn32` | `chimp-family` | 一致：消费文件与当前重写包相同  合法源域原始码流一致；reserved EOF 等输入除外 |
| 13 | `deepzip` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 14 | `deflate-zlib` | `lzbench/lz/zlib` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 15 | `dft` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 16 | `dwt-dct-ii` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 17 | `dzip` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 18 | `elf-plus` | `elf-plus → elf-family` | 不同：旧包未同步；抽查 payload 与完整帧不同  限定源域原始码流一致；f32 含显式原生构建修补，正式状态 BLOCKED |
| 19 | `elf-star` | `elf-star → elf-family` | 不同：旧包未同步；抽查 payload 相同，完整帧不同  限定源域原始码流一致；f32 含显式原生构建修补，正式状态 BLOCKED |
| 20 | `elf` | `elf → elf-original` | 不同：旧包未同步；抽查 payload 与完整帧不同  合法源域原始码流一致；原生恢复缺陷仍在，正式状态 BLOCKED |
| 21 | `fabba` | `abba-family` | 一致：消费文件与当前重写包相同  合同内语义一致；不承诺原生帧字节相同 |
| 22 | `fse` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 23 | `gorilla-prometheus-xor` | `gorilla-prometheus-xor` | 一致：消费文件与当前重写包相同  冻结对象范围内原始字节一致；原生 partial-byte reset/append 缺陷保留 |
| 24 | `huff0` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 25 | `leats-lossless-i64` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 26 | `lz4-frame` | `lzbench/lz/lz4` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 27 | `lzsse2-raw` | `lzbench/lz/lzsse` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 28 | `lzsse8-raw` | `lzbench/lz/lzsse` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 29 | `neats-lossless-i64` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 30 | `pip` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 31 | `pmc-mean` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 32 | `pmc-mr` | `chimp-family` | 一致：消费文件与当前重写包相同  限定输入域语义一致 |
| 33 | `qabba` | `abba-family` | 一致：消费文件与当前重写包相同  合同内语义一致；不承诺原生帧字节相同 |
| 34 | `self-star` | `self-star → elf-family` | 不同：旧包未同步；抽查 payload 相同，完整帧不同  限定源域原始码流一致；f32 含显式原生构建修补，正式状态 BLOCKED |
| 35 | `serf-qt` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 36 | `serf-xor` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 37 | `sim-piece` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 38 | `simdcomp-u32` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 39 | `snappy-raw` | `lzbench/lz/snappy` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 40 | `sprintz-delta-huffman` | `sprintz-family` | 一致：消费文件与当前重写包相同  限定配置原始字节一致；保留作者 Huff0 封装规则，含安全修补 |
| 41 | `sprintz-delta` | `sprintz-family` | 一致：消费文件与当前重写包相同  限定原生移植；raw16 奇数尾字节截断修复会改变原版返回流 |
| 42 | `sprintz-fire-huffman` | `sprintz-family` | 一致：消费文件与当前重写包相同  限定配置原始字节一致；保留作者 Huff0 封装规则，含安全修补 |
| 43 | `sprintz-fire` | `sprintz-family` | 一致：消费文件与当前重写包相同  限定原生移植；raw16 奇数尾字节截断修复会改变原版返回流 |
| 44 | `swab` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 45 | `swing-connected` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 46 | `swing-filter-disjoint-quantized` | `chimp-family` | 一致：消费文件与当前重写包相同  源语义一致；保留原生质量缺陷，不能推断通用误差界 |
| 47 | `swing-filter-disjoint` | `chimp-family` | 一致：消费文件与当前重写包相同  限定输入域语义一致 |
| 48 | `swing-filter` | `chimp-family` | 一致：消费文件与当前重写包相同  源语义一致；保留原生质量缺陷，不能推断通用误差界 |
| 49 | `tp` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 50 | `vw` | `cameo-family` | 一致：repaired-v1 消费文件相同  与授权 repaired-v1 目标语义一致；未修改原版的全家族资格仍 BLOCKED |
| 51 | `xz-stream` | `lzbench/lz/xz` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |
| 52 | `zfp-accuracy-1d` | `缺失` | 缺失：无对应独立重写包  缺失，无法对比 |
| 53 | `zstd-frame` | `lzbench/lz/zstd` | 一致：原生源码复用，非独立翻译包  原生源码直接复用；选中源文件相同，非独立翻译版 |

以下两项仍有登记和历史接入源码，但当前已排除：

| Bench key | 当前重写包 | Bench 与重写版对比 | 重写版与原生对比 |
|---|---|---|---|
| `lzss-dipperstein-c` | 缺失 | 缺失：无对应独立重写包；Bench 当前排除  缺失，无法对比 |
| `lzss-raw` | 缺失 | 缺失：无对应独立重写包；Bench 当前排除  缺失，无法对比 |

独立 GPU 扩展：

| Bench key | 当前重写包 | Bench 与重写版对比 | 重写版与原生对比 |
|---|---|---|---|
| `cuszp-fixed-1d` | 缺失 | 无独立重写包；Bench 直接消费原生 CUDA kernel  缺失，无法对比 |

`raw-store` 是框架存储基线，不计入压缩算法；`lz77` 是别名，不重复计数。

完整哈希、源码对照和资格范围见同目录 README.md、source_identity.json；本表没有修改任何算法或登记。

原生对比列描述的是当前独立重写包的证据范围，不能用来替旧 Bench ELF 包签署一致性。SEMANTIC、合法域字节一致和原件哈希相同是不同结论；均不能扩大为所有输入/所有能力等价。

本次仅扩展表格，沿用同目录既有核验结果，没有重新执行测试或更换算法。
