# TSBench 开发日志

本日志自2026-10-15本轮全codec direct core扩展起持续维护。此前记录只根据仓库现存文档、源码与运行证据回顾，不补造未记录的操作时间或实验。

当前全CPU扩展已完成统一构建、715项完整测试、28份串行正式配置及严格只读审计；最终范围见本日志末尾“正式运行完成与统一审计”。下列开发过程保留各自当时状态，不以最终结果覆盖早期失败或待验证记录。

## 神经路径补充设计：静态冻结

只读审查发现全 registry 原冻结设计的 DeepZip／DZip 都取前 64 个符号，实际上没有进入 `i/j>=64` 的神经预测循环；每个 encode／decode 均为 0 次 predict、0 次 train。这些结果只能说明均匀概率短流和完整模型／容器成本，且 N<65 是 contract 明确的 native 安全扩展。原 24 配置及其请求／证据保持不变。DZip BOOTSTRAP 任意长度都不在线训练；只有 COMBINED 在累计 128 次预测后训练一个完整 batch，DeepZip 训练则独立于 codec。

据源码阈值在正式运行前追加 `benchmark/tools/generate_neural_core_experiments.py` 与 `benchmark/experiments/native-neural/`：4 配置、6 请求，使用现存 `symbols4.npy` 完整257符号，DeepZip biGRU 与 DZip BOOTSTRAP／COMBINED 各有 prepared／fresh。每个 encode／decode 为193次predict；COMBINED另有1个128-window train batch／1 Adam step，并有65次后续预测消费更新权重。未采用192，是因为其训练发生在最后一符号之后；257无截断或补齐，仍保留原输入任务身份。次数由源码静态推导，未运行runtime计数验证。

补充设计沿用2sessions×7rounds，DZip loops2／warmup2、DeepZip loops8／warmup2，timeout均600s，共84名义trial、336名义测量操作。生成器仅解析输入与registry，不构建、不执行codec、不作性能计时；中央运行后才能确认实际成功。默认DZip输入相关seeded／untrained模型如实标注，未冒充预训练checkpoint。详细分支、计数、来源与限制见[实验设计记录](development/all_core_design.md)。

正式运行前的 symbolic 修正去除了ABBA／fABBA编码时未使用的完整恢复，造成与神经codec共用的binding.cpp完整源码hash变化。已把补充设计初版原样保存为 `benchmark/experiments/native-neural/design-before-symbolic-fix.json`，重新生成现行design.json，仅刷新该source reference：旧 `5740e843…`、新 `8e446c2f…`。输入、全部6请求、4配置、预测／训练计数及运行协议字段逐项不变；原24份与补充4份TOML均只读比较，hash及修改时间全部不变。旧身份的257短诊断保留为诊断证据，不转换成新身份正式结果。本步骤仅静态解析／hash校验，没有构建、执行codec或测试，完成后停止CPU工作；完整清单hash及原因见[实验设计记录](development/all_core_design.md)。

## 全量原生报告与神经路径补充审计

新增 `benchmark/tools/report_all_core_results.py`，默认分别审计 `native-all/design.json` 与 `native-neural/design.json`，保留原 352 请求与新增 6 请求的独立设计分母，再合并输出全量报告与证据索引。配置、循环数、输出目录及统计均来自冻结设计和保存的运行记录，不写入预设实测数字；只有执行源一致、结构证据有效、38 个 key 双生命周期存在完整合法案例且补充神经案例全部完成时才写报告。历史 `docs/native_results` 保留。`--design` 继续接受单一基础设计，`--supplement` 可指定补充设计，`--no-supplement` 显式只审计基础设计且不宣称取得神经路径结果。

报告器实际阅读并复核 `vendor/deepzip/src/deepzip.cpp` 的 encode_group／decode_group 与分 lane 逻辑、`vendor/dzip/src/codec.cpp` 的 encode_raw／decode_raw／adapt、`vendor/dzip/src/nn.cpp` 的 train 与 Adam 更新，以及直接 `native/binding.cpp` 的参数与模型初始化。神经专表逐请求区分 model／mode、257／64 输入、profile、生命周期、原生完整输出与批次吞吐，显示源码推导的 predict／train／Adam／更新后预测次数，明确不是动态 counter，也不是单独神经内核速度。合法案例总览优先使用完整神经补充输入；DZip BOOTSTRAP 与 COMBINED 以 resolved params 区分，避免同输入覆盖。

