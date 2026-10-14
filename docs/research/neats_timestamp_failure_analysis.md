# NeaTS / LeaTS 时间戳正确性失败分析

`runs/timestamps-20261013` 的 exact qualification 保存了两个真实失败：`neats-lossless-i64` 和 `leats-lossless-i64` 均为 `status=error, reason=bitwise_mismatch`。本分析只读取保留的 frame、实验记录和源码，用 Python 标准库解析序列化字段及计算源码预测公式；未编译、调用 native decoder、运行测试或 benchmark。完整身份和证据 SHA-256 见 [机器记录](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/neats_timestamp_failure_analysis.json)。

输入为 `records.npz` 中的 `T`，dtype 为 `<i8`，257 个元素，范围 `0..15_360_000_000_000 ns`，通常每步 `60_000_000_000 ns`，第 5 点重复。这里没有 epoch 偏移。两个 frame 均保存 `bias=0`；跨度远小于 `INT64_MAX`，满足 shim 的 signed 64-bit normalization 条件。

## 保存的 frame 证明

两份对象的 payload SHA-256 均与 descriptor 一致，native frame FNV 校验也一致。按实际 SDSL header 和 Elias–Fano 格式解析后，两个成员保存了相同的三段 linear 模型：

| 起始下标 | float32 斜率 | float64 截距 | 残差位数 |
|---:|---:|---:|---:|
| 0 | 60,000,002,048 | -60,000,000,000 | 0 |
| 5 | 120,000,004,096 | 120,000,000,000 | 0 |
| 7 | 60,000,002,048 | 360,000,000,000 | 0 |

序列化的 `residuals_bit_size=0`，每段 residual offset 也是 0。源码使用 `ceil(a * (j + 1 - start) + b)`，且 0 位残差不提供任何修正。第一点因此恢复为 `ceil(60_000_002_048 - 60_000_000_000)=2048`，原值为 0。纯公式重构的 257 个元素全部不一致，最大绝对误差为 **512,000 ns**；末点恢复 `15_360_000_512_000`，原值为 `15_360_000_000_000`。这是保存的系数与解码公式的直接结果，与 benchmark 的 bitwise failure 一致。

## 原因与修复边界

shim 的模板为 `compressor<uint32_t, int64_t, double, float, double>`。`float_pfa.hpp` 的 `create_fun` 从 double polygon 取斜率并转换为 `T1=float`；DP 根据 fitting epsilon 选择 residual 位数。随后两个成员的 `make_residuals` 没有检查保存精度下的实际预测是否仍落入所选 correction 范围。这里 fitting 选择 0 位，但系数量化已经引入误差，最终没有保存这些误差。

`max_bpc=32` 扩展 DP 候选上限，仍允许选择 0 位，因此单纯增大参数不能保证修复。将 `T1` 改为 double 可以处理此数据中可精确表示的斜率，但会改变实现及序列化布局，也不能据此宣称任意 int64 均可无损恢复。

完整修复需要对实际 decoder 预测重新校验：0 位必须逐点精确；`bpc>0` 时须保证 `error + 2^(bpc-1)` 落在 `[0, 2^bpc-1]`，使用不溢出的整数运算。若超过配置上限，需要经过验证的拆分／重拟合，或在输出成功 frame 前明确拒绝真实编码域限制。还应校验非有限／超出 int64 范围的预测，重算实际 residual 位数与 offsets，并用新 build 身份验证完整 bitwise 与独立 decoder。原始失败不能改写为 `unsupported`。

## 资格范围

之前保存的 834 个成功案例是其各自记录范围内的结果；NeaTS / LeaTS 的 integer grid 仅使用小幅整数，没有覆盖此大整数跨度、epoch 或完整 int64 极值。后续资格需覆盖实际时间戳、正负大 offset、小／大跨度、int64 常数与边缘值，以及超过 signed normalization span 的明确拒绝。此处还没有应用任何修复或执行新的 native 资格。

可审阅的原始记录为 [observations.jsonl](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/timestamps-20261013/observations.jsonl)、[manifest.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/timestamps-20261013/manifest.json)，以及 [NeaTS frame](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/timestamps-20261013/artifacts/c85615765ca27d5a09661d1f4ef7923e55aff2fcaf20cc3430cdd5f9c28af63a.tsb) 和 [LeaTS frame](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/timestamps-20261013/artifacts/1c55e79c0b3e3cee81a73bd146cc8b88348b1a2301c8b520d7da5ef6a6eeb7cf.tsb)。
