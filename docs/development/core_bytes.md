# 字节 codec 的直接原生入口

本组覆盖 Brotli、BZip2、zlib DEFLATE、XZ、FSE、HUFF0、EI10/EJ4/C32 LZSS、Dipperstein LZSS、LZSSE2 和 LZSSE8。原对象入口保留。直接入口不调用 `tscb_create`、`tscb_compress`、旧 C1 finalize、ABI 输入描述帧或 Python 循环，也不使用框架全局锁。

输入是任务 dtype、shape、C／F 物理布局对应的完整有效字节；不会为压缩率分母添加 padding 或描述头。字节算法对整个物理缓冲区编码，不把矩阵拆成重复时间戳的列。decoder context 只接收任务几何、`parameters_json={}` 和 `model=null`；恢复依赖的长度、模式、表与流参数必须来自完整输出或方法固定定义。

## 算法 API 与计时边界

| 方法 | 编码／解码的实际 API | prepared 可重用状态 |
| --- | --- | --- |
| Brotli | `BrotliEncoderCompress`；`BrotliDecoderCreateInstance`、`BrotliDecoderDecompressStream`、destroy | 固定配置与 caller buffer；单次 API 必需的 native state 创建／分配／销毁仍在操作内 |
| BZip2 | `BZ2_bzBuffToBuffCompress`；`BZ2_bzDecompressInit`、`BZ2_bzDecompress`、end | 固定配置与 caller buffer；native state 生命周期仍在操作内 |
| zlib | `deflateReset`、`deflate(..., Z_FINISH)`；`inflateReset`、`inflate(..., Z_FINISH)` | `deflateInit2`／`inflateInit2` 创建的 workspace；每次重新开始独立 RFC1950 stream |
| XZ | `lzma_easy_buffer_encode`；`lzma_stream_decoder`、`lzma_code(..., LZMA_FINISH)`、end | 固定配置与 caller buffer；内部必要分配仍在操作内 |
| FSE／HUFF0 | `FSE_compress`／`HUF_compress`；对应 decompress | caller buffer；每次 histogram、归一化、表构建／序列化和编码均执行，没有预训练表 |
| LZSS | `tscb_lzss_raw::encode`；同一原生算法单遍 `decode_checked` | caller buffer；滑动窗口初始化、match search、位打包／padding 每次执行 |
| Dipperstein LZSS | 上游 `EncodeLZSS(FILE*, FILE*)`／`DecodeLZSS(FILE*, FILE*)` | caller buffer；内存 FILE 创建、bitfile、流缓冲与关闭均包含在每次操作内 |
| LZSSE2／8 | `MakeOptimalParseState` 创建 workspace；`CompressOptimalParse`；`Decompress` | 原生 optimal parse workspace；每次 native API 自身重置 finder，并执行完整查找和最优解析 |

driver 在原生进程内循环上述操作。prepared 只移出合法 context／caller buffer 准备；不能把采样、数据建模、编码或结束移到计时外。fresh_request 额外包含 context 创建、配置、caller buffer 创建／分配和 context 销毁；产品存活到计时外验证和 release。所有本组返回值都直接指向 caller buffer，下一次操作及 context 销毁不会收回已有输出。

没有强行给不能 reset 的 API 构造虚假的稳定 context。Brotli、BZip2、XZ 的 native 单次分配成本会继续反映在 prepared 结果中。zlib 的 `deflateReset`／`inflateReset` 和 LZSSE 内部模型重置属于每次调用，不能留存上一份对象的历史字典。

## 完整输出

| 方法 | 全部计费的表示 | 恢复所需状态 |
| --- | --- | --- |
| Brotli | 完整 RFC7932 stream | window、元块、内建字典引用、末块与结束 bits |
| BZip2 | 完整 `BZh` stream | block size、每块表／内容、CRC 与结束标记 |
| zlib | 完整 RFC1950 stream | header、DEFLATE block 与 Adler32 |
| XZ | 完整单线程 XZ／LZMA2 stream，`LZMA_CHECK_NONE` | stream／block headers、filter properties、LZMA2 内容、index 与 footer；不暗中改用 raw LZMA2 |
| FSE／HUFF0 | `mode:u8 + decoded_bytes:u64le + body` | mode 0 为完整 raw bytes，mode 1 为一个 repeated symbol，mode 2 为包含本次模型／表的完整原生 entropy block |
| LZSS／Dipperstein LZSS | `decoded_bytes:u64le + unchanged native bitstream` | 固定方法定义的窗口／参数、literal／match token 与末字节 padding |
| LZSSE2／8 | `decoded_bytes:u64le + unchanged native block` | fixed optimal parse level 12、native prefix／control／literal tail；body 大小等于 decoded 大小时为上游原生 raw 表示 |

