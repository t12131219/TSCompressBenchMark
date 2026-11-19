# 首批原生功能验收：用例定义与未绑定项

`bmk native-contract-plan` 读取 [原生功能定义](../../configs/suites/m3_first_batch_native_v1/contract.json)，
生成一份面向 **M3 原生功能资格**的 M0 定义计划。它不是运行入口，与 M5 的 204 展示格 / 264 原子关系、
正式研究性能套件及 M0 可执行开发预检分别保留身份。定义计划 `runnable: false`；不会从 Unique 历史报告、
开发探针结果或绑定用例数量生成资格。

```sh
conda activate tsbench
./bmk native-contract-plan --out results/native-requirements-plan.json
```

CLI 与 `tsbench.api.plan_native_requirements(root)` 产生同一个内容身份。每条定义绑定 selection ID、
归档 SHA-256、目标、头文件和入口声明；与原生 inventory 的 12 项、36 组逐一闭合，漏组、重复组、
绑定到别组或未知要求、遗漏现有边界用例都会拒绝。定义中区分：

- **必需：**180 项，覆盖各组的适用域、实际机制、原始域质量、边界及失败；全部关联开发用例，共 215 个。
开发绑定覆盖不等于方法质量通过、正式执行绑定或正式资格。
- **条件：**六项，指定所需构建、硬件或工作负载谓词，如 ALP f64 可用 AVX2、Zstd 多线程启用且输入够触发 worker。
  定义保持 `requires_build_and_workload_evidence`；构建成功不代表实际调用，未运行也不代表不适用。
  开发预检的同次解析见下文，不代替正式条件资格。
- **不适用的原生主张：**26 项，均保留理由。例如 pcodec page drain 不算单遍在线流；Titchy callback 字节不算物理 I/O；
  CORAD 相关阈值不是原始域误差界。这里不排除这些任务的外置有效服务，也不改变 M5 分母。

功能定义预先指定 `artifact_each`、产物与所需资产的完整字节、独立新进程恢复与保留每个用例的恢复样本；不采集性能。
未冻结的逐方法输入域、数值质量与访问/资源预算、正式条件资格和执行驱动保留为开放项，不能套用开发上限或从
实际得分反推阈值。正式性能仍需独立套件、比较键、资源档、验证强度与统计政策。

后续的[原生准入定义](native-admission-plan.md)将本计划作为输入，绑定逐组域、质量、访问完成和恢复保留合同；
正式执行绑定仍不由开发 case 代替。

## 同次开发证据的条件判定

`native-contract-plan` 冻结六项 `conditional_plan`；`native-plan` 绑定探针、操作分组、用例包和报告路径。
`native-report` 先核验单账本与该探针的封存材料，再生成 `conditional_native_work`。只接受同一运行的绑定证据；
失败、跳过、取消等终态一律为 `not_observed`，不猜测构建或硬件。所有行的 `formal_qualification` 仍为 `not_run`。

[封存的禁网预检](../../results/m0-huff0-same-run-control-20261119-r2/native-report.json) 的实际判定：

| 条件项 | 开发判定及证据 |
|---|---|
| ALP f64 AVX2 | `observed_satisfied_in_development`：实际解码一个 decimal 向量，原生计数为 1；独立恢复逐位一致。 |
| ALP f64 AVX512BW | `pending_supported_runtime`：已构建，本宿主不可用。保留原生路线；兼容宿主上要求显式及 Auto 在含 decimal 的同一 f64 帧有效分派并独立逐位恢复。该后端不暴露原生向量计数，不填 0 或推算计数。 |
| ZFP OpenMP | `observed_satisfied_in_development`：serial/OMP 1/OMP 2 实际编码线程为 1/1/2，均执行 2,048 块；解码仍由调用线程完成并核对原值位模式。 |
| Zstd 原生 worker | `observed_satisfied_in_development`：相同输入和其余选项，`0` 没有后台作业，`2` 实测两个后台线程和 11 个编码作业；不据此声称解码多线程。 |
| XZ 原生 worker | `observed_satisfied_in_development`：调用线程同步、一个和两个后台 worker 是三个剖面；解码都输入同一份 `workers-2.xz`，实测 0/1/2 个后台线程。分别记录编码与解码任务，不用各自编码帧比较解码 worker。 |
| Huff0 BMI2 | `observed_satisfied_in_development`：动态 BMI2 与显式 portable 构建解码同次留存的 5 份 FEC1 载荷和 14 份 ETB1 块（4 个模型），恢复摘要一致。FEC1 4X、ETB1 1X、ETB1 4X 两侧均为 3/4/4 次实际调用，BMI2 参数分别为 1 与 0。未配置 portable 或对照未通过时，不得从历史补齐。 |

