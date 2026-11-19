"""Run and recompute one complete development lossless schedule."""
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import time
import tempfile
import uuid

from ..assets import ContractError, canonical_bytes, content_id, digest, load_json, local_file, require, verify_asset
from ..contracts import Contract, compile_contract, load_contract
from ..planner import smoke_isolation as isolation
from ..planner.measurement import PROFILE, SNAPSHOT as MEASUREMENT_SNAPSHOT, comparison_identity, timed
from ..planner.smoke_comparison import SNAPSHOT as COMPARISON_SNAPSHOT, verify_stage_comparisons
from ..planner.smoke import STAGE_PROTOCOL, STAGE_PURPOSE, _suite, check_plan, read_input, input_schema, sha, verify_stage_bindings, stage_purpose
from ..recovery import DIRECTORY as RECOVERY_DIR, MANIFEST as RECOVERY_MANIFEST, stage_recovery, verify_recovery_binding
from ..runtime import resolve_worker
from ..supervisor.process import invoke
from ..supervisor.isolated_worker import invoke_isolated_worker
from ..supervisor.resource import (SCHEMA as RESOURCE_SCHEMA, SNAPSHOT as RESOURCE_SNAPSHOT, admission,
                                   sample, verify_resources, workspace_inventory)

RUN_SCHEMA = "bmk.dev-lossless-run/1"
OBSERVATION_SNAPSHOT = "observation.schema.json"
STAGE_SNAPSHOT = "lossless-stage-suite.schema.json"
ARTIFACT_LIMIT_REASON = "serialized frame exceeds frozen preflight artifact limit"
RAW_FILES = ("run.json", "experiment.lock.json", "suite.lock.json", "source-build-manifest.json",
             OBSERVATION_SNAPSHOT, "schedule.jsonl", "events.jsonl", "observations.jsonl",
             "validations.jsonl", "accounting.jsonl")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _line(stream, document: dict) -> None:
    stream.write(canonical_bytes(document) + b"\n")
    stream.flush()
    os.fsync(stream.fileno())


def write_new(path: Path, doc: dict) -> None:
    with path.open("xb") as out:
        _line(out, doc)


def _publish(path: Path, doc: dict) -> None:
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=path.parent) as directory:
        staged = Path(directory) / path.name
        write_new(staged, doc)
        staged.replace(path)


def _rows(path: Path) -> list[dict]:
    # Reuse the strict JSON decoder, including rejection of non-finite values
    # and duplicate keys. The canonical raw writer emits no blank rows.
    from ..assets import parse_json
    with path.open("r", encoding="utf-8") as stream:
        return [parse_json(line, str(path)) for line in stream]


