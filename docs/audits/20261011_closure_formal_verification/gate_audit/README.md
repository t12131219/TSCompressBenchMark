# 完整 N／G／CAP 门禁可满足性盘点（2026-10-11）

本次对现有 33 个入口进行独立静态调查，没有运行 codec、pytest、源模型、训练或性能测量，没有安装或下载包，没有修改原源码、registry、配置或历史审计。文档中的命令是被检查的验收依据。输出：[逐入口行动与当前证据](report.json)、[本地环境和包载荷盘点](environment_inventory.json)、[来源／模型资产](source_assets.json)、[冻结能力盘点](capability_inventory.json)。本次盘点不签发 N0–N5 全部通过、G0–G6 全部通过、FULL_PARITY 或 REWRITE_DONE。

依据是移植标准 V3.0 的 §2.5–2.8、G0–G6/CAP、§38.2、§114.1–114.7 和 §105；当前路线来自原审计 `rewrite_routes.json`，未新增算法。源文件、环境和历史记录的哈希固定在本目录 `report.json`；其中已声明执行依赖 33/33 的验证结论是引用此前实际 factory 证据，不是本次重新调用 factory。

## 门禁的适用范围与可补行动

原生路线允许按事前冻结的 profile 完成 N0–N5，其范围外的上游能力仍留在 SourceCapabilityMatrix。完整上游 FULL_PARITY 则必须覆盖全部已冻结 REQUIRED_PARITY。核心重写的独立 REWRITE_DONE 必须完整完成 G0–G6/CAP，不可用 CPU-only 或单个固定参数 profile 追溯缩小完整合同。