## 已物化的开发用例

[已有边界配置](../../configs/suites/m0_method_boundaries_v1/cases.json) 现在由计划和执行共用；新 schema 拒绝
未知参数及错误用例定义。14 个用例固定留出窗口或小型位模式、规范输入与 schema 摘要、ABI 类型、参数身份、线程数、
预期后端、恢复任务与预期边界行为。每个用例都有稳定的 `case_id`；v3 两个新增域仍只比较 V，Zstd 标为 byte codec，
Gorilla 单独保留完整 TV 任务。

`native-plan` 把新定义计划 ID 和边界用例清单一起封入单一开发运行。执行时不仅检查报告/文件存在，还核对
**用例集合、顺序、输入和构建摘要、实际后端与线程、恢复的 dtype/shape 和位级摘要、帧哈希及大小**。ALP 检查已解析的
向量数；Zstd 与 Gorilla 的超限项必须实际返回 `BMK_RESOURCE_LIMIT`，且不得留下帧。复算只读取封存计划与证据，
不重新读取源数据或解码。它能检出声明与证据错配，不是对任意不可信执行器输出的密码学证明。

[Titchy 访问用例](titchy-native.md) 复用一个探针和一份留存 TCHY，从同一个冻结的原始数据窗口
分别绑定三个检查：复用 reader 的查询位模式、打开及逐次请求的逻辑读预算、无状态 range 的原始数据切片。
该探针也运行流和批的既有诊断，但这三项不替它们授予用例绑定，更不把整次探针的通过映射到该算法全部必需项。

[PBEPLA-RR](pbepla-native.md) 绑定 33 个开发用例，覆盖两组全部九个必需检查。原有七份输入上，渐进组逐层验证
独立前缀、精确原始域误差和有效界及字节，replay 组在三份输入上核对同版批载荷、各层误差和多遍输入及暂存账。
新增边界用例实跑值层上限的接受与超限拒绝；复算核对参数及非有限值拒绝、派生坏帧、四类 replay 故障、
资源释放及留存的失败输出。关联多个检查不重复跑算法或复制输入；开发绑定不上升为正式资格。

[CORAD 冻结模型推理](corad-native.md) 用同一份原值和六份帧，为六个必需检查绑定九个开发用例：
有序有限列、模型身份及尾部、独立恢复、原始域误差、预声明质量界、错配及限额拒绝。每个用例的身份包含
原值摘要和所引用的帧定义；复算从封存 CRD1 重建零行模型的哈希及恢复值，再重算每列最大
绝对误差和 RMSE。`bound_predeclared_before_formal_run` 绑定只读取 train 校准数据的逐列经验界；
两份冻结部署在此 test 窗均 `quality_rejected`。不能把探针成功当作质量达标。

[CORAD 训练](corad-native.md) 用同一有序训练/留出分区，另绑定 C 训练六项及 Source 训练五项。
前者核对 LARS/CD 解析答案、内层 KKT 与外层预算终态、种子重复和模型；后者核对原样桥及 tsbench 锁、
实际训练矩阵、两次独立拟合的预算和字典到 CRD1 的绑定。三个新模型均另做留出恢复；只报告质量观察。

[Gorilla C11](gorilla-tv-native.md) 按 TV 批、append/snapshot/resume 与 iterator 三组绑定 11 个检查。
同一套语料窗口与合成位模式用于保留的 TV 帧和 snapshot，后者另由新进程直接恢复；离线报告重解码流，核对
恢复摘要、尾部及两条续跑路径，验证重复时间戳和 EOF 的实际 seek 结果。独立 ELF 进程追加观测 resume
扫描行、终止调用和源块复制字节，以及 seek 命中、前进和不回退的实际扫描量。不改变选择、资格或服务分母。

[ALP Auto](alp-native.md) 的 `auto-batch` 与 `decode-backends` 新绑定九个必需检查，两组共十二条必需检查
均有开发用例（其中三条原有方法边界用例绑定不变）。封存九份帧及气象尾块原值；实际运行逐位恢复，离线
复算解析 ALN1 分支、侧信息、恢复摘要及 dispatch 证据。两个 SIMD 条件项仍独立，不用必需项绑定替代运行时证明。

