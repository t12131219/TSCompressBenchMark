# 压缩算法 C/C++ 重写与基准实现工程规范
## Compression Algorithm C/C++ Porting & Benchmark Implementation Standard

**文档版本**：v1.0  
**适用范围**：有损/无损压缩算法从 Python、NumPy、Java、Rust、MATLAB、Fortran 或其他语言迁移/重写至 C/C++；尤其适用于时序数据、传感器数据、科学计算数据及统一 Benchmark 框架。  
**目标读者**：项目经理、算法工程师、C/C++ 工程师、性能工程师、测试工程师、代码审查人员、研究生/科研开发人员。  
**文档性质**：工程规范、实现约束、Code Review 基线、CI 验收标准。  

---

# 0. 文档目标

本规范解决的不是“如何把 Python/Java/MATLAB/Rust 语法翻译成 C/C++”，而是：

> 在大规模压缩算法重写过程中，确保 **算法定义、数值语义、状态语义、bitstream 语义、内存语义、误差语义、性能计量语义和许可证语义** 不发生未经记录的变化。

整个迁移必须遵循：

```text
论文 / 标准 / 原始实现
        ↓
Algorithm Contract
        ↓
Golden Vectors
        ↓
Scalar Canonical C/C++
        ↓
Differential Validation
        ↓
Benchmark Adapter
        ↓
Optimized C/C++
        ↓
SIMD / Thread / GPU / HLS
        ↓
再次 Differential Validation
```

核心原则：

> **Reference First → Correctness First → Optimization Second → Parallel/SIMD Third**

第一版 C/C++ 实现的目标是“正确、可解释、可验证”，不是“最快”。

---

# 1. 规范性用语

本文件使用以下强制等级：

| 术语 | 含义 |
|---|---|
| **MUST / 必须** | 不满足则实现不得合入 canonical 分支 |
| **MUST NOT / 禁止** | 一旦违反视为 correctness defect |
| **SHOULD / 应当** | 除非有明确理由，否则必须遵守 |
| **SHOULD NOT / 不应** | 原则上禁止，若采用需记录原因 |
| **MAY / 可以** | 可选实现策略 |
| **WAIVER / 豁免** | 对规范的正式例外，必须留下书面理由和影响分析 |

任何开发者不得以“性能更快”“代码更短”“在我的机器上没问题”为理由绕过 MUST 条款。

---

# 2. 重写工作的三个等级

每个算法在立项时必须声明迁移目标等级。

## 2.1 Level P1：Source Port

要求：

- 数学算法一致；
- 编解码基本可用；
- 不要求与参考实现 bitstream 相同；
- 不要求跨实现交叉解码。

适合：

- 论文只有伪代码；
- 原代码质量差；
- 无公开格式规范；
- 只需要重现实验逻辑。

## 2.2 Level P2：Semantic Reimplementation

要求：

- 算法行为一致；
- 参数定义一致；
- 边界条件一致；
- 有损误差语义一致；
- block/state/reset 语义一致；
- 参考输入下关键中间状态可比。

**Benchmark 中的新实现至少应达到 P2。**

## 2.3 Level P3：Bitstream-Compatible Reimplementation

要求：

- 遵循标准/官方格式；
- 新编码器输出能被参考解码器读取；
- 新解码器能读取参考编码器输出；
- frame/header/block/checksum/dictionary/version 等字段兼容；
- 对标准允许的非唯一编码，不要求字节完全一致，除非格式定义要求 deterministic canonical encoding。

典型对象：

- DEFLATE；
- LZ4 Frame；
- Zstandard；
- 其他存在公开 bitstream 规范的编码格式。

---

# 3. 项目治理与阶段 Gate

任何算法必须经过以下 Gate。

## Gate G0：来源确认

必须明确：

- 论文；
- 代码仓库；
- commit/tag/version；
- 原始语言；
- 原始许可证；
- 是否标准格式；
- 是否存在官方 decoder；
- 是否存在测试向量。

**未完成 G0，不允许开始正式移植。**

## Gate G1：Algorithm Contract 冻结

必须定义：

- 输入类型；
- 数据布局；
- 参数；
- 数学公式；
- 边界条件；
- 状态模型；
- bitstream；
- error bound；
- 输出条件。

**未完成 G1，不允许开始优化。**

## Gate G2：Canonical Scalar Correctness

要求：

- scalar C/C++ 完成；
- golden tests 通过；
- sanitizer 通过；
- differential test 通过；
- 无损 round-trip 通过；
- 有损误差约束通过。

## Gate G3：Benchmark Adapter

要求：

- API 与统一框架一致；
- setup/encode/decode/reset 分离；
- memory accounting 明确；
- compressed-size accounting 明确；
- benchmark 不包含未声明的预处理成本。

## Gate G4：Optimization

只有 G2/G3 通过以后才允许：

- SIMD；
- OpenMP；
- pthread/std::thread；
- CUDA；
- architecture-specific intrinsic；
- fast-math 实验；
- GPU；
- HLS/FPGA。

## Gate G5：Release

必须完成：

- correctness；
- portability；
- security；
- performance；
- license；
- documentation；
- reproducibility。

---

# 4. 每个算法必须提交的交付物

建议目录：

```text
algorithms/
└── <algorithm_id>/
    ├── README.md
    ├── metadata.yaml
    ├── contract.md
    ├── LICENSE_ORIGIN.md
    ├── reference/
    │   └── ...
    ├── canonical/
    │   ├── encoder.cpp
    │   ├── decoder.cpp
    │   └── internal.hpp
    ├── optimized/
    │   ├── avx2/
    │   ├── avx512/
    │   ├── neon/
    │   └── omp/
    ├── adapter/
    │   └── benchmark_adapter.cpp
    ├── tests/
    │   ├── golden/
    │   ├── differential/
    │   ├── malformed/
    │   └── performance/
    └── reports/
        ├── porting_report.md
        └── validation_report.md
```

每个算法 MUST 有：

```text
metadata.yaml
contract.md
canonical implementation
unit tests
golden tests
validation report
source/license record
```

---

# 5. Algorithm Contract 模板

每个算法在编码前必须填写。

```yaml
algorithm_id:
algorithm_name:
category:
  - lossless | lossy
family:
source:
  paper:
  repo:
  commit:
  version:
original_language:
license:
porting_level: P1 | P2 | P3

input:
  dtype:
  dimensions:
  layout:
  signedness:
  endian:
  allows_empty:
  supports_nan:
  supports_inf:
  supports_negative_zero:
  supports_subnormal:

state:
  stateless:
  streaming:
  block_independent:
  cross_block_history:
  dictionary:
  reset_semantics:

lossy:
  enabled:
  error_mode:
  error_value:
  rounding:
  fp_precision:
  fma_policy:
  nan_policy:
  inf_policy:

bitstream:
  standardized:
  specification:
  byte_order:
  bit_order:
  version:
  checksum:
  frame_structure:

benchmark:
  preprocessing_included:
  metadata_included_in_size:
  workspace_accounted:
  threads:
```

---

# 6. 源语言语义审计

迁移前 MUST 写一份“Source Language Semantic Audit”。

原因：不同语言相同表达式可能具有不同语义。

---

## 6.1 Python

### PY-001：Python `int` 不得直接映射为 C `int`

Python 内置整数具有任意精度。

所以：

```python
x = a * b
```

不能默认翻译为：

```cpp
int x = a * b;
```

必须确定原算法的理论位宽。

### PY-002：必须区分 Python `int` 与 NumPy integer

NumPy：

```python
np.int32
np.int64
np.uint32
```

属于固定宽度数值类型。

其溢出行为和 Python `int` 不同。

### PY-003：Python `round()` 必须审计

Python 内置：

```python
round(0.5) == 0
round(1.5) == 2
round(2.5) == 2
```

采用 nearest-even tie-breaking。

不得直接替换成：

```cpp
std::round()
```

因为 C/C++ `round()` halfway 是 away-from-zero。

---

## 6.2 Java

