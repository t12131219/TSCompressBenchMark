# 三路线直接调用与同工作量对照

`configs/experiments/measurement_controls/direct_routes_v1.json` 定义开发诊断输入和完成端点。
`tsbench.control.direct` 一次执行全部方法，取 CMake 刚构建的二进制并复制到新的私有目录，
校验该次构建的插件和依赖身份。成功时在 CMake 输出根生成完整的 `direct-control.json`；
CTest 的 JUnit 仅存测试状态和文件位置。这个文件不是资格账本。

| 对照 | 相同之处 | 有意不同之处 / 证据边界 |
|---|---|---|
| 动态 worker ⇔ 直连 worker | 相同插件 DSO 及原生依赖、相同 `worker_main.cpp` 的编解码工作、独立进程与新 context、输出所有权、选项、完整封装、恢复数据与 schema；相同的 ABI 调用表 | 动态路线通过 `dlopen` 寻找入口，直连路线在链接时绑定；不是逐调用去虚化实验。端点是子进程退出并产物可读，不声称 `fsync`/掉电持久性 |
| Zstd 原生差分 | 同一个冻结 `liblzbench_native.so`，`LN_ZSTD`、level 3、单次块调用；独立使用 `ln_create`、`ln_compress`、`ln_decompress` | 原生调用仅有调用者提供的缓冲。不含输入 I/O、封装、worker 所有权释放；只比较内嵌码流和恢复 bits |
| ALP 原生差分 | 同一个冻结 `libalp_native.so`，`ALPN_AUTO`；`alpn_inspect` 和 `alpn_decompress_ex` 独立检查输出与 native backend/分支计数 | 同上，不把裸调用与完整路径的差异解释成框架开销。报告实际执行计数，不以请求 ISA 代替执行证据 |
| raw-store 独立参考 | 按格式规范独立构造整帧、逐字节检查 | 没有另一个原生库，不伪造算法性能对照 |

每份成功产物都做恢复比对；启动 decoder 前删除原始值和 schema 文件。Zstd 的 64 KiB+1
被明确拒绝；不支持的 ALP f32 + AVX2 解码组合失败，并检查没有悄悄切换后端。首批服务矩阵
分母不因探针通过或拒绝发生改变。诊断记录不采集性能时钟；缓存分类、控制变量冻结、独立
session 的配对随机顺序、测量开销和 profiling 扰动留待 M2/M4 正式实验。

```sh
# 在 tsbench 中从完成构建的目录运行，生成同一个全量诊断 JSON。
ctest --test-dir build/m0-layout-abi -L direct-control --output-on-failure
```
