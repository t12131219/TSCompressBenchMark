"""Audit current qualification runs without asserting formal performance eligibility."""
from __future__ import annotations

import argparse
import json
from collections import Counter

import numpy as np

from audit_maskedvbyte_run import (
    ROOT, KEYS, audit_supported, audit_unsupported, read_canonical,
    source_and_runtime, require, sha,
)
from tscompbench.codecs import CodecRegistry, SourceRegistry


def audit(key: str, qualification: str, unsupported: str) -> dict:
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest, source, runtime, sdk = source_and_runtime(registry, key)
    fixture = ROOT / "fixtures/datasets/streamvbyte_u32_uts.npz"
    dataset = json.loads((ROOT / "registry/datasets/streamvbyte_u32_uts.json").read_text())
    require(sha(fixture) == dataset["file"]["sha256"], "original fixture drift")
    with np.load(fixture, allow_pickle=False) as archive:
        original = archive["values"]
    require(original.dtype.str == "<u4" and len(original) == 8193, "fixture contract differs")
    run = ROOT / "runs" / qualification
    canonical_paths = list((run / "datasets").glob("*/*.canonical.tscb"))
    require(len(canonical_paths) == 1, "Layer1 canonical artifact absent")
    canonical = read_canonical(canonical_paths[0], include_buffers=True)
    require(list(canonical.buffers.values()) == [original.tobytes()], "source/canonical bytes differ")
    records, streams = audit_supported(run, manifest, source, runtime, False, original)
    rejected = audit_unsupported(ROOT / "runs" / unsupported, manifest, source, runtime)
    result = {
        "status": "PASS", "codec_key": key, "algorithm_id": manifest.algorithm_id,
        "source_artifact_id": manifest.source_artifact_id, "runtime_digest": runtime,
        "qualification_run": qualification, "unsupported_run": unsupported,
        "qualification_attempts": len(records), "unsupported_diagnostics": len(rejected),
        "status_counts": dict(Counter(r["status"] for r in records)),
        "distinct_streams": len(streams), "sdk_audit": sdk,
        "benchmark_five_layers": "QUALIFICATION_ONLY_FORMAL_AUDIT_PENDING",
        "full_logical_entry_qualified": False,
        "qualification_records_sha256": sha(run / "run_components.jsonl"),
        "unsupported_records_sha256": sha(ROOT / "runs" / unsupported / "run_components.jsonl"),
        "audit_dependencies": [{"path": p, "sha256": sha(ROOT / p)} for p in (
            "tools/audit_maskedvbyte_qualification.py", "tools/audit_maskedvbyte_run.py",
            "tools/streamvbyte_audit_common.py", "tools/audit_maskedvbyte_sdk.py")],
    }
    output = ROOT / f"build/source-audits/{key}-qualification-current-audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", choices=KEYS, required=True)
    parser.add_argument("--suffix", required=True)
    args = parser.parse_args()
    require(args.suffix and "/" not in args.suffix and ".." not in args.suffix, "unsafe suffix")
    result = audit(args.key, f"{args.key}-qualification-{args.suffix}",
                   f"{args.key}-unsupported-qualification-{args.suffix}")
    print(json.dumps({k: result[k] for k in ("status", "qualification_attempts", "unsupported_diagnostics")}))


if __name__ == "__main__":
    main()
