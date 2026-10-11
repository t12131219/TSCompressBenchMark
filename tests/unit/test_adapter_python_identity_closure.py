"""Real execution resolution must change when shared adapter code changes."""

import copy
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tscompbench.adapters.factory import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import CapabilityStatus
from tscompbench.ids import canonical_json_bytes
from tscompbench.planning.resolution import resolve_execution

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    (name, "lzsse8_raw.py")
    for name in (
        "alp",
        "alp-rd",
        "leats-lossless-i64",
        "neats-lossless-i64",
        "sprintz-delta",
        "sprintz-fire",
        "sprintz-fire-huff0",
        "sprintz-delta-u8",
        "sprintz-fire-u8",
    )
] + [
    ("fse", "deflate_zlib.py"),
    ("huff0", "deflate_zlib.py"),
    ("lzss-raw", "lzss_common.py"),
    ("lzss-dipperstein-c", "lzss_common.py"),
    ("alp", "source_reject_fallback.py"),
    ("sprintz-fire", "native_timing.py"),
]


@pytest.mark.parametrize("name,shared", CASES)
def test_transitive_or_conditional_mutation_changes_actual_execution_identity(
    tmp_path, name, shared
):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(name)
    directory = tmp_path / "src/tscompbench/adapters"
    directory.parent.mkdir(parents=True)
    shutil.copytree(
        ROOT / "src/tscompbench/adapters", directory, ignore=shutil.ignore_patterns("__pycache__")
    )
    document = copy.deepcopy(manifest.document)
    artifact = tmp_path / "build/release/libfixture.so"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"non-executable identity fixture; never loaded")
    document["adapter"]["artifact_path"] = str(artifact.relative_to(tmp_path))
    for field in ("models", "python_source_closure", "runtime_profile"):
        document["adapter"].pop(field, None)
    command = {
        "schema_version": "tscb.compile-command.v1",
        "profile": "release",
        "command": ["never-executed"],
    }
    (artifact.parent / "compile-command.json").write_text(json.dumps(command))
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "algorithm": name,
        "profile": "release",
        "artifact": str(artifact.relative_to(tmp_path)),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "compile_commands_sha256": hashlib.sha256(canonical_json_bytes(command)).hexdigest(),
    }
    (artifact.parent / "build-record.json").write_text(json.dumps(record))
    fake = SimpleNamespace(
        key=name,
        document=document,
        algorithm_id=manifest.algorithm_id,
        source_artifact_id=manifest.source_artifact_id,
    )
    config = SimpleNamespace(parameters={"isa": document["execution"]["isa"][0]})
    compatibility = SimpleNamespace(
        status=CapabilityStatus.DIRECT_SUPPORTED,
        output_descriptor=None,
        input_descriptor=SimpleNamespace(alignment_bytes=64),
    )
    environment = {
        "cpu": {"flags": ["avx", "avx2", "bmi2", "abm", "lzcnt", "sse4_1"], "affinity": [0]},
        "python": {},
        "tools": {},
        "environment_id": "fixture",
    }
    profile = {
        "threads": 3,
        **{
            name: "fixture"
            for name in (
                "runner_version",
                "allocation_policy",
                "cache_policy",
                "state_policy",
                "gc_policy",
                "jit_policy",
            )
        },
    }

    def resolve():
        primary, support = adapter_artifacts(tmp_path, fake)
        return support, resolve_execution(
            fake,
            config,
            compatibility,
            environment,
            artifact_path=primary,
            profile=profile,
            supporting_artifact_paths=support,
        )

    before_paths, before = resolve()
    changed = directory / shared
    contents = changed.read_text()
    changed.write_text(
        contents.replace("_MAX_RANK = 8", "_MAX_RANK = 7", 1)
        if "_MAX_RANK = 8" in contents
        else contents + "\n# isolated identity mutation\n"
    )
    after_paths, after = resolve()
    assert changed in before_paths
    assert before_paths == after_paths
    assert before.artifact_sha256 != after.artifact_sha256
    assert before.execution_path_hash != after.execution_path_hash


def test_multilevel_lzss_and_simd_helper_closure():
    from tscompbench.adapters.factory import _adapter_python_closure

    directory = ROOT / "src/tscompbench/adapters"
    lzss = _adapter_python_closure(ROOT, [directory / "lzss_raw.py"])
    assert {
        directory / "lzss_common.py",
        directory / "byte_container.py",
        directory / "native_timing.py",
    }.issubset(lzss)
    simd = _adapter_python_closure(ROOT, [directory / "simdcomp.py"])
    assert {directory / "native_buffers.py", directory / "native_timing.py"}.issubset(simd)
