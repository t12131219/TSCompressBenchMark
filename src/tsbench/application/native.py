"""One ledger and recomputable report for the M0 native candidate preflight."""
from collections import Counter
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from ..assets import ContractError, canonical_bytes, content_id, load_json, local_file, parse_json, require, verify_asset
from ..planner.native import NativePlanRequest, PLAN_SCHEMA, _file, plan_native
from ..qualification.alp import verify_alp
from ..qualification.corad_inference import verify_corad_inference
from ..qualification.corad_training import verify_corad_training
from ..qualification.frame_batches import verify_frame_batches
from ..qualification.gorilla import verify_gorilla
from ..qualification.huff0 import verify_huff0
from ..qualification.huff0_portable import comparison_binding, verify_portable_control
from ..qualification.lzbench import verify_lzbench
from ..qualification.method_boundaries import binding_build_inputs, verify_boundary_evidence
from ..qualification.native_conditions import resolve_conditions
from ..qualification.pcodec import verify_pcodec
from ..qualification.pbepla_progressive import verify_pbepla_progressive
from ..qualification.selfstar import verify_selfstar
from ..qualification.sprintz import verify_sprintz
from ..qualification.titchy_access import verify_titchy_access
from ..qualification.titchy_native import verify_titchy_native
from ..qualification.zfp import verify_zfp
from ..supervisor.process import invoke
from .smoke import _line, _publish, write_new

LEDGER = "observations.jsonl"
PRIMARY_NOT_PASSED = "primary Huff0 probe did not pass"
TERMINAL = frozenset({"passed", "skipped", "failed", "crash", "timeout", "cancelled", "dependency_failed", "evidence_failed"})


def _evidence_paths(slot, out):
    """A diagnostic may emit exactly one nested evidence directory, never a shard to select among."""
    for relative in slot['evidence']:
        parts = relative.split('/')
        if '{run_id}' not in parts:
            yield relative
            continue
        require(parts.count('{run_id}')==1 and len(parts)==3 and {'output':parts[0]} in slot['command'],
                'invalid nested diagnostic evidence contract')
        parent = out/parts[0]
        require(parent.is_dir() and not parent.is_symlink(), 'missing diagnostic evidence directory')
        children = list(parent.iterdir())
        require(len(children)==1 and children[0].is_dir() and not children[0].is_symlink() and
                re.fullmatch(r'[0-9a-f]{32}',children[0].name), 'expected exactly one diagnostic evidence directory')
        yield f'{parts[0]}/{children[0].name}/{parts[2]}'


def _check_plan(document: dict) -> None:
    require(isinstance(document, dict) and document.get("schema") == PLAN_SCHEMA and
            document.get("qualification_granted") is False and document.get("target_stage") == "M0" and
            document.get("evidence_scope") == "development_preflight" and document.get("runnable") is True,
            "not a native M0 preflight plan")
    body = {k: v for k, v in document.items() if k != "plan_content_id"}
    require(document.get("plan_content_id") == content_id(body), "invalid native preflight plan identity")
    bindings = document['bindings']
    if 'native_admission' in bindings:
        a = bindings['native_admission']
        require(a['schema']=='bmk.native-admission-plan/1' and a['plan_content_id']==content_id(
            {k:v for k,v in a.items() if k!='plan_content_id'}) and
            a['bindings']['requirements_plan_id']==bindings['native_requirements_plan_id'] and
            a['runnable'] is a['qualification_granted'] is a['stage_accepted'] is False and
            a['coverage']['formal_execution_bindings']==a['coverage']['formal_qualified_obligations']==0 and
            len(a['obligations'])==a['coverage']['total_obligations'] and
            all(r['qualification']=='not_run' for r in a['routes']) and
            [s['condition_case'] for s in a['obligations'] if s['kind']=='conditional']==bindings['native_conditional_plan']['obligations'],
            'native admission definition is inconsistent or claims execution/qualification')


def _argv(plan: dict, slot: dict, roots: dict, out: Path):
    for item in slot["command"]:
        if "asset" in item:
            ref = plan["bindings"]["command_inputs"][item["asset"]]
            yield str(local_file(roots[ref["root"]], ref["path"]))
        elif "python" in item:
            yield sys.executable
        elif "input_slot" in item:
            yield str(out.parent / item["input_slot"])
        elif "output" in item:
            yield str(out / item["output"])
        else:
            yield item["literal"]


