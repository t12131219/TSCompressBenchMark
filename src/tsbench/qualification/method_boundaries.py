"""Validate the case-level development report against a sealed plan and frames."""
from pathlib import Path

from ..assets import canonical_bytes, content_id, load_json, local_file, require, verify_asset


def binding_build_inputs(document: dict, slot: dict) -> dict[str, str]:
    files = [document["bindings"]["command_inputs"][i["asset"]] for i in slot["command"] if "asset" in i]
    native = [ref for ref in files if ref["root"] == "build"]
    by_name = {Path(ref["path"]).name: ref["sha256"] for ref in native}
    require(len(by_name) == len(native) and by_name, "invalid native probe build inputs")
    return by_name


def verify_boundary_evidence(bundle: dict, build: dict, out: Path, *, sealed_paths: set[str] | None = None) -> None:
    require(bundle["bundle_id"] == content_id({k: v for k, v in bundle.items() if k != "bundle_id"}),
            "method-boundary bundle identity differs")
    report = load_json(local_file(out, bundle["evidence_path"]))
    require(isinstance(report, dict) and report.keys() == {"schema", "config_id", "bundle_id", "build_sha256",
                "formal_qualification", "formal_performance", "rows"} and
            report["schema"] == "bmk.m0-method-boundary-report/2" and report["config_id"] == bundle["config_id"] and
            report["bundle_id"] == bundle["bundle_id"] and report["build_sha256"] == build and
            report["formal_qualification"] is False and report["formal_performance"] is False,
            "method-boundary report is not bound to input/configuration/build")
    rows = report["rows"]
    require(isinstance(rows, list) and len(rows) == len(bundle["cases"]), "method-boundary result closure differs")
    directory = Path(bundle["evidence_path"]).parent.as_posix()
    expected_frames = set()
    for row, case in zip(rows, bundle["cases"], strict=True):
        base = case["row"]
        label = base["case"]
        require(isinstance(row, dict) and case["case_id"] == row.get("case_id") and
                all(k in row and canonical_bytes(row[k]) == canonical_bytes(v) for k, v in base.items()),
                f"method-boundary case result differs from frozen input: {label}")
        require(row.get("actual") == base["expected"], f"unexpected method-boundary outcome: {label}")
        common = base.keys() | {"case_id", "actual", "encode_exit", "artifact"}
        if base["expected"] == "resource_limit_7":
            require(row.keys() == common | {"diagnostic"} and row["artifact"] is None and
                    type(row["encode_exit"]) is int and row["encode_exit"] == 3 and
                    isinstance(row["diagnostic"], str) and row["diagnostic"].startswith("plugin status 7:") and
                    not (out / directory / (label + ".bmk")).exists(), f"invalid expected resource refusal: {label}")
            continue
        vectors = case["expected_aln1_vectors"]
        require(row.keys() == common | {"encode_info", "decode_info", "restored"} | ({"aln1"} if vectors is not None else set()) and
                type(row["encode_exit"]) is int and row["encode_exit"] == 0, f"invalid restored result: {label}")
        for op in ("encode", "decode"):
            info = row[op + "_info"]
            require(isinstance(info, dict) and info.get("operation") == op and info.get("mode") == "batch" and
                    type(info.get("threads")) is int and info["threads"] == case["threads"] and
                    info.get("backend") == case["expected_" + op + "_backend"], f"unexpected {op} path: {label}")
        types = [{"dtype": dtype, "count": base["rows"]} for dtype in case["abi_types"]]
        require(canonical_bytes(row["restored"]) == canonical_bytes({
            "descriptor": types[0] if len(types) == 1 else {"columns": types},
            "schema_sha256": base["schema_sha256"], "columns_sha256": base["input_column_sha256"],
        }), f"restored data evidence differs from original-domain lock: {label}")
        if vectors is not None:
            layout = row["aln1"]
            require(isinstance(layout, dict) and all(type(layout.get(k)) is int and layout[k] >= 0 for k in ("raw_vectors", "coded_vectors"))
                    and layout["raw_vectors"] + layout["coded_vectors"] == vectors,
                    f"wrong observed ALN1 vector count: {label}")
        frame = row["artifact"]
        require(isinstance(frame, dict) and frame.keys() == {"path", "bytes", "sha256"} and
                frame["path"] == case["artifact_basename"] and type(frame["bytes"]) is int and
                0 < frame["bytes"] <= bundle["case_policy"]["max_frame_bytes"], f"invalid frame reference: {label}")
        relative = f"{directory}/{frame['path']}"
        expected_frames.add(relative)
        file = verify_asset(out, {**frame, "path": relative})
        require(file.stat().st_size == frame["bytes"], f"frame byte ledger differs: {label}")
    found = {f"{directory}/{p.name}" for p in (out / directory).glob("*.bmk")}
    require(found == expected_frames and (sealed_paths is None or expected_frames <= sealed_paths),
            "method-boundary frame denominator differs from frozen cases")
