"""Run each frozen lane's auxiliary audits once after the serial queue ends.

Preserve every command, log and exit code, including missing-analysis failures.
This performs no performance rerun and does not repair or overwrite raw trials.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUNS = ROOT / "build/closure-formal-verification-20261011/formal-r3/runs"
PLAN = ROOT / "build/closure-formal-verification-20261011/formal-r3/preparation/release_plan.json"


def reference(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def main() -> None:
    if sys.flags.optimize:
        raise ValueError("do not disable qualification assertions")
    plan = json.loads(PLAN.read_text())
    queue = json.loads((RUNS / "queue_result.json").read_text())
    if [row["lane"] for row in queue["results"]] != [
        lane["run_set_id"] for lane in plan["lanes"]
    ] or not queue["input_snapshot_unchanged"]:
        raise ValueError("queue must have ended with the complete frozen attempt denominator")
    output = RUNS / "post_queue_auxiliary"
    output.mkdir(exist_ok=False)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        **{key: "1" for key in (
            "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"
        )},
    }
    rows = []
    for lane in plan["lanes"]:
        for name in ("audit_v32_buffer_costs", "audit_v32_uncompressed_reference"):
            command = [
                sys.executable, str(ROOT / "tools" / (name + ".py")),
                str(RUNS / lane["run_set_id"]), "--lane", lane["kind"],
            ]
            started = datetime.now(UTC).isoformat()
            log = output / (lane["run_set_id"] + "." + name + ".log")
            with log.open("xb") as handle:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=handle,
                                        stderr=subprocess.STDOUT, check=False)
            row = {
                "lane": lane["run_set_id"], "kind": lane["kind"], "audit": name,
                "command": command, "started_at": started,
                "ended_at": datetime.now(UTC).isoformat(),
                "exit_code": result.returncode, "log": reference(log),
            }
            rows.append(row)
            with (output / "attempts.jsonl").open("a") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            print(json.dumps({key: row[key] for key in ("lane", "audit", "exit_code")}),
                  flush=True)
    summary = {
        "schema_version": "tscb.post-queue-auxiliary-attempts.v1",
        "plan": reference(PLAN), "queue": reference(RUNS / "queue_result.json"),
        "driver": reference(Path(__file__)), "planned_commands": 32,
        "completed_commands": len(rows),
        "successful_commands": sum(row["exit_code"] == 0 for row in rows),
        "results": rows, "performance_remeasured": False, "automatic_retries": 0,
    }
    with (output / "summary.json").open("x") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    raise SystemExit(0 if all(row["exit_code"] == 0 for row in rows) else 1)


if __name__ == "__main__":
    main()
