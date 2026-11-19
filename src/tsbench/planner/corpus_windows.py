"""Read partition-bounded windows from a frozen corpus lock."""
from pathlib import Path
import gzip
import struct
import zlib

from ..assets import ContractError, content_id, load_json, local_file, require, verify_asset
from ..corpus import PROFILES, TIME, TIME_AXES, _row, f64, time_coordinate


def bind_window(root: Path, manifest: str, corpus_id: str, request: dict) -> dict:
    require(request["partition"] == "test", "only frozen held-out windows may enter M1")
    return _bind_window(root, manifest, corpus_id, request)


def bind_service_window(root: Path, manifest: str, corpus_id: str, request: dict) -> dict:
    """Bind an explicitly partitioned service input, including offline development."""
    require(request.get("partition") in {"train", "development", "test"}, "invalid service window partition")
    return _bind_window(root, manifest, corpus_id, request)


def bind_training_window(root: Path, manifest: str, corpus_id: str, request: dict) -> dict:
    """Opt in to training explicitly; M1 and evaluation still use bind_window."""
    require(request["partition"] == "train", "training requires a frozen train partition")
    return _bind_window(root, manifest, corpus_id, request)


def read_held_out_boundary_window(root: Path, manifest: str, corpus_id: str, request: dict) -> tuple[dict, bytes, bytes]:
    """A bounded extra row for existing civil-second M0 rejection tests, not M1."""
    require(request["partition"] == "test", "boundary probe requires a held-out partition")
    bound = _bind_window(root, manifest, corpus_id, request, max_count=8193)
    require(bound["profile"] not in TIME_AXES, "boundary probe expects a civil-second coordinate")
    timestamps, values = _read_window(root, bound, include_time=True, max_count=8193)
    return bound, timestamps, values


def _bind_window(root: Path, manifest: str, corpus_id: str, request: dict, *, max_count: int = 8192) -> dict:
    doc = load_json(local_file(root, manifest))
    require(content_id(doc) == corpus_id, "real corpus identity changed while binding windows")
    found = [d for d in doc["datasets"] if d["id"] == request["dataset"]]
    require(len(found) == 1, f"unknown corpus dataset: {request['dataset']}")
    dataset = found[0]
    partition = request["partition"]
    locked_part = dataset["audit"]["partitions"][partition]
    offset, count = request["offset"], request["count"]
    require(type(offset) is int and type(count) is int and 0 <= offset and 1 <= count <= max_count and
            offset + count <= locked_part["rows"], "window crosses its frozen partition or input bound")
    columns = {name for name, _ in PROFILES[dataset["header_profile"]][0]}
    require(request["column"] in columns, f"unknown corpus column: {request['column']}")
    bounds = ({"partition_end": dataset["split_at"][0]} if partition == "train"
              else {"partition_start": dataset["split_at"][-1]})
    if partition == "development":
        bounds = {"partition_start": dataset["split_at"][0], "partition_end": dataset["split_at"][1]}
    profile = dataset["header_profile"]
    return {**request, "asset": dataset["asset"], "profile": profile,
            **({"time_axis": TIME_AXES[profile]} if profile in TIME_AXES else {}),
            **bounds, "partition_canonical_id": locked_part["canonical_id"],
            "source_cluster": dataset["source_cluster"], "corpus_id": corpus_id}


def read_window(root: Path, ref: dict) -> bytes:
    return _read_window(root, ref, include_time=False)[1]


def read_tv_window(root: Path, ref: dict) -> tuple[bytes, bytes]:
    """Return canonical little-endian i64 seconds and f64 from the same rows."""
    require(ref["profile"] not in TIME_AXES, "not a civil-second window; preserve the source time-axis semantics")
    return _read_window(root, ref, include_time=True)


def read_labeled_tv_window(root: Path, ref: dict) -> tuple[dict, bytes, bytes]:
    """Return time-axis semantics together with the original i64 coordinate and f64 values."""
    axis = TIME_AXES.get(ref["profile"], TIME)
    ticks, values = _read_window(root, ref, include_time=True)
    return dict(axis), ticks, values


def _read_window(root: Path, ref: dict, *, include_time: bool, max_count: int = 8192) -> tuple[bytes, bytes]:
    path = verify_asset(root, ref["asset"])
    require(path.stat().st_size == ref["asset"]["bytes"], "source asset length differs from plan")
    profile = ref["profile"]
    require(ref.get("time_axis") == TIME_AXES.get(profile), "window time-axis binding mismatch")
    columns, sep, decimal_point, max_rows = PROFILES[profile]
    names = ["timestamp", *[name for name, _ in columns]]
    column = names.index(ref["column"])
    # Membership stays chronological for every split; development stops before test.
    lower = time_coordinate(profile, ref["partition_start"]) if ref["partition"] != "train" else None
    upper = time_coordinate(profile, ref["partition_end"]) if ref["partition"] != "test" else None
    offset, count = ref["offset"], ref["count"]
    require(type(offset) is int and type(count) is int and offset >= 0 and 1 <= count <= max_count and column > 0,
            "invalid corpus window request")
    selected = 0
    timestamps, out = bytearray(), bytearray()
    try:
        with gzip.open(path, "rb") as stream:
            require(_row(stream.readline(4097), sep) == names, "source header differs from plan")
            for i in range(max_rows):
                raw = stream.readline(4097)
                if not raw:
                    break
                row = _row(raw, sep)
                require(len(row) == len(names), f"invalid corpus row width at {i + 1}")
                stamp = time_coordinate(profile, row[0])
                if upper is not None and stamp >= upper:
                    break  # the frozen corpus audit forbids backward partition membership
                if lower is not None and stamp < lower:
                    continue
                if selected >= offset:
                    if include_time:
                        timestamps.extend(struct.pack("<q", stamp))
                    out.extend(f64(row[column], decimal_point))
                selected += 1
                if selected == offset + count:
                    break
    except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise ContractError(f"corpus window read failed: {path.name}: {exc}") from exc
    require(len(out) == count * 8, "corpus window length differs from plan")
    return bytes(timestamps), bytes(out)
