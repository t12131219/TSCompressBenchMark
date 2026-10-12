# FORMAL 三驱动的独立门禁核验

对当前 prepare_current_queue.py、run_frozen_queue.py、audit_current_formal.py 的纯文件／哈希校验函数进行独立核验。只将实际函数 AST 编译到临时项目，使用最小 registry 夹具；未导入生产包、未加载任何 codec／ELF／模型，未运行 pytest 或性能。完整 source identity 验证、真实 RunSet 和生产报告验收不由此夹具代替。

[report-r2.json](report-r2.json) 为 PASS：**22 个案例全部符合预期**，测试前后三驱动 SHA 相同。

- 两个正例：原始夹具接受；具有显式 SHA 的绝对系统 runtime 引用接受并收录。
- 20 个拒绝反例：三份 driver 改字节、proof 改字节／错 SHA、historical base 改字节、protocol 改字节、protocol／preparation 引用／registered 相对路径逃逸、native 绝对路径逃逸、native .so／model／corpus／runtime SHA 漂移、固定 16 lane 分母／kind 修改、重新合法更新文件 SHA 后的 MethodID／non-source 决策变化、重复 preparation receipt。
- runner 和 audit 的真实 main AST 分别在 Python -O 子进程中触发优化模式拒绝；没有机会调用 lane、codec 或报告代码。
- 旧 audit 的 **22 个 assert 条件**全部按 AST 保留到 require；当前 assert 数为 0。require(False) 在普通解释器拒绝；[独立优化模式反例](optimized_require-r1.json)另外确认实际 require 函数在 -O 下也拒绝 false evidence。

首次读代码时发现 protocol 裸路径、registered 相对路径没有 ROOT 边界的静态缺口。主代理随后修补了三驱动；本核验没有将静态观察伪装成已运行的旧版本反例。首次夹具只有一条 lane，在新 16 lane 门禁下被拒，保留为 [harness-r1-failure.json](harness-r1-failure.json)及[当时夹具 driver](harness-r1-driver.py)。修正夹具为完整固定 lane 映射后，当前版本的门禁反例全部通过。

三驱动没有被本审计修改。队列 command／journal／执行 bundle／protocol／统计 raw 等后置验收条件仍须由实际最终 FORMAL 审计执行；本结果仅证明所测拒绝门禁，不签发性能资格。

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/formal_static_review/check_gates.py --output /tmp/tscb-formal-gate-review-new.json
```

输出拒绝覆盖已有证据。[final_index.json](final_index.json)冻结三份受审驱动、审计程序和结果 SHA。任何受审代码改变都会使这份 review 属于历史版本，必须重核。
