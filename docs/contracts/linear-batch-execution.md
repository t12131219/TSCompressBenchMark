# 原生单列批执行候选

`batch-execution-plan --suite linear-v1` 将原生准入定义中的 **#9 `auto-batch`** 和 **#40 `zstd-baseline`** 绑定到同一个 CPU worker 构建、冻结计划及一份运行账本。与 [Gorilla 执行候选](gorilla-batch-execution.md)共用启动、限额、留存、复算与逐产物恢复机制，不重用旧探针的 PASS。重叠的义务引用同一个产品槽，负例和直接入口对照不是独立样本。该套件不授正式资格或研究计时。

| 路线 | 冻结执行范围与验证 |
|---|---|
| #9 ALP Auto | 15 个 f32/f64 正向用例：1023/1024/1025 向量边界、特殊位、两种语料域、decimal/RD/raw 和跨 rowgroup 选型、气象尾块。逐帧独立恢复原始位并核对 schema；ALN1 结构解析核对原始 raw 片段与异常位、向量及组计数，再与实际 scalar-unfused 解码记录比对。4 次 sidecar 损坏须返回 `BMK_CORRUPT=5` 且无列输出。气象用例另调用同一个锁定 `libalp_native.so` 的直接 C ABI，在 `FE_DOWNWARD` 下验证编码和解码均返回 `ALPN_INVALID`、产出量均为零并恢复舍入模式。**不**覆盖另组的 FALP/SIMD 后端资格；AVX512BW 条件保持不变。 |
| #40 Zstd baseline | 8 个正向产品、1 个真实输入资源拒绝。既有 65528/65536/65544 B 窗口边界，另有 0/1/65535/65536 B 字节用例以及两种新语料域。Zstd 消费逻辑对象的原始字节，f64 标签只供框架恢复，不授原生 typed V。核对实际 level 3 单线程基线路径、Zstd 帧内容长度、无字典/校验和以及窗口上限。8 个解码负例重建外封装后测错误原始长度和截短的**内层**帧，处置为 `BMK_CORRUPT=5`。用独立程序通过锁定的 vendored `ZSTD_compress` 生产 65536 B 用例参考帧，再实际交给插件恢复；并不要求两个编码器恰好生成相同的字节。 |

计划将解码器与直接控制工具封入共享 ELF 闭包；每个子进程仅挂载所需依赖。每操作继承 128 MiB 地址空间、1 MiB 单文件写入限额、5 s 墙钟截止，另有输入/输出与留存额度。上述不是总磁盘硬配额。帧、工具载荷和共享闭包各列字节；错误输入由已封存帧和冻结变换重建，不保留重复损坏帧。同一运行中，先删除编码输入临时目录，再按产物在独立命名空间恢复；独立审计中 ALP 舍入对照读取本次恢复得到的已校验原值，不读取语料。`all_product_expectations_met` 与 `all_candidate_obligations_evidenced` 分开；缺舍入工具的旧计划必须保留 `incomplete_required_control`。

```sh
# 已激活 tsbench；BUILD 是 TSBench 内的相对构建路径。
cmake -S . -B "$BUILD" -DTSBENCH_PLUGINS='alp-auto;zstd' -DCMAKE_BUILD_TYPE=Release \
  -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"
cmake --build "$BUILD" --target tsbench_cpu_worker tsbench_alp_auto tsbench_zstd \
  tsbench_zstd_batch_control tsbench_alp_fenv_control
./bmk lock-build --worker "$BUILD/tsbench_cpu_worker" \
  --plugin "alp-auto=$BUILD/plugins/codecs/alp-auto/libbmk_alp_auto.so" \
  --plugin "zstd=$BUILD/plugins/codecs/zstd/libbmk_zstd.so" --out /tmp/linear-build.lock.json
./bmk batch-execution-plan --suite linear-v1 --build-lock /tmp/linear-build.lock.json \
  --direct-control "$BUILD/plugins/codecs/zstd/tsbench_zstd_batch_control" \
  --alp-fenv-control "$BUILD/plugins/codecs/alp-auto/tsbench_alp_fenv_control" --out /tmp/linear-plan.json
mkdir -p results/linear-batch-candidate
./bmk batch-execution-run --plan /tmp/linear-plan.json --results results/linear-batch-candidate
# 将 RUN 设为报告中的 run_id 对应目录
./bmk batch-execution-report "$RUN"
./bmk batch-execution-restore "$RUN"
```

