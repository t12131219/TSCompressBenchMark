import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.comparison import (
    ComparisonContract,
    ComparisonSpecError,
    CorpusSpec,
    ExecutionJob,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    TaskSpec,
    compile_group_plan,
    implementation_id,
    method_id,
    public_projection,
    registered_source_closure_digest,
    validate_job_for_cell,
)
from tscompbench.comparison.schema import SCHEMAS

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/comparison/byte_bundle.json"
TYPES = {
    "contract": ComparisonContract,
    "corpus": CorpusSpec,
    "config_map": MethodConfigMap,
    "expected_matrix": ExpectedOutcomeMatrix,
    "group": GroupSpec,
    "task": TaskSpec,
    "job": ExecutionJob,
}


@pytest.fixture
def raw_bundle():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def registry():
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def bind_specs(raw, registry=None):
    raw = copy.deepcopy(raw)
    if registry is not None:
        for member in raw["group"]["members"]:
            key = member["codec_key"]
            if key not in registry.keys():
                continue
            member["implementation"]["source_artifact_id"] = registry.get(key).source_artifact_id
            member["implementation"]["source_closure_sha256"] = registered_source_closure_digest(
                registry, key
            )
    contract = ComparisonContract.from_document(raw["contract"])
    corpus = CorpusSpec.from_document(raw["corpus"])
    raw["config_map"]["contract_id"] = contract.id
    configs = MethodConfigMap.from_document(raw["config_map"])
    raw["expected_matrix"].update(
        contract_id=contract.id, corpus_id=corpus.id, config_map_id=configs.id
    )
    expected = ExpectedOutcomeMatrix.from_document(raw["expected_matrix"])
    raw["group"].update(
        contract_id=contract.id,
        corpus_id=corpus.id,
        config_map_id=configs.id,
        expected_matrix_id=expected.id,
    )
    group = GroupSpec.from_document(raw["group"])
    return group, contract, corpus, configs, expected


def compile_bundle(raw, registry):
    return compile_group_plan(
        *bind_specs(raw, registry),
        codec_registry=registry,
        active_codec_keys={"lz4-frame", "zstd-frame"},
    )


def project(raw):
    task = TaskSpec.from_document(raw["task"])
    job = copy.deepcopy(raw["job"])
    job["task_spec_id"] = task.id
    job["original_content_id"] = raw["task"]["logical_content_id"]
    return public_projection(
        ComparisonContract.from_document(raw["contract"]), task, ExecutionJob.from_document(job)
    )


def curve_bundle(raw):
    raw = copy.deepcopy(raw)
    fidelity = {
        "kind": "QUALITY_CURVE",
        "error_metric": None,
        "threshold": None,
        "unit": "ORIGINAL_VALUE_UNITS",
        "quality_metrics": ["MAXAE_V1", "RMSE_V1"],
    }
    recovery = {
        "mode": "APPROX_GRID",
        "null_semantics": "BITWISE",
        "coordinate_policy": "PRESERVE_ORIGINAL_GRID",
    }
    for name in ("task", "contract"):
        raw[name]["fidelity"] = fidelity
        raw[name]["recovery"] = recovery
    raw["job"]["loss_mode"] = "UNBOUNDED_LOSSY"
    raw["job"]["guarantee"] = {
        "kind": "UNBOUNDED",
        "metric": None,
        "threshold": None,
        "unit": "ORIGINAL_VALUE_UNITS",
        "original_domain_total": False,
    }
    return raw


@pytest.mark.parametrize("key", TYPES)
def test_each_spec_is_closed_versioned_parsed_and_immutable(raw_bundle, key):
    kind = TYPES[key]
    spec = kind.from_document(raw_bundle[key])
    before = spec.id
    returned = spec.to_document()
    returned["schema_version"] = "changed"
    assert spec.id == before
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        spec.serialized = b"{}"
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        spec.domain = "changed"
    malformed = copy.deepcopy(raw_bundle[key])
    malformed["typo"] = True
    with pytest.raises(ComparisonSpecError, match="unknown"):
        kind.from_document(malformed)
    malformed = copy.deepcopy(raw_bundle[key])
    malformed["schema_version"] = "future"
    with pytest.raises(ComparisonSpecError, match="version"):
        kind.from_document(malformed)


