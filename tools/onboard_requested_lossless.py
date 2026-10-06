"""Record source admission and hashed native build evidence for frozen standalone APIs."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    sources = SourceRegistry(ROOT / "registry/sources")
    registry = CodecRegistry(ROOT / "registry/codecs", sources)
    lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
    native = json.loads((ROOT / "build/rewrite_review/native-abi/report.json").read_text())
    assert native["status"] == "PASS"
    assert native["frozen_lock_sha256"] == sha(ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json")
    for name, entry in lock["algorithms"].items():
        manifest = registry.get(name)
        pkg = entry["package"]
        origin = json.loads(
            (
                ROOT / "adapters/rewrite_lossless/vendor" / pkg / "UPSTREAM_PROVENANCE.json"
            ).read_text()
        )
        source = sources.get(manifest.source_artifact_id)
        records = []
        for profile in ["release", "sanitizer"]:
            folder = ROOT / "build/adapters" / name.replace("-", "_") / profile
            record = json.loads((folder / "build-record.json").read_text())
            assert record["artifact_sha256"] == sha(ROOT / record["artifact"])
            command_bytes = (folder / "compile-command.json").read_bytes().removesuffix(b"\n")
            assert record["compile_commands_sha256"] == hashlib.sha256(command_bytes).hexdigest()
            records.append(
                {
                    "kind": profile,
                    "artifact_sha256": record["artifact_sha256"],
                    "compile_commands_sha256": record["compile_commands_sha256"],
                }
            )
        report_path = (
            ROOT
            / "Compression_Rewrite/ReWrite"
            / pkg
            / (
                "validation/original-public-api/report.json"
                if pkg == "prometheus-xor-chunk"
                else "validation/differential/report.json"
            )
        )
        report = json.loads(report_path.read_text())
        assert report["status"] == "PASS"
        card = {
            "schema_version": "tscb.source-onboarding.v2",
            "source_artifact_id": manifest.source_artifact_id,
            "repository": {
                "chimp": "https://github.com/panagiotisl/chimp",
                "elf": "https://github.com/Spatio-Temporal-Lab/elf",
                "elf-plus": "https://github.com/Spatio-Temporal-Lab/elf",
                "elf-star": "https://github.com/Spatio-Temporal-Lab/SElfStar",
                "self-star": "https://github.com/Spatio-Temporal-Lab/SElfStar",
                "prometheus-xor-chunk": "https://github.com/prometheus/prometheus",
            }[pkg],
            "commit": origin["source_lock"].get("commit")
            or {
                "elf-plus": "64e0d6004be322d9d8eaf9931e371df202f1a0eb",
                "self-star": "457ceb0033e98d516fef42e39d17c9d4b8abbfdb",
            }.get(pkg),
            "dirty": False,
            "submodules": [],
            "implementation_files": [f["path"] for f in entry["files"] if "/src/" in f["path"]],
            "public_api_files": [f["path"] for f in entry["files"] if "/include/" in f["path"]],
            "benchmark_files": ["adapters/rewrite_lossless/native/tscb_rewrite_lossless.cc"],
            "test_files": [
                "adapters/rewrite_lossless/tests/qualification.cc",
                "tests/adapters/test_rewrite_lossless.py",
            ],
            "license_files": source["license"]["files"],
            "third_party_dependencies": [
                {
                    "scope": "NATIVE_SYSTEM_RUNTIME",
                    "name": "Linux C/C++ runtime",
                    "reference_runtime_not_linked": True,
                }
            ],
            "object_level_candidates": [manifest.object_level.value],
            "input_contract": manifest.document["input"],
            "output_contract": {
                "self_contained": True,
                "actual_written_length": True,
                "capacity_is_not_size": True,
                "framing": "TSCB_DESCRIPTOR_SHA256_AND_RWF1_FNV64_CHECKED_STANDALONE_FRAMES",
                "components": "OPAQUE_STANDALONE_CODEC_BYTES_WITH_EXACT_WRAPPER_ACCOUNTING_V1",
            },
            "lifecycle_contract": {
                "output_bound": "FROZEN_STANDALONE_API_BOUND_PLUS_EXACT_WRAPPER_BOUND",
                "return_length": "actual_used_bytes",
                "error_codes": [
                    "DST_TOO_SMALL",
                    "SOURCE_DOMAIN_UNSUPPORTED",
                    "INVALID_ARGUMENT",
                    "CODEC_ERROR",
                ],
                "finalize": "REQUIRED_ZERO_BYTE_FINALIZE",
                "reset": "MODE_ZERO_ONLY",
            },
            "stream_components": [
                "descriptor",
                "descriptor_checksum",
                "native_header",
                "record_headers",
                "standalone_frames",
                "native_checksum",
            ],
            "upstream_tests": [
                {
                    "status": "PASS",
                    "name": "current standalone original differential",
                    "log_sha256": sha(report_path),
                },
                {
                    "status": "PASS",
                    "name": "ASan/UBSan native ABI qualification",
                    "log_sha256": sha(ROOT / "build/rewrite_review/native-abi" / name / "run.log"),
                },
            ],
            "builds": records,
            "license_decision": {
                "spdx": source["license"]["spdx"],
                "status": source["license"]["status"],
                "reason": source["license"]["redistribution"],
            },
            "known_limitations": [
                "PIPELINE/E2E timing supported; native CORE rejected during planning",
                "Full standalone frames charged as opaque bytes; wrapper components exact",
                "No registered query/random-access/incremental Benchmark streaming profile",
                "Preserve source domain; no raw fallback",
                "Standalone multi-block source state preserved in SElfStar sessions",
            ],
            "unsupported_reason_codes": [
                "TRACK_OR_DTYPE_UNSUPPORTED",
                "SOURCE_DOMAIN_UNSUPPORTED",
                "STREAMING_PROFILE_NOT_REGISTERED",
                "QUERY_UNSUPPORTED",
                "VALIDITY_UNSUPPORTED",
                "TIMING_SCOPE_UNSUPPORTED",
            ],
        }
        card = validate_onboarding_card(card)
        (ROOT / "registry/onboarding" / (name + ".json")).write_text(
            json.dumps(card, indent=2, ensure_ascii=False) + "\n"
        )
    shutil.copy2(
        ROOT / "build/rewrite_review/native-abi/report.json",
        ROOT / "docs/requested_lossless_native_abi_qualification.json",
    )
    print("onboarding", len(lock["algorithms"]), "PASS")


if __name__ == "__main__":
    main()
