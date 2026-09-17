# TSBench中C/C++ Benchmark算法分析

## 一、主要C/C++ Benchmarks概览

TSBench共包含**11个主要的C/C++ Benchmark**,按代码规模排序:

| Benchmark | C/C++文件数 | 主要语言 | 类别 |
|-----------|------------|---------|------|
| **AMD_Xilinx_Vitis_Data_Compression** | 5,363 | C/C++ | FPGA/HLS压缩库 |
| **lzbench** | 2,552 | C/C++ | 通用无损压缩benchmark |
| **Serf** | 902 | C/C++ | 误差有界浮点压缩 |
| **NeaTS** | 754 | C++ | 神经网络自适应压缩 |
| **zfp** | 533 | C | 科学浮点压缩 |
| **ALP_FastLanes** | 409 | C++ | ALP压缩生态 |
| **Data-Stream-Compression** | 345 | C/C++ | 综合时序压缩实现 |
| **Sprintz** | 308 | C/C++ | Sprintz预测编码 |
| **FiniteStateEntropy** | 37 | C | FSE/Huff0熵编码 |
| **Intel_QAT_QATzip** | 24 | C | Intel硬件加速压缩 |
| **TerseTS** | 3 | Rust(少量C) | 统一时序压缩框架 |

---

## 二、lzbench包含的算法详细列表

**lzbench**是最全面的通用无损压缩benchmark,包含**60+种压缩算法**:

### 2.1 与Excel表格对应的算法

#### 通用字典压缩(General Dictionary Coding)
- ✅ **LZ77** - 通过zlib实现
- ✅ **LZSS** - 已集成
- ✅ **DEFLATE** - 通过zlib、libdeflate实现
- ✅ **LZ4 / LZ4HC** - lz4 v1.10.0
- ✅ **Snappy** - snappy v1.2.2
- ✅ **Zstandard (Zstd)** - zstd v1.5.7
- ✅ **Brotli** - brotli v1.2.0
- ✅ **LZMA / xz** - xz v5.8.3, lzma v26.01

#### LZ系列变体
- **LZAV** - lzav 5.16
- **LZF** - lzf 3.6
- **LZFSE/LZVN** - Apple的lzfse v1.0
- **LZG** - liblzg v1.0.10
- **LZHAM** - lzham v1.0
- **LZJB** - 2010版本
- **Lizard** - v2.1 (LZ4/LZ5的改进)
- **LZO系列** - lzo1/1a/1b/1c/1f/1x/1y/1z/2a (v2.10)
- **LZSSE2/4/8** - 2019版本(SSE4.1优化)

#### 熵编码类
- ✅ **BZ2 (Huffman Coding)** - bzip2 v1.0.8
- **BZ3** - bzip3 v1.5.3
- **BSC** - libbsc v3.3.12

#### 其他通用压缩
- **FastLZ** - v0.5.0
- **Fast-LZMA2** - v1.0.1
- **Kanzi** - v2.5.3
- **PPMD8** - v26.01
- **QuickLZ** - v1.5.1
- **SLZ** - v1.2.2
- **Tornado** - v0.6a
- **UCL** - v1.03
- **Zlib-NG** - v2.3.3
- **Zling** - 2018版本
- **ZPAQ** - v7.15
- **多种实验性算法** (aceapex, brieflz, crush, density等)

### 2.2 lzbench覆盖的Excel算法统计

**Value-Compress表中覆盖的算法:**
- 通用字典压缩: 8/8 (100%)
  - LZ77 ✅
  - LZSS ✅
  - DEFLATE ✅
  - LZ4 ✅
  - Snappy ✅
  - Zstd ✅
  - Brotli ✅
  - LZMA/xz ✅

---

## 三、AMD_Xilinx_Vitis_Data_Compression包含的算法

根据metadata和官方文档,该库提供**FPGA硬件加速**实现:

### 3.1 与Excel表格对应的算法

#### 通用字典压缩(FPGA实现)
- ✅ **LZ4** - HLS优化版本
- ✅ **Snappy** - FPGA实现
- ✅ **DEFLATE (GZip)** - 硬件加速
- ✅ **Zstandard (Zstd)** - FPGA版本

### 3.2 特点
- 所有算法均为**FPGA/HLS (High-Level Synthesis)** C/C++实现
- 提供硬件加速的压缩/解压缩
- 支持流式处理
- 官方文档: https://docs.amd.com/r/2024.1-English/Vitis_Libraries/data_compression/benchmark.html_3_0
- **注意**: 从2025.2版本起该PL(Programmable Logic)子库不再维护

---

## 四、其他C/C++ Benchmarks算法对应

### 4.1 FiniteStateEntropy
**熵编码专用库**

与Excel对应:
- ✅ **Huff0** - Huffman的快速变体
- ✅ **FSE (Finite State Entropy)** - tANS实现

### 4.2 Sprintz
**预测编码benchmark**

与Excel对应:
- ✅ **Sprintz-Delta** - 一阶差分+预测
- ✅ **Sprintz-FIRE** - Fast Integer REcoding

### 4.3 Serf
**误差有界浮点压缩**

与Excel对应:
- ✅ **Serf-Qt** - 量化+变换
- ✅ **Serf-XOR** - XOR编码

### 4.4 zfp
**科学计算浮点压缩**

与Excel对应:
- ✅ **zfp** - 误差有界压缩算法

### 4.5 ALP_FastLanes
**列式数据库压缩**

