# M0 原生统一预检合同 v1

`m0_native_candidate_v1` 是**可执行的开发预检**，不是 M0 通过收据、M3 原生资格套件或 M5
矩阵运行。它用一份计划覆盖首批选定来源的所有 36 个已索引操作组及公共 ABI/恢复/应用回归。
同一探针可检查多个操作组；目前 24 个基础探针包含额外的[方法边界](first-batch-method-boundaries.md)、
[XZ worker 恢复](lzbench-native-operations.md)、[CORAD worker 恢复](corad-native.md)、[原生批计时对照](m0-measurement-policy.md)
和 [Gorilla 派生角色回归](gorilla-derived-roles.md)，
不改变 36 个原生操作组，也不改变 204/264 的服务矩阵分母。

## 生成与执行

使用已锁定的 Conda `tsbench` 和支持的 Linux x86_64 构建。用 CMake 完成 Release 默认目标
构建，保留 `BUILD_TESTING=ON`，选择 `TSBENCH_PLUGINS=@enabled`（默认，首批插件须全部启用），并显式传入
`-DTSBENCH_CORAD_DIAGNOSTIC=ON -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"`。裁剪构建缺少
必需探针，不能用于该套件。
从项目根目录提交：

```sh
"$CONDA_PREFIX/bin/python" -B bmk native-plan --build-dir build/m0-native --out results/native-plan.json
"$CONDA_PREFIX/bin/python" -B bmk native-run --build-dir build/m0-native --plan results/native-plan.json
"$CONDA_PREFIX/bin/python" -B bmk native-report results/native-preflight/<run_id>
```

也可通过 `tsbench.api.NativePlanRequest`、`plan_native`、`run_native`、`report_native` 调用；
`tools/probe_offline_m0.sh` 在迁移目录、隔离网络和空构建下执行同一路径。默认只构建 TSBench 集成目标；
独立发布包审计使用 `--release-builds-only`，见[构建对账](first-batch-unique-builds.md)。