def _ref(run: Path, path: Path) -> dict:
    return {"path": path.relative_to(run).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def _worker_json(path: Path, lines: int) -> list[dict]:
    from ..assets import parse_json
    require(path.is_file() and path.stat().st_size <= 128 * 1024, "missing or oversized worker metadata")
    rows = [parse_json(line, str(path)) for line in path.read_text(encoding="utf-8").splitlines()]
    require(len(rows) == lines and all(type(row) is dict for row in rows), "invalid worker metadata")
    return rows


def _observation(contract: Contract, row: dict, location: str, *, observe_process=False, resources=False, isolated=False) -> None:
    contract.validate(row, location)
    ops, status, artifact = row["operations"], row["status"], row["artifact"]
    require(all(("process_wall_ns" in op) == (observe_process and op["pid"] is not None) for op in ops),
            "operation timing must match the frozen extent and actual process launch")
    require(all(("child_usage" in op)==(resources and op["pid"] is not None) for op in ops) and
            all((key in row)==resources for key in ("resource_guard","workspace")) and
            (resources or status!="resource_blocked"), "resource facts must match bound observer and actual process launch")
    for op in ops:
        require(("input_mounts" in op) == (isolated and op["pid"] is not None),
                "input mount evidence must match isolated execution and actual launch")
        if not isolated:
            require(op["status"] not in {"sandbox_failed", "file_limit_signal"} and
                    (op["status"] != "crash" or op["returncode"] < 0), "unbound isolated worker terminal")
    if artifact is not None:
        require(ops and ops[0]["pid"] is not None and artifact["path"] == f"artifacts/{row['slot_id']}.bmk",
                "artifact is not bound to the slot's encoder")
    if len(ops) == 2:
        require(ops[0]["status"] == "completed" and artifact is not None, "decode requires an encoded artifact")
    if not ops:
        require(status in {"input_failed", "dependency_failed", "cancelled", "resource_blocked"}, "missing operation for terminal status")
    elif status == "validation_failed":
        require(ops[-1]["status"] == "completed" and
                (len(ops) == 2 or artifact is None or row["reason"] == ARTIFACT_LIMIT_REASON),
                "validation failure must follow a successful child with missing or invalid output")
    elif status != "verified":
        require(status == ops[-1]["status"] and row["reason"] == ops[-1]["reason"],
                "terminal status or reason differs from last operation")


def _isolated_operation(run, plan, method, tmp, logs, direction, inputs, args, targets, cancelled):
    bindings = plan['contract_bindings']
    with tempfile.TemporaryDirectory(prefix=direction+'-', dir=tmp) as work:
        try:
            out, op = invoke_isolated_worker(run / RECOVERY_DIR, bindings['recovery'], method,
                bindings['isolation']['limits'], Path(work), logs, direction, inputs, args, cancelled, observe=True)
        except (ContractError, FileNotFoundError) as exc:
            # A lost/corrupted closure asset prevented this operation from launching.
            return {"operation": direction, "status": "dependency_failed", "reason": str(exc),
                    "pid": None, "session_id": None, "returncode": None}, False
        # The frozen native worker's ordinary exits are 0, 2 and 3. Bubblewrap
        # can forward signals as 128+signum (keep the observed launcher code).
        if op['status'] == 'failed' and op['returncode'] is not None and 129 <= op['returncode'] <= 192:
            op.update(status='crash', reason=f"worker signal forwarded as launcher exit {op['returncode']}")
        files = {p.name: p for p in out.iterdir()}
        regular = {name for name, p in files.items() if p.is_file() and not p.is_symlink()}
        valid = files.keys() == targets.keys() == regular
        for name in regular & targets.keys():
            if valid or op['status'] != 'completed':
                files[name].rename(targets[name])
        return op, valid


def _case(root, run, plan, slot, cancelled, contract, tmp, *, capture_usage=False, setup_reason=None) -> tuple[dict, dict | None, dict | None]:
    sid = slot["slot_id"]
    method = plan["methods"][slot["method_id"]]
    source = plan["inputs"][slot["input_id"]]
    row = {"schema": "bmk.dev-observation/1", "slot_id": sid, "attempt": 1, "operations": [],
           "status": "cancelled", "reason": "cancel requested before slot", "artifact": None}
    if cancelled():
        return row, None, None
    isolated = isolation.active(plan['suite'])
    if setup_reason is not None:
        row.update(status='dependency_failed', reason=setup_reason)
        return row, None, None
    if not isolated:
        try:
            declared = next(m for m in plan["suite"]["methods"] if m["plugin"] == method["plugin"])
            binding = resolve_worker(root, plan["build"], method["plugin"], declared["options"])
            require(binding["configuration_id"] == slot["configuration_id"] and binding["options"] == method["options"],
                    "resolved method differs from plan")
        except (ContractError, OSError, ValueError) as exc:
            row.update(status="dependency_failed", reason=str(exc))
            return row, None, None
    try:
        count, values = read_input(root, source)
        schema = input_schema(count)
        require(count == source["count"] and len(values) == source["bytes"] and sha(values) == source["raw_sha256"] and
                sha(schema) == source["schema_sha256"], "canonical input differs from plan")
    except (ContractError, OSError) as exc:
        row.update(status="input_failed", reason=str(exc))
        return row, None, None
    logs = run / "logs" / sid
    logs.mkdir()
    artifact = run / "artifacts" / f"{sid}.bmk"
    timeout = plan["suite"]["timeout_seconds_per_operation"]
    observe_process = timed(plan["suite"])
    src, meta = tmp / "original.bin", tmp / "original.json"
    src.write_bytes(values)
    meta.write_bytes(schema)
    if isolated:
        op, _ = _isolated_operation(run, plan, method, tmp, logs, 'encode',
            {'original.bin': src, 'original.json': meta},
            [str(source['dtype']), '/inputs/original.bin', '/inputs/original.json', '/out/frame.bmk'],
            {'frame.bmk': artifact}, cancelled)
    else:
        args = [binding["library"], method["plugin"], canonical_bytes(binding["options"]).decode("utf-8")]
        op = invoke([binding["worker"], "encode", *args, str(source["dtype"]), src, meta, artifact],
                    tmp, logs, "encode", timeout, cancelled, observe_process=observe_process,capture_usage=capture_usage)
    row["operations"].append(op)
    if artifact.is_file():
        row["artifact"] = _ref(run, artifact)
    if op["status"] != "completed":
        row.update(status=op["status"], reason=op["reason"])
        return row, None, None
    src.unlink()
    meta.unlink()
    dst, descriptor = tmp / "restored.bin", tmp / "restored.json"
    if row["artifact"] is None:
        row.update(status="validation_failed", reason="encoder produced no artifact")
        return row, None, None
    limit = plan["suite"].get("max_serialized_bytes_per_slot")
    if limit is not None and row["artifact"]["bytes"] > limit:
        row.update(status="validation_failed", reason=ARTIFACT_LIMIT_REASON)
        return row, None, None
    outputs_valid = True
    if isolated:
        op, outputs_valid = _isolated_operation(run, plan, method, tmp, logs, 'decode',
            {'frame.bmk': artifact}, ['/inputs/frame.bmk', '/out/restored.bin', '/out/restored.json'],
            {'restored.bin': dst, 'restored.json': descriptor}, cancelled)
    else:
        op = invoke([binding["worker"], "decode", *args, artifact, dst, descriptor], tmp, logs, "decode", timeout, cancelled,
                    observe_process=observe_process,capture_usage=capture_usage)
    row["operations"].append(op)
    if op["status"] != "completed":
        row.update(status=op["status"], reason=op["reason"])
        return row, None, None
    decoded_ref = None
    try:
        require(outputs_valid, "missing or undeclared isolated decode output")
        (enc,) = _worker_json(logs / "encode.stdout", 1)
        shape, dec = _worker_json(logs / "decode.stdout", 2)
        require(shape == {"dtype": source["dtype"], "count": count}, "restored dtype or shape differs")
        require(dst.is_file() and dst.stat().st_size == len(values) and descriptor.is_file() and
                descriptor.stat().st_size == len(schema), "restored bytes or schema length differs")
        decoded_ref = {"values_sha256": digest(dst), "schema_sha256": digest(descriptor)}
        require(dst.read_bytes() == values and descriptor.read_bytes() == schema, "restored values or schema differ")
        verified = {**row, "status": "verified", "reason": "", "execution": {"encode": enc, "decode": dec}}
        contract.validate(verified, "worker execution metadata")
    except (ContractError, ValueError, OSError) as exc:
        row.update(status="validation_failed", reason=str(exc))
        return row, {"slot_id": sid, "status": "failed", "decoded": decoded_ref}, None
    row = verified
    validated = {"slot_id": sid, "status": "bitwise_exact", "decoded": decoded_ref,
                 "original_passed_to_decode": False, "staged_source_removed": True, "verification": "artifact_each"}
    accounting = {"slot_id": sid, "original_logical_bytes": len(values), "serialized_bytes": row["artifact"]["bytes"],
                  "boundary": "complete_worker_frame_including_schema"}
    return row, validated, accounting


def run_smoke(root: Path, plan: dict, *, cancelled=lambda: False) -> dict:
    root = root.resolve(strict=True)
    check_plan(plan)
    check_plan(plan, _suite(root, plan["suite"]["id"]))
    stage = plan["schema"] == STAGE_PROTOCOL
    observed = timed(plan["suite"])
    resources = "resource" in plan.get("contract_bindings",{})
    recovery = plan.get('contract_bindings', {}).get('recovery')
    recovery_files, verified_slots = [], []
    recovery_status, recovery_reason = 'no_verified_samples', ''
    isolated = isolation.active(plan['suite'])
    attempted_setup = False
    if stage:
        verify_stage_bindings(root, plan)
    if observed:
        require(sys.platform == "linux" and all(hasattr(os, name) for name in ("waitid", "P_PID", "WEXITED", "WNOWAIT")),
                "process timing preflight requires Linux waitid/WNOWAIT")
    contract = load_contract(root, "observation")
    require(contract.document_id == plan["observation_schema_id"], "observation schema differs from frozen plan")
    results = root / "results"
    require(not results.is_symlink(), "results root cannot be a symlink")
    results.mkdir(exist_ok=True)
    run_id = uuid.uuid4().hex
    run = results / run_id
    run.mkdir(mode=0o700)
    run_started_ns = time.monotonic_ns() if resources else None
    for name in ("logs", "artifacts", "derived"):
        (run / name).mkdir()
    if resources:
        (run / "failures").mkdir()
    if recovery:
        (run / 'retained').mkdir()
    write_new(run / "run.json", {"schema": RUN_SCHEMA, "run_id": run_id,
                                 "kind": stage_purpose(plan["suite"]["id"]) if stage else "development_functional",
                                 "plan_content_id": plan["plan_content_id"], "started_at": utc(),
                                 "qualification_granted": False})
    write_new(run / "experiment.lock.json", plan)
    write_new(run / "suite.lock.json", {"suite": plan["suite"], "slots": plan["slots"]})
    write_new(run / "source-build-manifest.json", plan["build"])
    write_new(run / OBSERVATION_SNAPSHOT, contract.document)
    if stage:
        write_new(run / STAGE_SNAPSHOT, load_contract(root, "lossless-stage-suite").document)
    if observed:
        write_new(run / MEASUREMENT_SNAPSHOT, load_contract(root, "measurement-policy").document)
        write_new(run / COMPARISON_SNAPSHOT, load_contract(root, "comparison-contract").document)
    if resources:
        write_new(run / RESOURCE_SNAPSHOT, load_contract(root, RESOURCE_SCHEMA).document)
    with (run / "schedule.jsonl").open("xb") as schedule:
        for slot in plan["slots"]:
            _line(schedule, slot)
    with ExitStack() as stack:
        events, observations, validations, accounting = [stack.enter_context((run / (name + ".jsonl")).open("xb"))
                      for name in ("events", "observations", "validations", "accounting")]
        for slot in plan["slots"]:
            _line(events, {"event": "slot_started", "slot_id": slot["slot_id"], "at": utc()})
            pending = bool(recovery and not (attempted_setup if isolated else verified_slots))
            guard = admission(plan,slot,sample(run),recovery_pending=pending) if resources else None
            tmp = None
            if guard and guard['reasons']:
                row = {"schema":"bmk.dev-observation/1","slot_id":slot["slot_id"],"attempt":1,"operations":[],
                       "status":"resource_blocked","reason":"; ".join(guard['reasons']),"artifact":None}
                validation = byte_counts = None
            else:
                if isolated and not attempted_setup:
                    attempted_setup = True
                    try:
                        for declared in plan['suite']['methods']:
                            method = plan['methods'][declared['plugin']]
                            resolved = resolve_worker(root, plan['build'], method['plugin'], declared['options'])
                            require(all(resolved[key] == method[key] for key in ('configuration_id', 'options')),
                                    'resolved method differs from isolated plan')
                        recovery_files = stage_recovery(root, run, recovery)
                        recovery_status = 'ready'
                    except (ContractError, OSError, ValueError) as exc:
                        recovery_status, recovery_reason = 'setup_failed', str(exc)
                if resources:
                    # Commit validation, accounting and inventory before deleting any
                    # decoded files. Unexpected failure leaves this run unsealed.
                    tmp = Path(tempfile.mkdtemp(prefix=".case-",dir=run))
                    row,validation,byte_counts = _case(root,run,plan,slot,cancelled,contract,tmp,capture_usage=True,
                                                      setup_reason=recovery_reason if recovery_status=='setup_failed' else None)
                else:
                    with tempfile.TemporaryDirectory(prefix=".case-",dir=run) as folder:
                        row,validation,byte_counts = _case(root,run,plan,slot,cancelled,contract,Path(folder))
            if resources:
                row.update(resource_guard=guard,workspace=workspace_inventory(tmp) if tmp else [])
            _observation(contract,row,f"observation for {slot['slot_id']}",observe_process=observed,resources=resources,isolated=isolated)
            if validation:
                _line(validations,validation)
            if byte_counts:
                _line(accounting,byte_counts)
            _line(observations,row)
            if recovery and row['status']=='verified':
                if not isolated and not verified_slots:
                    try:
                        recovery_files = stage_recovery(root,run,recovery)
                        recovery_status = 'ready'
                    except (ContractError,OSError) as exc:
                        recovery_status, recovery_reason = 'unavailable', str(exc)
                verified_slots.append(row['slot_id'])
            end = {"event":"slot_terminal","slot_id":row["slot_id"],"status":row["status"],"at":utc()}
            if resources:
                action = 'no_files'
                if tmp is not None:
                    if row['workspace'] and row['status']!='verified':
                        tmp.rename(run/'failures'/row['slot_id'])
                        action = 'failure_retained'
                    elif row['status']=='verified' and recovery_status=='unavailable':
                        tmp.rename(run/'retained'/row['slot_id'])
                        action = 'verified_retained'
                    else:
                        for ref in row['workspace']:
                            (tmp/ref['name']).unlink()
                        tmp.rmdir()
                        if row['status']=='verified':
                            action = 'verified_released'
                end['workspace_action'] = action
            _line(events,end)
    evidence = [run / name for name in RAW_FILES] + sorted(p for p in (run / "logs").rglob("*") if p.is_file())
    if stage:
        evidence.append(run / STAGE_SNAPSHOT)
    if observed:
        evidence.extend(run / name for name in (MEASUREMENT_SNAPSHOT,COMPARISON_SNAPSHOT))
    if resources:
        evidence.extend([run / RESOURCE_SNAPSHOT,*sorted((run/"failures").glob("*/*"))])
    if recovery:
        path = run/RECOVERY_MANIFEST
        write_new(path, {'recovery_id':recovery['recovery_id'], 'status':recovery_status,
                         'reason':recovery_reason, 'sample_slots':sorted(verified_slots)})
        evidence.extend([path,*recovery_files,*sorted((run/'retained').glob('*/*'))])
    evidence += sorted((run / "artifacts").iterdir())
    seal = {"schema": "bmk.dev-lossless-seal/1", "run_id": run_id, "finished_at": utc(),
            "files": [_ref(run, path) for path in evidence]}
    if resources:
        seal["run_elapsed_ns"] = time.monotonic_ns()-run_started_ns
    _publish(run / "completion.json", {**seal, "seal_id": content_id(seal)})
    return report_smoke(root, run_id)


def _read_run(root: Path, run_id: str) -> tuple[Path, dict, dict, list, dict]:
    require(isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id), "invalid run ID")
    run = local_file(root, f"results/{run_id}/run.json").parent
    require((run / "completion.json").is_file(), "run is unsealed; cannot report an interrupted run as complete")
    seal = load_json(local_file(run, "completion.json"))
    require(seal["schema"] == "bmk.dev-lossless-seal/1" and seal["run_id"] == run_id and
            seal["seal_id"] == content_id({k: v for k, v in seal.items() if k != "seal_id"}), "invalid run seal")
    sealed = {row["path"]: row for row in seal["files"]}
    require(len(sealed) == len(seal["files"]) and set(RAW_FILES) <= sealed.keys(), "incomplete or duplicate raw evidence closure")
    for item in sealed.values():
        require(verify_asset(run, item).stat().st_size == item["bytes"], f"evidence size mismatch: {item['path']}")
    meta = load_json(run / "run.json")
    require(meta["schema"] == RUN_SCHEMA and meta["run_id"] == run_id and meta["qualification_granted"] is False,
            "run identity or purpose mismatch")
    plan = load_json(run / "experiment.lock.json")
    check_plan(plan)
    stage = plan["schema"] == STAGE_PROTOCOL
    require(meta["kind"] == (stage_purpose(plan["suite"]["id"]) if stage else "development_functional"), "run kind differs from plan")
    if stage:
        require(STAGE_SNAPSHOT in sealed, "stage suite schema unavailable from seal")
        schema = compile_contract("lossless-stage-suite", load_json(run / STAGE_SNAPSHOT))
        require(schema.document_id == plan["contract_bindings"]["suite_schema"], "stage suite schema differs from plan")
        schema.validate(plan["suite"], "sealed stage suite")
    observed = timed(plan["suite"])
    if observed:
        require(MEASUREMENT_SNAPSHOT in sealed, "measurement schema unavailable from seal")
        measurement = plan["contract_bindings"]["measurement"]
        schema = compile_contract("measurement-policy", load_json(run / MEASUREMENT_SNAPSHOT))
        require(schema.document_id == measurement["schema_id"] and
                content_id(measurement["policy"]) == measurement["policy_id"], "measurement contract differs from frozen plan")
        schema.validate(measurement["policy"], "sealed measurement policy")
        if "comparison" in plan["contract_bindings"]:
            require(COMPARISON_SNAPSHOT in sealed, "comparison schema unavailable from seal")
            verify_stage_comparisons(plan,load_json(run / COMPARISON_SNAPSHOT))
    resources = plan.get("contract_bindings",{}).get("resource")
    if resources:
        require(observed and RESOURCE_SNAPSHOT in sealed and type(seal.get("run_elapsed_ns")) is int and
                seal["run_elapsed_ns"]>0, "resource policy or elapsed-time evidence unavailable from seal")
        schema = compile_contract(RESOURCE_SCHEMA,load_json(run / RESOURCE_SNAPSHOT))
        require(schema.document_id==resources['schema_id'] and content_id(resources['policy'])==resources['policy_id'],
                "resource policy identity differs from plan")
        schema.validate(resources['policy'],"sealed candidate resource policy")
    else:
        require(RESOURCE_SNAPSHOT not in sealed and "run_elapsed_ns" not in seal,"unbound resource observations")
    contract = compile_contract("observation", load_json(run / OBSERVATION_SNAPSHOT))
    require(contract.document_id == plan["observation_schema_id"], "sealed observation schema differs from frozen plan")
    require(plan["plan_content_id"] == meta["plan_content_id"] and plan["slots"] == _rows(run / "schedule.jsonl"),
            "run schedule or experiment identity differs")
    require(load_json(run / "suite.lock.json") == {"suite": plan["suite"], "slots": plan["slots"]} and
            load_json(run / "source-build-manifest.json") == plan["build"], "suite or build snapshot differs")
    observations = _rows(run / "observations.jsonl")
    sessions = set()
    for index, row in enumerate(observations, 1):
        _observation(contract, row, f"observations.jsonl:{index}", observe_process=observed,resources=bool(resources),isolated=isolation.active(plan["suite"]))
        for op in row["operations"]:
            session = op["session_id"]
            if session is not None:
                require(session not in sessions, "operation session reused in this run")
                sessions.add(session)
    require([row["slot_id"] for row in observations] == [slot["slot_id"] for slot in plan["slots"]],
            "terminal ledger must cover the entire plan in order")
    return run, plan, sealed, observations, seal


