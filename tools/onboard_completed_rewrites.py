"""Write validated onboarding cards from current, hashed native qualification evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from build_completed_rewrite import KINDS

from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]
LIMITATIONS = {
    "abba": [
        "Finite binary64, at least two samples; source endpoint arithmetic failures rejected "
        "atomically. Source weighted/symmetric defaults fixed; no universal error bound."
    ],
    "fabba": ["Finite binary64; positive scl; one native worker; no universal error bound."],
    "tristan": [
        "Complete windows only; constant columns and invalid normalization arithmetic rejected. "
        "Per-object dictionary learning and inverse normalization included. Source ignores "
        "requested_n_iter; actual maximum 10 learning iterations with early stop."
    ],
    "corad": [
        "Complete windows only; constant columns and invalid normalization arithmetic rejected. "
        "Per-object dictionary learning, Pearson selection and inverse normalization included; "
        "source maximum 10 learning iterations with early stop."
    ],
    "deepzip": [
        "CPU numerical profile; all 17 frozen model variants verified against native vocabulary "
        "width 4. Native byte alphabet 0..3 only; no byte remapping, CUDA or HDF5 importer in this "
        "profile. External checkpoint loading/hashing included in encode; independent decode "
        "uses embedded model."
    ],
    "dzip": [
        "CPU bootstrap/combined profiles with explicitly seeded, untrained native initial model "
        "based on sorted input alphabet; full weights embedded and charged. No external fitting "
        "or quality claim for a trained model. Source rejects alphabet cardinality 9; empty input "
        "uses declared 256-symbol extension. AVX baseline plus MKLDNN dispatch; process thread "
        "budget 3 for caller and two Eigen one-worker pools."
    ],
    "walloc-1d": [
        "CPU stereo float32 normalized-audio profile, official stereo_5x/stereo_20x models. "
        "Native zero-padding, WebP latent container, embedded full model and cropped "
        "reconstruction retained. No universal error bound; SIMD dependency dispatch, "
        "no scalar-kernel claim."
    ],
    "influxdb-tsm-adaptive-timestamp": [
        "Whole timestamp object, both STREAM and BATCH selectors; no benchmark incremental "
        "streaming/query profile."
    ],
    "prometheus-xor2-chunk": [
        "Joint ST/T/value stream with configured constant ST per object; original ST transitions "
        "are outside this registered profile."
    ],
    "prometheus-histogram-st": [
        "Explicit uint64 bit-field histogram records: gauge hint 3, schema 0, one positive bucket, "
        "no negative/custom buckets. Other native histogram layouts are not registered. "
        "Scalar CSV data is never reinterpreted as histograms."
    ],
    "prometheus-float-histogram-st": [
        "Explicit floating-histogram uint64 bit fields: gauge hint 3, schema 0, one positive "
        "bucket, no negative/custom buckets. Other native layouts are not registered."
    ],
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def provenance(entry):
    text = (ROOT / entry["source_manifest"]["path"]).read_text()
    if text.lstrip().startswith("{"):
        record = json.loads(text)
        return record["repository"], record["source_commit"]
    repository = re.search(r"^repository:\s*(\S+)", text, re.M).group(1)
    commit = re.search(r"^source_commit:\s*([0-9a-f]{40})", text, re.M).group(1)
    return repository, commit


def main():
    lock = json.loads((ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json").read_text())
    sources = SourceRegistry(ROOT / "registry/sources")
    codecs = CodecRegistry(ROOT / "registry/codecs", sources)
    for name in KINDS:
        package = "prometheus-histogram-st" if name == "prometheus-float-histogram-st" else name
        entry = lock["packages"][package]
        manifest = codecs.get(name)
        source = sources.get(manifest.source_artifact_id)
        builds = []
        tests = []
        dependencies = []
        for profile in ("release", "sanitizer"):
            folder = ROOT / "build/adapters" / name.replace("-", "_") / profile
            build = json.loads((folder / "build-record.json").read_text())
            qualification = json.loads((folder / "qualification.json").read_text())
            assert qualification["status"] == "PASS"
            assert sha(folder / "build-record.json") == qualification["build_record_sha256"]
            assert sha(ROOT / build["artifact"]) == build["artifact_sha256"]
            assert sha(ROOT / qualification["log"]) == qualification["log_sha256"]
            builds.append(
                {
                    "kind": profile,
                    "artifact_sha256": build["artifact_sha256"],
                    "compile_commands_sha256": build["compile_commands_sha256"],
                    "build_record_sha256": sha(folder / "build-record.json"),
                    "compiler": build["compiler"],
                    "configure_command": build["configure_command"],
                }
            )
            tests.append(
                {
                    "status": "PASS",
                    "name": f"{profile}: upstream CTest and framework ABI qualification",
                    "log_sha256": qualification["log_sha256"],
                    "log": qualification["log"],
                    "scope": qualification["scope"],
                }
            )
            if profile == "release":
                dependencies = build["runtime_dependencies"]
        repository, commit = provenance(entry)
        card = {
            "schema_version": "tscb.source-onboarding.v2",
            "source_artifact_id": manifest.source_artifact_id,
            "repository": repository,
            "commit": commit,
            "dirty": False,
            "submodules": [],
            "implementation_files": [f["path"] for f in entry["files"] if "/src/" in f["path"]],
            "public_api_files": [f["path"] for f in entry["files"] if "/include/" in f["path"]],
            "benchmark_files": [
                "adapters/completed_rewrites/native/binding.cpp",
                "src/tscompbench/adapters/completed_rewrites.py",
            ],
            "test_files": [
                "adapters/completed_rewrites/tests/qualification.cpp",
                "tests/adapters/test_completed_rewrites.py",
                "tests/integration/test_completed_rewrites_qualification.py",
            ],
            "license_files": source["license"]["files"],
            "third_party_dependencies": dependencies,
            "object_level_candidates": [manifest.object_level.value],
            "input_contract": manifest.document["input"],
            "output_contract": {
                "framing": "SHA256_DESCRIPTOR_AND_COMPLETE_NATIVE_FRAMES_V1",
                "self_contained": True,
                "actual_written_length": True,
                "capacity_is_not_size": True,
                "model_and_dictionary_accounting": (
                    "OPAQUE_NATIVE_FRAME_BYTES; INCLUDED_IN_FINAL_BITS; NOT_SEPARATELY_ATTRIBUTED"
                ),
            },
            "lifecycle_contract": {
                "output_bound": "FROZEN_NATIVE_BOUND_PLUS_EXACT_DESCRIPTOR_AND_RECORD_OVERHEAD",
                "return_length": "actual_used_bytes",
                "error_codes": [
                    "OUTPUT_CAPACITY",
                    "EXECUTION_CONTRACT",
                    "SOURCE_DOMAIN_UNSUPPORTED",
                ],
                "finalize": "EXACTLY_ONCE_REQUIRED_ZERO_BYTE_FINALIZE",
                "reset": "FRESH_INDEPENDENT_SESSION_PER_INNER_OBJECT",
            },
            "stream_components": [
                "descriptor_and_checksums",
                "native_record_lengths",
                "complete_native_frames",
            ],
            "upstream_tests": tests,
            "builds": builds,
            "license_decision": source["license"],
            "known_limitations": LIMITATIONS[name]
            + [
                "PIPELINE/E2E supported; CORE/native timing unavailable and reported as null.",
                "Independent object profile; streaming/query/random access rejected during "
                "planning.",
                "Synthetic acceptance fixtures establish integration, not real-world performance "
                "or quality rankings.",
            ],
            "unsupported_reason_codes": [
                "TRACK_OR_DTYPE_UNSUPPORTED",
                "TIMING_SCOPE_UNSUPPORTED",
                "STREAMING_UNSUPPORTED",
                "QUERY_UNSUPPORTED",
                "SOURCE_DOMAIN_UNSUPPORTED",
                "ISA_UNSUPPORTED",
            ],
        }
        card = validate_onboarding_card(card)
        (ROOT / "registry/onboarding" / f"{name}.json").write_text(
            json.dumps(card, indent=2) + "\n"
        )
        print(name, "onboarding PASS", flush=True)


if __name__ == "__main__":
    main()