审计器复核补充设计来源 hash 及计数元数据、所有正式与 warmup 完整产物、资格缓存原始证据和独立 decoder 进程；每个 scheduled round batch 只作为一个统计样本。不完整案例主性能留空；CSV 保留全部请求、admission 与每次尝试的状态／原因。该项仅编辑报告器和开发日志；`ast.parse` 语法检查与 `git diff --check` 已通过，未执行生成器、codec、构建或测试。正式运行及报告验证由中央串行安排。

## 记录规则

后续每次实现、配置、计量边界、文档或结果变更均须同步更新本日志，至少说明具体问题、采用的解决办法、实际阅读的参考、验证结果和未解决限制。未构建、未运行或未阅读的内容明确标为未验证；历史raw及既有证据身份保持原样。并行开发可先写入`docs/development/`下的分组记录，再由集成者合并或链接到本文件。

## 本轮开始前可核验的改造事实

- 默认目标已从完整对象处理切换为`native_core / prepared / natural`，Python承担准备与调度，C++ driver内部重复计时；显式`native_api`与`object_memory`目标保留。原因是对象wire大小与Python处理耗时不能代表codec原生表现。
- 首批direct core为raw-store、Zstd、LZ4-frame及Snappy；通用API辅助覆盖36个真实CPU codec在各自合法任务下的case。其余direct core请求明确unsupported，未知完整输出大小继续null，未估计扣除ABI／框架开销。
- 六组新运行共792请求、181ready、611unsupported，2534个正式trial成功，其中2254个native trial逐份验证22540对正式／warmup压缩恢复产物。统计样本是round batch均值，内循环不是独立样本。当前完整测试为372 passed。
- 上述范围、实际输入窗口、来源与限制见[实施报告](implementation.md)、[原生结果](native_results/README.md)及[证据索引](native_evidence.json)。[原生参考笔记](research/native_reference_notes.md)记录实际阅读的lzbench固定来源；未定位可靠TFBench源码，不声称已阅读。用户指定的旧复现包在当前checkout缺失，本轮未使用或验证。

## 全codec direct core扩展：初期开发记录

目标是为现有codec逐项追加真实`tsbench_core_*`入口，绕过原C1／RW对象封装及不必要复制，保持算法必需建模、采样、重置与finalize在计时内；编码输出必须携带独立恢复所需参数、模型、索引与结束数据。统一结果支持caller buffer或codec vector所有权，按实际入口收费与验证。模型加载可以作为prepared context准备，但不能把每次输入相关训练或在线状态更新移出编码。

直接接口、driver所有权与Python调度正在集成，新增入口尚未统一构建或正式测量；既有2534个trial不赋予本轮新实现身份。分组源码阅读、问题和实现进展见[模型与records组](development/core_models_records.md)。

模型与records组的ABBA／fABBA／DeepZip／DZip／Gorilla五入口实现已追加到既有binding TU，尚待统一构建及验证。固定DeepZip模型可prepared加载；DZip默认输入相关模型仍逐次在encode创建，所有codec必要模型与参数保留在完整压缩输出。Gorilla输出owner持有原生Encoder，decoder直接恢复16bytes T/V pairs；详见分组记录。下一项为SIMDComp独立direct core TU，保持width选择在编码时钟内。

SIMDComp研究与独立恢复格式说明见[SIMDComp分组记录](development/core_simdcomp.md)，实现范围保持registry声明的PLAIN参数域，SSE／AVX各有真实内核及明确尾处理。独立baseline C++入口及无timer AVX桥已写入；新增测试覆盖五条参数路径、块边界／极端位宽、独立恢复、错误格式、容量和非自然对齐。测试源码未执行，仍待中央统一构建和验证；不能引用此前测试或性能结果作为新增入口证据。

SIMDComp完整流边界验证拆为`tsbench_core_validate`，由driver在decode主时钟外逐产物调用；decode只执行必要header读取和单遍native unpack，接受此前已验证的不可变产物，允许独立验证context及fresh request新context。SIMDComp、四模型入口与Gorilla新增storage声明，区分caller／owned输出，避免给vector路径预留冗余caller容量；该集成尚待统一验证。

模型组准入进一步拆分：ABBA／fABBA有限值及endpoint算术域、DeepZip模型alphabet附加scan移入`tsbench_core_validate_input`，driver在主计时前单独验证；真实原生算法自身检查／转换保留。DZip输入alphabet决定实际网络形状，其扫描及seeded模型初始化继续在每次encode内，不作为准入缓存。

模型／records专用测试源码已补29个case：四模型的完整输出及无encoder参数／模型独立恢复、owner在context销毁后存活、DeepZip外部副本删除、DZip同context变更真实alphabet；Gorilla两路全部36份归档完整bytes、极端位型及0至65535条count边界。测试按中央安排尚未执行，详情见[分组记录](development/core_models_records.md)。