2026-11-19 [r3 唯一主报告](../../results/m0-linear-batch-20261119-r3/batch-report.json)，run `5c176149d8b0463ea39172f3212947c4`：**23 帧独立恢复，1 项编码限额拒绝；两组 14/14 项候选义务均有证据**。
[迁移恢复](../../results/m0-linear-batch-20261119-r3/restore-audit.json)重跑 23 帧、1 份外部 Zstd 入口产物、12 次损坏解码和 1 个 ALP 舍入对照；禁网挂载仅供复算的环境不含原构建或语料，报告逐字节一致。CLI/API 计划一致；130 项 Python 测试通过。[资源负测](../../results/m0-linear-batch-20261119-r3/resource-negative-controls.json)观察到 `ENOMEM`、1 MiB 界触发 `SIGXFSZ` 和墙钟截止，[账本负测](../../results/m0-linear-batch-20261119-r3/execution-negative-controls.json)拒绝伪造负例输入和舍入恢复，另保存独立取消提交。

r1 因单列恢复分派错误中止，未封存，不作成功证据。r2 的 23 帧恢复通过，但 ALP 舍入仍缺驱动；其旧报告保留不改。r3 独立提交，没有拼接过去的通过项。通用执行层仍需覆盖其余批路线与不同的流、查询和训练协议，才能应用到全范围阶段计划。

## 四路线 `extended-v1`

在 `linear-v1` 上增加以下两条，冻结四路线的一份计划、一次提交和一份账本。

| 新路线 | 冻结执行范围与验证 |
|---|---|
| #85 Titchy `batch` | 12 帧，含 u8/u16/u32/u64、分块与 split 边界。独立 TCHY v2 reader 核对原值、逻辑计数和实际 split；C11 直接工具链接同一锁定 `libtitchy_c.so`，字节比对并实际调用原生解码、短容量和配额拒绝。空块不主张已测短容量。独立验证不把流、访问或逻辑读取当成批能力。 |
| #31 ZFP `field-baseline` | 11 帧，覆盖 i32/i64/f32/f64、特殊位、边界及气象尾块；核对外封装、8 B 字对齐、串行 `zn_encode` / `zn_decode` 与原始位。负例只修改可在预检阶段拒绝的封装字段，不将任意裸坏流交给原生解码。动态闭包包含实际依赖 `libgomp.so.1`，不证明本次执行了 OpenMP 路线；不含多维、误差模式或 array。 |

[四路线主报告](../../results/m0-extended-batch-20261119-r1/batch-report.json) `9e100a86dd694079b8a823ea655f18b0`：53 槽，46 正向、7 输入拒绝，**23/23 项候选义务有证据**。[迁移恢复](../../results/m0-extended-batch-20261119-r1/restore-audit.json)重跑 46 份产物、162 次坏帧拒绝、12 份 Titchy 原生对照以及原 Zstd、ALP 各一项直接对照。禁网复算报告逐字节相同；[负测](../../results/m0-extended-batch-20261119-r1/execution-negative-controls.json)拒绝去掉 Titchy 调用和重标 ZFP 限额错误。

## 五路线 `extended-v2`：XZ baseline

增加 #39 `xz-baseline`，与 Zstd 绑定同一份 `liblzbench_native.so`。XZ 的四个字节用例覆盖 0、1、65,535、65,536 B；65,537 B 必须按输入资源界拒绝。独立解析核对单 Stream、Check=None、Index 及单 LZMA2 块的原始长和字典属性；空输入没有块。插件新进程从封装恢复原始字节。它不是 typed V，也不提供任意 XZ 流导入。

直接工具从同版 `ln_*` 入口重新编解码，检查裸 payload 字节一致、短容量、错原始长度、截断和绝对长度。**原生配置 `threads=1` 不等于调用线程同步**：三个非空正例各观测到一次编码 job、一个后台 worker、零 caller job，空例三者为零。用 1 B 帧重建 384 MiB 字典声明；vendored `lzma_stream_decoder_mt` 在 256 MiB 原生内存上限下返回 `LZMA_MEMLIMIT_ERROR`，legacy `ln_decompress` 将其报为无产出的 `LN_CODEC_ERROR`，插件报 `BMK_CORRUPT`。这三个层的结果分别记录，不把它当成 OS 地址空间拒绝。