def _verify_bound_evidence(document, slot, out, *, sealed_paths=None):
    bindings = document["bindings"]
    boundary = bindings.get("method_boundaries")
    if boundary and boundary["test"] == slot["test"]:
        verify_boundary_evidence(boundary, binding_build_inputs(document, slot), out, sealed_paths=sealed_paths)
    batches = bindings.get("frame_batches")
    if batches and batches["test"] == slot["test"]:
        verify_frame_batches(batches, binding_build_inputs(document, slot), out, sealed_paths=sealed_paths)
    alp = bindings.get("alp")
    if alp and alp["test"] == slot["test"]:
        driver = bindings["command_inputs"][slot["command"][3]["asset"]]
        ffi = [x["sha256"] for x in bindings["project_inputs"] if x["path"] == "tests/integration/direct_control.py"]
        require(len(ffi) == 1, "ALP FFI source identity missing")
        verify_alp(alp, binding_build_inputs(document, slot), driver["sha256"], out,
                   sealed_paths=sealed_paths, ffi_sha256=ffi[0])
    lzbench = bindings.get("lzbench")
    if lzbench and lzbench["test"] == slot["test"]:
        sources = {x["path"]:x["sha256"] for x in bindings["project_inputs"]}
        cpp_path = "tests/native/lzbench_contract.cpp"
        driver_path = "tests/integration/lzbench_native_probe.py"
        require(cpp_path in sources and driver_path in sources, "lzbench diagnostic source identity missing")
        verify_lzbench(lzbench, binding_build_inputs(document, slot),
                       {"cpp":sources[cpp_path], "driver":sources[driver_path]}, out, sealed_paths=sealed_paths)
    for key, verify in (("titchy_access", verify_titchy_access), ("pbepla", verify_pbepla_progressive), ("gorilla", verify_gorilla),
                        ("pcodec", verify_pcodec), ("sprintz", verify_sprintz), ("titchy_native", verify_titchy_native),
                        ("selfstar", verify_selfstar)):
        bundle = bindings.get(key)
        if bundle and bundle["test"] == slot["test"]:
            driver = bindings["command_inputs"][slot["command"][3]["asset"]]
            verify(bundle, binding_build_inputs(document, slot), driver["sha256"], out, sealed_paths=sealed_paths)
    zfp = bindings.get("zfp")
    if zfp and zfp["test"] == slot["test"]:
        driver = bindings["command_inputs"][slot["command"][3]["asset"]]
        sources = [x["sha256"] for x in bindings["project_inputs"] if x["path"] == "tests/native/zfp_omp_control.cpp"]
        require(len(sources) == 1, "ZFP diagnostic source identity missing")
        verify_zfp(zfp, binding_build_inputs(document, slot), driver["sha256"], sources[0], out,
                   sealed_paths=sealed_paths)
    huff0 = bindings.get("huff0")
    if huff0 and huff0["test"] == slot["test"]:
        driver = bindings["command_inputs"][slot["command"][3]["asset"]]
        sources = [x["sha256"] for x in bindings["project_inputs"] if x["path"] == "tests/native/huff0_control.cpp"]
        require(len(sources) == 1, "Huff0 diagnostic source identity missing")
        verify_huff0(huff0, binding_build_inputs(document, slot), driver["sha256"], sources[0], out,
                     sealed_paths=sealed_paths)
    corad = bindings.get("corad_inference")
    if corad and corad["test"] == slot["test"]:
        driver = bindings["command_inputs"][slot["command"][3]["asset"]]
        sources = [x["sha256"] for x in bindings["project_inputs"] if x["path"] == "tests/isolation/corad_native_control.py"]
        require(len(sources) == 1, "CORAD direct control source identity missing")
        verify_corad_inference(corad, binding_build_inputs(document, slot), driver["sha256"], out,
                               sealed_paths=sealed_paths, source_oracle_sha256=sources[0])
    training = bindings.get("corad_training")
    if training and training["test"] == slot["test"]:
        driver = bindings["command_inputs"][slot["command"][3]["asset"]]
        verify_corad_training(training, binding_build_inputs(document, slot), driver["sha256"],
                              bindings["python_sha256"], out, sealed_paths=sealed_paths)