计划新增§14.19统一direct契约，实施报告和架构README／绘图源同步说明38个CPU key（含raw）的开发目标、storage flags、主时钟外input／stream验证、统一输入身份及历史API／object结果保留。当前只更新绘图源码及Mermaid，不执行SVG／PNG渲染，以免与中央构建争用CPU；中央集成在正式测量前统一渲染并检查布局。新增代码尚无完整测试／正式结果，本轮完成位置已在实施报告前部预留。计划§14.16继续逐字保留。

中央首次全suite为688 passed／3 failed；三个失败均为DZip专用case在Conda主pytest进程加载已构建库时，旧libstdc++缺GLIBCXX_3.4.30。测试改为仅这三项使用既有DZip显式system runtime profile，在新pytest子进程启动前设置preload并核对实际maps，原断言照常运行，父进程要求真实1 passed，不skip、不全局更换runtime，也不改codec／build。修订等待中央三项重跑及全suite；首次失败日志保留在`build/verification/all-core/pytest.log`与`junit.xml`。细节见[模型／records记录](development/core_models_records.md)。

中央后续全suite实际691 passed（69.74s），随后只读源码审阅发现ABBA／fABBA原encode调用transform会生成不被压缩stream消费的quantized decoder pieces和完整N点reconstructed。新增仅对build-local派生源码追加encode_only的两个patch，direct入口调用同一分段／digitize及完整序列化，移除未使用恢复；冻结vendor、原encode／transform、RW／object行为不变。`_rw_build`仅这两个key复制派生并应用patch，现有source闭包自动包含patch与实际派生编译依赖。新增24个合法参数／长度的完整native输出逐字节对照与计时外独立恢复测试，等待中央重建及全suite，691不能回填为该修正验证。详见[模型／records记录](development/core_models_records.md)。


## 直接原生 driver 与统一构建：初期记录

- 新增`tsbench_core`契约：输入为任务物理bytes与dtype/shape/order；原生输出可使用caller buffer或移交vector owner。driver逐份保留所有warmup／正式产物，计时结束后保存并释放；异常路径也在动态库卸载之前释放，context销毁不使结果失效。
- 原生vector不再复制进ABI输出buffer。内存记录同时计入caller预留与已保留原生owner容量，避免把额外持有内存隐去；该数不是瞬时内部工作区或峰值RSS。首次请求包含create、bound和caller分配，prepared将这些准备移至主时钟外。算法每次所需分配与重置照常计时。
- Python core入口发送完整已解析参数及原始物理bytes；独立解码移除encoder参数／模型。Gorilla使用真实T/V交错pairs，分母仅T+V一次；无mask／无channelwise的单序列chunk进入直接批量入口。
- 混合C/C++编译分别保留真实依赖文件，并以C++ linker链接新C++ shim；Elf/Elf+只对build-local副本应用移除内部decode自检的补丁，原frozen vendor与锁保持原样。
- Sprintz新增直接typed路由，原生metadata与精确末尾完整收费。原生wide load/store要求guard scratch，其分配／复制在操作内，padding不进入输出大小或分母。FIRE+Huff0包含完整两阶段、raw/RLE回退及恢复所需stage长度。未调用TSI1/TSF1或C1入口。
- 当前上述改动尚待统一构建与测试；不可引用早期372项测试为新增代码验证。分组细节见[浮点组](development/core_floats.md)、[模型与records组](development/core_models_records.md)及后续字节组记录。

首轮编译发现严格告警阻止构建：Clang把共享JSON解析器的无括号if/for判为misleading-indentation，GCC对bzip2／zlib多语句if亦报错。已通过明确作用域／拆行修复，保留-Werror；这些初期build仅用于定位问题，源文件仍在开发，不作为正式实验身份。driver的raw-store直接批量及独立解码短诊断已成功（129个float64，2次操作+1次warmup），该检查不作性能证据。


边界复核又纠正三项：Sprintz／SIMDComp的完整流准入扫描移至decode主时钟外，快解码只消费已验证且不可变的真实产物；Serf core从生成阶段移除可选FNV，完整必要参数流另用SQC1/SXC1标识，旧C1保留；ABBA／DeepZip／ZFP额外输入源域扫描移至可选input validator，DZip真实alphabet建模仍在encode。driver新增storage flags，只分配实际caller API需要的buffer，vector API首次请求不再承担无用框架分配。跨codec输入ID统一由物理内容及逻辑dtype/shape/layout/components生成，API视角保留为旁记录。首两轮37真实codec构建最终全部通过，但这些边界修正发生在其后，必须再次构建验证。LZSSE8跨adapter共享实现也已纳入recipe source identity，而非只依赖编译后closure。

