# WaLLoC native 格式与状态

所有整数为小端，张量为 IEEE754 float32。版本未知、字段溢出、截断、额外字节、非有限模型、重复/缺失/形状不符的参数均拒绝。输入 tensor 上限 64M elements，模型 256MiB，frame 512MiB；推理/训练估算工作集上限 2GiB/3GiB。配置上限见 contract；失败使用 C++ exception，CLI 非零退出。

WLFRA001 是新自包含格式，未宣称兼容上游裸 WebP。

| offset | size | 字段 |
|---|---|---|
| 0 | 8 | ASCII WLFRA001 |
| 8 | 4 | version=1 |
| 12 | 4 | encode profile：0 CPU，1 CUDA |
| 16 | 8 | 原始长度 L |
| 24 | 8 | 零填充长度 P=ceil(L/65536)*65536 |
| 32 | 8 | 未填充 latent 长度 Z=P/(2^J)+2 |
| 40 | 8 | 完整 neutral model 字节 M |
| 48 | 8 | WebP payload 字节 S |
| 56 | M | WLMOD001 model |
| 56+M | S | lossless RGB WebP |
| 56+M+S | 4 | CRC32 IEEE，覆盖前面全部字节 |

空帧 L=P=Z=S=0，仍携带完整模型。metadata 固定 60 字节。profile 标记编码数值后端；decoder 设备显式由调用方指定，跨设备不承诺相同 float32 输出。length 和模型不是隐式外部依赖。损坏输入拒绝；CRC 不是防恶意篡改的密码认证。

WLMOD001：8 字节 magic，8 个 uint32 配置依次为 channels、J、Ne、Nd、latent_dim、bits、lightweight、post_filter；随后 uint32 entry count。每项为 uint32 name bytes、UTF8 name、uint32 rank、rank 个 uint64 dimensions、uint64 payload bytes、contiguous float32 payload。张量名称及形状必须完整对应配置图，包括 wt/iwt filters 和 weight_norm 的 g/v。模型不含执行图或 pickle。

WLTRN001：8 字节 magic、uint64 model size、完整 WLMOD001、uint64 optimizer updates；依次 moment1、moment2、accumulated gradient 三张表，各含 uint32 count 和上述 named tensor 项；uint32 CPU RNG bytes 及 state，uint32 device RNG bytes 及 state；最终 CRC32。恢复检查模型/参数/optimizer 结构与完整状态；`train_continue` 恢复 handle 的 RNG，`train_replay` 接收锁定后端原版 RNG 用于差分验证。

Schedule 是独立公开 C++ 值对象，调度参数、scheduler_step、bad_epochs、best、has_best、current_lr 均可保存/恢复；WLTRN001 仅存 Codec 状态，调用方须另外持久化 Schedule、外部数据游标与 crop/mix 选择，不能把模型 checkpoint 当成整个训练作业 checkpoint。

`encode` 接收单对象 C,L，模型内 channels 固定；`evaluate/train` 接收 B,C,L。WebP 仅允许 latent_dim=3*n*n，裸 tensor API 没有该容器限制。latent 零填充到 128，转换为 offset uint8 后 RGB tile；质量80、method4、lossless1、exact0、threads0，解码完整验证零 padding 和尺寸。