def _indexed(run: Path, name: str, expected_ids: set[str]) -> dict:
    rows = _rows(run / name)
    require(all(type(row) is dict and type(row.get("slot_id")) is str for row in rows), f"invalid rows in {name}")
    indexed = {row["slot_id"]: row for row in rows}
    require(len(indexed) == len(rows) and indexed.keys() == expected_ids, f"unexpected, missing or duplicate slots in {name}")
    return indexed


def _verify_isolated_case(run, plan, slot, row, sealed, sessions):
    sid = slot['slot_id']
    source = plan['inputs'][slot['input_id']]
    artifact = row['artifact']
    expected = {
        'encode': {'original.bin': {'sha256': source['raw_sha256'], 'bytes': source['bytes']},
                   'original.json': {'sha256': source['schema_sha256'], 'bytes': len(input_schema(source['count']))}},
        'decode': {'frame.bmk': {k: artifact[k] for k in ('sha256', 'bytes')}} if artifact else None,
    }
    mount_evidence = {}
    for op in row['operations']:
        if op['pid'] is None:
            continue
        direction, session = op['operation'], op['session_id']
        require(session not in sessions, 'isolated operations must have fresh launcher sessions')
        sessions.add(session)
        require(op['input_mounts'] == expected[direction], 'isolated inputs do not match the slot boundary')
        require(all(f'logs/{sid}/{direction}.{name}' in sealed for name in ('stdout','stderr')),
                'isolated operation lacks sealed process logs')
        mount_evidence[direction] = op['input_mounts']
    if row['status'] == 'verified':
        enc, = _worker_json(run / f'logs/{sid}/encode.stdout', 1)
        shape, dec = _worker_json(run / f'logs/{sid}/decode.stdout', 2)
        require(row['execution'] == {'encode': enc, 'decode': dec} and
                shape == {'dtype': source['dtype'], 'count': source['count']},
                'sealed isolated worker metadata differs from validated result')
    return mount_evidence


