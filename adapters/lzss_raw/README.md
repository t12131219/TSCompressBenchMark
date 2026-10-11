# lzss-raw C++ 实现

`lzss-raw` 是 alexkazik/lzss 0.9.1 固定 `Lzss<10, 4, 0x20, 1024, 2048>` 配置的 C++17 重写。原作来源为 commit `512b9163d8a936003c925e24f7f682eeaeda8307`，许可证见 [LICENSE](LICENSE)。本次迁移仅覆盖已登记的 EI10/EJ4/C32 配置；其他参数和原作的全部公共 API 不在接入范围内。

核心使用 1024 字节窗口、17 字节前瞻和空格初始填充。编码按原作逆序扫描候选，仅在严格更长时更新匹配，平局保留最近位置；位流为 MSB-first，末尾补零。解码逐字节更新环形字典，支持重叠引用。原始流没有 framing、校验和或长度字段；框架容器保存恢复所需的 dtype、shape、名称和精确解码长度。

`native/lzss_raw_codec.h/.cc` 实现零动态分配、`noexcept` 的编解码 API；`native/tscb_lzss_raw.cc` 提供 C ABI v1、生命周期、容量与别名检查。压缩输出必须预留 `n + ceil(n / 8)` 字节；解压在写输出前检查精确 token 覆盖、完整消费和最多七位零 padding。Finalize 输出零字节。原生计时只围住 C++ 编解码 API，容量/格式预检与框架容器处理位于该区间之外。

在仓库根目录、已安装项目 Python 依赖的环境执行：

```bash
python tools/build_codec.py lzss-raw --profile release
python tools/build_codec.py lzss-raw --profile sanitizer
python tools/qualify_lzss.py --profile all
python -m pytest tests/adapters/test_lzss_raw.py tests/integration/test_lzss_qualification.py
```

构建使用 `CXX` 指定的 C++17 编译器，默认 `c++`；sanitizer profile 启用 ASan/UBSan。资格工具执行原生 ABI 用例、独立解码合同用例和 [282 个原作 bitstream fixtures](tests/fixtures/reference_vectors.json) 回放。Fixtures 在删除旧实现前由原作库产生，当前回放无需原作 runtime；与迁移前原作库的实时双向交叉验证记录见[迁移报告](../../docs/lzss_cpp_rewrite_20261011/README.md)。

本入口的当前源码、构建、执行与资格回放均无 Rust、Cargo、`rustc`、Rust FFI、Rust 静态库或 `void` crate 依赖。原作身份和历史报告中的 Rust 字样保留为来源证据；外部 `Compression_Source_Code/Source_Code` 参考集合不属于本入口的构建或运行依赖。迁移前冻结的 Benchmark 记录属于旧工件身份，新实验需使用当前 C++ 工件重新建立运行身份。
