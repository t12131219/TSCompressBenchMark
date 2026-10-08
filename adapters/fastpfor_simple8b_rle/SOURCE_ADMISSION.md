# FastPFOR Simple8b_RLE 源码准入

当前已通过 **build-only 补丁后的合法 uint32 对象源码 API 和有界 C ABI 范围**。
Python SDK、注册、合成uint32五层与正式重复已通过，第148条完整资格为 false。
三档真实共享库功能、系统坏输入、guard page及同发布object的fault均已执行，
独立native审计PASS，详见 `contract.md`。原生范围不替代SDK或五层资格。

## 来源与 benchmark 提取决定

清单“全量审计”第148条，worksheet row154，来源 TimeStanp-Compress row60。
仓库 `https://github.com/fast-pack/FastPFOR`，固定 commit
`2457e1ed1af35bbf7f4c509c863fa9797e637cb3`，Apache-2.0 / RUN_ALLOWED。
原 `_repos` 保持 clean、只读；九个算法文件和七个 benchmark/test 参考文件
逐一核对固定 Git bytes，保存为 `SOURCE_LOCK.json`，vendor 不施加补丁。

`sprintz-lzbench` 的固定 commit
`580c4f085381f31b1ad669525ed04e63cbc385f3` 带有 RLE header 和内部 factory
注册，但没有独立 lzbench RLE 入口。其 `bits()` 使用 population count，
清单版本使用 bit length，因此实际编码选择不同：三个 `1 << 20`，清单版
输出一个 RLE word，benchmark 副本输出两个 packing words。
两份原 encoder 各九组实际比较及原文件、命令、二进制和 diff 保留于
`build/source-audits/fastpfor-simple8b-rle-provenance-2/`。
继续以清单版本为算法身份，记录有差异的 benchmark 参考，不直接替换版本。

它是 uint32 primitive，不是 Timescale Simple8b-RLE，不隐含 Delta/ZigZag。
上游 `inmemorybenchmark.cpp` 调用 `Delta::process`，相关预处理只作为显式
pipeline 行为参考，不能给本 primitive 自动提供 timestamp 或 float 能力。

## 原 API 与实际失败

保留 `Simple8b_RLE<false/true>::encodeArray/decodeArray`，使用原
`Simple8b_Codec::Compress/Decompress`。selector1–14 为 packing，selector15
为32-bit value 加28-bit count的 RLE，selector0 为 EOS；encoder 不产生 EOS。
mark_length=true 在 payload 前放一个 uint32 count，false 依赖外部 count。

已实际复现原 API 的三个问题：marked returned count 漏掉开头一个 word；
N=1 的 unrolled decoder 覆盖七个 tail canaries，精确 output 触发 ASan
heap-buffer-overflow；marked payload 的4-byte偏移触发 UBSan 未对齐访问。
原 decoder 还忽略 compressed length，encoder 忽略 capacity；错误的 RLE
count、EOS、截断、无效尾部等需由后续有界 ABI 在 source 调用前检查。
原 API 的 uint32 输入/输出必须对齐，不声明外部 byte-misaligned 支持。

完整原 FastPFOR `src/unit.cpp` / unfiltered factory 的既有 release/assertions
执行已重新独立审计有效，其中包含五个 RLE 大 Zipfian 场景，源码闭包55文件。
这是源码自测证据复用，没有复用过期的 SDK 或五层执行记录。
原自测预留1024个元素，不能证明精确容量或尾部安全。
`unittest/test_simple8b.cpp` 测试的是 Simple8b，不代替 RLE 自测。

## Build-only 修复与实际验证

`patches/0001-complete-length-word-access-and-tail.patch` 的 SHA-256：
`5629cfc08ac5adc416679f8f80552ef02a1337c7e35dc52dc4a8b0854a9bade7`。
只改变四处：packed uint64 load/store 使用 memcpy；只有完整八值组进入
unrolled loop；marked 返回长度包含 marker。selector 表、RLE 选择、位布局
和序列化 bytes 保持原算法行为。返回长度合同的缺陷被显式修正。
`PATCH_LOCK.json` 保存原/改 header、补丁和生成器 hash；补丁实际应用于
`build/source-audits/fastpfor-simple8b-rle-source-20261007-1/generated/`。

独立逐 bit wire oracle 覆盖 uint32 widths0–32，89种长度（含0–64全量、
各 tail 和多块边界、4095/4096/4097），六种 pattern，两种 marker 配置，
两个 uint32-aligned offsets；所有15种可编码 selector 均实际覆盖。

