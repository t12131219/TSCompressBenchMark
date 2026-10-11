"""Render the current rewrite review only from current, qualified audit entries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[1]


def main():
    audit_path = ROOT / "docs/completed_rewrite_integration_audit.json"
    audit = json.loads(audit_path.read_text())
    assert audit["status"] == "PASS" and not audit["issues"]
    scope = json.loads((ROOT / "registry/algorithm_scope.json").read_text())
    entries = [codec for package in audit["inventory"] for codec in package["codecs"]]
    expected = {key for keys in scope["rewrite_packages"].values() for key in keys}
    assert {entry["algorithm"] for entry in entries} == expected
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    for entry in entries:
        assert entry["integration_status"] == "QUALIFIED"
        assert entry["algorithm_id"] == registry.get(entry["algorithm"]).algorithm_id
        for artifact in entry["artifacts"]:
            assert (
                hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest()
                == artifact["sha256"]
            )
    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    lines = [
        "# 当前重写入口五层接入验收记录",
        "",
        f"本记录限定于机器审计中的 {len(entries)} 个活动入口及其冻结输入、参数和执行闭包。",
        "算法范围以 V3 和 registry/algorithm_scope.json 为准；已退出算法及历史资格不计入当前范围。",
        "",
        f"机器证据：[integration audit](completed_rewrite_integration_audit.json)，SHA-256：`{audit_hash}`。",
        "",
        "| Codec | 原始观测 | 合格摘要 n | 资源排除 | 证据 |",
        "|---|---:|---:|---:|---|",
    ]
    for entry in entries:
        name = entry["algorithm"]
        lines.append(
            f"| {name} | {entry['record_count']} | {entry['summary_n']} | "
            f"{entry['resource_excluded_count']} | [formal](completed_rewrites/{name}-formal.json) |"
        )
    lines += [
        "",
        "所有计划观测均保留，正式摘要须通过重复次数、最短时长、正确性和资源门禁。",
        "该范围资格不等于全部上游能力、全部输入类型、源码全域一致性或真实语料性能排名。",
        "CORE、PIPELINE、E2E 与原生计时须分别记录；缺失的 native timer 不能用 CORE 代替。",
        "完整码流包含实际恢复所需的头部、校验、字典、模型和恢复信息。",
        "",
        "当前输入、参数、ISA、线程、依赖和已知限制见各 registry/onboarding 接入卡。",
        "重新构建或修改执行闭包后，历史 FORMAL 不自动获得新资格。",
        "",
        "## 复现",
        "",
        "```bash",
        "PYTHONPATH=src python tools/qualify_completed_rewrites.py --mode FORMAL --repetitions 20 --suffix fresh-formal",
        "PYTHONPATH=src python tools/verify_completed_rewrite_integration.py --suffix fresh-formal --dzip-suffix fresh-formal",
        "PYTHONPATH=src python tools/write_completed_rewrite_review.py",
        "```",
        "",
        "验收依据：[V3](../TimeSeries_Compression_Benchmark_V3_工程实施总计划.md)。",
        "",
    ]
    destination = ROOT / "docs/completed_rewrite_integration_review.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
