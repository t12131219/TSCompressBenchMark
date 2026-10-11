"""Create explicit framework contracts for frozen, independently completed rewrites."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[1]


def integer(default, minimum=0, maximum=16777216):
    return {"type": "integer", "default": default, "minimum": minimum, "maximum": maximum}


def choice(default, values):
    return {"type": "string", "default": default, "enum": values}


def decimal(default):
    return {"type": "decimal-string", "default": default}


def main():
    lock = json.loads((ROOT / "adapters/completed_rewrites/FROZEN_SOURCES.json").read_text())
    template = json.loads((ROOT / "registry/codecs/chimp.json").read_text())
    params = {
        "abba": {
            "compression_tolerance": decimal("0.1"),
            "digitization_tolerance": decimal("0.1"),
            "min_k": integer(1, 1, 65535),
            "max_k": integer(100, 1, 65535),
            "max_len": integer(4294967295, 1, 4294967295),
            "norm": integer(2, 1, 2),
            "scl": decimal("0"),
            "clustering": choice("KMEANS", ["KMEANS", "INCREMENTAL"]),
        },
        "fabba": {
            "tolerance": decimal("0.1"),
            "alpha": decimal("0.1"),
            "scl": decimal("1"),
            "max_len": integer(4294967295, 1, 4294967295),
        },
        "deepzip": {"lanes": integer(1, 1, 4096)},
        "dzip": {
            "mode": choice("BOOTSTRAP", ["BOOTSTRAP", "COMBINED"]),
            "initial_model": choice(
                "NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET", ["NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET"]
            ),
            "model_seed": integer(0, 0, 4294967295),
        },
    }
    for name, properties in params.items():
        package = name
        entry = lock["packages"][package]
        provenance = (
            ROOT / "adapters/completed_rewrites/vendor" / package / "PORT_MANIFEST.yaml"
        ).read_text()
        if entry.get("source_manifest"):
            provenance += "\n" + (ROOT / entry["source_manifest"]["path"]).read_text()
        commits = re.findall("(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", provenance)
        licenses = [
            f["path"]
            for f in entry["files"]
            if "license" in f["path"].lower() or "notice" in f["path"].lower()
        ]
        license_id = "NOASSERTION"
        declared_license = re.search("concluded_spdx:\\s*([^\\n]+)", provenance)
        if declared_license:
            license_id = declared_license.group(1).strip()
        source = {
            "schema_version": "tscb.source-artifact.v2",
            "key": name + "-completed-rewrite",
            "kind": "FROZEN_STANDALONE_CPP_REWRITE_PUBLIC_API",
            "identity": {
                "kind": "FROZEN_STANDALONE_CPP_REWRITE_PUBLIC_API",
                "package": name,
                "api_files": [{k: f[k] for k in ("path", "sha256")} for f in entry["files"]],
                "port_manifest_sha256": entry["port_manifest_sha256"],
                "upstream_commits": sorted(set(commits)),
                "variant": name,
                "source_manifest": entry.get("source_manifest"),
            },
            "license": {
                "spdx": license_id,
                "status": "RUN_ALLOWED"
                if license_id != "NOASSERTION"
                else "REDISTRIBUTION_RESTRICTED",
                "files": licenses,
                "redistribution": "LOCAL_EXECUTION_ONLY; ORIGINAL_NOTICES_RETAINED; NO_UPSTREAM_LICENSE_GRANT_INVENTED",
            },
            "build": {
                "recipe": f"python tools/build_codec.py {name} --profile all",
                "frozen_lock": "adapters/completed_rewrites/FROZEN_SOURCES.json",
                "standalone_package": name,
            },
        }
        (ROOT / "registry/sources" / f"{name}-completed-rewrite.artifact.json").write_text(
            json.dumps(source, indent=2) + "\n"
        )
        doc = deepcopy(template)
        doc["key"] = name
        doc["identity"] = {
            "display_name": name,
            "family": name.upper(),
            "citations": [
                f"adapters/completed_rewrites/vendor/{package}/"
                + (
                    "contract_v1.md"
                    if name == "deepzip"
                    else "contract.md"
                    if (
                        ROOT / "adapters/completed_rewrites/vendor" / package / "contract.md"
                    ).is_file()
                    else "contract_v1.md"
                )
            ],
            "source_artifact_id": stable_id("source-artifact", source["identity"]),
        }
        unbounded = name in {"abba", "fabba"}
        learned = name in {"abba", "fabba", "deepzip", "dzip"}
        doc["classification"].update(
            object_level="P2_PIPELINE" if learned else "P1_STANDALONE_CODEC",
            implementation_class="LEARNED" if learned else "CONVENTIONAL",
            tracks=["VALUE"],
            subtracks=["V0"],
        )
        inp = doc["input"]
        inp.pop("value_domain", None)
        inp.update(
            dtypes=["|u1"] if name in {"deepzip", "dzip"} else ["<f8"],
            min_n=2 if name in {"abba", "fabba"} else 0,
            max_n=16777216,
            min_m=1,
            max_m=65535,
            value_coupling_mode="COLUMN_INDEPENDENT",
        )
        if unbounded:
            reasons = ["FINITE_INPUT_REQUIRED"]
            if name in {"abba", "fabba"}:
                reasons += ["SEGMENT_ENDPOINT_ARITHMETIC_UNSUPPORTED"]
            inp["value_domain"] = {
                "kind": "FROZEN_SOURCE_WITH_BOUNDED_REJECTION",
                "unsupported_action": "REJECT_BEFORE_OUTPUT",
                "oracle_evidence": f"adapters/completed_rewrites/vendor/{name}/contract.md",
                "rejection_reasons": reasons,
            }
        if name in {"deepzip", "dzip"}:
            inp["value_domain"] = {
                "kind": "FROZEN_SOURCE_WITH_BOUNDED_REJECTION",
                "unsupported_action": "REJECT_BEFORE_OUTPUT",
                "oracle_evidence": doc["identity"]["citations"][0],
                "rejection_reasons": ["MODEL_ALPHABET_UNSUPPORTED"],
            }
        doc["semantics"].update(
            loss_modes=["UNBOUNDED_LOSSY" if unbounded else "LOSSLESS"],
            reconstruction_modes=["APPROX_GRID" if unbounded else "EXACT_GRID"],
            rebuild_protocol="COMPLETE_NATIVE_FRAME_WITH_ORIGINAL_GRID_V1",
            decodability_profile="SELF_CONTAINED_DESCRIPTOR_AND_NATIVE_FRAMES",
            bitstream_separability="PER_COLUMN"
            if inp["value_coupling_mode"] == "COLUMN_INDEPENDENT"
            else "FULL_MATRIX",
        )
        doc["lifecycle"].update(
            block_semantics="WHOLE_OBJECT",
            state_semantics="INDEPENDENT_OBJECT",
            tail_policy="EXACT_COUNT",
            dictionary="EMBEDDED_AND_CHARGED" if learned else "NONE",
            model="EMBEDDED_AND_CHARGED" if learned else "NONE",
        )
        doc["execution"].update(
            backends=["COMPLETED_REWRITE_ABI_V1"],
            runtime_dispatch=name in {"dzip"},
            isa=["AVX"] if name == "dzip" else ["SCALAR"],
            fallback_policy="DISALLOWED",
            timing_scopes=["CORE", "PIPELINE", "E2E"],
        )
        if name == "dzip":
            doc["execution"]["threading"] = "CALLER_PLUS_TWO_PERSISTENT_SINGLE_WORKER_EIGEN_POOLS"
        properties["isa"] = choice(doc["execution"]["isa"][0], doc["execution"]["isa"])
        doc["parameters"]["properties"] = properties
        doc["parameters"]["constraints"] = []
        if name == "abba":
            doc["parameters"]["constraints"].append(
                {"kind": "ordered", "lower": "min_k", "upper": "max_k"}
            )
        for key in ("compression_tolerance", "digitization_tolerance", "tolerance", "alpha", "scl"):
            if key in properties:
                doc["parameters"]["constraints"].append(
                    {"kind": "numeric_range", "parameter": key, "minimum": "0"}
                )
        if name == "fabba":
            doc["parameters"]["constraints"].append(
                {
                    "kind": "numeric_range",
                    "parameter": "scl",
                    "minimum": "0",
                    "exclusive_minimum": True,
                }
            )
        doc["adapter"].update(
            backend="COMPLETED_REWRITE_ABI_V1",
            version="completed-rewrites-v1",
            factory="COMPLETED_REWRITE_CTYPES_V1",
            artifact_path=f"build/adapters/{name.replace('-', '_')}/release/libtscb_{name.replace('-', '_')}.so",
            timing_boundary="PYTHON_LAYOUT_C_ABI_NATIVE_FRAME_AND_MODEL_LOAD_INCLUDED",
            accounting_hooks=[
                "FINAL_STREAM_LENGTH",
                "CONTAINER_BYTES",
                "COMPLETE_NATIVE_FRAMES_WITH_ALL_MODEL_BITS",
            ],
        )
        if name in {"deepzip"}:
            prefix = f"adapters/completed_rewrites/vendor/{name}/"
            models = {
                Path(f["path"]).stem: {"path": f["path"], "sha256": f["sha256"]}
                for f in entry["files"]
                if f["path"].startswith(prefix + "models/")
                or (name == "deepzip" and f["path"] == prefix + "tests/fixtures/biGRU.dzm")
            }
            default = "biGRU" if name == "deepzip" else "stereo_5x"
            properties["model_key"] = choice(default, sorted(models))
            doc["adapter"]["models"] = models
            if name == "deepzip":
                for model in models.values():
                    model["alphabet_size"] = 4
        doc["adapter"]["parameter_contract"] = deepcopy(doc["parameters"])
        doc["adapter"]["input_contract"] = deepcopy(inp)
        doc["adapter"]["runtime_profile"] = "CPU_SINGLE_THREAD"
        if name == "dzip":
            doc["adapter"]["runtime_profile"] = (
                "CPU_AVX_BASELINE_AND_MKLDNN_DISPATCH; PROCESS_THREAD_BUDGET_3"
            )
        doc["adapter"]["isa_scope"] = (
            "WRAPPER_BASELINE; DEPENDENCY_DISPATCH_RECORDED_IN_BUILD"
            if doc["execution"]["runtime_dispatch"]
            else "NATIVE_BASELINE"
        )
        (ROOT / "registry/codecs" / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n")
    print("registered", len(params), "completed rewrite contracts")


if __name__ == "__main__":
    main()