## 统一验证：首轮

37个真实CPU codec在边界修正后的统一第三轮构建全部成功（raw-store由driver提供）。首轮全套测试为688 passed、3 failed，失败均为新DZip直接ctypes测试在Conda Python进程内加载旧libstdc++缺少GLIBCXX_3.4.30；正式DZip profile原已显式配置系统runtime preload，不能通过静默替换全局runtime或跳过算法掩盖。正在把这三个测试改为具名runtime的独立子进程验证，随后重跑。固定全矩阵的短诊断另存build/verification，不充作正式性能样本；目前bounded、DeepZip、DZip、empirical与entropy诊断均成功。

## 正式运行前最终验证

ABBA／fABBA encode-only修正后，因构建配方源身份变化，统一重新构建37个真实CPU codec，全部成功，记录为`build/verification/all-core/build-final.log`与`build-status-symbolic-final.json`。最终完整suite实际为715 passed、0 failures／errors／skips，70.91s，日志及JUnit为`pytest-symbolic-final.log`与`junit-symbolic-final.xml`。其中新增24项逐字节对照证明direct编码与原native完整stream一致，再在计时外独立恢复；原API行为保留。此前688／3与691结果继续保留各自源码时点。

24组单loop短诊断342 ready／10 unsupported，每个key两个生命周期均有成功案例；额外4组257神经短诊断6／6请求成功，包含DZip COMBINED完整训练及独立重放。诊断另存`build/verification/all-core/`，不作性能证据。正式配置原24加补充4全部不变，源码／构建现已冻结，所有agent停止CPU工作；接下来只由中央依次运行28份配置，正式时间内不并行构建、测试、绘图或profiling，失败与不支持保留原请求分母。

## 正式运行完成与统一审计（2026-10-15）

中央在统一执行源`sha256:9f67a210226e2432d848229b9742fbec0457b89ef905da4073f7ba3dfb830d08`下串行完成28份冻结配置：基础24份／352请求，神经补充4份／6请求，分别保留设计身份。合计358请求、348 ready、10 unsupported，348个ready case全部完整有效；4872／4872正式trial成功，额外attempt为0。每个当前registry key在prepared与fresh_request均有共同输入的完整成功案例，包括37个真实CPU codec及driver raw-store。此次正式运行使用最终37／37构建与715 passed完整suite的源码身份，不借用此前短诊断或首阶段2534trial。

`benchmark/tools/report_all_core_results.py`对冻结设计、配置、manifest、raw、summary、独立资格缓存、源码快照、编译闭包、工具链及实际runtime执行统一严格只读审计并通过，`audit_passed=true`；日志为`build/verification/all-core/report-audit.log`。核对48216对正式阶段压缩／恢复产物记录（38472对正式操作、9744对warmup）与3444对exact资格产物记录（含warmup）。完整压缩文件的大小与hash按实际文件核对；恢复文件已按协议删除，保留digest与逐份计时外验证记录，审计没有重新运行decoder。报告仅将每个session／round batch作为一个样本，loops及warmup不增加样本量。

当前结果为[全量原生报告](all_core_results/README.md)、[请求覆盖](all_core_results/coverage.md)、[审计边界](all_core_results/audit.md)和[独立证据索引](all_core_evidence.json)。主指标继续使用`native_core / prepared / natural`，fresh_request独立展示；有效bytes及完整codec输出遵守计划§14.19契约。合法案例覆盖不外推为全域功能支持，不在不同输入／任务／dtype／布局／质量或线程profile间排名。首阶段`docs/native_results`、API、对象与GPU结果保留原身份。

神经补充案例实际完成不改变计数证据的性质：基础64符号短流为0 predict／0 train，完整257符号每次编解码为193次源码推导的预测；DZip COMBINED另含1个128-window训练batch／1 Adam更新，更新后65次预测，均不是动态counter。DeepZip使用随库固定`biGRU.dzm`，其训练来源本轮未确认；DZip为输入alphabet相关seeded初始模型，每次编码重新初始化。完整模型／参数照实计费，输入相关初始化与在线更新计时。

本次文档收尾同步更新计划§14.18／14.19状态、追加§14.20，并更新README与实施报告当前入口；§14.16保持原文及既有hash，历史raw不改写。静态核对文档链接、`git diff --check`和§14.16 hash；本项未再构建、测试或运行codec。更广真实来源、第二物理机器及第三方复现仍需各自证据，当前缺失的旧私有复现包未被使用或验证。


