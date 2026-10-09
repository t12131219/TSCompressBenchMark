"""Cross-CPU qualification coverage must not lose strategies or double-count cases."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from summarize_all_dataset_grids import grid_identity, insert_case, verify_record
from tscompbench.configuration import _load_profile


def test_grid_identity_ignores_only_execution_affinity():
    policy = {"algorithm": "a", "config_id": "c", "track": "VALUE",
              "profile": {"cpu_affinity": [2], "timing_scope": "CORE", "query_workload": False}}
    changed = deepcopy(policy)
    changed["profile"]["cpu_affinity"] = [3]
    assert grid_identity(policy) == grid_identity(changed)
    changed["profile"]["timing_scope"] = "E2E"
    assert grid_identity(policy) != grid_identity(changed)
    changed = deepcopy(policy)
    changed["profile"]["query_workload"] = True
    assert grid_identity(policy) != grid_identity(changed)


def test_duplicate_execution_cannot_inflate_grid_coverage():
    rows = {}
    row = {"dataset": "d", "grid_point_id": "p", "cpu_affinity": [2]}
    insert_case(rows, row)
    with pytest.raises(ValueError, match="Duplicate"):
        insert_case(rows, {**row, "cpu_affinity": [3]})
    assert len(rows) == 1


@pytest.mark.parametrize("tamper", ["eligibility", "accounting", "preflight", "correctness", "artifact", "affinity"])
def test_summary_rejects_false_pass_evidence(tamper):
    profile = _load_profile({"measurement_mode": "QUALIFICATION", "cpu_affinity": [2]}).as_document()
    policy = {"algorithm": "a", "config_id": "c", "track": "VALUE", "parameters": {},
              "templates": ["t"], "profile": profile}
    task = {"task_id": "task", "dataset_id": "d", "algorithm_id": "a", "config_id": "c",
            "track": "VALUE", "profile_id": _load_profile(profile).profile_id,
            "execution": {"cpu_affinity": [2], "artifact_sha256": "b" * 64, "execution_path_hash": "e"}}
    accounting = {k: 0 for k in ("timestamp_bits", "value_bits", "shared_bits", "unallocated_shared_bits",
                                "metadata_bits", "validity_bits", "dictionary_bits", "model_bits", "index_bits",
                                "checkpoint_bits", "checksum_bits", "padding_bits", "container_bits")}
    accounting.update(value_bits=8, serialized_bits=8, final_bits=8,
                      external_side_information_bits=0, final_physical_bytes=1)
    record = {k: task[k] for k in ("task_id", "dataset_id", "algorithm_id", "config_id", "track")}
    record.update(eligibility=False, execution_path_hash="e", correctness={"status": "PASS"},
                  accounting=accounting, bitstream_sha256="f" * 64, status="PASS", reason_code="ok")
    row = {k: policy[k] for k in ("algorithm", "config_id", "track", "parameters", "templates")}
    row.update(task=task, records=[record], status="PASS", reason_code="ok",
               preflight={"status": "PASS"}, bitstream_sha256="f" * 64)
    verify_record(row, policy, "d", "a", "b" * 64)
    if tamper == "eligibility":
        record["eligibility"] = True
    elif tamper == "accounting":
        accounting["final_bits"] += 8
    elif tamper == "preflight":
        row["preflight"]["status"] = "CORRECTNESS_FAIL"
    elif tamper == "correctness":
        record["correctness"]["status"] = "BOUND_VIOLATION"
    elif tamper == "artifact":
        task["execution"]["artifact_sha256"] = "0" * 64
    else:
        task["execution"]["cpu_affinity"] = [3]
    with pytest.raises(ValueError):
        verify_record(row, policy, "d", "a", "b" * 64)
