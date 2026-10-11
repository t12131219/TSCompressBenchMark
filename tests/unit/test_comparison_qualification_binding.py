"""Saved PASS evidence must belong to its actual codec and original fixture."""

import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from tscompbench.comparison import runner
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.recovery import DecodeContext
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes, stable_id


@pytest.fixture
def saved_pass(tmp_path, monkeypatch):
    buffers = (LogicalBuffer("value/0", np.arange(3, dtype=np.int16), 48),)
    routed = RoutedInput(
        dataset_id="fixture-one",
        track=BenchmarkTrack.VALUE,
        n=3,
        m=1,
        buffers=buffers,
        timestamp_unit=None,
        timestamp_epoch=None,
        value_units=(None,),
        canonical_raw_bits=48,
        timestamp_reference=None,
        validity_reference=None,
        input_sha256=hash_logical_buffers(buffers),
    )
    compatibility = SimpleNamespace(
        effective_loss_mode="LOSSLESS",
        input_descriptor=SimpleNamespace(dtype_vector=("<i2",)),
        operations=(),
    )
    context = DecodeContext.from_routed(
        routed, compatibility, adapter_id="adapter-one", parameters={"level": 1}
    )
    task = {
        "task_id": "task-one",
        "dataset_id": "fixture-one",
        "algorithm_id": "algorithm-one",
        "config_id": "config-one",
        "track": "VALUE",
        "execution": {"execution_path_hash": "path-one", "adapter_id": "adapter-one"},
        "compatibility": {"compatibility_plan_id": "compat-one"},
    }
    cell = {
        "cell_id": "cell-one",
        "algorithm_id": "algorithm-one",
        "legacy_config_id": "config-one",
        "parameters": {"level": 1},
        "codec_key": "codec-one",
        "allowed_paths": ["DIRECT"],
        "expected": {"outcome": "PASS"},
        "member_id": "method-one",
        "config_label": "default",
    }
    run = SimpleNamespace(
        path=tmp_path,
        plan={"comparison_id": "comparison-one"},
        cells={"cell-one": cell},
        bundle={"qualification_datasets": []},
    )
    monkeypatch.setattr(runner, "_saved_preflight_inputs", lambda *args: (task, routed, context))
    directory = runner._qualification_capture_directory(run, cell, "core")
    directory.mkdir(parents=True)
    artifacts = {}
    for role, name, payload in (
        ("stream", "stream.bin", b"actual-one"),
        ("context", "context.json", context.serialized),
    ):
        path = directory / name
        path.write_bytes(payload)
        artifacts[role] = {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    artifacts["binding"] = {
        "task_id": "task-one",
        "dataset_id": "fixture-one",
        "algorithm_id": "algorithm-one",
        "config_id": "config-one",
        "execution_path_hash": "path-one",
        "track": "VALUE",
        "input_sha256": routed.input_sha256,
        "canonical_raw_bits": 48,
        "adapter_id": "adapter-one",
        "parameters": {"level": 1},
    }
    (directory / "binding.json").write_bytes(canonical_json_bytes(artifacts))
    preflight = {
        "status": "PASS",
        "eligible_for_formal_repetitions": True,
        "correctness": {"status": "PASS"},
        "input_validation": {"input_sha256": routed.input_sha256},
        "bitstream_sha256": artifacts["stream"]["sha256"],
        "accounting": {
            "canonical_raw_bits": 48,
            "serialized_bits": len(b"actual-one") * 8,
            "external_side_information_bits": len(context.serialized) * 8,
            "final_bits": (len(b"actual-one") + len(context.serialized)) * 8,
        },
        "diagnostics": {
            "qualification_artifacts": artifacts,
            "independent_recovery_worker_lifecycle": {
                "start_method": "spawn",
                "worker_pid": 100,
                "worker_exit_confirmed": True,
                "exit_code": 0,
            },
            "independent_recovery": {
                "start_method": "spawn",
                "original_input_available": False,
                "encoder_session_available": False,
                "output_owned_in_worker": True,
                "worker_pid": 100,
                "decode_context_sha256": context.sha256,
                "required_external_bits": len(context.serialized) * 8,
                "stream_sha256": artifacts["stream"]["sha256"],
            },
        },
    }
    document = {
        "schema_version": "tscb.comparison-qualification.v1",
        "comparison_id": "comparison-one",
        "status": "PASS",
        "failure_count": 0,
        "evidence": [
            {
                "cell_id": "cell-one",
                "scope": "CORE_OR_EXTENSION",
                "expected": {"outcome": "PASS"},
                "preflight": preflight,
            }
        ],
    }
    document["qualification_id"] = stable_id("comparison-qualification", document)
    return run, cell, task, routed, context, preflight, document


def resign(document):
    document["qualification_id"] = stable_id(
        "comparison-qualification", {k: v for k, v in document.items() if k != "qualification_id"}
    )


def test_current_artifacts_qualify_without_codec_calls(saved_pass):
    run, _, _, _, _, _, document = saved_pass
    runner.validate_qualification_evidence(run, document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("algorithm_id", "other-codec"),
        ("dataset_id", "other-fixture"),
        ("config_id", "other-parameters"),
        ("input_sha256", "0" * 64),
    ],
)
def test_copied_pass_cannot_be_retagged_and_resigned(saved_pass, field, value):
    run, _, _, _, _, _, original = saved_pass
    document = copy.deepcopy(original)
    document["evidence"][0]["preflight"]["diagnostics"]["qualification_artifacts"]["binding"][
        field
    ] = value
    resign(document)
    with pytest.raises(ValueError, match="binding differs"):
        runner.validate_qualification_evidence(run, document)


