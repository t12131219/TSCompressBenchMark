# Chimp / FPC / PMC-MR / Swing 独立 C++ 重写

从同一仓库 panagiotisl/chimp 的 Java 核心重写，冻结提交320d397157c7e0696b3c64dc1711fc17a3add3da。覆盖 Chimp、Chimp32、Chimp128/ChimpN、Chimp128-no-index、ChimpN32、FPC、PMC-MR、Swing Filter、Swing Filter Disjoint、Swing Filter Disjoint Quantized，另保留 quantized.filter2 公共路径。方法号与别名见 ALIASES.json 和 include/chimp_family.hpp。

```sh
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release -j2
ctest --test-dir build/release --output-on-failure
cmake --install build/release --prefix "$PWD/dist/local"
python tools/verify.py --cli build/release/chimp_cli --out validation/new-differential --corpus /path/to/TSBench_Corpus --shared /path/to/Dataset_Verify
```

运行差分需系统 Java21/javac 和 Python3；独立 C++ 库/CLI 仅需 C++17 与 CMake，不依赖 Java、Maven、Benchmark 或共享数据目录。已冻结的 canonical inputs、source/cpp raw outputs、frames 及 decoded outputs 均保存在 validation/qualified-v2/blobs，以 SHA256 索引、gzip存储；新环境可使用 tools/replay.py 重放，不需要外部真实数据。

CLI：`chimp_cli MODE METHOD N EPS COUNT INPUT OUTPUT`。MODE1原始编码、2原始解码、3自包含 frame 编码、4冷解码、5有损 filter+解码、6严格 ABS epsilon frame 编码。METHOD1..11。无损输入/输出是 uint64 LE 原始位模式列表（32位变体的上32位必须零）；有损输入/输出是 `(int64 timestamp LE, float32 value LE)`。源有损输出原本是对象列表，MODE1使用显式52字节 segment 序列化。完整 wire 格式见 FRAME_FORMAT.md。server 是批量测试协议入口，额外提供 FPC 跨调用状态测试模式。

C++ owning-vector API：ChimpEncoder.add/finalize/reset，ChimpDecoder.next/reset；Fpc.encode/decode/reset/finalize；filter、SegmentDecoder.next/reset；encode_frame/decode_frame。返回容器拥有内存，参数 const 不修改，无异常状态混用、无隐藏可变全局对象。调用方自行同步同一实例；独立实例可并发。查询 meaningful_bits/bytes/workspace_bytes 时，引用随下一次变更失效。无 caller-provided 输出 buffer，bound-1/canary 容量用例不适用于该 owning API；raw_bound 为安全分配上界，字节访问不允许 overread。全部限制与失败原子性见 contract.md。

Chimp 的 canonical positive quiet NaN 是 EOF，编码显式拒绝该位型；其他位型按原源码保留。FPC 会将 NaN 规范化，与 Java Double.doubleToLongBits 相同，默认不能声称任意 NaN payload 无损；可显式拒绝 payload NaN。所有有损值为 float32，中间运算按源码保留 float/double 混合精度。量化版使用样本序号，忽略输入 timestamp；其单点源缺陷产生非有限结果。源码兼容模式保留分段行为，严格模式在实际重建值超限或非有限时拒绝；没有用单纯 differential PASS 代替误差合同。

研究范围豁免由本会话用户书面批准，记录于 validation/WAIVER.json。代码许可现状、原始版权和哈希均保留，本地验证不宣称新获再分发许可。本任务不修改 Benchmark adapter、registry 或实验结果；不声明 FORMAL 排名，也不宣称无限资源输入域 FULL_PARITY。结论与边界见 validation/porting_report.md。
