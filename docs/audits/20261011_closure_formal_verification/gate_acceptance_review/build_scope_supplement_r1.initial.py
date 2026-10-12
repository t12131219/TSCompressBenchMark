"""Append bounded small-receipt evidence without altering frozen acceptance.

No production imports, codec/model execution, builds, performance, individual
trace traversal, binaries or whole-tree hashes are used by this supplement.
"""

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / "docs/audits/20261011_closure_formal_verification"
HERE = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise ValueError(message)


def ref(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    output = HERE / "scope_clarification_build_supplement_r1.json"
    markdown = HERE / "scope_clarification_build_supplement_r1.md"
    index = HERE / "scope_clarification_build_supplement_r1.index.json"
    require(not any(p.exists() for p in (output, markdown, index)), "retain prior supplements")
    paths = {
        "frozen_acceptance_review": HERE / "acceptance_review_r1.json",
        "independent_acceptance_review": AUDIT / "formal_static_review/gate-acceptance-independent-review-r1.json",
        "fresh_deepzip_source_summary": AUDIT / "learned_source_oracle_r1/summary-r2.json",
        "fresh_67_build_summary": AUDIT / "build_link/fresh_profile_summary_r1.json",
        "strict_33_release_summary": AUDIT / "build_link/strict_release_summary_r1.json",
        "all_build_trials": AUDIT / "build_link/all_trial_index_r1.json",
        "build_final_independent_review": AUDIT / "formal_static_review/build-final-summary-independent-review-r1.json",
        "dzip_generated_header_difference": AUDIT / "build_link/dzip-release-generated-header-difference-r1.json",
    }
    inputs = {key: ref(path) for key, path in paths.items()}
    loaded = {key: json.loads(path.read_text()) for key, path in paths.items()}
    original = loaded["frozen_acceptance_review"]
    learned = loaded["fresh_deepzip_source_summary"]
    fresh = loaded["fresh_67_build_summary"]
    strict = loaded["strict_33_release_summary"]
    trials = loaded["all_build_trials"]
    build_review = loaded["build_final_independent_review"]
    dzip = loaded["dzip_generated_header_difference"]
    rows = [g for entry in original["entries"] for g in entry["gates"]]
    require(len(rows) == 220 and len({(g["codec_key"], g["gate"]) for g in rows}) == 220,
            "original gate denominator changed")
    require(original["gate_status_counts"] == {"PASS": 3, "UNKNOWN": 185, "FAIL": 32},
            "original acceptance conclusion changed")
    require(dict(Counter(g["status"] for g in rows)) == original["gate_status_counts"], "counts")
    require(loaded["independent_acceptance_review"]["status"] == "PASS", "independent gate review")
    require(build_review["status"] == "PASS", "independent build summary review")
    require(len(fresh["rows"]) == 67 and len({(r["codec"], r["profile"]) for r in fresh["rows"]}) == 67,
            "fresh build profile denominator")
    require(all(r["fresh_build_closure_status"] == "PASS" for r in fresh["rows"]), "fresh observation scope")
    require(len(strict["rows"]) == 33 and len({r["codec"] for r in strict["rows"]}) == 33,
            "strict release denominator")
    require(all(r["strict_observed_build_closure_status"] == "PASS" and not r["full_N1_granted"]
                and r["old_new_artifact_bytes_equal"] for r in strict["rows"]), "strict scope boundary")
    require(learned["checks"]["source_gpu_actual_execution"] == "PASS_4_CUDNNRNN_STEP_STATS_GPU_NODES"
            and learned["checks"]["CDF_independently_predicted_full15"] == "FAIL_1_OF15_DIFFERENT",
            "fresh GPU observation or retained CDF difference changed")
    require(trials["analysis_receipt_count"] == 177 and trials["analysis_PASS_count"] == 171
            and trials["analysis_FAIL_count"] == 6 and trials["analysis_GAPS_REMAIN_count"] == 4,
            "trial counts")
    result = {
        "schema_version": "tscb.gate-acceptance-scope-and-build-supplement.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "CLARIFICATION_AND_BOUNDED_BUILD_EVIDENCE_APPENDED_NO_GATE_STATUS_CHANGE",
        "driver": ref(Path(__file__)), "inputs": inputs,
        "original_review_preserved": True,
        "unchanged_entry_count": 33, "unchanged_gate_count": 220,
        "unchanged_gate_status_counts": original["gate_status_counts"],
        "DeepZip_G5_clarification": {
            "original_gate_status": "FAIL", "status_after_supplement": "FAIL",
            "meaning_of_complete_required_not_executed": "The complete required source/native optimized capability set is not completed. This never means that every source GPU execution is absent.",
            "actually_completed_source_scope": learned["scope"],
            "actual_source_GPU_and_scoped_comparison_results": learned["checks"],
            "completed_scope_description": "Unmodified pinned source biGRU with exactly assigned current fixed weights, alphabet4 and three contexts executes four actual GPU CudnnRNN nodes. All12 probabilities pass frozen3e-5; identical-source-probability conversion matches15CDF integers exactly.",
            "observed_independent_CDF_difference": "Independently predicted full15CDF has1 differing integer: third arange(64)%4 context final total source10000004/native10000003. This actual semantic difference is retained, not hidden by probability tolerance.",
            "not_completed": ["All required original trained checkpoints and predictor regimes", "Current native GPU required paths and complete source/native same-data differential", "Complete codec/dataset pipeline and full required CAP closure"],
            "r2_command_execution": learned["execution_failures"]["r2"],
            "r1_profiler_execution_failure_preserved": learned["execution_failures"]["r1"],
            "source_bitstream_FULL_PARITY_or_G5_qualified": False,
        },
        "build_evidence_after_original_pending_snapshot": {
            "fresh_unique_profiles": 67, "fresh_limited_observation_PASS": 67,
            "profile_counts": dict(Counter(r["profile"] for r in fresh["rows"])),
            "fresh_scope": fresh["scope"], "fresh_scope_limit": fresh["original_67_profile_scope_limit"],
            "strict_unique_release_builds": 33, "strict_declared_observation_PASS": 33,
            "strict_scope": strict["scope"], "strict_limitations": strict["limits"],
            "shared_artifact_comparison": {"equal": 50, "different": 17,
                "all_33_release_equal": True,
                "association_rule": fresh["association_rule"],
                "source_objects_or_tests_same_not_implied": True},
            "dzip_source_object_and_test_difference": {
                "source_closure_counts": dzip["source_closure_counts"],
                "generated_header_diff": dzip["header_diff"],
                "depfile_consumer_count": dzip["compiler_depfile_consumer_count"],
                "changed_object_count": dzip["changed_object_count"],
                "shared_adapter_SHA_equal": dzip["old_new_shared_adapter_sha_equal"],
                "qualified_test_artifacts_byte_equal": dzip["old_new_qualified_test_artifacts_byte_equal"]},
            "all_trial_receipts": {"count": 177, "base_PASS": 171, "base_FAIL": 6,
                "strict_GAPS_REMAIN_included_not_added": 4,
                "trial_count_not_unique_profile_or_codec_denominator": True},
            "independent_final_summary_review": "PASS_SMALL_RECEIPT_ROW_AND_WORDING_SCOPE_ONLY",
            "actual_full_N1_or_G1_granted": False,
            "historical_execution_reconstructed_or_ID_resigned": False,
            "tests_codec_or_performance_executed_by_build_summary": False,
            "current_gate_impact": "Named new-build exec/open/link observation subitems now have finite PASS evidence. Complete N1/G1, source semantics, API safety, CAP, independent delivery and FORMAL are not transferred or granted.",
        },
        "pending_after_supplement": [
            {"item": "FULL_N1_G1", "status": "PENDING", "reason": "Complete actual closure contract, all consumption versions and historical association are not proven by exec/read-capable OPEN initial-version scope."},
            {"item": "FULL_REQUIRED_CAP_G3_G4_G5_G6", "status": "PENDING_OR_RECORDED_ACCEPTANCE_FAIL_AS_IN_FROZEN_REVIEW", "reason": "Required source/function/API/optimized/release contracts remain unclosed; DeepZip limited CDF difference remains recorded."},
            {"item": "N5_INDEPENDENT_DELIVERY", "status": "PENDING", "reason": "Isolated independent source/API/driver/build/test/recovery/SBOM/report acceptance remains mandatory and has no FORMAL prerequisite."},
            {"item": "FORMAL_FINAL_MEASUREMENTS_AUX_REFERENCE_AND_INDEX", "status": "PENDING_AT_SUPPLEMENT_FREEZE", "reason": "Parent reports FORMAL execution in progress. This supplement does not inspect or accept unfinished measurement outputs."},
        ],
        "lightweight_review_boundaries": {
            "only_named_small_JSON_inputs_hashed": True,
            "individual_trace_files_or_full_trees_or_binaries_hashed": False,
            "production_modules_imported": False,
            "codec_model_training_build_test_or_performance_executed": False,
            "frozen_src_tools_tests_configs_registry_or_FORMAL_drivers_modified": False,
            "original_220_report_or_main_matrix_modified": False,
            "gate_status_changes": 0},
        "quiet": True,
    }
    require(all(ref(paths[key]) == value for key, value in inputs.items()), "small receipt drift")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    markdown.write_text("""# 门禁范围澄清与最终构建补证 r1

本补证只追加已冻结的小型源差分／构建回执及独立审阅，原 33 入口、220 条报告保持 **3 PASS / 32 FAIL / 185 UNKNOWN**。32 条是完整验收条件未满足的门禁，不是 32 个算法编解码失败。原报告、能力分类、主矩阵和冻结生产文件均未修改。

DeepZip G5 中“完整 required 集合未执行／未完成”的措辞只指完整 source/native 必需能力集合，不能读成源 GPU 全未运行。源 biGRU、alphabet=4、三个上下文已实测四个 GPU CudnnRNN 节点；当前权重 reexport EXACT；12 个概率在原3e-5容差内 PASS（maxabs1.4901161193847656e-08）；相同源概率的15整数CDF转换 EXACT。独立预测完整CDF有真实 **1/15 差异**，第三上下文 total source10000004/native10000003。r2三命令exit0，差异不是crash；r1附加FULL_TRACE缺CUPTI导致abort(-6)仍保留。其余完整 predictor/trained checkpoint/nativeGPU/codec/真实数据与CAP未闭合，G5 FAIL和有限PASS均保持，不授源码流或完整parity。

最终构建回执补充 **67/67 唯一配置有限观察 PASS**（release33、sanitizer33、debug1）及 **33/33 严格release有限观察 PASS**。67项记录exec/open/link map/archive member/外部checkpoint；33项增加exec及内核解释器前后SHA、可读OPEN初始文件版本。没有证明同一描述符写入后读取的全部字节，没有重建历史执行，不授完整N1/G1或source parity。原pending快照保留，新的有限完成证据由本补证追加。

50个新旧共享产物相同、17个不同；33个release均相同。共享库相同不能扩大成整个源树／对象／测试程序相同：DZip有生成mkldnn_version.h差异，98个depfile消费者、1个对象变化，已登记测试程序也不同。177份试验回执（171基础PASS、6基础FAIL；4个strict GAPS_REMAIN已包含）全部保留，不能当成67配置／33算法的分母。构建观察不把CTest清单当测试执行。

FORMAL最终测量、aux/reference成本和完整索引在本补证冻结时仍pending。**N5独立交付不以FORMAL为前置条件**。所有原N/G/CAP状态保持；后续结果仍需以新证据、明确范围及身份单独验收。

[机器补证](scope_clarification_build_supplement_r1.json)保存八份输入SHA与完整计数／限定边界；[生成驱动](build_scope_supplement_r1.py)仅消费小型JSON，不导入生产模块、不遍历单份trace、不执行构建／codec／模型／训练／测试／性能。[独立新索引](scope_clarification_build_supplement_r1.index.json)绑定这次新增文件；原索引未覆盖。该补证已quiet。
""")
    files = [Path(__file__), output, markdown]
    index.write_text(json.dumps({"schema_version": "tscb.gate-scope-supplement-index.v1",
        "files": [ref(path) for path in files], "original_review_unmodified": True,
        "no_gate_status_change": True}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"supplement": ref(output), "index": ref(index),
        "unchanged_gate_status_counts": original["gate_status_counts"],
        "only_small_receipts_read": len(inputs), "quiet": True}))


if __name__ == "__main__":
    main()
