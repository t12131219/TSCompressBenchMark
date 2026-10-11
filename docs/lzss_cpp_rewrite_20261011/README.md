# lzss-raw C++ 迁移验收（2026-10-11）

当前 `lzss-raw` 已重写为 C++17，编解码核心、严格位流验证和 C ABI 均执行 C++ 代码。该入口的 Rust 源码、FFI、Cargo/void 依赖、静态库和旧构建产物已删除。验收结果为 **PASS**，无需 Rust 工具链即可重新构建和运行。

迁移范围是已经登记的 alexkazik/lzss 0.9.1 `Lzss<10, 4, 0x20, 1024, 2048>` 配置，对应原作 commit `512b9163d8a936003c925e24f7f682eeaeda8307`。此结论适用于 `lzss-raw` 固定 EI10/EJ4/C32 入口；原库其他参数、动态配置、原地编码和全部公共 API 未纳入迁移范围。原作 MIT 版权保留在 [LICENSE](../../adapters/lzss_raw/LICENSE)。

## 实现与兼容性

[C++ 核心](../../adapters/lzss_raw/native/lzss_raw_codec.cc) 使用固定栈缓冲区，编解码函数为 `noexcept`，无动态分配。实现保持 1024 字节窗口、17 字节前瞻、初始空格字典、候选逆序扫描和严格更长匹配更新；同长度匹配保留最近候选。完整前瞻匹配允许提前结束扫描，位流结果保持一致。滑窗保留历史与前瞻，解码逐字节更新字典，正确处理重叠引用和环绕。

位流继续使用 MSB-first literal `1+8` 位或 reference `1+10+4` 位，末尾为最多七位零 padding。C ABI、容器 magic/schema、描述符和 Finalize 零输出协议保留。压缩容量上界为 `n + ceil(n/8)`；严格解码在写输出前拒绝截断、超长解码、额外字节和非零 padding。原生计时直接围住 C++ 编解码（包含字典初始化），容量及位流预检、Python FFI 和容器处理在计时区间之外。

## 验证结果

| 检查 | 结果 | 证据 |
|---|---|---|
| 原作实时交叉验证 | 282 个用例全部通过；C++ 压缩流逐字节等于原流，双方交叉解码一致 | [live_wire_parity.json](live_wire_parity.json) |
| 迁移前真实 Benchmark 产物 | 10/10 正式 repetition 的旧容器由当前 C++ 解码，逻辑输入 SHA 一致；C++ 重新编码逐字节等于旧 raw frame | [legacy_benchmark_artifacts.json](legacy_benchmark_artifacts.json) |
| Release 原生资格 | 39 个 ABI 用例、16,442 个合法手工流、587 个畸形流/危险描述符拒绝、282 个原作位流回放全部通过 | [native_qualification.json](native_qualification.json) |
| ASan/UBSan 原生资格 | 相同用例全部通过，覆盖 C++ 核心、严格验证、ABI 与原生测试程序 | [原生资格日志](native_qualification_log.txt) |
| 无 Rust 工具链构建 | PATH 仅有 `c++`、`as`、`ld`，无法发现 `rustc`/Cargo；全新库哈希与登记 release 相同，全部 release 原生用例通过 | [no_rust_build.json](no_rust_build.json)、[日志](no_rust_build_log.txt) |
| Python 与集成测试 | 114 项通过；最终闭包检查另通过 1 项 | [python_validation.json](python_validation.json) |
| 新 Benchmark 五层资格 | `national_illness` VALUE 任务 PASS；持久化流与解码上下文在独立 worker 恢复，无原输入和编码会话；resume 执行零任务且 raw 不变 | [benchmark_qualification.json](benchmark_qualification.json) |
| Rust 清理及动态依赖 | 活动 adapter/build 无 Rust 文件或产物；共享库仅依赖标准 C/C++ runtime | [rust_removal.json](rust_removal.json)、[符号](release_symbols.txt)、[动态依赖](release_dynamic_dependencies.txt) |

[黄金向量](../../adapters/lzss_raw/tests/fixtures/reference_vectors.json) 在删除原实现前，由原 Rust release 库实际编码生成，保存原库和原算法源码哈希；期望流没有使用 C++ 编码器生成。数据覆盖空输入、短尾、位边界、窗口和滑动边界、多次滑窗、重复/随机/匹配平局模式，最长输入为 131,073 字节。正常资格回放只需要这些冻结流，不需要原作 runtime。迁移使用的临时原 Rust 对照库也已删除。

[独立解码合同测试](../../adapters/lzss_raw/tests/test_decoder_contract.cc) 手工构造全部 1024 个 offset 与 16 个 length 组合，并覆盖初始字典、distinct 字典、重叠/环绕、bit alignment、截断、拼接、padding、长度不符及指针/容量溢出。拒绝用例检查 destination 与 `used_bytes` 均不改变。

ASan/UBSan 已启用并通过。LSan 受本机 sandbox 的 ptrace 限制，资格工具关闭 leak detection；系统 runtime 未插桩。这里不声称通过 LSan。黄金向量与边界用例是已运行的验证证据，不能泛化为全部输入和平台的形式化证明。

