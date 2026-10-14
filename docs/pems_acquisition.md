# PeMS 精确获取与校验

[fetch_pems.py](../benchmark/tools/fetch_pems.py) 提供标准库 `fetch`／`verify` 入口，读取[冻结准备文件](../benchmark/experiments/pems-values/preparation.json)中的四个固定作者 URL、字节数和 SHA-256。没有原始数据打包，也不安装软件。`--directory` 必须由调用者指定，`--manifest` 必须是新的 JSONL 文件路径。所有下载、失败和校验发生在正式 benchmark 计时之外。

作者仓库是 `guoshnBJTU/ASTGNN`，固定 ref 为 `9c2e19b98c4cedf1f35214d8789685b6381b3aad`。下载 URL 使用 `https://raw.githubusercontent.com/guoshnBJTU/ASTGNN/<ref>/data/PEMSxx/PEMSxx.npz`，由准备文件精确读取；本地文件名保持下表的大小写。工具固定准备文件的 SHA-256 为 `25382f5ef6de5e91a97e05f720b1b4c1043a38e31622e09e4ecd17d07131178b`。`--preparation` 允许重定位同一文件，任何字节改变都拒绝，不能通过修改 expected hash 接受新数据。

| Dataset ID | 本地文件名 | 期望字节数 | 期望 SHA-256 |
|---|---|---:|---|
| pems03 | PEMS03.npz | 15800415 | `34859517425eded66a0014db63de54b95d0428c38890741a1710ed4d3b043de8` |
| pems04 | pems04.npz | 32956284 | `95a3c9b720fffdb85f0330d09bfab41b0b3cad0ca86c0d7d5f3accacb4ac999a` |
| pems07 | PEMS07.npz | 43705518 | `a07887e610aa986276209bc9384d14ed7858fdcad1ded67f53dca19eb828600b` |
| pems08 | pems08.npz | 18525419 | `e1d03ce74e9fb79149e6e7c37c680214822c4a285baa2f42278cacabcd25c075` |

四个文件总计 110987636 bytes。初次获取整个固定集合，在项目根目录执行（替换原始数据目录）：

```bash
python benchmark/tools/fetch_pems.py fetch \
  --directory /path/to/raw-pems \
  --manifest acquisition/pems-fetch-20261013.jsonl
```

已有本地文件可以只校验，不发出 HTTP 请求：

```bash
python benchmark/tools/fetch_pems.py verify \
  --directory /home/fzg/PycharmProjects/材料/TSBench_Corpus \
  --manifest acquisition/pems-verify-20261013.jsonl
```

可重复传入 `--dataset pems03` 等参数选择固定集合的子集。`fetch` 遇到已有文件只校验；长度或 SHA 不符会失败，保留原文件，不重取覆盖。源文件位置若是符号链接或目录也会拒绝。读取已有文件后再次比较 fd 和路径的 device／inode／size／mtime／ctime；读取期间替换路径或原地改写也会拒绝。校验成功只对应最终检查前观察到的文件，不承诺之后没有其他写入者。清单已有时，命令在获取前退出并要求新路径。全部所选源成功返回 0；获取、校验或中断失败返回 1，参数错误返回 2。`--timeout` 是每次阻塞网络操作的超时，不声明整个获取过程的总时限。

下载流最多读取期望长度加一字节，实际读取字节数和 SHA 是验收依据，HTTP `Content-Length` 仅记录。短流、错误 SHA、超长流、HTTP 拒绝和网络中断都不能安装。数据先暂存到目标同目录，长度和 SHA 均匹配后，通过不覆盖目标的 atomic hard link 发布；若另一写入者抢先创建目标，安装失败并保留该目标。通常错误或中断会清除本次临时文件，不修改源身份或原有数据。

JSONL 清单以 exclusive create 保留新路径，并使用 append、flush、fsync 保存起始、准备绑定、逐源开始、进度、逐源结束和总结果事件。失败仍记录固定 URL、expected hash、HTTP／异常及已观察字节。`streamed_sha256` 对应 `streamed_bytes` 个实际读取字节；超长或网络中断时只是读取前缀的 hash，不能解释为未读完整远程正文的 hash。突然终止只可能留下未完成事件，不能据此声称获取成功。既有清单不被替换。

该工具不解析 NPZ，也不进行 codec 内容资格验证。新机器获取后，应使用实际目标目录生成新实验准备，避免覆盖历史准备文件：

```bash
PYTHONPATH=benchmark/src python benchmark/tools/generate_pems.py \
  --corpus /path/to/raw-pems \
  --output benchmark/experiments/pems-replay \
  --run-root runs/pems-replay
```

新准备记录当前路径、运行环境和 cpu0 sysfs 缓存容量；如果固定 8192 行容量比较在新机器不成立，生成器会明确停止，需声明新的实验设计，不能把原机器的缓存容量套给新机器。正式执行仍需选择实际 build root、独立 run output 并完成资格验证。获取器始终使用上面的原始冻结 source evidence；新生成的不同准备文件不自动成为它的 expected identities。

17 项 focused tests 使用本地几字节内容与模拟 HTTP 响应，验证长度、污染、超长、部分传输、HTTP 失败、安装竞争、原文件保留、读取期间原地修改／路径替换、清单不可覆盖、准备文件污染及 HTTPS 降级拒绝。本轮没有用新获取器下载远程四份 NPZ；网络可达性和实际下载成功应以未来新清单为准。此前的[来源研究](research/additional_data_sources.md)建立了已有本地文件与作者固定 Git blob SHA-1／长度的身份关联，未重算远程完整 NPZ SHA-256。

[持久化的小数据 CLI 故障证据](research/pems_acquisition_faults/README.md)保存 12 byte 污染 fixture、缺失文件失败、重复清单拒绝、原始 append ledger、真实 stdout／stderr、代码快照和 JSON hash 引用。临时路径与事件保持原样，没有把复制后的证据重写成新的获取过程。

精确作者预处理文件的许可、特征单位及提取／插补历史仍未知。作者仓库无已确立的数据专用 LICENSE，Caltrans 的有条件一般网页政策不能赋予这些加工文件新的许可。代码与说明只给出来源、获取路线和校验身份，不捆绑或声明这些数据可再分发。
