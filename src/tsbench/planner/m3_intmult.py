"""Bind the existing integer fixture definitions, not prior IntMult results."""
from pathlib import Path

from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import pcodec_intmult

KEY = (11, "intmult")
DRIVER = "pcodec-intmult-specialized/1"
LIMITS = {"address_space_bytes": 256 << 20, "file_bytes": pcodec_intmult.FILE_LIMIT, "wall_seconds": 15}
CODE = (*pcodec_intmult.SOURCES, "src/tsbench/planner/m3_intmult.py", "src/tsbench/application/m3_intmult.py",
        "src/tsbench/recovery.py", "src/tsbench/supervisor/isolated_worker.py", "src/tsbench/supervisor/process.py")


def bind_intmult(root: Path, obligations: list, pages: dict) -> dict:
    products, cases = pcodec_intmult.execution_inputs(root)
    targets = [o for o in obligations if (o["selection"], o["route"]) == KEY]
    require(len(targets) == len(cases) == 4 and all(o["kind"] == "required" for o in targets),
            "M3 pcodec IntMult obligation scope differs")
    members = {}
    for row in targets:
        require(len(row["planned_case_inputs"]) == 1, "IntMult must bind exactly one planned case per obligation")
        case = row["planned_case_inputs"][0]
        result = cases.get(case["case_id"])
        require(case["bundle_key"] == "pcodec_cases" and result is not None and result[0] == case["bundle_id"],
                "M3 pcodec IntMult fixture identity differs from M0")
        members[row["obligation_id"]] = list(result[1])
    flat = [sid for ids in members.values() for sid in ids]
    require(len(flat) == len(products) == 6 and set(flat) == products.keys(), "M3 pcodec IntMult fixture coverage differs")
    validate_limits(LIMITS)
    tools = {pcodec_intmult.TOOL: {k: pages["executable"][k] for k in ("path", "sha256")}}
    decoder = plan_recovery(root, {}, (), tools=tools, libraries=[pages["dependency"]])
    return {"driver": DRIVER, "limits": dict(LIMITS), "launchers": launcher_lock(), "decoder": decoder,
            "code": {p: digest(local_file(root, p)) for p in CODE}, "obligation_slots": members,
            "slots": {sid: slot for sid, (slot, _) in products.items()}}