FSE 的公开 API 特别规定：返回 0 表示不可压缩，且不写出可解码内容；返回 1 表示 repeated symbol，`FSE_decompress` 本身不处理这两种分支。因此不能把返回值当作完整压缩 bytes。HUFF0 decoder 可以恢复 raw／RLE，但同样依赖原长和调用方分支判断。本组保留 9-byte 模式／长度格式，raw／RLE 都是所选完整 entropy 方法的显式表示，完整计费。空输入表示为 mode 0、原长 0 的 9 bytes。

LZSS 和 LZSSE 的长度字段用于恢复终止与 raw／compressed 判定，属于方法输出，而非实验管理记录。空输入是长度为零的 8 bytes。Dipperstein 的空输入绕过有 bitfile 分配但提前 return 而未释放的上游路径；没有可编码 token，该表示完整。Brotli／BZip2／zlib／XZ 则由原生 API 写出各自完整空流。

实验 JSON、来源、hash、输入身份和保存路径由框架旁置，不写入以上结果。大小不会由旧 ABI 字节数估算扣除。

## 限制与检查

FSE／HUFF0 当前为单块完整方法，限制 128 KiB；超限请求保持 unsupported，不自动切块改变方法。BZip2／zlib 遵循其 unsigned int API 界限，LZSS 两实现限制 UINT32_MAX bytes，LZSSE 限制 INT32_MAX bytes 并要求 SSE4.1。XZ decoder 保留 1 GiB 原生内存限制。

EI10/EJ4/C32 LZSS 新增 `decode_checked` 在恢复字节的同一趟解析中验证 token 读取、确切输出数量和最终零 padding。旧对象入口的 `strict_stream + decode` 仍保留，但不把完整流预扫描混入新直接入口。

Dipperstein 上游 `lzss.c`／`tree.c` 使用 static 滑动窗口／查找状态，不能把它声明为可并发 reentrant context。本工程使用单线程 worker 进程，每进程串行调用；进程间状态隔离。输出通过 `fopencookie` 限界写入 caller buffer，避免旧 `open_memstream` 后再复制整份输出；创建／flush／error／close 都在调用内。该 decoder 继承原源以 EOF 结束的语义，没有增加全流 grammar prepass；框架外部精确恢复验证仍为结果有效的必要条件。

LZSSE 使用原生 fast decoder，并检查长度字段、raw size 分支、最小 SIMD prefix／control／tail 大小和返回数量。没有把旧 shim 的全流扫描留在主时间内。vendor fast API 对任意损坏流的行为不等同于经安全审计的解析器；本入口处理其真实编码产物，正式结果必须通过独立进程与计时外逐产物精确验证。若原源在特定输入上恢复错误，应使结果失效，不能用另一算法或 raw fallback 替换测量。

## 与 lzbench 的对照

只读对照 `/home/fzg/PycharmProjects/lzbench/bench/lz_codecs.cpp` 的 Brotli、LZSSE2／8 wrappers，以及 `bench/symmetric_codecs.cpp` 的 BZip2 wrappers。Brotli 与 BZip2 使用同种完整 native encode API；LZSSE 的 workspace 在 init 创建、重复调用 `CompressOptimalParse`，本组 prepared 遵循相同的合法 workspace 复用。新增长度字段完整计费，不能直接把本站完整表示压缩率等同于 lzbench raw body 大小。

该 checkout 的 XZ wrapper 使用多线程 stream encoder／decoder；本工程冻结为单线程、无 data check 的完整 XZ 单次方法，不能因参考它而替换线程或格式。没有执行 lzbench 性能测试；TFBench 的可确认来源限制见 [原生参考记录](../research/native_reference_notes.md)。

## 验证安排

`benchmark/tests/test_core_bytes.py` 使用中央构建的真实动态库，覆盖 10 个 codec、0／1／31／257／4099 bytes、同一 context 内不同输入再回原输入、输出保留到 context 销毁之后、只给空参数的独立 decoder、caller 前后 canary 与输入不变、C／F 浮点物理布局、容量失败及截断 header。FSE／HUFF0 另覆盖 raw／RLE／model 三分支；LZSSE 另覆盖 native raw 与 optimal parse compressed 分支。BZip2／zlib／XZ 还由 Python 标准库独立验证原生标准流。

本组不自行构建、运行测试或生成性能结果。主任务统一串行构建、测试与正式运行；这里记录实现事实，尚未通过的检查不声明为通过。

## 构建集成

6 个新增 C++ TU 为 `adapters/{brotli_stream,bzip2_stream,deflate_zlib,xz_stream,entropy_fse,lzss_dipperstein}/native/direct_core.cc`。要求 C++17 和 C++ runtime，原 vendor C TU 继续由 C 编译器编译并以 C linkage 引用；`entropy_fse` 按 `TSCB_HUFF0=0/1` 分别链接相应方法。LZSS／LZSSE 的原 C++ shim include 对应 `direct_core.hpp`，不再新增编译 TU。

共享 `native/include/tsbench_core_bytes.hpp` 与 `native/include/tsbench_core.hpp`、`tsbench_core.h` 都属于构建身份。LZSSE8 还 transitive include `adapters/lzsse2_raw/native/direct_core_shared.hpp`，不能漏记这条源码依赖。
