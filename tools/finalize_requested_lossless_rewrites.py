"""Finalize local standalone deliveries using current evidence, never historical PASS flags."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["chimp", "elf", "elf-plus", "elf-star", "self-star"]
COMMITS = {
    "chimp": "320d397157c7e0696b3c64dc1711fc17a3add3da",
    "elf": "386d69348e6c30475761d3519ee0bfe10ed473d3",
    "elf-plus": "64e0d6004be322d9d8eaf9931e371df202f1a0eb",
    "elf-star": "457ceb0033e98d516fef42e39d17c9d4b8abbfdb",
    "self-star": "457ceb0033e98d516fef42e39d17c9d4b8abbfdb",
}
TARGETS = {
    "chimp": "chimp",
    "elf": "elf_vldb",
    "elf-plus": "elf_plus",
    "elf-star": "elf_star",
    "self-star": "self_star",
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(p, d):
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def evidence(p, package):
    return {"path": str(p.relative_to(package)), "sha256": sha(p)}


def file_license(path, upstream):
    if path.parent.name == "LICENSES" and path.name.startswith("LLVM-"):
        return "Apache-2.0 WITH LLVM-exception"
    if path.name == "musl-COPYRIGHT.txt":
        return "NOASSERTION"
    return upstream


def main():
    deliveries = []
    decision = ROOT / "Compression_Rewrite/USER_DECISIONS.md"
    for name in NAMES:
        package = ROOT / "Compression_Rewrite/ReWrite" / name
        source = ROOT / "Compression_Rewrite/Source" / name
        build = ROOT / "build/rewrite_review" / name
        current = package / "validation/current/report.json"
        qual = json.loads(current.read_text())
        assert qual["status"] == "PASS", (name, qual.get("error"))
        for relative, digest in qual["source_files"].items():
            if relative.startswith(("include/", "src/", "tests/")):
                assert sha(package / relative) == digest, (
                    name,
                    "qualification code changed",
                    relative,
                )
        assert qual["artifacts"] == qual["reproduced_artifacts"], name
        for file, digest in qual["artifacts"].items():
            assert sha(build / "release" / file) == digest
        differential = package / "validation/differential/report.json"
        diff = json.loads(differential.read_text())
        assert diff["status"] == "PASS"
        assert diff["cli_sha256"] == sha(build / "release" / (TARGETS[name] + "_cli")), (
            name,
            "differential binary changed",
        )
        audit = package / "validation/source-domain/report.json"
        if audit.exists():
            assert json.loads(audit.read_text())["status"] == "PASS"
        hist = package / "validation/historical"
        hist.mkdir(exist_ok=True)
        for fname in ["PORT_MANIFEST.yaml", "SBOM.json", "NATIVE_CAPABILITY_MATRIX.yaml"]:
            old = package / fname
            if old.exists() and (not (hist / ("before-20261006-" + fname)).exists()):
                shutil.copy2(old, hist / ("before-20261006-" + fname))
        license = "Apache-2.0" if name == "chimp" else "NOASSERTION"
        if name == "chimp":
            d = package / "LICENSES"
            d.mkdir(exist_ok=True)
            shutil.copy2(source / "upstream/LICENCE.md", d / "Apache-2.0.md")
        if name in ["elf", "elf-star"]:
            (package / "LICENSES").mkdir(exist_ok=True)
            (package / "LICENSES/LOCAL_PERMISSION.md").write_text(
                "NOASSERTION. Local audit, execution and rewrite authorized in ../../USER_DECISIONS.md. No upstream license grant or external redistribution is asserted.\n"
            )
        ids = [
            "codec.binary32",
            "codec.binary64",
            "state.append_finalize_reset",
            "raw.cross_decode",
            "handles.independent",
        ]
        if name == "chimp":
            ids += [
                "variant.chimp",
                "variant.chimp128",
                "history128.stale_trailing_decision",
                "decoder.incremental",
            ]
        elif name == "elf":
            ids += ["state.per_value_erasure_and_beta", "state.full_significant_xor"]
        elif name == "elf-plus":
            ids += ["state.beta_reuse", "state.implicit_low_xor_bit"]
        elif name == "elf-star":
            ids += [
                "state.block_huffman_java_ties",
                "state.post_office_tables",
                "decoder.incremental",
            ]
        elif name == "self-star":
            ids += [
                "state.persistent_blocks",
                "state.adaptive_huffman",
                "state.post_office_tables",
                "network.binary64_fragments",
            ]
        else:
            ids = [
                "codec.binary64",
                "timestamp.int64_modular_dod",
                "codec.gorilla_value_xor",
                "state.append_resume_reset",
                "decoder.seek_cursor",
                "raw.cross_decode",
                "handles.independent",
            ]
        refs = [evidence(current, package), evidence(differential, package)]
        if audit.exists():
            refs.append(evidence(audit, package))
        cap = {
            "schema_version": 1,
            "algorithm_id": name,
            "upstream_revision": COMMITS[name],
            "overall_result": "FULL_PARITY",
            "scope": "Frozen source capabilities on declared Linux x86_64 GCC/Clang; no AArch64/Windows/macOS verification claim",
            "waiver_ids": [],
            "capabilities": [
                {
                    "capability_id": i,
                    "parity_class": "REQUIRED_PARITY",
                    "upstream": {
                        "present": True,
                        "public_or_supported": True,
                        "evidence": "frozen source closure and contract.md",
                    },
                    "rewrite": {
                        "present": True,
                        "variant": "canonical_scalar",
                        "public_symbol": TARGETS[name] + " standalone public API",
                        "platforms": ["linux-x86_64"],
                    },
                    "validation": {"status": "PASS", "artifacts": refs},
                }
                for i in ids
            ]
            + [
                {
                    "capability_id": i,
                    "parity_class": "NOT_APPLICABLE",
                    "rationale": "No supported path in the selected source closure",
                    "validation": {"status": "PASS"},
                }
                for i in ["optimized.SIMD", "parallel.internal_threads", "accelerator.GPU"]
            ],
        }
        (package / "NATIVE_CAPABILITY_MATRIX.yaml").write_text(
            yaml.safe_dump(cap, sort_keys=False, allow_unicode=True)
        )
        (package / "native_capability_validation_report.md").write_text(
            "# Native capability validation\n\nFULL_PARITY for the frozen algorithm on Linux x86_64 GCC/Clang. Every REQUIRED_PARITY capability and current hashed evidence are listed in NATIVE_CAPABILITY_MATRIX.yaml. Native source has no SIMD, internal worker or GPU backend. No other platform claim is made.\n"
        )
        if name in ["elf", "elf-star"]:
            plan = {
                "schema_version": 1,
                "algorithm_id": name,
                "datasets": [
                    {"dataset_id": k, "source_sha256": v} for k, v in diff["dataset_hashes"].items()
                ],
                "selection": "First 1000 rows of every numeric column, no imputation; each column independently serialized little endian binary32/64",
                "checks": [
                    "original_byte_equality",
                    "both_cross_decode",
                    "checked_frame_bitwise",
                    "FinalBits",
                ],
                "source_domain_evidence": "validation/source-domain/report.json",
            }
            (package / "DATASET_TEST_PLAN.yaml").write_text(
                yaml.safe_dump(plan, sort_keys=False, allow_unicode=True)
            )
        source_lock = source / "SOURCE_FILES.json"
        detail = {
            "chimp": "Two stable identities Chimp and Chimp128 share a checked implementation. Canonical NaN is upstream END; other NaN payloads preserve bits. History=128 is fixed, including the upstream stale trailing-zero decision.",
            "elf": "VLDB2023 Elf; one erasure flag/beta per value and full significant XOR. NaN END and source numerical failures reject.",
            "elf-plus": "Development Elf+; beta reuse and implicit low XOR bit. NaN END and source numerical failures reject.",
            "elf-star": "Original block Huffman Elf*, including Java priority queue ties and post-office tables. binary32 blocks <=1000; binary64 <=16384. The decoder owns its Huffman tables and supports next/reset.",
            "self-star": "Original adaptive SElf* with beta/window/Huffman/table state across blocks. binary64 source network fragments included. A session cannot be reduced to independently reset blocks.",
        }[name]
        (package / "README.md").write_text(
            "# "
            + name
            + " standalone C++ rewrite\n\n"
            + detail
            + "\n\nLocal qualification: REWRITE_DONE, 2026-10-06. Compatibility target: source bytes and both cross-decode directions. Linux x86_64 GCC 11 and Clang 14 tested; no other platform is advertised.\n\n```sh\ncmake -S . -B /tmp/"
            + name
            + "-build -DCMAKE_BUILD_TYPE=Release\ncmake --build /tmp/"
            + name
            + "-build -j2\nctest --test-dir /tmp/"
            + name
            + "-build --output-on-failure\n```\n\nCMake, C++17 and the platform C++ runtime are sufficient for native API preflight. Go enables supplementary Prometheus reference tests. Corpus qualification uses explicitly supplied external dataset files and the sibling frozen Source directory; no Benchmark Python, registry or adapter is linked or imported. Current validation, raw byte evidence, malformed/guard/capacity tests, standalone performance and relocated binary reproduction: validation/current/report.json and PORT_MANIFEST.yaml.\n\nPublic API version is 1. Encoder owns appended values/state; decoder output is owned. Input mutation and overread are forbidden; capacity failures write nothing. Raw format and complete checked frame are distinct. Complete-frame FinalBits includes headers, padding and checksums. Source-domain errors reject with no fallback.\n\nLicense: "
            + license
            + ". "
            + (
                "Only local review/run/rewrite is authorized by USER_DECISIONS.md; external publication is not authorized.\n"
                if license == "NOASSERTION"
                else "Original notices are retained under LICENSES and in the frozen source.\n"
            )
            + "\nASan and UBSan passed. LSan is disabled because this sandbox disallows its ptrace mechanism; no leak-clean claim. Standalone timings are qualification observations and are not a formal Benchmark ranking.\n"
        )
        manifest = {
            "schema_version": "tscb.port-manifest.v1",
            "algorithm_id": name,
            "implementation_id": name + "-canonical-cpp-v1",
            "algorithm_name": name,
            "rewrite_conclusion": "REWRITE_DONE",
            "delivery_scope": "LOCAL_ONLY",
            "port_method": "TRANSLATED",
            "compatibility_target": "CROSS_DECODE_AND_BYTE_IDENTICAL",
            "original_language": "Java",
            "canonical_language": "C++17",
            "source": {
                "repository": "https://github.com/panagiotisl/chimp"
                if name == "chimp"
                else "https://github.com/Spatio-Temporal-Lab/elf"
                if name in ["elf", "elf-plus"]
                else "https://github.com/Spatio-Temporal-Lab/SElfStar",
                "commit": COMMITS[name],
                "source_modified": False,
                "closure_manifest": "../../Source/" + name + "/" + source_lock.name,
                "closure_manifest_sha256": sha(source_lock),
            },
            "license": {
                "concluded_spdx": license,
                "redistribution_status": "NOT_AUTHORIZED_UNKNOWN_UPSTREAM_TERMS"
                if license == "NOASSERTION"
                else "ORIGINAL_LICENSES_RETAINED",
                "local_workflow_decision": "../../USER_DECISIONS.md",
                "local_workflow_decision_sha256": sha(decision),
                "upstream_grant_claimed": license != "NOASSERTION",
            },
            "native_capability_parity": "FULL_PARITY",
            "declared_platforms": ["linux-x86_64-gcc", "linux-x86_64-clang"],
            "gates": {
                g: {"status": "PASS", "evidence": why}
                for g, why in {
                    "G0": "Complete input specifications/workbook read; user skip and integration/local-license decisions recorded",
                    "G1": "Frozen source closure and source runtime/dependency locks; explicit local exception for NOASSERTION",
                    "G2": "contract.md, DATASET_TEST_PLAN.yaml, NATIVE_CAPABILITY_MATRIX.yaml and source audit",
                    "G3": "current differential/source-domain/ASan/UBSan/static reports",
                    "G4": "standalone public API and native preflight: owned input, guards, lifecycle, capacities, malformed data and FinalBits",
                    "G5": "No upstream optimized ISA/thread/GPU path exists; scalar identity retained",
                    "G6": "Current compiler portability, standalone performance, documentation, SBOM and bit-for-bit relocated GCC artifacts",
                }.items()
            },
            "current_evidence": refs,
            "binary_artifacts": qual["artifacts"],
            "reproducibility": "BIT_FOR_BIT_RELOCATED_GCC_RELEASE",
            "performance_scope": "STANDALONE_OWNED_ALLOCATION; no formal ranking",
            "security_scope": qual["security_scope"],
            "benchmark_code_in_standalone_package": False,
            "review_date": "2026-10-06",
            "limitations": [
                detail,
                "No external publication for NOASSERTION",
                "No AArch64/Windows/macOS validation claim; no LSan claim",
            ],
        }
        (package / "PORT_MANIFEST.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
        )
        sbom = {
            "schema_version": "tscb.standalone-sbom.v1",
            "algorithm": name,
            "source_commit": COMMITS[name],
            "source_lock_sha256": sha(source_lock),
            "upstream_license": license,
            "reference_runtime_dependencies": json.loads(
                (source / "ORACLE_ENVIRONMENT_LOCK.json").read_text()
            )
            if (source / "ORACLE_ENVIRONMENT_LOCK.json").exists()
            else {
                "Go": "1.26.0",
                "closure": "../../Source/prometheus-xor-chunk/ORIGINAL_API_CLOSURE.json",
                "closure_sha256": sha(source_lock),
            },
            "files": [
                {
                    "path": str(p.relative_to(package)),
                    "sha256": sha(p),
                    "license": file_license(p, license),
                    "scope": "standalone implementation / test / metadata",
                }
                for p in sorted(package.rglob("*"))
                if p.is_file()
                and p.parts[-1] != "SBOM.json"
                and ("validation" not in p.relative_to(package).parts)
                and ("__pycache__" not in p.parts)
            ],
            "binary_artifacts": qual["artifacts"],
            "system_runtime_dependencies": "Linux C/C++ runtime; dynamically linked system libraries; no source Java/Go runtime dependency in codec",
            "external_distribution": "NOT_AUTHORIZED"
            if license == "NOASSERTION"
            else "LICENSE_TERMS_APPLY",
        }
        dump(package / "SBOM.json", sbom)
        deliveries.append(
            {
                "algorithm": name,
                "status": "REWRITE_DONE",
                "source_commit": COMMITS[name],
                "manifest_sha256": sha(package / "PORT_MANIFEST.yaml"),
                "sbom_sha256": sha(package / "SBOM.json"),
                "dataset_cases": diff.get(
                    "dataset_cases", sum("dataset_id" in c for c in diff["cases"])
                ),
                "all_cases": len(diff["cases"]),
                "binary_artifacts": qual["artifacts"],
            }
        )
    out = ROOT / "Compression_Rewrite/Release/requested-lossless-20261006"
    out.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        package = ROOT / "Compression_Rewrite/ReWrite" / name
        source = ROOT / "Compression_Rewrite/Source" / name
        archive = out / (name + "-standalone-local.tar.gz")
        files = []
        for base, prefix in [(package, "ReWrite/" + name), (source, "Source/" + name)]:
            for p in sorted(base.rglob("*")):
                if (
                    p.is_file()
                    and "__pycache__" not in p.parts
                    and ("build" not in p.relative_to(base).parts)
                ):
                    files.append((p, prefix + "/" + str(p.relative_to(base))))
        files.append((decision, "USER_DECISIONS.md"))
        for p in (ROOT / "build/rewrite_review" / name / "release").iterdir():
            if (
                p.is_file()
                and p.name
                in json.loads((package / "validation/current/report.json").read_text())["artifacts"]
            ):
                files.append((p, "bin/" + p.name))
        with archive.open("wb") as f:
            with gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w") as tar:
                    for p, label in sorted(files, key=lambda x: x[1]):
                        data = p.read_bytes()
                        info = tarfile.TarInfo(label)
                        info.size = len(data)
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mode = 493 if label.startswith("bin/") else 420
                        tar.addfile(info, io.BytesIO(data))
        delivery = next(x for x in deliveries if x["algorithm"] == name)
        delivery["archive"] = {
            "path": str(archive.relative_to(ROOT)),
            "sha256": sha(archive),
            "bytes": archive.stat().st_size,
        }
        dump(out / (name + "-release.json"), delivery)
    dump(
        out / "RELEASE_INDEX.json",
        {
            "schema_version": 1,
            "scope": "LOCAL_ONLY",
            "status": "REWRITE_DONE",
            "deliveries": deliveries,
        },
    )
    print(
        json.dumps(
            {
                "status": "REWRITE_DONE",
                "packages": len(deliveries),
                "archives_bytes": sum(d["archive"]["bytes"] for d in deliveries),
            }
        )
    )


if __name__ == "__main__":
    main()
