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
        "influxdb-tsm-adaptive-timestamp": {
            "encoding_profile": choice("STREAM", ["STREAM", "BATCH"])
        },
        "prometheus-xor2-chunk": {
            "start_timestamp": integer(0, -9223372036854775808, 9223372036854775807)
        },
        "tristan": {
            "window_size": integer(40, 2, 4096),
            "atoms": integer(8, 1, 4096),
            "nonzeros": integer(2, 1, 4096),
            "requested_n_iter": integer(150, 150, 150),
            "model_seed": integer(0, 0, 4294967295),
            "alpha": decimal("1"),
            "solver": integer(0, 0, 4),
        },
        "corad": {
            "window_size": integer(40, 2, 4096),
            "atoms": integer(8, 1, 4096),
            "nonzeros": integer(2, 1, 4096),
            "requested_n_iter": integer(150, 150, 150),
            "model_seed": integer(0, 0, 4294967295),
            "alpha": decimal("1"),
            "solver": integer(0, 0, 4),
            "correlation_threshold": decimal("0.8"),
        },
        "deepzip": {"lanes": integer(1, 1, 4096)},
        "dzip": {
            "mode": choice("BOOTSTRAP", ["BOOTSTRAP", "COMBINED"]),
            "initial_model": choice(
                "NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET", ["NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET"]
            ),
            "model_seed": integer(0, 0, 4294967295),
        },
        "walloc-1d": {},
        "prometheus-histogram-st": {},
        "prometheus-float-histogram-st": {},
    }
    for name, properties in params.items():
        package = "prometheus-histogram-st" if name == "prometheus-float-histogram-st" else name
        entry = lock["packages"][package]
        provenance = (
            ROOT / "adapters/completed_rewrites/vendor" / package / "PORT_MANIFEST.yaml"
        ).read_text()
        if entry.get("source_manifest"):
            provenance += "\n" + (ROOT / entry["source_manifest"]["path"]).read_text()
        commits = re.findall(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", provenance)
        licenses = [
            f["path"]
            for f in entry["files"]
            if "license" in f["path"].lower() or "notice" in f["path"].lower()
        ]
        license_id = (
            "MIT"
            if name == "influxdb-tsm-adaptive-timestamp"
            else "Apache-2.0 AND BSD-3-Clause"
            if name == "prometheus-xor2-chunk"
            else "NOASSERTION"
        )
        declared_license = re.search(r"concluded_spdx:\s*([^\n]+)", provenance)
        if declared_license:
            license_id = declared_license.group(1).strip()
        if package == "prometheus-histogram-st":
            license_id = "Apache-2.0 AND BSD-3-Clause"
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
                "redistribution": (
                    "LOCAL_EXECUTION_ONLY; ORIGINAL_NOTICES_RETAINED; "
                    "NO_UPSTREAM_LICENSE_GRANT_INVENTED"
                ),
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
        timestamp = name == "influxdb-tsm-adaptive-timestamp"
        histogram = name in {"prometheus-histogram-st", "prometheus-float-histogram-st"}
        system = name == "prometheus-xor2-chunk" or histogram
        unbounded = name in {"abba", "fabba", "tristan", "corad", "walloc-1d"}
        learned = name in {"abba", "fabba", "tristan", "corad", "deepzip", "dzip", "walloc-1d"}
        doc["classification"].update(
            object_level="P3_STORAGE_SYSTEM"
            if system
            else "P2_PIPELINE"
            if learned
            else "P1_STANDALONE_CODEC",
            implementation_class="LEARNED" if learned else "CONVENTIONAL",
            tracks=["TIMESTAMP" if timestamp else "SYSTEM" if system else "VALUE"],
            subtracks=["T1" if timestamp else "S0" if system else "V0"],
        )
        inp = doc["input"]
        inp.pop("value_domain", None)
        inp.update(
            dtypes=["<i8"]
            if timestamp
            else ["<i8", "<f8"]
            if system
            else ["|u1"]
            if name in {"deepzip", "dzip"}
            else ["<f4"]
            if name == "walloc-1d"
            else ["<f8"],
            min_n=2 if name in {"abba", "fabba"} else 40 if name in {"tristan", "corad"} else 0,
            max_n=16383 if histogram else 65535 if system else 16777216,
            min_m=2 if name == "walloc-1d" else 1,
            max_m=2 if name == "walloc-1d" else 65535,
            value_coupling_mode="FULL_MATRIX"
            if name in {"tristan", "corad", "walloc-1d"}
            else "COLUMN_INDEPENDENT",
        )
        if name in {"tristan", "corad"}:
            inp.update(min_n=2, max_n=1048576, max_m=256)
        if system:
            inp["component_dtypes"] = {"timestamp": ["<i8"], "value": ["<f8"]}
        if name == "prometheus-xor2-chunk":
            # SYSTEM supplies paired T and V buffers. This composite role does
            # not require transposing the value matrix's logical axes.
            inp["layouts"] = ["COMPOSITE_T_V", "ROW_MAJOR_CONTIG", "SOA_COLUMNS"]
        if histogram:
            inp.update(
                dtypes=["<i8", "<u8"],
                min_m=6,
                max_m=6,
                component_dtypes={"timestamp": ["<i8"], "value": ["<u8"]},
                value_coupling_mode="FULL_MATRIX",
                required_value_units=[
                    "HISTOGRAM_ST_INT64_BITS",
                    "HISTOGRAM_COUNT_BITS",
                    "HISTOGRAM_ZERO_COUNT_BITS",
                    "HISTOGRAM_SUM_BINARY64_BITS",
                    "HISTOGRAM_ZERO_THRESHOLD_BINARY64_BITS",
                    "HISTOGRAM_BUCKET_BITS",
                ],
                logical_record="PROMETHEUS_GAUGE_SCHEMA0_ONE_POSITIVE_BUCKET_V1",
            )
        if unbounded:
            reasons = ["FINITE_INPUT_REQUIRED"]
            if name in {"abba", "fabba"}:
                reasons += ["SEGMENT_ENDPOINT_ARITHMETIC_UNSUPPORTED"]
            if name in {"tristan", "corad"}:
                reasons += [
                    "INCOMPLETE_WINDOW_UNSUPPORTED",
                    "CONSTANT_COLUMN_UNSUPPORTED",
                    "NORMALIZATION_ARITHMETIC_UNSUPPORTED",
                ]
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
            bitstream_separability="JOINT_CODEWORD"
            if system
            else "PER_COLUMN"
            if inp["value_coupling_mode"] == "COLUMN_INDEPENDENT"
            else "FULL_MATRIX",
        )
        doc["lifecycle"].update(
            block_semantics="WHOLE_OBJECT",
            state_semantics="INDEPENDENT_OBJECT",
            tail_policy="REJECT_INCOMPLETE_WINDOWS"
            if name in {"tristan", "corad"}
            else "EXACT_COUNT",
            dictionary="EMBEDDED_AND_CHARGED" if learned else "NONE",
            model="EMBEDDED_AND_CHARGED" if learned else "NONE",
        )
        doc["execution"].update(
            backends=["COMPLETED_REWRITE_ABI_V1"],
            runtime_dispatch=name in {"tristan", "corad", "walloc-1d", "dzip"},
            isa=["AVX"]
            if name == "dzip"
            else ["CPU_RUNTIME_DISPATCH"]
            if name in {"tristan", "corad", "walloc-1d"}
            else ["SCALAR"],
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
        if name in {"tristan", "corad"}:
            doc["parameters"]["constraints"].extend(
                [
                    {"kind": "ordered", "lower": "nonzeros", "upper": "atoms"},
                    {"kind": "ordered", "lower": "nonzeros", "upper": "window_size"},
                ]
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
        if name == "corad":
            doc["parameters"]["constraints"].append(
                {
                    "kind": "numeric_range",
                    "parameter": "correlation_threshold",
                    "minimum": "0",
                    "maximum": "1",
                }
            )
        doc["adapter"].update(
            backend="COMPLETED_REWRITE_ABI_V1",
            version="completed-rewrites-v1",
            factory="COMPLETED_REWRITE_CTYPES_V1",
            artifact_path=(
                f"build/adapters/{name.replace('-', '_')}/release/"
                f"libtscb_{name.replace('-', '_')}.so"
            ),
            timing_boundary="PYTHON_LAYOUT_C_ABI_NATIVE_FRAME_AND_MODEL_LOAD_INCLUDED",
            accounting_hooks=[
                "FINAL_STREAM_LENGTH",
                "CONTAINER_BYTES",
                "COMPLETE_NATIVE_FRAMES_WITH_ALL_MODEL_BITS",
            ],
        )
        if name in {"deepzip", "walloc-1d"}:
            prefix = f"adapters/completed_rewrites/vendor/{name}/"
            models = {
                Path(f["path"]).stem: {"path": f["path"], "sha256": f["sha256"]}
                for f in entry["files"]
                if f["path"].startswith(prefix + "models/")
                or name == "deepzip"
                and f["path"] == prefix + "tests/fixtures/biGRU.dzm"
            }
            default = "biGRU" if name == "deepzip" else "stereo_5x"
            properties["model_key"] = choice(default, sorted(models))
            doc["adapter"]["models"] = models
            if name == "deepzip":
                for model in models.values():
                    model["alphabet_size"] = 4
        if name == "walloc-1d":
            inp["required_value_units"] = ["NORMALIZED_AUDIO_MINUS_HALF_TO_HALF"]
        doc["adapter"]["parameter_contract"] = deepcopy(doc["parameters"])
        doc["adapter"]["input_contract"] = deepcopy(inp)
        doc["adapter"]["runtime_profile"] = (
            "CPU_SINGLE_THREAD_NATIVE_DEPENDENCY_DISPATCH"
            if name in {"tristan", "corad", "walloc-1d"}
            else "CPU_SINGLE_THREAD"
        )
        if name == "dzip":
            doc["adapter"]["runtime_profile"] = (
                "CPU_AVX_BASELINE_AND_MKLDNN_DISPATCH; PROCESS_THREAD_BUDGET_3"
            )
        doc["adapter"]["isa_scope"] = (
            "WRAPPER_BASELINE; DEPENDENCY_DISPATCH_RECORDED_IN_BUILD"
            if doc["execution"]["runtime_dispatch"]
            else "NATIVE_BASELINE"
        )
        if name in {"tristan", "corad"}:
            doc["adapter"]["training_profile"] = (
                "PER_OBJECT_IN_BAND; SOURCE_IGNORES_REQUESTED_N_ITER; "
                "ACTUAL_MAX_ITER_10_WITH_SOURCE_EARLY_STOP"
            )
        (ROOT / "registry/codecs" / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n")
    print("registered", len(params), "completed rewrite contracts")


if __name__ == "__main__":
    main()
