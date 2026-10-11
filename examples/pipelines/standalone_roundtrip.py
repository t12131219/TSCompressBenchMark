"""Diagnostic P2 round trip; this does not mint FORMAL comparison evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from tscompbench.pipelines import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineRecipe,
    decode_in_fresh_process,
    encode_object,
    validate_restored_object,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--n", type=int, default=17)
    args = parser.parse_args()
    if args.n < 0:
        parser.error("--n must be nonnegative")
    values = {
        "sensor/i16": np.arange(6 * args.n, dtype=np.int16).reshape(2, args.n, 3),
        "sensor/f64": np.arange(args.n, dtype=np.float64) / 3,
    }
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": name,
                    "dtype": array.dtype.str,
                    "shape": list(array.shape),
                    "axes": ["entity", "time", "feature"] if array.ndim == 3 else ["time"],
                    "time_axis": 1 if array.ndim == 3 else 0,
                    "unit": "counts" if array.dtype.kind == "i" else "m/s",
                    "entity": "device_a",
                    "feature": "samples" if array.dtype.kind == "i" else "speed",
                }
                for name, array in values.items()
            ],
            "timestamp": {
                "present": True,
                "dtype": "<i8",
                "unit": "ns",
                "epoch": "unix",
                "pairing": "SHARED_TIME_AXIS",
            },
            "null_recovery_contract": "SEMANTIC",
        }
    )
    masks = {name: np.ones(array.shape, dtype=np.bool_) for name, array in values.items()}
    if args.n:
        masks["sensor/f64"][0] = False
        values["sensor/f64"][0] = np.nan  # Null comes from the mask, not from NaN.
    original = LogicalObject(schema, values, np.arange(args.n, dtype=np.int64) * 3 - 1, masks)
    recipe = PipelineRecipe(
        {"sensor/i16": ChildSpec("neats-lossless-i64", {}), "sensor/f64": ChildSpec("alp", {})},
        ChildSpec("lz4-frame", {}),
        ChildSpec("zstd-frame", {}),
        block_size=8,
        tail_policy="RAW_TAIL",
    )
    start = time.perf_counter_ns()
    artifact = encode_object(args.project_root, original, recipe)
    encode_ns = time.perf_counter_ns() - start
    args.output_directory.mkdir(parents=True, exist_ok=True)
    artifact_path = args.output_directory / "standalone.p2"
    artifact_path.write_bytes(artifact.stream)
    # The child receives only persisted artifact bytes and public decoder dependencies.
    start = time.perf_counter_ns()
    restored, decoder_evidence = decode_in_fresh_process(
        args.project_root, artifact_path.read_bytes()
    )
    cold_spawn_and_decode_ns = time.perf_counter_ns() - start
    validation = validate_restored_object(original, restored)
    evidence = {
        "schema_version": "tscb.pipeline-diagnostic.v1",
        "evidence_class": "DIAGNOSTIC",
        "recipe": recipe.to_document(),
        "recipe_id": recipe.recipe_id,
        "logical_schema": schema.to_document(),
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "artifact_sha256": hashlib.sha256(artifact.stream).hexdigest(),
        "ledger": artifact.ledger.to_document(),
        "clean_decoder": decoder_evidence,
        "validation": validation,
        "timing": {
            "encode_object_elapsed_ns": encode_ns,
            "cold_spawn_and_decode_elapsed_ns": cold_spawn_and_decode_ns,
            "clock": "perf_counter_ns",
            "boundary": "WALL_ELAPSED_DIAGNOSTIC_INCLUDES_SPAWN_NOT_FORMAL_CODEC_TIME",
        },
        "limitations": [
            "NO_STAGE_CLOCK_ATTRIBUTION",
            "NO_FORMAL_REPETITION_OR_RESOURCE_LEASE",
            "NO_EXTERNAL_MODEL_DEPENDENCY_BUNDLE",
        ],
    }
    (args.output_directory / "diagnostic.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "passed": validation["passed"],
                "final_bits": artifact.ledger.final_bits,
                "recipe_id": recipe.recipe_id,
            },
            ensure_ascii=False,
        )
    )
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
