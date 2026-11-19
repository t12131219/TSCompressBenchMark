"""End-to-end CLI/API smoke and terminal-state evidence on one frozen schedule."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import SmokePlanRequest, plan_smoke, report_smoke, run_smoke
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json
from tsbench.planner.measurement import POLICY as MEASUREMENT_POLICY, PROFILE, SNAPSHOT as MEASUREMENT_SNAPSHOT, TIMED_SUITE
from tsbench.planner.smoke_comparison import SNAPSHOT as COMPARISON_SNAPSHOT
from tsbench.recovery import DIRECTORY as RECOVERY_DIR, MANIFEST as RECOVERY_MANIFEST
from tsbench.runtime import create_build_lock
from tsbench.supervisor.resource import SNAPSHOT as RESOURCE_SNAPSHOT
from tsbench.supervisor.process import invoke as child_invoke


def stage(root, worker, *artifacts):
    for name in ("catalog", "schemas", "plugins", "include", "cmake", "tools", "third_party", "configs", "datasets"):
        shutil.copytree(ROOT / name, root / name,
                        ignore=shutil.ignore_patterns("unique") if name == "datasets" else None)
    for artifact in (worker, *artifacts):
        shutil.copy2(artifact, root / Path(artifact).name)
    return {"raw-store": Path(artifacts[0]).name, "zstd": Path(artifacts[1]).name, "alp-auto": Path(artifacts[3]).name}


def plan(root, worker, libraries, lock):
    write_new(root / lock, create_build_lock(root, worker, libraries))
    return plan_smoke(root, SmokePlanRequest(lock))


def cli(root, *args, code=0):
    result = subprocess.run([sys.executable, "-I", "-B", ROOT / "bmk", "--root", root, *args],
                            capture_output=True, timeout=15)
    assert result.returncode == code, result
    return json.loads(result.stdout if code != 2 else result.stderr)


def assert_full(root, result, status, count=6):
    assert result["statuses"] == {status: count} and result["planned_slots"] == count
    assert result["complete"] and not result["qualification_granted"]
    run = root / "results" / result["run_id"]
    assert (run / "completion.json").is_file()
    rows = [json.loads(line) for line in (run / "observations.jsonl").read_text().splitlines()]
    assert [row["slot_id"] for row in rows] == [row["slot_id"] for row in result["cases"]]
    return run, rows


def rewrite_evidence(run, name, data):
    """Reseal a modified file to exercise semantic checks beyond hash checks."""
    path = run / name
    path.write_bytes(data)
    completion = run / "completion.json"
    seal = load_json(completion)
    seal.pop("seal_id")
    ref = next(ref for ref in seal["files"] if ref["path"] == name)
    ref.update(bytes=len(data), sha256=digest(path))
    completion.write_bytes(canonical_bytes({**seal, "seal_id": content_id(seal)}) + b"\n")


def successful(root, worker, artifacts):
    libs = stage(root, worker, *artifacts)
    name = Path(worker).name
    cli(root, "lock-build", "--worker", name,
        *(token for key, value in libs.items() for token in ("--plugin", f"{key}={value}")), "--out", root / "build.json")
    api_plan = plan_smoke(root, SmokePlanRequest("build.json"))
    cli(root, "smoke-plan", "--build-lock", "build.json", "--out", root / "plan.json")
    assert load_json(root / "plan.json") == api_plan
    live_schema = root / "schemas/observation.schema.json"
    original_schema = live_schema.read_bytes()
    live_schema.write_text(json.dumps({**load_json(live_schema), "$comment": "new contract"}))
    revised_plan = plan_smoke(root, SmokePlanRequest("build.json"))
    assert revised_plan["observation_schema_id"] != api_plan["observation_schema_id"]
    assert revised_plan["plan_content_id"] != api_plan["plan_content_id"]
    assert "observation schema differs" in cli(root, "smoke-run", "--plan", "plan.json", code=2)["reason"]
    assert not (root / "results").exists()
    live_schema.write_bytes(original_schema)
    result = cli(root, "smoke-run", "--plan", "plan.json")
    run, rows = assert_full(root, result, "verified")
    sessions = [op["session_id"] for row in rows for op in row["operations"]]
    assert len(sessions) == len(set(sessions)) == 12
    assert all(op["pid"] and op["returncode"] == 0 for row in rows for op in row["operations"])
    candidate_id = TIMED_SUITE
    cli(root, "smoke-plan", "--suite", candidate_id, "--build-lock", "build.json", "--out", root / "candidate-plan.json")
    candidate = plan_smoke(root, SmokePlanRequest("build.json", candidate_id))
    assert load_json(root / "candidate-plan.json") == candidate
    assert len(candidate["slots"]) == 18 and candidate["estimates"]["max_worker_operations"] == 36
    assert candidate["estimates"]["max_planned_case_logical_input_bytes"] == 65536
    assert len({item["window"]["source_cluster"] for item in candidate["inputs"].values() if item["kind"] == "corpus_window"}) == 2
    stage_suite = root / "configs/suites" / candidate_id / "suite.json"
    original = stage_suite.read_bytes()
    invalid = load_json(stage_suite)
    invalid["scheduling"]["max_attempts"] = 2
    stage_suite.write_text(json.dumps(invalid))
    refusal = cli(root, "smoke-plan", "--suite", candidate_id, "--build-lock", "build.json", code=2)
    assert "violates lossless-stage-suite schema" in refusal["reason"], refusal
    stage_suite.write_bytes(original)
    control = root / candidate["suite"]["direct_control"]
    original = control.read_bytes()
    control.write_text(json.dumps({**load_json(control), "state": "changed since planning"}))
    refusal = cli(root, "smoke-run", "--plan", "candidate-plan.json", code=2)
    assert "stage contract bindings differ" in refusal["reason"], refusal
    control.write_bytes(original)
    measurement = root / MEASUREMENT_POLICY
    original_measurement = measurement.read_bytes()
    invalid_mode = load_json(measurement)
    invalid_mode["profiles"][PROFILE]["rankable"] = True
    measurement.write_text(json.dumps(invalid_mode))
    refusal = cli(root, "smoke-run", "--plan", "candidate-plan.json", code=2)
    assert "violates measurement-policy schema" in refusal["reason"], refusal
    measurement.write_bytes(original_measurement)
    stage_result = cli(root, "smoke-run", "--plan", "candidate-plan.json")
    stage_run, stage_rows = assert_full(root, stage_result, "verified", 18)
    assert stage_result["evidence_scope"] == "m1_candidate_preflight" and stage_result["measurement"] == PROFILE
    assert stage_result["extent"] == candidate["contract_bindings"]["measurement"]["policy"]["profiles"][PROFILE]
    assert not stage_result["extent"]["rankable"]
    groups = {}
    resource_summary = stage_result['resource_diagnostics']
    assert resource_summary['child_operations_observed']==36 and resource_summary['hard_isolation'] is False
    assert resource_summary['verified_workspace_released_files']==36 and resource_summary['failed_workspace_retained_files']==0
    assert resource_summary['run_elapsed_ns']>0 and resource_summary['child_maxrss_max_bytes']>0
    assert (stage_run / RESOURCE_SNAPSHOT).is_file() and not list(stage_run.glob('.case-*'))
    assert len(list((stage_run/'artifacts').iterdir()))==18
    recovery = candidate['contract_bindings']['recovery']
    bundled = stage_result['recovery']
    assert bundled['status']=='ready' and bundled['files']==len(recovery['files'])==11
    assert bundled['bytes']==candidate['estimates']['recovery_bundle_logical_bytes']
    first, second = stage_result['cases'][:2]
    assert first['resources']['guard']['minimum']['available_bytes'] - second['resources']['guard']['minimum']['available_bytes']==bundled['bytes']
    assert first['resources']['guard']['minimum']['available_inodes'] - second['resources']['guard']['minimum']['available_inodes']==bundled['files']+3
    assert bundled['sample_slots']==sorted(r['slot_id'] for r in stage_rows)
    by_input = stage_result['comparison_contracts']['by_input']
    assert stage_result['comparison_contracts'] == candidate['contract_bindings']['comparison']
    assert len({b['comparison_id'] for by_direction in by_input.values() for b in by_direction.values()}) == 12
    for item, observation in zip(stage_result["cases"], stage_rows, strict=True):
        groups.setdefault(item["comparison_id"], set()).add(item["method_id"])
        assert item["process_wall_ns"] == {o["operation"]: o["process_wall_ns"] for o in observation["operations"]}
        assert all(type(n) is int and n > 0 for n in item["process_wall_ns"].values())
        assert item["execution"] == observation["execution"]
        assert item['resources']['child_usage']=={o['operation']:o['child_usage'] for o in observation['operations']}
        assert item['resources']['guard']['sample']['disk']['device']==stage_run.stat().st_dev
        assert item['workspace']['action']=='verified_released'
        assert [f['name'] for f in item['workspace']['files']]==['restored.bin','restored.json']
        assert item['frozen_comparison_ids'] == {d:b['comparison_id'] for d,b in by_input[item['input_id']].items()}
        assert item['primary_comparison']['admitted'] is False
        assert 'formal_resource_budget_not_verified' in item['primary_comparison']['reasons']
    assert len(groups) == 6 and all(group == {"raw-store", "zstd", "alp-auto"} for group in groups.values())
    measured_rows = stage_run / "observations.jsonl"
    original_rows_v2 = measured_rows.read_bytes()
    measured_seal = (stage_run / "completion.json").read_bytes()
    del stage_rows[0]["operations"][0]["process_wall_ns"]
    rewrite_evidence(stage_run, measured_rows.name, b"".join(canonical_bytes(row) + b"\n" for row in stage_rows))
    assert "must match the frozen extent" in cli(root, "smoke-report", stage_result["run_id"], code=2)["reason"]
    measured_rows.write_bytes(original_rows_v2)
    (stage_run / "completion.json").write_bytes(measured_seal)
    assert (stage_run / MEASUREMENT_SNAPSHOT).is_file()
    snapshot = (stage_run / COMPARISON_SNAPSHOT).read_bytes()
    rewrite_evidence(stage_run, COMPARISON_SNAPSHOT, snapshot.replace(b'Frozen workload', b'Modified workload'))
    assert 'frozen comparison contracts differ' in cli(root, 'smoke-report', stage_result['run_id'], code=2)['reason']
    (stage_run / COMPARISON_SNAPSHOT).write_bytes(snapshot)
    (stage_run / 'completion.json').write_bytes(measured_seal)
    # A hash-valid seal without its complete closure is still not usable.
    recovery_file = f'{RECOVERY_DIR}/lib/libalp_native.so'
    gone = stage_run/recovery_file
    moved = stage_run/'removed-dso'
    gone.rename(moved)
    try:
        assert 'unavailable local asset' in cli(root,'smoke-restore-audit',stage_result['run_id'],code=2)['reason']
        incomplete = load_json(stage_run/'completion.json')
        incomplete.pop('seal_id')
        incomplete['files'] = [ref for ref in incomplete['files'] if ref['path']!=recovery_file]
        (stage_run/'completion.json').write_bytes(canonical_bytes({**incomplete,'seal_id':content_id(incomplete)}))
        assert 'package is incomplete' in cli(root,'smoke-restore-audit',stage_result['run_id'],code=2)['reason']
    finally:
        moved.rename(gone)
        (stage_run/'completion.json').write_bytes(measured_seal)
    gone.chmod(0o600)
    original_dso = gone.read_bytes()
    rewrite_evidence(stage_run,recovery_file,(stage_run/RECOVERY_DIR/'lib/liblzbench_native.so').read_bytes())
    assert 'package is incomplete' in cli(root,'smoke-restore-audit',stage_result['run_id'],code=2)['reason']
    gone.write_bytes(original_dso)
    gone.chmod(0o400)
    (stage_run/'completion.json').write_bytes(measured_seal)
    manifest_copy = (stage_run/RECOVERY_MANIFEST).read_bytes()
    wrong = load_json(stage_run/RECOVERY_MANIFEST)
    wrong['sample_slots'].pop()
    rewrite_evidence(stage_run,RECOVERY_MANIFEST,canonical_bytes(wrong))
    assert 'differs from run slots' in cli(root,'smoke-restore-audit',stage_result['run_id'],code=2)['reason']
    (stage_run/RECOVERY_MANIFEST).write_bytes(manifest_copy)
    (stage_run/'completion.json').write_bytes(measured_seal)
    vals = (stage_run/'validations.jsonl').read_bytes()
    bad = json.loads(vals.splitlines()[0])
    bad['decoded']['schema_sha256'] = '0' * 64
    rewrite_evidence(stage_run, 'validations.jsonl', canonical_bytes(bad)+b'\n'+vals.split(b'\n',1)[1])
    assert 'matching validator evidence' in cli(root,'smoke-restore-audit',stage_result['run_id'],code=2)['reason']
    (stage_run/'validations.jsonl').write_bytes(vals)
    (stage_run/'completion.json').write_bytes(measured_seal)
    # A partial copy failure cannot publish any closure or discard verified outputs.
    copy = shutil.copyfileobj
    def fail_copy(inp, out, *args, **kwargs):
        if '.stage-recovery-' in out.name and out.name.endswith('/lib/libc.so.6'):
            out.write(b'truncated')
            raise OSError('injected recovery copy failure')
        return copy(inp,out,*args,**kwargs)
    with patch('tsbench.recovery.shutil.copyfileobj',side_effect=fail_copy):
        fallback = run_smoke(root,candidate)
    fallback_run, _ = assert_full(root,fallback,'verified',18)
    assert fallback['recovery']['status']=='unavailable' and 'copy failure' in fallback['recovery']['reason']
    assert not (fallback_run/RECOVERY_DIR).exists() and not list(fallback_run.glob('.stage-recovery-*'))
    assert fallback['resource_diagnostics']['verified_workspace_released_files']==0
    assert len(list((fallback_run/'retained').glob('*/*')))==36
    assert all(c['workspace']['action']=='verified_retained' for c in fallback['cases'])
    assert 'no complete sealed decoder closure' in cli(root,'smoke-restore-audit',fallback['run_id'],code=2)['reason']
    # A missing worker after planning becomes slot failures, not an invalid plan or a fallback executable.
    worker_path, hidden = root/name, root/'hidden-worker'
    worker_path.rename(hidden)
    try:
        missing = run_smoke(root,candidate)
        assert_full(root,missing,'dependency_failed',18)
        assert missing['recovery']['status']=='no_verified_samples'
    finally:
        hidden.rename(worker_path)
    # Admission failure creates all planned terminal rows, and no worker calls.
    low_inode = {'disk':{'device':stage_run.stat().st_dev,'available_bytes':10**9,'available_inodes':0},
                 'host_memavailable_bytes':10**9}
    with patch('tsbench.application.smoke.sample',return_value=low_inode),          patch('tsbench.application.smoke.invoke',side_effect=AssertionError('blocked work launched')):
        blocked = run_smoke(root,candidate)
    _, blocked_rows = assert_full(root,blocked,'resource_blocked',18)
    assert all(row['resource_guard']['reasons']==['results_mount_free_inodes_below_floor'] and not row['operations']
               for row in blocked_rows)
    assert blocked['resource_diagnostics']['child_maxrss_max_bytes'] is None
    assert blocked['recovery']['status']=='no_verified_samples'
    # A real nonzero child termination keeps the staged inputs as failed-workspace evidence.
    stop = Event()
    def fail_once(argv,tmp,logs,operation,deadline,cancelled,**kwargs):
        row = child_invoke([sys.executable,'-B','-c','raise SystemExit(7)'],tmp,logs,operation,deadline,cancelled,**kwargs)
        stop.set()
        return row
    with patch('tsbench.application.smoke.invoke',side_effect=fail_once):
        failed = run_smoke(root,candidate,cancelled=stop.is_set)
    assert failed['statuses']=={'cancelled':17,'failed':1}
    failed_slot = failed['cases'][0]
    assert failed_slot['workspace']['action']=='failure_retained'
    failed_ws = root/'results'/failed['run_id']/'failures'/failed_slot['slot_id']
    assert sorted(p.name for p in failed_ws.iterdir())==['original.bin','original.json']
    assert failed['resource_diagnostics']['failed_workspace_retained_files']==2
    stage_sessions = [op["session_id"] for row in stage_rows for op in row["operations"]]
    assert len(stage_sessions) == len(set(stage_sessions)) == 36
    (root / "datasets").rename(root / "unavailable-inputs")
    (root / name).rename(root / "unavailable-worker")
    live_schema.unlink()
    (root / "schemas/lossless-stage-suite.schema.json").unlink()
    (root / "schemas/measurement-policy.schema.json").unlink()
    (root / "schemas" / COMPARISON_SNAPSHOT).unlink()
    (root / "schemas" / RESOURCE_SNAPSHOT).unlink()
    measurement.unlink()
    (run / "derived/report.json").unlink()
    assert cli(root, "smoke-report", result["run_id"]) == result
    assert report_smoke(root, result["run_id"]) == result
    (stage_run / "derived/report.json").unlink()
    assert cli(root, "smoke-report", stage_result["run_id"]) == stage_result
    if out := os.environ.get("TSBENCH_SMOKE_EVIDENCE_DIR"):
        exported = Path(out) / "results" / run.name
        shutil.copytree(run, exported)
        assert report_smoke(Path(out), result["run_id"]) == result
        write_new(Path(out) / "verified.json", result)
        shutil.copytree(stage_run, Path(out) / "results" / stage_run.name)
        assert report_smoke(Path(out), stage_result["run_id"]) == stage_result
        write_new(Path(out) / "m1-candidate-verified.json", stage_result)
    completion = run / "completion.json"
    seal = completion.read_bytes()
    completion.unlink()
    assert "run is unsealed" in cli(root, "smoke-report", result["run_id"], code=2)["reason"]
    completion.write_bytes(seal)
    evidence = run / "observations.jsonl"
    original_rows = evidence.read_bytes()
    rows[0]["qualification_granted"] = True
    rewrite_evidence(run, evidence.name, b"".join(canonical_bytes(row) + b"\n" for row in rows))
    assert "violates observation schema" in cli(root, "smoke-report", result["run_id"], code=2)["reason"]
    evidence.write_bytes(original_rows)
    completion.write_bytes(seal)
    ledger = run / "accounting.jsonl"
    original_ledger = ledger.read_bytes()
    rewrite_evidence(run, ledger.name, original_ledger + original_ledger.splitlines(keepends=True)[0])
    assert "duplicate slots in accounting.jsonl" in cli(root, "smoke-report", result["run_id"], code=2)["reason"]
    ledger.write_bytes(original_ledger)
    completion.write_bytes(seal)
    artifact = run / rows[0]["artifact"]["path"]
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    rejection = cli(root, "smoke-report", result["run_id"], code=2)
    assert "SHA-256 mismatch" in rejection["reason"], rejection


def failures(root, worker, artifacts):
    libs = stage(root, worker, *artifacts)
    name = Path(worker).name
    original = plan(root, name, libs, "original.json")
    (root / name).rename(root / "unavailable-worker")
    assert_full(root, run_smoke(root, original), "dependency_failed")
    suite = root / "configs/suites/dev_lossless_smoke_v1/suite.json"
    cfg = load_json(suite)
    cfg["timeout_seconds_per_operation"] = 1
    suite.write_text(json.dumps(cfg), encoding="utf-8")
    bodies = {
        "failed": "raise SystemExit(9)",
        "crash": "import os,signal; os.kill(os.getpid(),signal.SIGKILL)",
        "validation_failed": "import pathlib,sys; pathlib.Path(sys.argv[-1]).write_bytes(b'fake')",
        "timeout": "import time; time.sleep(30)",
    }
    for status, body in bodies.items():
        script = root / status
        script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
        script.chmod(0o700)
        frozen = plan(root, status, libs, f"{status}.json")
        assert_full(root, run_smoke(root, frozen), status)
    cfg["timeout_seconds_per_operation"] = 10
    suite.write_text(json.dumps(cfg), encoding="utf-8")
    script = root / "waiting"
    script.write_text(f"#!{sys.executable}\nimport pathlib,time\npathlib.Path({str(root/'child-ready')!r}).touch()\ntime.sleep(30)\n")
    script.chmod(0o700)
    frozen = plan(root, "waiting", libs, "waiting.json")
    cancel = Event()
    def when_ready():
        for _ in range(500):
            if (root / "child-ready").exists():
                cancel.set()
                return
            time.sleep(.01)
        cancel.set()
    watcher = Thread(target=when_ready, daemon=True)
    watcher.start()
    _, rows = assert_full(root, run_smoke(root, frozen, cancelled=cancel.is_set), "cancelled")
    watcher.join()
    assert rows[0]["operations"][0]["pid"] is not None
    assert rows[0]["operations"][0]["returncode"] < 0 and not rows[1]["operations"]


def main():
    worker, *artifacts = sys.argv[1:]
    for check in (successful, failures):
        with tempfile.TemporaryDirectory(prefix="tsbench-smoke-exec-") as folder:
            check(Path(folder), worker, artifacts)
    print("complete CLI/API execution and recompute; sealed missing dependency, failure, crash, invalid output, timeout and cancellation")


if __name__ == "__main__":
    main()
