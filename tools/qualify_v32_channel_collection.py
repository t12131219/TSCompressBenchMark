"""Finite asynchronous/ragged qualification with existing LZ4/Zstd P2 children.

This is a correctness, accounting and independent recovery qualification; it
does not grant native collection support or make formal performance claims.
Validation binds current code/source/build/runtime and saved raw/encoded bytes.
Its default read-only audit invokes public independent decoders, never encoders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from qualify_v32_active_entries import file_evidence, source_evidence  # noqa: E402

from tscompbench.adapters import adapter_artifacts  # noqa: E402
from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.runner import control_plane_snapshot  # noqa: E402
from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402
from tscompbench.measurement.resource_lease import ResourceLease  # noqa: E402
from tscompbench.pipelines.channel_collection import (  # noqa: E402
    ChannelCollection,
    ChannelCollectionArtifact,
    ChannelCollectionRecipe,
    ChannelCollectionSchema,
    decode_collection_in_fresh_process,
    encode_collection,
    import_collection_raw,
    prepare_collection_raw,
    standalone_collection_rejection,
    validate_restored_collection,
)
from tscompbench.pipelines.models import (  # noqa: E402
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineError,
    PipelineLedger,
    PipelineRecipe,
)

METHODS = ("lz4-frame", "zstd-frame")
CASES = tuple(
    (topology, null_policy, masks)
    for topology in ("ASYNCHRONOUS_MTS", "RAGGED_CHANNELS")
    for null_policy, masks in (("BITWISE", True), ("SEMANTIC", True), ("BITWISE", False))
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(path: Path, output: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(output)),
        "sha256": _sha(path),
        "bytes": path.stat().st_size,
    }


def _load_file(row: dict[str, Any], output: Path) -> Path:
    _require(
        set(row) == {"path", "sha256", "bytes"} and isinstance(row["path"], str),
        "invalid collection artifact reference",
    )
    path = (output / row["path"]).resolve()
    _require(path.is_relative_to(output) and path.is_file(), "missing/escaping collection artifact")
    _require(
        path.stat().st_size == row["bytes"] and _sha(path) == row["sha256"],
        "saved collection artifact bytes changed",
    )
    return path


def fixture(topology: str, null_policy: str, masks: bool) -> ChannelCollection:
    """Fixed independent qualification objects; never synchronize their T axes."""
    channels, rows = {}, []
    for index, n in enumerate((32, 17, 5)):
        name = f"qualification/device/{index}"
        values = (
            np.arange(4 * n, dtype=np.int16).reshape(2, 2 * n)[:, ::2]
            if index == 0
            else np.arange(n, dtype=np.float64) / 3
        )
        if index == 1:
            values.view(np.uint64)[0] = 0x7FF8000000000042
        present = topology == "ASYNCHRONOUS_MTS" or index != 2
        schema = LogicalObjectSchema.from_document(
            {
                "schema_version": "tscb.logical-object-schema.v1",
                "values": [
                    {
                        "name": "reading",
                        "dtype": values.dtype.str,
                        "shape": list(values.shape),
                        "time_axis": 1 if index == 0 else 0,
                        "axes": ["feature", "time"] if index == 0 else ["time"],
                        "unit": "counts" if index == 0 else "m/s",
                        "entity": name,
                        "feature": "reading",
                    }
                ],
                "timestamp": {
                    "present": present,
                    "dtype": "<i8" if present else "NOT_APPLICABLE",
                    "unit": "ns" if present else "NOT_APPLICABLE",
                    "epoch": "unix" if present else "NOT_APPLICABLE",
                    "pairing": "SHARED_TIME_AXIS" if present else "NOT_APPLICABLE",
                },
                "null_recovery_contract": null_policy,
            }
        )
        timestamp = np.arange(n, dtype=np.int64) * (3 + index) - 9 if present else None
        if n and timestamp is not None:
            timestamp[1:4] = [3, 3, -4]
        validity = None
        if masks:
            mask = np.ones(values.shape, dtype=np.bool_)
            if mask.size:
                mask.reshape(-1)[-1] = False
            validity = {"reading": mask}
        channels[name] = LogicalObject(schema, {"reading": values}, timestamp, validity)
        rows.append(
            {
                "channel_id": name,
                "timestamp_origin": "MANIFEST_CONSTRUCTED" if present else "NONE",
                "logical_schema": schema.to_document(),
            }
        )
    return ChannelCollection(
        ChannelCollectionSchema.from_document(
            {
                "schema_version": "tscb.channel-collection-schema.v1",
                "topology": {"kind": topology, "alignment": "NONE", "time_pairing": "PER_CHANNEL"},
                "channels": rows,
            }
        ),
        channels,
    )


def recipe(original: ChannelCollection, codec: str) -> ChannelCollectionRecipe:
    return ChannelCollectionRecipe.from_recipes(
        {
            name: PipelineRecipe(
                {key: ChildSpec(codec, {}) for key in child.values},
                ChildSpec(codec, {}) if child.timestamp is not None else None,
                ChildSpec(codec, {}) if child.validity is not None else None,
                8,
                "COMPRESS_TAIL",
            )
            for name, child in original.channels.items()
        }
    )


def facts(original: ChannelCollection) -> dict[str, Any]:
    return {
        "schema_id": original.schema.schema_id,
        "content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "canonical_raw_bits": original.canonical_raw_bits,
        "topology": original.schema.to_document()["topology"],
        "channels": [
            {
                "channel_id": name,
                "n": child.schema.n,
                "schema": child.schema.to_document(),
                "content_id": child.content_id,
                "canonical_raw_bits": child.canonical_raw_bits,
                "timestamp_sha256": None
                if child.timestamp is None
                else hashlib.sha256(child.timestamp.tobytes()).hexdigest(),
                "validity_present": child.validity is not None,
                "validity_sha256": None
                if child.validity is None
                else {
                    key: hashlib.sha256(mask.tobytes()).hexdigest()
                    for key, mask in child.validity.items()
                },
            }
            for name, child in original.channels.items()
        ],
    }


def frozen_inputs(root: Path) -> dict[str, Any]:
    registry = CodecRegistry(root / "registry/codecs", SourceRegistry(root / "registry/sources"))
    rows = []
    for key in METHODS:
        manifest = registry.get(key)
        source = registry.sources.get(manifest.source_artifact_id)
        primary, supporting = adapter_artifacts(root, manifest)
        artifact_paths = [primary, *supporting]
        rows.append(
            {
                "codec_key": key,
                "algorithm_id": manifest.algorithm_id,
                "source_artifact_id": manifest.source_artifact_id,
                "manifest": file_evidence(root, root / "registry/codecs" / f"{key}.json"),
                "source": source_evidence(root, source),
                "artifacts": [file_evidence(root, path) for path in artifact_paths],
                "build_records": [
                    file_evidence(root, path.parent / "build-record.json")
                    for path in artifact_paths
                ],
            }
        )
    extra = [
        root / "tools/qualify_v32_channel_collection.py",
        root / "tools/qualify_v32_active_entries.py",
        root / "registry/algorithm_scope.json",
    ]
    extra += sorted((root / "schemas/pipelines/v1").glob("*.json"))
    extra += [
        Path(sys.executable).resolve(),
        Path(np.__file__).resolve(),
        Path(np._core._multiarray_umath.__file__).resolve(),
    ]
    return {
        "control_plane": control_plane_snapshot(root),
        "methods": rows,
        "dependencies": [file_evidence(root, path) for path in extra],
        "python_version": sys.version,
        "numpy_version": np.__version__,
    }


def _negative_raw(original: ChannelCollection) -> list[dict[str, Any]]:
    raw = prepare_collection_raw(original)
    results = []
    for name, broken in (
        ("TRUNCATION", raw[:-1]),
        ("HIDDEN_SUFFIX", raw + b"hidden"),
        ("PAYLOAD_HASH", raw[:-1] + bytes([raw[-1] ^ 1])),
    ):
        try:
            import_collection_raw(broken)
        except PipelineError as error:
            results.append(
                {
                    "case": name,
                    "expected": "REJECT",
                    "observed": "REJECT",
                    "reason": str(error),
                    "codec_called": False,
                }
            )
        else:
            raise ValueError(f"raw negative qualification unexpectedly accepted {name}")
    return results


def qualify(output: Path, cpu: int, root: Path = ROOT) -> dict[str, Any]:
    _require(not (output / "qualification.json").exists(), "qualification evidence is immutable")
    frozen = frozen_inputs(root)
    rows, negative = [], []
    with ResourceLease(
        run_set_id=output.name + "-collection-qualification",
        logical_cpus=(cpu,),
        threads=1,
        memory_limit_bytes=1_073_741_824,
    ) as lease:
        lease_before = lease.to_document()
        for ordinal, (topology, null_policy, masks) in enumerate(CASES):
            original = fixture(topology, null_policy, masks)
            raw_path = output / "inputs" / f"collection-{ordinal}.raw"
            _write(raw_path, prepare_collection_raw(original))
            imported = import_collection_raw(raw_path.read_bytes())
            _require(
                validate_restored_collection(original, imported)["passed"],
                "raw importer changed original per-channel semantics",
            )
            negative.extend({"object_ordinal": ordinal, **row} for row in _negative_raw(original))
            for codec in METHODS:
                instructions = recipe(imported, codec)
                artifact = encode_collection(root, imported, instructions)
                encoded = output / "encoded" / f"collection-{ordinal}-{codec}.tscbcp"
                _write(encoded, artifact.stream)
                restored, recovery = decode_collection_in_fresh_process(root, artifact)
                validation = validate_restored_collection(imported, restored)
                _require(validation["passed"], "public fresh collection decoder changed original")
                rows.append(
                    {
                        "object_ordinal": ordinal,
                        "codec_key": codec,
                        "original": facts(imported),
                        "raw": _file(raw_path, output),
                        "encoded": _file(encoded, output),
                        "recipe": instructions.to_document(),
                        "recipe_id": instructions.recipe_id,
                        "ledger": artifact.ledger.to_document(),
                        "recovery": recovery,
                        "restored": facts(restored),
                        "validation": validation,
                        "acceptance": "SCOPED_PASS",
                        "standalone_rejection": standalone_collection_rejection(imported),
                    }
                )
        # Missing decoder is a genuine cold public-decoder failure, with saved artifact.
        exemplar = rows[0]
        artifact_bytes = _load_file(exemplar["encoded"], output).read_bytes()
        try:
            decode_collection_in_fresh_process(root, artifact_bytes, available_child_keys=set())
        except PipelineError as error:
            negative.append(
                {
                    "case": "MISSING_PUBLIC_CHILD_DECODER",
                    "expected": "REJECT",
                    "observed": "REJECT",
                    "reason": str(error),
                    "codec_called": False,
                }
            )
        else:
            raise ValueError(
                "collection public decoder silently recovered with no available children"
            )
        lease_after = lease.to_document()
    _require(frozen == frozen_inputs(root), "collection qualification control/source/build drift")
    report = {
        "schema_version": "tscb.channel-collection-qualification.v3.2",
        "status": "SCOPED_QUALIFICATION_COMPLETE",
        "frozen_inputs": frozen,
        "scope": {
            "object_count": len(CASES),
            "method_count": len(METHODS),
            "expected_cells": len(CASES) * len(METHODS),
            "existing_methods": list(METHODS),
            "performance_claim": False,
            "native_collection_support_claim": False,
            "full_domain_claim": False,
            "alignment": "NONE",
            "codec_execution_required": True,
            "execution_scope": "QUALIFICATION_ONLY",
        },
        "resources": {"cpu": cpu, "threads": 1, "memory_limit_bytes": 1_073_741_824},
        "lease_before": lease_before,
        "lease_after": lease_after,
        "cells": rows,
        "negative_cases": negative,
    }
    report["qualification_id"] = stable_id("channel-collection-qualification-v32", report)
    _write(output / "qualification.json", canonical_json_bytes(report) + b"\n")
    return report


def validate_collection_qualification(
    report_path: Path,
    *,
    root: Path = ROOT,
    decode_artifacts: bool = True,
) -> dict[str, Any]:
    """Rebuild all frozen identities and accounting; optionally cold-decode saved bytes.

    The default is a read-only independent decoder audit. It writes no evidence
    and measures no performance. The false option checks structural evidence
    only and cannot grant the final independent decoder audit.
    """
    output = report_path.resolve().parent
    report = json.loads(report_path.read_bytes())
    identity = {key: value for key, value in report.items() if key != "qualification_id"}
    _require(
        stable_id("channel-collection-qualification-v32", identity) == report["qualification_id"],
        "collection qualification identity mismatch",
    )
    _require(
        report["schema_version"] == "tscb.channel-collection-qualification.v3.2"
        and report["status"] == "SCOPED_QUALIFICATION_COMPLETE",
        "incomplete collection evidence",
    )
    _require(report["frozen_inputs"] == frozen_inputs(root), "current collection dependency drift")
    _require(
        report["scope"]
        == {
            "object_count": len(CASES),
            "method_count": len(METHODS),
            "expected_cells": len(CASES) * len(METHODS),
            "existing_methods": list(METHODS),
            "performance_claim": False,
            "native_collection_support_claim": False,
            "full_domain_claim": False,
            "alignment": "NONE",
            "codec_execution_required": True,
            "execution_scope": "QUALIFICATION_ONLY",
        },
        "collection scope or fixed denominator changed",
    )
    seen = set()
    for row in report["cells"]:
        ordinal, codec = row["object_ordinal"], row["codec_key"]
        _require(
            type(ordinal) is int and 0 <= ordinal < len(CASES) and codec in METHODS,
            "unknown collection qualification cell",
        )
        _require((ordinal, codec) not in seen, "duplicate collection qualification cell")
        seen.add((ordinal, codec))
        original = fixture(*CASES[ordinal])
        raw = _load_file(row["raw"], output)
        _require(raw.read_bytes() == prepare_collection_raw(original), "frozen raw fixture changed")
        imported = import_collection_raw(raw.read_bytes())
        _require(
            facts(imported) == row["original"], "collection original facts/schema/RawBits differ"
        )
        _require(
            row["standalone_rejection"] == standalone_collection_rejection(imported),
            "standalone collection rejection evidence changed",
        )
        instructions = recipe(imported, codec)
        _require(
            instructions.to_document() == row["recipe"]
            and instructions.recipe_id == row["recipe_id"],
            "collection per-channel recipe changed",
        )
        encoded = _load_file(row["encoded"], output)
        ledger = row["ledger"]
        _require(
            ledger.get("schema_version") == "tscb.pipeline-ledger.v1", "wrong collection ledger"
        )
        paid = PipelineLedger(
            **{key: value for key, value in ledger.items() if key != "schema_version"}
        )
        artifact = ChannelCollectionArtifact(
            encoded.read_bytes(), paid, instructions.recipe_id, imported.content_id
        )
        _require(
            paid.canonical_raw_bits == imported.canonical_raw_bits
            and paid.required_external_bits == 0
            and paid.final_bits == encoded.stat().st_size * 8,
            "collection accounting mismatch",
        )
        recovery = row["recovery"]
        _require(
            recovery["start_method"] == "spawn"
            and recovery["original_input_available"] is False
            and recovery["encoder_session_available"] is False
            and recovery["output_owned_in_worker"] is True
            and recovery["worker_exit_confirmed"] is True
            and recovery["exit_code"] == 0
            and recovery["stream_sha256"] == row["encoded"]["sha256"]
            and recovery["schema_id"] == imported.schema.schema_id,
            "public fresh decoder evidence is incomplete or unbound",
        )
        if decode_artifacts:
            restored, audit = decode_collection_in_fresh_process(root, artifact)
            _require(
                audit["worker_exit_confirmed"] and facts(restored) == row["restored"],
                "saved collection is not independently recoverable",
            )
            _require(
                validate_restored_collection(imported, restored) == row["validation"],
                "saved collection validation differs from public recovery",
            )
        _require(
            row["acceptance"] == "SCOPED_PASS" and row["validation"]["passed"] is True,
            "collection cell did not qualify",
        )
    _require(
        seen == {(ordinal, codec) for ordinal in range(len(CASES)) for codec in METHODS},
        "collection qualification fixed denominator is incomplete",
    )
    expected_negatives = [
        dict(object_ordinal=ordinal, **row)
        for ordinal in range(len(CASES))
        for row in _negative_raw(fixture(*CASES[ordinal]))
    ]
    _require(
        report["negative_cases"][:-1] == expected_negatives,
        "raw parser negative qualification does not reproduce",
    )
    missing = report["negative_cases"][-1]
    _require(
        missing["case"] == "MISSING_PUBLIC_CHILD_DECODER"
        and missing["observed"] == "REJECT"
        and missing["expected"] == "REJECT",
        "missing child-decoder rejection evidence",
    )
    if decode_artifacts:
        try:
            decode_collection_in_fresh_process(
                root,
                _load_file(report["cells"][0]["encoded"], output).read_bytes(),
                available_child_keys=set(),
            )
        except PipelineError:
            pass
        else:
            raise ValueError("unavailable collection public decoder was not rejected")
    _require(report["frozen_inputs"] == frozen_inputs(root), "collection audit dependency drift")
    return {
        "status": "SCOPED_QUALIFICATION_COMPLETE"
        if decode_artifacts
        else "STRUCTURAL_EVIDENCE_VALIDATED",
        "qualification_id": report["qualification_id"],
        "cells": len(seen),
        "objects": len(CASES),
        "methods": list(METHODS),
        "performance_execution_required": False,
        "codec_execution_required": decode_artifacts,
        "codec_execution_scope": "READ_ONLY_INDEPENDENT_DECODER_AUDIT"
        if decode_artifacts
        else "STRUCTURAL_EVIDENCE_ONLY",
        "frozen_inputs": report["frozen_inputs"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    result = (
        validate_collection_qualification(output / "qualification.json")
        if args.validate
        else qualify(output, args.cpu)
    )
    print(json.dumps({key: result[key] for key in ("status", "qualification_id")}, indent=2))


if __name__ == "__main__":
    main()
