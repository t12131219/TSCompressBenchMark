"""Freeze the PBEPLA diagnostic inputs, geometries, levels and retained evidence."""
from hashlib import sha256
import math
from pathlib import Path
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..contracts import load_contract
from .corpus_windows import bind_window, read_window

CONFIG = "configs/suites/dev_pbepla_v1/cases.json"
PROBE = "tsbench.worker.pbepla.progressive"
EVIDENCE = "pbepla-control.json"
WORD_MAGIC = b"PBWORDS1"
REPLAY_HELPER = "tsbench_pbepla_replay_control"
PROGRESSIVE = ("each_prefix_without_later_layers", "rational_error_each_level", "effective_eps_and_bytes")
REPLAY = ("same_output_levels_as_batch", "verify_each_original_domain_bound", "source_passes_first_write_and_staging")
REJECT_OPTIONS = ('{}','{"eps":[]}','{"eps":[0.1,0.2]}','{"eps":[1,1]}','{"eps":[-1]}','{"eps":[1e400]}',
                  '{"eps":[1e308]}','{"eps":[1.e2]}','{"eps":[01]}','{"eps":[0]}','{"eps":[1],"connected":true}',
                  '{"eps":[17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1]}')


def boundary_source(count):
    return struct.pack('<d', 2.75) * count


def fixture(generator: str, n: int) -> bytes:
    values = [2.75 if generator == "constant" else (i % 31 - 14) * 0.0625 + (i // 31 % 3) * 0.25 for i in range(n)]
    return struct.pack(f"<{n}d", *values)


def schema_bytes(name: str) -> bytes:
    return canonical_bytes({"dtype": "f64", "column": "v", "case": name})


def retained_paths(bundle: dict) -> list[str]:
    positive = [path for spec in bundle["inputs"] for path in [spec["word_path"], *spec["frame_paths"]]]
    failures = bundle.get('failure_policy')
    return positive + failures['retained'] if failures else positive


def plan_pbepla_progressive(root: Path) -> tuple[dict, dict, dict[str, bytes]]:
    config = load_json(local_file(root, CONFIG))
    schema = load_contract(root, "pbepla-cases")
    schema.validate(config, CONFIG)
    window = bind_window(root, config["corpus"], config["corpus_id"], config["window"])
    inputs, cases, raw = [], [], {}
    method = config["method"]
    replay_names = set(config["replay"]["cases"])

    def add(name, data, eps, source, geometry):
        require(name not in raw and all(math.isfinite(2 * v) and v > 0 for v in eps) and
                all(a > b for a, b in zip(eps, eps[1:])), f"PBEPLA invalid case or eps order: {name}")
        replay = name in replay_names
        require(not replay or geometry is None, "PBEPLA replay fixtures must use default geometry")
        frame_paths = [f"pbepla-{name}-L{i}.bmk" for i in range(1, len(eps) + 1)]
        n = len(data) // 8
        require(n * len(eps) <= method["value_layer_budget"], f"PBEPLA exceeds ABI work bound: {name}")
        count = len(geometry.get("resolutions", eps)) if geometry else len(eps)
        require(count == len(eps), f"PBEPLA resolution schedule differs from eps: {name}")
        spec = {"name": name, "source": source, "count": n, "input_sha256": sha256(data).hexdigest(),
                "schema_sha256": sha256(schema_bytes(name)).hexdigest(), "requested_eps": eps, "geometry": geometry,
                "expected_flags": 1 if geometry is None else int(not geometry.get("connected")) + 2 * geometry.get("symmetric_band", 0),
                "expected_delay": method["max_delay"] if geometry is None else geometry["max_delay"],
                "replay": replay, "frame_paths": frame_paths, "word_path": f"pbepla-{name}.f64le",
                "word_bytes": len(WORD_MAGIC) + (len(eps) + 1) * len(data)}
        inputs.append({**spec, "input_id": content_id(spec)})
        raw[name] = data
        for route, checks in (("pbepla-progressive", PROGRESSIVE), ("pbepla-replay", REPLAY if replay else ())):
            for check in checks:
                case = {"selection": 87, "route": route, "check": check, "input_id": inputs[-1]["input_id"],
                        "name": f"{name}-{check}", "validator": config["validator"]}
                cases.append({**case, "case_id": content_id(case)})

    for spec in config["fixtures"]:
        name = spec["id"]
        add(name, fixture(name, spec["count"]), spec["eps"], {"generator": name, "rows": spec["count"]}, None)
    add("weather", read_window(root, window), config["window_eps"], {"window": window}, None)
    for spec in config["alternate_geometry"]:
        add(spec["id"], fixture("piecewise", spec["count"]), spec["eps"],
            {"generator": "piecewise", "rows": spec["count"]}, spec["geometry"])
    require(replay_names <= raw.keys() and len(inputs) == 7, "PBEPLA input closure differs")
    sixteen = next(s for s in inputs if s['name']=='sixteen-layers')['requested_eps']
    count, rem = divmod(method['value_layer_budget'],len(sixteen))
    require(len(sixteen)==16 and rem==0 and count==131072,'PBEPLA budget boundary differs')
    boundary = [{'name':f'budget-{side}', 'count':n, 'requested_eps':sixteen, 'expected_flags':1,
                 'expected_delay':method['max_delay'],'geometry':None,'input_sha256':sha256(boundary_source(n)).hexdigest(),
                 'schema_sha256':sha256(schema_bytes(f'budget-{side}')).hexdigest(), 'frame':f'pbepla-budget-{side}.bmk'}
                for side,n in [('at',count),('over',count+1)]]
    failures = {'boundary': boundary, 'work_limit': method['value_layer_budget'], 'options': list(REJECT_OPTIONS),
                'reject_dtype':9, 'nonfinite_u64':[0x7ff8000000000042,0x7ff0000000000000,0xfff0000000000000],
                'fault_input':'piecewise','fault_modes':config['replay']['faults'],
                'restored':'pbepla-budget-at.f64le','partial':'pbepla-sink-fail.pbep'}
    require(failures['fault_modes']==['changed','no-rewind','sink-fail','value-limit'],'unexpected PBEPLA failure matrix')
    failures['retained'] = [s['frame'] for s in boundary] + [failures['restored'],failures['partial']]
    for route,check in [('pbepla-progressive','decreasing_eps_and_work_bound'),('pbepla-progressive','reject_bad_layers_and_nonfinite'),
                        ('pbepla-replay','changed_source_rewind_and_sink_failures')]:
        row = {'name':f'pbepla-{check}','selection':87,'route':route,'check':check,'policy_id':content_id(failures),
               'validator':'pbepla-negative-and-boundary-v1'}
        cases.append({**row,'case_id':content_id(row)})
    bundle = {"config_id": content_id(config), "config_schema_id": schema.document_id, "test": PROBE,
              "evidence_path": EVIDENCE, "method": method, "retention": config["retention"],
              "replay_policy": config["replay"]["accounting"], "inputs": inputs, "cases": cases, "failure_policy":failures}
    return {**bundle, "bundle_id": content_id(bundle)}, config, raw
