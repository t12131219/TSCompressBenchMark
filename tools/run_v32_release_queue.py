"""Run a frozen list of existing V3.2 lanes serially and retain every attempt log.

Each lane applies its own qualification, development pilot, host lease, formal
budget and no-op resume verification. This queue never overrides those gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.comparison.runner import control_plane_snapshot  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def input_snapshot(lanes: list[dict]) -> list[dict]:
    paths = set((ROOT / "registry").rglob("*.json"))
    for lane in lanes:
        for field in ("bundle", "protocol"):
            if field in lane:
                path = (ROOT / lane[field]).resolve()
                if not path.is_relative_to(ROOT):
                    raise ValueError("release input escapes project")
                paths.add(path)
    return [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(paths)
    ]


def command(lane: dict, output_root: Path) -> list[str]:
    kind, name = lane["kind"], lane["run_set_id"]
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("lane requires a simple run_set_id")
    resume = (output_root / name).exists()
    if kind == "pipeline":
        return [
            sys.executable,
            str(ROOT / "tools/run_v32_pipeline_comparison.py"),
            "all",
            "--output",
            str(output_root / name),
            "--cpu",
            str(lane["cpu"]),
            "--verify-resume",
            *(["--resume"] if resume else []),
        ]
    if kind not in {"comparison", "workload"}:
        raise ValueError("unsupported release queue lane")
    result = [
        sys.executable,
        str(ROOT / f"tools/run_v32_existing_{kind}.py"),
        str(ROOT / lane["bundle"]),
        "--output-root",
        str(output_root),
        "--run-set-id",
        name,
    ]
    if kind == "workload":
        result += ["--protocol", str(ROOT / lane["protocol"])]
    return result + (["--resume"] if resume else [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    lanes = plan["lanes"]
    if not lanes or len({r["run_set_id"] for r in lanes}) != len(lanes):
        raise ValueError("release queue requires unique fixed lanes")
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    frozen = {
        "schema_version": "tscb.release-queue.v1",
        "lanes": lanes,
        "control_plane": control_plane_snapshot(ROOT),
        "input_snapshot": input_snapshot(lanes),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "lane_driver_sha256": {
            name: hashlib.sha256((ROOT / "tools" / name).read_bytes()).hexdigest()
            for name in (
                "run_v32_existing_comparison.py",
                "run_v32_existing_workload.py",
                "run_v32_pipeline_comparison.py",
            )
        },
    }
    payload = canonical_json_bytes(frozen) + b"\n"
    queue = output / "release_queue.json"
    if queue.exists():
        if queue.read_bytes() != payload:
            raise ValueError("frozen queue or source changed; retain evidence and use a new queue")
    else:
        with queue.open("xb") as handle:
            handle.write(payload)
    environment = dict(os.environ)
    environment.update(
        PYTHONPATH=str(ROOT / "src"),
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    logs = output / "queue_logs"
    logs.mkdir(exist_ok=True)
    for lane in lanes:
        if (
            control_plane_snapshot(ROOT) != frozen["control_plane"]
            or input_snapshot(lanes) != frozen["input_snapshot"]
        ):
            raise ValueError("source, registry or frozen configuration changed during the queue")
        invocation = command(lane, output)
        name = lane["run_set_id"]
        attempt = len(list(logs.glob(name + ".attempt-*.log"))) + 1
        log = logs / f"{name}.attempt-{attempt}.log"
        print(json.dumps({"lane": name, "stage": "START", "log": str(log)}), flush=True)
        with log.open("xb") as handle:
            result = subprocess.run(
                invocation, cwd=ROOT, env=environment, stdout=handle, stderr=subprocess.STDOUT
            )
        record = {
            "lane": name,
            "attempt": attempt,
            "command": invocation,
            "exit_code": result.returncode,
            "log": str(log.relative_to(output)),
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        }
        with (output / "queue_attempts.jsonl").open("ab") as handle:
            handle.write(canonical_json_bytes(record) + b"\n")
        print(json.dumps(record), flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
    if (
        control_plane_snapshot(ROOT) != frozen["control_plane"]
        or input_snapshot(lanes) != frozen["input_snapshot"]
    ):
        raise ValueError("source, registry or configuration changed before queue completion")
    print(json.dumps({"status": "QUEUE_COMPLETE", "lane_count": len(lanes)}), flush=True)


if __name__ == "__main__":
    main()
