# 现代 Stream VByte 来源准入卡

本卡对应计划 7.2、7.6、8.3、16.1–16.3。源码调查发生于适配前；
此文件补录调查结果，构建与资格证据须实际运行后更新，不能凭注册签署通过。

- 来源：`https://github.com/fast-pack/streamvbyte`，commit
  `7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce`，2026-10-07 复查 clean，无 submodule。
- 先审查本地 lzbench/FastPFOR Benchmark：它们携带旧 Stream VByte，
  count 在原 API 码流内，scalar encode、SSE4.1 decode。它们不能代表清单指定的
  fast-pack 现代来源，因此保留旧注册并建立独立现代身份。
- 真实实现：`src/streamvbyte_encode.c`、`src/streamvbyte_decode.c`，以及它们
  include 的 x64/scalar 实现与 shuffle tables；公共 API `include/streamvbyte.h`。
  上游 Benchmark 为 `tests/perf.c`，自测为 `tests/unit.c`。
- 冻结闭包：`SOURCE_LOCK.json` 按文件 SHA-256 固定所需 30 个原始文件及安全补丁；
  vendor 文件原样保存，补丁只在 out-of-tree 构建目录 replay，原 `_repos` 只读。
- 许可：主 Apache-2.0，ISA detection header 包含 BSD-3-Clause；
  原许可证、作者及所有文件内 notices 保留。无额外第三方链接依赖。
- 分类：原 uint32 1234 API 为 P0；checked int64 Delta/ZigZag/limb32 + API 为
  显式 P2，属于项目组合，不把它冒充上游 modular uint32 delta API。
  0124、delta32、ARM、scalar fallback 尚未注册。
- 原 API 输入：不可变 uint32 vector、count 由调用者保存，返回实际 used/consumed；
  无 source error/capacity API、无上下文 finalize。1234 为每值 1/2/3/4 字节。
- ISA：构建固定 `-msse4.1`，create 检查 CPU；encode/decode 均走 SSE4.1，
  完整向量以外的标量尾部是声明路径。禁止隐藏 scalar fallback。
- 内存：原 decode 允许 16 字节 overread，原 encode 也要求 padded capacity。
  适配使用内部 padding 与 aligned staging，外部 overread 为 0；
  unaligned control-store 安全修补不改变码流，必须验证原 API 等价。
- 注册输入：P0 `<u4>` UTS；P2 `<i8>` 时间戳，保序、重复、负差值、OOO 与 epoch
  原样保留。N 上限 16,777,216；P2 delta/recovery checked int64 溢出原子拒绝。
- 生命周期：一 update、必需零字节 finalize、reset mode 0、fresh decoder；
  output bound 包括独立 count、descriptor 和所有 framing，capacity 不当作压缩长度。
- 码流：shim 写独立 count，原 API bytes 保持原样。descriptor、count、seed、
  control/data 与包装每个实际字节仅计费一次；内部 padding 不进入 FinalBits。
- 上游原 release/debug 自测通过，原 sanitizer 在 ZigZag delta 辅助模块报告
  signed overflow，失败保存在 `build/source-audits/streamvbyte-modern-native-tests-before-upstream-safety-patch.json`。
  第二个独立补丁采用 unsigned modular32 算术及 memcpy 恢复位模式，并修复
  delta32 SIMD 控制字的未对齐写入。此模块只用于完整上游自测闭包，不扩大注册范围。
- 安全资格与三档构建：仍待补丁后本轮实际运行；历史旧来源证据不能代替现代来源资格。
- 五层验收、正式重复、自检：待本轮实际运行；未完成前不标已接入。

来源、能力、计费或 ISA 变更必须刷新来源/构建/运行证据；系统压力保留为独立异常。