@pytest.mark.parametrize(
    "path", ["DIRECT", "EXACT_WIDEN", "BYTE_SERIALIZATION", "COLUMN_INDEPENDENT", "JOINT"]
)
def test_complete_object_projection_compares_paths_not_unique_execution_hashes(raw_bundle, path):
    original = project(raw_bundle)
    changed = copy.deepcopy(raw_bundle)
    changed["job"].update(
        path=path,
        config_id="another-legal-method-config",
        recipe_id="another-recipe",
        view_id="another-view",
        actual_input_id="another-native-input",
        actual_input_schema_id="another-native-dtype-and-rank",
        backend="OTHER_CPU_BACKEND",
        actual_isa="AVX2",
        build_id="another-build",
        implementation_id="another-implementation",
        method_id="another-method",
        algorithm_id="another-registration",
        execution_path_hash="another-closure",
        runtime_id="another-runtime",
    )
    compared = project(changed)
    assert compared.key == original.key
    assert compared.disclosures["execution_job_id"] != original.disclosures["execution_job_id"]
    assert (
        compared.disclosures["actual_input_schema_id"]
        != original.disclosures["actual_input_schema_id"]
    )


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda b: b["task"]["logical_schema"].update(track="TIMESTAMP"), "track"),
        (lambda b: b["task"].update(cost_boundary="SELF_CONTAINED_OBJECT"), "cost_boundary"),
        (lambda b: b["task"]["recovery"].update(null_semantics="SEMANTIC"), "recovery"),
        (lambda b: b["job"].update(state="CONTINUOUS_STREAM"), "state/timing"),
        (lambda b: b["job"].update(timing_boundary="E2E"), "state/timing"),
        (lambda b: b["job"]["resources"].update(threads=2), "resource"),
        (lambda b: b["job"]["resources"].update(machine_policy_id="OTHER_MACHINE"), "resource"),
    ],
)
def test_different_task_recovery_cost_state_and_resources_do_not_mix(raw_bundle, change, message):
    change(raw_bundle)
    with pytest.raises(ComparisonSpecError, match=message):
        project(raw_bundle)


def test_native_api_input_equality_and_controlled_isa_remain_constraints(raw_bundle):
    for key in ("task", "contract"):
        raw_bundle[key].update(cost_boundary="NATIVE_COMPONENT", workload="API_COMPONENT")
    raw_bundle["contract"].update(mode="COMMON_NATIVE_API", timing_boundary="CORE_API")
    raw_bundle["job"]["timing_boundary"] = "CORE_API"
    first = project(raw_bundle)
    raw_bundle["job"]["actual_input_id"] = "different-native-bits"
    assert project(raw_bundle).key != first.key
    raw_bundle["contract"]["resources"].update(isa_policy="FIXED", allowed_isa=["SCALAR", "AVX2"])
    raw_bundle["job"]["resources"] = copy.deepcopy(raw_bundle["contract"]["resources"])
    first = project(raw_bundle)
    raw_bundle["job"]["actual_isa"] = "AVX2"
    assert project(raw_bundle).key != first.key


def test_quality_curve_keeps_different_guarantee_types_and_parameter_points_together(raw_bundle):
    raw = curve_bundle(raw_bundle)
    first = project(raw)
    for loss_mode, guarantee in (
        (
            "ERROR_BOUNDED_LOSSY",
            {
                "kind": "PROVEN_BOUND",
                "metric": "MAXAE_V1",
                "threshold": "0.01",
                "unit": "ORIGINAL_VALUE_UNITS",
                "original_domain_total": True,
            },
        ),
        (
            "RATE_CONTROLLED_LOSSY",
            {
                "kind": "RATE_CONTROLLED",
                "metric": None,
                "threshold": None,
                "unit": "ORIGINAL_VALUE_UNITS",
                "original_domain_total": False,
            },
        ),
    ):
        raw["job"].update(
            loss_mode=loss_mode, guarantee=guarantee, config_id="different-curve-point"
        )
        compared = project(raw)
        assert compared.key == first.key
        assert compared.disclosures["fixed_error_guarantee_ranking_eligible"] is False
        assert compared.disclosures["loss_mode"] == loss_mode


def test_empirical_quality_never_grants_fixed_error_guarantee_membership(raw_bundle):
    raw = curve_bundle(raw_bundle)
    fixed = {
        "kind": "FIXED_ERROR",
        "error_metric": "MAXAE_V1",
        "threshold": "0.1",
        "unit": "ORIGINAL_VALUE_UNITS",
        "quality_metrics": [],
    }
    for key in ("task", "contract"):
        raw[key]["fidelity"] = fixed
    with pytest.raises(ComparisonSpecError, match="original-domain guarantee"):
        project(raw)
    raw["job"].update(
        loss_mode="ERROR_BOUNDED_LOSSY",
        guarantee={
            "kind": "PROVEN_BOUND",
            "metric": "MAXAE_V1",
            "threshold": "0.01",
            "unit": "ORIGINAL_VALUE_UNITS",
            "original_domain_total": True,
        },
    )
    assert project(raw).disclosures["fixed_error_guarantee_ranking_eligible"] is True
    raw["job"]["guarantee"]["original_domain_total"] = False
    with pytest.raises(ComparisonSpecError, match="original-domain guarantee"):
        project(raw)


