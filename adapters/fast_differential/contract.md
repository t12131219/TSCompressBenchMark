# FastDifferentialCoding 原源码接入合同

来源和本地 Benchmark D1/D4 调查见 `SOURCE_ADMISSION.md`；vendor 七文件原样
冻结于 `SOURCE_LOCK.json`。此组件是 P0 `uint32` D1 变换，差值和逆 prefix sum
均模 2^32。不排序、不截断 int64 timestamp、不转换浮点，不增加压缩 backend。
四个上游 API 全部保留：参数 `api_mode=DISTINCT/INPLACE` 分别选择对应的
encode/decode API；`starting_point` 是完整 uint32 参数，默认为 0。

## 原生 ABI 和输入

使用 `native/include/tscb_adapter_v1.h`。原生 create 只接受精确 canonical JSON：
`{"api_mode":"DISTINCT","isa":"SSE4_1","starting_point":0}`，亦支持 INPLACE
和 0..4294967295 的任意十进制 seed。未知字段、空格、重复字段、负值、溢出、
前导零和非规范表示均拒绝。Linux x86_64、little endian、SSE4.1；无 fallback。
构建不使用 `-march=native`。原 API 的完整四词组使用 SSE，尾部 scalar。

输入为 rank-1、dtype U32_LE、stride=4，N=0..16777216。输入 shape=N，used=4N，
capacity>=used；输出 byte/vector descriptor 的 shape 等于 capacity/元素宽度。
unused shape/stride 槽为 0，reserved=0，合法 ownership/alignment。允许 byte
alignment=1；源码 scalar typed access 经 malloc 的 uint32 staging，external
overread=0。对外输入输出区间禁止重叠，包括 INPLACE 模式；该模式只作用于
内部 staging。原输入不可写，失败不修改输出 data/used 或生命周期。

一对象一次 update，随后必须一次 zero-byte finalize，才能获取 accounting。
重复 update/finalize 拒绝；未 update finalize 返回 FINALIZE_REQUIRED。
reset mode=0 清除对象状态和 timer，但保留 mode/seed/timer enablement；其他
reset mode 拒绝。decode 可使用全新 context，并按码流保存的 seed/mode 运行，
不依赖 decoder 默认参数或先前 encode；decode 不改变 encode 生命周期。
query、增量 streaming、random access 不支持。

## 实际原生对象（FDC1）

所有字段 little endian，长度恰为 `32 + 4N`：

| offset | bytes | 内容 |
| --- | --- | --- |
| 0 | 8 | `TSCBFDC1` |
| 8 | 4 | N |
| 12 | 4 | starting_point |
| 16 | 4 | mode：0=DISTINCT，1=INPLACE |
| 20 | 4 | reserved=0 |
| 24 | 4N | 原 API 输出的 D1 uint32 words，逐字节保存 |
| 24+4N | 8 | 前面所有 bytes 的 FNV-1a-64（非认证 checksum） |

decode 在任何原 API 调用和输出写入前检查 magic、count limit、mode、reserved、
exact payload length、checksum 与输出 capacity。较大输出允许，used=4N；不足
返回 DST_TOO_SMALL。所有长度和地址运算先检查，畸形 metadata 不会触发原 API。
native bound 是精确序列化长度，capacity 未用尾部不计费。FNV 实现属于 wrapper，
不得替换成源算法时间。

Python 完整对象保存并校验 dtype/shape/name/track/units 和参数 descriptor。
外层为 magic `TSCBFDP1`（8 bytes）、descriptor 长度 u32（4）、descriptor SHA256
（32）、canonical UTF-8 JSON descriptor、完整 FDC1。descriptor 限 4096 bytes，
保存全部算法参数（mode/ISA/seed），计时开关属于 measurement 参数而不改变码流。
该接入当前限定 VALUE/UTS 的单个 uint32 列；strided/reversed 只做同 dtype/order
的显式 gather，misaligned contig 交由 native typed staging；无 validity bitmap。
解码不借用 encoder context 或原 dataset shape。每个 API 模式均公开实际函数名、
copy/allocation requests 和 padding=0。所有 wrapper bytes、checksum、words 都
计入 FinalBits。32 bytes 原生
wrapper 可拆为 metadata=16、container=8、checksum=8，words=4N。P0 不减少
payload 字节，扩张必须如实报告。此合同不等于已通过五层验收。

## 分配、拷贝与计时边界

成功路径每 encode/decode 的 typed staging allocation 请求：INPLACE 为
`4*max(N,1)`，DISTINCT 为 `8*max(N,1)`。encode 首先 copy 4N 输入 bytes，
原 API 后 copy 4N words 到真实输出；decode copy 4N words 到 typed staging，
原 API 后 copy 4N reconstructed bytes 到输出。没有外部 padding 或隐藏 backend。
wrapper 的 header/checksum 使用 byte access，不要求 aligned 输入输出。

native timer 仅包所选原 `compute_deltas[_inplace]` 和
`compute_prefix_sum[_inplace]`，包含 N=0 的真实原 API 调用。分配、copy、format、
checksum、FFI、descriptor 的 update/decode 工作包含于主 CORE，生命周期遵循
框架的 PIPELINE/E2E 边界（create/bound/accounting/close 不冒充 CORE）；不能
把辅助 timer 作为主结果。复用共享 timer 的非破坏查询、累计、reset、disabled/
unavailable 语义；提前拒绝不计 native API 时间。Python allocation telemetry
报告确定的请求字节，不能冒充 peak RSS。

## 资格范围

source 原 unit 与 source_guard 的三档 PASS 仅证明原 API。bounded ABI 必须另测
两模式、seed、SIMD/tail/empty、guard pages、misalignment、source oracle/byte
equivalence、capacity/alias、corruption、atomic failure、lifecycle、allocation
failure 和 native timing。只有随后 Python/registry/五层运行/正式重复/独立审计
全部完成后，才可在追踪表声明相应范围接入。源文件、公共 headers、binding、
compile command、binary 与实际 compiled closure 的漂移不得绕过。
