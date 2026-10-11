"""Fail closed on cross-version IDs without changing reviewed active scope."""

import copy
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from algorithm_scope import load_scope  # noqa: E402
from candidate_integration_ledger import (  # noqa: E402
    LEDGER_PATH,
    REVIEWED,
    build_ledger,
    read_selection,
    resolve_candidate,
    seal_ledger,
    validate_ledger,
)


@pytest.fixture
def reviewed_root(tmp_path):
    (tmp_path / "registry").mkdir()
    for relative in ("registry/algorithm_scope.json", LEDGER_PATH):
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    return tmp_path


@pytest.fixture
def current_root(reviewed_root):
    csv_path = ROOT / "algorithm_implementation_plan.csv"
    if not csv_path.exists():
        pytest.skip("local CSV is ignored; checked-in ledger is verified independently")
    shutil.copyfile(csv_path, reviewed_root / csv_path.name)
    codec_root = reviewed_root / "registry/codecs"
    codec_root.mkdir()
    ledger = validate_ledger(reviewed_root)
    for key in {r["key"] for record in ledger["records"] for r in record["registrations"]}:
        shutil.copyfile(ROOT / f"registry/codecs/{key}.json", codec_root / f"{key}.json")
    # The repository ledger preserves its historical registration snapshots.
    # This fixture represents a fresh review of the copied current manifests.
    current_snapshot = build_ledger(reviewed_root)
    current_snapshot["review_status"] = REVIEWED
    write_ledger(reviewed_root, current_snapshot)
    return reviewed_root


def write_ledger(root, document, *, seal=True):
    if seal:
        seal_ledger(document)
    (root / LEDGER_PATH).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def rewrite_csv(root, change):
    path = root / "algorithm_implementation_plan.csv"
    _, rows = read_selection(path)
    change(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_reviewed_snapshot_preserves_legacy_scope_when_local_csv_is_absent(reviewed_root):
    scope_bytes = (reviewed_root / "registry/algorithm_scope.json").read_bytes()
    assert load_scope(reviewed_root) == json.loads(scope_bytes)
    ledger = validate_ledger(reviewed_root)
    assert len(ledger["records"]) == 166
    assert (reviewed_root / "registry/algorithm_scope.json").read_bytes() == scope_bytes


def test_reviewed_current_csv_unblocks_tools_without_relabeling_scope(current_root):
    scope_bytes = (current_root / "registry/algorithm_scope.json").read_bytes()
    csv_bytes = (current_root / "algorithm_implementation_plan.csv").read_bytes()
    assert load_scope(current_root) == json.loads(scope_bytes)
    ledger = validate_ledger(current_root, check_registrations=True)
    assert ledger["mapping_counts"] == {
        "EXACT_NAME_SOURCE_VARIANT_MATCH": 163,
        "NEW_RECORD_NO_ADMISSION": 3,
    }
    assert (current_root / "registry/algorithm_scope.json").read_bytes() == scope_bytes
    assert (current_root / "algorithm_implementation_plan.csv").read_bytes() == csv_bytes


def test_every_record_has_a_destination_without_fabricating_method_coverage(reviewed_root):
    ledger = validate_ledger(reviewed_root)
    records = ledger["records"]
    assert Counter(record["recommendation"] for record in records) == {
        "主集合保留": 79,
        "扩展保留": 48,
        "组件/配置/来源保留": 39,
    }
    assert sum(record["record_id"] != record["original_ref"]["id"] for record in records) == 152
    retired = [
        record
        for record in records
        if any(d["kind"] == "EXPLICITLY_RETIRED" for d in record["destinations"])
    ]
    assert len(retired) == 19
    assert all(record["destinations"] and record["source_names"] for record in records)
    assert all(record["method_id"] is None for record in records)
    assert ledger["coverage_denominator"]["independent_method_denominator"] is None
    assert ledger["coverage_denominator"]["planned_record_count"] == 147
    assert (
        len(
            {
                r["key"]
                for record in records
                for r in record["registrations"]
                if r["scope_status"] == "IN_SCOPE"
            }
        )
        == 33
    )
    assert (
        sum(
            any(r["scope_status"] == "IN_SCOPE" for r in record["registrations"])
            for record in records
        )
        == 28
    )


def test_colliding_v10_ids_resolve_only_with_an_explicit_namespace(reviewed_root):
    ledger = validate_ledger(reviewed_root)
    current = resolve_candidate(
        root=reviewed_root, selection_sha256=ledger["selection"]["sha256"], record_id="V10"
    )
    old = resolve_candidate(
        root=reviewed_root,
        selection_sha256=ledger["legacy_scope"]["selection_sha256"],
        record_id="V10",
    )
    assert current["name"] == "lzsse2"
    assert current["legacy_candidate_id"] is None
    assert current["related_retired_implementation_keys"] == []
    assert current["registrations"][0]["scope_status"] == "RETAINED_OUT_OF_SCOPE"
    assert old["name"] == "TRISTAN"
    assert old["record_id"] == "V12"
    assert old["destinations"][0]["kind"] == "EXPLICITLY_RETIRED"
    with pytest.raises(ValueError, match="unknown"):
        resolve_candidate(root=reviewed_root, selection_sha256="0" * 64, record_id="V10")


def test_retired_combinations_do_not_retire_the_active_simdcomp_component(reviewed_root):
    ledger = validate_ledger(reviewed_root)
    simdcomp = resolve_candidate(
        root=reviewed_root, selection_sha256=ledger["selection"]["sha256"], record_id="T37"
    )
    assert simdcomp["name"] == "SIMDComp"
    assert {r["key"] for r in simdcomp["registrations"]} == {"simdcomp-u32"}
    assert set(simdcomp["related_retired_implementation_keys"]) == {
        "delta-simdcomp-u32",
        "for-simdcomp-u32",
    }
    assert "EXPLICITLY_RETIRED" not in {d["kind"] for d in simdcomp["destinations"]}


def test_sprintz_merged_sources_preserve_cross_table_ids_and_targets(reviewed_root):
    ledger = validate_ledger(reviewed_root)
    sprintz = resolve_candidate(
        root=reviewed_root, selection_sha256=ledger["selection"]["sha256"], record_id="V42"
    )
    assert {detail["source_ref"]["id"] for detail in sprintz["merged_sources"]} == {
        "T83",
        "T98",
        "T100",
    }
    assert {source["group"] for source in sprintz["source_names"]} == {
        "ValueCompress",
        "TimeStampCompress",
    }
    for detail in sprintz["merged_sources"]:
        assert detail["source_ref"]["namespace"] == "CSV_DECLARED_ORIGINAL_RECORD_ID"
        assert sprintz["candidate_id"] in detail["target_candidate_ids"]


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda d: d.update(review_status="DRAFT_REQUIRES_EXPLICIT_REVIEW"), "not a reviewed"),
        (lambda d: d["legacy_scope"].update(file_sha256="0" * 64), "frozen legacy scope"),
        (lambda d: d["records"].append(copy.deepcopy(d["records"][0])), "duplicate or incomplete"),
        (
            lambda d: d["records"][9].update(
                legacy_candidate_id=d["records"][11]["legacy_candidate_id"]
            ),
            "ambiguous version/name",
        ),
        (
            lambda d: d["records"][11]["destinations"].append({"kind": "PLANNED_BATCH_EVALUATION"}),
            "retired candidate",
        ),
        (lambda d: d["records"][0].update(registrations=[]), "active registration"),
        (
            lambda d: d["records"][4]["merged_sources"][0]["source_ref"].update(
                namespace="CURRENT_RECORD_ID"
            ),
            "ambiguous namespace",
        ),
    ],
)
def test_tampered_reviewed_mapping_fails_closed_without_local_csv(reviewed_root, mutation, message):
    document = validate_ledger(reviewed_root)
    mutation(document)
    write_ledger(reviewed_root, document)
    with pytest.raises(ValueError, match=message):
        validate_ledger(reviewed_root)


