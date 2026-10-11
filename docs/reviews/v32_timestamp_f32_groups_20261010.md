# V3.2 原始时间戳与派生 f32 冻结组

日期：2026-10-10。只使用当前 33 活动入口；未新增算法。工具：
`tools/build_v32_timestamp_f32_bundles.py`。默认基于原始 byte 共同组 v3 的测量合同、
协议和公共 CPU / 内存预算派生新的独立 GroupSpec，不修改原组或其证据。

| 冻结组 | bundle | 全部单元 | 核心单元 | 核心入口 / 等价类 | 独立真实来源 |
|---|---|---:|---:|---:|---:|
| G-TIMESTAMP | `configs/comparisons/g-timestamp-v32-20261010-v1.json` | 40 | 32 | 8 / 7 | 2 |
| G-FLOAT-LL-F32 | `configs/comparisons/g-float-ll-f32-v32-20261010-v1.json` | 40 | 32 | 8 / 8 | 2 |

当前生成的全部新 canonical source manifest 使用 `tscb.dataset-content.v2`；
source payload、准备后工件、逻辑身份、父 source ID 与原文件 SHA 保留。
工具遇到相同路径的不同内容即拒绝覆盖。

## 原始 T 任务

ETTh1 / Weather 各取事前冻结的 `[0,4096)` 和 `[4096,8192)` 两个窗口。
T 必须来自源 CSV 的实际时间列；保留解析后的 int64 值、顺序、unit、epoch 和
`SOURCE_COLUMN` origin，不排序、不基准平移、不构造规则采样 T。
两个窗口仍是同一个来源独立单元，四个 workload 不冒充四个来源。

现 canonical 容器要求至少一个 value column，因而工件保留第一列实际值作为 carrier。
该列明确位于 TIMESTAMP 任务外；route、输入 raw bits 和计时对象只包含原始 T。
carrier 没有被算入 T 压缩分母，亦未代替缺失 T。

核心保留全部 8 个当前 TIMESTAMP byte 入口：LZ4、Zstandard、Snappy、DEFLATE、Brotli、
xz 和两个 LZSS 实现。两个 LZSS 入口来源/执行身份独立，但在本 byte 任务采用保守共同
`lzss-family` 方法等价类，共计 7 类；不凭实现数增加不同方法数。
结论仅限这些完整 byte 方案，不声称已接入专用 delta / delta-of-delta 时间戳方法。

独立合成 VALIDATION 包括 regular、jitter、duplicate、out-of-order 四个 T pattern，
pilot 另用固定种子的独立 jitter 对象。普通 preflight 的现有 boundary suite 还覆盖
negative delta、large gap、int64 extreme epochs 与 capacity-minus-one 原子拒绝。
边界清单是待运行合同；未运行部分不据此称安全 PASS。

另保留 1 个缺失必需 T 的 TEST extension fixture × 8 入口，共 8 个 REJECT 单元。
期望为 `CAPABILITY_MISMATCH` / `INPUT_NEGOTIATION`，缺少 T 不构造 fake 输入。
原先 prepare 在 route 阶段抛出 `TIMESTAMP_UNAVAILABLE`，已由主流程修复为未路由身份，
明确 `actual_input_observed=false`、`input_sha256=null`；普通 preflight 对不合法 task
返回原输入准入拒绝，不执行编码器。

## 派生 f32 任务

静态检查发现当前 8 个专用无损入口已经声明 f32：ALP、ALP-RD、Chimp、Chimp128、
Elf、Elf+、Elf*、SElf*；不必只用两个 byte 参考凑本组方法数。LZ4 / Zstandard 是参考。
三个有界 f32 入口 Serf QT、Serf XOR 和 zfp 不进入这个无损组。

ETTh1 / Weather 各取前 8192 行、前 1 / 4 列，产生 UTS / MTS 共四个 workload。
原始源为 f64，f32 明确是 IEEE 转换后的新 typed ground truth；记录发生数值舍入的
parent 元素数与转换规则。组内 LOSSLESS 验证恢复派生 f32 位，不声称恢复原始 f64。
父对象、原始域有损任务和当前派生无损任务保持不同身份。

资格沿固定 constant / linear / periodic / random f32 patterns，pilot 为独立随机对象；
同一 v2 logical policy 对 TEST 与 VALIDATION 内容重算，检查不重叠。
ALP 的 SOURCE_REJECT_RAW 路径沿既有显式完整方案合同，不扩展 ALP 原生域，也不把 raw
分支计作原生 ALP 成功。

## 已验证范围

两个 bundle 已完成 full matrix compile，分别规划 320 trials。开发计划：
`/tmp/tscb-v32-t-f32-plan/timestamp-v1-dev2` 与 `f32-v1-dev`。
T-v1 同冻结 resume plan 成功；对 8 个不合法 T task 的普通 preflight 均得到预期拒绝，
同时核验未提交 codec 输入身份和空 hash。该只读准入检查没有测量 codec 性能。

独立检查逐对象重新加载真实父数据，核验 T payload / unit / epoch 原样保留、f32 payload
等于声明的父窗口转换、所有新 manifest 使用 v2 身份、TEST / VALIDATION 逻辑内容不重叠。
相关工具的 Ruff 检查通过。本轮合法核心 encode / decode、完整成本、spawn recovery、pilot
和 FORMAL 仍必须在统一源码 / native build 冻结后执行，当前不签署组完成。

```bash
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/build_v32_timestamp_f32_bundles.py --groups timestamp f32 --revision 1
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python -m tscompbench \
  --dataset-manifest-root registry/comparison_datasets/v32_20261010 \
  comparison plan configs/comparisons/g-timestamp-v32-20261010-v1.json \
  --output-root /tmp/tscb-v32-plan --run-set-id timestamp-development
```

正式 RunSet 要求新路径，并顺序执行 qualify、pilot、formal、无新增 trial resume 和 report。
活动入口的 SDK 刷新后映射见 `docs/reviews/v32_active_stage_role_ledger_20261010-v4.json` / `.md`：
10 个冻结组涉及 28 个活动入口，其余 5 个保留共同组与方法等价关系待冻结条件。
166 条候选与旧 163 条 scope 的完整版本 provenance 保留，长期多数候选集成完成状态仍为 false。
