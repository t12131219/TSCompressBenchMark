# 原生实际运行库与 Python 执行身份补充审查（2026-10-11）

本记录补充原 `native_contract_review.md`。修正真实加载选择和 adapter 共享代码的执行身份；不把构建时 `ldd` 文件哈希当作当前 Python 进程的实际运行库，不签发完整 N1 或源码 FULL_PARITY。

## 执行身份修正

`factory.adapter_artifacts()` 从所选 adapter 的 Python 文件递归读取 adapter-local import。ALP/ALP-RD、NeaTS/LeaTS、Sprintz 的 `lzsse8_raw.py`、FSE/Huff0 的 `deflate_zlib.py`、LZSS 的多级公共模块以及 SIMD 的 `native_buffers.py` 都纳入支持工件；ALP 的条件 `source_reject_fallback.py` 在 planner 决定使用恢复路线前纳入。factory/build_evidence/runtime_evidence 基础设施分别直接纳入，不把 factory 的全部算法分发 import 当作每个算法的依赖。

15 个隔离变异案例经真实 `resolve_execution()` 验证支持路径集合保持、`artifact_sha256` 和 `execution_path_hash` 都变化；另有 LZSS 多级与 SIMD 辅助模块递归控制。此为 adapter-local 静态 import 闭包，不声称任意动态 import 或 NumPy/系统 Python 包的全部源码闭包。

## 真实运行库门禁

新增 `runtime_evidence.py` 与 `capture_runtime_profiles.py`，显式区分：

1. 原 build-record 声明的构建/测试链接运行库；completed 的声明可以是库与 CTest executable 的并集。
2. 在当前相同环境下运行 `ldd` 选择的该生产库精确集合。
3. 实际当前进程 `/proc/self/maps` 中按 ELF `DT_SONAME` 匹配的递归 `DT_NEEDED` 集合，包括已由 NumPy 加载的 Conda `libstdc++`/`libgcc_s` 及其附加 `libdl` 依赖。

新 profile 把后二者分别按绝对路径、SHA256 和 SONAME 固定，绑定原工件和原 build-record 的 SHA，固定 resolver 程序和 capture driver。实际支持路径返回 profile 与选中的运行库，因此影响 ExecArtifactID。非空 `LD_PRELOAD`、`LD_AUDIT`、全局 `/etc/ld.so.preload`、未登记 resolver 程序/文件选择、已加载的同 SONAME 不同文件与重复 SONAME 映射均拒绝。resolver 程序先于执行被校验。

factory 在其普通 build gate 后显式受控 `CDLL`，然后重新校验实际映射并保留 handle，使延迟到 `create_session()` 才绑定符号的 adapter 同样经过实际加载验证。profile 的实际加载成功仅是 runtime 范围证据，不能替代 ABI 测试、数据域对照、source parity 或性能资格。

## 已执行验证

- `runtime_profiles_v2/registration.json`：36 个现有非 oracle 对象，包含 33 个 active 与 3 个保留回归对象；每个在独立生产 Python 子进程实际 capture，然后另一个独立进程 pre/post load 复放，共 72 个观测 PASS。SourceArtifactID 保持；仅新增 codec `adapter.runtime_profile`，同步 LZ77 alias 的 canonical AlgorithmID。before/candidate 与登记回执保存；没有覆盖旧 build-record，也没有新增算法或改变 activity。
- `tests/unit/test_adapter_build_evidence.py`、`test_adapter_python_identity_closure.py`、`test_runtime_resolution_evidence.py` 一次实际回归：67 PASS。真实非 codec ELF 包括原 LD_LIBRARY_PATH 替换、不同文件名同 SONAME 的提前加载、load 后同 SONAME 冲突、preload/audit、未登记 resolver 和 lazy factory 路线。所改 Python Ruff PASS。
- `runtime_resolution_replay_v1.json`：原三 toy DSO 反例原目录复放，原合法依赖 value=11 PASS，alternative 选择被拒。原 `result.json`、record、command、库、driver 与 child 文件 SHA 全部保持。
- `python_closure_replay_v1/python_closure_report.json`：原隔离 Python 反例按当前 factory 复放，33 活跃入口的 adapter-local import 缺失集合为空，门禁待处理错误为空；原 13 个变异案例的真实 artifact/execution identity 均改变。变异只作用于新审计目录的非执行 fixture。
- `current_factory_runtime_verification_v2.json`：最终 SDK r3 登记后的 40 个当前入口全部 factory PASS；36 非 oracle 完成实际生产 pre/post load 门禁与各自注册 ABI identity 核验，4 oracle 完成 factory 核验。这里仅检查 ABI version/algorithm，不称完整 finite NativeAPI suite。该清单的 `combined_artifact_sha256` 是本审计自有 role 标签的支持文件清单摘要，不是 planning 的 ExecArtifactID。
- `general_native_qualification_v4/qualification.json`：62 个现有 release/sanitizer build-record 声明依赖 PASS；60 个真实有限 ABI/kernel/allocation native test PASS。各独立 executable 保存 run 前后选择相同的 `ldd` runtime path/SHA/SONAME，共 387 个条目。该报告明确 `BUILD_RECORD_AUDIT_NOT_PRODUCTION_CDLL_PROFILE`、`NOT_QUALIFIED_BY_THIS_NATIVE_EXECUTABLE_REPORT`；native executable 的 selected-runtime 检查不是实际 proc-map 追踪。

`runtime_profiles_v1` 是单 ALP pilot；`general_native_qualification_v3` 是格式检查后中断的试验，未签发 PASS 报告。二者保留且未用于当前登记。`current_factory_runtime_verification_v1.json` 是审计驱动错误地向 completed 四库读取普通 `tscb_get_abi_version` 的失败记录；v2 使用 completed 实际 `rw_version/rw_algorithm` 后全部通过，没有为修复审计假设改动任何生产库。

SIMD 的 fresh SDK r3 单独完成 504 项实际测试与 audit/refresh，沿用原 native artifact/build-record 并保留本 runtime profile；其 Python pins 更新后的最终 AlgorithmID 以 v2 factory 清单为准。runtime 初次登记回执中较早的 SIMD AlgorithmID 保留为登记时事实。

## 适用边界

实际门禁覆盖 factory 受控加载前后的 artifact 递归 ELF `DT_NEEDED` 选择与 proc 映射；不追踪任意后续 `dlopen`、CDLL constructor 的执行行为、所有系统包代码或静态 startup/runtime archive。对缺失、重复 SONAME 和已删除的进程文件映射采取显式拒绝。文件并发就地修改与任意恶意进程内存修改不在此证据范围；完整 N1 仍未授予。

ASan/UBSan 资格保留独立 native executable 的环境，未因 Python profile 登记而反向授予 Conda runtime 的源 parity；系统运行库未插桩，LeakSanitizer 仍受宿主限制关闭。历史 run 保留旧 AlgorithmID/ExecArtifactID。新 profile 与共享 Python 漂移会使当前门禁失效并需要重新资格，不能改旧证据 SHA 使其通过。
