# forecasting_transpose 代表文件实验（2026-10-18 16:14，Asia/Shanghai）

按用户确认：每个数据家族选择代表文件，代表文件使用全部行列，接受长时间运行。

冻结规则：文件名前缀 `_dataset` 之前作为家族；其余文件去除末尾 `_数字`。每家族按 `(数值元素总数, 文件名)` 排序，选择下中位文件。共 53 个家族、53 个代表文件。

- `inventory.json`：全部 8,093 个 CSV 的 SHA-256、列名、shape 和有限值检查。
- `design.json`：代表文件、typed 输入和 314 份配置的冻结身份。
- `preparation_at_freeze.py`：CSV 转完整 C-order float64 NPY 的准备代码；NumPy 负责 codec 输入，pandas 仅用于计时外解析。无填补、量化或截断。
- `typed/`：单独声明的 float32、可逆整数与单变量 T+V 输入；同一输入在两个生命周期完全相同。
- `gpu_availability.json`：本轮 GPU build／驱动检查，GPU unavailable 不生成性能数值。

正式 CPU 测量使用现有 `tsbench run`；2 sessions × 7 rounds，prepared／fresh_request 分开。大于128 KiB的完整f64文件每批1次计时、1次warmup，其余8次计时、2次warmup。各类输入不跨dtype或质量任务排名。每个实际产物都在主时钟外验证；exact资格保留代表payload，正式重复产物保留hash与校验记录。

运行与报告脚本位于 `benchmark/tools/forecasting_benchmark.py` 和 `benchmark/tools/report_forecasting_results.py`。已有已完成run自动保留；中断run通过原配置resume。

DeepZip 适用域补充：原代表文件不能满足固定模型的0..3符号域，另从全部语料中符合该域的4份完整文件按同一中位规则选出 `vehicle_trips_dataset_without_missing_values_280.csv`（122点）。仅精确转为u8，双生命周期单独测量；不改变原53份代表文件的均值分母。原始加DeepZip补充请求5,380。

独立质量参数补充：Quantized的compatible模式在N=1资格fixture复现合同已知的无穷恢复，因此保留该失败，并追加注册表默认strict_abs模式、epsilon=0.1在全部53份完整f32输入上的双生命周期请求。使用1计时循环+1warmup；条件独立展示，不替换或掩盖compatible失败。总配置314、总请求5,486。

DZip 时长修订：完整10,898点输入资格检查显示单次编码/解码约48秒，尚无正式DZip终态结果时，将其双生命周期内部批次由8计时+2预热改为1计时+1预热。仍为2 sessions × 7 rounds，全部行列不变；原配置、原资格记录和修改前设计全部保留。详见 `amendments/dzip-duration/amendment.json`。

GPU 宿主机补充：隔离环境的 nvidia-smi 失败不代表宿主机不可用；宿主机确认 RTX 2070、驱动535.288.01可用。CPU结束后在宿主机构建并测量 cuSZp，53份完整f64和f32输入、2种边界，共212请求。rank2与域不支持保留拒绝，不截取单列、不flatten。GPU独立对象生命周期和CPU双生命周期分开展示。
