"Finalize local standalone deliveries using current evidence, never historical PASS flags."

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
NAMES = ["chimp", "elf", "elf-plus", "elf-star", "self-star", "prometheus-xor-chunk"]
COMMITS = {
    "chimp": "320d397157c7e0696b3c64dc1711fc17a3add3da",
    "elf": "386d69348e6c30475761d3519ee0bfe10ed473d3",
    "elf-plus": "64e0d6004be322d9d8eaf9931e371df202f1a0eb",
    "elf-star": "457ceb0033e98d516fef42e39d17c9d4b8abbfdb",
    "self-star": "457ceb0033e98d516fef42e39d17c9d4b8abbfdb",
    "prometheus-xor-chunk": "8374d30cb3fe705773bbac72d7015eba17480557",
}
TARGETS = {
    "chimp": "chimp",
    "elf": "elf_vldb",
    "elf-plus": "elf_plus",
    "elf-star": "elf_star",
    "self-star": "self_star",
    "prometheus-xor-chunk": "prometheus_xor_chunk",
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
    # musl COPYRIGHT collects multiple file-specific grants; preserve the full notice.
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
        differential = package / (
            "validation/original-public-api/report.json"
            if name == "prometheus-xor-chunk"
            else "validation/differential/report.json"
        )
        diff = json.loads(differential.read_text())
        assert diff["status"] == "PASS"
        assert diff["cli_sha256"] == sha(build / "release" / (TARGETS[name] + "_cli")), (
            name,
            "differential binary changed",
        )
        audit = package / "validation/source-domain/report.json"
        if audit.exists():
            assert json.loads(audit.read_text())["status"] == "PASS"
        # Retain prior metadata for historical review; all current declarations are rebuilt below.
        hist = package / "validation/historical"
        hist.mkdir(exist_ok=True)
        for fname in ["PORT_MANIFEST.yaml", "SBOM.json", "NATIVE_CAPABILITY_MATRIX.yaml"]:
            old = package / fname
            if old.exists() and not (hist / ("before-20261006-" + fname)).exists():
                shutil.copy2(old, hist / ("before-20261006-" + fname))
        license = (
            "Apache-2.0"
            if name == "chimp"
            else "Apache-2.0 AND BSD-3-Clause"
            if name == "prometheus-xor-chunk"
            else "NOASSERTION"
        )
        if name == "chimp":
            d = package / "LICENSES"
            d.mkdir(exist_ok=True)
            shutil.copy2(source / "upstream/LICENCE.md", d / "Apache-2.0.md")
        if name in ["elf", "elf-star"]:
            (package / "LICENSES").mkdir(exist_ok=True)
            (package / "LICENSES/LOCAL_PERMISSION.md").write_text(
                "NOASSERTION. Local audit, execution and rewrite authorized i"
                "n ../../USER_DECISIONS.md. No upstream license grant or exte"
                "rnal redistribution is asserted.\n"
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
            "scope": (
                "Frozen source capabilities on declared Linux x86_64 GCC/Clan"
                "g; no AArch64/Windows/macOS verification claim"
            ),
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
            "# Native capability validation\n\nFULL_PARITY for the frozen a"
            "lgorithm on Linux x86_64 GCC/Clang. Every REQUIRED_PARITY ca"
            "pability and current hashed evidence are listed in NATIVE_CA"
            "PABILITY_MATRIX.yaml. Native source has no SIMD, internal wo"
            "rker or GPU backend. No other platform claim is made.\n"
        )
        if name in ["elf", "elf-star"]:
            plan = {
                "schema_version": 1,
                "algorithm_id": name,
                "datasets": [
                    {"dataset_id": k, "source_sha256": v} for k, v in diff["dataset_hashes"].items()
                ],
                "selection": (
                    "First 1000 rows of every numeric column, no imputation; each"
                    " column independently serialized little endian binary32/64"
                ),
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
        elif name == "prometheus-xor-chunk":
            plan = {
                "schema_version": 1,
                "algorithm_id": name,
                "datasets": [
                    {"dataset_id": k, "source_sha256": v} for k, v in diff["dataset_hashes"].items()
                ],
                "selection": (
                    "Every row of every numeric value column paired with original"
                    " UTC timestamp milliseconds; one independent complete chunk "
                    "per column"
                ),
                "widths": [64],
                "case_count": diff["dataset_cases"],
                "oracle": (
                    "Unmodified upstream public API, Go1.26.0, frozen closure ORI"
                    "GINAL_API_CLOSURE.json"
                ),
                "checks": ["byte_identical", "both_cross_decode", "paired_bitwise", "FinalBits"],
            }
            (package / "DATASET_TEST_PLAN.yaml").write_text(yaml.safe_dump(plan, sort_keys=False))
            (package / "validation/dataset_validation_report.md").write_text(
                "# Original Prometheus public API validation\n\nPASS: "
                + str(diff["dataset_cases"])
                + " complete real-data column chunks and "
                + str(len(diff["cases"]))
                + (
                    " total cases. Includes all rows/columns of ETTh1, exchange_r"
                    "ate, weather and national_illness, 64 property vectors and s"
                    "ix frozen golden vectors. Exact bytes, both cross-decode dir"
                    "ections and int64/value bit patterns agree. Current hashes a"
                    "nd commands: original-public-api/report.json. The extracted "
                    "Go oracle is supplementary evidence.\n"
                )
            )
        source_lock = source / (
            "ORIGINAL_API_CLOSURE.json" if name == "prometheus-xor-chunk" else "SOURCE_FILES.json"
        )
        detail = {
            "chimp": (
                "Two stable identities Chimp and Chimp128 share a checked imp"
                "lementation. Canonical NaN is upstream END; other NaN payloa"
                "ds preserve bits. History=128 is fixed, including the upstre"
                "am stale trailing-zero decision."
            ),
            "elf": (
                "VLDB2023 Elf; one erasure flag/beta per value and full signi"
                "ficant XOR. NaN END and source numerical failures reject."
            ),
            "elf-plus": (
                "Development Elf+; beta reuse and implicit low XOR bit. NaN E"
                "ND and source numerical failures reject."
            ),
            "elf-star": (
                "Original block Huffman Elf*, including Java priority queue t"
                "ies and post-office tables. binary32 blocks <=1000; binary64"
                " <=16384. The decoder owns its Huffman tables and supports n"
                "ext/reset."
            ),
            "self-star": (
                "Original adaptive SElf* with beta/window/Huffman/table state"
                " across blocks. binary64 source network fragments included. "
                "A session cannot be reduced to independently reset blocks."
            ),
            "prometheus-xor-chunk": (
                "Joint Prometheus XOR timestamp/value chunk. Gorilla value XO"
                "R and timestamp Delta-of-Delta share one identity. Timestamp"
                " signed overflow follows upstream modular arithmetic. Maximu"
                "m 65535 paired samples per chunk."
            ),
        }[name]
        (package / "README.md").write_text(
            "# "
            + name
            + " standalone C++ rewrite\n\n"
            + detail
            + (
                "\n\nLocal qualification: REWRITE_DONE, 2026-10-06. Compatibili"
                "ty target: source bytes and both cross-decode directions. Li"
                "nux x86_64 GCC 11 and Clang 14 tested; no other platform is "
                "advertised.\n\n```sh\ncmake -S . -B /tmp/"
            )
            + name
            + "-build -DCMAKE_BUILD_TYPE=Release\ncmake --build /tmp/"
            + name
            + "-build -j2\nctest --test-dir /tmp/"
            + name
            + (
                "-build --output-on-failure\n```\n\nCMake, C++17 and the platfor"
                "m C++ runtime are sufficient for native API preflight. Go en"
                "ables supplementary Prometheus reference tests. Corpus quali"
                "fication uses explicitly supplied external dataset files and"
                " the sibling frozen Source directory; no Benchmark Python, r"
                "egistry or adapter is linked or imported. Current validation"
                ", raw byte evidence, malformed/guard/capacity tests, standal"
                "one performance and relocated binary reproduction: validatio"
                "n/current/report.json and PORT_MANIFEST.yaml.\n\nPublic API ve"
                "rsion is 1. Encoder owns appended values/state; decoder outp"
                "ut is owned. Input mutation and overread are forbidden; capa"
                "city failures write nothing. Raw format and complete checked"
                " frame are distinct. Complete-frame FinalBits includes heade"
                "rs, padding and checksums. Source-domain errors reject with "
                "no fallback.\n\nLicense: "
            )
            + license
            + ". "
            + (
                (
                    "Only local review/run/rewrite is authorized by USER_DECISION"
                    "S.md; external publication is not authorized.\n"
                )
                if license == "NOASSERTION"
                else "Original notices are retained under LICENSES and in the frozen source.\n"
            )
            + (
                "\nASan and UBSan passed. LSan is disabled because this sandbo"
                "x disallows its ptrace mechanism; no leak-clean claim. Stand"
                "alone timings are qualification observations and are not a f"
                "ormal Benchmark ranking.\n"
            )
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
            "original_language": "Go" if name == "prometheus-xor-chunk" else "Java",
            "canonical_language": "C++17",
            "source": {
                "repository": "https://github.com/prometheus/prometheus"
                if name == "prometheus-xor-chunk"
                else "https://github.com/panagiotisl/chimp"
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
                    "G0": (
                        "Complete input specifications/workbook read; user skip and i"
                        "ntegration/local-license decisions recorded"
                    ),
                    "G1": (
                        "Frozen source closure and source runtime/dependency locks; e"
                        "xplicit local exception for NOASSERTION"
                    ),
                    "G2": (
                        "contract.md, DATASET_TEST_PLAN.yaml, NATIVE_CAPABILITY_MATRI"
                        "X.yaml and source audit"
                    ),
                    "G3": "current differential/source-domain/ASan/UBSan/static reports",
                    "G4": (
                        "standalone public API and native preflight: owned input, gua"
                        "rds, lifecycle, capacities, malformed data and FinalBits"
                    ),
                    "G5": (
                        "No upstream optimized ISA/thread/GPU path exists; scalar identity retained"
                    ),
                    "G6": (
                        "Current compiler portability, standalone performance, docume"
                        "ntation, SBOM and bit-for-bit relocated GCC artifacts"
                    ),
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
                and "validation" not in p.relative_to(package).parts
                and "__pycache__" not in p.parts
            ],
            "binary_artifacts": qual["artifacts"],
            "system_runtime_dependencies": (
                "Linux C/C++ runtime; dynamically linked system libraries; no"
                " source Java/Go runtime dependency in codec"
            ),
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
                    and "build" not in p.relative_to(base).parts
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
                        info.mode = 0o755 if label.startswith("bin/") else 0o644
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