XZ 单独锁定 256 MiB **进程地址空间上限**，其他路线仍是 128 MiB；两档都保留 1 MiB 文件上限与 5 s 操作截止。不是峰值内存测量或等资源性能组。[r1](../../results/m0-xz-batch-20261119-r1/batch-report.json) 在 128 MiB 下有三个非空 XZ 编码失败；[r2](../../results/m0-xz-batch-20261119-r2/batch-report.json) 按新计划从头独立执行，未复用 r1 的通过项。新版报告以 `selection/route/check` 确定检查名，避免 Zstd/XZ 同名检查合并。

```sh
# 已激活 tsbench；BUILD 是本项目内的构建路径。
cmake -S . -B "$BUILD" -DTSBENCH_PLUGINS='alp-auto;zstd;titchy-batch;zfp-reversible;xz-baseline' \
  -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"
cmake --build "$BUILD" --target tsbench_cpu_worker tsbench_alp_auto tsbench_zstd tsbench_titchy_batch \
  tsbench_zfp_reversible tsbench_xz_baseline tsbench_zstd_batch_control tsbench_alp_fenv_control \
  tsbench_titchy_batch_control tsbench_xz_batch_control
./bmk lock-build --worker "$BUILD/tsbench_cpu_worker" \
  --plugin "alp-auto=$BUILD/plugins/codecs/alp-auto/libbmk_alp_auto.so" \
  --plugin "zstd=$BUILD/plugins/codecs/zstd/libbmk_zstd.so" \
  --plugin "titchy-batch=$BUILD/plugins/codecs/titchy-batch/libbmk_titchy_batch.so" \
  --plugin "zfp-reversible=$BUILD/plugins/codecs/zfp-reversible/libbmk_zfp_reversible.so" \
  --plugin "xz-baseline=$BUILD/plugins/codecs/zstd/libbmk_xz_baseline.so" --out /tmp/xz-build.lock.json
./bmk batch-execution-plan --suite extended-v2 --build-lock /tmp/xz-build.lock.json \
  --direct-control "$BUILD/plugins/codecs/zstd/tsbench_zstd_batch_control" \
  --alp-fenv-control "$BUILD/plugins/codecs/alp-auto/tsbench_alp_fenv_control" \
  --titchy-direct-control "$BUILD/plugins/codecs/titchy-batch/tsbench_titchy_batch_control" \
  --xz-direct-control "$BUILD/plugins/codecs/zstd/tsbench_xz_batch_control" --out /tmp/xz-plan.json
mkdir -p results/xz-batch-candidate
./bmk batch-execution-run --plan /tmp/xz-plan.json --results results/xz-batch-candidate
# RUN 指向报告内 run_id 对应的目录
./bmk batch-execution-report "$RUN"
./bmk batch-execution-restore "$RUN"
```

要执行 `extended-v1`，移除 XZ 插件、构建目标、构建锁条目和 `--xz-direct-control`，使用 `--suite extended-v1`。

2026-11-19 r2，run `dc9cd4c7cd43496ca9176b9eb28b49de`：**58 槽，50 逐产物独立恢复，8 预期输入拒绝；五组 28/28 候选义务有证据**。[恢复审计](../../results/m0-xz-batch-20261119-r2/restore-audit.json)另外重跑了 171 次坏帧拒绝、XZ 4 次及 Titchy 12 次直接对照、ALP 舍入和 Zstd 参考帧。复算在不挂载原构建或语料的禁网环境逐字节相同，CLI 与 API 计划一致，136 项 Python 测试通过。[账本负测](../../results/m0-xz-batch-20261119-r2/execution-negative-controls.json)另拒绝伪造 XZ 内存负例摘要、将后台 job 改为同步，以及验证了 58 槽全部取消的终态。

本节不涵盖 XZ 扩展会话、多 worker 方法或正式测量，五路线仅有候选功能执行证据。不将其他运行（包括 Gorilla）的通过项并入本报告。

## 七路线 `extended-v3`：pcodec SourceAuto / C NativeAuto

