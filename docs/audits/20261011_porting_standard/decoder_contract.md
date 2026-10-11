# 当前 typed-byte 解码合同与修正

本轮只修正现有入口的框架恢复和失败合同，不改变原生压缩算法、合法编码位流或已退出范围。

## 分配前验证

`byte_container.py` 对 JSON 对象、重复键、元数据大小、基础数值 dtype、维数、每维尺寸、Python 整数乘积、可寻址 stride、名称唯一性、payload 长度与 logical bits 进行检查。所有依赖该层的解码器在 native 调用及输出分配之前执行验证。零字节 block-major 对象跳过按不可信巨大行数的遍历。

混合空／非空 buffer 的 block-major 对象先计算每个 buffer 的 row bytes，每块只处理非空 buffer，最后仍恢复空 buffer 的原 shape。这样空描述符数量不会乘上 block 数量放大恢复工作；231 项容器安全回归包含操作量边界和精确恢复测试。

六个一般字节入口（LZ4、Zstd、Snappy、Brotli、DEFLATE、XZ）和 LZSS 两入口使用默认 1 GiB 输出预算；直接 `decompress(..., max_output_bytes=...)` 可以传入另行预算的更大对象。元数据预算为 1 MiB。它们是框架解码资源政策，不能解释为上游算法值域限制。FSE/Huff0 保持登记的 128 KiB 限制。LZSS/FSE/Huff0 仍只接受原登记的基础数值 dtype，未扩大为 bool 输入。

## 原始对象恢复

buffer-major 和已声明 `BLOCK_MAJOR_BUFFER_ORDER` 分别恢复每个 buffer 的原 dtype、shape 与位模式。流式输出保存后，新 one-shot decoder 仅凭容器恢复混合字宽、IEEE 位模式、多 buffer 与最后不足整块的 tail。数组恢复后设为只读。

## 验证边界

恶意描述符测试使用没有 native handle 的 session，若触及 native 访问会产生 AttributeError；预期是提前抛出 ExecutionContractError。真实 mixed-buffer 流式恢复测试通过当前 factory 选择已登记工件，不依赖 encoder 的原数据。全量回归及当前入口资格另保存独立执行闭包。

这些测试证明所选恢复与拒绝合同，不证明全部上游能力、其他平台、无界流式内存或正式性能。