可选的 `--huff0-portable-build <独立构建目录>` 在 `native-plan` 和 `native-run` 都要指定；它追加
一个依赖主 Huff0 探针的同次解码对照（总计 25 个探针，仍为 36 个操作组）。没有指定时，保留默认
24 个开发探针，在支持 BMI2 的环境中将这一条件报告为缺少同次对照。脚本也可用 `--with-huff0-portable`
同时准备两套构建并只提交一次预检。脚本和构建要求见
[Huff0 同次对照](huff0-native.md#在统一预检内复用实际产物的-portable-解码对照)。

- [候选套件](../../configs/suites/m0_native_candidate_v1/suite.json) 把 selection/操作组绑定到
  CMake 生成的已配置测试。每条操作组保留 `selection_id`、归档和目标、声明入口及原有
  域/必查项。发现清单或测试分母有重复、缺项或意外项就拒绝；不默默取交集执行。
- 派生角色诊断的产物允许位于该 slot 唯一的 UUID 子目录；缺目录、多目录或缺文件先拒绝再记录终态，不挑选一次通过的子执行。
  派生角色诊断不是新增原生操作组。预检计划内嵌[原生准入定义](native-admission-plan.md)，开发结果不能改写正式资格。
- 计划哈希绑定套件及 schema、首批范围草案与 v1/v3 语料身份（v3 继承 v2 分区）、项目配置/fixture/验证器、
  模型资产及部署清单、
  实际命令输入和二进制、`tsbench` Conda 元数据及 Python 可执行文件。运行前重解并核对完整
  计划；显式修改计划、配置、测试、已绑定二进制或现场环境必须重新冻结，不能只改旧哈希。
  `ctest --show-only=json-v1` 只发现已配置命令；执行器不从传入 JSON 接受未列明的命令、命令
  前缀或额外 CTest 运行属性。这里锁定实跑二进制，不等于完整的可复现发布构建证明。
- 计划绑定[原生功能定义计划](first-batch-native-requirements.md)的身份及方法边界的物化用例、原始域摘要、
  预期后端和输出；另绑定 [ALP](alp-native.md) 的实际分支、侧信息、逐后端恢复和舍入模式拒绝，
  [Gorilla](gorilla-tv-native.md) 的批帧、重启 snapshot、续跑、前向 seek 及独立进程观测的扫描和复制量，
  [Sprintz-FIRE](sprintz-fire-native.md) 的 SFB1/worker 帧、独立恢复和实际查询后端逐 lane 归约，
  [pcodec](pcodec-native.md) 的双批入口、分离封装、共享页元数据与反序独立恢复，以及 IntMult 码流模式和精确基数，
  [Zstd / XZ](lzbench-native-operations.md) 的帧旗标、独立恢复、原生 span 会话账、字典依赖、XZ 块与 filter 及其内存拒绝、匹配参数的 worker 对照，
  [Titchy](titchy-native.md) 的批封装、TSTR/TSC1 独立重解码、查询与逻辑读量，
  [ZFP](zfp-native.md) 的 field/array 恢复和误差、保留块、OpenMP 同工作量诊断，
  [Huff0](huff0-native.md) 的 FEC1 固定 4X、ETB1 1X/4X、留出分区、独立恢复、CRC、模型和字节账，
  [SElf*](selfstar-native.md) 的顺序块、位长度与 padding、完成前缀、终止符与跨块回放计费，
  [PBEPLA-RR](pbepla-native.md) 的独立前缀、精确逐层误差和 replay 逻辑计费，以及 [CORAD](corad-native.md)
  的部署身份、有序多列、共享原值、留存帧、训练校准的逐列经验界与实际判定，以及独立的 C/Source 训练和留出证据。
  `empirical_quality` 单列质量判定；探针成功代表证据完整，不代表质量通过。原生批对照另外冻结输入、计时边界、轮序、校准
  与八份参考帧的留存。执行与报告复算都核对这些证据；用例绑定与正式资格分别记录。
- 执行器内部串行启动各探针，在每个用例的新工作目录执行，输出路径改指本次运行目录；不会
  把构建目录里的旧诊断输出当成本轮结果。原生内置线程仍由各探针自己的配置与验证决定。
  有期限限制，跳过、超时、崩溃、取消、产物缺失或不合法分别记录；成功退出却没有声明的诊断
  产物不计通过。计时只作开发诊断，不把探针期限看作性能或内存上限。
- 一次提交产生一个外层 `run_id`、`plan.json`、统一 `observations.jsonl`、完成标记和派生报告。
  留存每项小型核验产物及 stderr/stdout，临时工作目录回收。应用回归内部也运行其既有 M1 候选
  smoke，并在该探针目录内保留它的证据；当前嵌入 `m1_lossless_candidate_v2` 的
  [进程墙钟诊断](m0-measurement-policy.md)。不需要用户分开提交，也不把候选结果升格为 M1 通过或性能样本。
- `native-report` 从封存的计划和账本复算并核对留存文件哈希，不重建、不访问语料、不重跑探针。
  受控取消可封存带取消终态的不全绿报告；未发布完成标记的中断不算完整，目前不实现检查点续跑。
  完成标记检测意外改动，不是签名。`native-run` 退出 1 表示有非通过终态，退出 2 表示输入拒绝。

## 不能由本计划证明的事项

`probe_status=passed` 只表示对应探针通过。一个探针遇到未安装的 ISA/设备、只覆盖一部分参数域或
暴露劣质恢复时，分项诊断仍保留原结论；不能从批次状态读成组内任意条件均通过。CORAD 的冻结模型推理
已接入 worker；C11 与 Source 训练仍仅走原生诊断，任何相关性阈值均不充当正式质量门槛。

正式 M0 仍需冻结完整语料和压缩特征覆盖、每条必需/有条件/不适用原生用例、质量与访问限额、
资源边界、计量计费、忠实性对照及正式样本留存与恢复规则，接入适用的执行者并验证拒绝与交付闭包。
M1–M6 及 204/264 的服务资格不因这一轮开发预检推进。
