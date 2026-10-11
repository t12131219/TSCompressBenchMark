# 独立 P2 bridge recipes（2026-10-10）

这两个 bridge 保持 `tscb.pipeline-recipe.v1` 和现有算法登记不变；它们是显式组合方案，拥有自己的 RecipeID、wire magic、输入域、恢复和账本。

`BYTE_TO_RADIX4` 将每个原始 `u8` 按 `6,4,2,0` 位拆为四个 `[0,3]` 的 `|u1` digit，记录真实 `4N` native 输入元素、mapping stage 的访问/分配诊断、真实 DeepZip 完整 frame（包括冻结 model 和 header），再按 digit 数量逆组装。源 DeepZip 仍只接受 alphabet=4 的 digit；对原始 byte 直接调用会保留 `MODEL_ALPHABET_UNSUPPORTED` 拒绝。`tests/unit/test_byte_symbol_bridge.py` 覆盖 0/1/2/B±1、0..255 全字节、截断/头部篡改、缺 child、spawn。

`SOURCE_REJECT_TO_RAW_BLOCK` 仅捕获 typed `SourceDomainError`，并在冻结块内选择 codec 或原始 byte block。OOM、capacity、build、配置、普通异常都继续失败。每个块保存 owner/column/start/count/dtype、input hash、child key/parameters、拒绝类型/原因、实际编码分支和 payload hash；失败尝试时钟在 execution evidence 中保存且不进入 wire，便于确定性码流和重复统计。全 RAW 结果标识 `COMPOSITE_RAW_ESCAPE`，不能改写 child 的 native PASS。RAW 选择仍承担真实 raw bytes 和 outer metadata 账本，CODEC 分支保存并重新验证实际 child recipe。真实 `/home/fzg/PycharmProjects/Compression_Rewrite/datasets/ETTh1.csv` 的 HUFL（17420 f64，完整 rowgroup）触发 ALP 的 `input rowgroup selects ALP_RD; forced ALP identity forbids fallback`，v2 bridge 用 1 个 RAW 块完成冷 spawn 可逆恢复；ETTh1 的 8192 行派生比较切片低于 ALP rowgroup，实际接受 ALP，不能伪造 raw rejection。

两种 bridge 都拒绝缺失 child、改变计数/dtype/order、伪造 child recipe、损坏 payload 和错误 identity。正式 compare/formal 仍需由独立 worker 记录 stage wall/cpu、resource lease、重复与 eligibility；这里的 measured mapping/attempt time 是控制面诊断。