def absolute_bundle(raw):
    raw = curve_bundle(raw)
    raw["contract"]["fidelity"] = {
        "kind": "FIXED_ERROR",
        "error_metric": "MAXAE_V1",
        "threshold": "0.1",
        "unit": "ORIGINAL_VALUE_UNITS",
        "quality_metrics": [],
    }
    for member, key in zip(raw["group"]["members"], ("serf-qt", "serf-xor"), strict=True):
        member["codec_key"] = key
    for member in raw["config_map"]["members"]:
        member["configs"][0].update(
            parameters={"error_bound": "0.1"},
            loss_mode="ERROR_BOUNDED_LOSSY",
            guarantee={
                "kind": "PROVEN_BOUND",
                "metric": "MAXAE_V1",
                "threshold": "0.1",
                "unit": "ORIGINAL_VALUE_UNITS",
                "original_domain_total": True,
            },
        )
    return raw


def compile_absolute(raw, registry):
    return compile_group_plan(
        *bind_specs(raw, registry),
        codec_registry=registry,
        active_codec_keys={"serf-qt", "serf-xor"},
    )


def test_registered_absolute_guarantee_binds_actual_normalized_parameter(raw_bundle, registry):
    raw = absolute_bundle(raw_bundle)
    plan = compile_absolute(raw, registry)
    assert all(cell.to_document()["parameters"]["error_bound"] == "0.1" for cell in plan.cells)
    raw["config_map"]["members"][0]["configs"][0]["parameters"]["error_bound"] = "1"
    with pytest.raises(ComparisonSpecError, match="normalized error_bound"):
        compile_absolute(raw, registry)


@pytest.mark.parametrize("field,value", [("metric", "RMSE_V1"), ("unit", "NORMALIZED")])
def test_native_absolute_bound_cannot_claim_another_metric_or_unit(
    raw_bundle, registry, field, value
):
    raw = absolute_bundle(raw_bundle)
    raw["contract"]["fidelity"].update(error_metric="RMSE_V1", unit="NORMALIZED")
    for member in raw["config_map"]["members"]:
        member["configs"][0]["guarantee"].update(metric="RMSE_V1", unit="NORMALIZED")
    raw["config_map"]["members"][0]["configs"][0]["guarantee"][field] = value
    with pytest.raises(ComparisonSpecError, match="MAXAE_V1 in original units"):
        compile_absolute(raw, registry)


def test_native_bound_never_proves_unaccounted_lossy_input_transform(raw_bundle, registry):
    raw = absolute_bundle(raw_bundle)
    raw["group"]["members"][0]["allowed_paths"].append("LOSSY_CAST")
    with pytest.raises(ComparisonSpecError, match="total original-domain bound"):
        compile_absolute(raw, registry)


def test_real_per_method_configs_are_normalized_and_matrix_denominators_frozen(
    raw_bundle, registry
):
    raw_bundle["config_map"]["members"][0]["configs"][0]["parameters"] = {"compression_level": 0}
    raw_bundle["config_map"]["members"][1]["configs"][0]["parameters"] = {"compression_level": 9}
    raw_bundle["expected_matrix"]["entries"][0]["expected"].update(
        outcome="REJECT",
        origin="SOURCE_DOMAIN",
        stage="DOMAIN_VALIDATION",
        reason="FROZEN_SOURCE_PREDICATE",
    )
    plan = compile_bundle(raw_bundle, registry)
    assert len(plan.cells) == plan.denominators["core_cells"] == 4
    assert plan.denominators["core_expected_pass_cells"] == 3
    assert plan.denominators["core_expected_reject_cells"] == 1
    assert plan.denominators["distinct_core_methods"] == 2
    assert plan.denominators["independent_real_sources"] == 2
    cells = [cell.to_document() for cell in plan.cells]
    assert {cell["parameters"]["compression_level"] for cell in cells} == {0, 9}
    assert all(
        cell["algorithm_id"] and cell["config_id"] and cell["legacy_config_id"] for cell in cells
    )


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda b: b["config_map"]["members"][0]["configs"][0]["parameters"].update(
                typo_parameter=1
            ),
            "illegal configuration",
        ),
        (
            lambda b: b["config_map"]["members"][0]["configs"][0]["framework_parameters"].update(
                unused_setting=1
            ),
            "framework parameter",
        ),
        (lambda b: b["config_map"]["members"].pop(), "every frozen member"),
        (lambda b: b["expected_matrix"]["entries"].pop(), "full frozen universe"),
        (lambda b: b["group"]["members"][0].update(codec_key="lz77"), "alias, retired"),
        (lambda b: b["group"]["members"][0].update(codec_key="tristan"), "alias, retired"),
    ],
)
def test_illegal_configs_and_missing_members_cannot_shrink_the_matrix(
    raw_bundle, registry, mutation, message
):
    mutation(raw_bundle)
    with pytest.raises(ComparisonSpecError, match=message):
        compile_bundle(raw_bundle, registry)