### JAVA-001：整数 overflow 语义必须显式复制

Java 固定宽度整数溢出保留低位，即具有定义好的二补码 wrap 行为。

C/C++ signed overflow 则可能是 undefined behavior。

错误迁移：

```java
int hash = value * 0x9E3779B9;
```

直接变成：

```cpp
int32_t hash = value * 0x9E3779B9;
```

正确策略通常是先转换成：

```cpp
uint32_t hash =
    static_cast<uint32_t>(value) * UINT32_C(0x9E3779B9);
```

再在需要时显式解释位模式。

### JAVA-002：Java shift distance 必须审计

Java 对 `int` shift 只使用 shift count 的低 5 bit，对 `long` 使用低 6 bit。

C/C++ 不允许直接假设相同语义。

所有 Java：

```java
x << s
x >> s
x >>> s
```

迁移时必须独立审核。

特别注意 Java `>>>` 无符号右移在 C/C++ 中没有 signed 类型的一一对应操作。

---

## 6.3 Rust

### RUST-001：不得假设普通 Rust overflow 始终等于 C++ unsigned wrap

Rust debug 与某些 build configuration 下 overflow 可 panic；release 可能 wrap。

原实现若使用：

```rust
wrapping_add
wrapping_mul
checked_add
saturating_add
```

必须逐一保留对应语义。

### RUST-002：`wrapping_*` 必须用显式无符号或专门 helper 重现

禁止依赖 C/C++ signed overflow。

---

## 6.4 MATLAB

### MATLAB-001：数组布局必须审核

MATLAB 默认：

```text
column-major
```

C/C++ 常规二维数组：

```text
row-major
```

因此 MATLAB：

```matlab
A(i,j)
```

迁移时不能机械映射。

必须审计：

- linear indexing；
- reshape；
- transpose；
- permute；
- flatten；
- 邻域访问；
- predictor 邻接关系。

### MATLAB-002：round 版本和 TieBreaker 必须记录

现代 MATLAB 默认 tie 行为可与 C/C++ `std::round` 接近，但历史版本行为发生过变化。

项目必须记录：

```text
MATLAB version
round tie mode
```

### MATLAB-003：矩阵运算顺序不得擅自改变

```matlab
A * B
```

如果迁移时为了方便将数据 transpose 后计算，必须证明：

```text
数学含义一致
+
storage layout 转换成本被正确计量
```

---

# 7. C/C++ 语言基线

推荐 canonical 实现使用：

```text
C11/C17
或
C++17/C++20
```

项目必须固定：

```text
compiler family
compiler version
language standard
standard library
platform ABI
```

建议主要核心类型来自：

```cpp
#include <cstdint>
#include <cstddef>
#include <limits>
```

---

# 8. 整数规则

## INT-001：serialized integer 必须有明确宽度

必须使用：

```cpp
std::uint8_t
std::uint16_t
std::uint32_t
std::uint64_t

std::int8_t
std::int16_t
std::int32_t
std::int64_t
```

禁止在文件格式中使用未固定宽度的：

```cpp
int
long
short
```

---

## INT-002：长度和容器大小优先使用 `size_t`

但不得混淆：

```text
size_t
serialized uint64
algorithmic uint32
```

它们是三种不同概念。

---

## INT-003：禁止依赖 signed overflow

以下写法必须审核：

```cpp
a + b
a - b
a * b
-a
```

特别是：

```cpp
INT_MIN - 1
-INT_MIN
```

---

## INT-004：模 2^N 算术必须显式使用 unsigned

如果算法定义：

\[
x \leftarrow x \pmod{2^{32}}
\]

必须使用：

```cpp
std::uint32_t
```

而不是：

```cpp
std::int32_t
```

的 overflow。

---

## INT-005：所有 size arithmetic 必须做 overflow check

例如：

```cpp
size_t total = n * channels * sizeof(double);
```

必须检查：

```text
n * channels
channels * sizeof(T)
offset + length
header + payload
```

推荐 helper：

```cpp
bool checked_add_size(size_t a, size_t b, size_t* out);
bool checked_mul_size(size_t a, size_t b, size_t* out);
```

---

## INT-006：conversion 必须审核

高风险转换：

```cpp
uint64_t -> uint32_t
size_t   -> int
double   -> int32_t
int64_t  -> int32_t
signed   -> unsigned
```

必须确认：

```text
range
rounding
overflow
negative input
```

---

# 9. Shift / Bit Operation 规则

## BIT-001：shift count 必须满足位宽范围

禁止：

```cpp
x << 32  // 对 32 位值
x << 64  // 对 64 位值
```

所有动态 shift：

```cpp
x << n
```

必须保证：

```text
0 <= n < bit_width
```

---

## BIT-002：对 signed negative value 的位运算必须谨慎

需要逻辑右移时：

```cpp
static_cast<uint32_t>(x) >> n
```

不要依赖 signed right shift 的平台/语言语义差异。

---

## BIT-003：bit mask 必须用正确宽度常量

推荐：

```cpp
UINT32_C(1)
UINT64_C(1)
```

例如：

```cpp
UINT64_C(1) << bit
```

而不是：

```cpp
1 << bit
```

---

# 10. Endianness

## END-001：bitstream 禁止使用 host-native endian

禁止：

```cpp
fwrite(&value, sizeof(value), 1, file);
```

作为协议序列化方式。

必须明确：

```text
Little Endian
或
Big Endian
```

---

## END-002：提供统一 serialization helper

例如：

```cpp
uint16_t load16_le(const std::byte* p);
uint32_t load32_le(const std::byte* p);
uint64_t load64_le(const std::byte* p);

void store16_le(std::byte* p, uint16_t v);
void store32_le(std::byte* p, uint32_t v);
void store64_le(std::byte* p, uint64_t v);
```

算法代码不应自行重复 endian conversion。

---

## END-003：跨平台 CI 必须至少验证两种架构

理想：

```text
x86_64
AArch64
```

如有 big-endian 环境可进一步加入。

---

# 11. Bitstream 统一规则

建议公共模块：

```text
core/bitstream/
    bit_reader.hpp
    bit_writer.hpp
    endian.hpp
    varint.hpp
    zigzag.hpp
```

---

## BITSTREAM-001：每个格式必须声明

```text
byte_order
bit_order
field_width
padding
alignment
flush rule
frame termination
```

---

## BITSTREAM-002：bit order 和 byte order 必须分开

例如必须明确：

```text
byte order: little endian
bit packing: LSB first
Huffman code traversal: MSB first
```

不能只写：

```text
little endian
```

---

## BITSTREAM-003：跨 64-bit word 写入必须有专门测试

测试：

```text
bitpos = 0
1
7
8
31
32
63
```

并测试：

```text
nbits = 0
1
7
8
31
32
63
64
```

特别是：

```text
bitpos + nbits > 64
```

---

## BITSTREAM-004：flush 必须定义

必须说明：

```text
最后一个 byte 未填满怎么办？
padding bit = 0 还是 unspecified？
是否必须 byte align？
EOF 如何判断？
```

---

# 12. Frame / Header / Metadata

每个自定义格式 SHOULD 使用：

```text
Magic
Version
Flags
Original Size
Algorithm Metadata
Payload Size
Payload
Checksum
```

---

## FRAME-001：格式必须 versioned

禁止发布：

```text
header
payload
```

却没有格式版本。

---

## FRAME-002：reserved bits 必须定义

编码器：

```text
reserved bits = 0
```

解码器：

```text
遇到未知 required feature 必须报错
```

---

## FRAME-003：metadata 必须算入 compressed size

Compression Ratio：

\[
CR=\frac{UncompressedBytes}{TotalCompressedBytes}
\]

其中：

```text
TotalCompressedBytes =
header
+ metadata
+ dictionary if embedded
+ payload
+ padding
+ checksum
```

禁止只统计 entropy payload。

---

# 13. Varint / ZigZag

## VARINT-001：必须限制最大长度

decoder 不能无限读取 varint。