与Excel对应:
- ✅ **ALP** - Adaptive Lossless floating-Point
- ✅ **ALP_RD** - ALP with dictionary
- ✅ **FastLanes** - SIMD向量化框架

### 4.6 NeaTS
**神经网络压缩**

与Excel对应:
- ✅ **NeaTS** - Neural adaptive time-series compression
- ✅ **LeaTS** - Learned time-series compression

### 4.7 Intel_QAT_QATzip
**Intel硬件加速**

与Excel对应:
- ✅ **Intel QAT/QATzip** - Quick Assist Technology硬件加速

### 4.8 Data-Stream-Compression
**综合时序压缩集合**

包含多种经典算法的C++实现,具体需查看仓库详情。

---

## 五、总结对比表

### 5.1 lzbench vs Excel算法对应

| Excel分类 | 算法名称 | lzbench支持 | 版本/实现 |
|----------|---------|------------|----------|
| 通用字典压缩 | LZ77 | ✅ | zlib |
| 通用字典压缩 | LZSS | ✅ | 独立实现 |
| 通用字典压缩 | DEFLATE | ✅ | zlib/libdeflate |
| 通用字典压缩 | LZ4 | ✅ | v1.10.0 |
| 通用字典压缩 | Snappy | ✅ | v1.2.2 |
| 通用字典压缩 | Zstd | ✅ | v1.5.7 |
| 通用字典压缩 | Brotli | ✅ | v1.2.0 |
| 通用字典压缩 | LZMA/xz | ✅ | v5.8.3 |
| 预测编码 | Sprintz-Delta | ❌ | 在独立Sprintz仓库 |
| 预测编码 | Sprintz-FIRE | ❌ | 在独立Sprintz仓库 |
| 熵编码 | Huffman | ✅ | bzip2 |
| 熵编码 | FSE | ❌ | 在FiniteStateEntropy仓库 |
| 熵编码 | Huff0 | ❌ | 在FiniteStateEntropy仓库 |

**lzbench覆盖率**: Value-Compress表中通用压缩算法的 **8/8 (100%)**

### 5.2 AMD_Xilinx vs Excel算法对应

| Excel分类 | 算法名称 | AMD_Xilinx支持 | 实现类型 |
|----------|---------|----------------|---------|
| 通用字典压缩 | LZ4 | ✅ | FPGA/HLS |
| 通用字典压缩 | Snappy | ✅ | FPGA/HLS |
| 通用字典压缩 | DEFLATE(GZip) | ✅ | FPGA/HLS |
| 通用字典压缩 | Zstd | ✅ | FPGA/HLS |
| 硬件加速 | AMD/Xilinx Vitis | ✅ | 原生实现 |

**AMD_Xilinx覆盖率**: 硬件加速通用压缩算法 **4/4 (100%)**

### 5.3 所有C/C++ Benchmarks总覆盖统计

**Excel "Value-Compress"表(89个算法)中已覆盖:**

| 类别 | 覆盖算法数 | 主要Benchmark |
|-----|----------|--------------|
| 通用字典压缩 | 8/8 | lzbench, AMD_Xilinx |
| 预测编码 | 2 (Sprintz系列) | Sprintz |
| 熵编码 | 2 (FSE, Huff0) | FiniteStateEntropy |
| 浮点压缩 | 4 (zfp, Serf, ALP系列) | zfp, Serf, ALP_FastLanes |
| 神经网络压缩 | 2 (NeaTS, LeaTS) | NeaTS |
| 硬件加速 | 2类 (FPGA, QAT) | AMD_Xilinx, Intel_QAT |

**总计约**: **20-25个算法** 有完整的C/C++实现

---

## 六、推荐使用策略

### 6.1 通用压缩算法测试
**首选**: **lzbench**
- 最全面的通用压缩benchmark
- 统一测试框架
- 支持60+种算法
- 自动化性能对比

### 6.2 时序数据专用压缩
**分散在多个仓库**:
- **Sprintz**: 预测编码
- **Serf**: 浮点误差有界
- **NeaTS**: 神经网络压缩
- **Data-Stream-Compression**: 综合时序算法

### 6.3 硬件加速测试
- **FPGA**: AMD_Xilinx_Vitis_Data_Compression
- **Intel QAT**: Intel_QAT_QATzip

### 6.4 熵编码专项
- **FiniteStateEntropy**: FSE/Huff0参考实现

---

## 七、与Excel表格的对应关系汇总

**"第一步实现的算法.xlsx"** 中列出的算法在TSBench C/C++ Benchmarks中的分布:

### Value-Compress表 (89个算法)
- **通用字典压缩** (8个): 完全覆盖 ✅ (lzbench)
- **时序模式字典** (3个): 部分覆盖 (CORAD、TRISTAN需查看其他仓库)
- **预测编码** (4个): Sprintz系列完全覆盖 ✅
- **熵编码** (9个): FSE/Huff0覆盖 ✅,其他需补充
- **浮点压缩** (7个): zfp/Serf/ALP覆盖 ✅
- **神经网络** (4个): NeaTS/LeaTS覆盖 ✅
- **硬件加速** (3个): AMD/Intel覆盖 ✅

### TimeStamp-Compress表 (110个算法)
TSBench主要focus在Value压缩,时间戳压缩算法需要在:
- IoTDB
- InfluxDB  
- TimescaleDB
- ClickHouse
等时序数据库源码中查找

---

**生成时间**: 2026-09-17
**数据来源**: TSBench metadata + lzbench README + 仓库分析