| 门禁 | 已有实证与本轮静态结果 | 完整验收还要完成 |
| --- | --- | --- |
| N0 来源路径／对象 | 22 个原生入口的实际路线、原生核心及 P0/P1/P2 角色已在逐入口审计明确 | 核对完整源能力 inventory 与当前目标分界，review 去重及方法／来源身份；不能仅凭路线标签签全部 N0 |
| N1 来源／构建基线 | 原生实际 TU/header/object/宏/动态库及 build-copy patch 已有限定记录；所有 33 入口声明依赖经此前 factory 核验 | 补实际 compiler/linker/process trace、生成步骤、隐式启动／静态 runtime archives、完整依赖和许可证／SBOM；核未修改基线。Dipperstein 尚缺独立原始 authority。来源库存 24 个 UNKNOWN 不自动等于 N1 失败：应核其实际选定构建闭包和 hash 协议，不能机械要求整个上游仓库均参与构建 |
| N2 合同／偏差 | 当前输入、资源、raw/frame、状态、误差、patch／变体及部分源缺陷已登记 | 逐 scope 冻结兼容目标、源能力／必需能力分类及独立 oracle、真实数据／平台测试计划；事后测试成功不可替代事前计划 |
| N3 核心／API 安全 | release/sanitizer、非空测试、容量／生命周期／恶意描述符、独立恢复已有有限实测 | 对本次声明范围建立逐 API 必测映射并检查覆盖；guard/padding/bound−1、失败后重用、cold decoder、并发及适用 race 检测未覆盖项保持 UNKNOWN；未插桩外部库不能借封装 sanitizer PASS |
| N4 一致性／能力 | Java 六入口 fresh raw 对照、LZSS 固定 profile Rust 对照及部分原生 API／字节对照已存在 | NATIVE_PORT 对每个受影响路径与未修改基线比较同一 canonical input／参数／状态；补原生公开 API 独立 baseline、真实数据／已承诺 ISA／线程／平台，不把 raw 核心结论转授外层 frame |
| N5 独立交付／交接 | 当前 source/API/driver 和构建 recipe 可盘点 | 在隔离目录只消费已声明资产完成独立构建／测试／cold restore；核 patch/closure/SBOM/license/report 索引；不依赖未声明 Bench runtime/registry。N5 不要求先取得 FORMAL |
| G0 资产／对象 | 11 个 SOURCE_REWRITE 及各对象角色已明确 | 独立包逻辑 AlgorithmID／ImplementationID、来源映射和去重审阅；Bench hash ID 不等于独立包逻辑 ID |
| G1 源／许可证／能力 | 原 Java/Rust/Python authority 与大量历史元数据仍可读取；当前 fresh 和归档重放分开 | 真实 source-language closure、精确可运行 oracle 环境、许可证／SBOM、完整 public API/build/docs/CI/tests 能力 inventory；训练源环境暂不具备本地离线恢复条件 |
| G2 合同／oracle | 源域、当前变体、部分参数 profile 和独立向量存在 | 审阅全功能四态 CAP 分类及 owner/platform/test；完整公式／状态／bitstream/error 目标、兼容真实数据选择和原源 oracle 冻结；不得把 native seed 自回环当源 expected |
| G3 canonical 正确性 | 613 Java 合法无损、282 LZSS 固定 profile、ABBA/fABBA 阶段／稳定化差分及有限 CPU 模型证据 | 对全部必需 canonical 功能执行相同真实数据、预处理、配置、模型及 reset/block 边界的源差分／交叉解码；同时完成合成边界、malformed 与 sanitizer，源缺陷拒绝单列 |
| G4 独立 API／资格 | 一些 standalone CLI、原生 API／当前有限 preflight 已存在 | 独立包 API 直接暴露全部 required 功能并通过生命周期、所有权、容量、FinalBits、冷恢复；Bench binding 或旧源 raw CLI 不能替代全部 current standalone API |
| G5 required 优化 | 有现有 SIMD/线程/CUDA 核心和历史记录 | 逐 required variant forced-path 证据、canonical differential、资源／并发／tail／平台；CUDA unavailable 不是 CUDA 执行 PASS，cross-compile 不代替目标机执行 |
| G6 独立发布 | 历史独立发布记录被保留 | 当前变更后的包独立 build/test/release、真实数据报告、correctness/security/portability/performance/license/docs/reproducibility 和 CAP closure；旧发布快照不反向授新 vendor |
| CAP-GATE | DeepZip 原矩阵 24 个 required，DZip 14 个，ABBA/fABBA 各 2 个；完整列表见 JSON | G1 inventory、G2 四态分类、G3功能、G4 API、G5优化、G6逐项报告均完整；历史总体 FULL_PARITY 不迁到当前新 scope；缺 required 实证阻断完整声明 |

`REPORT/UNKNOWN` 表示本次没有完成相应验收；它不把以前有限测试 PASS 改写为运行失败。若补执行暴露源缺陷、行为差异或安全错误，应保存原结果和首个 divergence；不能降低原 required 分类来消除问题。

## DeepZip／DZip 的本地可复现性

当前所有检查到的 conda 环境均未找到 TensorFlow 包目录。ArchCanvas 的现代 Keras 3.x 与已锁 Keras 2.2.2/TF1.x 不兼容，不能用它签旧原作 parity。三个已锁临时 Python 路径均缺失。原历史 metadata archive 保存了环境锁和完整报告元数据，但其中没有 `.whl`、`.conda` 或 `.tar.bz2` 安装包载荷，也没有被假定为可执行环境。

搜索 conda 包缓存、显式旧 `/tmp` cache、Compression_Rewrite、Compression_Source_Code、材料和 pip cache 后，70 个锁定安装包**引用**中 21 个可按 SHA 取得，49 个未找到；包含重复引用时不按 70 个唯一包计数。pip 的无文件名缓存载荷亦按已锁包大小筛选并核 SHA。关键 Python 3.6.13、TF-GPU 1.8、TF-CPU 1.14、Keras 2.2.2、NumPy 1.16.4、CUDA 9/cuDNN 7.1.2 均没有在这些根中找到精确载荷；所以本次不能完成精确 oracle 的本地离线重建。搜索范围与读错误全部保存在 JSON，不声称搜索过整台主机所有路径。