例如 uint64：

```text
最多 10 bytes
```

超过必须返回 malformed stream。

---

## VARINT-002：ZigZag 必须避免 signed overflow

必须从位级定义实现和测试：

```text
0
-1
1
INT32_MIN
INT32_MAX
INT64_MIN
INT64_MAX
```

---

# 14. Memory / Object Model

## MEM-001：禁止未验证的 pointer punning

高风险：

```cpp
uint32_t x = *reinterpret_cast<const uint32_t*>(p);
```

可能涉及：

```text
alignment
strict aliasing
object lifetime
```

优先：

```cpp
std::memcpy(&x, p, sizeof(x));
```

然后显式 endian conversion。

---

## MEM-002：alignment 必须声明

SIMD buffer 必须明确：

```text
required_alignment = 1/8/16/32/64
```

并区分：

```text
aligned load
unaligned load
```

---

## MEM-003：不得默认 allocator 成本为零

Benchmark 必须区分：

```text
setup allocation
workspace allocation
per-call allocation
kernel
```

---

## MEM-004：hot path SHOULD NOT 分配临时容器

不推荐：

```cpp
for (...) {
    std::vector<uint8_t> tmp(size);
    ...
}
```

优先：

```text
create
prepare
allocate workspace
repeat encode/decode
destroy
```

---

## MEM-005：workspace 必须可观测

API 建议暴露：

```cpp
size_t workspace_bytes(const Config&, const InputDesc&);
```

并在 benchmark 结果记录。

---

# 15. Output Capacity

## BUF-001：所有 encoder 必须定义最坏输出容量

不得：

```cpp
compressed.resize(input_size);
```

必须提供：

```cpp
size_t max_compressed_size(
    const InputDesc& input,
    const CodecConfig& cfg);
```

---

## BUF-002：容量计算本身必须 overflow-safe

例如：

```text
header + n + n/255 + ...
```

也需要 checked arithmetic。

---

## BUF-003：encoder 写入前必须验证 output capacity

API 返回：

```text
OK
OUTPUT_TOO_SMALL
INVALID_CONFIG
UNSUPPORTED
INTERNAL_ERROR
```

禁止缓冲区越界后再报错。

---

# 16. Decoder 安全规则

**所有 compressed input 必须视为不可信数据。**

## DEC-001：所有长度字段都必须验证

包括：

```text
frame_size
block_size
literal_length
match_length
dictionary_size
symbol_count
tree_size
offset
```

---

## DEC-002：所有 offset 必须验证

LZ 类算法：

```text
offset > 0
offset <= bytes_already_decoded
```

---

## DEC-003：任何写操作前检查

```text
out_pos + write_len <= output_capacity
```

必须采用 overflow-safe check：

```cpp
if (write_len > output_capacity - out_pos) ...
```

优于：

```cpp
if (out_pos + write_len > output_capacity)
```

因为后者本身可能 overflow。

---

## DEC-004：递归树解析必须限制深度

Huffman/grammar/tree decoder 必须限制：

```text
node count
depth
symbol count
```

防止畸形输入造成：

```text
stack overflow
CPU DoS
memory DoS
```

---

## DEC-005：错误输入必须 deterministic fail

禁止：

```text
crash
UB
hang
infinite loop
silent corruption
```

---

# 17. 无损压缩专项

无损的基本正确性要求：

\[
D(C(x)) = x
\]

但仅做 round-trip 不够。

---

## LOSSLESS-001：必须做 bit-exact reconstruction

对于整数和原始 byte 数据：

```text
memcmp(original, decoded) == 0
```

---

## LOSSLESS-002：浮点无损必须比较 bit pattern

不能只做：

```cpp
a == b
```

因为需要判断：

```text
-0
NaN payload
NaN sign
```

如算法承诺 bitwise lossless，应比较原始 bit pattern。

---

## LOSSLESS-003：Delta 类算法必须定义第一个值

例如：

```text
delta[0] = x[0]
```

还是：

```text
base = x[0]
delta 从 x[1] 开始
```

必须进入格式定义。

---

## LOSSLESS-004：预测 residual 的位宽必须审核

例如：

```cpp
int32_t residual = current - predicted;
```

若两者都是 int32，数学差值可能需要 33 bit。

必须决定：

```text
wrap
widen to int64
zigzag
saturate
error
```

---

## LOSSLESS-005：Dictionary 生命周期必须明确

必须定义：

```text
dictionary source
dictionary ID
dictionary lifetime
per-stream / per-block
embedded / external
reset
```

---

## LOSSLESS-006：Entropy coder 必须定义 tie-breaking

如果相同 frequency 下 Huffman tree 有多个合法结果，必须确认：

- 是否要求 deterministic tree；
- 是否有 canonical Huffman；
- symbol 排序规则；
- frequency tie-breaking；
- code-length ordering。

---

# 18. 有损压缩专项

有损算法的核心不是“能解码”，而是：

\[
\hat{x}=D(C(x))
\]

满足正式 quality/error contract。

---

# 19. Error Bound 语义

## LOSSY-001：禁止只有一个模糊的 `error_bound`

必须使用结构化配置：

```cpp
enum class ErrorMode {
    None,
    Absolute,
    RelativeRange,
    RelativePointwise,
    PSNR,
    L2Norm,
    FixedRate,
    FixedPrecision
};

struct ErrorSpec {
    ErrorMode mode;
    double value;
};
```

---

## LOSSY-002：Relative 必须说明 denominator

可能是：

```text
global max-min
global max(abs(x))
pointwise abs(x_i)
RMS
other scale
```

必须明确公式。

---

## LOSSY-003：ABS 必须明确严格/近似保证

例如：

\[
|x_i-\hat{x_i}| \le \epsilon
\]

如果算法只能“统计上通常满足”，不能标为 strict absolute-bound codec。

---

## LOSSY-004：PSNR 必须明确 peak definition

\[
PSNR = 20\log_{10}\frac{MAX}{RMSE}
\]

其中 `MAX` 到底是：

```text
dtype maximum
data max
range
application fixed peak
```

必须写清楚。

---

# 20. Floating-Point 精度

## FP-001：canonical implementation 必须固定 float/double

不得因为“double 更精确”擅自把原来的：

```text
float32 predictor
```

改为：

```text
double predictor
```

除非该行为作为新的实现 variant 被明确记录。

---

## FP-002：中间精度必须审核

特别关注：

```text
accumulator
mean
variance
regression coefficient
prediction
transform
quantization input
```

---

## FP-003：禁止 canonical build 默认 `-ffast-math`

理由：

fast-math 可能改变：

```text
NaN
Inf
signed zero
reassociation
reciprocal
rounding assumptions
FMA
```

建议：

```text
canonical correctness:
    -O2/-O3
    strict/precise FP

optimized:
    -O3

experimental-fast:
    -O3 -ffast-math
```

`experimental-fast` 必须独立标记，禁止与 canonical 混淆。

---

# 21. Rounding

## ROUND-001：每个 quantizer 必须声明 tie-breaking

可能值：

```text
toward zero
toward +inf
toward -inf
nearest-away-from-zero
nearest-even
custom
```

---

## ROUND-002：禁止直接将 Python `round` 翻成 `std::round`

Python built-in 默认 nearest-even。

C/C++ `std::round` halfway 默认 away-from-zero。

这可以直接改变 quantized code。

---

## ROUND-003：若使用当前 FP rounding mode，必须显式设置/验证

例如：

```cpp
fesetround(FE_TONEAREST);
```

并保证编译器选项允许程序依赖 rounding environment。

---

# 22. FMA / FP Contraction

## FMA-001：canonical validation 必须固定 FMA policy

例如：

```text
FMA_OFF
FMA_STANDARD
FMA_FAST
```

---

## FMA-002：quantization boundary 前的 FMA 特别敏感

```cpp
pred = a * x + b;
q = round((value - pred) / eb);
```

FMA 可能造成：

