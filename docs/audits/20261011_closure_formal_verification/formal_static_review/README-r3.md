# FORMAL 三驱动独立门禁核验 r3

本轮对应 audit_current_formal.py 的 SHA-256 `53dedde868d9eced31556e9e53ec7b3e0732a8340a0de75b0984be3a471b3452`；prepare 与 runner 的 SHA 未变化。旧 [r2 报告](report-r2.json)、[README](README.md)、[final_index.json](final_index.json)与首次失败均保留，未覆盖。

[report-r3.json](report-r3.json) 的 **22 个案例全部符合预期**：2 个正例接受，20 个反例拒绝。测试前后三驱动 SHA 相同。旧 audit 的 22 个 assert 条件全部按 AST 保留到 require，当前 assert 数为 0。runner 与 audit 的实际 main AST 在 Python `-O` 下均命中入口拒绝；[optimized_require-r2.json](optimized_require-r2.json)进一步确认本轮实际 require 函数在 `-O` 下仍拒绝 false evidence。

[normalized_protocol_ast-r1.json](normalized_protocol_ast-r1.json)独立确认当前真实 audit 使用 `workload["protocol"] == WorkloadProtocol(**read(ROOT / lane["protocol"])).to_document()` 作为 require 条件。此项只验证真实 AST 的归一化比较表达式；不将 AST 核验冒称真实 workload 执行通过。

反例覆盖三驱动字节漂移、proof／historical base／protocol 漂移、引用路径逃逸、native／model／corpus／runtime SHA 漂移、固定 16 lane 分母与 kind、更新合法文件 SHA 后的 MethodID／non-source 决策变更、重复 receipt。允许具有显式 SHA 的系统绝对 runtime 引用。

只编译真实驱动的纯文件／哈希校验函数 AST，并在临时项目中使用最小 registry 夹具。未导入生产包、未加载 codec／ELF／模型运行时、未运行 pytest／oracle／性能，未改生产文件或三份驱动。本结果仅证明所测拒绝门禁，不代替完整源依赖闭包、全部 N/G/CAP、真实 16 lane 执行及最终 FORMAL 性能资格。

[final_index-r3.json](final_index-r3.json)冻结本轮报告、优化模式反例、协议 AST 核验、审计程序与三份受审驱动 SHA；任何受审驱动改动均要求重新核验。

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/formal_static_review/check_gates.py --output /tmp/tscb-formal-gate-review-new.json
```

输出拒绝覆盖既有证据。
