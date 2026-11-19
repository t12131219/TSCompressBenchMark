"""One frozen Titchy backing and three distinct access checks, development only."""
from hashlib import sha256
from pathlib import Path
import struct

from ..assets import content_id, load_json, local_file, require
from .corpus_windows import bind_window, read_tv_window

CONFIG = "configs/suites/dev_titchy_v1/cases.json"
PROBE = "tsbench.worker.titchy.recovery"
EVIDENCE = "titchy-control.json"
BACKING = "access.tchy"
TRANSFORM = "canonical_f64_to_u64_bitcast_le_inverse_v1"
VALIDATOR = "native_read_at_boundaries_and_file_bits_v2"
SCOPE = "bytes_requested_at_memory_callback_including_repeated_offsets_not_physical_io"


def expected_queries(values, request: dict) -> dict:
    start, count = request["range"]
    return {"point": values[request["point"]], "range": list(values[start:start + count]),
            "bits": [(values[i // 64] >> (63 - i % 64)) & 1 for i in request["bits"]]}


def logical_result_bits(request: dict) -> dict[str, int]:
    return {"point": 64, "range": 64 * request["range"][1], **{f"bit-{i}": 1 for i in request["bits"]}}


def plan_titchy_access(root: Path) -> tuple[dict, dict, bytes]:
    cfg = load_json(local_file(root, CONFIG))
    require(isinstance(cfg, dict) and cfg.keys() == {"schema", "selection", "corpus", "corpus_id", "window",
                                                     "transform", "batch", "stream", "reader"} and cfg.get("schema") == "bmk.dev-titchy-cases/2" and cfg.get("selection") == 85 and
            cfg.get("transform") == TRANSFORM, "invalid Titchy access config identity")
    reader = cfg.get("reader")
    require(isinstance(reader, dict) and reader.keys() == {"point", "range", "bits", "validator", "policy"} and
            reader["validator"] == VALIDATOR, "invalid Titchy access validator or request")
    request = {k: reader[k] for k in ("point", "range", "bits")}
    window = bind_window(root, cfg["corpus"], cfg["corpus_id"], cfg["window"])
    n = window["count"]
    point, span, bits = (request[k] for k in ("point", "range", "bits"))
    require(type(point) is int and 0 <= point < n and isinstance(span, list) and len(span) == 2 and
            all(type(v) is int for v in span) and 0 <= span[0] < n and 0 < span[1] <= n - span[0] and
            isinstance(bits, list) and 0 < len(bits) <= 16 and all(type(i) is int and 0 <= i < 64 * n for i in bits) and
            len(set(bits)) == len(bits), "Titchy access requests outside frozen input")
    policy = reader["policy"]
    require(isinstance(policy, dict) and policy.keys() == {"max_backing_bytes", "open", "point", "range", "bit"} and
            all(type(v) is int and 0 < v <= (128 << 10) for v in policy.values()) and
            all(policy[k] < policy["max_backing_bytes"] for k in ("open", "point", "range", "bit")),
            "invalid Titchy logical-read budget")
    _, source = read_tv_window(root, window)
    values = tuple(v for (v,) in struct.iter_unpack("<Q", source))
    expected = expected_queries(values, request)
    common = {"window": window, "input_sha256": sha256(source).hexdigest(), "input_bytes": len(source),
              "transform": TRANSFORM, "validator": VALIDATOR}
    cases = []
    for name, route, check, criteria in (
        ("titchy-loaded-query-oracle", "loaded-file-access", "point_bit_range_oracle",
         {"request": request, "expected": expected}),
        ("titchy-loaded-logical-reads", "loaded-file-access", "log_open_and_request_bytes",
         {"request": request, "byte_limits": policy, "scope": SCOPE, "request_passes": 2}),
        ("titchy-stateless-range-oracle", "batch-range", "range_original_slice",
         {"range": span, "expected": expected["range"]}),
    ):
        case = {**common, "selection": 85, "route": route, "check": check, "name": name, "criteria": criteria}
        cases.append({**case, "case_id": content_id(case)})
    bundle = {"config_id": content_id(cfg), "test": PROBE, "evidence_path": EVIDENCE, "backing_path": BACKING,
              "cases": cases}
    return {**bundle, "bundle_id": content_id(bundle)}, cfg, source
