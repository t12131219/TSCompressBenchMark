"""Active evidence identity negatives use fabricated workers and no codec calls."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from tscompbench.accounting import AccountingLedger
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import read_canonical, write_canonical
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "active_evidence_binding_tool", ROOT / "tools/qualify_v32_active_entries.py"
)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _resign(result):
    result.pop("evidence_id", None)
    result["evidence_id"] = stable_id("active-entry-qualification-evidence-v32", result)
    return result


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    # Resolution inspects registry/source files and bytes, without constructing
    # adapters or invoking qualification/measurement workers.
    monkeypatch.setattr(tool, "create_adapter", lambda *_: pytest.fail("codec must not load"))
    monkeypatch.setattr(tool, "preflight_task", lambda *_a, **_k: pytest.fail("codec must not run"))
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    environment = {"environment_id": "MOCK_TEST_ENVIRONMENT", "cpu": {"flags": [], "affinity": [0]}}
    entries, results = [], []
    for codec in ("lz4-frame", "zstd-frame"):
        manifest = registry.get(codec)
        case = next(
            case for case in tool.select_cases(ROOT, registry, codec, 0) if case["track"] == "VALUE"
        )
        entry = {
            "codec_key": codec,
            "algorithm_id": manifest.algorithm_id,
            "source_artifact_id": manifest.source_artifact_id,
            "cases": [case],
        }
        entries.append(entry)
        dataset = load_dataset(
            DatasetRegistry(ROOT / "registry/datasets", ROOT).load(case["dataset_key"])
        )
        path = tmp_path / "datasets" / f"{case['dataset_key']}.tscb"
        if not path.exists():
            write_canonical(dataset, path)
        artifact = read_canonical(path)
        resolved = tool._resolve_case(ROOT, entry, case, environment, artifact)
        _, _, descriptor, _, _, task, routed, input_report, context = resolved
        stream = b"pure mock compressed object; never decode this as real codec output"
        stream_hash = hashlib.sha256(stream).hexdigest()
        capture_root = tmp_path / "qualification_artifacts" / case["case_id"].rsplit(":", 1)[-1]
        capture_root.mkdir(parents=True)
        captured = {}
        for name, filename, payload in (
            ("stream", "stream.bin", stream),
            ("context", "context.json", context.serialized),
        ):
            target = capture_root / filename
            target.write_bytes(payload)
            captured[name] = {
                "path": str(target),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        captured["binding"] = {
            "task_id": task.task_id,
            "dataset_id": task.dataset_id,
            "algorithm_id": task.algorithm_id,
            "config_id": task.config_id,
            "execution_path_hash": task.execution.execution_path_hash,
            "track": task.track,
            "input_sha256": routed.input_sha256,
            "canonical_raw_bits": routed.canonical_raw_bits,
            "adapter_id": task.execution.adapter_id,
            "parameters": case["parameters"],
        }
        (capture_root / "binding.json").write_bytes(canonical_json_bytes(captured) + b"\n")
        ledger = AccountingLedger.create(
            track=task.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=len(stream) * 8,
            external_side_information_bits=len(context.serialized) * 8,
            accounting_method="MOCK_STREAM+PERSISTED_DECODE_CONTEXT_V1",
        )
        preflight = {
            "status": "PASS",
            "input_validation": input_report,
            "correctness": {"status": "PASS"},
            "boundary": {
                "passed": True,
                "observations": [{"status": "PASS", "reason": "MOCK_ONLY"}],
            },
            "accounting": ledger.to_document(),
            "bitstream_sha256": stream_hash,
            "diagnostics": {
                "qualification_artifacts": captured,
                "independent_recovery": {
                    "start_method": "spawn",
                    "encoder_session_available": False,
                    "original_input_available": False,
                    "output_owned_in_worker": True,
                    "stream_sha256": stream_hash,
                    "decode_context_sha256": context.sha256,
                    "required_external_bits": len(context.serialized) * 8,
                    "worker_pid": 200,
                },
                "independent_recovery_worker_lifecycle": {
                    "start_method": "spawn",
                    "worker_exit_confirmed": True,
                    "exit_code": 0,
                    "worker_pid": 200,
                    "parent_pid": 100,
                },
            },
        }
        preflight["run_record"] = tool._preflight_binding(
            entry, case, artifact, task, descriptor, routed, context, preflight
        )
        result = {
            "case_id": case["case_id"],
            "codec_key": codec,
            "canonical": tool.file_evidence(ROOT, path),
            "task": task.to_document(),
            "preflight": preflight,
            "acceptance": tool.preflight_acceptance(preflight),
        }
        results.append(json.loads(canonical_json_bytes(result)))
    plan = {"entries": entries, "plan_id": "PURE_MOCK_PLAN"}
    for result in results:
        result["plan_id"] = plan["plan_id"]
        _resign(result)
    return tmp_path, plan, environment, results


def test_correctly_bound_mock_evidence_audits_without_codec(evidence):
    output, plan, environment, results = evidence
    for result in results:
        assert result["acceptance"]["status"] == "SCOPED_PASS"
        tool.validate_case_evidence(result, plan, output=output, environment=environment)


def test_copy_other_codec_pass_and_resign_outer_hash_is_rejected(evidence):
    output, plan, environment, results = evidence
    copied = copy.deepcopy(results[1])
    target = results[0]
    copied.update(
        case_id=target["case_id"], codec_key=target["codec_key"], canonical=target["canonical"]
    )
    _resign(copied)
    with pytest.raises(ValueError, match="task algorithm/config/profile/dataset"):
        tool.validate_case_evidence(copied, plan, output=output, environment=environment)


@pytest.mark.parametrize(
    "field", ["algorithm_id", "config_id", "profile_id", "dataset_id", "task_id"]
)
def test_resigned_task_identity_change_is_rejected(evidence, field):
    output, plan, environment, results = evidence
    changed = copy.deepcopy(results[0])
    changed["task"][field] = "foreign-task-component"
    _resign(changed)
    with pytest.raises(ValueError, match="task algorithm/config/profile/dataset"):
        tool.validate_case_evidence(changed, plan, output=output, environment=environment)


@pytest.mark.parametrize(
    "mutation",
    [
        "input_hash",
        "shape",
        "nested_algorithm",
        "worker_pid",
        "worker_exit",
        "stream_file",
        "context_file",
        "canonical_hash",
        "binding_file",
    ],
)
def test_resigned_nested_evidence_or_actual_artifact_change_is_rejected(evidence, mutation):
    output, plan, environment, results = evidence
    changed = copy.deepcopy(results[0])
    preflight = changed["preflight"]
    if mutation == "input_hash":
        preflight["input_validation"]["input_sha256"] = "0" * 64
    elif mutation == "shape":
        preflight["input_validation"]["observed_shapes"][0][0] += 1
    elif mutation == "nested_algorithm":
        preflight["run_record"]["algorithm_id"] = "another-algorithm"
    elif mutation == "worker_pid":
        preflight["diagnostics"]["independent_recovery_worker_lifecycle"]["worker_pid"] = 300
    elif mutation == "worker_exit":
        preflight["diagnostics"]["independent_recovery_worker_lifecycle"][
            "worker_exit_confirmed"
        ] = False
    elif mutation in {"stream_file", "context_file"}:
        name = "stream" if mutation == "stream_file" else "context"
        artifact = preflight["diagnostics"]["qualification_artifacts"][name]
        Path(artifact["path"]).write_bytes(b"foreign retained bytes")
    elif mutation == "canonical_hash":
        changed["canonical"]["actual_sha256"] = "0" * 64
    else:
        path = (
            output
            / "qualification_artifacts"
            / changed["case_id"].rsplit(":", 1)[-1]
            / "binding.json"
        )
        path.write_text("{}")
    _resign(changed)
    with pytest.raises(ValueError):
        tool.validate_case_evidence(changed, plan, output=output, environment=environment)


def test_missing_original_canonical_cannot_be_replaced_by_metadata_hash(evidence):
    output, plan, environment, results = evidence
    changed = copy.deepcopy(results[0])
    Path(changed["canonical"]["path"]).unlink()
    _resign(changed)
    with pytest.raises(ValueError, match="canonical artifact is missing"):
        tool.validate_case_evidence(changed, plan, output=output, environment=environment)


def test_resigned_valid_canonical_of_a_different_fixture_is_rejected(evidence):
    output, plan, environment, results = evidence
    changed = copy.deepcopy(results[0])
    foreign = load_dataset(
        DatasetRegistry(ROOT / "registry/datasets", ROOT).load("rewrite_byte_uts")
    )
    path = Path(changed["canonical"]["path"])
    path.unlink()
    write_canonical(foreign, path)
    changed["canonical"] = tool.file_evidence(ROOT, path)
    _resign(changed)
    with pytest.raises(
        ValueError, match="canonical bytes differ from the original planned fixture"
    ):
        tool.validate_case_evidence(changed, plan, output=output, environment=environment)


def test_resigned_closed_ledger_with_foreign_original_denominator_is_rejected(evidence):
    output, plan, environment, results = evidence
    changed = copy.deepcopy(results[0])
    ledger = changed["preflight"]["accounting"]
    changed["preflight"]["accounting"] = json.loads(
        canonical_json_bytes(
            AccountingLedger.create(
                track=BenchmarkTrack.VALUE,
                canonical_raw_bits=ledger["canonical_raw_bits"] + 64,
                final_physical_bytes=ledger["final_physical_bytes"],
                value_bits=ledger["value_bits"],
                external_side_information_bits=ledger["external_side_information_bits"],
                accounting_method=ledger["accounting_method"],
            ).to_document()
        )
    )
    changed["acceptance"] = tool.preflight_acceptance(changed["preflight"])
    assert changed["acceptance"]["status"] == "SCOPED_PASS"
    _resign(changed)
    with pytest.raises(ValueError, match="original denominator/track"):
        tool.validate_case_evidence(changed, plan, output=output, environment=environment)


def test_resigned_foreign_context_and_all_its_hashes_are_rejected(evidence):
    output, plan, environment, results = evidence
    changed = copy.deepcopy(results[0])
    preflight = changed["preflight"]
    captured = preflight["diagnostics"]["qualification_artifacts"]
    path = Path(captured["context"]["path"])
    context = json.loads(path.read_bytes())
    context["adapter_id"] = "foreign-recovery-adapter"
    serialized = canonical_json_bytes(context)
    path.write_bytes(serialized)
    digest = hashlib.sha256(serialized).hexdigest()
    captured["context"].update(sha256=digest, bytes=len(serialized))
    (path.parent / "binding.json").write_bytes(canonical_json_bytes(captured) + b"\n")
    recovery = preflight["diagnostics"]["independent_recovery"]
    recovery.update(decode_context_sha256=digest, required_external_bits=len(serialized) * 8)
    ledger = preflight["accounting"]
    preflight["accounting"] = json.loads(
        canonical_json_bytes(
            AccountingLedger.create(
                track=BenchmarkTrack.VALUE,
                canonical_raw_bits=ledger["canonical_raw_bits"],
                final_physical_bytes=ledger["final_physical_bytes"],
                value_bits=ledger["value_bits"],
                external_side_information_bits=len(serialized) * 8,
                accounting_method=ledger["accounting_method"],
            ).to_document()
        )
    )
    preflight["run_record"].update(
        decode_context=context,
        decode_context_sha256=digest,
        required_external_bits=len(serialized) * 8,
    )
    changed["acceptance"] = tool.preflight_acceptance(preflight)
    assert changed["acceptance"]["status"] == "SCOPED_PASS"
    _resign(changed)
    with pytest.raises(ValueError, match="actual paid recovery context differs"):
        tool.validate_case_evidence(changed, plan, output=output, environment=environment)