将 selection #11 的 `source-auto` 与 `c-native-auto` 接入同一次批提交；用 `(selection, route)` 选路，同一 selection 的两个方法不互相覆盖。检查分别沿用原生准入定义的 ID。两插件与独立 C11 直接工具都动态链接同一个封存 `libpcodec_c.so`，构建保留 `PC_SOURCE_BACKEND=ON`、`PC_NATIVE=ON` 与离线 Cargo 依赖。**C NativeAuto 是 C 编码、Rust Source 解码**，不是纯 C 编解码方法；`-march=native` 也不证明执行过指定 SIMD 路径。

| 检查 | 同次执行及独立恢复 |
|---|---|
| 输入和适用域 | 同一批 13 个用例：11 种整数/浮点类型（含 binary16 原始位）、空 f64、773 行真实交通 f64。SourceAuto 恢复全部 13 份；C NativeAuto 恢复 12 份，f16 由 ABI 报 `BMK_UNSUPPORTED=1`，直接 `pc_compress_native` 报 `PC_UNSUPPORTED=5`、输出指针为空且字节数为零。 |
| 忠实性 | 原生 payload 与直接 `pcs_compress`（SourceAuto）或 `pc_compress_native`（C NativeAuto）逐字节一致。另一入口 `pcs_decompress` 直接读对应裸 payload、比较原始位；worker 在新进程从完整封装按原始 count 上限解码。不会因两个方法恰好产出相同的裸流就合并身份或互认封装。 |
| 格式与负例 | 分别核对两个外封装、原 schema、`pco!` v3 / wrapped 4.1、count hint、首块类型与行数。该独立解析只验证布局，不取代完整 native entropy 解码。每帧验证截断、尾随、缺元数据、错误 count 和错误方法封装；非空帧另验证原生 `PC_LIMIT=6` 与 ABI `BMK_RESOURCE_LIMIT=7`。留存完整产物，不另存一份相同的直接 payload。 |
| 从已封存产物复核拒绝 | 用同一计划中 SourceAuto 的 f16 正例恢复出的原始位及 schema，重跑 C NativeAuto 的 ABI 和直接 C 拒绝；按输入摘要与来源槽关联，不读取原始数据目录，也不留一份失败输入副本。 |

复跑用上一节命令，在构建清单加入 `pcodec-source-auto;pcodec-c-native-auto`，使用 `tsbench` 的 Python 和锁定的 Rust 工具链。增加构建目标和构建锁条目，再选择 `extended-v3` 和 C11 直接对照工具：

```sh
# 配置 BUILD 时将两个 pcodec 插件与上节五插件一起启用。
cmake --build "$BUILD" --target tsbench_pcodec_source_auto tsbench_pcodec_c_native_auto tsbench_pcodec_batch_control
# 在上一节 bmk lock-build 中额外加入：
#   --plugin "pcodec-source-auto=$BUILD/plugins/codecs/pcodec/libbmk_pcodec_source_auto.so"
#   --plugin "pcodec-c-native-auto=$BUILD/plugins/codecs/pcodec/libbmk_pcodec_c_native_auto.so"
# 上一节的 bmk batch-execution-plan 改为 --suite extended-v3，并额外加入：
#   --pcodec-direct-control "$BUILD/plugins/codecs/pcodec/tsbench_pcodec_batch_control"
```

2026-11-19 [七路线主报告](../../results/m0-pcodec-unified-batch-20261119-r1/batch-report.json)，run `7b60ce6f7ff74b1799635b6151384246`：**84 槽，75 个产物独立恢复，9 个输入按预期拒绝，39/39 项候选义务有证据**。[迁移恢复](../../results/m0-pcodec-unified-batch-20261119-r1/restore-audit.json)重跑 344 次坏帧拒绝（其中 pcodec 173 次）、25 次 pcodec 原生直接对照和 1 次 C f16 的双入口拒绝。无原构建/语料挂载的禁网环境可逐字节复算报告；CLI 与 Python API 计划相同。[负测](../../results/m0-pcodec-unified-batch-20261119-r1/execution-negative-controls.json)另验证 84 槽取消，拒绝删掉直接 C f16 拒绝、把 SourceAuto 改标为 C 或伪造拒绝带输出。139 项 Python 测试通过。

此运行未纳入 pcodec 的 `source-pages`、`native-pages` 或 `intmult`；它们仍用独立开发诊断，不计入此运行。pcodec 两种批方法沿用 128 MiB 地址空间、1 MiB 单文件以及 5 s 操作上限；没有压测整个原生输入域，也没有正式计时、SIMD 资格或阶段验收。