def test_damaged_snapshot_checksum_is_rejected(reviewed_root):
    document = validate_ledger(reviewed_root)
    document["records"][0]["source_urls"] = "corrupted provenance"
    write_ledger(reviewed_root, document, seal=False)
    with pytest.raises(ValueError, match="checksum"):
        validate_ledger(reviewed_root)


def test_csv_drift_with_a_reviewed_ledger_still_requires_review(current_root):
    path = current_root / "algorithm_implementation_plan.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="CSV selection changed"):
        load_scope(current_root)


@pytest.mark.parametrize(
    "change, message",
    [
        (
            lambda rows: rows[15].update(算法名称="Unrelated ABBA replacement"),
            "name/source/variant",
        ),
        (lambda rows: rows[9].update(原始记录ID="V10"), "duplicate or invalid"),
        (lambda rows: rows[15].update(合并来源明细JSON="[]"), "merged source IDs disagree"),
    ],
)
def test_draft_generation_rejects_ambiguous_provenance(current_root, change, message):
    rewrite_csv(current_root, change)
    with pytest.raises(ValueError, match=message):
        build_ledger(current_root)


def test_default_mapping_accepts_registration_drift_but_optional_snapshot_check_rejects_it(
    current_root,
):
    reviewed_snapshot = validate_ledger(current_root, check_registrations=True)
    ledger_bytes = (current_root / LEDGER_PATH).read_bytes()
    manifest = current_root / "registry/codecs/abba.json"
    document = json.loads(manifest.read_text())
    document["identity"]["display_name"] = "new reviewed implementation display name"
    manifest.write_text(json.dumps(document))
    assert validate_ledger(current_root) == reviewed_snapshot
    assert load_scope(current_root)["selection"]["record_count"] == 163
    with pytest.raises(ValueError, match="differs from verified"):
        validate_ledger(current_root, check_registrations=True)
    assert (current_root / LEDGER_PATH).read_bytes() == ledger_bytes


def test_draft_command_cannot_overwrite_the_reviewed_ledger():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/candidate_integration_ledger.py"),
            "draft",
            "--output",
            str(ROOT / LEDGER_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "cannot overwrite reviewed ledger, scope or CSV" in result.stderr