def _execute(document, slot, roots, run, cancelled, by_slot, control):
    out = run / "slots" / slot["slot_id"]
    out.mkdir()
    if 'requires_slot' in slot and by_slot[slot['requires_slot']] != 'passed':
        return {'slot_id':slot['slot_id'],'test':slot['test'],'status':'dependency_failed','returncode':None,
                'session_id':None,'reason':PRIMARY_NOT_PASSED,'artifacts':[]}
    with tempfile.TemporaryDirectory(prefix="work-", dir=out) as work:
        env = {"LC_ALL": "C", "PATH": os.defpath, "HOME": work, "TMPDIR": work, "PYTHONDONTWRITEBYTECODE": "1"}
        if slot["smoke_export"]:
            env["TSBENCH_SMOKE_EVIDENCE_DIR"] = str(out / "smoke")
        argv = list(_argv(document, slot, roots, out))
        operation = invoke(argv, Path(work), out, "probe", slot["timeout_seconds"], cancelled, environment=env)
    state, code, reason = (operation[k] for k in ("status", "returncode", "reason"))
    if state == "completed":
        state = "passed"
        try:
            for relative in _evidence_paths(slot,out):
                evidence = load_json(local_file(out, relative))
                require(isinstance(evidence, dict) and evidence, f"invalid diagnostic object: {relative}")
            for relative in slot.get("binary_evidence", []):
                require(local_file(out, relative).stat().st_size > 0, f"empty binary evidence: {relative}")
            _verify_bound_evidence(document, slot, out)
            if control and slot["slot_id"]==control["control_slot_id"]:
                verify_portable_control(document,run,control)
        except (ContractError, OSError) as exc:
            state, reason = "evidence_failed", str(exc)
    elif state == "failed" and code == slot["skip_returncode"] and code is not None:
        state, reason = "skipped", f"probe returned configured skip code {code}"
    require(state in TERMINAL, "unknown probe terminal state")
    artifacts = []
    for path in sorted(out.rglob("*")):
        require(not path.is_symlink(), "probe emitted a symlink into retained evidence")
        if path.is_file():
            artifacts.append(_file(run, path.relative_to(run).as_posix()))
    return {"slot_id": slot["slot_id"], "test": slot["test"], "status": state, "returncode": code,
            "session_id": operation["session_id"], "reason": reason, "artifacts": artifacts}


def run_native(root: Path, request: NativePlanRequest, document: dict, results: Path, *, cancelled=lambda: False) -> dict:
    _check_plan(document)
    expected = plan_native(root, request)
    require(canonical_bytes(document) == canonical_bytes(expected), "native preflight bindings changed; freeze a new plan")
    root, build = root.resolve(), request.build_dir.resolve()
    roots = {'project':root,'build':build}
    if request.huff0_portable_build is not None:
        roots['huff0_portable'] = request.huff0_portable_build.resolve(strict=True)
    control = comparison_binding(document)
    results = results.resolve()
    require(not any(results.is_relative_to(p) for k,p in roots.items() if k!='project'),
            "native preflight results must not be inside a bound build")
    run_id = uuid.uuid4().hex
    run = results / run_id
    run.mkdir(parents=True)
    (run / "slots").mkdir()
    write_new(run / "plan.json", document)
    by_slot = {}
    with (run / LEDGER).open("xb") as ledger:
        for slot in document["slots"]:
            row = _execute(document,slot,roots,run,cancelled,by_slot,control)
            _line(ledger,row)
            by_slot[slot['slot_id']] = row['status']
    seal = {"schema": "bmk.native-preflight-completion/1", "run_id": run_id,
            "plan_content_id": document["plan_content_id"], "sealed_inputs": [_file(run, path) for path in ("plan.json", LEDGER)]}
    _publish(run / "completion.json", seal)
    result = report_native(run)
    write_new(run / "report.json", result)
    return result


def _check_probe_dependency(slot, row, seen):
    if 'requires_slot' not in slot:
        return
    parent = slot['requires_slot']
    require(parent in seen, 'Huff0 portable primary dependency must be earlier in the ledger')
    if seen[parent] != 'passed':
        require(row['reason']==PRIMARY_NOT_PASSED and row['status']=='dependency_failed' and
                row['returncode'] is None and row['session_id'] is None and not row['artifacts'],
                'unstarted Huff0 portable control has execution evidence or an inconsistent terminal state')
    else:
        require(row['reason']!=PRIMARY_NOT_PASSED, 'Huff0 portable primary dependency did pass')


def _report_rows(run, document, observations, control):
    slots = document["slots"]
    require(len(slots) == len(observations) == document["coverage"]["slots"], "incomplete native ledger")
    statuses, sessions, seen, portable = {}, set(), {}, None
    for slot, row in zip(slots, observations, strict=True):
        slot_id, name = slot["slot_id"], slot["test"]
        require(type(row) is dict and set(row) == {"slot_id", "test", "status", "returncode", "session_id", "reason", "artifacts"}
                and row["slot_id"] == slot_id and row["test"] == name and name not in statuses and slot_id not in seen,
                "native ledger slot order/closure mismatch")
        status, code, session = row["status"], row["returncode"], row["session_id"]
        require(status in TERMINAL and (code is None or type(code) is int) and isinstance(row["reason"], str),
                "invalid native ledger status")
        if status in {"passed", "evidence_failed"}:
            require(code == 0, "successful probe completion must have zero exit code")
        elif status == "skipped":
            require(code is not None and code == slot["skip_returncode"], "unexpected native skip")
        elif status == "failed":
            require(code is None or code > 0 and code != slot["skip_returncode"], "inconsistent native failure")
        elif status == "crash":
            require(code is not None and code < 0, "inconsistent native crash")
        require((code is None) == (session is None), "inconsistent native session identity")
        if session is not None:
            require(re.fullmatch(r"[0-9a-f]{32}", session) and session not in sessions, "duplicate or invalid native session")
            sessions.add(session)
        _check_probe_dependency(slot,row,seen)
        prefix = f"slots/{slot_id}/"
        paths = set()
        for ref in row["artifacts"]:
            require(ref["path"].startswith(prefix) and ref["path"] not in paths, "artifact is outside its native slot")
            path = verify_asset(run, ref)
            require(type(ref["bytes"]) is int and ref["bytes"] == path.stat().st_size, "native evidence size mismatch")
            paths.add(ref["path"])
        if status == "passed":
            expected = {prefix + p for p in (*_evidence_paths(slot,run/prefix), *slot.get("binary_evidence", []), "probe.stdout", "probe.stderr")}
            require(expected <= paths, "successful native probe is missing evidence")
            _verify_bound_evidence(document, slot, run / prefix, sealed_paths={p.removeprefix(prefix) for p in paths})
            if control and slot_id==control['control_slot_id']:
                portable = verify_portable_control(document,run,control)
        statuses[name] = status
        seen[slot_id] = status
    return statuses, portable


