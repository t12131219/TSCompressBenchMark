# SIMDComp direct core开发记录

状态：2026-10-15，源码研究、入口和测试源码已写入；未执行构建、测试或正式测量。

现有C1入口用SBP1、每块目录、FNV校验、整份frame及typed staging复制。真实registry仅注册`simdcomp-u32`的PLAIN uint32路径：SSE4_1的LENGTH／MASKED／WITHOUTMASK，以及AVX2的MASKED／WITHOUTMASK；starting_point=0。未注册的D1／FOR不在本次参数扩展范围。

已完整阅读现有`tscb_simdcomp.c`、`avx2_bridge.c`、独立构建器、contract、公共SIMDComp API头、`simdcomputil.c`、Python C1配置分支与AVX2零宽补丁；定向逐行阅读生成源的shortlength／length pack与unpack、SSE与AVX2代表位宽、width=0／32、分派和尾处理。没有声称逐行读过所有自动生成位宽内核。

新core格式仅保存独立恢复必需信息：count u32 LE、profile u8（0=SSE128，1=AVX256），随后每块width u8与原native packed bytes。尾逻辑长度由count确定，AVX不足256尾使用SSE length API；不保存SBP1、校验或重复尺寸目录。width选择、tail处理与必要header序列化均在encode内。全部格式字节计入codec完整大小，不扩大uint32逻辑分母。

已新增独立baseline C++ TU `adapters/simdcomp/native/direct_core.cc`，已有AVX桥TU新增无timer的width／pack／unpack转发；仅AVX桥和原生AVX源使用AVX2编译选项。新入口直接读写caller buffer；非自然对齐时仅逐块使用context固定32-byte对齐工作区，不为常规对齐输入构造整份中间数组。decoder从frame恢复layout，参数为空。`tsbench_core_validate`在decode主时钟外核实全部块边界及无trailing bytes，`decode`按已验证不可变产物契约单遍调用native unpack，只保留必要头字段和caller容量检查；验证可在独立context进行，不缓存单一产物pointer。width=0没有payload，width=32使用native absolute uint32 bytes，其他尾块按照原生四lane规则计入全部padding字节。

新增`benchmark/tests/test_core_simdcomp.py`，使用中央构建产物验证五条已注册参数路径、0／32及中间位宽、0／1／127／128／129／255／256／257／513有效元素、空参数独立恢复、完整输出大小、输入保持原样、非自然对齐buffer、输出容量拒绝，以及错误count／profile／width、截断和多余尾字节在调用native unpack前拒绝。AVX2 LENGTH测试绕过Python约束，验证native同样返回unsupported。测试源码已经写入，按集成安排没有执行；正常CPU ISA缺失可明确skip，不能当作成功覆盖。

本次未修改冻结vendor。既有AVX2 width0 unpack补丁必须继续由统一构建应用，不能将其错误的256-byte清零恢复为原样。完整测试、统一构建及正式benchmark由root执行，结果待追加；当前`git diff --check`通过只说明补丁无空白错误。

统一storage声明同时补入：SIMDComp返回3（caller encode／decode），ABBA／fABBA／DeepZip／DZip返回0（owned vector encode／decode），Gorilla返回2（owned encode／caller decode）。driver据此避免对vector路径预留冗余caller输出；该构建／计量集成待中央验证。