```text
几个 ULP 差异
↓
跨量化边界
↓
q 不同
↓
bitstream 完全不同
```

因此必须测试边界样本。

---

# 23. NaN / Inf / ±0 / Subnormal

每个浮点算法 capability 必须声明：

```text
supports_nan
supports_inf
preserve_nan
preserve_nan_payload
preserve_signed_zero
supports_subnormal
flush_subnormal
```

---

## SPECIAL-001：NaN policy 必须明确

例如：

```text
reject
pass-through side channel
preserve bit pattern
canonicalize
encode as special symbol
```

---

## SPECIAL-002：Inf policy 必须明确

不能让：

```text
max-min
```

在包含 Inf 时悄悄变成 Inf 并破坏 error bound。

---

## SPECIAL-003：±0 必须明确

如果算法承诺 bitwise lossless：

```text
+0 != -0
```

在 bit pattern 层面必须保留。

---

# 24. Predictor / Transform

## PRED-001：公式必须原样记录

例如：

```text
p_i = x_{i-1}
p_i = 2x_{i-1} - x_{i-2}
```

不能仅写“linear predictor”。

---

## PRED-002：必须定义前 K 个样本

对于 order-K predictor：

```text
x[0:K]
```

怎么编码必须明确。

---

## PRED-003：block boundary 必须定义

例如：

```text
每 block 重置 predictor
```

或：

```text
继承上一 block state
```

二者会直接影响 CR 与 random access。

---

# 25. Block / Chunk / Stream

## STATE-001：必须区分

```text
independent block
dependent block
continuous stream
```

---

## STATE-002：Benchmark 不得擅自改变 reset frequency

例如算法原生 1 MB continuous stream，Adapter 不得因为统一接口而：

```text
每 64 KB reset
```

除非明确作为 benchmark mode。

---

## STATE-003：chunk size 必须作为实验参数记录

至少记录：

```text
input size
block size
chunk size
number of blocks
state reset interval
```

---

## STATE-004：random access 能力必须真实

只有满足：

```text
独立定位
+
不解码之前所有数据
```

才可以声明 random access。

---

# 26. Multivariate / ND 数据布局

必须明确：

```text
N = timestamps
D = channels
```

以及：

```text
row-major:
values[t * D + d]

column-major:
values[d * N + t]
```

---

## LAYOUT-001：不得用 flatten 冒充 multivariate compression

必须区分：

```text
COLUMN_INDEPENDENT
GROUPED_CHANNELS
FULL_MATRIX
NATIVE_ND_ARRAY
```

---

## LAYOUT-002：layout conversion 成本必须计量

如果一个算法必须：

```text
row-major → column-major
```

必须明确：

- conversion 是否算入 encode latency；
- 临时内存是否算入 peak memory。

---

# 27. 统一 Codec API 建议

```cpp
enum class Status {
    Ok,
    InvalidArgument,
    InvalidConfig,
    UnsupportedDType,
    UnsupportedShape,
    OutputTooSmall,
    CorruptInput,
    VersionMismatch,
    DictionaryMismatch,
    InternalError
};

struct BufferView {
    const std::byte* data;
    size_t size;
};

struct MutableBufferView {
    std::byte* data;
    size_t size;
};

struct InputDesc {
    const void* data;
    size_t element_count;
    size_t bytes;
    DType dtype;

    size_t ndim;
    size_t shape[4];
    Layout layout;
};

struct CodecResult {
    Status status;
    size_t bytes_written;
    size_t bytes_read;
};

class Codec {
public:
    virtual ~Codec() = default;

    virtual Status configure(const CodecConfig&) = 0;

    virtual size_t max_compressed_size(
        const InputDesc&) const = 0;

    virtual size_t workspace_bytes(
        const InputDesc&) const = 0;

    virtual CodecResult compress(
        const InputDesc&,
        MutableBufferView output,
        Workspace&) = 0;

    virtual CodecResult decompress(
        BufferView compressed,
        const OutputDesc&,
        MutableBufferView output,
        Workspace&) = 0;

    virtual void reset() = 0;
};
```

---

# 28. API 设计约束

## API-001：禁止隐藏全局状态

不允许：

```cpp
static Dictionary dict;
static PredictorState state;
```

除非明确只读且 thread-safe。

---

## API-002：必须支持 reset

任何 streaming/stateful codec 都要提供：

```cpp
reset()
```

---

## API-003：必须返回实际 bytes_written

禁止由 caller 猜测压缩长度。

---

## API-004：禁止异常和 status 混用无规范

项目必须统一：

```text
exception-based
或
status-code-based
```

Benchmark hot path 推荐 status code，避免异常开销和跨语言 ABI 问题。

---

# 29. Canonical 与 Optimized 实现分离

目录示例：

```text
kernel/
├── scalar/
│   └── codec_scalar.cpp
├── avx2/
├── avx512/
├── neon/
└── cuda/
```

规则：

```text
scalar = correctness oracle
optimized = 必须与 scalar 做 differential validation
```

禁止删除 scalar 版只留下最快版本。

---

# 30. SIMD 规则

## SIMD-001：不得改变算法语义

vectorization 后必须保持：

```text
symbol sequence
error bound
state
```

在规范允许范围内一致。

---

## SIMD-002：tail 必须专项测试

测试长度：

```text
0
1
vector_width - 1
vector_width
vector_width + 1
2*vector_width - 1
```

---

## SIMD-003：ISA fallback 必须记录

结果 metadata：

```text
isa_requested
isa_available
isa_used
fallback_path
```

---

## SIMD-004：禁止 benchmark 中静默 fallback

例如：

```text
要求 AVX512
实际跑 scalar
```

必须在结果中可见。

---

# 31. 并行化

## THREAD-001：线程数必须固定和记录

```text
threads_requested
threads_used
```

---

## THREAD-002：不得把单线程算法与多线程算法直接比较而不标注

至少分：

```text
single-thread benchmark
multi-thread benchmark
```

---

## THREAD-003：并行版必须通过 TSan 或等效 data-race 检测

特别关注：

```text
shared dictionary
shared histogram
global scratch
static buffer
lazy initialization
```

---

## THREAD-004：determinism 必须定义

多线程压缩可能因为：

```text
parallel reduction order
hash table insertion order
task scheduling
```

导致输出不同。

必须说明：

```text
bitstream deterministic?
semantic deterministic?
quality deterministic?
```

---

# 32. 编译配置

建议至少四类 build。

## 32.1 Debug

```text
-O0/-Og
-g
warnings high
assertions
```

## 32.2 Sanitizer

```text
-O1/-O2
-g
ASan
UBSan
```

多线程另建：

```text
TSan
```

ASan 和 TSan 通常不要放同一 binary。

## 32.3 Canonical Release

```text
-O3
no fast-math
fixed language standard
fixed ISA baseline
```

## 32.4 Optimized Benchmark

```text
-O3
target ISA
LTO policy fixed
vectorization policy fixed
```

---

# 33. Compiler Flag 记录

Benchmark 输出必须保存：

```text
compiler_name
compiler_version
language_standard
optimization_level
march
mtune
mavx/mavx2/mavx512...
mfpu / neon
ffast-math
ffp-contract
lto
openmp
debug_symbols
```

---

# 34. `-march=native` 的约束

`-march=native` MAY 用于：

```text
单设备峰值实验
```

但跨设备 Benchmark 不应将它作为唯一 build。

推荐：

```text
portable baseline
+
native optimized
```

分别报告。

---

# 35. Warning Policy

建议 CI：

```text
-Wall
-Wextra
-Wpedantic
-Wconversion
-Wsign-conversion
-Wshadow
-Wformat=2
```

可按实际编译器调整。

项目应逐步实现：

```text
warnings-as-errors
```

但第三方代码可独立处理。

---

# 36. Sanitizer

## SAN-001：ASan

用于发现：

```text
heap OOB
stack OOB
global OOB
use-after-free
double-free
invalid free
```

## SAN-002：UBSan

用于发现：