## 正式结果报告：极小数显示与模型身份说明

正式28组运行完成后，发现DeepZip／DZip的非零MiB/s在Markdown按两位小数显示为0.00。仅调整报告器number()与rate()的文本格式：低于相应小数精度的非零值使用科学计数，完整产物大小、统计计算、排序、CSV数值与原始运行记录均不变；每codec总览与神经路径表复用同一格式。新增4项纯格式回归检查，覆盖极小正负数、真实零／缺失值、正常数字、吞吐中位数及反向四分位区间，全部通过；没有执行codec或重跑性能测量／完整suite。

独立审阅另指出DeepZip随库biGRU来自fixture模型，现有证据不足以溯源其训练过程。报告移除“固定预训练模型”的确定性表述，改为固定随库fixture模型，prepared可预载；证据索引同步记录该范围。此处不改变模型文件、配置或测量身份。

按先前中央授权重新执行严格报告审计，通过：358请求、348完整有效案例、4872/4872正式批次成功，extra attempts为0，正式产物记录48216份、精确资格产物记录3444份；source_id仍为sha256:9f67a210226e2432d848229b9742fbec0457b89ef905da4073f7ba3dfb830d08。重新生成后，primary.csv逐字节相同，SHA-256仍为e658fa100bf489cc9f7abe1510555a699173bba5f453637fdd1b43041288781b；逐案例统计、运行身份、覆盖与输入cohort语义摘要亦完全相同。神经表现可读为DeepZip约3.99e-04、DZip BOOTSTRAP约2.32e-03、COMBINED约4.80e-05 MiB/s（prepared编码），不再显示为假零。

## 最终集成核对与架构图同步

正式计时全部结束后，同步架构README、Mermaid与绘图源的38-key／双生命周期、28配置、358请求、4872成功批次和715项完整测试范围；单独保留首阶段四入口、2534trial及API／对象历史范围，避免误读。重新生成两张SVG并用rsvg-convert更新PNG，逐张视觉检查文字、连线及布局均通过；流程图明确通常loops8、DZip loops2，输入／流安全检查及产物最终释放仍在主计时外。

中央在精度和模型身份修正后再次运行严格报告审计，通过，report-audit.log保存实际输出；没有重跑codec或正式性能实验。独立只读审阅逐行复算348个完整案例的压缩倍数、bits/value和吞吐，核对358请求状态、10项明确拒绝与38-key双生命周期覆盖，未发现未解决数值问题。四份生成报告的实际bytes／hash与证据索引一致，CSV保留原hash。计划§14.16仍为`4fbc96a85ffdd57d8d94fda6e1885f8acc81dab6b73a814186927697476a96b1`，git diff --check通过，新增路径无_v4／-v4标记。

新增[最终验证证据索引](all_core_verification.json)，记录37项成功构建、715项完整suite及其JUnit／日志、之后独立通过的4项纯格式检查、28份正式运行、统一报告审计与图文件hash；它仅索引已有证据，不增加框架运行门槛。全文件文档链接扫描发现39个既有历史run目标当前缺失，清单如实收录，不重写历史正文或虚构恢复文件；当前原生结果链接有效。旧私有复现包仍未取得，DeepZip fixture训练来源未确认，广域／跨机／第三方复现未获新证据；本轮完成范围为本机冻结输入、参数、质量及资源约束下的现有CPU codec直接原生闭环。

## ALP / ALP-RD 替换为独立 safe-v1（2026-10-17）

问题与依据：此前[一致性核对](alp_consistency_20261017.md)确认 Bench 使用旧 forced decimal／forced RD 和三项补丁，未消费本次独立验收 safe-v1；数值边界、安全处理和完整格式均有差异。用户明确要求删除旧接入并使用同级 `Compression_Rewrite` 的独立发布包。依据 V3.0 的路线／交接／证据失效条款（§114–116）、V4 默认 native_core 契约，以及独立 README、QUALIFICATION、CONTRACT、HANDOFF 和真实 C API 实施，不将文档中的完整重写或正式性能流程误当额外用户授权。

处理：旧 adapters/alp、两张 codec card 和来源登记先保存到[替换前归档](alp_integration/legacy-alp-before-safe-v1.tar.gz)，包含当时未提交 direct 修改；删除活动旧 vendor 和三个补丁。发布包消费的56个文件按归档成员逐文件冻结，核心／API／码流保持原字节。新 shim 调用 `alp_port_*`，alp 自适应 ALP/RD，alp-rd 强制 RD；direct 为完整 ALPRW001，caller 两方向存储。辅助 C1 使用 TAI1→APS1 列容器，保留原子失败、一次零字节 finalize／reset；完整 API 成本按实际边界计时。构建前逐文件校验冻结源；更新 source/card/implementation 身份，bridge 明确拒绝旧同名库。其他 codec 既有修改保留。

