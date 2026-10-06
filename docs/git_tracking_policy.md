# Git 文件保留规则

仓库保存构建、运行、测试和理解算法契约所需的文件。可重新生成的本机运行结果和
临时产物由根目录 `.gitignore` 标记，本地文件保留。

| 不上传到 Git | 用途 / 再生成来源 |
| --- | --- |
| `build/`、根目录 `cmake-build-*/`、CMake 缓存 | 编译产物、构建日志；由构建工具重新生成 |
| `runs/` | 原始重复记录、资源采样、统计和 HTML/Markdown 报告；由 Benchmark 运行生成 |
| `outputs/`、`reports/`、`artifacts/`、`dist/` | 导出表格、检查转储、打包和其他生成产物 |
| `docs/completed_rewrites/` | native release/sanitizer、qualification、formal 的本机详细 JSON 报告 |
| `docs/*_integration_audit.json`、`*_qualification.json`、`*_release_consumption.json`、`*_rewrite_review.json`、`*_evidence_refresh.json` | 详细审计、验证、发布消费与刷新报告；由 `tools/` 中对应脚本生成 |
| `docs/**/*.visual-check.json` | 图表/页面的视觉验证结果 |
| `docs/rewrite_cleanup/` | 本地清理清单、历史归档、操作日志和清理报告 |
| `datasets/`、`Compression_Rewrite/` | 原有本地数据集、参考源、独立重写工作区及发布包 |
| Python 缓存、coverage、虚拟环境、编辑器/agent 配置、日志和临时文件 | 本机环境和可重复生成的中间文件 |

继续跟踪：`src/`、`native/`、adapter 源码、`tests/`、`fixtures/`、实验配置、schema、
registry/onboarding、许可证、补丁、源锁定清单、模型清单及算法必需模型。测试程序和
golden vectors 即使名称包含 `validation`、`qualification` 或 `report`，也属于必要资产。
不使用 `*.json`、`*.csv`、`*.npz`、`*.bin`、`models/` 等全局忽略规则。

人工维护的 README、审查结论、self-check、source audit、决策记录和架构图保留。
其中指向 `runs/` 或详细 JSON 证据的链接属于本地证据路径，干净克隆中可能不存在。
复现这些报告需要先准备对应数据、原版工具链/本地重写包，再按 adapter README 和
`tools/` 中的流程构建、验证或运行；不将旧宿主机报告视为新机器的验证结果。

2026-10-07 的调整将 64 个已跟踪的报告/导出文件（约 3.10 MiB）从 Git 索引移除
（`git rm --cached`），没有删除工作目录文件。修改后的下一次提交会停止跟踪这些
路径；此前提交中的文件仍保留在历史中。本次未重写历史、提交或推送。

WaLLoC 的 `stereo_5x.wlm` 和 `stereo_20x.wlm` 是冻结运行模型，不是临时文件，
因此保留。GitHub 提示超过建议的 50 MB 大小；如需解决该体积提示，应单独采用
Git LFS 或带哈希校验的模型分发流程，并同步更新构建与身份核验。本次未迁移模型。