## 九路线 `extended-v4`：pcodec 原生 wrapped pages

在同一冻结提交中增加 #11 的 `source-pages` 和 `native-pages` 各一个**多文件产物槽**。两个方法调用冻结库的 `pcs_*`/`pcn_*` 分页入口，不调用 standalone ABI 插件伪装分页。原来的七条单帧路线仍完整执行。每条分页路线对应主账本的一行；一个产物中的四个文件不是四份收据，也不允许跨 run 补证。

- 用同一份交通测试窗的 **773 个 f64** 训练块级共享元数据，原生分页 `[513,260]`，原生读调用容量 256。真实操作先生成 page 1、再生成 page 0。分别封存 `meta`、`page-0`、`page-1` 和外部 `geometry.json`（dtype、count、capacity 和压缩字节长度）；本例各路线 **85 + 632 + 317 + 81 = 1,115 B**，含侧车。保留两条方法身份，不因本例裸流相同而宣称一般兼容或选模等价。
- 恢复先校验侧车，再分别启动进程逆序恢复 page 1 / page 0。每个进程**只挂载共享元数据和被选中的压缩页**，不挂载相邻页或原数据；实际返回 `[256,4]` 和 `[256,256,1]` 并验证 `finished`。原始域逐页和拼接后均验位。`native_input_bytes` 是实际给 native worker 的逻辑输入长度（402 或 717 B），不是物理 I/O，不含控制层解析的 81 B 侧车。
- 仅挂载 page 0 的反例不能初始化 decoder，Source 返回 `PC_TRUNCATED=3`，C Native 返回 `PC_INVALID=1`。会话控制验证容量 255 拒绝、当前页读完前拒绝下一页、首个小配额拒绝、尾随拒绝和错误后的状态。先完成 513 行后以 260 为配额开始第 2 页：**Source 接受，C Native 以累计配额返回 `PC_LIMIT=6`**；C Native 将配额设为 773 后同会话可完成第 2 页。C Native 在调用者压缩页缓冲被清零后仍恢复原位，验证它持有输入副本。
- 截掉第 1 页末字节的反例在两路线都先返回 **256 行**，然后 `PC_TRUNCATED=3`，未达到 `finished`。这不是对其他负例允许前缀产出的通用结论；也不把有界输出称为边接收边解码。页面已在启动时整页提供，故不授原生输入流资格。

复跑沿用 `extended-v3` 的插件和工具，再构建 `tsbench_pcodec_pages_control`，把 `batch-execution-plan` 改成 `--suite extended-v4` 并追加 `--pcodec-wrapped-driver "$BUILD/plugins/codecs/pcodec/tsbench_pcodec_pages_control"`。Rust 构建继续使用随包依赖及 Cargo `--offline --locked`；`PC_NATIVE` 不构成 Rust 或 C 路径 SIMD 实测。仍需在 `tsbench` 环境执行。分页驱动加入共享 ELF 闭包，两个协议操作组经 `pcs_*`/`pcn_*` 直接绑定，不增加独立 codec 插件。

2026-11-19 [r2 主报告](../../results/m0-pcodec-wrapped-20261119-r2/batch-report.json)，run `59b37809543041e1aa8f562327b3639b`：**86 槽，77 恢复，9 项预期输入拒绝；51/51 个候选义务**。 [迁移复核](../../results/m0-pcodec-wrapped-20261119-r2/restore-audit.json)重跑两份分配置分页产物的 4 个独立页、2 个缺元数据拒绝及两种配额会话；主报告禁网复算逐字节一致，CLI/API 同计划。[负测](../../results/m0-pcodec-wrapped-20261119-r2/execution-negative-controls.json)拒绝删共享元数据、把累计配额伪装成按页和把首个 span 当整页完成。[r1 失败](../../results/m0-pcodec-wrapped-20261119-r1/batch-report.json)的控制错误是假定截断前有两个完整跨度；已保留失败原貌，r2 重新冻结完整运行，不拼 r1。IntMult 不在本次；不授阶段资格或正式计时。

## 十路线 `extended-v5`：同次 Gorilla C11 对照与全分母绑定视图