```text
signed overflow
invalid shift
misalignment
null dereference
array OOB
invalid cast/conversion
```

## SAN-003：TSan

用于并行实现的数据竞争检测。

## SAN-004：Sanitizer build 禁止用于性能结论

---

# 37. Static Analysis

SHOULD 使用至少一种：

```text
clang-tidy
Clang Static Analyzer
GCC analyzer
Coverity
CodeQL
cppcheck
```

重点规则：

```text
integer overflow
lifetime
null pointer
bounds
uninitialized read
use-after-move
ownership
```

---

# 38. Correctness Testing 总体分层

必须至少分：

```text
L0 Unit
L1 Golden
L2 Roundtrip
L3 Differential
L4 Cross Decode
L5 Malformed Input
L6 Sanitizer
L7 Fuzz
L8 Cross Platform
L9 Performance Regression
```

---

# 39. Golden Vector

每种算法至少准备：

```text
input.bin
config.json
expected_metadata.json
expected_output.bin       # 若 bitstream identity 有意义
expected_decoded.bin
expected_metrics.json
```

---

# 40. 无损测试矩阵

必须包含：

```text
empty input
1 element
2 elements
small blocks
exact block boundary
boundary + 1
all zero
all one
constant
monotonic increasing
monotonic decreasing
alternating
periodic
random
high entropy
low entropy
INT_MIN/MAX
UINT_MAX
overflow-prone delta
```

---

# 41. 浮点测试矩阵

至少：

```text
+0
-0
small normal
subnormal
FLT_MIN
FLT_MAX
DBL_MIN
DBL_MAX
NaN
+Inf
-Inf
values near quantization boundaries
very small dynamic range
very large dynamic range
constant arrays
```

---

# 42. Differential Testing

原则：

```text
same input
same config

Reference
↓
intermediate/output

Canonical C++
↓
intermediate/output
```

比较：

```text
preprocessing
predictor
residual
quantized symbol
entropy symbol
metadata
decoded output
```

这样才能知道差异首次出现在哪里。

---

# 43. 无损四路验证

当参考格式支持时：

```text
1.
C_ref(x)
↓
D_ref
↓
x

2.
C_new(x)
↓
D_new
↓
x

3.
C_new(x)
↓
D_ref
↓
x

4.
C_ref(x)
↓
D_new
↓
x
```

对应：

```text
self reference
self new
new → reference
reference → new
```

---

# 44. Bitstream Identity 不是所有算法都需要

必须区分：

```text
Algorithm Equivalence
Format Compatibility
Bitstream Identity
```

两个 encoder 可能：

```text
bitstream 不同
但都合法
且都可被 decoder 正确读取
```

因此不能将：

```text
compressed_bytes_equal
```

错误地当作所有压缩器的 correctness 条件。

---

# 45. 有损验证

至少计算：

```text
max_abs_error
MAE
MSE
RMSE
NRMSE
PSNR
relative error
L2 norm error
```

根据 codec 声明选择强制指标。

---

## LOSSY-VAL-001：先验证合同，再比较指标

如果配置声明：

```text
ABS <= 1e-3
```

第一判断必须是：

\[
\max_i |x_i-\hat{x_i}| \le 10^{-3}
\]

而不是：

```text
PSNR 看起来很高，所以算通过
```

---

# 46. Fuzz Testing

decoder SHOULD 使用 fuzzing：

```text
random bytes
mutated valid frames
truncated frame
corrupted length
corrupted checksum
oversized varint
invalid offset
unknown version
reserved flag
```

目标：

```text
no crash
no UB
no hang
no OOB
bounded resource consumption
clean error
```

---

# 47. Determinism Testing

相同：

```text
input
config
version
ISA
thread count
```

重复 N 次。

验证：

```text
compressed size
decoded output
quality metrics
bitstream if promised deterministic
```

---

# 48. Benchmark 公平性

Benchmark 必须先回答：

> 我们是在比较“算法”，还是比较“具体实现”？

建议同时定义：

```text
Algorithm Benchmark
Implementation Benchmark
```

---

# 49. Algorithm Benchmark

目标：

```text
尽量减少实现技巧差异
```

推荐：

```text
scalar
single thread
统一编译器
统一优化等级
统一输入
统一 chunk
```

---

# 50. Implementation Benchmark

目标：

```text
测量实际最好实现
```

允许：

```text
SIMD
multithread
native ISA
GPU
```

但必须明确 variant。

---

# 51. 时间边界

必须定义计时范围。

## Kernel-only

```text
prepared input
prepared workspace
start timer
encode
stop timer
```

## End-to-end

```text
layout conversion
preprocess
allocation if applicable
encode
metadata generation
```

两个指标都可以保留，但不得混淆。

---

# 52. Warmup

性能测试必须做 warmup，尤其存在：

```text
instruction cache
data cache
dynamic dispatch
lazy initialization
CPU frequency ramp
JIT（参考语言）
GPU context
```

---

# 53. Repetition

至少记录：

```text
iterations
repetitions
mean
median
min
max
stddev
CV
```

推荐主要展示：

```text
median
+
dispersion
```

避免单次结果。

---

# 54. Throughput

压缩：

\[
T_c=\frac{UncompressedBytes}{CompressionTime}
\]

解压：

\[
T_d=\frac{UncompressedBytes}{DecompressionTime}
\]

必须明确单位：

```text
MB/s  = 10^6 B/s
MiB/s = 2^20 B/s
```

禁止混用。

---

# 55. Compression Ratio

推荐：

\[
CR=\frac{UncompressedBytes}{CompressedBytes}
\]

也可报告：

\[
SpaceSaving=1-\frac{CompressedBytes}{UncompressedBytes}
\]

必须确保 `CompressedBytes` 包含协议必须字节。

---

# 56. Memory Accounting

至少分：

```text
input bytes
output capacity
actual compressed bytes
workspace bytes
codec state
dictionary bytes
temporary peak
total peak RSS（可选）
```

---

# 57. CPU 环境

性能结果至少记录：

```text
CPU model
architecture
cores
SMT
frequency
cache
RAM
OS
kernel
NUMA
```

---

# 58. CPU Frequency / Thermal

长时间 benchmark 必须关注：

```text
DVFS
turbo
thermal throttling
background load
```

如无法完全控制，至少记录并增加 repetition。

---

# 59. Thread Affinity

高精度 Benchmark SHOULD：

```text
pin thread
record CPU core
```

尤其多核设备。

---

# 60. NUMA

在多 socket 系统：

```text
memory placement
thread placement
```

会显著影响结果。

因此必须在高级 Benchmark 中固定或记录。

---

# 61. Dataset 规则

输入 dataset 必须保存：

```text
dataset_id
checksum
dtype
shape
bytes
sampling info
preprocessing
missing-value policy
```

---

# 62. 禁止算法特化污染公平性

一个算法不得偷偷做：

```text
if dataset_name == X:
    use special parameter
```

参数自动选择必须：

```text
公开
可复现
对所有算法采用公平规则
```

---

# 63. Preprocessing

例如：

```text
normalize
transpose
delta
shuffle
byte shuffle
scale
cast
remove NaN
```

必须明确属于：

```text
algorithm intrinsic
还是
external preprocessing
```

并统一计量。

---

# 64. Parameter Tuning

如果算法需要调参：

```text
compression level
block size
error tolerance
dictionary size
predictor order
```

必须定义：

```text
default track
tuned track
```

不得给某算法手工精调而其他算法只用默认参数，然后宣称算法优劣。

---

# 65. Cross-Platform 验证

至少推荐：

```text
Linux x86_64
Linux AArch64
```

如有条件：

```text
Windows x64
macOS ARM64
```

---

# 66. Serialization 的平台独立性

必须验证：

```text
encode on x86
decode on ARM

encode on ARM
decode on x86
```

对 P3 级实现应成为正式测试。

---

# 67. C ABI 与 C++ ABI

若 benchmark 动态加载算法插件，推荐：

```text
稳定 C ABI
内部可用 C++
```