@pytest.mark.parametrize("shared", ["family", "entity", "independence_unit"])
def test_same_source_metadata_does_not_count_as_independent_real_sources(
    raw_bundle, registry, shared
):
    datasets = raw_bundle["corpus"]["datasets"]
    datasets[1]["source"][shared] = datasets[0]["source"][shared]
    corpus = CorpusSpec.from_document(raw_bundle["corpus"])
    assert len(corpus.independent_real_source_groups()) == 1
    with pytest.raises(ComparisonSpecError, match="independent real source"):
        compile_bundle(raw_bundle, registry)


def test_parent_resampling_chain_cannot_manufacture_another_real_source(raw_bundle):
    a, b = raw_bundle["corpus"]["datasets"]
    b["derivation"] = "RESAMPLE"
    b["parents"] = [
        {
            "dataset_id": a["dataset_id"],
            "source_kind": a["source_kind"],
            **{key: a["source"][key] for key in ("family", "entity", "independence_unit")},
        }
    ]
    assert len(CorpusSpec.from_document(raw_bundle["corpus"]).independent_real_source_groups()) == 1
    b["parents"][0]["source_kind"] = "SYNTHETIC"
    with pytest.raises(ComparisonSpecError, match="synthetic lineage"):
        CorpusSpec.from_document(raw_bundle["corpus"])


def test_method_identity_stable_across_display_and_implementation_builds(raw_bundle):
    member = raw_bundle["group"]["members"][0]
    identity = method_id(member["method"])
    definition = copy.deepcopy(member["method"])
    definition["name"] = "Display spelling update"
    assert method_id(definition) == identity
    impl = copy.deepcopy(member["implementation"])
    impl["implementation_variant"] = "OTHER_SOURCE_IMPLEMENTATION"
    assert implementation_id(impl) != implementation_id(member["implementation"])
    assert impl["method_id"] == identity
    raw_bundle["group"]["members"][1]["method"] = copy.deepcopy(member["method"])
    raw_bundle["group"]["members"][1]["implementation"]["method_id"] = identity
    with pytest.raises(ComparisonSpecError, match="cannot increase method count"):
        GroupSpec.from_document(raw_bundle["group"])


def test_actual_job_must_bind_to_frozen_configuration_and_allowed_recipe(raw_bundle, registry):
    specs = bind_specs(raw_bundle, registry)
    group, contract, *_ = specs
    plan = compile_group_plan(
        *specs, codec_registry=registry, active_codec_keys={"lz4-frame", "zstd-frame"}
    )
    cell = plan.cells[0]
    planned = cell.to_document()
    task = TaskSpec.from_document(raw_bundle["task"])
    job_doc = copy.deepcopy(raw_bundle["job"])
    for key in (
        "member_id",
        "method_id",
        "implementation_id",
        "algorithm_id",
        "config_id",
        "source_artifact_id",
    ):
        job_doc[key] = planned[key]
    job_doc["task_spec_id"] = task.id
    job = ExecutionJob.from_document(job_doc)
    validate_job_for_cell(group, cell, task, job)
    assert public_projection(contract, task, job).disclosures["config_id"] == planned["config_id"]
    job_doc["config_id"] = "unapproved-config"
    with pytest.raises(ComparisonSpecError, match="config_id"):
        validate_job_for_cell(group, cell, task, ExecutionJob.from_document(job_doc))


def test_all_exported_schemas_are_closed_and_match_parser_definitions():
    for name, expected in SCHEMAS.items():
        schema = json.loads((ROOT / f"schemas/comparison/v1/{name}.schema.json").read_text())
        assert schema == expected
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "path",
    [
        ("contract", "resources"),
        ("contract", "selection_policy"),
        ("task", "logical_schema"),
        ("job", "guarantee"),
    ],
)
def test_nested_unknown_fields_are_rejected(raw_bundle, path):
    raw_bundle[path[0]][path[1]]["unimplemented_option"] = "future"
    with pytest.raises(ComparisonSpecError, match="unknown"):
        TYPES[path[0]].from_document(raw_bundle[path[0]])