在 `extended-v4` 的九组之外加 #7 `tv-batch`，复用原有输入和直接 C11 对照 driver，但所有产品与对照都在**新的一次提交中实际执行**。`gorilla-tv` 插件、直接 C driver 与 `libgorilla_c.so` 共用 CMake 构建，文件依赖按 ELF 闭包核验；Gorilla 仍使用 16 KiB 的单文件限制，只有 XZ 将进程地址空间提高到 256 MiB。pcodec wrapped 保留独立元数据、页面与侧车。历史 v2 Gorilla 和 v3 批报告未改版。

[统一执行计划](../../results/m0-unified-batch-20261119-r1/build/batch-plan.json)内封存整份原生准入定义，另给出 `case_products` 和 `execution_binding`：按 `route → obligation → case → product slot` 关联原始输入，按产品标明有效参数（含负例）、进程限额、输入字节、产物上界、操作顺序、实际 driver 和恢复所需程序；程序索引引用共享封存的精确 ELF 文件闭包。直接调用、发布产品恢复和坏帧控制保留为不同操作。只把每个声明的产物或拒绝记录一次，重叠义务引用同一产品。未绑定的 125 项必需检查与 6 项条件检查仍明确列出，不以编译或历史探针代替。

```sh
# 使用 tsbench，不使用 base；输出目录必须为空。
bash tools/probe_offline_unified_batch.sh /home/fzg/anaconda3/envs/tsbench \
  /home/fzg/.rustup/toolchains/stable-x86_64-unknown-linux-gnu \
  results/m0-unified-batch-repro
```

`--suite extended-v5` 的 CLI / Python API 同计划，新增 `--gorilla-direct-control` 绑定同构建 C driver。2026-11-19 空目录禁网构建运行 `ad905f634b48448b9563b6474d47b282`，**95 槽、85 个产物独立恢复、10 项预期拒绝、10/36 组的 55 项候选义务获得本运行证据**，包含 6 个 Gorilla 双向交叉解码和 2 个 pcodec wrapped 产物（4 页）。[主报告](../../results/m0-unified-batch-20261119-r1/report.json)从只挂载封存运行和报告代码的目录逐字节复算，[独立恢复](../../results/m0-unified-batch-20261119-r1/restore.json)不挂载输入或原构建。[控制](../../results/m0-unified-batch-20261119-r1/controls.json)核对 593 个独立操作会话并拒绝跨路线替换用例、删除条件/对照槽、篡改限额和省略 C 依赖；152 项 Python 测试和 12 项 CTest 通过。

只冻结当前执行边界，而非适用所有操作组的正式资源与保留政策。日志最坏容量是进程单文件限制的算术上界，不是预分配或磁盘可用量保证；实测账本列出实际保留字节。当前尚无 36 组完整的正式计划、动态调度/检查点或计时准入；ALP AVX512 对象仍构建，本次没有实际调用该后端，未授任何正式资格。

## 十二路线 `extended-v6`：SElf* 顺序批与完整逐值块

`extended-v6` 在现有统一执行器中增加 #4 的两组 9 项候选义务，保持其逐块学习和恢复语义；不是把批算法包成在线流。批插件和直接 SElf* driver 在同一构建中链接 `libselfstar_c.so`，逐值对象可以仅挂载直接 driver 的 ELF 闭包恢复。所有操作仍由同一个计划及主账本调度，产品独立计费，不引用其他运行的通过项。[SElf* 机制合同](selfstar-native.md)说明 `finish`/终止符、状态丢失与重播证据。

```sh
bash tools/probe_offline_unified_batch.sh /home/fzg/anaconda3/envs/tsbench \
  /home/fzg/.rustup/toolchains/stable-x86_64-unknown-linux-gnu \
  results/m0-ordered-selfstar-repro --ordered
```

[计划](../../results/m0-ordered-selfstar-20261119-r1/build/batch-plan.json) `671120cca6bad88f40c99d690ea36dab9fe4f4a62b2e3c1806ce4b0c0d9c2968`，run `5f678302a30744119796016ecce2f153`：**120 槽、103 个产物独立恢复、17 项预期输入拒绝**，含 SElf* 18 个产物和 7 项输入拒绝。共 12/36 组、64/180 项必需义务有本次候选证据；116 项必需及 6 项条件仍未绑定。禁网空构建的 152 项 Python 测试和 13 项 CTest 通过；六项负检及迁移后字节复算通过。不增加正式资格，不改变 ALP AVX512 条件。
