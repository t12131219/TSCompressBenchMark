# 当前保留的完整重写接入


| 入口 | Track | 当前输入合同 |
| --- | --- | --- |
| deepzip | VALUE | uint8、冻结模型的 4 符号词表，仅 0..3；外部模型加载成本计入编码 |
| dzip | VALUE | uint8、排序字母表、显式种子与原生初始模型；bootstrap/combined；9 符号字母表拒绝 |

完整 native frame、模型、descriptor、校验与恢复所需信息计入最终码流。独立 session 解码不依赖原输入；模型内部费用未细分时不能把 model_bits=0 当作免费。保留 CORE/PIPELINE/E2E 的已声明边界，内部 native timer 仍不可用，不从 CORE 推导原生耗时。

```bash
python tools/build_completed_rewrite.py deepzip --profile all --output-root build/completed-local
python tools/build_completed_rewrite.py dzip --profile all --output-root build/completed-local
PYTHONPATH=src python tools/qualify_completed_rewrites_native.py --build-root build/completed-local --output-directory build/completed-local-native-proof
PYTHONPATH=src python tools/onboard_completed_rewrites.py --build-root build/completed-local --qualification-directory build/completed-local-native-proof --output-directory build/completed-local-registration
PYTHONPATH=src python tools/qualify_completed_rewrites.py --mode QUALIFICATION --suffix local-qualification
```

构建并行度由 `TSCB_REWRITE_BUILD_JOBS` 设置为 1..16；默认 2。CPU 模型依赖的位置可由 `TSCB_TORCH_ROOT` 指定，但仍必须通过锁定文件哈希检查。ASan/UBSan 验证 binding 与参与构建的源码；未插桩的外部二进制及关闭的 leak detection 不在声明范围内。

上述目录必须使用未存在的新路径。资格签署前后核对当前冻结包、实际编译依赖、测试程序、动态依赖和完整非空 CTest 清单；跳过、未运行或缺失测试不能签 PASS。接入工具保存旧注册文档与候选文档，再更新实际工件路径及派生身份。C++ API/安全测试不能替代原语言源 oracle 或完整 G0–G6/CAP-GATE 验收。

正式统计必须完成预热、完整重复、最短编码/解码时长与资源门禁。退出前的报告和运行目录保留为历史证据，不由本次范围变更重新签成 PASS。

ABBA/fABBA 已归档删除；当前三算法接入见 ../abba_family/README.md。
