# 本地 codec 选择、构建和开发回归

## 新增或选择插件

1. 在 `plugins/codecs/` 增加自包含的 ABI v1 包、CMake 入口、manifest、options schema 和契约测试。
   在 `catalog/plugins.toml` 增加对应 ID。manifest 的 `build.cmake_dir` 指向工程内包目录，
   `build.target` 指向本包声明的共享库目标。将该目录的 `CMakeLists.txt` 列入 `source_files`，
   同时登记源码、辅助构建文件、受控归档和运行依赖。构建入口只接受本工程信任的包。
2. CMake 默认 `TSBENCH_PLUGINS=@enabled`，只引入已启用的包。用 `-DTSBENCH_PLUGINS='raw-store;zstd'`
   显式限制 ID；空字符串只构建 worker（若启用 `BUILD_TESTING`，也会构建公共 ABI 测试）。
   未选择的包不解析其 manifest 或检查其源码。指定已禁用、未知 ID、缺声明或目标与包不匹配时，
   配置失败。目录可能仍有以前留下的构建产物；隔离审计用空目录，不从目录扫描加载 DSO。
3. 多个 ID 可共用一个包；该包在 CMake 中只引入一次，以 `BMK_SELECTED_PLUGIN_IDS` 判断要声明的
   adapter（pcodec 是例子）。不借用其他插件先加载出的符号；共享库由包声明明确的构建与相邻运行依赖。
   冻结的 Unique 包只核验所用归档及其身份闭包；`bmk check-sources` 仍单独核验完整首批范围。
4. 用 `bmk lock-build --worker <项目内路径> --plugin ID=<项目内DSO> --out <新文件>` 绑定选中产物。
   构建、manifest 和 options 变化要求新锁，不能把旧锁更新成新结果。完整首批候选原生预检仍要求
   全部已配置的探针；裁剪的构建不能缩小其分母。CORAD 当前只是来源侧诊断，需要显式
   `-DTSBENCH_CORAD_DIAGNOSTIC=ON`，不是注册的 worker 插件。

## 增加开发 suite 或方法配置

`bmk smoke-plan --suite <ID>` 可读取项目内 `configs/suites/<ID>/suite.json`；参考
[现有开发套件](../../configs/suites/dev_lossless_smoke_v1/suite.json)。不改核心算法分支即可
选择满足该任务的替换方法。当前通用路径只处理小型连续单列 f64、无 validity、按位无损的 V 任务；
manifest 必须声明适用 `role` 和 `supported_tasks: ["linear_f64_bitwise"]`。使用 `bytes` 路线
时仍只证明 codec 能复原该列的 canonical 字节，不宣称 typed V 能力。此声明不是资格。

插件 options schema 定义默认值、合法值和必需字段；冻结计划展开实际参数并绑定其内容身份。
不匹配的角色、未声明的任务、缺依赖和未知参数不得静默替代。执行用 `bmk smoke-run --plan …`，
保留逐产物独立解码与验证、一份账本和可复算报告。`scripts/smoke.sh` 仍是 raw-store / Zstd / ALP
三方法的便利入口；自定义套件直接用 lock/plan/run 命令。

## 版本演进与验证范围

不兼容格式更新应留存旧 manifest、构建锁和匹配的解码工件。用新构建验证新格式；用旧解码器
恢复保留的旧样本；不能因为同一个 plugin ID 仍能加载就宣布格式兼容。旧报告从原始账本复算，
不重写旧实现、配置或格式的身份。

`tools/probe_offline_m0.sh --pluggability-only <tsbench-prefix> <rust-toolchain> <空输出目录>`
在无网络、迁移路径下从最小工程副本构建并实测。副本不含第三方归档；其他已注册但未选择的
插件目录也不存在。验证新增测试插件、同任务方法切换、禁用和移除、修改 schema 默认值与覆盖、
实际传参、旧锁拒绝、旧格式拒绝及历史解码器独立恢复。测试插件不是首批算法；这份回归只覆盖
本地 codec/小型无损任务，不能替代所有插件类型、组合和平台的交付验收。