实际验证：独立 CMake reference 的3项 ctest通过；targeted155项和完整798项 Python测试全部通过，无失败／跳过。与独立新构建 safe-v1 的完整差分为284 case、10,004,036个处理值，完整字节相等、双向解码、C1 frame相等和逐位恢复；28次reference CLI冷恢复。两个方法×core/API×prepared/fresh的8个短批次组合逐份验证。两个方法完整绑定／核心 sanitizer各22个dtype／长度case通过。初次LSan在ptrace环境退出失败的日志保留，随后同二进制在非ptrace环境启用detect_leaks=1成功，未禁用LSan。16个对象组合覆盖f32/f64、C/F、整块／分列分块，全部由新进程CLI恢复；补充[重放脚本](alp_integration/qualify_objects.py)并实际复验。

范围：本次只开放 portable／SCALAR、LP64 little endian、单线程 f32/f64；不签上游FULL_PARITY。native_core完整ALPRW001大小可核实，辅助native_api主空间指标保持null；内部API分配／采样／CRC仍计时，不把caller输出存储称零分配。未重跑FORMAL性能、AVX2、ARM/QEMU、TSan或fuzz，不继承独立包对应PASS；旧正式RunSet保留原身份。当前源码／二进制与详细日志hash、复验命令、边界和限制见[接入报告](alp_integration/README.md)及[证据索引](alp_integration/evidence.json)。

## Chimp 家族研究发布包替换接入（2026-10-17）

问题与依据：用户要求删除现有对应算法，消费独立 chimp-family 发布包。完整阅读 V3.0、V4.0 和包内 README／验证报告／contract／FRAME_FORMAT，先写[接入计划](chimp_integration/PLAN.md)。独立包资格为 RESEARCH_REWRITE_VALIDATED；源码 Swing／Quantized 存在已知误差和单点非有限行为，不能当通用 bounded codec 或 FULL_PARITY。

处理：旧 Chimp vendor、两张卡、共享 shim（含原有未提交修改）和冻结清单先归档；旧来源清单另归档；移除活动 Chimp 分支及源资产，保持 Elf 核心并重建四个 Elf／SElf 入口。发布包 SHA-256 为 7161320b6df76d07dc397a1199ca6341012e088ffebb5d10173cbbc11caf46dc，62个消费／参考文件逐成员哈希核验并写成普通文件，未修改核心或硬链接原件。新增 chimp、chimp32、chimp128、chimpn、chimp128-no-index、chimpn32、pmc-mr、swing-filter、swing-filter-disjoint、swing-filter-disjoint-quantized；新 source／build／binding 身份拒绝旧同名库。f32/f64显式区分，Chimp128固定为ChimpN(128)，FPC／filter2不注册。

接口：默认 core 调用真实 owning-vector API，staging／对象创建与reset／完整CFP1／重构和strict检查在操作中，两方向owned结果在context销毁后存活。无损保留分块与准确尾块；C1／对象以CFI1→CFS1独立列容器保存完整CFP1，冷解码不依赖编码器设置，严格检查长度／CRC／网格／方法／类型及shape，完整输出计费。错误路径改用固定消息缓冲区；原子失败、容量重试、零字节finalize和reset分别验证。极小正epsilon最初被stod归为codec错误，已明确作为unsupported拒绝，Python和原生都不接受float32下溢。

有损边界：有限f32、单位索引时间轴；core限单列，API／对象支持矩阵独立列。默认strict_abs调用源码实际重构检查，兼容模式只准empirical_quality；实际任务另做质量检查，不承诺普适界，也不开放未经资格的相对界。从实际CFP1头／CRC恢复epsilon，保留decimal请求、f32参数和任务界的区别；quality_mode注明来自请求而非帧。补充默认参数测试，避免只写epsilon或省略参数时质量记录缺字段。Java算术NaN可规范化，有限值及正负零保持位比较。