[Zstd / XZ](lzbench-native-operations.md) 同一冻结库的探针共绑定 30 个必需检查：Zstd 裸批四项、
Zstd 原生会话五项、XZ 裸批五项、XZ 原生会话五项、Zstd 字典五项、Zstd worker 三项、XZ worker 三项。
复算核对帧旗标、Zstd 字典身份及恢复依赖字节、XZ 多块 Index、CRC64、每块 filter 链、预算拒绝的同一负向帧，
以及 worker 对照的实际选项、恢复摘要和既有跨度账。XZ 的 `synchronous_control` 由同一冻结包的调用线程
Block 编码和 Stream 解码诊断覆盖，不把 `threads=1` 的一个原生 worker 当同步。条件项不因开发探针成功
而改变正式状态。逻辑输入估计按内容去重，计入字典训练和留出样本及 worker 的源输入，
不重复计不同 profile 或留出样本的拼接视图。

[pcodec 批与分页](pcodec-native.md) 新绑定 23 项：SourceAuto 批六项、C NativeAuto 批五项、两条分页路线各六项。
两种批路线分别保留实跑的格式、原值域和边界证据；C 编码路线的解码仍是 Rust Source。
两种分页冻结同一个 773 行测试窗口，不把分页和同一批输入重复计为独立语料。复算结合真实产物的页/元数据/sidecar
字节账、逆序 drain 的位摘要和实际拒绝状态区分逐页限额、累计限额；不能把分页增量解码计为在线编码。
IntMult 另绑定四项：实际发出 IntMult、精确 `u64` 基数、尺寸兜底回退到 Classic、输入域拒绝。
三份裸帧绑定新进程恢复与完整 drain 结果；独立复算直接从码流读取 chunk 类型、计数、mode 和整数基数。
这 27 项的开发绑定均不授正式阶段或方法资格。

[Sprintz-FIRE](sprintz-fire-native.md) 新绑定批处理和查询各五项。worker 部分延续 u16/4 lane，
另由同归档原生入口覆盖 u8/u16 的 lowdim/generic、通道和消息边界及脱离原值的恢复；用例绑定分别
保留 native/worker 身份。复算核对 9 份完整 SFB1、4 份 worker 封装、实际 Auto/Scalar 的逐 lane
COUNT/SUM/MAX 与拒绝结果。冻结输入按摘要去重，只计一次，不因同输入的 native/worker 或查询对照而重复计入。

[Titchy](titchy-native.md) 在原有三项访问绑定之外新增 19 项，覆盖批处理、packet 流、复用 reader 和无状态 range，
四组的 22 个必需检查均有开发用例。独立复算完整批帧及 TSTR/TSC1 后比对冻结输入摘要；将原生采集的实际
返回码、首次/逐包输出位置、独立恢复、尾部预算和访问语义分开核对。逻辑输入不重复计算同一交通窗口的子切片。

[ZFP](zfp-native.md) 新绑定四组 19 项必需检查。串行可逆批由独立 worker 新进程恢复；原生 field 请求/有效参数、
实际 stride、未覆盖 padding 和有损原值误差按封存输出复核。OpenMP 以同一输入和工作量对照 serial、OMP 1/2，
条件项保留正式的环境与工作负载判定；本开发探针的两个实际块工作线程不替代正式资格。
固定率 array 分开核对持久化数据、受影响块和只读的未修改块。共享气象原值不随不同策略重复计数。

[Huff0](huff0-native.md) 新绑定两组 11 项必需检查。FEC1 的 Huffman 分支固定 4X；1X/4X 对照
由两条 ETB1 模型配置实跑，保留各自的真实调用计数。五份批封装和四个共享模型 profile 的压缩产物由
新进程恢复，复算从封存材料核对长度、FEC1 原始 CRC、模型身份、拒绝和字节；ETB1 不继承 FEC1 的 CRC。

[SElf*](selfstar-native.md) 新绑定顺序批处理和逐值增量两组 9 项。f32/f64 精确 512 值、短尾和特殊值与
独立 worker 恢复一并验证；对 5 个跨块用例检查 reset、从头回放、缺前缀拒绝、finish 前后实际位数、
原生 reader 的终止符消费以及 1000 值和 workspace 上限。预检不把暂读值当作完成产物或首值时延。