`nvidia-smi --query-gpu=name,driver_version --format=csv,noheader` 本次退出 9，当前进程不能与 NVIDIA driver 通信。此结果仅表示当前执行上下文不可用，不能单独证明主机没有 GPU、不能签 CUDA PASS，也不构成正式 waiver。历史环境文档还明确要求设备访问并提醒 sandbox probe 的限制。

DeepZip authority 保留 **152 份 trained HDF5**，包括 SHA 匹配的 xor20/biGRU checkpoint。当前四符号 CPU 的 17 个原构造器未训练 fixture 不等于这些已训练模型；当前 CPU 对 51 个存档 TF context 的概率对照不等于本次原 TF 执行。完整条件需要恢复原环境并按模型／字典／训练合同执行原 source checkpoint loading、完整概率/CDF／arithmetic pipeline，以及 required GPU prediction 路径。已训练模型存在与全部模型路径可运行是不同结论。

DZip 当前 `NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET` 变体不等价原 TF initializer 或 loaded trained PRNN。源 README、`train_bootstrap.py` 和 models 明确有预训练 bootstrap、CPU online adaptation 及官方 CuDNN bootstrap GPU 路径。应独立对照 bootstrap 权重、每步 online Adam/状态/CDF、full batch/tail、HDF5/BSC 恢复和真实训练轨迹；GPU BPC estimator 不产生完整码流，其范围不能与官方 bootstrap CUDA 路径混淆。原矩阵的 `REFERENCE_ONLY` 是历史标签，不属于 V3 四态；新审阅须依据原来源／对象说明其应采用的有效分类，历史文件不改写。

DeepZip/DZip 的历史矩阵分别引用 123 和 65 次验证路径，当前 vendor 目录下均没有对应验证文件，但归档 metadata 可以取得这些路径。它们是历史可读性，不能当 fresh execution。ABBA/fABBA `tests` 中的 `golden`、`dataset` 等是案例标签，不被本盘点当成缺失文件路径。

## 逐入口下一步

以下行动保留现有范围，完整机器可读步骤见 `report.json`。公共前提是补实际构建／运行闭包、许可证和独立交付；除特别标出的外部资产问题外，本表表示可进一步组织验证，不预先保证执行通过。

