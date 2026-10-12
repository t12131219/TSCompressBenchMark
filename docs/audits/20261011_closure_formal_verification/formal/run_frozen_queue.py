"""Run the fixed current-closure lanes serially with complete project input hashes.

The existing lane drivers retain all qualification, pilot, resource, direction
signal, formal budget and no-op resume gates. A failing lane does not receive
formal eligibility; independent remaining lanes are still attempted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from rebind_v32_comparison_sources import semantic_projection  # noqa: E402
from run_v32_release_queue import command  # noqa: E402

from tscompbench.codecs import SourceRegistry  # noqa: E402
from tscompbench.comparison.runner import control_plane_snapshot  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def ref(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def preparation_inputs(plan_path: Path, lanes: list[dict]) -> set[Path]:
    """Verify SHA references and decision equality before trusting preparation."""
    plan = json.loads(plan_path.read_text())
    required = {
        **dict.fromkeys(
            (
                "byte",
                "f64",
                "i16",
                "abs",
                "f32",
                "quality",
                "model",
                "cold",
                "api",
                "entropy",
                "u8",
                "timestamp",
            ),
            "comparison",
        ),
        **dict.fromkeys(("stream", "query-warm", "query-fresh"), "workload"),
        "pipeline": "pipeline",
    }
    if len(lanes) != 16 or {lane["run_set_id"]: lane["kind"] for lane in lanes} != required:
        raise ValueError("fixed performance lane denominator or kind changed")
    paths = set()

    def references(value):
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                path = (ROOT / value["path"]).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file():
                    raise ValueError("preparation reference escapes or is missing")
                actual = ref(path)
                if actual["sha256"] != value["sha256"] or (
                    "bytes" in value and actual["bytes"] != value["bytes"]
                ):
                    raise ValueError("preparation reference changed: " + value["path"])
                paths.add(path)
            for item in value.values():
                references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)

    references(plan)
    receipts = {item["lane"]: item for item in plan["receipts"]}
    expected = {lane["run_set_id"] for lane in lanes if "bundle" in lane}
    if set(receipts) != expected or len(receipts) != len(plan["receipts"]):
        raise ValueError("preparation receipt denominator differs")
    for lane in lanes:
        if "bundle" not in lane:
            continue
        receipt = receipts[lane["run_set_id"]]
        if receipt["bundle"]["path"] != lane["bundle"]:
            raise ValueError("lane bundle differs from its preparation receipt")
        proof = json.loads((ROOT / receipt["proof"]["path"]).read_text())
        references(proof)
        old = json.loads((ROOT / receipt["base"]["path"]).read_text())
        new = json.loads((ROOT / lane["bundle"]).read_text())
        if semantic_projection(old) != semantic_projection(new):
            raise ValueError("non-source lane decisions changed")
        old_methods = [m["implementation"]["method_id"] for m in old["group"]["members"]]
        new_methods = [m["implementation"]["method_id"] for m in new["group"]["members"]]
        if old_methods != new_methods:
            raise ValueError("MethodID decisions changed")
        if "protocol" in lane:
            original = ROOT / lane["historical_protocol"]["path"]
            protocol = (ROOT / lane["protocol"]).resolve()
            if not protocol.is_relative_to(ROOT):
                raise ValueError("lane protocol escapes project")
            if protocol.read_bytes() != original.read_bytes():
                raise ValueError("workload protocol decisions changed")
    return paths


def registered_inputs() -> set[Path]:
    """Pin registered native artifacts, source/model/corpus and runtime references."""
    paths, checked = {Path(sys.executable).resolve()}, {}

    def references(value):
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                path = (ROOT / value["path"]).resolve()
                if not Path(value["path"]).is_absolute() and not path.is_relative_to(ROOT):
                    raise ValueError("relative registered input escapes project")
                if path not in checked:
                    checked[path] = ref(path)
                actual = checked[path]
                if actual["sha256"] != value["sha256"] or (
                    "bytes" in value and actual["bytes"] != value["bytes"]
                ):
                    raise ValueError("registered input changed: " + value["path"])
                paths.add(path)
            for item in value.values():
                references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)

    active = json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
    sources = SourceRegistry(ROOT / "registry/sources")
    for key in active:
        codec = json.loads((ROOT / "registry/codecs" / (key + ".json")).read_text())
        references(codec)
        references(sources.get(codec["identity"]["source_artifact_id"]))
        adapter = codec["adapter"]
        if "artifact_path" in adapter:
            artifact = (ROOT / adapter["artifact_path"]).resolve()
            if not artifact.is_relative_to(ROOT):
                raise ValueError("native artifact escapes project")
            paths.add(artifact)
        if "runtime_profile" in adapter:
            profile = ROOT / adapter["runtime_profile"]["path"]
            references(json.loads(profile.read_text()))
    for path in (ROOT / "registry/comparison_datasets/v32_20261010").glob("*.json"):
        references(json.loads(path.read_text()))
    for key in ("etth1", "weather"):
        references(json.loads((ROOT / "registry/datasets" / (key + ".json")).read_text()))
    return paths


def manifest(plan: Path, lanes: list[dict]) -> list[dict]:
    drivers = {
        Path(__file__).with_name(name)
        for name in ("prepare_current_queue.py", "run_frozen_queue.py", "audit_current_formal.py")
    }
    paths = {
        ROOT / "pyproject.toml",
        plan,
        *drivers,
        *preparation_inputs(plan, lanes),
        *registered_inputs(),
    }
    for directory in ("src", "tools", "tests", "configs", "registry", "schemas", "adapters"):
        paths.update(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file()
            and not {"__pycache__", ".pytest_cache", ".ruff_cache"}.intersection(path.parts)
            and path.suffix not in {".pyc", ".pyo"}
        )
    for lane in lanes:
        for key in ("bundle", "protocol"):
            if key in lane:
                paths.add((ROOT / lane[key]).resolve())
    return [ref(path) for path in sorted(paths)]


def save(path: Path, document: dict) -> None:
    with path.open("xb") as handle:
        handle.write(canonical_json_bytes(document) + b"\n")


def main() -> None:
    if sys.flags.optimize:
        raise ValueError("optimized Python cannot run qualification validators")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan_path, output = args.plan.resolve(), args.output.resolve()
    if not plan_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        parser.error("keep all inputs and evidence inside the project")
    if output.exists():
        parser.error("choose a new queue output; preserve previous attempts")
    plan = json.loads(plan_path.read_text())
    lanes = plan["lanes"]
    if len(lanes) != 16 or len({lane["run_set_id"] for lane in lanes}) != 16:
        raise ValueError("the fixed current-existing-scope queue requires 16 unique lanes")
    before = manifest(plan_path, lanes)
    control = control_plane_snapshot(ROOT)
    output.mkdir(parents=True)
    logs = output / "queue_logs"
    logs.mkdir()
    save(
        output / "input_snapshot.json",
        {
            "schema_version": "tscb.current-closure-queue-inputs.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "files": before,
            "control_plane": control,
            "lanes": lanes,
            "scope": (
                "NONCACHE_PROJECT_CODE_ADAPTERS_PLUS_DRIVERS_PREPARATION_AND_REGISTERED_ASSETS_RUNTIME"
            ),
        },
    )
    environment = dict(os.environ)
    environment.update(
        PYTHONPATH=str(ROOT / "src"),
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    results = []
    for lane in lanes:
        if manifest(plan_path, lanes) != before or control_plane_snapshot(ROOT) != control:
            raise ValueError("project inputs changed; do not run any later lane")
        invocation = command(lane, output)
        name = lane["run_set_id"]
        log = logs / (name + ".attempt-1.log")
        print(json.dumps({"lane": name, "stage": "START", "command": invocation}), flush=True)
        started = datetime.now(UTC).isoformat()
        with log.open("xb") as handle:
            result = subprocess.run(
                invocation, cwd=ROOT, env=environment, stdout=handle, stderr=subprocess.STDOUT
            )
        stable = manifest(plan_path, lanes) == before and control_plane_snapshot(ROOT) == control
        record = {
            "lane": name,
            "kind": lane["kind"],
            "command": invocation,
            "started_at": started,
            "ended_at": datetime.now(UTC).isoformat(),
            "exit_code": result.returncode,
            "input_snapshot_unchanged": stable,
            "log": ref(log),
        }
        results.append(record)
        with (output / "queue_attempts.jsonl").open("ab") as handle:
            handle.write(canonical_json_bytes(record) + b"\n")
        print(json.dumps(record), flush=True)
        if not stable:
            raise ValueError("inputs changed during this lane; retain results and stop")
    stable = manifest(plan_path, lanes) == before and control_plane_snapshot(ROOT) == control
    passed = sum(item["exit_code"] == 0 for item in results)
    document = {
        "schema_version": "tscb.current-closure-queue-result.v1",
        "status": "QUEUE_DRIVERS_COMPLETED"
        if stable and passed == len(lanes)
        else "QUEUE_COMPLETED_WITH_GAPS",
        "lane_count": len(lanes),
        "successful_lane_driver_count": passed,
        "input_snapshot_unchanged": stable,
        "results": results,
        "claim_boundary": (
            "Lane driver completion requires independent raw, identity and report audit; "
            "no all-source parity or N/G/CAP acceptance is inferred."
        ),
    }
    save(output / "queue_result.json", document)
    print(
        json.dumps(
            {
                k: document[k]
                for k in (
                    "status",
                    "lane_count",
                    "successful_lane_driver_count",
                    "input_snapshot_unchanged",
                )
            }
        ),
        flush=True,
    )
    raise SystemExit(0 if document["status"] == "QUEUE_DRIVERS_COMPLETED" else 1)


if __name__ == "__main__":
    main()
