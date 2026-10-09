from copy import deepcopy
from pathlib import Path

import pytest
from test_planning import _descriptor

from tscompbench.codecs import CodecManifest, CodecRegistry, SourceRegistry
from tscompbench.contracts import RunStatus
from tscompbench.planning import expand_sweep, resolve_execution

ROOT = Path(__file__).resolve().parents[2]


def registry():
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def test_registered_entries_and_aliases_allow_all_three_harness_scopes():
    codecs = registry()
    for key in [*codecs, *[alias["key"] for alias in codecs.alias_documents()]]:
        manifest = codecs.get(key)
        assert set(
            manifest.document["execution"].get("timing_scopes", ["CORE", "PIPELINE", "E2E"])
        ) == {"CORE", "PIPELINE", "E2E"}, key
        if manifest.document["adapter"].get("factory") in {
            "REWRITE_LOSSLESS_CTYPES_V1",
            "COMPLETED_REWRITE_CTYPES_V1",
        }:
            boundaries = manifest.document["adapter"]["timing_scope_boundaries"]
            assert "compress_update + finalize" in boundaries["CORE"]
            assert boundaries["NATIVE"].startswith("UNAVAILABLE_NULL")


@pytest.mark.parametrize("scope", ["CORE", "PIPELINE", "E2E"])
def test_explicit_scope_restriction_is_still_enforced_before_execution(tmp_path, scope):
    from tscompbench.codecs import negotiate

    base = registry().get("oracle-direct")
    doc = deepcopy(base.document)
    doc["execution"]["timing_scopes"] = ["PIPELINE", "E2E"]
    manifest = CodecManifest(base.key, doc, base.algorithm_id)
    artifact = tmp_path / "adapter.bin"
    artifact.write_bytes(b"test artifact")
    resolution = resolve_execution(
        manifest,
        expand_sweep(manifest, {})[0],
        negotiate(manifest, _descriptor()),
        {"environment_id": "test", "cpu": {"flags": [], "affinity": [2]}},
        artifact_path=artifact,
        profile={
            "threads": 1,
            "timing_scope": scope,
            "runner_version": "test",
            "allocation_policy": "PER_REPETITION",
            "cache_policy": "WARM_INPUT",
            "state_policy": "RESET_PER_REPETITION",
            "gc_policy": "DISABLED_DURING_TIMING",
            "jit_policy": "NOT_APPLICABLE",
        },
    )
    if scope == "CORE":
        assert resolution.status is RunStatus.UNSUPPORTED
        assert resolution.reason_code == "TIMING_SCOPE_UNSUPPORTED"
        assert resolution.actual_isa == "NOT_EXECUTED"
    else:
        assert resolution.status is RunStatus.PLANNED
