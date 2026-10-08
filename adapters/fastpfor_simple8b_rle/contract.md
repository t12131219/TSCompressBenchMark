# FastPFOR Simple8b_RLE 有界 ABI 与 SDK 合同

三档 native safety/fault、466 项 Python SDK 测试、注册、五层执行和正式统计
已通过独立审计。五层/正式范围限于合成 uint32 VALUE/UTS；完整清单条目未完成。

## 配置和输入

仅 little-endian x86-64，源码 ISA=baseline scalar，无隐式 ISA fallback。
canonical config 为
`{"codec":"SIMPLE8B_RLE","isa":"SCALAR","mark_length":true}`，
mark_length 可为 false，其余参数非法；不隐含 Delta/ZigZag。
输入 dtype 为 U32_LE，rank1、stride4，全部 uint32 value 有效；
count范围0–16,777,216。count上限还保证源 RLE 的 bit-length乘法不溢出。
源 `uint32_t*` 输入/输出通过内部 aligned vectors 提供；外部 alignment=1，
无需外部 padding。源/输出区域、descriptor 与 opaque handle 相互 alias 拒绝。

bounded ABI 使用 `native/include/tscb_adapter_v1.h` 和可选 timing 扩展；
C++异常被映射为 CODEC_ERROR，不跨 ABI。
单对象一次 compress，finalize不产出额外 bytes；重复update/finalize拒绝，
reset保留配置和计时开关。失败不改变外部输出/used字段，允许重试。
不声明 streaming/query 或并发 handle 共享。
共享库以 `-Wl,-Bsymbolic` 绑定自身函数和C++虚表；仅C ABI跨库边界。

## 8BR1 物理对象

全部多字节字段为 little-endian。总长度为 `40 + 4 * source_words`。

| 偏移 | 字节 | 内容 |
| --- | --- | --- |
| 0 | 8 | magic `TSCB8BR1` |
| 8 | 4 | uint32 logical count |
| 12 | 4 | kind=0，唯一的 RLE 版本 |
| 16 | 4 | mark_length=0或1 |
| 20 | 4 | 完整 source_words，含可选 uint32 count marker |
| 24 | 8 | 两个保留 uint32，均为0 |
| 32 | 4×source_words | 修复后的原公共 API 产生的完整 source bytes |
| 32+4×source_words | 8 | 前述所有 bytes 的 FNV-1a64 checksum |

bound为 `40 + 8*N + (mark_length ? 4 : 0)`，不是真实最终长度。
fresh decoder 从对象恢复 marker配置和 count，不依赖创建时的 mark_length。
先检查 identity、geometry、资源上限、checksum、容量、marker count，
再检查每个完整 uint64 word 的 selector、RLE count、packing value域及零尾位。
selector0/EOS、RLE count=0、超过剩余 logical count 的 RLE、额外/不足words、
非零未使用位及不适用于uint32的60-bit值拒绝。
scanner不重建 values，真正的重建仍调用修复后的原 decodeArray。

## 完整计费与计时

账本包含 magic64、frame metadata192、checksum64、可选 source marker32、
每word的selector4。RLE另计count28和value32；普通packing计实际使用字段，
selector14的uint32 value计32，其60-bit区域其余28计padding。
全量 components 之和必须等于真实对象长度×8；内部 staging 不当作码流。
telemetry另记录原payload/raw bytes、两个 staging vectors 的 allocation和copy成本。

native计时在handle创建时关闭；setter清零，reset保留开关并清零，query不清零。
encode/decode分别包围一次原公共 API；参数检查、预验证、分配、拷贝、frame、
checksum和accounting不计入原API辅助时间，但属于wrapper/CORE成本。
关闭计时保持相同wire；坏时钟、倒退、累计溢出及源调用C++异常使计时不可用。
CPP异常时结束读钟仍执行，不把不可用计时发布为0。

## 已执行与尚缺的验证

CPU2 release/debug/ASan+UBSan shared libraries 已各实际执行26,928个功能场景，
共80,784：widths0–32、17种长度、六种pattern、两个marker配置、四个外部
byte offsets；核对原wire oracle、RLE字段计费、input immutability、canary、
bound/exact-1原子拒绝及重试、fresh decoder、finalize和真实timer开关/累计。

原始命令、实际共享库/可执行文件hash与compiler closure保存于
`build/source-audits/fastpfor-simple8b-rle-native-smoke-20261007-2/report.json`。
三档构建与实际补丁应用位于
`build/adapters/fastpfor_simple8b_rle/20261007-2/<profile>/build-record.json`。
测试程序只含独立wire oracle和C ABI，不含FastPFOR实现或C++虚表；
每档实际 `nm --defined-only` 的原始结果也保留，确认实现未被测试程序覆盖。
初始编号1的构建、执行、原测试代码和driver仍保留为历史证据：其测试程序
包含RLE的弱虚表符号，库也有可被替换的虚表relocation；因此不能据初始
功能结果认定执行了原发布库的kernel。当前结论采用重新构建和执行的编号2。
使用detect_leaks=0，无LeakSanitizer声明。

系统化 malformed/truncation/descriptor/alias/guard-page矩阵和同发布objects的
source/allocation/clock fault已在三档CPU2实际运行通过；新增功能105,732、
malformed/truncation106,359、guard-page7,128、descriptor/alias/lifecycle474、
fault102。89长度功能矩阵的四种offset按场景对循环，并非offset笛卡尔积。
实际测试和闭包保存在native-safety/native-faults的20261007-1独立目录。
独立native审计PASS，有界ABI为QUALIFIED_SCOPED_UINT32_ONLY；
完整清单条目为false。

## Python SDK 和已执行的 Benchmark 范围

登记 key 为 `fastpfor-simple8b-rle-u32`，SDK 位于
`src/tscompbench/adapters/fastpfor_simple8b_rle.py`，复用 Simple 的 descriptor、
有界生命周期和 native timing 基础设施，RLE 独立验证 frame 和 selector/RLE 账本。
Python 对象是 44-byte `TSCB8BC1` prefix、规范 JSON descriptor、descriptor SHA256
和完整8BR1；decoder从stream恢复marker配置。native辅助计时默认由SDK开启，
关闭时原时钟不调用且wire相同，计时结果为null。descriptor、grammar、allocation、
copy、checksum均计入CORE/PIPELINE，原API辅助时间仅包围encodeArray/decodeArray。

CPU2已实际运行466项SDK测试，87个实际导入项目文件逐字节冻结；证据目录
`build/source-audits/fastpfor-simple8b-rle-sdk-20261007-1/`。完整uint32、零长度、
15 selectors、布局、alias、精确容量、生命周期、坏对象及每个截断点均覆盖。

五层资格执行 `20261007-2` 的四个marked/timer配置，4 PASS；ETTh1 VALUE 和
TIMESTAMP的8条任务均UNSUPPORTED，不隐式cast、预处理或改变算法域。
正式CPU0串行，每配置20次，共80次，74次有效、6次检测到swap并排除；
四组有效次数分别为14、20、20、20，预热和encode/decode各至少1秒满足。
独立审计重建完整wire及账本，核对fresh opposite-marker decoder、原API计时、
staging成本、所有五层文件、原始投影、coverage及基于全部有效重复的统计。

当前审计为 `build/source-audits/fastpfor_simple8b_rle_{qualification,formal}_current_audit.json`，
实际报告为 `build/source-audits/fastpfor-simple8b-rle-{qualification,formal}-20261007-2/report.json`。
其他数据集、timestamp pipeline和其余清单范围仍待完成。
