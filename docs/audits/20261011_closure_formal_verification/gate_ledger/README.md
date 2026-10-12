# 当前完整门禁台账

本目录把独立调查明确展开为 33 个入口、220 条适用门禁：22 个原生入口各 N0–N5，11 个重写入口各 G0–G6/CAP-GATE。[机器可读台账](current_complete_gate_ledger.json) 保存路线、对象、已声明 profile、原有限证据、逐项标准、下一步、外部资产／执行条件和原能力分类。[驱动](build_gate_ledger.py) 只消费先前的静态 JSON，没有执行 codec、测试、源模型、训练或性能。

`current_complete_gate_status=UNKNOWN` 表示当前完整门禁尚未完成独立核验及签署，不是把历史有限 PASS 改为失败。已有源路线、factory 依赖验证、边界／差分结果仍保留在 `prior_scoped_evidence`，没有新增 FAIL，也没有授 N/G、FORMAL、FULL_PARITY 或 REWRITE_DONE。

原生验收允许针对事前冻结的当前 profile；完整上游能力仍须保留并单独评审。重写完整验收覆盖原已冻结 required 全集，不能追溯缩成目前 Bench 的单个变体。四份既存能力矩阵逐项展开，原 required 分类不降级；DZip 的历史 `REFERENCE_ONLY` 保留原值，明确需要重新作合法四态评审，未擅自转换为 `NOT_APPLICABLE`。

DeepZip/DZip 的精确旧源环境包载荷在已搜索本地根中仍缺，当前进程也不能与 NVIDIA driver 通信；Dipperstein 缺独立 pinned 原始 authority。相关范围在前序 [门禁盘点](../gate_audit/README.md) 有完整证据。其他入口的下一步表示还须组织验收，不预先保证执行成功。N5 独立交付不要求先取得 FORMAL。

台账引用五份既有调查文件的 SHA，生成后再次核对相同。旧 `gate_audit/file_index.json`、历史审计和原能力矩阵没有修改。