@pytest.mark.parametrize("target", ["stream", "context", "binding"])
def test_actual_saved_bytes_are_verified(saved_pass, target):
    run, cell, _, _, _, _, document = saved_pass
    directory = runner._qualification_capture_directory(run, cell, "core")
    filename = {"stream": "stream.bin", "context": "context.json", "binding": "binding.json"}[
        target
    ]
    (directory / filename).write_bytes(b"changed")
    with pytest.raises((ValueError, json.JSONDecodeError)):
        runner.validate_qualification_evidence(run, document)


@pytest.mark.parametrize(
    "part,field,value",
    [
        ("lifecycle", "worker_pid", 101),
        ("lifecycle", "worker_exit_confirmed", False),
        ("recovery", "decode_context_sha256", "0" * 64),
        ("accounting", "final_bits", 0),
        ("input", "input_sha256", "0" * 64),
    ],
)
def test_nested_worker_input_and_cost_facts_are_verified(saved_pass, part, field, value):
    run, _, _, _, _, _, original = saved_pass
    document = copy.deepcopy(original)
    preflight = document["evidence"][0]["preflight"]
    target = {
        "lifecycle": preflight["diagnostics"]["independent_recovery_worker_lifecycle"],
        "recovery": preflight["diagnostics"]["independent_recovery"],
        "accounting": preflight["accounting"],
        "input": preflight["input_validation"],
    }[part]
    target[field] = value
    resign(document)
    with pytest.raises(ValueError, match="evidence differs"):
        runner.validate_qualification_evidence(run, document)


