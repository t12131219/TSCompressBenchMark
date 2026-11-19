# 源文件加载器可插拔性：T/V 开发套件 v3

`bmk.dev-tv-suite/3` 用 `source_groups` 显式声明每个原始对象由哪些已注册加载器提供，
而不是在核心仅允许 CSV、NPY、TXT 三个固定 ID。[示例套件](../../configs/suites/dev_tv_source_providers_v3/suite.json)
沿用已有的真实交通尾块和特殊位尾块。原 `bmk.dev-tv-suite/2` 仍严格要求三种既定格式，
不更新旧计划、已封存报告或首批服务范围。

- 对照组声明 2–8 个不同 provider；实际排定的 case 必须与这些 ID 一一对应。每个 provider 的源字节摘要必须不同，
  原始对象 schema 与内容（包括原时间轴和每列的位模式）必须一致。每个比较覆盖其引用的完整组，一个 canonical
  对象只计一个权重；不同 provider 不等于增加独立数据来源。
- 工程本地 [加载器注册表](../../catalog/source-loaders.json) 绑定受信任的 Python 实现、选项 schema 和版本；
  源 manifest 选择一个注册项并声明文件摘要、原域 schema 和显式选项。新增实现不需要修改 TV planner、比较器、
  worker、报告或恢复逻辑。撤下注册项即不可选，留下同名文件也不能隐式加载；不引用该项的配置仍可运行。
- 替换实现或选项会绑定新的 ingestion 身份；如果原对象没有变，则 canonical、T/V 方法与比较语义不变。
  不兼容的源格式须由新实现显式拒绝，不能将失败归为 codec。已封存的 bundle 只依赖对应 decoder 闭包，
  加载器不计入解码依赖。不修改 ingress/setup 在 worker 计时之前的合同，仍不是源文件端到端性能测量。

```bash
./bmk tv-plan --suite configs/suites/dev_tv_source_providers_v3/suite.json \
  --build-lock build/build-lock.json --out results/provider-plan.json
./bmk tv-run --plan results/provider-plan.json
```

## 禁网迁移验证

[生命周期审计](../../results/m0-source-loader-authoring-20261119-r2/audit.json) 在 `tsbench` 中用精简迁移副本、
只读来源与已锁定构建完成。审计用一个测试专用的行式二进制加载器，v1 和 v2 的 header 不兼容，v2 有独立的 `byte_order` 选项。
每个状态使用自己的一份冻结计划、一次运行和一份账本，三个状态不拼接为一次正式验收。

| 状态 | 证据 |
|---|---|
| 新增 v1，CSV + NPY + 新加载器 | [6 个产物独立恢复](../../results/m0-source-loader-authoring-20261119-r2/added-restore.json)；三种源字节身份仍还原成一个原对象 |
| 撤下注册，文件还在 | [旧计划提交被拒绝](../../results/m0-source-loader-authoring-20261119-r2/logs/submit-disabled.stderr)，未新建运行账本 |
| 同 ID 更新 v2 | 新选项配置有效；旧选项和带正确新选项的旧 header 分别拒绝，随后 [6 个新版产物独立恢复](../../results/m0-source-loader-authoring-20261119-r2/upgraded-restore.json) |
| 移除加载器文件、schema 和数据引用 | CSV + NPY [仍能执行并独立恢复 4 个产物](../../results/m0-source-loader-authoring-20261119-r2/remaining-restore.json) |

脱离原始文件、源码插件目录、注册表和构建目录，各次报告从封存计划、账本及产物复算，CLI 输出逐字节一致；
旧产物恢复仅挂载封存的解码器和依赖。验收范围只到已实现的 dense i64 + f64 的批式 T/V provider 生命周期。
不宣称 12 项所有加载域、转换/服务插件生命周期或正式原生资格均已完成。

可用 `bash tools/probe_offline_source_loader_authoring.sh "$CONDA_PREFIX" <匹配TV构建目录> <空结果目录>` 复现；
已存在完整生命周期证据时可用 `--replay-only "$CONDA_PREFIX" <现有结果目录>` 仅复核，不再编码。
