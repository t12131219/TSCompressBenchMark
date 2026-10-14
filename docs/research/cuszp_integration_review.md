# cuSZp 3.0.0 GPU extension source review

本次新增 `cuszp-fixed-1d`，独立于保留的 36 个 CPU key。算法代码来自官方
[cuSZp 仓库](https://github.com/szcompressor/cuSZp/tree/f581dcf329c907c320f4743a9c6e7ee2fb9c5494)，
固定提交为 `f581dcf329c907c320f4743a9c6e7ee2fb9c5494`，CMake 项目版本为 3.0.0，
许可证为 BSD-3-Clause。逐文件来源、大小与 SHA-256 见
[源码锁](../../adapters/cuszp/SOURCE_LOCK.json)。vendor 中的两份 1D f32/f64 kernel
翻译单元和其头文件完整保留上游内容；自编 host wrapper 负责检查、生命周期和
边界计费，不重写压缩算法，也不提供 CPU fallback。

官方 README 引用 SC'23 的 cuSZp、SC'24 的 cuSZp2、SC'25 的 cuSZp3 和 ICS'25
的 hierarchical-delta 工作；这些引用提供算法背景，不能直接作为当前 binary 的
性能或正确性证据。本次行为判断主要依据固定提交中实际编译与调用的 kernel
源码。SC'25 的多维模式及 plain/outlier modes 未通过该扩展暴露。

选择 1D FIXED 的原因是，源码直接按数值量化后的绝对值生成每个 32 元素块的
位宽，不依赖跨值 predictor 或外部模型状态。`quantization()` 在 GPU 上计算
`value*(0.5/bound)` 并转 signed int，因此 host 源数据预检保守限制其量级至
`2**28`，避免输入触发 signed-int 转换溢出。FIXED 的 sign 字段另占每个非零块
4 字节；payload 长度为 padded rate table 加每个非零块的 `4+4*width`。
这里的 rate table 对齐到 32768 元素 tile，一元素对象也必须保留 1024 字节。
上游小样例按 raw input 大小分配输出的习惯不能作为本适配器的安全容量公式。
真实 GPU 资格检查又确认单 tile 的最终 global offset 未由上游 `warp>0` 分支
写入，host wrapper 对该情况读取 `locOffset[1]`，并保留原失败运行的 checkpoint
和独立重现记录；这仍没有改动上游 kernel 或 wire 格式。

FIXED decoder 对 width=0 的块不写输出，适配器必须在真正 decode kernel 前
将输出清零，否则全零或尾部零块可能读取到未初始化显存。每个 persisted payload
的所有 rate bytes、padding-only rate 和精确长度在 H2D 前检查；encode 后也执行
同类检查。opaque owner 保存 input/payload/decoded kind，typed count、dtype、bound
或 owner kind 不匹配时，在 kernel 启动前拒绝。以上调整位于 host wrapper，
没有改动上游 kernel。

float32 使用向下取到可表示 f32 的实际 ABS bound；float64 直接将 double bound
传递给 f64 kernel，避免从通用上游入口的 float 参数丢失精度。特殊值不使用
隐藏的 raw escape：negative zero、subnormal、NaN、infinity 全部拒绝。有限正常值
和整数安全限制仍不能构成对浮点误差界的全域证明，Benchmark 每次完整恢复后必须
独立验证 requested ABS bound，失败数据不能进入合格性能统计。

独立恢复只读取 CSP1 持久化对象，含 dtype、N、actual bound、native payload 和
metadata/payload SHA-256；不能借用 encoder session 或隐式全局字典。host-to-host
和 device-to-device 是不同边界。encode CUDA event 包含 control memset、host
路径的 H2D、kernel 和 size/rate D2H；decode event 包含 control/output memset 和
kernel。这些是实际 stream 区间，不能标为纯 kernel 时间。allocation、完整
materialization、wire packing、close 与其它外部工作进入对应 wall/setup/postprocess
字段；详细契约见 [contract](../../adapters/cuszp/contract.md)。

构建证据同时冻结 adapter/vendor/bridge/capability card、nvcc 与 host 编译工具、
CUDA libdevice/static runtime、GCC CRT 和实际 linker trace 的仍存留依赖、编译
头文件及 dynamic runtime。构建本身不执行 GPU，也不能代替资格检查。真正 runtime
加载的 driver 和其它共享库须由资格/执行进程的 `/proc/self/maps` 再记录。
[资格工具](../../benchmark/tools/qualify_cuszp.py) 检查 host/device wire 一致、输入不变、
独立 decoder 误差、fresh-process 恢复、真实 native 预启动失败及 checked owner/
stream/event 释放平衡；它不宣称正式吞吐、OOM 恢复或失败 CUDA context 恢复。