def report_native(run: Path) -> dict:
    run = run.resolve(strict=True)
    require((run / "completion.json").is_file(), "native preflight run is unsealed")
    seal = load_json(local_file(run, "completion.json"))
    require(seal.get("schema") == "bmk.native-preflight-completion/1" and seal.get("run_id") == run.name and
            re.fullmatch(r"[0-9a-f]{32}", run.name), "native completion identity mismatch")
    require(seal.get("sealed_inputs") == [_file(run, p) for p in ("plan.json", LEDGER)], "native preflight seal mismatch")
    document = load_json(local_file(run, "plan.json"))
    _check_plan(document)
    require(seal.get("plan_content_id") == document["plan_content_id"], "native completion plan mismatch")
    ledger = local_file(run, LEDGER)
    with ledger.open(encoding="utf-8") as stream:
        rows = [parse_json(line, str(ledger)) for line in stream]
    control = comparison_binding(document)
    statuses, portable = _report_rows(run, document, rows, control)
    group_rows = [{"selection": g["selection"], "route": g["operation"]["route"],
                   "test": g["test"], "probe_status": statuses[g["test"]], "qualification": "not_run"}
                  for g in document["groups"]]
    require(len(group_rows) == document["coverage"]["native_groups"], "native group denominator mismatch")
    quality = {}
    corad = document['bindings'].get('corad_inference', {})
    if isinstance(policy := corad.get('quality_policy'),dict):
        [slot] = [s for s in document['slots'] if s['test']==corad['test']]
        if statuses[slot['test']]=='passed':
            out = run/'slots'/slot['slot_id']
            gate = load_json(local_file(out,corad['evidence_path']))['quality_gate']
            quality['empirical_quality'] = {'corad-inference': {'policy_id':policy['policy_id'],
                        'scope':policy['definition']['scope'],'decisions':{k:v['decision'] for k,v in gate['heldout'].items()}}}
        else:
            quality['empirical_quality'] = {'corad-inference': {'policy_id':policy['policy_id'],
                        'scope':policy['definition']['scope'],'decisions':None,'probe_status':statuses[slot['test']]}}
    conditional = ({'conditional_native_work':resolve_conditions(run,document,statuses,portable=portable)}
                   if 'native_conditional_plan' in document['bindings'] else {})
    admission = {}
    if a := document['bindings'].get('native_admission'):
        empirical = quality['empirical_quality']['corad-inference']
        [corad_contract] = [r['quality'] for r in a['routes'] if r['route']=='corad-inference']
        require(corad_contract['quality_policy']['policy_id']==empirical['policy_id'] and
                corad_contract['case_bundle_id']==corad['bundle_id'], 'CORAD evidence and admission quality definition differ')
        admission['native_admission'] = {'plan_content_id':a['plan_content_id'],'coverage':a['coverage'],
                                          'readiness':'definition_only','open':a['open']}
    return {"schema": "bmk.native-preflight-report/1", "run_id": run.name, "target_stage": "M0",
            "plan_content_id": document["plan_content_id"], "evidence_scope": document["evidence_scope"],
            "measurement": "development_diagnostics_only" if "frame_batches" in document["bindings"] else "not_collected",
            "qualification_granted": False, "stage_accepted": False,
            "complete": True, "all_probes_passed": all(s == "passed" for s in statuses.values()),
            "coverage": document["coverage"], "probe_statuses": dict(Counter(statuses.values())),
            "group_probe_statuses": dict(Counter(row["probe_status"] for row in group_rows)),
            "operations": group_rows, "observations": rows, **quality, **conditional, **admission}