def test_pilot_worker_file_rejects_wrong_codec_and_fixture(saved_pass):
    run, cell, task, routed, _, _, _ = saved_pass
    pilot = {"lifecycle": {"worker_pid": 500}}
    path = run.path / "pilot_probes/500.json"
    path.parent.mkdir()
    observed = {
        "schema_version": "tscb.comparison-pilot-probe-binding.v1",
        "worker_pid": 500,
        "codec_key": cell["codec_key"],
        "algorithm_id": cell["algorithm_id"],
        "dataset_id": routed.dataset_id,
        "input_sha256": routed.input_sha256,
        "canonical_raw_bits": routed.canonical_raw_bits,
        "track": "VALUE",
        "parameters": cell["parameters"],
        "compatibility_plan_id": "compat-one",
        "source_reject_fallback": False,
    }
    for field, value in (
        (None, None),
        ("codec_key", "other-codec"),
        ("dataset_id", "other-fixture"),
    ):
        changed = {**observed, **({field: value} if field is not None else {})}
        payload = canonical_json_bytes(changed)
        path.write_bytes(payload)
        reference = {
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
        if field is None:
            runner._validate_saved_pilot_probe(run, cell, pilot, reference, task, routed)
        else:
            with pytest.raises(ValueError, match="binding differs"):
                runner._validate_saved_pilot_probe(run, cell, pilot, reference, task, routed)


@pytest.mark.parametrize("cold_pass", [True, False])
def test_preflight_capture_preserves_real_payload_and_failed_attempt(
    saved_pass, monkeypatch, cold_pass
):
    """Mock isolation responses; no adapter/session or codec is invoked."""
    from tscompbench.contracts import RunStatus
    from tscompbench.execution import preflight as module

    run, cell, task_doc, routed, _, _, _ = saved_pass
    compatibility = SimpleNamespace(
        status=SimpleNamespace(value="NATIVE"),
        effective_loss_mode="LOSSLESS",
        operations=(),
        input_descriptor=SimpleNamespace(dtype_vector=("<i2",)),
    )
    task = SimpleNamespace(
        **{name: task_doc[name] for name in ("task_id", "dataset_id", "algorithm_id", "config_id")},
        track=BenchmarkTrack.VALUE,
        status=RunStatus.PLANNED,
        reason_code="OK",
        execution=SimpleNamespace(**task_doc["execution"], artifact_sha256="artifact"),
        preprocess=SimpleNamespace(stages=()),
        compatibility=compatibility,
        resource_limits={"timeout_seconds": 1, "memory_limit_bytes": 1_000_000},
    )
    encoded = SimpleNamespace(
        stream=b"real-saved-payload",
        stream_sha256=hashlib.sha256(b"real-saved-payload").hexdigest(),
        ledger=SimpleNamespace(to_document=lambda: {}),
    )

    class Boundary:
        passed = True

    class Observation:
        decoded = None
        determinism_match = True
        input_immutable = True
        canary_intact = True

    observed = Observation()
    observed.encoded = encoded
    lifecycle = {
        "start_method": "spawn",
        "worker_pid": 333,
        "worker_exit_confirmed": True,
        "exit_code": 0 if cold_pass else 9,
    }
    calls = iter(
        [
            SimpleNamespace(status=RunStatus.PASS, value=Boundary()),
            SimpleNamespace(status=RunStatus.PASS, value=observed, limit_method="MOCK"),
            SimpleNamespace(
                status=RunStatus.PASS if cold_pass else RunStatus.CRASHED,
                value=(None, {"worker_pid": 333}),
                exception_type="MockFailure",
                message="mocked",
                lifecycle_document=lambda: lifecycle,
            ),
        ]
    )
    monkeypatch.setattr(module, "BoundarySuiteReport", Boundary)
    monkeypatch.setattr(module, "RoundTripObservation", Observation)
    monkeypatch.setattr(module, "reviewed_pipeline_executor", lambda *args: True)
    monkeypatch.setattr(module, "route_canonical_artifact", lambda *args: routed)
    monkeypatch.setattr(module, "validate_routed_input", lambda *args: None)
    monkeypatch.setattr(
        module,
        "prepare_execution_input",
        lambda *args, **kwargs: SimpleNamespace(
            original=routed,
            codec_input=routed,
        ),
    )
    monkeypatch.setattr(module, "run_isolated", lambda *args, **kwargs: next(calls))
    monkeypatch.setattr(
        module,
        "validate_common_correctness",
        lambda *args, **kwargs: SimpleNamespace(status=RunStatus.PASS),
    )
    monkeypatch.setattr(module, "bind_decode_context", lambda artifact, context: artifact)
    directory = run.path / "mock-capture"
    result, _ = module.preflight_task(
        task,
        SimpleNamespace(document={}, key="codec-one"),
        {"kind": "BUILTIN_HARNESS"},
        None,
        SimpleNamespace(adapter_id="adapter-one"),
        cell["parameters"],
        capture_directory=directory,
    )
    assert result.status is (RunStatus.PASS if cold_pass else RunStatus.CRASHED)
    artifacts = result.diagnostics["qualification_artifacts"]
    assert (directory / "stream.bin").read_bytes() == encoded.stream
    assert (
        hashlib.sha256((directory / "context.json").read_bytes()).hexdigest()
        == artifacts["context"]["sha256"]
    )
    assert result.diagnostics["independent_recovery_worker_lifecycle"] == lifecycle
    before = (directory / "stream.bin").read_bytes()
    # A later attempt cannot replace a retained successful or failed stream.
    calls = iter(
        [
            SimpleNamespace(status=RunStatus.PASS, value=Boundary()),
            SimpleNamespace(status=RunStatus.PASS, value=observed, limit_method="MOCK"),
        ]
    )
    with pytest.raises(FileExistsError):
        module.preflight_task(
            task,
            SimpleNamespace(document={}, key="codec-one"),
            {"kind": "BUILTIN_HARNESS"},
            None,
            SimpleNamespace(adapter_id="adapter-one"),
            cell["parameters"],
            capture_directory=directory,
        )
    assert (directory / "stream.bin").read_bytes() == before


def test_pilot_uses_the_same_frozen_representative_as_its_generator(saved_pass, monkeypatch):
    from tscompbench.measurement import v32_protocol

    run, cell, task, routed, _, preflight, _ = saved_pass
    first = {**cell, "cell_id": "first-cell", "logical_content_id": "test-content"}
    last = {**cell, "cell_id": "last-cell", "logical_content_id": "test-content"}
    run.cells = {first["cell_id"]: first, last["cell_id"]: last}
    run.protocol = SimpleNamespace(protocol_id="protocol", profile="STEADY_PROCESS")
    run.corpus = SimpleNamespace(id="test-corpus")
    run.bundle["development_dataset"] = "development"
    monkeypatch.setattr(
        runner, "_saved_auxiliary_artifact", lambda *args: SimpleNamespace(metadata={})
    )
    monkeypatch.setattr(runner, "_comparison_content_sha256", lambda *args: "development-content")
    observed = []

    def actual_capture(*args):
        observed.append(args[1]["cell_id"])
        assert args[1]["cell_id"] == "last-cell"

    monkeypatch.setattr(runner, "_validate_preflight_artifacts", actual_capture)
    monkeypatch.setattr(runner, "_validate_saved_pilot_probe", lambda *args: None)
    monkeypatch.setattr(v32_protocol, "validate_pilot_evidence", lambda *args: {"eligible": True})
    document = {
        "schema_version": "tscb.comparison-pilot-set.v1",
        "comparison_id": "comparison-one",
        "protocol_id": "protocol",
        "test_corpus_id": "test-corpus",
        "status": "PASS",
        "members": [
            {
                "member_id": cell["member_id"],
                "config_label": cell["config_label"],
                "development_preflight": preflight,
                "pilot": {
                    "development_corpus_id": "development-content",
                    "test_corpus_id": "test-corpus",
                },
            }
        ],
    }
    document["pilot_id"] = stable_id("comparison-pilot-set", document)
    runner.validate_comparison_pilots(run, document)
    assert observed == ["last-cell"]