旧产物检查读取 `runset-20260918T074940Z-f8855e7299f1` 的实际 `.bin` 和原始 record，不依赖旧 Rust 库。该 RunSet 的 45 个文件在检查前后树哈希不变。十个 repetition 属于同一个输入及同一种确定性流，报告分别记录，未将其计为十种独立数据。检查仅证明产物兼容，保留原正式测量身份。

## 当前实现身份

源码闭包包括两个编译单元、核心头文件及两个必要的 ABI/timing 头文件，共五个文件。登记卡和 build record 同时保存逐文件 SHA；总哈希按排序后的仓库相对路径 UTF-8、NUL、文件内容依次计算。

| 项目 | 当前值 |
|---|---|
| SourceArtifactID | `v2:source-artifact:sha256:9579e054e8623059d897c666c92d1703fc092e51b91a33d7de988fb6c2695b92` |
| AlgorithmID | `v2:algorithm:sha256:1bdb0ce868a939b4ca16dfdac9204c32da9950cd050e1b639ab5685ea2dd1913` |
| SourceOnboardingID | `v2:source-onboarding:sha256:16ac66eb1a368e8828afcd03eb5ee99e7671bdc92c712bf6b580f9e7431ca4c2` |
| C++ 源码闭包 SHA256 | `e1b2bf0606a8ab91a5970e5bf62c43519b158e45b00b6c4d844b90a1d1cd49b5` |
| Release 库 SHA256 | `9b6034d6a5f6eb1589e23d35812476cbbba5e628a403eebfee75e97a757c0329` |
| ASan/UBSan 库 SHA256 | `134e60e40f738ba4f52dec374551e77ad1980374db9a1e88392f20f1aceed924` |

[来源卡](../../registry/sources/lzss-alexkazik.artifact.json)、[codec manifest](../../registry/codecs/lzss-raw.json) 和 [onboarding 卡](../../registry/onboarding/lzss-raw.json) 已使用当前 C++ 身份。源码类别明确为翻译实现，原作 commit 用于来源归属。当前工作列表引用也已更新。完整构建记录和实际编译命令分别见 [release](release_build-record.json)、[release 命令](release_compile-command.json)、[sanitizer](sanitizer_build-record.json)、[sanitizer 命令](sanitizer_compile-command.json)。

## 删除范围与历史证据

删除了 `adapters/lzss_raw/native/ffi.rs`、整个 `adapters/lzss_raw/vendor`（lzss 与 void），以及 release/sanitizer 下的 `rust-build`、`.rlib`、Rust 静态库和 `upstream-*` 测试程序。[构建工具](../../tools/build_codec.py)、[资格工具](../../tools/qualify_lzss.py) 和 Python adapter 均已移除活动 Rust 路径与命名。

外部 `Compression_Source_Code/Source_Code` 是原作参考集合，不是当前编译依赖，未修改。旧来源卡、manifest 与 onboarding 卡保存为本目录的 `previous_*.json`；历史报告和已签发的 Benchmark 记录保留原内容与身份。比较配置和 candidate ledger 的历史快照也保持原签名，不能用更新哈希的方式将旧 Rust 测量解释为 C++ 测量。旧 V3.2 冻结验收不构成当前 C++ 的正式性能验收。

新资格 RunSet 为 `lzss-cpp-qualification-20261011`，完整本地运行位于 `build/lzss_cpp_rewrite_20261011_benchmark/lzss-cpp-qualification-20261011`；关键任务、预检、产物、计量与报告已另存于 [benchmark_qualification](benchmark_qualification)。该 RunSet 的 `eligibility=false`，没有正式性能排名。本次未重测或重签全部 V3.2 比较 lane。

## 复现

在仓库根目录、项目 Python 3.14 环境执行：

```bash
python tools/build_codec.py lzss-raw --profile all
python tools/qualify_lzss.py --profile all
python tools/verify_lzss_cpp.py \
  --library build/adapters/lzss_raw/release/libtscb_lzss_raw.so \
  --output build/lzss-cpp-bitstream-replay.json
python tools/verify_lzss_cpp_artifacts.py \
  --library build/adapters/lzss_raw/release/libtscb_lzss_raw.so \
  --run-set runs/runset-20260918T074940Z-f8855e7299f1 \
  --output build/lzss-cpp-legacy-artifact-compatibility.json
python -m pytest tests/adapters/test_lzss_raw.py tests/adapters/test_native_timing.py \
  tests/contracts/test_codec_registry.py tests/unit/test_planning.py \
  tests/unit/test_native_integration_plan.py tests/integration/test_lzss_qualification.py
```

创建新的 Benchmark 资格身份：

```bash
python -m tscompbench --project-root . run validate \
  configs/experiments/lzss-raw-qualification.toml \
  --output-root build/lzss-cpp-local --run-set-id lzss-cpp-local-qualification
python -m tscompbench --project-root . run report \
  configs/experiments/lzss-raw-qualification.toml \
  --output-root build/lzss-cpp-local --run-set-id lzss-cpp-local-qualification --resume
```
