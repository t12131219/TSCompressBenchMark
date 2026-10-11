from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.rewrite_lossless import RewriteLosslessAdapter
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    ExecutionContractError,
    LogicalBuffer,
    RoutedInput,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array

ROOT = Path(__file__).resolve().parents[2]
ALGORITHMS = ["chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star"]


def codec(name):
    doc = json.loads((ROOT / "registry/codecs" / (name + ".json")).read_text())
    path = ROOT / doc["adapter"]["artifact_path"]
    assert path.is_file(), f"build {name} before qualification"
    return RewriteLosslessAdapter(path, doc["adapter"], name)


def route(n, width=8, m=2, matrix=False, system=False):
    values = np.array([(i % 19 - 9) / 10 for i in range(n * m)], dtype=f"<f{width}").reshape(n, m)
    values.flags.writeable = False
    if matrix:
        buffers = [LogicalBuffer("value/matrix", values, values.nbytes * 8)]
    else:
        buffers = [
            LogicalBuffer(f"value/{i:06}", np.ascontiguousarray(values[:, i]), n * width * 8)
            for i in range(m)
        ]
    timestamp = None
    if system:
        pattern = [-(2**63), 2**63 - 1, 0, 0, -1, -15, 1000]
        timestamp = np.array([pattern[i % len(pattern)] for i in range(n)], dtype="<i8")
        timestamp.flags.writeable = False
        buffers.insert(0, LogicalBuffer("timestamp", timestamp, n * 64))
    for b in buffers:
        b.array.flags.writeable = False
    buffers = tuple(buffers)
    return RoutedInput(
        "dataset:rewrite-tests",
        BenchmarkTrack.SYSTEM if system else BenchmarkTrack.VALUE,
        buffers,
        timestamp,
        None,
        n,
        m,
        sum(b.logical_bits for b in buffers),
        hash_logical_buffers(buffers),
        segment_plan_id="segment:tests" if system else None,
        pairing_reference_sha256=hash_reference_array(timestamp),
    )


@pytest.mark.parametrize("name", ["elf", "elf-plus", "elf-star", "self-star"])
def test_source_non_lossless_values_reject_without_raw_fallback(name):
    r = route(1, m=1)
    for value in [float("nan"), 1e20]:
        a = np.array([value], dtype="<f8")
        unsupported = replace(r, buffers=(LogicalBuffer("value/000000", a, 64),))
        with pytest.raises(ExecutionContractError):
            perform_roundtrip(codec(name), unsupported, {"block_size": 7})


def test_frozen_snapshots_are_exact_and_source_ids_are_bound_to_them():
    lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
    for name in ALGORITHMS:
        for record in lock["algorithms"][name]["files"]:
            path = ROOT / record["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        doc = json.loads(
            (ROOT / "registry/sources" / (name + "-rewrite.artifact.json")).read_text()
        )
        assert doc["identity"]["api_files"] == lock["algorithms"][name]["files"]