例如：

```cpp
extern "C" {
    codec_handle* codec_create(...);
    codec_status codec_compress(...);
    void codec_destroy(...);
}
```

避免跨编译器 C++ ABI 差异。

---

# 68. 版本兼容

格式版本和实现版本必须区分：

```text
codec_implementation_version
bitstream_format_version
benchmark_adapter_version
```

三者不可混为一谈。

---

# 69. 错误处理

统一状态：

```text
INVALID_ARGUMENT
UNSUPPORTED
OUT_OF_MEMORY
OUTPUT_TOO_SMALL
CORRUPT_STREAM
CHECKSUM_ERROR
VERSION_ERROR
DICTIONARY_ERROR
NUMERIC_ERROR
INTERNAL_ERROR
```

禁止：

```text
返回 -1 但不知道为什么
```

---

# 70. 日志

Benchmark hot path 禁止 logging。

错误和 debug 日志必须：

```text
可关闭
不影响 benchmark
```

---

# 71. Global State

禁止算法依赖：

```text
global mutable singleton
environment variable without recording
current locale
current rounding mode without setting
random seed without recording
wall-clock time
```

---

# 72. Randomness

如果算法使用随机过程：

```text
sampling
dictionary training
random projection
initialization
```

必须记录：

```text
PRNG algorithm
seed
version
```

Benchmark 默认应 deterministic。

---

# 73. Locale

字符串配置解析不得受 locale 隐式影响：

```text
1.5
1,5
```

必须采用明确规则。

---

# 74. File I/O

默认 codec kernel Benchmark SHOULD 不包含文件 I/O。

若评估 end-to-end file compression，则单独报告：

```text
read
compress
write
read compressed
decompress
```

---

# 75. Checksum

Checksum 的性能开销必须明确：

```text
checksum enabled
checksum disabled
```

不能不同算法配置不同却不标注。

---

# 76. Reference Implementation 保留规则

参考实现 MUST：

```text
固定版本
保存 commit
禁止被优化版覆盖
```

它的作用是：

```text
oracle
```

不是 benchmark contender。

---

# 77. Canonical Scalar 的原则

canonical scalar SHOULD：

```text
代码清晰
无 architecture intrinsic
无并行
无 fast-math
少模板魔法
中间状态易观察
```

即：

> 优先可审计性，而非极限速度。

---

# 78. Optimization Patch Rule

任何优化 PR 必须回答：

```text
优化了什么？
理论上为什么更快？
有没有改变算法语义？
有没有改变内存？
有没有改变 bitstream？
有没有改变误差？
benchmark 是否显著？
```

---

# 79. 优化不得与算法修改混在一个 PR

例如禁止一个 PR 同时：

```text
rewrite predictor
+
change quantizer
+
add AVX2
+
change bitstream
```

应该拆分。

否则 regression 无法定位。

---

# 80. Code Review 最小检查

Reviewer 必须检查：

```text
integer width
overflow
shift
signedness
endian
bit order
bounds
alignment
aliasing
FP precision
rounding
FMA
state reset
block boundary
metadata size
decoder validation
license
```

---

# 81. 规范化规则编号建议

项目可以将规则细化为：

```text
PORT-xxx   总体迁移
SRC-xxx    来源
INT-xxx    整数
BIT-xxx    位操作
END-xxx    端序
MEM-xxx    内存
BUF-xxx    缓冲区
FP-xxx     浮点
ROUND-xxx  舍入
LOSSY-xxx  有损
LOSSLESS-xxx 无损
STATE-xxx  状态
API-xxx    接口
SIMD-xxx   SIMD
THREAD-xxx 并行
TEST-xxx   测试
BENCH-xxx  Benchmark
SEC-xxx    安全
LIC-xxx    许可证
CI-xxx     CI
```

---

# 82. 项目级硬约束

以下建议直接作为 MUST：

### PORT-001
禁止未经说明改变论文/参考实现的数学定义。

### PORT-002
第一版 C/C++ 必须先实现 scalar canonical version。

### PORT-003
canonical correctness 未通过前禁止性能优化进入主分支。

### PORT-004
任何行为差异都必须进入 porting report。

### INT-001
所有 serialized integer 必须有明确 bit width。

### INT-002
禁止依赖 signed overflow。

### BIT-001
所有 shift count 必须合法。

### END-001
bitstream 禁止依赖 host native endian。

### BITSTREAM-001
bit order 必须显式定义。

### MEM-001
禁止未验证 alignment/aliasing 的 pointer punning。

### LOSSY-001
有损算法必须明确 error mode。

### ROUND-001
有损 quantizer 必须明确 rounding semantics。

### FP-001
canonical build 禁止默认 fast-math。

### STATE-001
block/chunk/reset/state semantics 必须固定。

### TEST-001
original/reference implementation 必须保留作为 oracle。

### TEST-002
无损必须 round-trip。

### TEST-003
有损必须验证正式 error contract。

### TEST-004
decoder 必须测试 malformed input。

### BENCH-001
compressed size 必须包括必需 metadata。

### BENCH-002
压缩与解压吞吐必须分别报告。

### BENCH-003
线程数、ISA、compiler flags 必须记录。

### LIC-001
必须记录原始代码许可证及来源。

---

# 83. CI Pipeline 建议

```text
PR
│
├─ format
├─ compile
│  ├─ GCC
│  └─ Clang
├─ warnings
├─ unit
├─ golden
├─ roundtrip
├─ differential
├─ ASan
├─ UBSan
├─ static analysis
├─ fuzz smoke
├─ cross-platform
└─ benchmark smoke
```

Nightly：

```text
full differential
large datasets
TSan
long fuzz
performance regression
memory regression
cross-ISA
```

---

# 84. Performance Regression Gate

每个 algorithm/variant 维护 baseline：

```text
compression throughput
decompression throughput
compressed size
workspace
peak memory
```

如果 PR 导致：

```text
> X% throughput regression
或
> Y% size regression
```

必须人工审核。

阈值由项目统一定义，不建议算法各自定义。

---

# 85. Correctness 优先于性能

以下情况必须阻止合入：

```text
快 30%
但偶尔违反 error bound
```

```text
快 15%
但 sanitizer 报 UB
```

```text
压缩率更高
但 decoder 无法兼容格式
```

```text
速度更快
但改变了 block reset
```

因为这些不是“优化”，而是“算法/语义改变”。

---

# 86. License 与来源管理

每个算法至少记录：

```yaml
source_url:
source_commit:
source_tag:
paper_doi:
original_author:
original_language:
license:
spdx_identifier:
port_type:
  - clean_reimplementation
  - translated
  - modified_source
```

---

## LIC-002：不得认为“改成 C++ 就不受原许可证约束”

语言转换本身不会自动消除原代码的版权/许可证问题。

---

## LIC-003：区分“参考论文独立实现”和“源码翻译”

这两者必须在 metadata 中明确。

---

## LIC-004：SPDX identifier SHOULD 用标准名称

例如：

```text
MIT
BSD-3-Clause
Apache-2.0
GPL-3.0-only
GPL-3.0-or-later
```

---

# 87. Security Threat Model

Decoder 输入视为攻击者可控。

需要防：

```text
integer overflow
buffer overflow
out-of-bounds read
infinite loop
stack exhaustion
allocation bomb
decompression bomb
malformed Huffman tree
invalid offset
corrupted block table
oversized metadata
```

---

# 88. Resource Limit

Decoder SHOULD 支持：

```text
max_output_bytes
max_blocks
max_dictionary_bytes
max_metadata_bytes
max_tree_nodes
```

避免不受限分配。

---

# 89. Decompression Bomb

如果 frame 声明：

```text
compressed = 1 KB
uncompressed = 1 TB
```

必须在分配前检查用户/benchmark 设置的最大输出。

---

# 90. CMake / Build System

推荐：

```text
core
algorithms
adapters
tests
benchmarks
```

分 target。

canonical 和 optimized variant 应为独立 target，方便不同 flags：

