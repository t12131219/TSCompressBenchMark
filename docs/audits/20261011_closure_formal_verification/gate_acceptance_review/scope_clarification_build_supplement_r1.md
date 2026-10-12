# 门禁范围澄清与最终构建补证 r1

本补证只追加已冻结的小型源差分／构建回执及独立审阅，原 33 入口、220 条报告保持 **3 PASS / 32 FAIL / 185 UNKNOWN**。32 条是完整验收条件未满足的门禁，不是 32 个算法编解码失败。原报告、能力分类、主矩阵和冻结生产文件均未修改。

DeepZip G5 中“完整 required 集合未执行／未完成”的措辞只指完整 source/native 必需能力集合，不能读成源 GPU 全未运行。源 biGRU、alphabet=4、三个上下文已实测四个 GPU CudnnRNN 节点；当前权重 reexport EXACT；12 个概率在原3e-5容差内 PASS（maxabs1.4901161193847656e-08）；相同源概率的15整数CDF转换 EXACT。独立预测完整CDF有真实 **1/15 差异**，第三上下文 total source10000004/native10000003。r2三命令exit0，差异不是crash；r1附加FULL_TRACE缺CUPTI导致abort(-6)仍保留。其余完整 predictor/trained checkpoint/nativeGPU/codec/真实数据与CAP未闭合，G5 FAIL和有限PASS均保持，不授源码流或完整parity。

最终构建回执补充 **67/67 唯一配置有限观察 PASS**（release33、sanitizer33、debug1）及 **33/33 严格release有限观察 PASS**。67项记录exec/open/link map/archive member/外部checkpoint；33项增加exec及内核解释器前后SHA、可读OPEN初始文件版本。没有证明同一描述符写入后读取的全部字节，没有重建历史执行，不授完整N1/G1或source parity。原pending快照保留，新的有限完成证据由本补证追加。

50个新旧共享产物相同、17个不同；33个release均相同。共享库相同不能扩大成整个源树／对象／测试程序相同：DZip有生成mkldnn_version.h差异，98个depfile消费者、1个对象变化，已登记测试程序也不同。177份试验回执（171基础PASS、6基础FAIL；4个strict GAPS_REMAIN已包含）全部保留，不能当成67配置／33算法的分母。构建观察不把CTest清单当测试执行。

FORMAL最终测量、aux/reference成本和完整索引在本补证冻结时仍pending。**N5独立交付不以FORMAL为前置条件**。所有原N/G/CAP状态保持；后续结果仍需以新证据、明确范围及身份单独验收。

[机器补证](scope_clarification_build_supplement_r1.json)保存八份输入SHA与完整计数／限定边界；[生成驱动](build_scope_supplement_r1.py)仅消费小型JSON，不导入生产模块、不遍历单份trace、不执行构建／codec／模型／训练／测试／性能。[独立新索引](scope_clarification_build_supplement_r1.index.json)绑定这次新增文件；原索引未覆盖。该补证已quiet。
