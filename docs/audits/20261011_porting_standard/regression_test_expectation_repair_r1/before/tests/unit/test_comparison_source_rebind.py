"""Source migrations preserve decisions and cannot reuse historical acceptance."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.comparison import (
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    compile_group_plan,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "comparison_source_rebind", ROOT / "tools/rebind_v32_comparison_sources.py"
)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
BASES = (
    "g-int-ll-i16-v32-20261010-v3.json",
    "g-quality-v32-20261010-v5.json",
    "g-timestamp-v32-20261010-v1.json",
    "g-query-ll-variants-v32-20261010.json",
)


def load(name):
    return json.loads((ROOT / "configs/comparisons" / name).read_text())


def compile_current(document):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    return compile_group_plan(
        GroupSpec.from_document(document["group"]),
        ComparisonContract.from_document(document["contract"]),
        CorpusSpec.from_document(document["corpus"]),
        MethodConfigMap.from_document(document["config_map"]),
        ExpectedOutcomeMatrix.from_document(document["expected_matrix"]),
        codec_registry=registry,
        active_codec_keys=set(
            json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
        ),
    )


@pytest.mark.parametrize("name", BASES)
def test_current_source_revision_preserves_every_comparison_decision(name):
    old = load(name)
    preserved = copy.deepcopy(old)
    with pytest.raises(ValueError, match="implementation source differs"):
        compile_current(old)
    current, proof = tool.rebind_document(ROOT, old, "independent-source-revision-test")
    assert old == preserved
    for field in (
        "corpus",
        "protocol",
        "analysis_policy",
        "dataset_bindings",
        "cpu_affinity",
        "seed",
        "development_dataset",
        "qualification_datasets",
    ):
        assert current[field] == old[field]
    for field in ("selection_policy", "fidelity", "resources", "recovery", "estimand"):
        assert current["contract"][field] == old["contract"][field]
    assert current["config_map"]["members"] == old["config_map"]["members"]
    assert current["expected_matrix"]["entries"] == old["expected_matrix"]["entries"]
    assert proof["old_group_id"] != proof["current_group_id"]
    assert proof["corpus_id_preserved"] == CorpusSpec.from_document(old["corpus"]).id
    assert proof["status"] == "PLANNED_SOURCE_REVISION_ONLY"
    assert proof["qualification_transferred"] is proof["formal_results_transferred"] is False
    assert proof["full_parity_granted"] is proof["historical_evidence_rewritten"] is False
    plan = compile_current(current)
    assert plan.denominators == proof["planned_denominators"]


def test_cpp_source_label_changes_without_changing_lzss_method_semantics():
    old = load(BASES[2])
    current, proof = tool.rebind_document(ROOT, old, "cpp-source-revision-test")
    prior = next(m for m in old["group"]["members"] if m["codec_key"] == "lzss-raw")
    member = next(m for m in current["group"]["members"] if m["codec_key"] == "lzss-raw")
    changed = next(m for m in proof["members"] if m["codec_key"] == "lzss-raw")
    assert "Rust source" in prior["method"]["name"]
    assert "C++ rewrite" in member["method"]["name"]
    assert changed["old_method_id"] != changed["current_method_id"]
    assert changed["old_method_name"] == prior["method"]["name"]
    assert changed["current_method_name"] == member["method"]["name"]
    for field in ("definition_sha256", "semantic_version", "mechanism", "variant"):
        assert prior["method"][field] == member["method"][field]


@pytest.mark.parametrize("revision", ["", "../overwrite", "with space", "20261010-v3", "x" * 129])
def test_requires_an_explicit_safe_new_revision(revision):
    with pytest.raises(ValueError, match="revision"):
        tool.rebind_document(ROOT, load(BASES[0]), revision)


@pytest.mark.parametrize("fault", ["method", "method_id", "source_tag", "equivalence", "chain"])
def test_cannot_launder_changed_semantics_or_unbound_identity(fault):
    document = load(BASES[1])
    member = document["group"]["members"][0]
    if fault == "method":
        member["method"]["definition_sha256"] = "0" * 64
    elif fault == "method_id":
        member["implementation"]["method_id"] = "v3:method:sha256:" + "0" * 64
    elif fault == "source_tag":
        member["shared_code_tags"] = ["SOURCE_ARTIFACT:unrelated"]
    elif fault == "equivalence":
        document["group"]["method_equivalence"][0]["evidence"].append("SOURCE_ARTIFACT:unrelated")
    else:
        document["group"]["contract_id"] = "v3:comparison-contract:sha256:" + "0" * 64
    with pytest.raises(ValueError):
        tool.rebind_document(ROOT, document, "rejected-source-revision-test")


def test_uses_explicit_root_and_refuses_registration_changes(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "registry", tmp_path / "registry")
    document = load(BASES[0])
    _, proof = tool.rebind_document(tmp_path, document, "copied-source-revision-test")
    assert proof["registration_snapshot"] == tool.registration_snapshot(tmp_path)
    actual = tool.registration_snapshot
    calls = 0

    def drift(root):
        nonlocal calls
        calls += 1
        result = actual(root)
        if calls == 2:
            result[0]["sha256"] = "0" * 64
        return result

    monkeypatch.setattr(tool, "registration_snapshot", drift)
    with pytest.raises(ValueError, match="registration changed"):
        tool.rebind_document(tmp_path, document, "drift-source-revision-test")


@pytest.mark.parametrize("existing", ["bundle", "proof"])
def test_cli_preserves_existing_bundle_and_proof(tmp_path, monkeypatch, existing):
    output, proof = tmp_path / "new.json", tmp_path / "proof.json"
    preserved = output if existing == "bundle" else proof
    preserved.write_text("historical result")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebind",
            "--root",
            str(ROOT),
            "--base-bundle",
            str(ROOT / "configs/comparisons" / BASES[0]),
            "--revision",
            "cli-source-test",
            "--output",
            str(output),
            "--proof",
            str(proof),
        ],
    )
    with pytest.raises(FileExistsError):
        tool.main()
    assert preserved.read_text() == "historical result"
    assert not (proof if existing == "bundle" else output).exists()


def test_cli_proof_binds_actual_output_and_preserves_base(tmp_path, monkeypatch):
    output, proof_path = tmp_path / "new.json", tmp_path / "proof.json"
    base = ROOT / "configs/comparisons" / BASES[0]
    original = base.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebind",
            "--root",
            str(ROOT),
            "--base-bundle",
            str(base),
            "--revision",
            "cli-source-test",
            "--output",
            str(output),
            "--proof",
            str(proof_path),
        ],
    )
    tool.main()
    proof = json.loads(proof_path.read_text())
    assert proof["output_bundle"]["sha256"] == tool.sha(output)
    assert proof["driver"]["sha256"] == tool.sha(Path(tool.__file__))
    assert proof["base_bundle"]["sha256"] == tool.sha(base)
    assert base.read_bytes() == original
