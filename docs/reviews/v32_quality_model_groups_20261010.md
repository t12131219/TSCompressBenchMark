# V3.2 G-QUALITY 与 G-BYTE-MODEL 冻结组

证据日期：2026-10-10。范围仅限已注册的现有压缩器；未新增算法。

## 冻结配置与分母

| 组 | 配置 | 核心方法 | 参考方法 | 真实来源 | 全部 / 核心单元 |
|---|---|---|---|---|---|
| G-QUALITY | `configs/comparisons/g-quality-v32-20261010-v5.json` | ABBA、fABBA | 无 | ETTh1、Weather | 24 / 24 |
| G-BYTE-MODEL | `configs/comparisons/g-byte-model-v32-20261010-v5.json` | DeepZip、DZip | LZ4、Zstandard | ETTh1、Weather | 16 / 8 |

`tools/build_v32_comparison_bundles.py` 通过现有 Registry 生成并编译两组。
v5 bundle、plan 和 provenance 均按不可覆盖规则生成；早期草案保留各自身份。
规划成功不等于资格或正式性能验收。

## G-QUALITY 的任务与质量

两个真实来源各取 UTS / MTS，共四个有限 f64 原始值对象，与浮点无损组使用相同对象。
两个方法各冻结三个点 `0.01`、`0.1`、`1`，采用 FULL_GRID，保留全部 24 个单元。
ABBA 的 compression / digitization tolerance 与 fABBA 的 tolerance / alpha 分别写入
MethodConfigMap，不假设同名数值参数具有相同精度含义。

全部配置声明 `UNBOUNDED_LOSSY` / `UNBOUNDED`，原始域质量以 RMSE 和 MaxAE 观察；
不将参数容差当作原域数学误差界。当前公共任务的 QUALITY_CURVE 资格规则不接纳 LOSSLESS
模式，因此本组没有加入不合法的无损参考项。常规浮点无损任务单独保留。

## G-BYTE-MODEL 的共同输入域

DeepZip 的冻结模型不接受任意 0–255 字节。共同任务使用合法的 `0,1,2,3` 符号域：
从 ETTh1 / Weather 的前 32 行、前 1 / 4 列得到 column-major little-endian f64 bytes，
再把每个 octet 按 MSB-first 分为四个二位符号。映射可逆并检查实际 payload。
四个比较对象是 `UINT8_BASE4_SYMBOL_STREAM`，其父数据的 hash、选择窗口、列顺序、序列化
规则和 payload hash 均保留；这一组不声称直接比较恢复原始 f64 的压缩成本。

资格和 pilot 使用固定的独立合成 VALIDATION 对象。TEST / VALIDATION 以同一 v2 logical
content policy 重算并检查不重叠，不用不同版本 hash 的差异替代逻辑内容隔离。
真实对象的相关 UTS / MTS 衍生流各自仍属于同一来源独立单元；两个来源仅证明此固定语料流程。

DeepZip 冻结权重、模型位置、参数、source artifact identity 进入 provenance。训练对象与
本地 TEST 的重叠未知，状态为 `UNKNOWN_FOR_FROZEN_DEEPZIP_MODEL_NO_GENERALIZATION_CLAIM`。
本组未训练共享模型、未按 TEST 选择超参，不作训练集无泄漏或泛化保证。
对象内在线适配的计算属于编码路径。

完整 native frame 中嵌入的模型字节计入 ValueBits；当前 opaque frame inspector 未进一步
分配 ModelBits。provenance 明确 `COMPLETE_EMBEDDED_NATIVE_MODEL_FRAMES_COUNTED_IN_VALUE_BITS`
及 `NOT_ALLOCATED_BY_CURRENT_OPAQUE_FRAME_INSPECTOR`，不能把 model_bits=0 解释为免费模型，
也不能把已经计费的嵌入模型再相加。

本组全体方法使用相同的 3 线程预算、CPU affinity `[0,2,4]`、8 GiB 请求内存、
900 秒单 trial / 7200 秒总 wall budget。协议固定 4 outer repetitions、最多 8 inner
iterations、3 次 pilot repeat。线程预算用于接纳 DZip 的固定后台 Eigen 池；执行前仍须
以实际线程高水位和 host resource lease 验收，冻结预算不是已观测的合规证据。

## 验证与执行状态

2026-10-10：bundle compile 与两条 CLI plan 均成功，G-QUALITY 规划 192 trials，
G-BYTE-MODEL 规划 64 trials。开发用 plan 位于
`/tmp/tscb-v32-quality-model-plan/{quality-v5-dev,model-v5-dev}`，不作为正式验收 RunSet。
这两组尚未取得本轮 qualify / pilot / formal 证据。

`tests/unit/test_v32_quality_model_bundles.py`、`test_v32_comparison_bundles.py` 与
`test_v32_active_entries.py` 合计 35 项测试通过；相关新增工具与测试的 Ruff 检查通过。
测试覆盖完整分母、同原始对象质量网格、共同模型 alphabet、实际父 payload 映射、全 octet
映射可逆性、同版本逻辑内容隔离、未知训练 provenance 和完整 frame 成本说明。

源码与 native build 闭包稳定后必须新建正式 RunSet。依次运行 qualify、pilot、formal，
随后无新增 trial 的 resume 与 report，核验原始证据 hash 和 analysis identity 不变。
host lease 只允许一组占用受控测量资源。

```bash
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/build_v32_comparison_bundles.py --groups quality --revision 5
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python \
  tools/build_v32_comparison_bundles.py --groups model --revision 5 --cpu-affinity 0 2 4
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python -m tscompbench \
  --dataset-manifest-root registry/comparison_datasets/v32_20261010 \
  comparison qualify configs/comparisons/g-quality-v32-20261010-v5.json \
  --output-root /tmp/tscb-v32-final --run-set-id quality-final
```

正式全阶段与续跑使用 `tools/run_v32_existing_comparison.py`；该工具验证并复用已有资格和
pilot，不因 `--resume` 重新测量它们。单阶段操作使用 `tools/run_v32_comparison.py`。
保持同 bundle、output-root、run-set-id；model 使用自己的新 RunSet。
若闭包漂移，保留既有证据并生成新执行身份，不覆盖旧 RunSet 或缩小分母。
