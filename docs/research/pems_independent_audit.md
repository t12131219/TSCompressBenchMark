# PeMS 正式 run 独立只读审计

[manifest](../../runs/current-pems-20261013/pems-values/manifest.json)与[observations](../../runs/current-pems-20261013/pems-values/observations.jsonl)完整审计未发现统计、shape或身份错误。48个请求是36ready与12Chimp128原生rank3 unsupported，后者保留请求分母，没有reshape／降精度fallback。schedule、planned、started、terminal六字段键完全一致，756个正式槽位全部ok，36case各3sessions×7rounds，108个measurement worker PID。216个warmup、108个calibration、72个qualification和12个unsupported admission终态分别计数。

756条正式结果均bitwise通过、input_unchanged=true、violation0、identity transform、codec_input_bytes=raw_bytes；case raw_object_id与冻结preparation一致。12个原生V对象保持`<f8`、C order、rank3/time×sensor×feature；36个exact wire的完整hash、descriptor checksum、part hash、shape/dtype/order/schema/params及payload interval均匹配，12个raw-store body的实际hash等于preparation typed_bytes_sha256。四份来源NPZ及execution sources/snapshots、Zstd／Deflate source/runtime/binary/build-record均实际核对hash。机器记录见[pems_independent_audit.json](pems_independent_audit.json)。

36个exact-input qualification全部fresh、cache_hit=false、pass，实际各由新subprocess仅凭wire与明确roots恢复，returncode0、artifact hash、restored object identity与原始相符。CPU recovery没有持久化decoder_pid、execution_provenance、native_diagnostics、effective_profile，四项各缺36条，不能声称已逐项核对。756measurement是worker内的fresh native decoder session，不能写成756次fresh subprocess恢复。

case admission actual profile为affinity[0..15]、native thread1、object workers1、4GiB RLIMIT_AS，worker在NumPy/native import之前实际getrlimit读回。保存profile有raw-store/native runtime两组，不称全相同；该观测不是每轮或独立decoder的profile。

run级UTC窗口`2026-10-13T11:52:44.479456+00:00`至`2026-10-13T12:02:02.915135+00:00`，明确晚于installed validation输出mtime`2026-10-13T11:48:06.238716Z`。runner先持久化created manifest再资格/测量；raw未保存per-trial绝对UTC，不补造每轮wall时间。四NPZ属于同一发布/采集体系、窗口嵌套且已有暴露；许可、物理单位、提取插补历史unknown，原始与真实来源wire不进入复现导出。大窗口logical bytes与cpu0共享L3仅容量比较，不宣称实测cache状态或性能因果。完整byte审计已在此报告写入前完成，写入时重查manifest/raw SHA与当时一致；没有重新执行codec/native、数据解析、下载或正式计时，也没有修改原run。
