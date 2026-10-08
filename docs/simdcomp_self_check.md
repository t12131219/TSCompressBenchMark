# SIMDComp 接入自检（2026-10-07）

依据工程计划 7.2、7.6、8.3、11.5、13.3、20.3。对应工作簿“全量审计”
第 137 条 `SIMDComp`；完整工作清单仍保留 221 条逻辑条目与 115 个原生候选。

| 注册身份 | 分类 | 当前数据域 | 原始执行路径 |
| --- | --- | --- | --- |
| `simdcomp-u32` | P0 | VALUE/UTS `<u4` | SSE4.1 LENGTH/MASKED/WITHOUTMASK；AVX2 MASKED/WITHOUTMASK |
| `delta-simdcomp-u32` | P2 | VALUE/UTS `<u4` | SSE4.1 原始模 2^32 D1 + bitpacking |
| `for-simdcomp-u32` | P2 | VALUE/UTS `<u4` | SSE4.1 原始固定基值 FOR LENGTH/FULL + bitpacking |

三者拥有不同 AlgorithmID，共用同一 SourceArtifactID。原始源码为
`lemire/simdcomp@d5301778fe5045ca8099252de5a6ed8016a287df`，BSD-3-Clause。
27 个 vendor 文件与固定 Git tree 一致；四个补丁只应用于 build 副本，原版
SSE/AVX2 失败证据保留。FastPFOR SIMDBinaryPacking 的 API/格式不同，保留
参考记录，未替换本条目指定的原始实现。

## 验证结果

- 源码：SSE 三档原/补丁对照及独立 guard；AVX2 共 72 个程序，保留原版
  16 项失败，补丁版全部通过。
- 有界 ABI：六个主要程序各 31,878 个独立 wire 场景，合计 191,268 检查；
  fault injection、guard page、最小容量、alias、时钟失败与原子拒绝通过。
- SDK：888 项测试通过，无失败或跳过；实际导入的项目 Python 闭包为
  80 个文件。独立 auditor 核对 SDK/native/source 与复用 helper 的 hash。
- 框架接入：163 项测试通过。Pipeline A/B/D 独立验证 residual、inverse、
  width32 absolute 特例、lane words、padding 和容器；A/B 融合时间记 null。
- 证据：45 项测试通过（13 SDK、32 run），覆盖 SDK 闭包漂移、删除依赖后
  同步伪造摘要、正确 checksum 下的错误 payload/seed/descriptor、伪造不执行
  任务、raw/Coverage 和正式分位数、CI、CV 篡改。
- 接入清单：两个测试通过；当前源与旧算法证据有出入时保留重新验证状态。

## 五层资格

每种身份实际经过 Canonical Loader、能力协商/Task Matrix、Preflight、执行/
同轮 correctness 与 measurement、账本、raw CSV、统计过滤、Coverage 和报告。
支持 fixture 为已登记的 `streamvbyte_u32_uts`：8193 个全范围 uint32 值，不
把真实 float/int64 数据隐式转换为 uint32。拒绝矩阵使用实际 ETTh1 数据。

| 身份 | 资格任务 | PASS | SCHEMA_ERROR | 拒绝任务 | UNSUPPORTED | SCHEMA_ERROR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `simdcomp-u32` | 12 | 10 | 2 | 24 | 20 | 4 |
| `delta-simdcomp-u32` | 16 | 16 | 0 | 32 | 32 | 0 |
| `for-simdcomp-u32` | 16 | 16 | 0 | 32 | 32 | 0 |

非法 AVX2 LENGTH 配置提前产生 SCHEMA_ERROR。拒绝与非法配置均保留任务、
原因和 DIAGNOSTIC；没有伪造 stream、账本、计时或资格。QUALIFICATION
结果不参加正式性能排名。

独立运行 auditor 从实际 SBP1 的四/八 lane words 解码，未调用源码或阶段
validator。逐 byte 证明 fixture/canonical/stream 关系，并复核每个 ledger
组件、staging/copy、真实 full/tail API、native timer、raw CSV 与 Coverage。
证据入口为 `build/source-audits/<key_with_underscores>_qualification_current_audit.json`。

## 正式重复与剩余范围

当前正式组为 `runs/<key>-formal-20-20261007-1/`，由
`tools/qualify_simdcomp_benchmark.py` 在 CPU0 串行执行。固定单线程、每有效
配置 20 次、至少三次且 0.5 秒预热、每次编码和解码各至少一秒。原生计时
分别开/关；固定 seed0 正式测量，四种 seed 的执行与 wire 在资格组验证。
RESOURCE_PRESSURE 原样保留并排除，独立 audit 要求每配置至少 10 次 eligible。

三组正式运行已终态完成，独立五层审计全部 PASS：

| 身份 | 正式记录 | PASS / eligible | RESOURCE_PRESSURE | SCHEMA_ERROR |
| --- | ---: | ---: | ---: | ---: |
| `simdcomp-u32` | 202 | 198 | 2 | 2 |
| `delta-simdcomp-u32` | 80 | 78 | 2 | 0 |
| `for-simdcomp-u32` | 80 | 79 | 1 | 0 |

普通身份有 10 个合法配置，D1/FOR 各有 4 个；每个合法配置实际完成 20 次
重复，且各有至少 10 次 eligible。普通身份两个非法配置各保留一条诊断。
审计独立重算 raw/summary 的 median、分位数、SD/CV、bootstrap CI 和吞吐，
核对原生计时开关不改变码流及 formal/qualification 码流一致。
实际正式 driver 导入的框架闭包为 95 个文件，逐份核对当前 SHA-256；修复了
审计报告中 canonical 文件列表遮蔽框架依赖计数的问题。

最终证据为 `build/source-audits/{simdcomp_u32,delta_simdcomp_u32,for_simdcomp_u32}_five_layer_audit.json`。
接入清单将本范围标为 `UINT32_UTS_P0_P2_SIMDCOMP_SCOPE_QUALIFIED_INT64_OTHER_ISA_PENDING`。
本范围资格不能冒充整个逻辑条目完成。Checked int64 Timestamp、其他 ISA、
其他数据域与查询接入仍需各自实现和资格。

重现入口：

```bash
python tools/build_codec.py simdcomp-u32 --profile all
python tools/qualify_simdcomp_sdk.py
PYTHONPATH=src python tools/onboard_simdcomp.py
PYTHONPATH=src taskset -c 0 python tools/qualify_simdcomp_benchmark.py --run-suffix <new_suffix> --formal
PYTHONPATH=src taskset -c 2 python tools/audit_simdcomp_run.py <formal_run> <qualification_run> --key <key> --unsupported-run-set-id <unsupported_run>
```

重建或源码/框架依赖变更会使旧 hash 证据失效，须先刷新相应原生/SDK 资格、
注册闭包和新 run set，不能直接沿用旧正式排名。
