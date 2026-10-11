# 当前原生移植契约修正与验证（2026-10-11）

当前包装层存在可复现的输出描述符及生命周期缺陷，已修正并在新的 release、ASan/UBSan 工件上验证。这里记录有限原生资格；不据此签发源码/论文 `FULL_PARITY`，也不改变活跃算法范围。

本次子审查完整阅读移植标准 v3.0 的 L1–2100 与 L5501–5754，尤其 §2.2 的合法比特流兼容、§114 的构建输入闭包和 API 失败/生命周期，以及 §115 的证据失效规则。其余条款和全文审查由主任务及其他审查记录覆盖。

## 修正与结果

| 问题 | 修正 | 实际验证 |
|---|---|---|
| LZ4/Zstd 原生 decode 接受 `used_bytes > capacity_bytes` 并写输出 | 所有输出入口先检查 dtype、rank、used/capacity、size_t、指针范围；非法描述符失败前保持缓冲区与 used 字段 | 旧库对 capacity=128、used=129 返回成功并改为 used=128；新库返回 INVALID_ARGUMENT，used=129 保持 |
| 增量 decode 到 EOF 后继续使用同一解码状态 | EOF 后 update 返回 CODEC_ERROR，显式 reset 后允许再次解码 | release 与 ASan/UBSan，EOF 前后、finish-before-data、reset 后恢复均通过 |
| 普通构建缺少实际头文件/对象/运行依赖闭包 | 每 TU 真正使用 `-c -MD -MF` 编译再链接；保存命令、.d、对象、TU/头文件、所选工具链和 ldd 依赖 | 62 个新 build-record 的已声明依赖通过；共 17,024 个按记录去重的路径检查 |
| 大部分原生工件加载没有统一的缺失/漂移拒绝 | factory 使用只读 build_evidence 门禁，核现有真实 schema、库/命令/源码/补丁/模型/Python 支持依赖 | 漂移、缺失、路径穿越、符号链接逃逸、模型、旧补丁字段与多 TU/GCC/Clang 反例均通过 |
| 普通 adapter 测试固定读取旧 `build/adapters` 并隐式重建 | 11 份测试读取当前 manifest 并经 factory 创建；缺工件直接失败 | 新工件的 Python 边界/恢复/账户/字节一致性测试通过，见下方分次回归事实 |
| LZSSE smoke 使用了 Snappy level=1 配置 | 使用已注册 LZSSE level=12，修正输出名称 | LZSSE2/8 新库两 profile 的真实 ABI smoke 通过 |

LZ4/Zstd vendor 未改动。包装层旧源码保存在 `native_api_baselines`，两个真正 unified patch 存在各 adapter 的 `patches/0001-output-descriptor-eof-state.patch`；报告记录旧/新/patch SHA，并在独立目录完成 `git apply --check`、实际 apply 和最终字节相等验证。

## 新证据

- [构建状态：31 个既有/保留工件 × 两 profile](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/general_native_builds_v3/build_status.json)
- [62 份构建闭包和 60 个真实 ABI/kernel/分配失败测试](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/general_native_qualification_v2/qualification.json)
- [LZ4/Zstd 包装层测试、补丁重放及有限字节兼容](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/frame_binding_qualification_v3/qualification.json)：8 个真实 native executable；590 个合法输入编码字节相等案例、1,180 次双向 cross decode。覆盖 0/1/2、帧边界、固定 seed 随机、常量和三份实际数据文件的 byte sample。
- [Sprintz lowdim 源实现/补丁有限差分](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/sprintz_lowdim_source_parity.log)：重新编译原始/补丁 encoder，128 条输出相等；bounded 与 allocation failure 在 release/ASan/UBSan 通过。这不覆盖完整 Sprintz 上游输入域。
- [当前注册刷新](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/native_registration_refresh.json)：SourceArtifactID 保持；更新包装层 version、新库路径、source build 和 onboarding。LZ77 alias 绑定新的 canonical AlgorithmID。范围外三个保留对象仅作既有工件回归，没有加入活跃集合。
- [证据及驱动 SHA 索引](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/native_evidence_index.json)

最终普通构建路径为 `build/port-standard-v30-20261011/native-builds-v3`。旧 `build/adapters`、第一轮和第二轮目录、失败测试 log 均保留。显式新 output-root 会拒绝覆盖已有 profile 目录；构建驱动中途漂移也会拒绝签发新记录。

## 回归事实与边界

第一次所负责 Python 回归是 [390 PASS、2 FAIL](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/current_registered_native_adapter_tests.log)。两项失败来自 onboarding 测试把历史和当前 build 总数固定为 2；已改成分别验证当前 release/sanitizer 的记录 SHA、artifact/command SHA，以及历史记录保留。[两项修正后复测均 PASS](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_port_standard_v30/updated_onboarding_native_adapter_tests.log)。这里没有声称同一次 392 PASS。所负责源码 Ruff 与 `git diff --check` 通过。

当前 N1 证据核验真实 compiler `.d` 中的 TU/header、对象、构建驱动、compiler driver/frontend、assembler/linker 选定文件、动态运行库和旧 schema 已声明补丁等文件。GCC/Clang 的程序选择记录来自 compiler driver discovery，不是 exec 追踪；并未完整 pin 所有隐式静态 startup/runtime 归档。因此完整 N1 仍需补充，不能因为所声明 SHA 全通过就称 N0–N5 全部完成。

ASan/UBSan 覆盖本次构建的包装层/codec/object；系统运行库未插桩，LeakSanitizer 受主机 ptrace 限制关闭。仅 ABI version 检查的条目在报告中保留空 `native_tests`，不构成完整 NativeAPI suite。源码、论文、Benchmark 和 SDK 资格依然是独立证据；历史运行结果不自动适用于新的 AlgorithmID/ExecArtifactID。
