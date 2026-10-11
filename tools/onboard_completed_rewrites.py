"""Write validated onboarding cards from current, hashed native qualification evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from pathlib import Path

from build_completed_rewrite import KINDS
from qualify_completed_rewrites_native import verify_build, verify_junit

from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[1]
LIMITATIONS = {
    "abba": [
        "Finite binary64, at least two samples; source endpoint arithmetic failures rejected "
        "atomically. Source weighted/symmetric defaults fixed; no universal error bound."
    ],
    "fabba": ["Finite binary64; positive scl; one native worker; no universal error bound."],
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
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def provenance(entry):
    text = (ROOT / entry["source_manifest"]["path"]).read_text()
    if text.lstrip().startswith("{"):
        record = json.loads(text)
        return (record["repository"], record["source_commit"])
    repository = re.search("^repository:\\s*(\\S+)", text, re.M).group(1)
    commit = re.search("^source_commit:\\s*([0-9a-f]{40})", text, re.M).group(1)
    return (repository, commit)


def checked_qualification(name, profile, folder, directory):
    path = directory / name / profile / "qualification.json"
    qualification = json.loads(path.read_text())
    if qualification.get("status") != "PASS":
        raise RuntimeError("current native qualification did not pass: " + str(path))
    expected_command = [
        "ctest",
        "--test-dir",
        str(folder / "cmake"),
        "--output-on-failure",
        "--no-tests=error",
        "--output-junit",
        str(path.parent / "ctest.xml"),
    ]
    if (
        qualification.get("algorithm") != name
        or qualification.get("profile") != profile
        or qualification.get("exit_code") != 0
        or qualification.get("command") != expected_command
    ):
        raise RuntimeError("native qualification command/algorithm/profile execution differs")
    if qualification.get("driver_sha256") != sha(
        ROOT / "tools/qualify_completed_rewrites_native.py"
    ):
        raise RuntimeError("native qualification driver drift")
    current = verify_build(ROOT, name, profile, folder)
    if qualification.get("closure") != current:
        raise RuntimeError("native qualification source/build/runtime/test closure drift")
    log = Path(qualification["log"])
    if sha(log) != qualification["log_sha256"]:
        raise RuntimeError("native qualification log drift")
    junit = path.parent / "ctest.xml"
    if sha(junit) != qualification["junit_sha256"]:
        raise RuntimeError("native qualification JUnit drift")
    if verify_junit(junit, current["ctest_tests"]) != qualification["test_count"]:
        raise RuntimeError("native qualification test count drift")
    return qualification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithms", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--qualification-directory", type=Path, required=True)
    parser.add_argument(
        "--output-directory",
        type=Path,
        required=True,
        help="new before/candidate migration evidence directory",
    )
    args = parser.parse_args()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before_root, candidate_root = output / "before", output / "candidate"
    before_root.mkdir()
    candidate_root.mkdir()
    staged = []
    identities = []
    lock = json.loads((ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json").read_text())
    sources = SourceRegistry(ROOT / "registry/sources")
    codecs = CodecRegistry(ROOT / "registry/codecs", sources)
    # Proposed source IDs must be checked by the actual registry loader before
    # any of the currently registered source/codec/card records are replaced.
    shutil.copytree(ROOT / "registry/sources", candidate_root / "registry/sources")
    for name in args.algorithms:
        entry = lock["packages"][name]
        manifest = codecs.get(name)
        source_path = ROOT / "registry/sources" / (name + "-completed-rewrite.artifact.json")
        source = json.loads(source_path.read_text())
        previous_source_id = manifest.source_artifact_id
        frozen_files = {item["path"]: item["sha256"] for item in entry["files"]}
        for item in source["identity"]["api_files"]:
            if item["path"] not in frozen_files:
                raise RuntimeError("source API file outside frozen package: " + item["path"])
            item["sha256"] = frozen_files[item["path"]]
        if name in {"abba", "fabba"}:
            patch = (
                ROOT
                / "adapters/completed_rewrites/patches"
                / (name + "-0001-reconstruction-capacity-cast.patch")
            )
            source["identity"]["patch_series"] = [
                {
                    "path": str(patch.relative_to(ROOT)),
                    "sha256": sha(patch),
                    "classification": "INVALID_INPUT_CAPACITY_AND_FLOAT_CAST_SAFETY",
                    "legal_bitstream_semantics_changed": False,
                }
            ]
            source["build"]["patches"] = source["identity"]["patch_series"]
        source_id = stable_id("source-artifact", source["identity"])
        document = copy.deepcopy(manifest.document)
        document["identity"]["source_artifact_id"] = source_id
        release = args.build_root.resolve() / name / "release" / ("libtscb_" + name + ".so")
        document["adapter"]["artifact_path"] = str(release.relative_to(ROOT))
        builds, tests, dependencies = [], [], []
        for profile in ("release", "sanitizer"):
            folder = args.build_root.resolve() / name / profile
            build = json.loads((folder / "build-record.json").read_text())
            qualification = checked_qualification(
                name, profile, folder, args.qualification_directory.resolve()
            )
            qualification_path = (
                args.qualification_directory.resolve() / name / profile / "qualification.json"
            )
            builds.append(
                {
                    "kind": profile,
                    "artifact_sha256": build["artifact_sha256"],
                    "compile_commands_sha256": build["compile_commands_sha256"],
                    "build_record_sha256": sha(folder / "build-record.json"),
                    "build_record": str((folder / "build-record.json").relative_to(ROOT)),
                    "compiler": build["compiler"],
                    "configure_command": build["configure_command"],
                }
            )
            tests.append(
                {
                    "status": "PASS",
                    "name": profile + ": current C++ standalone and framework ABI tests",
                    "evidence": str(qualification_path.relative_to(ROOT)),
                    "evidence_sha256": sha(qualification_path),
                    "log": str(Path(qualification["log"]).relative_to(ROOT)),
                    "log_sha256": qualification["log_sha256"],
                    "scope": qualification["scope"],
                    "sanitizer_scope": build["sanitizer_scope"],
                    "source_language_parity": "NOT_GRANTED_BY_CPP_TESTS",
                }
            )
            if profile == "release":
                dependencies = build["runtime_dependencies"]
        source["build"]["recipe"] = (
            "python tools/build_completed_rewrite.py "
            + name
            + " --profile all --output-root "
            + str(args.build_root.resolve().relative_to(ROOT))
        )
        source["build"]["native_qualification"] = tests
        repository, commit = provenance(entry)
        card = {
            "schema_version": "tscb.source-onboarding.v2",
            "source_artifact_id": source_id,
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
                "tools/qualify_completed_rewrites_native.py",
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
                "CORE/PIPELINE/E2E supported using harness session/object boundaries; API-internal "
                "staging, framing, model work and decode materialization remain in CORE. Optional "
                "native timing unavailable (null).",
                "Independent object profile; streaming/query/random access rejected during "
                "planning.",
                "Synthetic acceptance fixtures establish integration, not real-world performance "
                "or quality rankings.",
                "Current C++ standalone/binding tests do not grant fresh source-language parity, "
                "complete upstream capability parity or standalone G0-G6 REWRITE_DONE.",
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
        staged.extend(
            [
                (source_path, source),
                (ROOT / "registry/codecs" / (name + ".json"), document),
                (ROOT / "registry/onboarding" / (name + ".json"), card),
            ]
        )
        identities.append(
            {
                "codec_key": name,
                "previous_algorithm_id": manifest.algorithm_id,
                "previous_source_artifact_id": previous_source_id,
                "current_source_artifact_id": source_id,
            }
        )
    for path, candidate in staged:
        relative = path.relative_to(ROOT)
        saved = before_root / relative
        proposed = candidate_root / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        proposed.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(path.read_bytes())
        proposed.write_text(json.dumps(candidate, indent=2) + "\n")
    proposed = CodecRegistry(
        candidate_root / "registry/codecs", SourceRegistry(candidate_root / "registry/sources")
    )
    for identity in identities:
        identity["current_algorithm_id"] = proposed.get(identity["codec_key"]).algorithm_id
    for path, _ in staged:
        path.write_bytes((candidate_root / path.relative_to(ROOT)).read_bytes())
    try:
        current = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        for identity in identities:
            if current.get(identity["codec_key"]).algorithm_id != identity["current_algorithm_id"]:
                raise RuntimeError("applied codec identity differs from reviewed candidate")
    except Exception:
        for path, _ in staged:
            path.write_bytes((before_root / path.relative_to(ROOT)).read_bytes())
        raise
    report = {
        "status": "PASS",
        "identities": identities,
        "driver_sha256": sha(Path(__file__)),
        "source_language_parity_promoted": False,
        "historical_evidence_rewritten": False,
        "files": [
            {
                "path": str(path.relative_to(ROOT)),
                "previous_sha256": sha(before_root / path.relative_to(ROOT)),
                "current_sha256": sha(path),
            }
            for path, _ in staged
        ],
    }
    (output / "registration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "identities": identities}, indent=2))


if __name__ == "__main__":
    main()
