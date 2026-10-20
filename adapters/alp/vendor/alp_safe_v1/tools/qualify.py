#!/usr/bin/env python3
"""Sign only the frozen bounded native profile from completed fresh evidence."""
import hashlib,json,pathlib
from package_release import selected
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def main():
    real=json.loads((ROOT/'reports/verification-qualified/verification.json').read_text())
    clang=json.loads((ROOT/'reports/profiles-clang-qualified/profiles.json').read_text())
    arm=json.loads((ROOT/'reports/profiles-arm64-qualified/profiles.json').read_text())
    clean=json.loads((ROOT/'reports/standalone-clean-validation.json').read_text())
    assert real['totals']['cases']==284 and real['totals']['fail']==0
    assert real['totals']['raw_byte_identical']==272 and real['totals']['source_UB_frames_rejected']==10
    assert all(all(p['byte_identical'] and p['cross_decode'] for p in c['other_profiles']) for c in real['cases'])
    assert all(c['branches']['RAW']==0 for c in real['cases'])
    assert clang['totals']['cases']==clang['totals']['pass']==clang['totals']['byte_identical']==284
    assert arm['totals']['cases']==arm['totals']['pass']==arm['totals']['byte_identical']==56
    for name in ['release','avx2','clang','asan','asan-avx2','arm64']:
        text=(ROOT/f'reports/test-{name}-qualified.log').read_text()
        assert '100% tests passed, 0 tests failed out of 3' in text,name
    assert 'PASS checks=1' in (ROOT/'reports/test-tsan-qualified.log').read_text()
    assert 'Done 50000 runs' in (ROOT/'reports/fuzz-qualified.log').read_text()
    assert all(x['returncode']!=0 for x in json.loads((ROOT/'reports/source-defects.json').read_text()))
    assert clean['status']=='PASS' and clean['synthetic_totals']['pass']==28
    assert all(x['byte_identical'] for x in clean['reproducible_installed_binaries'].values())
    groups=[
        ('N0','Source selection, deduplicated ALP/RD and complete capability inventory',['docs/SOURCE_LOCK.json','docs/NATIVE_CAPABILITY_MATRIX.yaml','docs/MATRICES.md']),
        ('N1','Frozen MIT source, executable independent original baseline, build/runtime closure',['docs/SOURCE_LOCK.json','reports/BUILD_LOCK.json','SBOM.json','reports/verification-qualified/commands.json']),
        ('N2','Bounded input/FP/state/wire/resource and safety-variant contract; no RAW',['docs/CONTRACT.md','docs/SOURCE_DEFECTS.md','patches/INDEX.json','patches/safe-v1.patch']),
        ('N3','Bitpattern recovery, C ABI, atomic capacity/OOM/malformed refusals, ASan/UBSan/LSan/fuzz/concurrency',['reports/test-asan-qualified.log','reports/test-asan-avx2-qualified.log','reports/test-tsan-qualified.log','reports/fuzz-qualified.log','reports/test-release-qualified.log']),
        ('N4','Fresh independent original-source differential and cross-decode with explicit source UB exclusions; real columns and forced profiles',['reports/verification-qualified/verification.json','reports/profiles-clang-qualified/profiles.json','reports/profiles-arm64-qualified/profiles.json','reports/source-defects.json']),
        ('N5','Independent extracted build, original oracle, exact patch replay, installed cold recovery and reproducible binaries',['reports/standalone-clean-validation.json','reports/patch-replay.log','HANDOFF.md','README.md'])]
    report={'format':'local native qualification report v1 (not registry schema)','standard':'v3.0','date':'2026-10-17','route':'NATIVE_PORT','algorithms':['ALP adaptive','ALP-RD forced'],'implementation':'cwida-alp-native-safe-v1','conclusion':'NATIVE_PORT_QUALIFIED(frozen bounded native profile)','full_upstream_parity':'NOT_CLAIMED','source_commit':real['source_commit'],'contract_sha256':sha(ROOT/'docs/CONTRACT.md'),'gates':[],'fresh_source_totals':real['totals'],'additional_profiles':{'clang':clang['totals'],'AArch64_QEMU':arm['totals']},'limits':['No universal bitstream equivalence on original UB paths; 10 source FACT[10] frames expected rejected, 2 special IEEE adaptive source encodes not run on frozen UB domain.','Original release parity on source UB arithmetic is empirical only; bitpattern and safe output source decode are independent checks.','AVX512 and publication intrinsic fused decoders remain unopened, without a FULL_PARITY claim.','No internal MT, continuous stream, GPU, timestamps/null mask, Benchmark integration or FORMAL performance claim.','System C/C++ libraries and QEMU not sanitizer-instrumented; ARM is emulated, not physical.','n<=2^24 checked resource ceiling; maximum-sized allocation is not asserted tested.'],'build_note':'CLI build RPATH uses $ORIGIN for reproducible relocation; initial candidate had identical library but differing CLI build-id from absolute build paths. Initial failed reproducibility check is preserved in history; final clean binaries both match.'}
    for gate,scope,paths in groups:
        report['gates'].append({'gate':gate,'status':'PASS','scope':scope,'evidence':{f:sha(ROOT/f) for f in paths}})
    (ROOT/'reports/QUALIFICATION.json').write_text(json.dumps(report,indent=2)+'\n')
    summary='''# ALP / ALP-RD 原生移植验收（2026-10-17）

结论：**NATIVE_PORT_QUALIFIED（冻结的 safe-v1 限定 profile）**；N0–N5
全部通过。上游已经是 C++，本任务按 V3.0 §114 完成原生移植与安全修复，
不签署跨语言 REWRITE_DONE 或上游 FULL_PARITY。

七份真实 CSV 的所有数值列/所有行，另含边界与 IEEE fixtures，共 284 个
精度×方法案例、10,004,036 个处理值，全部逐位恢复，RAW 分支数为零。
原版与移植版独立双向解码，并比较完整 raw 对象：272 个字节一致；10 个
原版 float32 factor=10 非法流按安全合同拒绝；另 2 个 IEEE adaptive
原版编码因事前冻结的源 UB 域不运行。拒绝与未执行不计作原版编码成功。

Clang 全部 284 案例、AVX2 全部 284 案例与基线字节一致；AArch64/QEMU
验证 56 案例、1,371,908 值，字节一致且双向解码通过。ARM 子集为全部
synthetic 和每个真实数据集第一数值列的所有行、两精度和两方法。

完整合同集包含 360 个长度×值域×类型×方法回环、容量/guard/未对齐/
畸形/资源/FP 拒绝、240 次 8 线程并发调用，以及 C consumer 和 OOM
注入测试。GCC/Clang/AVX2/ARM、ASan+UBSan+LSan、AVX2 sanitizer、
TSan 和最终 50,000 次 libFuzzer 均通过。逐字节 guard 检查计数不作为
独立测试案例数。外部系统库/QEMU 不在插桩覆盖声明中。

源码原版保留，四类 UB 有独立 UBSan 反例；两个上游头文件的安全修改
具备 exact pre/post hash 和可重放 patch。没有修改 RD 核心。新外层
frame 单独版本化，含完整恢复元数据、字典、exceptions、padding 和 CRC；
FinalBits 为完整文件字节数×8。

独立解压后重新构建、原版驱动、28 个 synthetic 差分、C ABI/失败合同、
补丁重放、安装后的新进程冷恢复通过，libalp_port.so 与 CLI 安装二进制
均逐字节可复现。源/工具链/动态依赖/实际 TU、headers、binary 和证据
hash 见 BUILD_LOCK、SOURCE_LOCK、SBOM、EVIDENCE_INDEX 与发布 manifest。

AVX-512/publication intrinsic decoder、物理 ARM 与上游可变 state 的
公开封装未开放；不宣称 FULL_PARITY。Benchmark 绑定及正式性能比较
是独立后续验收，本任务没有修改其 adapter、registry 或实验结果。
'''
    (ROOT/'reports/QUALIFICATION.md').write_text(summary)
    files={}
    for f in selected():
        if f.is_relative_to(ROOT) and str(f.relative_to(ROOT))!='reports/EVIDENCE_INDEX.json':files[str(f.relative_to(ROOT))]=sha(f)
    (ROOT/'reports/EVIDENCE_INDEX.json').write_text(json.dumps({'format':'local content index v1','files':files},indent=2)+'\n')
    print(report['conclusion'],'N0-N5 PASS;',len(files),'indexed files')
if __name__=='__main__':main()