实际验证：独立CMake reference契约／分配失败ctest 2/2；最终完整Python **962 passed**。最终新Java编译／源码差分＋归档Java基线＋独立C++CLI冷恢复，经Bench核心完成 **11537个接入案例／5679407个输入值**，含Chimp128别名重复；8个独立非PASS、2557个未请求方法、11个非128 no-index和24个外部时间戳案例明示排除。123个源码质量失败案例全部strict拒绝，兼容模式保留原行为。40对象组合C/F×整列／分列分块均由新进程CLI恢复；40组key×core/API×prepared/fresh实际检查120份产物和独立冷恢复，所有完整大小及bits/value核对。最终绑定64个ASan+UBSan+LSan案例通过，detect_leaks=1、stderr为空；10个key各实测1048576值常量输入逐位冷恢复并拒绝1048577。固定源码、真实编译依赖／runtime／类文件及当前artifact身份见[报告](chimp_integration/README.md)和[索引](chimp_integration/evidence.json)。

配置：新增按dtype／质量分组的三个Chimp示例；全core设计生成器分开32/64位与有损域，保留旧冻结设计，当前真实CPU key为45（另有raw-store）。本轮不运行FORMAL性能；已有37+1个入口的历史吞吐不能改签为这批新实现。不继承独立包Clang／ARM／fuzz／TSan／可复现构建资格；本地研究许可事实及到期2026-11-17保留，不推断分发授权。大块源码每值reserve可能有频繁分配成本，未旁路或修改冻结行为。ALP、Gorilla及其他既有工作区修改保留。


## Sprintz 原生发布包替换接入（2026-10-17）

用户要求完整阅读两份总规范和独立Sprintz说明／验收报告后替换全部旧Sprintz算法，后续再次明确不保留旧入口。先完成[N0计划](sprintz_integration/PLAN.md)；归档旧adapters/sprintz（含未提交direct_core和bounded修改）、五卡、三来源卡、旧配方后删除活动资产，原旧build indexes单独保留后移除。当前只有四个主键，*-u8及fire-huff0不保留别名。新source/binding/build身份和bridge manifest拒绝旧同名库。其它ALP、Chimp、Gorilla和工作区既有修改保留，ELF前期核对尚未替换代码。

消费发布包SHA757789b014f2e5f7804ea88b68ce22bc3b5f86b9121626861c2c7209f4e5e624，1593文件逐成员核验，核心无修改；原版oracle源码分开保存，不链接进production。Linux x86_64、AVX2/BMI1/BMI2/LZCNT/POPCNT、8/16位、1–128维、64KiB上限；API/binding基线TU与ISA核心分开编译并CPUID拒绝。只开放已验收path，不扩展query／float量化／外部分块。core原始物理输入，两方向caller输出，安全API内部暂存／scan／分配计时；SZF1完整24字节恢复头及原样payload两边界都计费，冷decoder参数为空也可恢复。C1一次compress+零字节finalize，原子失败／容量重试／reset分别验。

新构建未修改原版oracle与独立发布库+Bench：774差分，722字节一致、52为raw16截断修复；补回已写尾字节后一致并port→source恢复，52原版截断流安全API和Bench均拒绝、输出不变。76canonical/真实三计数列整数、297专项和1259完整Python测试通过。32对象C/F×8/16位×整块／分列分块由新进程CLI恢复；32原生边界／生命周期／dtype组合保存96份产物并独立冷恢复。绑定96 ASan/UBSan/LSan案例在非ptrace环境detect_leaks=1通过、stderr为空。初次隐藏导出失败、短拷贝没有native scratch分配导致错误故障断言、LSan ptrace环境失败全部保留，不混入PASS。

四份历史native-all整数设计按原hash保留，新配置移到独立目录并使用新output身份；其他当前示例迁移四主键，新增四算法示例，全core生成器更新四主键和未来设计日期。当前44真实CPU key+raw-store。正式性能未重跑，未继承FULL_PARITY、独立包跨编译器／TSan／fuzz，历史结果保持原身份。[完整报告与证据](sprintz_integration/README.md)。

## 当前字节算法与 lzbench 一致性审计（2026-10-17）

按用户请求审计 Zstd、LZ4、Snappy、zlib、Brotli、BZip2、XZ、两种 LZSS 和 LZSSE2/8；没有替换算法。固定本地 lzbench fa871e66 工作区，606/606 vendor 文件哈希相同，另记录构建时 LZSSE 安全补丁与执行配置差异。独立编译原 lzbench wrapper／源码库，不用同一 Bench 库作参考；XZ reference 库的 CMake 配置差异明示，未运行性能主程序。

