# 旧 TF oracle 环境已恢复，源一致性仍待执行

当前结果是精确包取得、隔离安装、版本／空 Session设备及安装字节补证。71 个去重包（80个引用）均已实际取得并通过原SHA，总计 1,778,340,023 bytes；51个复用已核本地／本轮小包，20个从官方地址下载。三套新环境均安装成功，已有环境、源码、registry和原锁不改写。本轮没有训练、模型构造器／checkpoint推理、压缩／解压或性能测量。

| 新 prefix（均在 `build/legacy-oracle-recovery-20261011/oracle-recovery-r1`） | 实际版本 | 外部空 Session探针 |
| --- | --- | --- |
| `deepzip-tf18` | Python3.6.13、TF GPU1.8.0、Keras2.2.2、NumPy1.16.4、h5py2.10.0 | GPU已枚举 |
| `dzip-tf114-cpu` | Python3.6.13、TF CPU1.14.0，其余同上 | CPU已枚举，GPU不可见 |
| `dzip-tf114-gpu` | Python3.6.13、TF GPU1.14.0，其余同上 | GPU已枚举 |

CUDA/cuDNN版本API实测分别为 `9000/7102` 和 `10000/7605`；driver API返回12020。实际 `libcudart.so.9.0.176`／`libcudnn.so.7.1.2` 和新 `cuda10-runtime/lib/libcudart.so.10.0.130`／`libcudnn.so.7.6.5` 路径、加载库SHA和ldd均保存。普通sandbox原exit9与外部RTX2070/driver535.288.01 exit0来自不同执行上下文，两条记录都保留；不再把当前缺口解释为主机无GPU。

DeepZip原 installed-file lock的8,361个文件，8,329完全匹配、32仅为安装RECORD／迁址脚本差异；8,170个记录代码／数据文件全部匹配，30个conda version/build均匹配。DZip CPU／GPU overlay分别3,073／2,934个Python／ELF成员与exact wheel字节匹配。首次overlay审计没有解释wheel `.data/purelib`的安装映射，形成各2,491个假缺失；初版结果不改写，r2显式处理标准wheel映射及versioned `.so`后全部通过。这是审计harness问题，不是环境或codec运行失败。gast等sdist的安装代码没有独立历史overlay安装文件锁，这个证据边界保留。

原DeepZip `restore_environment.py`未修改；缺失的requirements文件由原锁已安装32发行包明确推导为28 pip选择，其余4项由conda提供。DZip GPU原恢复脚本会硬编码旧/tmp并改写Source lock，因此只把其锁定提取／venv／8pip动作等效重映到新目录。具体步骤和兼容性边界见 [原恢复runbook](RECOVERY_RUNBOOK.md)，推导见 [requirements_derivation.json](requirements_derivation.json)。

本轮批量取得用时约173秒，隔离恢复命令跨度约74秒；新build目录占用7,876,534,272 bytes（约7.88GB，包含下载cache、解包cache与三套prefix／CUDA side runtime）。后续的原源差分需要 separately冻结source/model/input/config/state和driver，不能用native seed或环境PASS产生expected，也不能把这次恢复授成G1/G3/G5/CAP/FULL_PARITY。

主要证据：

- [精确包获取](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/legacy-oracle-recovery-20261011/oracle-recovery-r1/acquisition-attempt-1.json)
- [隔离恢复](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/legacy-oracle-recovery-20261011/oracle-recovery-r1/restoration-attempt-1.json)
- [环境探针](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/legacy-oracle-recovery-20261011/oracle-recovery-r1/environment-probes-sandbox-external/report.json)
- [代码／ELF字节审计r2](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/legacy-oracle-recovery-20261011/oracle-recovery-r1/installed_byte_audit_r2.json)
- [CUDA/cuDNN版本API](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/legacy-oracle-recovery-20261011/oracle-recovery-r1/cuda_cudnn_version_api_report.json)

首次网络请求受普通sandbox限制的失败、Python3.11静态审查不支持3.14语法的历史harness失败及源gate旧盘点均保持原记录。当前补证只解除精确环境／设备访问的可取得性问题，没有反写旧调查。
