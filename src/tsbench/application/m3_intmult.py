"""Execute frozen IntMult obligations as rows of the current M3 run."""
from collections import Counter
from pathlib import Path

from ..assets import ContractError, digest, require, verify_asset
from ..planner.m3_intmult import KEY
from ..planner.pcodec_intmult import execution_inputs
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import pcodec_intmult as native


def _refs(run, paths):
    return {p.relative_to(run).as_posix(): {"path": p.relative_to(run).as_posix(), "bytes": p.stat().st_size,
                                         "sha256": digest(p)} for p in sorted(paths)}


def _terminal(row, slot):
    return row["status"] == ("expected_rejection" if slot["expected_status"] else "verified")


def run_intmult(root: Path, run: Path, binding: dict, rows: list) -> dict:
    products, _ = execution_inputs(root)
    require({sid: slot for sid, (slot, _) in products.items()} == binding["slots"] and
            {r["obligation_id"] for r in rows} == binding["obligation_slots"].keys() and
            all((r["selection"], r["route"]) == KEY for r in rows), "IntMult execution inputs differ from frozen M3 binding")
    base = {"driver": binding["driver"], "recovery_id": binding["decoder"]["recovery_id"]}
    try:
        require(launcher_lock() == binding["launchers"], "IntMult isolation launchers changed after planning")
        staged = stage_recovery(root, run, binding["decoder"])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status="dependency_failed", reason=str(exc))
        return {**base, "fixtures": {}, "statuses": {}, "files": {}}
    (run / "logs").mkdir(exist_ok=True)
    (run / "products").mkdir(exist_ok=True)
    fixture_rows = {}
    for row in rows:
        ids = binding["obligation_slots"][row["obligation_id"]]
        failures = []
        for sid in ids:
            slot, sample = products[sid]
            result = native.run_slot(run, binding, slot, sample, lambda: False)
            fixture_rows[sid] = result
            if not _terminal(result, slot):
                failures.append(f"{slot['name']}: {result['status']} ({result['reason']})")
        row.update(status="failed" if failures else "verified", reason="; ".join(failures),
                   evidence={"driver": binding["driver"], "fixture_slots": ids})
    paths = [*staged, *(p for sid in fixture_rows for p in (run / "logs" / sid).iterdir()),
             *(run / p["path"] for fixture in fixture_rows.values() for p in fixture["parts"].values())]
    return {**base, "fixtures": fixture_rows, "statuses": dict(sorted(Counter(f["status"] for f in fixture_rows.values()).items())),
            "files": _refs(run, paths)}


def audit_intmult(run: Path, binding: dict, rows: list, evidence: dict, *, replay: bool = False) -> dict:
    """Verify all assets and results; optionally re-run code with only sealed mounts."""
    fixtures, files = evidence["fixtures"], evidence["files"]
    require(evidence["driver"] == binding["driver"] and evidence["recovery_id"] == binding["decoder"]["recovery_id"] and
            {r["obligation_id"] for r in rows} == binding["obligation_slots"].keys() and
            fixtures.keys() == binding["slots"].keys() and
            evidence["statuses"] == dict(Counter(f["status"] for f in fixtures.values())),
            "incomplete IntMult obligation evidence")
    expected_closure = {f"{DIRECTORY}/{rel}": {"path": f"{DIRECTORY}/{rel}", "sha256": spec["sha256"], "bytes": spec["bytes"]}
                        for rel, spec in binding["decoder"]["files"].items()}
    require({key: ref for key, ref in files.items() if key.startswith(f"{DIRECTORY}/")} == expected_closure,
            "IntMult retained decoder closure differs")
    allowed = set(expected_closure)
    for name, ref in files.items():
        require(ref["path"] == name and verify_asset(run, ref).stat().st_size == ref["bytes"], "IntMult retained asset differs")
    for row in rows:
        ids = binding["obligation_slots"][row["obligation_id"]]
        require(row["status"] == "verified" and not row["reason"] and
                row["evidence"] == {"driver": binding["driver"], "fixture_slots": ids}, "unverified IntMult obligation")
        for sid in ids:
            slot, result = binding["slots"][sid], fixtures[sid]
            require(result["product_slot"] == sid and _terminal(result, slot) and
                    native.inspect_evidence(run, binding, slot, result, files, allowed), "IntMult fixture did not verify")
    require(files.keys() == allowed, "IntMult has undeclared retained files")
    replayed = []
    if replay:
        require(launcher_lock() == binding["launchers"], "IntMult replay launchers differ from plan")
        replayed = [native.audit_slot(run, binding, binding["slots"][sid], result) for sid, result in fixtures.items()]
    return {"verified_obligations": len(rows), "fixture_statuses": evidence["statuses"], "replayed": replayed}
