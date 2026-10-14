# PeMS 获取器的小数据故障证据

这里保存精确获取器的本地 CLI 故障验证，不是 PeMS 语料或 benchmark 性能数据。`polluted_fixture.bin` 只有 12 bytes（`polluted NPZ`），故意不满足任何 NPZ 身份；第二个请求的本地文件不存在。没有 HTTP 请求、真实源文件读取、NPZ 解析、codec 或正式计时。

`verify.jsonl` 是修复读取期间替换／改写检测后的真实 append ledger；`cli_results.json` 保存实际 argv、stdout／stderr、返回值和重复清单拒绝检查。第一次返回 1 并准确记录两个 source error；再次使用同清单返回 2，清单和污染文件均未修改。`fetch_pems_at_validation.py` 是该次 CLI 的代码快照，hash 与 ledger 起始事件相同。`earlier_verify.jsonl` 保留此前临时目录的历史 receipt，其原 script hash 和路径保持不变，未赋予新代码身份。

所有 ledger 的临时目录路径、inode、时间和原事件保持原样。持久化 fixture 只复制字节，并不把持久化位置伪装成当时执行位置。文件长度与 SHA 引用见 `references.json`；它也绑定当前 focused test 文件和原始冻结 preparation 的小文件 hash。17 项 focused tests 使用小数据与模拟响应，完整远程获取未在本轮执行。

工具的使用和获取语义见 [PeMS 获取说明](../../pems_acquisition.md)。历史 acquisition 失败不能视为当前 PeMS codec 性能实验失败，两者有独立的对象、入口和证据。
