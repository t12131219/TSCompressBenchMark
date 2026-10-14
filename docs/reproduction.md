# 本地复现导出与源码运行

`benchmark/tools/export_reproduction.py` 创建**私有、本地审阅用**源码与证据包，不上传、不发布、不安装依赖，也不运行 codec。它按 [current_evidence.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/current_evidence.json) 动态选择当前 run；索引增加新 run 后，下一份包随之增加，不扫描整个历史 `runs/` 或 `build/`。

包保留 codecs 的 native/vendor/patch/model、原许可证与限制、Python 源码、工具、测试、实验配置、V4 计划和架构图、当前索引引用的文档、manifest／append-only raw／summary／源码快照。只加入实际引用的 build records，默认不带 native binary 或 wheel；`--include-binaries` 才加入这些库与当前 package verification 引用的 wheel。若索引有 `package_installed_verification`，以其 wheel 为当前选择，早期 packaging smoke check 文档仍原样保留，旧 wheel 列为 omission。不加入未引用 wheel、编译中间对象或系统／CUDA runtime。包内旧 evidence 的字节、hash、身份与绝对路径原样保留。

所有 CSV／TSV／NPY／NPZ／Parquet／Arrow 文件、独立 decoder restored 输出均不打包。保存的 wire 仅允许来自项目明确的 CPU examples／GPU P4 合成 fixture 目录；真实来源或无法确认来源的 wire 排除，记录原 hash、长度与 omission reason。raw corpus 的精确来源／hash继续由数据 catalog 和 run lineage 声明，外部原文件不会被遍历或复制。项目生成的 `.dzm` 模型作为 codec 资产保留，不能与真实时序输入混为一类。

这不是可公开再分发的授权包。`EXPORT_MANIFEST.json` 保留各 source record 的原许可状态，明确 `public_redistribution_claimed=false`；ELF 系列、DZip 等已有 local-only／redistribution restrictions 不因本地打包而改变。包可以用于本机备份和审阅，不能据此声称所有资产可公开发布。

## 计划、导出与逐文件核对

```bash
# 只读显示选择数量与未压缩大小，不导出、不测量。
python benchmark/tools/export_reproduction.py --plan

# 所有正式测量与文档修改结束后，选择一个新文件名。
python benchmark/tools/export_reproduction.py \
  --output build/reproduction-bundles/current-private-source.tar.gz

# 显式请求当前引用的 native libraries；仍不带系统 runtime。
python benchmark/tools/export_reproduction.py --include-binaries \
  --output build/reproduction-bundles/current-private-with-binaries.tar.gz

# 不解包，核查安全成员名、完整 ledger 和每个成员的实际 SHA-256。
python benchmark/tools/export_reproduction.py \
  --verify build/reproduction-bundles/current-private-source.tar.gz
```

导出拒绝已有目标、越界路径、`..`、symlink、索引引用的 evidence hash 漂移；源文件在读取中变化则不安装最终输出。它使用同目录临时文件和不覆盖的原子安装。内嵌 manifest 给出每个文件的原绝对路径、archive 相对路径、实际长度／SHA-256、选择 group，以及每个 omission 的长度／SHA-256。verify 不相信文件名或数量推定完整，重复、未知、unsafe 或 hash 不同的 member 均失败。核查证明归档内部与其 ledger 一致，不是签名／独立第三方真实性证明。

## 从导出的源码运行

当前 native 资产已经在包内，不需要从可变的 upstream main 重新取得它们；源码锁与 per-file hash 记录实际选择。取得这份**明确 SHA-256 的本地 archive**才是取得本次完整源状态，`git archive HEAD` 会漏掉未提交的新实施文件。文件摘要由导出命令返回，调用方可另外保存其输出。解包到新目录，保留 `tsbench-local/` 下的相对结构。

下面使用已有 Python 3.11+、NumPy、C/C++ 工具链、CMake、patch、git 和 ldd。核心依赖见 `benchmark/pyproject.toml`；实际 compiler、头文件、链接输入与 runtime 身份会由新 build record 捕捉。全成员还受各自 Linux／ISA／源域条件限制，不从当前本机成功推导其他平台全部支持。下面命令执行新的构建／资格／测量，应在独占测量时段运行；本导出工具没有执行它们。

```bash
cd /path/to/unpacked/tsbench-local
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"

# 源码方式提供完整 assets；pure Python wheel 的安装与 native 构建分开。
python -m pip install ./benchmark
python benchmark/examples/generate_fixtures.py --output benchmark/examples/data

# 使用本机实际兼容库，不能把另一机器的绝对路径当通用设置。
TSBENCH_REPLAY_STDCXX=/path/to/compatible/libstdc++.so.6
python benchmark/examples/generate_experiments.py \
  --dzip-runtime-preload "$TSBENCH_REPLAY_STDCXX"
env LD_PRELOAD="$TSBENCH_REPLAY_STDCXX" python -m tsbench build --all \
  --asset-root "$PWD" --build-root "$PWD/build/reproduction-native"
env LD_PRELOAD="$TSBENCH_REPLAY_STDCXX" python benchmark/tools/qualify_native_assets.py \
  --asset-root "$PWD" --build-root "$PWD/build/reproduction-native" \
  --output "$PWD/runs/reproduction-native/qualification.json"
python benchmark/tools/replay_environment.py \
  benchmark/examples/all_lossless_runtime.toml \
  benchmark/examples/bounded_quality.toml \
  benchmark/examples/empirical_quality.toml \
  benchmark/examples/records.toml \
  benchmark/examples/timestamps_normalized.toml \
  --skip-build --build-root "$PWD/build/reproduction-native" \
  --output-root "$PWD/runs/reproduction-core"
```

`runtime_preload` 只改变显式对应的 worker profile；资格工具的 preload 必须在 Python 启动前声明。新 worker／decoder 会记录实际映射库，build 的 ldd 声明与进程实际使用的库分别保留。build root 保持在 asset project 内。新绝对路径、解释器或工具链会得到新 source/build/run 身份；不要改旧 index／build record 的路径后尝试 resume 来冒充同一测量。已有 binary 即使显式带入，也不代表它能在不同 runtime 上使用；重建是源码复跑的默认路线。

真实对象需要外部 exact corpus，先按 [data_sources.md](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/data_sources.md) 的取得路线、许可说明和 frozen hash 获取或验证，再用 `generate_study.py --corpus /path/to/corpus --output ...`、`generate_real_objects.py --corpus /path/to/corpus --output ... --run-root ...` 生成新配置。这些参数显式替换输入位置，不能将旧 manifest 当可移动配置。新加入的来源只按它自己的 frozen source/selection 文档重建；本工具不自动给缺少版本或许可绑定的候选赋予资格。当前 source-only 包不会含原始或恢复的真实数组。

GPU 是独立入口。具有合适 CUDA toolkit／host compiler／device 的环境可使用 `benchmark/tools/build_cuszp.py --root /path/to/tsbench-local --build-root /path/to/tsbench-local/build/reproduction-gpu --architecture 75` 明示源码、build 和计算架构；CLI 使用可见的 nvcc／g++-11 等工具链，`tsbench.cuszp_build.build` 的 Python API 另支持显式 nvcc／host_compiler 路径。实际被选工具链及其 hash 保存在 build record，再按 cuSZp 接入文档与 `python -m tsbench.gpu` 配置独立资格及正式 run。导出没有运行 GPU probe、CUDA workload 或推定 VRAM limit；CPU 表与 GPU 两个 boundary 继续分开解释。纯 Python wheel 的已保存验证只证明同主机、显式安装 roots 下的独立 wire 解码；本归档不声称已完成第三方或跨机器复现。