| 入口 | 需取得的独立验收证据 |
| --- | --- |
| lzss-raw | 固定 EI10/EJ4/C32 已有 raw/cross-decode；另核完整 generic/dynamic/in-place 能力、真实数据、独立 current core/API 发布 |
| lzss-dipperstein-c | 先补 pinned 原 lzss/bitfile 独立 authority，再重放 sentinel patch 并与未修改合法流／file API 对照 |
| deflate-zlib | 原 zlib 公开 API baseline；完整 RFC1950 stream、flush/finalize/reset/backpressure/capacity 与冷恢复 |
| lz4-frame | 完整 LZ4 frame 独立 baseline、output.used/EOF/reset 修复前后合法流和状态；raw block 比较对象另列 |
| snappy-raw | 原 Snappy raw API 同对象对照、容量／扩张／malformed／typed 冷恢复 |
| zstd-frame | 完整 Zstd frame 独立 baseline、output.used/EOF/reset；保持已冻结单线程无字典 profile 与源完整能力分界 |
| brotli-stream | 原 Brotli stream API baseline、Finalize/重用/backpressure/容量，静态字典与外部字典分别说明 |
| xz-stream | 原 XZ/LZMA2 preset6/checkNONE API baseline、结构 CRC、stream 生命周期／尾块／冷恢复 |
| abba | 完整 Python＋CKmeans 调用图、参数／tie/增量路径，阶段组合与未改完整 oracle 分开；当前长度安全修复的新独立发布 |
| fabba | 稳定化变体与原 AGG 的分界、required parallel partition、实际线程／race／state/tail及真实数据独立发布 |
| neats-lossless-i64 | 原基线＋三 patch，scalar/min-shift/predictor/serialization/index/query独立差分；不冒称源 SIMD 已验 |
| leats-lossless-i64 | 共用闭包但独立验证 LeaTS binary64 predictor、序列化／query边界和 signed 极值 |
| sprintz-delta | 原 delta 与 patched staging 同8/16-bit矩阵／维度／tail；实际 AVX2/BMI2/LZCNT、guard及分配失败 |
| sprintz-delta-u8 | 低维 u8 delta 单独源差分／staging/ISA/tail，不能借宽域入口通过 |
| sprintz-fire | FIRE predictor 溢出／分配 patch 前后合法数值、字节／状态及8/16-bit group/tail/真实ISA |
| sprintz-fire-huff0 | 两个独立 stage oracle、P2逆恢复/完整账本、HUF entropy/RAW、ISA/tail |
| sprintz-fire-u8 | 低维 u8 FIRE 独立 predictor/overflow/staging/ISA/tail验证 |
| chimp | fresh raw 对照以外的全部 required公开功能、真实数据及当前独立包/API发布 |
| chimp128 | N128 profile以外的 required N参数／状态/API inventory及独立数据／发布 |
| elf | 保留 END/scale/significance拒绝和既有许可决定范围，补全公开功能／真实数据／独立发布 |
| elf-plus | 82合法＋2END与8存档预期拒绝分别保留；需要的新原 source失败复现不得冒称已完成 |
| elf-star | 保留无关 helper compile overlay身份与真正未改算法路径；补全CAP/独立发布 |
| self-star | network6例以外的required network/共享状态/block/reset等公开API和真实数据，Bench未开放能力另列 |
| alp | 三安全patch原基线对照、强制decimal决策／reject、f32/f64 rowgroup/tail/ISA；RAW组合独立 |
| alp-rd | 强制RD dictionary/exception路径、rowgroup/tail/ISA独立对照；源自适应能力inventory保留 |
| serf-qt | Qt分支三patch数值与恢复对照、原域完整误差／RAW/tail，不能借XOR证据 |
| serf-xor | XOR分支独立 overflow/IEEE/RAW/error/tail／状态对照 |
| zfp-accuracy-1d | 原serial accuracy1D f32/f64同列baseline、实际tolerance/header/error/tail；异常RAW分开 |
| deepzip | 精确原环境、17构造器／trained checkpoint／完整CDF-codec／HDF5/CUDA required专项和独立发布 |
| dzip | 精确原CPU／官方GPU bootstrap环境，source初始化／trained PRNN／训练与online轨迹、HDF5/BSC和独立发布 |
| huff0 | 原HUF API与项目RAW/RLE/HUF完整frame分别验证容量／错误／成本／冷恢复 |
| fse | 原FSE API与项目RAW/RLE/FSE完整frame分别验证容量／malformed／成本／冷恢复 |
| simdcomp-u32 | 原C plain uint32各API/SSE4.1/AVX2 forced-path、宽度0…32／guard/padding/tail、P0恢复协议 |

## 证据边界

本目录提供当前完整门禁的行动计划与本地可满足性证据。原能力矩阵／完整回归／入口资格的成功范围保留；需要缺失包、原始 authority 或可用设备的完整验收项保持未授予。当前声明 profile 的新 RunSet／FORMAL 可以按 V3 另行验证，且必须附 profile／模型／变体与闭包身份，不得标成上游 FULL_PARITY。

首次以 CompressBench14 Python 启动本静态盘点时缺 PyYAML，退出 1；没有执行任何 codec 或生产测试。之后使用本机已有 PyYAML 的 Python 完成盘点，没有安装依赖。独立盘点驱动和实际解释器身份在 `report.json` 中保存；运行前后其引用的六份历史／验收依据字节完全相同。
