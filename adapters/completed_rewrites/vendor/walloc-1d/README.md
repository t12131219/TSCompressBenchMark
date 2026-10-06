# WaLLoC-1D 独立 C++ 重写

当前状态以 `PORT_MANIFEST.yaml` 为准；只有 G0–G6、全部 18 项必需能力和独立发布审计通过，才是 `REWRITE_DONE`。

实现完整 Codec1D：periodized bior4.4 wavelet packet、轻量与 Oobleck 编码器、CDF/量化、Oobleck 解码器、可选后滤波、WebP 音频容器和自包含帧。训练包含原版 custom backward、随机瓶颈、两种损失、真实 AdamW 更新、累积梯度、学习率调度及模型/优化器/RNG 恢复。两套官方 stereo 模型均保留。

生产代码是独立翻译的 C++17 算法图；ATen/LibTorch 2.6.0+cu118 仅提供 native tensor/autograd primitives，libwebp 1.6.0 为锁定的原生容器依赖。生产不执行 Python、diffusers、pytorch_wavelets、TorchScript、ONNX 或原版导出执行图，不链接 libtorch_python。外部 native runtime 的精确文件与哈希见 `DEPENDENCY_LOCK.json`；解压发布包不会自动安装运行库。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DWALLOC_TORCH_ROOT=/tmp/tscb-terracodec-oracle/lib/python3.11/site-packages/torch \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda-11.8/bin/nvcc -DCUDAToolkit_ROOT=/usr/local/cuda-11.8
cmake --build build -j2
ctest --test-dir build --output-on-failure
```

依赖前缀应包含 `include/` 与 `lib/`，保持 ABI=0、锁定版本与 CUDA/cuDNN 配套库。完整构建还需要 CUDA11.8 toolkit/nvcc；CUDA_ARCHITECTURES=75，私有 sum kernel 不启用 fast-math/FMA。平台为 Linux x86_64，GPU 验证目标 RTX2070 sm75；未宣称 ARM、跨 GPU 位流一致或内部 GPU 并行吞吐。

```sh
build/walloc_cli encode models/stereo_5x.wlm \
  input-f32-planar.bin 2048 output.wlf cpu
build/walloc_cli decode output.wlf decoded.bin cpu
```

上例长度必须与所选输入的实际 `L` 一致，输入文件由调用方提供。输入/输出是小端 float32，布局 C,L；解码只读取完整帧和声明的 native runtime。选择 `cuda` 时 GPU 不可用会失败，不会静默回退 CPU。CPU 是单线程 numerical profile，依赖内部 SIMD/dispatch 如实保留，未声称逐指令 scalar。

API 为 `include/walloc.hpp`；`include/walloc_tensor.hpp` 额外提供设备驻留 ATen 张量、裸 wavelet/linear/uniform/quantized/decoder/post 阶段和损失，可跳过量化与 WebP 做压缩域计算。裸阶段为 inference，输入须是有限 float32 张量；返回值留在指定设备，不暗中转到 host。普通 API 检查有限值并返回 host snapshots。

训练广播梯度采用私有 CUDA sum primitive：原版 ATen2.6 归约模板只增加两处共享存储复用前的同步，归约算术/布局/次序不变，不覆盖全局 dispatch，也不修改外部库。Snake 与卷积偏置的广播梯度均接入；卷积前向保留原生无融合偏置加法。192 个形状/布局逐位对照、后滤波偏置前向逐位对照及四种 GPU sanitizer 证据见 `validation/reduction-v4/report.json`，完整网络还须通过最终安全报告。

首次调用前执行一次 `Codec::configure_cpu_threads(1)`，随后不要更改全局线程或 backend 设置。独立 handle 可并发；同 handle 串行化，共享训练 RNG 受锁保护，GPU graph 调用串行化以保持确定性。`Encoder` 的 bound/finalize 支持不足容量时不写、重复 finalize 和 reset，借用输入不会被修改。

初始化显式设置 oneDNN 和 cuDNN deterministic，cuDNN benchmark/TF32 关闭；不依赖未声明的 CPU 默认算法选择。生产 CUDA runtime 统一使用锁定的共享 libcudart，避免混入额外静态 runtime。重复构建采用 NVCC `--objdir-as-tempdir` 固定临时源名称，不通过事后删除诊断或改动产物字节伪造一致性。

这是有损音频语义：输出 clamp 到 [-.5,.5]，MSE 在未 clamp 的重建上计算。普通 framed API 接收已归一化输入；mean/max 归一化和四轨混合是显式工具，不自动拟合测试数据。原版 notebook 的模型/长度在 WebP 外，重写帧将全部 decoder 状态内嵌，`FinalBits = 8 × frame_bytes`，没有免费模型。源式裸 forward 对部分未对齐长度报错；framed pipeline 补零到 65536。空帧是明确的 native 安全扩展，不声称空输入原版一致。

见 `contract.md`、`format.md`、`validation_report.md` 和 `porting_report.md`。性能仅为 QUALIFICATION，不进入框架排名。30 epochs × 10000 steps 的收敛及 batch32/length524288 默认训练计划未在验收中跑完；完整网络实际更新和 batch32 短序列验证不能替代这些声明。

来源 danjacobellis/walloc commit `c75d1b05e03fd35f66f72fa6ae21d3bb51c2d7b2`，上游算法许可 `NOASSERTION`。本地重写按用户授权继续，见 `reproduction/USER_DECISIONS.md`（工作区原件 `../../USER_DECISIONS.md`）；不伪造上游许可授予。依赖原始 notices 保留在 LICENSES；不进行外部发布、adapter、registry 或 Benchmark 集成。
