from dataclasses import replace
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import SourceDomainError
from tscompbench.validation.boundary import build_boundary_suite, run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]


class RejectingSession:
    def __init__(self, dirty):
        self.dirty = dirty

    def output_bound(self, routed):
        return 16

    def compress_update(self, routed, destination):
        if self.dirty:
            destination[0] = 1
        raise SourceDomainError("canonical NaN is END")

    def close(self):
        pass


class RejectingAdapter:
    adapter_id = "adapter:source-domain-test"
    deterministic = True

    def __init__(self, dirty):
        self.dirty = dirty

    def create_session(self, parameters):
        return RejectingSession(self.dirty)


def registry():
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def test_declared_source_rejection_never_excuses_output_mutation(monkeypatch):
    manifest = registry().get("chimp")
    import tscompbench.validation.boundary as boundary

    cases = tuple(
        q for q in build_boundary_suite(manifest, {"block_size": 7}) if q.axis == "ENTROPY"
    )
    monkeypatch.setattr(boundary, "build_boundary_suite", lambda *args: cases)
    assert run_boundary_suite(
        RejectingAdapter(False), manifest, BenchmarkTrack.VALUE, {"block_size": 7}
    ).passed
    assert not run_boundary_suite(
        RejectingAdapter(True), manifest, BenchmarkTrack.VALUE, {"block_size": 7}
    ).passed
    undeclared = replace(
        manifest,
        document={
            **manifest.document,
            "input": {k: v for k, v in manifest.document["input"].items() if k != "value_domain"},
        },
    )
    assert not run_boundary_suite(
        RejectingAdapter(False), undeclared, BenchmarkTrack.VALUE, {"block_size": 7}
    ).passed