- 原 release/debug encoder 合计140,976次 wire 检查通过，不授予原 decoder安全。
- 补丁 release/debug/ASan+UBSan 合计211,464次 wire、inverse、返回长度、
  input immutability 与 canary 检查通过。
- 三档合计4,788次精确容量、只读输入与 trailing guard-page 往返通过，
  不依赖未序列化 padding。
- 补丁后的完整 original unit 和 unfiltered factory 重新实际运行通过；
  原九个有效 objects 复用，`codecfactory.cpp` 以实际补丁 header 重新编译，
  编译闭包、对象、link命令和全部运行结果冻结。完整 unit 只在 release/
  assertions-enabled 跑过，不宣称整个 factory 的 sanitizer 资格。

使用 `detect_leaks=0`，无 LeakSanitizer 资格声明。源码失败记录、原始与
修复后的执行记录均保留，不重写或覆盖历史结果。

`tools/audit_fastpfor_simple8b_rle_source.py` 独立审计 PASS，核对源文件/许可证/
原 benchmark 差异、四处补丁、完整编译/运行宇宙、实际 compiler closure、
二进制 sanitizer symbols、raw/nested observations、原失败与完整 unit objects。
证据为 `build/source-audits/fastpfor_simple8b_rle_source_current_audit.json` 和
上述 source execution 目录的 `report.json`。

## 有界 C ABI 范围资格

沿用编号2的真实共享库和发布shim.o，未重新改动kernel或封装源码。
CPU2 release/debug/ASan+UBSan均实际执行以下场景并通过独立审计：

- 既有80,784个共享库功能场景证据保持有效；新增105,732个功能场景，
  使用89种长度、33种位宽、六种pattern和两个marker；外部四种byte offset
  按场景对循环分配，不宣称新增矩阵是四种offset的笛卡尔积。
- 106,359个坏码流/全截断场景，包含有效checksum下的非法EOS、RLE count、
  count marker、word geometry、unused bits及uint32域；拒绝前不调用原decoder。
- 7,128个leading/trailing guard-page精确容量场景，输入只读，
  覆盖空对象、packing tail、RLE、多块和4095/4096/4097。
- 474个descriptor、alias、资源限制、reset/update/finalize场景。
- 102个同发布object的allocation/clock/source API fault，验证原子失败、
  重试、真实调用计时、异常/坏时钟不可用。source API强符号替换仅供fault测试；
  普通功能测试不含FastPFOR类或vtable，实际链接发布shared library。

新driver、命令、测试源快照、compiler/runtime闭包与产物hash保存在
`build/source-audits/fastpfor-simple8b-rle-native-{safety,faults}-20261007-1/`。
`tools/audit_fastpfor_simple8b_rle_native.py`独立核对源码范围、三档build、
实际发布库/object、完整测试宇宙、原始observations、flags、symbols和闭包。
当前审计为`build/source-audits/fastpfor_simple8b_rle_native_current_audit.json`。
使用detect_leaks=0，无LeakSanitizer资格声明。

## SDK、注册和五层实际执行

实际SDK：466 passed、零skip，87个实际导入项目Python文件及源码快照冻结在
`build/source-audits/fastpfor-simple8b-rle-sdk-20261007-1/`，独立SDK审计PASS。
`registry/codecs/fastpfor-simple8b-rle-u32.json`登记完整uint32 VALUE/UTS scalar
primitive，无隐式Delta/ZigZag或dtype转换。源码artifact为
`v2:source-artifact:sha256:9abca09936b172fb697105687fa64b10edf334b2bbc9646c1d64d1c422ce2473`。

五层资格 `20261007-2` 四个marker/timer配置均PASS，ETTh1 VALUE/TIMESTAMP
八个能力不匹配任务均UNSUPPORTED。CPU0串行正式20次/配置，共80次：
74次有效，6次检测到swap后保留并排除；每组至少10次有效，完整统计审计PASS。
`tools/audit_fastpfor_simple8b_rle_run.py`独立核对完整wire、descriptor、RLE账本、
canonical bytes、fresh解码、计时和allocation/copy遥测、拒绝路径、原始报告与统计。
实际执行及独立审计路径见 `contract.md`；编号1五层报告保留为历史版本。

修改公共factory前已冻结LittleIntPacker120个原执行所消费的文件及审计结果，位于
`build/source-audits/littleintpacker-before-rle-sdk-20261007-1/`。已重新实际运行
499-case SDK和90-record五层资格，正式重测单独推进，不重hash旧报告。
第148条完整资格仍=false，其他数据集和数据域仍待验证。
