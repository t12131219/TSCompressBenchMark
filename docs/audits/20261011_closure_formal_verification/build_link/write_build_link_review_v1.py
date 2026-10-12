"""Write final limited-scope build audit and actual DZip stage timing receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent
BUILD = ROOT / "build/closure-formal-verification-20261011"


def read(path):
    return json.loads(path.read_text())


def identity(path):
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": sha, "size_bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timing", type=Path, required=True)
    args = parser.parse_args()
    profile_path = BASE / "fresh_profile_summary_r1.json"
    strict_path = BASE / "strict_release_summary_r1.json"
    index_path = BASE / "all_trial_index_r1.json"
    profiles, strict, index = map(read, (profile_path, strict_path, index_path))
    batch_path = BUILD / "traced-builds-r5/special-sanitizer/summary.json"
    batch = read(batch_path)
    timings = []
    for phase in ("discovery", "pinned-replay"):
        row = next(row for row in batch["rows"] if row["codec"] == "dzip" and row["phase"] == phase)
        report_path = Path(row["report"])
        report = read(report_path)
        driver_path = Path(report["driver_report"]["path"])
        driver = read(driver_path)
        stages = []
        for invocation in driver["invocations"]:
            argv = invocation["actual_argv"]
            if "epoch_begin" in invocation:
                stages.append({"kind": invocation["kind"], "actual_argv": argv,
                               "returncode": invocation["returncode"],
                               "epoch_begin": invocation["epoch_begin"],
                               "epoch_end": invocation["epoch_end"],
                               "elapsed_seconds": invocation["epoch_end"] - invocation["epoch_begin"]})
        timings.append({"phase": phase, "batch_elapsed_seconds": row["elapsed_seconds"],
                        "driver_elapsed_seconds": driver["elapsed_seconds"],
                        "batch_minus_driver_seconds": row["elapsed_seconds"] - driver["elapsed_seconds"],
                        "driver_receipt": identity(driver_path), "analysis_receipt": identity(report_path),
                        "stages": stages})
    timing = {"scope": "ACTUAL_COMPLETED_DZIP_SANITIZER_BUILD_STAGE_TIMESTAMPS_NOT_ESTIMATES",
              "batch_receipt": identity(batch_path), "rows": timings,
              "qualification_tests_executed_by_this_timing_receipt": False,
              "ctest_scope": "SHOW_ONLY_JSON_INVENTORY", "driver": identity(Path(__file__))}
    with args.timing.open("x") as stream:
        stream.write(json.dumps(timing, ensure_ascii=False, indent=2) + "\n")

    receipts = [("67 配置汇总", profile_path), ("33 严格发布构建汇总", strict_path),
                ("全部试验及失败索引", index_path), ("DZip 实际阶段耗时", args.timing),
                ("DZip 生成头文件差异", BASE / "dzip-release-generated-header-difference-r1.json")]
    lines = [
        "# 当前压缩器构建与链接闭包复核（2026-10-11）",
        "",
        f"当前 {profiles['active_codecs']} 个算法、{profiles['current_profiles']} 个注册配置均有本次实际子进程构建与链接观察；"
        f"有限观察范围 PASS 为 {profiles['fresh_observed_profiles_PASS']}/{profiles['current_profiles']}。"
        f"严格发布构建覆盖 {strict['unique_actual_release_builds']}/{strict['current_registered_release_codec_count']} 个算法，"
        f"所声明严格门禁 PASS 为 {strict['strict_gate_PASS_count']}/{strict['unique_actual_release_builds']}。",
        "",
        "该结论只适用于本次新构建。67 配置的普通观察保留实际 exec、文件打开、链接 map、archive member 与外部检查点，"
        "其历史 exec/解释器前置 SHA、按进程绑定文件版本缺口没有追溯修复。33 严格发布构建额外验证实际 exec/内核解释器"
        "执行前后 SHA，以及可读 OPEN 时的初始文件版本。没有证明同一描述符写入后的读取字节，也没有重建历史执行。"
        "本报告不授予完整 N1、source parity 或其他 N/G/CAP 门禁。",
        "",
        "| 配置 | 本次观察 PASS / 配置数 | 新旧共享产物字节相同 | 新旧共享产物字节不同 |",
        "|---|---:|---:|---:|",
    ]
    for profile in ("release", "sanitizer", "debug"):
        selected = [row for row in profiles["rows"] if row["profile"] == profile]
        if selected:
            equal = sum(row["old_new_artifact_bytes_equal"] for row in selected)
            passed = sum(row["fresh_build_closure_status"] == "PASS" for row in selected)
            lines.append(f"| {profile} | {passed}/{len(selected)} | {equal} | {len(selected) - equal} |")
    lines.extend([
        "",
        f"冻结注册产物、记录、显式链接输入、元数据、依赖文件、测试产物和注册快照的 SHA 复核："
        f"{'PASS（无漂移）' if profiles['current_registered_artifacts_records_and_registration_frozen'] else 'FAIL（见汇总中的漂移清单）'}。"
        "未覆盖、重签或修改既有记录；新旧产物字节不同的 sanitizer/debug 配置不向旧产物转移新闭包证明。",
        "",
        "33 个严格发布构建的新旧共享库字节全部相同。DZip 的这个一致性结论只覆盖共享适配库："
        "939 项声明源闭包中只有生成的 mkldnn_version.h 不同，MKLDNN_VERSION_HASH 从 "
        "355468119cd20d8ede370f5063839549806c3bb8 变为 6300188e70faf7d93f3a97f87f0d9cebfb7cdf4c；"
        "98 个编译依赖项消费该头文件，verbose.cpp.o 一个对象不同，四个已登记测试可执行文件也不同。"
        "共享库字节相同不等价于整个源树、所有对象和测试程序相同。",
        "",
        "| DZip sanitizer 阶段 | CMake configure 秒 | CMake build 秒 | driver 秒 | 批次含分析秒 |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in timings:
        configure = sum(stage["elapsed_seconds"] for stage in row["stages"] if stage["kind"] == "CMAKE_CONFIGURE_WITH_AUDIT_ONLY_LAUNCHERS")
        build = sum(stage["elapsed_seconds"] for stage in row["stages"] if "--build" in stage["actual_argv"])
        lines.append(f"| {row['phase']} | {configure:.3f} | {build:.3f} | {row['driver_elapsed_seconds']:.3f} | {row['batch_elapsed_seconds']:.3f} |")
    lines.extend([
        "",
        f"全部试验索引保留 {index['analysis_receipt_count']} 份分析回执，其中 PASS {index['analysis_PASS_count']}、"
        f"FAIL {index['analysis_FAIL_count']}；严格分析另有 {index['analysis_GAPS_REMAIN_count']} 份 GAPS_REMAIN。"
        "这些是原始试验数量，不能当作唯一 67 配置或 33 算法的分母。原 XZ 分析失败、严格 collector 的失败 pilot，"
        "以及 r9 错误 codec 名导致的中断均保留；后续隔离试验没有改写它们。",
        "",
        "每份汇总保留实际命令、driver/analyzer 身份、逐配置回执及声明的证明边界。审计辅助 wrapper/helper 仅在新输出树运行；"
        "ldd 使用不带审计 LD_PRELOAD 的环境。本轮构建没有执行正式测量，也没有将 ctest --show-only 清单当作测试运行。",
        "",
        "| 回执 | SHA-256 |",
        "|---|---|",
    ])
    for label, path in receipts:
        item = identity(path)
        lines.append(f"| [{label}]({path}) | `{item['sha256']}` |")
    with args.report.open("x") as stream:
        stream.write("\n".join(lines) + "\n")
    print(json.dumps({"report": identity(args.report), "timing": identity(args.timing)}, indent=2))


if __name__ == "__main__":
    main()