def test_adapter_unavailability_is_blocked_and_not_a_correct_source_rejection(raw_bundle):
    entry = raw_bundle["expected_matrix"]["entries"][0]["expected"]
    entry.update(outcome="REJECT", origin="ADAPTER", reason="ADAPTER_NOT_IMPLEMENTED")
    with pytest.raises(ComparisonSpecError, match="blocked"):
        ExpectedOutcomeMatrix.from_document(raw_bundle["expected_matrix"])
    entry["outcome"] = "BLOCKED"
    ExpectedOutcomeMatrix.from_document(raw_bundle["expected_matrix"])


def test_development_selection_does_not_run_as_evaluation_or_reuse_test_content(
    raw_bundle, registry
):
    development = copy.deepcopy(raw_bundle["corpus"]["datasets"][0])
    development.update(
        dataset_id="fixture-development",
        logical_content_id="fixture-dev-content",
        role="EXTENSION",
        split="VALIDATION",
    )
    raw_bundle["corpus"]["datasets"].append(development)
    policy = {
        **raw_bundle["contract"]["selection_policy"],
        "kind": "VALIDATION_SELECT",
        "selection_dataset_ids": [development["dataset_id"]],
        "objective": "MIN_FINAL_BITS",
    }
    raw_bundle["contract"]["selection_policy"] = policy
    raw_bundle["config_map"]["selection_policy"] = policy
    plan = compile_bundle(raw_bundle, registry)
    assert len(plan.cells) == 4
    assert development["dataset_id"] not in {cell.dataset_id for cell in plan.cells}
    development["logical_content_id"] = raw_bundle["corpus"]["datasets"][0]["logical_content_id"]
    with pytest.raises(ComparisonSpecError, match="share the same logical content"):
        compile_bundle(raw_bundle, registry)


def test_duplicate_normalized_defaults_do_not_create_extra_curve_points(raw_bundle, registry):
    policy = {
        **raw_bundle["contract"]["selection_policy"],
        "kind": "FULL_GRID",
        "max_configs_per_method": 2,
    }
    raw_bundle["contract"]["selection_policy"] = policy
    raw_bundle["config_map"]["selection_policy"] = policy
    first = raw_bundle["config_map"]["members"][0]
    duplicate = copy.deepcopy(first["configs"][0])
    duplicate["config_key"] = "same-default-again"
    duplicate["parameters"] = {"compression_level": 0}
    first["configs"].append(duplicate)
    for entry in list(raw_bundle["expected_matrix"]["entries"]):
        if entry["member_id"] == first["member_id"]:
            added = copy.deepcopy(entry)
            added["config_key"] = duplicate["config_key"]
            raw_bundle["expected_matrix"]["entries"].append(added)
    with pytest.raises(ComparisonSpecError, match="duplicate normalized configuration"):
        compile_bundle(raw_bundle, registry)


def test_cyclic_derivation_and_false_source_closure_fail_closed(raw_bundle, registry):
    a, b = raw_bundle["corpus"]["datasets"]
    for child, parent in ((a, b), (b, a)):
        child["derivation"] = "WINDOW"
        child["parents"] = [
            {
                "dataset_id": parent["dataset_id"],
                "source_kind": parent["source_kind"],
                **{key: parent["source"][key] for key in ("family", "entity", "independence_unit")},
            }
        ]
    with pytest.raises(ComparisonSpecError, match="cyclic"):
        CorpusSpec.from_document(raw_bundle["corpus"])
    fresh = json.loads(FIXTURE.read_text())
    specs = list(bind_specs(fresh, registry))
    document = specs[0].to_document()
    document["members"][0]["implementation"]["source_closure_sha256"] = "0" * 64
    specs[0] = GroupSpec.from_document(document)
    with pytest.raises(ComparisonSpecError, match="closure differs"):
        compile_group_plan(
            *specs, codec_registry=registry, active_codec_keys={"lz4-frame", "zstd-frame"}
        )


def test_golden_spec_method_implementation_and_projection_ids(raw_bundle):
    golden = json.loads((ROOT / "tests/fixtures/comparison/golden_ids.json").read_text())
    assert {
        name: kind.from_document(raw_bundle[name]).id for name, kind in TYPES.items()
    } == golden["specs"]
    for member in raw_bundle["group"]["members"]:
        assert method_id(member["method"]) == golden["methods"][member["member_id"]]
        assert (
            implementation_id(member["implementation"])
            == golden["implementations"][member["member_id"]]
        )
    assert project(raw_bundle).key == golden["projection"]
