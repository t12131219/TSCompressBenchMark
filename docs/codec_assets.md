# V4 native codec 接入资格（2026-10-13）


2026-10-22：新增 CAMEO/SIP、VW、PIP、TP、SWAB、Sim-Piece、PMC-Mean、connected SWING、DFT、正交 DCT-II 共10项 repaired-v1 接入；主core单列binary64、API/对象独立列、empirical_quality。当前53可用真实CPU codec（另有raw-store），LZSS两项继续排除；历史性能不改签。详见[接入报告](cameo_family_integration/README.md)及 `benchmark/examples/cameo-family.toml`。

2026-10-20当前接入：ABBA/fABBA旧vendor与RW分支已归档删除，三算法改用abba-family（新增qabba），见[接入报告](abba_family_integration/README.md)。下表及32 C1/4 RW、834通过等数字是2026-10-13历史资格，不能用于当前替换实现。

本轮从保留的 native/vendor/patch 源码构建36个真实成员；新 `tsbench` bridge 不导入或运行旧 `tscompbench`。资格结果仅覆盖下表记录的输入、配置、binary和bridge，不等同于upstream全域一致性。

独立 `encode` / `decode` 每次新建和销毁 C ABI context；RW API为无句柄操作。32个 C1 成员分别适配真实格式和Finish语义，4个RW成员按列显式封装完整native frames。native timer默认关闭；参数显式 `native_timing=true` 用于独立诊断。

## 构建与缓存

`tsbench build --all` 编译全部成员；缓存默认位于 `build/tsbench/<identity-sha>/<codec>/`，`<codec>.index.json`定位当前库。`build.json`记录真实编译命令、每TU `-MD` 源码/系统头文件闭包、编译器与工具链文件、动态运行依赖及binary SHA-256。缓存命中逐项验证闭包与运行依赖；依赖漂移试验确认重新编译后恢复原生成header，冻结源码资产未修改。

decoder只需要已安装library、codec card、build记录/index与动态runtime。factory核binary/runtime哈希，不触发编译，不读取源码或models。DeepZip/DZip在无adapters/source/models目录的临时安装root及独立进程中均完成bitwise恢复。

## 本轮验证范围

原始资格 grid 有834个通过案例、14个expected source rejection；该 grid 内无未解释失败。它不覆盖全 int64 极值/大跨度域，后续纳秒时间轴的 NeaTS／LeaTS [真实反例](research/neats_timestamp_failure_analysis.md)另行保留。包括每成员声明dtype的17/257样本、支持的3列矩阵与empty、字节codec的ND rank3/4、Sprintz有符号/高位极值bitpattern、SIMDComp五种合法ISA/API组合与0/17/127/128/129/255/256/257样本、DeepZip所有17 model_key的tiny输入，以及Serf/zfp实际绝对误差。ABBA/fABBA仅报告经验误差，不将其参数称为严格重构界。

| Codec | dtype | 通过 | 源域拒绝 | 本轮观察到的最大绝对误差 |
|---|---|---:|---:|---:|
| abba | <f8 | 3 | 0 | 0.600041789 |
| alp | <f8, <f4 | 8 | 0 | 0（bitwise） |
| alp-rd | <f8, <f4 | 8 | 0 | 0（bitwise） |
| brotli-stream | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| bzip2-stream | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| chimp | <f4, <f8 | 8 | 2 | 0（bitwise） |
| chimp128 | <f4, <f8 | 8 | 2 | 0（bitwise） |
| deepzip | |u1 | 21 | 1 | 0（bitwise） |
| deflate-zlib | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| dzip | |u1 | 5 | 1 | 0（bitwise） |
| elf | <f4, <f8 | 8 | 2 | 0（bitwise） |
| elf-plus | <f4, <f8 | 8 | 2 | 0（bitwise） |
| elf-star | <f4, <f8 | 8 | 2 | 0（bitwise） |
| fabba | <f8 | 3 | 0 | 0.503670288 |
| fse | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| huff0 | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| leats-lossless-i64 | |i1, <i2, <i4, <i8 | 14 | 0 | 0（bitwise） |
| lz4-frame | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| lzss-dipperstein-c | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| lzss-raw | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| lzsse2-raw | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| lzsse8-raw | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| neats-lossless-i64 | |i1, <i2, <i4, <i8 | 14 | 0 | 0（bitwise） |
| self-star | <f4, <f8 | 8 | 2 | 0（bitwise） |
| serf-qt | <f8, <f4 | 12 | 0 | 0.000998056432 |
| serf-xor | <f8, <f4 | 12 | 0 | 0.000998621807 |
| simdcomp-u32 | <u4 | 48 | 0 | 0（bitwise） |
| snappy-raw | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| sprintz-delta | |i1, |u1, <i2, <u2 | 24 | 0 | 0（bitwise） |
| sprintz-delta-u8 | |u1 | 4 | 0 | 0（bitwise） |
| sprintz-fire | |i1, |u1, <i2, <u2 | 24 | 0 | 0（bitwise） |
| sprintz-fire-huff0 | |i1, |u1, <i2, <u2 | 24 | 0 | 0（bitwise） |
| sprintz-fire-u8 | |u1 | 4 | 0 | 0（bitwise） |
| xz-stream | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |
| zfp-accuracy-1d | <f4, <f8 | 12 | 0 | 0.000444913012 |
| zstd-frame | <i8, <i4, <i2, |i1, <u8, <u4, <u2, |u1, <f8, <f4 | 42 | 0 | 0（bitwise） |

## 重放与证据

```bash
# 本机 Conda 运行库条件，须在 Python 启动前生效；其他机器按实际构建依赖选择。
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libstdc++.so.6 PYTHONPATH=benchmark/src python benchmark/tools/qualify_native_assets.py --output build/tsbench/native_qualification_replay.json
```

本地详细JSON：

- `build/tsbench/native_qualification.json`：每案例的实际输入和解码hash、shape/dtype/参数、完整payload字节数、误差与拒绝原因。
- `build/tsbench/wire_only_decoder.json`：DeepZip/DZip仅library+card的独立decoder证据。
- `build/tsbench/build_dependency_cache_audit.json`：真实编译依赖漂移缓存试验。

本轮保存结果不是性能测量；正式performance由独占worker执行并记录其实际边界、session/round和资格身份。native card中stream/query声明是资产能力，executor是否已经提供对应任务以实际executor capability为准。