```cmake
codec_scalar
codec_avx2
codec_neon
```

不要给整个工程全局加：

```text
-march=native
-ffast-math
```

---

# 91. 第三方库隔离

第三方：

```text
zstd
lz4
boost
eigen
...
```

必须通过明确 dependency boundary。

记录：

```text
version
build options
license
```

---

# 92. 自研算法和第三方 wrapper 必须区分

Benchmark 中：

```text
native upstream implementation
```

和：

```text
our C++ reimplementation
```

必须有不同 algorithm/implementation ID。

否则无法判断性能来源。

---

# 93. Implementation Identity

建议：

```text
algorithm_id = delta_rle
implementation_id = canonical_cpp
variant = scalar
```

另一个：

```text
algorithm_id = delta_rle
implementation_id = optimized_cpp
variant = avx2
```

---

# 94. Benchmark 结果 Schema

建议：

```json
{
  "algorithm_id": "...",
  "implementation_id": "...",
  "variant": "...",
  "dataset_id": "...",
  "dtype": "...",
  "shape": [],
  "input_bytes": 0,
  "compressed_bytes": 0,
  "compression_ratio": 0,
  "compression_time_ns": 0,
  "decompression_time_ns": 0,
  "compression_throughput_mib_s": 0,
  "decompression_throughput_mib_s": 0,
  "workspace_bytes": 0,
  "threads_used": 1,
  "isa_used": "...",
  "compiler": "...",
  "compiler_version": "...",
  "flags": [],
  "correctness": true,
  "error_metrics": {}
}
```

---

# 95. Porting Report 模板

```markdown
# <Algorithm> Porting Report

## 1. Source
## 2. Paper
## 3. Version
## 4. License
## 5. Original Language
## 6. Porting Level
## 7. Algorithm Contract
## 8. Integer Semantics
## 9. Floating Semantics
## 10. Rounding
## 11. Data Layout
## 12. State / Block
## 13. Bitstream
## 14. Known Differences
## 15. Golden Vectors
## 16. Differential Results
## 17. Sanitizer Results
## 18. Cross-platform Results
## 19. Performance
## 20. Remaining Risks
```

---

# 96. 单算法验收 Checklist

## 来源

- [ ] 论文确认
- [ ] 原仓库确认
- [ ] commit/tag 固定
- [ ] license 确认
- [ ] SPDX 确认
- [ ] port type 确认

## Contract

- [ ] 输入 dtype
- [ ] shape
- [ ] layout
- [ ] block size
- [ ] state
- [ ] error mode
- [ ] bitstream
- [ ] endian
- [ ] bit order
- [ ] special values

## Integer

- [ ] 所有固定宽度类型审核
- [ ] signed overflow 审核
- [ ] shift 审核
- [ ] narrowing 审核
- [ ] size arithmetic 审核

## Floating

- [ ] float/double 审核
- [ ] rounding 审核
- [ ] FMA 审核
- [ ] NaN/Inf 审核
- [ ] subnormal 审核
- [ ] fast-math 禁用

## Memory

- [ ] alignment
- [ ] aliasing
- [ ] lifetime
- [ ] capacity
- [ ] workspace
- [ ] allocation

## Correctness

- [ ] unit
- [ ] golden
- [ ] roundtrip
- [ ] differential
- [ ] cross-decode
- [ ] malformed
- [ ] ASan
- [ ] UBSan
- [ ] fuzz

## Performance

- [ ] warmup
- [ ] repetition
- [ ] compression throughput
- [ ] decompression throughput
- [ ] compressed bytes
- [ ] workspace
- [ ] compiler flags
- [ ] ISA
- [ ] threads

---

# 97. PR 模板建议

```markdown
## Algorithm
<name>

## Change Type
- [ ] Canonical correctness
- [ ] Bug fix
- [ ] Bitstream
- [ ] Optimization
- [ ] SIMD
- [ ] Parallel
- [ ] Benchmark adapter

## Semantic Changes
None / Describe

## Bitstream Changes
None / Describe

## Error-bound Changes
None / Describe

## Tests
- [ ] unit
- [ ] golden
- [ ] differential
- [ ] sanitizer
- [ ] cross-platform

## Performance
Before:
After:

## Risk
...
```

---

# 98. 推荐的实施顺序

对大量算法，不建议随机开工。

建议先做基础设施：

```text
1. DType
2. Buffer/View
3. Checked arithmetic
4. Endian helpers
5. BitReader/BitWriter
6. Varint/ZigZag
7. ErrorSpec
8. Codec API
9. Test harness
10. Benchmark harness
```

然后选 3–5 个代表算法打通：

```text
简单无损
LZ 类
预测 + entropy
简单有损 quantization
复杂有损
```

确认框架稳定后再批量扩展。

---

# 99. 不建议的开发方式

## 错误方式 A

```text
把 Python 全翻成 C++
↓
能编译
↓
跑几个数据
↓
开始 AVX
```

问题：

```text
缺少 semantic oracle
```

---

## 错误方式 B

```text
一开始追求最快
```

结果可能：

```text
不知道性能来自算法还是优化技巧
```

---

## 错误方式 C

```text
所有算法都强行套相同 chunk
```

会破坏：

```text
dictionary
predictor
state
```

---

## 错误方式 D

```text
只验证 decompress(compress(x)) == x
```

如果 encoder 和 decoder 同时犯相同错误，也可能“通过”。

---

## 错误方式 E

```text
只比较 compressed bytes
```

对合法但非唯一编码可能造成误判。

---

# 100. 典型 Bug 示例

## Case 1：Python → C++ rounding

Python：

```python
q = round(r / eb)
```

错误：

```cpp
auto q = std::round(r / eb);
```

结果：

```text
tie point symbol 变化
```

---

## Case 2：Java hash → C++

Java：

```java
int h = x * 0x9E3779B9;
```

错误：

```cpp
int32_t h = x * 0x9E3779B9;
```

原因：

```text
Java wrap
vs
C++ signed overflow UB
```

---

## Case 3：MATLAB → C++

MATLAB：

```text
column-major
```

C++ 代码按：

```text
row-major
```

线性扫描。

结果：

```text
预测邻接关系变化
```

甚至算法已经不同。

---

## Case 4：native endian

```cpp
fwrite(&header, sizeof(header), 1, f);
```

x86 工作。

换 CPU 后格式损坏。

---

## Case 5：错误 benchmark

算法 A：

```text
preallocate workspace
```

算法 B：

```text
每次 encode malloc
```

如果时间边界不一致，结果不具可比性。

---

# 101. 推荐的核心公共组件

```text
core/
├── checked_math.hpp
├── types.hpp
├── status.hpp
├── buffer.hpp
├── endian.hpp
├── bit_reader.hpp
├── bit_writer.hpp
├── varint.hpp
├── zigzag.hpp
├── fp_policy.hpp
├── error_spec.hpp
├── workspace.hpp
├── codec.hpp
└── validation/
```

原则：

> 将最容易出错的底层行为集中实现一次，而不是让每个算法重复写。

---

# 102. `checked_math.hpp` 应负责

```text
checked_add
checked_sub
checked_mul
checked_cast
```

目的：

```text
避免 size overflow
避免隐式 narrowing
```

---

# 103. `endian.hpp` 应负责

```text
load16_le/be
load32_le/be
load64_le/be
store16_le/be
store32_le/be
store64_le/be
```

---

# 104. `bit_writer.hpp` 应负责

```text
write_bit
write_bits
align_byte
flush
capacity
bytes_written
```

并规定：

```text
bit numbering
bit order
overflow behavior
```

---

# 105. `fp_policy.hpp`

建议：

```cpp
struct FloatingPolicy {
    PrecisionMode precision;
    RoundingMode rounding;
    FmaMode fma;
    SpecialValuePolicy special;
};
```

---

# 106. Debug Instrumentation

canonical 实现可以加入：

```text
dump_predictor
dump_residual
dump_quantized_symbol
dump_code_length
dump_block_header
```

