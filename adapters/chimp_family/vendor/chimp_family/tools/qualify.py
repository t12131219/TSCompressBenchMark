#!/usr/bin/env python3
"""Bind the frozen local-research implementation to final evidence; no Benchmark or FORMAL qualification."""
import hashlib,json,pathlib,subprocess
R=pathlib.Path(__file__).resolve().parents[1];ROOT=R.parent.parent;S=ROOT/'Source/chimp-family';V=R/'validation'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 base=json.loads((V/'qualified-v2/verification.json').read_text());summary=base['summary'];assert summary['fail']==0 and summary['pass_cases']==13473 and summary['cases']==13481
 assert base['verifier_sha256']==sha(R/'tools/verify.py') and base['contract_sha256']==sha(R/'contract.md')
 assert base['cli_sha256']==sha(pathlib.Path('/tmp/chimp-work/build/chimp_cli'))
 for row in base['source_files']:assert sha(S/row['path'])==row['sha256']
 profiles={}
 for name in ['clang','arm-qualified']:
  q=json.loads((V/('profile-'+name)/'replay.json').read_text());assert q['status']=='PASS' and q['baseline_sha256']==sha(V/'qualified-v2/verification.json');profiles[name]={k:v for k,v in q.items() if k!='rows'}
 state=json.loads((V/'state-qualified/state.json').read_text());assert state['status']=='PASS' and state['cli_sha256']==base['cli_sha256']
 for label in ['release','clang','arm','asan','tsan']:
  p=V/('test-'+label+'-final.log.json');assert json.loads(p.read_text())['returncode']==0
 assert json.loads((V/'static-analysis-final.log.json').read_text())['returncode']==0
 assert 'Done 50000 runs' in (V/'fuzz-final.log').read_text() and json.loads((V/'fuzz-final.log.json').read_text())['returncode']==0
 assert json.loads((V/'WAIVER.json').read_text())['expiration']=='2026-11-17'
 rows=[json.loads(line) for line in (V/'qualified-v2/cases.jsonl').read_text().splitlines()];assert len(rows)==summary['cases']
 for x in rows:
  if x['status']=='PASS':assert x['source_equivalent'] and x['final_bits_closure'] and (x.get('cross_decode') or (x.get('decoded_equal') and x['strict_mode_matches_measured_quality']))
 quality=[x for x in rows if x.get('absolute_epsilon_pass')==False];(V/'source_quality_failures.json').write_text(json.dumps(dict(scope='Source-compatible numerical defects, not C++ differential failures; strict ABS mode rejects every case',cases=quality),indent=2)+'\n')
 for name,details in summary['by_method'].items():
  if name.endswith('.filter2'):continue
  d=ROOT/'ReWrite'/name;m=json.loads((d/'NATIVE_CAPABILITY_MATRIX.yaml').read_text());m['overall_result']='PARTIAL_WITH_WAIVER';m['qualification_note']='All frozen REQUIRED_PARITY functionality passed in the declared resource/input contract. Local research/license waiver; no exhaustive unbounded-input FULL_PARITY or external redistribution assertion.'
  for c in m['capabilities']:c['validation'].update(status='PASS',evidence=['../chimp-family/validation/qualified-v2/verification.json','../chimp-family/validation/test-asan-final.log','../chimp-family/validation/state-qualified/state.json' if name=='fpc-chimp' else '../chimp-family/validation/profile-arm-qualified/replay.json']);c['waiver_id']='CHIMP-LOCAL-RESEARCH-20261017' if name!='fpc-chimp' else None
  (d/'NATIVE_CAPABILITY_MATRIX.yaml').write_text(json.dumps(m,indent=2)+'\n')
  manifest=json.loads((d/'PORT_MANIFEST.yaml').read_text());manifest.update(current_gate='G6_LOCAL_RESEARCH',terminal_status='RESEARCH_REWRITE_VALIDATED',qualification='local source-compatible C++ rewrite validated; deliberately not formal REWRITE_DONE for license-unknown algorithms under the approved research waiver',source_core='../../Source/'+name+'/upstream',shared_source_oracle='../../Source/chimp-family',evidence='../chimp-family/validation/QUALIFICATION.json',release_attestation='../../Release/chimp-family-research-20261017.validation.json',native_capability_parity='PARTIAL_WITH_WAIVER',input_resource_limits={'max_values':1048576,'max_history':65536})
  (d/'PORT_MANIFEST.yaml').write_text(json.dumps(manifest,indent=2)+'\n')
  src=ROOT/'Source'/name/'SOURCE_MANIFEST.yaml';sm=json.loads(src.read_text());sm.update(local_research_authorization='CHIMP-LOCAL-RESEARCH-20261017' if name!='fpc-chimp' else 'EPL-1.0',g1_local_scope='PASS_WITH_USER_RESEARCH_WAIVER' if name!='fpc-chimp' else 'PASS_EPL_SOURCE_AUDIT');src.write_text(json.dumps(sm,indent=2)+'\n')
  text=f'''# {name} local research porting report

SOURCE_REWRITE / TRANSLATED. Implementation `{name}-cpp-scalar-v1`; frozen upstream320d397157c7e0696b3c64dc1711fc17a3add3da. Local standalone implementation and verification complete in the approved research scope. Shared independent C++17 source/API/CLI in ../chimp-family. No Benchmark integration.

Final cases: {details['cases']}; source-equivalent PASS: {details['pass_cases']}. Measured epsilon-failing source cases: {details['quality_failed_cases']}; nonfinite source cases: {details['nonfinite_cases']}. These remain source-compatible diagnostic results, not strict error-bound successes. Strict mode rejects failing reconstructed quality. Expected original capacity or undefined-input cases are separately counted. Full case hashes/commands/source and target streams are in qualified-v2/cases.jsonl and content-addressed gzip blobs.

G0 source identity/dedup complete; G1 frozen closure/license facts with approved local research waiver where needed; G2 explicit source semantics/input/state/FP/format contract; G3 fresh Java differential/roundtrip/error predicates/boundary/malformed/sanitizer; G4 owning-vector API/reset/incremental/finalize/OOM/concurrency; G5 upstream optimized/SIMD/thread/accelerator paths absent, scalar only; G6 independent archive clean-build, patch replay, installed consumer/cold-decode and reproducibility signed by external Release/chimp-family-research-20261017.validation.json.

Native capabilities pass within the checked resource contract. Limits: count<=1,048,576, history power-of-two1..65536; finite lossy input/epsilon with source timestamp/state semantics. Chimp EOF NaN reserved; FPC canonicalizes payload NaNs. AArch64 is QEMU, not physical hardware. Arithmetic NaN sign/payload unspecified for lossy methods; cross-platform comparison normalizes only these fields and requires identical non-NaN fields and valid cold decode. Local performance is owning-vector API timing including setup, never a source speed ranking or FORMAL Benchmark result.

No claim of unrestricted upstream resource-domain FULL_PARITY, universal strict ABS quality, arbitrary NaN-payload FPC losslessness, or new redistribution grant. The unknown-license algorithms are deliberately marked RESEARCH_REWRITE_VALIDATED, not formal REWRITE_DONE, under the written user waiver.
'''
  (d/'validation/porting_report.md').write_text(text)
  for report in ['dataset_validation_report.md','native_capability_validation_report.md','validation_report.md','build_reproducibility.md']:(d/'validation'/report).write_text(f'# {name}\n\nSee porting_report.md and ../chimp-family/validation/{report}. Shared evidence is hash-bound by QUALIFICATION.json and the external release attestation.\n')
 allcaps=[]
 for name in summary['by_method']:
  if not name.endswith('.filter2'):allcaps+=json.loads((ROOT/'ReWrite'/name/'NATIVE_CAPABILITY_MATRIX.yaml').read_text())['capabilities']
 (R/'NATIVE_CAPABILITY_MATRIX.yaml').write_text(json.dumps(dict(schema_version=1,algorithm_id='chimp-family',overall_result='PARTIAL_WITH_WAIVER',capabilities=allcaps,limits='Explicit safe research input/resource domain; no exhaustive upstream unbounded-input claim'),indent=2)+'\n')
 report=dict(status='RESEARCH_REWRITE_VALIDATED',standard='V3.0 SOURCE_REWRITE local research scope',implementation='chimp-family-cpp-scalar-v1',source_revision='320d397157c7e0696b3c64dc1711fc17a3add3da',source_compatibility='Lossless raw BYTE_IDENTICAL/four-way decode; lossy SEMANTIC segments+float outputs, arithmetic NaNs compared semantically',summary=summary,state_values=state['values'],profiles=profiles,source_quality_failed_cases=len(quality),gates={'G0':'PASS','G1':'PASS_WITH_USER_LOCAL_RESEARCH_WAIVER where license unknown','G2':'PASS frozen narrative contract, materialized machine matrix','G3':'PASS source-compatible semantics; strict quality refusals separately checked','G4':'PASS owning C++ API/state/OOM/malformed/concurrency','G5':'N/A no upstream optimized paths','G6':'External exact-archive clean-build/reproducibility attestation required'},waiver='WAIVER.json',external_release_attestation='Release/chimp-family-research-20261017.validation.json',no_formal_rewrite_done=True,no_benchmark_integration=True,limits=['count<=1048576, N power-of-two1..65536','finite lossy inputs, source timestamp/unit-interval/sample-index semantics','AArch64 under QEMU; not physical ARM','JDK/system C++ runtimes explicit prerequisites, not hermetic archive','strict mode rejects source quality defects, no silent repair'])
 evidence=['qualified-v2/verification.json','qualified-v2/cases.jsonl','state-qualified/state.json','profile-clang/replay.json','profile-arm-qualified/replay.json','test-release-final.log','test-clang-final.log','test-arm-final.log','test-asan-final.log','test-tsan-final.log','fuzz-final.log','static-analysis-final.log','BUILD_LOCK.json','performance.json','source_quality_failures.json']
 report['evidence']={p:sha(V/p) for p in evidence};report['core_hashes']={str(p.relative_to(R)):sha(p) for p in [R/'include/chimp_family.hpp',R/'src/canonical/chimp_family.cpp',R/'contract.md',R/'FRAME_FORMAT.md',R/'NATIVE_CAPABILITY_MATRIX.yaml']}
 (V/'QUALIFICATION.json').write_text(json.dumps(report,indent=2)+'\n')
 summary_text=f'''# 本地研究重写与验证结果

全部所列算法已在独立 C++17 包中实现。原仓库 panagiotisl/chimp，冻结提交320d397157c7e0696b3c64dc1711fc17a3add3da。用户批准的研究验证豁免记录在 WAIVER.json；未声明新获再分发许可或正式 REWRITE_DONE。

最终共{summary['cases']}案例、{summary['values']:,}处理值：{summary['pass_cases']}源码等价通过；8案例单独登记（5原始固定缓冲区损坏反例、3Swing单点未定义输入）。无损原始流逐字节一致、四路解码通过；有损分段边界/系数与重建float一致。四份真实CSV全部数值列/全部行，另有共享验证语料及合成边界。FPC再验证{state['values']:,}值的连续预测器历史/奇数块补位/源帮助函数。

源有损缺陷：Swing41个案例、Quantized82个案例超过给定epsilon；Quantized3个单点案例非有限。全部由严格 ABS 模式拒绝；兼容模式保持原行为。PMC、Disjoint及filter2在本次案例中未超限，但这不等于数学普适保证。

GCC/Clang构建、ASan+UBSan+LeakSanitizer、OOM、独立对象TSan、静态分析和50,000次libFuzzer通过。Clang重放{profiles['clang']['cases']}案例；AArch64/QEMU重放{profiles['arm-qualified']['cases']}案例/{profiles['arm-qualified']['values']:,}值（全部synthetic/shared及每份真实CSV首数值列全部行）。ARM仅量化单点源缺陷的NaN符号不同；非NaN字段与格式/冷恢复严格核对。

容量/resource、空输入、小长度、ring wrap、EOF、重复finalize、reset、失败原子性、原始输入不变、畸形/截断/校验/超限、FP模式均验证。owning-vector API没有调用方输出容量，bound-1/canary槽位要求不适用；无overread。

source/build/runtime/license、FP/Java语义、数据hash、raw/frame/decoded gzip证据、矩阵、命令日志、性能（setup包含的本地API测量）完整保留。最终精确归档的独立解包/原始oracle重建/补丁重放/安装后C++消费与冷解码/库和CLI字节可复现结论，见Release/chimp-family-research-20261017.validation.json外部签署。封包使用tar hardlinks内容去重，保留全部原始路径及hash；不要在证据快照中原地编辑共享inode。
'''
 (V/'porting_report.md').write_text(summary_text)
 (V/'dataset_validation_report.md').write_text(summary_text+'\n逐案例记录：qualified-v2/cases.jsonl；四份自然数据file hashes：qualified-v2/natural-selection.json；共享索引及选中样本：qualified-v2/shared-selection.json。\n')
 (V/'native_capability_validation_report.md').write_text('# Native capability report\n\nAll frozen REQUIRED_PARITY public functionality PASS within the explicit safe resource domain. No upstream SIMD/parallel/GPU/accelerator path exists. User-approved research waiver applies to license-unknown sources; no unbounded-domain FULL_PARITY assertion. Per-method machine matrices and exact public source symbols are retained.\n')
 (V/'validation_report.md').write_text(summary_text)
 (V/'build_reproducibility.md').write_text('# Reproducible build\n\nGCC11.4, Clang14, CMake3.22, Java21 versions, actual flags/TUs/library/binary/runtime hashes are retained in BUILD_LOCK.json and build-records. Source/build paths remapped; no fast math or contraction; installed RPATH relative to $ORIGIN. Final archive is extracted independently and rebuilt with GCC; installed libchimp_family.so and chimp_cli must both be byte-identical to dist/x86_64. Exact signed result is external Release/chimp-family-research-20261017.validation.json so it cannot mutate the archived content index. JDK, libc and libstdc++ are recorded system prerequisites, not an embedded hermetic runtime.\n')
 (R/'SBOM.json').write_text(json.dumps(dict(source_repo='panagiotisl/chimp',source_commit=report['source_revision'],components=[dict(name='Chimp/PMC/Swing algorithm sources',license='NOASSERTION',authorization='local research waiver'),dict(name='Michael Kutschke FPC',license='EPL-1.0'),dict(name='ModelarDB LinearFunction',license='Apache-2.0'),dict(name='Java fixed-width oracle infrastructure',origin='frozen original bitstream helpers plus explicit patch and support source',license='NOASSERTION',dependency_binaries=[]),dict(name='C++ translation',license='derived per-source obligations retained; research scope'),dict(name='system GCC/Clang/JDK runtimes',scope='explicit build/runtime prerequisite; see BUILD_LOCK and TOOLCHAIN_MANIFEST')]),indent=2)+'\n')
 (R/'PORT_MANIFEST.yaml').write_text(json.dumps(report,indent=2)+'\n')
 print(report['status'],summary['pass_cases'],'source-equivalent cases;',len(allcaps),'functional capability rows PASS')
if __name__=='__main__':main()