def _read_report(root: Path, run_id: str):
    run, plan, sealed, rows, seal = _read_run(root, run_id)
    verified = {row["slot_id"] for row in rows if row["status"] == "verified"}
    invalid = {row["slot_id"] for row in rows if row["status"] == "validation_failed" and len(row["operations"]) == 2}
    validations = _indexed(run, "validations.jsonl", verified | invalid)
    require(all(validations[sid].get("status") == "failed" for sid in invalid), "validation failure lacks failed verdict")
    accounting = _indexed(run, "accounting.jsonl", verified)
    events = _rows(run / "events.jsonl")
    require([(x["event"], x["slot_id"], x.get("status")) for x in events] ==
            [event for row in rows for event in (("slot_started", row["slot_id"], None),
                                                  ("slot_terminal", row["slot_id"], row["status"]))], "incomplete event ledger")
    cases = []
    observed = timed(plan["suite"])
    comparisons = plan.get("contract_bindings",{}).get("comparison")
    resources = plan.get("contract_bindings",{}).get("resource")
    recovery = plan.get('contract_bindings',{}).get('recovery')
    isolated = isolation.active(plan["suite"])
    if recovery:
        require(RECOVERY_MANIFEST in sealed, 'recovery metadata is not sealed')
        recovery_report = verify_recovery_binding(plan, load_json(run/RECOVERY_MANIFEST), sealed, verified, pre_staged=isolated)
        keep_verified = recovery_report['status']=='unavailable'
        require(all(p.split('/')[1] in verified for p in sealed if p.startswith('retained/')),
                'retained workspace is not bound to a verified slot')
    else:
        require(not any(p==RECOVERY_MANIFEST or p.startswith((RECOVERY_DIR+'/', 'retained/')) for p in sealed),
                'unbound recovery evidence')
        recovery_report, keep_verified = None, False
    released, retained = [], []
    if isolated:
        require(recovery_report["status"] in {"ready", "setup_failed", "no_verified_samples"},
                "isolated recovery setup has invalid status")
    sessions = set()
    setup_seen = False
    verified_before = False
    usage = []
    for i,(slot,row) in enumerate(zip(plan["slots"], rows,strict=True)):
        sid, status = row["slot_id"], row["status"]
        artifact = row["artifact"]
        if artifact is not None:
            require(sealed.get(artifact["path"]) == artifact, "artifact is not sealed")
        if status == "verified":
            source = plan["inputs"][slot["input_id"]]
            verdict = validations.get(sid, {})
            require(artifact is not None and verdict.get("status") == "bitwise_exact" and
                    verdict.get("decoded") == {"values_sha256": source["raw_sha256"], "schema_sha256": source["schema_sha256"]} and
                    verdict.get("original_passed_to_decode") is False and verdict.get("staged_source_removed") is True and
                    verdict.get("verification") == "artifact_each", "verified row lacks matching validator evidence")
            expected = {"slot_id": sid, "original_logical_bytes": source["bytes"], "serialized_bytes": artifact["bytes"],
                        "boundary": "complete_worker_frame_including_schema"}
            require(canonical_bytes(accounting[sid]) == canonical_bytes(expected), "mismatched byte accounting")
            limit = plan["suite"].get("max_serialized_bytes_per_slot")
            require(limit is None or artifact["bytes"] <= limit, "verified artifact exceeds frozen limit")
        case = {**slot, "status": status, "reason": row["reason"], "artifact": artifact,
                "accounting": accounting.get(sid)}
        if observed:
            case.update(comparison_id=comparison_identity(plan, plan["inputs"][slot["input_id"]]),
                        process_wall_ns={op["operation"]: op["process_wall_ns"] for op in row["operations"] if "process_wall_ns" in op},
                        execution=row.get("execution"))
        if isolated:
            case['input_mounts'] = _verify_isolated_case(run, plan, slot, row, sealed, sessions)
            if status != 'resource_blocked':
                require(recovery_report['status'] != 'no_verified_samples', 'admitted slot lacks isolated setup outcome')
                if recovery_report['status'] == 'setup_failed':
                    require(not row['operations'] and (status == 'cancelled' or
                            status == 'dependency_failed' and row['reason'] == recovery_report['reason']),
                            'isolated setup failure differs from slot terminal')
        if resources:
            event = events[2*i+1]
            verify_resources(plan,slot,row,event,validations.get(sid),sealed,
                             recovery_pending=bool(recovery and not (setup_seen if isolated else verified_before)),
                             keep_verified=keep_verified)
            setup_seen |= status != "resource_blocked"
            verified_before |= status=='verified'
            use = {op['operation']:op['child_usage'] for op in row['operations'] if 'child_usage' in op}
            usage.extend(use.values())
            case['resources'] = {'guard':row['resource_guard'],'child_usage':use}
            case['workspace'] = {'action':event['workspace_action'],'files':row['workspace']}
            if event['workspace_action']=='verified_released':
                released.extend(row['workspace'])
            elif event['workspace_action']=='failure_retained':
                retained.extend(row['workspace'])
        if comparisons:
            case['frozen_comparison_ids'] = {d:b['comparison_id'] for d,b in comparisons['by_input'][slot['input_id']].items()}
            case['primary_comparison'] = {'admitted':False,'reasons':['development_diagnostic_only',
                'formal_resource_budget_not_verified','formal_qualification_not_run'] +
                ([] if status=='verified' else ['terminal_not_verified'])}
        cases.append(case)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    report = {"schema": "bmk.dev-lossless-report/1", "run_id": run_id, "plan_content_id": plan["plan_content_id"],
              "planned_slots": len(plan["slots"]), "statuses": counts, "cases": cases,
              "complete": True, "all_verified": counts.get("verified") == len(rows), "qualification_granted": False}
    if plan["schema"] == STAGE_PROTOCOL:
        report.update(evidence_scope=plan["purpose"], target_stage="M1", measurement=PROFILE if observed else "not_collected",
                      estimates=plan["estimates"])
    if observed:
        report["extent"] = dict(plan["contract_bindings"]["measurement"]["policy"]["profiles"][PROFILE])
    if comparisons:
        report["comparison_contracts"] = comparisons
    if resources:
        require(sum(op.get('process_wall_ns',0) for row in rows for op in row['operations'])<=seal['run_elapsed_ns'],
                'serial child lifetimes exceed total measured run time')
        report['resource_diagnostics'] = {'policy_id':resources['policy_id'],'hard_isolation':False,
            'run_elapsed_ns':seal['run_elapsed_ns'],'child_operations_observed':len(usage),
            'child_maxrss_max_bytes':max((x['maxrss_bytes'] for x in usage),default=None),
            'child_cpu_total_ns':sum(x['user_cpu_ns']+x['system_cpu_ns'] for x in usage) if usage else None,
            'sealed_logical_bytes':sum(x['bytes'] for x in sealed.values()),'sealed_files':len(sealed),
            'verified_workspace_released_bytes':sum(x['bytes'] for x in released),'verified_workspace_released_files':len(released),
            'failed_workspace_retained_bytes':sum(x['bytes'] for x in retained),'failed_workspace_retained_files':len(retained)}
    if isolated:
        require(setup_seen == (recovery_report['status'] != 'no_verified_samples'), 'isolated setup was not attempted as planned')
        report['isolation'] = plan['contract_bindings']['isolation']
        report['extent'].update(output_boundary='worker_output_file_closed_before_launcher_reap',
                                observed_clock_boundary=isolation.SCOPE)
        report['resource_diagnostics'].update(usage_boundary=isolation.USAGE,
            per_process_address_space_and_per_file_limits=True)
    if recovery_report is not None:
        report['recovery'] = recovery_report
    return report, run, plan, seal


def report_smoke(root: Path, run_id: str) -> dict:
    report, run, _, _ = _read_report(root, run_id)
    derived = run / "derived"
    require(not derived.is_symlink(), "derived directory cannot be a symlink")
    derived.mkdir(exist_ok=True)
    _publish(derived / "report.json", report)
    return report