用于 differential testing。

Release 时编译关闭。

---

# 107. 中间状态 checksum

大量数据时不必保存全部 trace。

可以对每阶段计算：

```text
hash(predictions)
hash(residuals)
hash(symbols)
hash(bitstream)
```

快速找到第一个 divergence stage。

---

# 108. 大规模批量迁移管理

建议维护总表：

| Algorithm | Source | License | Contract | Scalar | Diff | Sanitizer | Benchmark | SIMD | Status |
|---|---|---|---|---|---|---|---|---|---|

状态：

```text
DISCOVERED
CONTRACTING
PORTING
VALIDATING
BENCH_READY
OPTIMIZING
DONE
BLOCKED
```

---

# 109. Definition of Done

一个算法只有全部满足以下条件才是 DONE：

```text
来源明确
合同冻结
canonical 完成
correctness 通过
sanitizer 通过
benchmark adapter 通过
结果可复现
license 完成
文档完成
```

“能编译”不等于完成。

“能解压”不等于完成。

“速度快”不等于完成。

---

# 110. Exception / Waiver 流程

如果必须违反规范：

```text
Rule ID:
Reason:
Affected Algorithm:
Semantic Impact:
Portability Impact:
Benchmark Impact:
Security Impact:
Tests Added:
Approver:
Expiration:
```

禁止口头豁免。

---

# 111. 最终原则

整个项目必须坚持下面的层次：

```text
论文/标准
↓
算法语义
↓
数值语义
↓
状态语义
↓
bitstream
↓
C/C++ object/memory semantics
↓
correctness
↓
benchmark integration
↓
optimization
↓
hardware specialization
```

不能倒过来。

最危险的工程模式是：

```text
先优化
↓
能跑
↓
结果差不多
↓
认为正确
```

正确模式应是：

```text
先定义
↓
先冻结语义
↓
先建立 oracle
↓
先写 scalar
↓
逐层验证
↓
再优化
↓
优化后重新验证
```

---

# 112. 推荐参考资料

以下资料应作为本项目底层规则的外部参考。

## C/C++ 整数与对象模型

- cppreference, fixed-width integers  
  https://en.cppreference.com/cpp/types/integer

- cppreference, object model / strict aliasing / alignment  
  https://en.cppreference.com/cpp/language/object

- cppreference, `memcpy`  
  https://en.cppreference.com/c/string/byte/memcpy

## 浮点与编译器

- GCC Optimize Options  
  https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html

- Clang Compiler User's Manual — Floating Point Behavior  
  https://clang.llvm.org/docs/UsersManual.html

- C++ `std::round`  
  https://en.cppreference.com/cpp/numeric/math/round

- C++ `std::nearbyint`  
  https://en.cppreference.com/cpp/numeric/math/nearbyint

## Sanitizers

- AddressSanitizer  
  https://clang.llvm.org/docs/AddressSanitizer.html

- UndefinedBehaviorSanitizer  
  https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html

- ThreadSanitizer  
  https://clang.llvm.org/docs/ThreadSanitizer.html

## 压缩格式

- RFC 1951 — DEFLATE  
  https://www.rfc-editor.org/rfc/rfc1951

- RFC 8878 — Zstandard  
  https://www.rfc-editor.org/rfc/rfc8878

- LZ4 Frame Format  
  https://github.com/lz4/lz4/blob/dev/doc/lz4_Frame_format.md

## 有损压缩

- zfp Documentation  
  https://zfp.readthedocs.io/

- SZ3  
  https://szcompressor.org/

## Benchmark

- Google Benchmark User Guide  
  https://github.com/google/benchmark/blob/main/docs/user_guide.md

## 并行

- OpenMP Specifications  
  https://www.openmp.org/specifications/

## 源语言行为

- Python built-in functions (`round`)  
  https://docs.python.org/3/library/functions.html

- Python built-in numeric types  
  https://docs.python.org/3/library/stdtypes.html

- Rust Reference — Integer Overflow  
  https://doc.rust-lang.org/reference/behavior-not-considered-unsafe.html

- Java Language Specification  
  https://docs.oracle.com/javase/specs/

- MATLAB Row/Column Major Layout  
  https://www.mathworks.com/help/coder/ug/what-are-column-major-and-row-major-representation-1.html

- MATLAB `round`  
  https://www.mathworks.com/help/matlab/ref/double.round.html

## License

- SPDX License List  
  https://spdx.org/licenses/

- GNU GPL FAQ  
  https://www.gnu.org/licenses/gpl-faq.html

---

# Appendix A：强制规则快速表

| Rule | Requirement |
|---|---|
| PORT-001 | 不得未经说明改变算法数学定义 |
| PORT-002 | 第一版必须先有 canonical scalar |
| PORT-003 | correctness 通过前不得进入正式优化 |
| SRC-001 | 必须固定 reference source + commit |
| SRC-002 | 必须记录 license |
| INT-001 | serialized integer 固定宽度 |
| INT-002 | 禁止依赖 signed overflow |
| INT-003 | size arithmetic 必须 checked |
| BIT-001 | shift count 必须合法 |
| END-001 | bitstream 禁止 native endian |
| BITSTREAM-001 | bit order 必须显式 |
| MEM-001 | 禁止不安全 pointer punning |
| MEM-002 | alignment 必须显式 |
| BUF-001 | encoder 必须有 worst-case capacity |
| DEC-001 | decoder 必须验证所有长度 |
| DEC-002 | decoder 必须验证所有 offset |
| FP-001 | canonical 禁止默认 fast-math |
| ROUND-001 | rounding semantics 必须声明 |
| FMA-001 | FMA policy 必须固定 |
| SPECIAL-001 | NaN/Inf/±0 policy 必须声明 |
| STATE-001 | block/chunk/reset semantics 必须固定 |
| LOSSLESS-001 | 无损必须 bit-exact reconstruction |
| LOSSY-001 | 有损必须定义 error mode |
| LOSSY-VAL-001 | 必须验证正式误差约束 |
| SIMD-001 | SIMD 不得改变算法语义 |
| THREAD-001 | 线程数必须记录 |
| TEST-001 | reference implementation 必须保留 |
| TEST-002 | 必须 golden + differential |
| TEST-003 | decoder 必须 malformed-input test |
| SAN-001 | canonical 必须 ASan/UBSan |
| BENCH-001 | metadata 必须计入 compressed bytes |
| BENCH-002 | encode/decode throughput 分开报告 |
| BENCH-003 | compiler/ISA/thread 必须记录 |
| LIC-001 | 许可证与来源必须可追踪 |

---

# Appendix B：开发者开始实现前的 20 个问题

开发者在写第一行 C/C++ kernel 前，必须能够回答：

1. 原始算法的唯一可信来源是什么？
2. 当前参考代码对应哪个 commit/version？
3. 算法是有损还是无损？
4. 输入数据真实 dtype 是什么？
5. 数组是 row-major 还是 column-major？
6. 参考语言整数是否可能 overflow？
7. overflow 的原始语义是什么？
8. shift 的原始语义是什么？
9. predictor 的边界样本如何处理？
10. block 之间是否共享状态？
11. dictionary 是否跨 block？
12. bitstream byte order 是什么？
13. bitstream bit order 是什么？
14. 是否有 format version？
15. rounding rule 是什么？
16. floating precision 是什么？
17. FMA 是否影响结果？
18. NaN/Inf/-0 怎么处理？
19. correctness oracle 是什么？
20. 什么条件才能说明“该 C/C++ 重写完成”？

如果这 20 个问题有任何一个无法回答，应优先补充 Algorithm Contract，而不是继续编码。

---

# Appendix C：推荐团队口令

项目中建议形成统一工程习惯：

> **没有 Contract，不移植。**  
> **没有 Oracle，不优化。**  
> **没有 Differential Test，不宣称等价。**  
> **没有 Sanitizer，不宣称安全。**  
> **没有环境记录，不比较性能。**  
> **没有许可证记录，不合并源码。**

