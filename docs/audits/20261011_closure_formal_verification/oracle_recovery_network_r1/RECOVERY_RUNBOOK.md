# 精确旧 oracle 环境恢复路线

本次继续恢复只在新目录 `build/legacy-oracle-recovery-20261011/oracle-recovery-r1` 创建下载 cache、conda cache、独立 prefix、日志及探针。现有 conda 环境、源码、锁、registry、GPU 系统安装不修改。包选择严格来自归档锁；PyPI 未保存 URL 的条目用官方版本元数据核 filename/SHA/size 后取得原字节，不替换版本。

## 当前公开获取依据与空间

80 个 acquisition 引用去重 71 包，32 个 conda 原 URL 的 HEAD 均可达，39 个 pip 文件均与官方 SHA/size 相符。合计 1,778,340,023 bytes（约 1.78 GB）；新审计已取并核 30 个小包 4,301,714 bytes，大包尚需逐 SHA 验证。目标文件系统查询有 59,012,825,088 bytes 可用。下载、conda 解包、三个隔离环境及 CUDA side prefix 预计需数 GB；时间取决于下载与本机解包，没有预先保证时长。

| 锁组 | 包引用／取得总量 | 精确环境 |
| --- | --- | --- |
| DeepZip base | 30 conda＋31 pip，840,515,056 bytes | Python 3.6.13、TF GPU 1.8.0、Keras 2.2.2、NumPy 1.16.4、CUDA 9.0、cuDNN 7.1.2 |
| DZip CPU overlay | 9 pip，114,006,001 bytes | 上述 base 的独立 system-site-packages venv，CPU TF 1.14.0、Keras 2.2.2、NumPy 1.16.4；GPU visibility为空 |
| DZip GPU overlay | 2 conda＋8 pip，827,743,104 bytes | 新 system-site-packages venv 中 TF GPU 1.14.0；另立 CUDA 10.0.130／cuDNN 7.6.5 runtime |

包引用有共享，三行不可相加作去重总量。GPU overlay 三个原锁未写大小的包采用本次官方 HEAD／PyPI size，SHA仍取原锁。完整 URL、大小、SHA、probe 和小包 receipt 在 [network_recovery_report.json](network_recovery_report.json)。

## 恢复方式

1. 将每个原 SHA 对应包取得到新 build cache。复用本轮精确小包或此前本地匹配包时也重新核 SHA；下载先写 `.partial`，校大小和 SHA 后才成为可消费文件。所有取得结果逐项留日志，失配保留失败。
2. DeepZip 使用归档的未修改 [restore_environment.py](Source__deepzip__restore_environment.py)。在新 build recipe 中按其原相对文件名复制原锁和脚本，用 `--conda /home/fzg/anaconda3/bin/conda --conda-cache <new-cache/conda> --pip-cache <new-cache/pip> --prefix <new/deepzip-tf18>`；`CONDA_PKGS_DIRS` 也固定新 build cache。原驱动先核全部 30/31 archive，再 `conda create --offline --no-deps` 和 `pip install --no-index --no-deps`。
3. 原 metadata archive 没有脚本引用的 `oracle-requirements.txt`。新 recipe 的该文件由原锁记录的 32 个 installed distributions 推导：conda提供 certifi/pip/setuptools/wheel，余 28 个逐一与唯一 exact acquisition匹配。原 Keras 2.2.4／Applications 1.0.8／Preprocessing 1.1.2 三个仅比较 acquisition不安装。推导和 SHA保存在 [requirements_derivation.json](requirements_derivation.json)。这是显式补齐缺失 recipe 输入，不能冒称取到了历史原 requirements字节；安装后须比较锁中可重定位 installed-file hash和版本。
4. DZip CPU 按原 TOOLCHAIN lock，用新 DeepZip Python `-m venv --system-site-packages <new/dzip-tf114-cpu>`；离线安装原 9 个 overlay archive，`--no-deps`，以新 venv 的 TF CPU 1.14覆盖继承包。`LD_LIBRARY_PATH=<new/deepzip-tf18/lib>`，`CUDA_VISIBLE_DEVICES=''`，`PYTHONHASHSEED=0`。
5. DZip GPU 的原 [prepare_gpu_oracle.py](Source__dzip__prepare_gpu_oracle.py) 固定写 `/tmp` 和 Source lock，不直接执行它。新恢复驱动等效重放其确切动作、仅重映路径：用已有 conda-package-handling 将原 CUDA10／cuDNN包解至新 runtime；新 DeepZip Python 创建独立 system-site-packages venv，离线安装原 8 个 pip overlay，`--ignore-installed --no-deps`。每个包先按原 GPU lock核 SHA，不改写原 lock。该历史 GPU lock 的状态仅 `INSTALLED_NOT_YET_RUNTIME_VALIDATED`，本轮不能继承不存在的运行 PASS。
6. 创建之后先做独立环境版本／import／设备及动态依赖探针：核 Python、TF、Keras、NumPy、h5py 和实际库路径。GPU探针用 sandbox-external；普通 sandbox exit9和外部 RTX2070/driver535.288.01 exit0两条实测均保留。线程固定，TF1.8按原来源文档设 `TF_FP16_RNN_USE_FP32_COMPUTE=0`，不改算法。

本恢复阶段暂不训练、不压缩／解压、不测性能，也不自动授 G1/G3/G5/CAP/FULL_PARITY。下一步真正源 oracle需要另冻结源码／checkpoint／driver／输入／参数和差分合同。

## 必须实测的兼容性边界

- 原 cp36 manylinux wheel、Python3.6.13 和已锁系统库在当前 OS loader实际加载；不要用系统同名库代替被锁 .so。
- CUDA9／cuDNN7.1.2 与 RTX2070／driver535.288.01 的实际 TF1.8设备枚举及 RNN初始化；历史原文有同设备成功记录，但本轮 fresh load仍需实测。CUDA10/cuDNN7.6.5 的 TF1.14 GPU也单独测。
- DeepZip TF1.8 FP16 descriptor flag的必要性、单线程／allow-growth与原 Keras依赖；设备可见不等于全部17构造器或trained checkpoint验证。
- DZip源README推荐 Python ≤3.6.8，本次锁实际为3.6.13；须如实保留这个源建议／实际oracle版本差别。CPU TF1.14不证明官方 CUDA bootstrap；GPU BPC estimator不等于完整 codec。
- 由原 archive恢复的安装文件与锁中 per-file hash；可重定位脚本/shebang和重新生成dist-info文件分别记录，不因移路径把核心代码hash差异隐藏。