702 组当前主路径组合和 110 组 C1 全部往返通过；主路径逐份 warmup／measurement 精确验证及独立进程冷恢复。624 组参考双向恢复中585组对应 lzbench wrapper（LZSSE 去除／重建8字节原长头），39组是补充 LZ4F 对照。匹配参数的 Snappy／zlib／Brotli／BZip2、关闭checksum的Zstd和LZSSE raw payload字节相同；LZ4 frame对raw block、XZ easy对MT stream、默认Zstd checksum与LZSSE framing均使完整方法不同。Brotli空流C1=3b、主路径／lzbench=06，均1byte且可恢复。两种LZSS不在该lzbench登记表；alexkazik原作冻结向量282/282回放通过。相关现有测试127 passed、无skip；没有重跑FORMAL、sanitizer/fuzz或跨架构资格。新增可重放审计工具及[逐项报告／证据](research/lzbench_consistency_20261017/README.md)，历史运行、设计及其他既有修改保留。

## LZSS 标记异常并排除（2026-10-17）

用户明确要求暂停LZSS使用并标记“算法接入异常，处于排除状态”。两种LZSS登记（lzss-raw、lzss-dipperstein-c）均设admission=EXCLUDED，统一中文原因。新增可检查登记但默认不可选择的状态门禁：三测试边界、组件路由、显式构建／bridge加载／操作全部拒绝，报告status=excluded、stage=registry.admission；build --all、当前示例与未来生成器不选用。CLI codecs保留状态和原因，参数／来源查询可用。LZSSE2／8继续开放；当前42个可用真实CPU codec+raw-store，44个真实登记中2项排除。

既有源码／二进制／历史原始结果及冻结配置保留，不将此前只读审计改签恢复失败。通用测试和C ABI交叉探针改用仍开放的Snappy／LZSSE2，新增排除策略回归。专项142 passed；完整Python回归1255 passed、4 subtests passed，无失败或skip。见[排除记录与日志](lzss_exclusion_20261017.md)。本次不产生性能结果、不解除其他算法的既有限制。


## ABBA / fABBA / QABBA 独立发布包替换接入（2026-10-20）

用户要求完整阅读交付md后删除旧ABBA/fABBA，接入三算法。先写[N0计划](abba_family_integration/PLAN.md)，旧vendor/四补丁/两source卡/原共享binding与构建配方、辅助溯源和测试、旧indexes归档；随后移除活动分支，DeepZip/DZip保留并重建。新三卡、source/binding/build身份与C1 manifest拒绝旧库，不改历史设计和正式结果。冻结发布包SHA ec70b59fd9e0a48303604596df43fa8e21090b6f577513f11894e727a6240b1e，7830消费/参考成员不改核心，保留LGPL >=3 CKmeans及JSON安全补丁、完整许可证和重链接源码。

主core为binary64单列owning API，C1/对象为独立列矩阵；完整AFS1/AFM1计费，冷decoder无编码参数或外部模型。每对象拟合、staging/模型/符号编码/CRC/序列化/恢复检查在计时内，bound不拟合；原发布encoder的fit重建工作照实保留。FE_TONEAREST、无fast-math、关闭contraction，最多1048576总值、4096列、256MiB完整帧，单worker。只开放empirical_quality；不开放模型复用/共享多序列拟合/图像/缺失填充等未接入路径。ABBA min_k=1是明确Bench默认；fABBA alpha变为新源码默认0.5；QABBA宽度1..64与九种非上下文符号编码按登记开放。源码重建长度变化的对象提交前unsupported，不做补点或重采样，额外检查计时。

独立CMake参考/native_safety ctest1/1，187组/26670值源码与完整frame对照中144成功、43预期QABBA网格拒绝；原120数据对象全部纳入，99成功/21拒绝。所有成功逐字节与独立CLI一致、双向恢复、C1一致，Python源码数值abs/rel 1e-10对照；拒绝另验源码长度。12组主边界×生命周期保存并验证36产物，24对象C/F×列/块组合新进程恢复。绑定+独立重编发布核心的ASan/UBSan/LSan147例通过，宿主detect_leaks=1、stderr为空；其共享链接控制不冒称生产二进制本体开启sanitizer。最终完整1387 passed、4 subtests passed，0失败/skip，88.78s。

首次外层Threads目标缺失、Autotools改写14个distribution文件（已恢复后转私有副本）、Unicode splitlines拆JSON、旧测试误认QABBA网格及两处旧42键断言、LSan沙箱ptrace失败均保留诊断。每生产库实际依赖735项，含Autotools.Plo；字节库静态本地符号，不覆盖其它codec。当前43可用真实CPU key+raw-store、45登记中LZSS两项继续排除。未来生成器加入QABBA，新示例明确QABBA max_len=1，三方法ETTh1 256值实测通过。未运行FORMAL，不继承独立包跨ISA/fuzz/OOM/可复现构建资格。见[报告](abba_family_integration/README.md)与[证据索引](abba_family_integration/evidence.json)。
