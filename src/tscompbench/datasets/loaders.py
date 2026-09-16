from __future__ import annotations

import calendar
import csv
import platform
from datetime import datetime
from typing import Any

import numpy as np

from .models import (
    CanonicalDataset,
    DatasetContractError,
    DatasetManifest,
    ValueBuffer,
    immutable,
)
from .registry import sha256_file


def _resolve_value_columns(header: list[str], value_spec: dict[str, Any]) -> list[dict[str, str]]:
    selection = value_spec["column_selection"]
    if selection["kind"] != "ALL_EXCEPT":
        raise DatasetContractError("unsupported CSV value column selection")
    excluded = set(selection["excluded"])
    names = [name for name in header if name not in excluded]
    expected_count = selection.get("expected_count")
    if expected_count is not None and len(names) != expected_count:
        raise DatasetContractError(
            f"resolved {len(names)} value columns, expected {expected_count}"
        )
    default = value_spec["default_column"]
    overrides = value_spec.get("overrides", {})
    display_overrides = value_spec.get("display_name_overrides", {})
    columns: list[dict[str, str]] = []
    for name in names:
        merged = dict(default)
        merged.update(overrides.get(name, {}))
        entity = name if merged.get("entity") == "$HEADER" else merged["entity"]
        feature = name if merged.get("feature") == "$HEADER" else merged["feature"]
        columns.append(
            {
                "name": name,
                "display_name": display_overrides.get(name, name),
                "dtype": merged["dtype"],
                "unit": merged["unit"],
                "entity": entity,
                "feature": feature,
            }
        )
    return columns


def _parse_timestamp(token: str, spec: dict[str, Any]) -> int:
    parsed: datetime | None = None
    for date_format in spec["formats"]:
        try:
            parsed = datetime.strptime(token, date_format)
            break
        except ValueError:
            continue
    if parsed is None:
        raise DatasetContractError(f"timestamp does not match declared formats: {token!r}")
    if spec["timezone_interpretation"] != "NAIVE_AS_UTC":
        raise DatasetContractError("unsupported timestamp timezone interpretation")
    seconds = calendar.timegm(parsed.timetuple())
    if spec["unit"] == "s":
        return seconds
    if spec["unit"] == "ms":
        return seconds * 1_000 + parsed.microsecond // 1_000
    if spec["unit"] == "us":
        return seconds * 1_000_000 + parsed.microsecond
    if spec["unit"] == "ns":
        return seconds * 1_000_000_000 + parsed.microsecond * 1_000
    raise DatasetContractError(f"unsupported timestamp unit: {spec['unit']}")


def _parse_number(token: str, dtype: np.dtype[Any], *, row: int, column: str) -> Any:
    if token == "":
        raise DatasetContractError(f"undeclared missing value at row {row}, column {column}")
    try:
        if np.issubdtype(dtype, np.integer):
            value = int(token, 10)
            bounds = np.iinfo(dtype)
            if value < bounds.min or value > bounds.max:
                raise DatasetContractError(
                    f"integer overflow at row {row}, column {column}: {value}"
                )
            return value
        if np.issubdtype(dtype, np.floating):
            return float(token)
    except ValueError as error:
        raise DatasetContractError(
            f"invalid {dtype.str} value at row {row}, column {column}: {token!r}"
        ) from error
    raise DatasetContractError(f"unsupported value dtype: {dtype.str}")


def _validate_timestamp_semantics(timestamp: np.ndarray[Any], spec: dict[str, Any]) -> None:
    if timestamp.size < 2:
        return
    previous = int(timestamp[0])
    duplicate = False
    out_of_order = False
    for value in timestamp[1:]:
        current = int(value)
        duplicate |= current == previous
        out_of_order |= current < previous
        previous = current
    if duplicate and not spec["allow_duplicates"]:
        raise DatasetContractError("source contains duplicate timestamps forbidden by manifest")
    if out_of_order and not spec["allow_out_of_order"]:
        raise DatasetContractError("source contains out-of-order timestamps forbidden by manifest")


def _load_csv(manifest: DatasetManifest) -> CanonicalDataset:
    document = manifest.document
    parser = document["parser"]
    expected = document["expected"]
    timestamp_spec = document["logical"]["timestamp"]
    with manifest.source_path.open(
        "r", encoding=parser["encoding"], errors=parser["encoding_errors"], newline=""
    ) as handle:
        reader = csv.reader(handle, delimiter=parser["delimiter"], strict=True)
        try:
            header = next(reader)
        except StopIteration as error:
            raise DatasetContractError("CSV is empty") from error
        if len(header) != expected["columns"]:
            raise DatasetContractError(
                f"CSV header has {len(header)} columns, expected {expected['columns']}"
            )
        if len(set(header)) != len(header):
            raise DatasetContractError("CSV header contains duplicate names")
        timestamp_column = timestamp_spec["column"]
        if timestamp_column not in header:
            raise DatasetContractError(f"timestamp column is missing: {timestamp_column}")
        timestamp_index = header.index(timestamp_column)
        column_specs = _resolve_value_columns(header, document["logical"]["value"])
        column_indices = [header.index(spec["name"]) for spec in column_specs]
        dtypes = [np.dtype(spec["dtype"]) for spec in column_specs]
        if any(dtype.byteorder not in {"<", "=", "|"} for dtype in dtypes):
            raise DatasetContractError("canonical value dtype must be little-endian")

        row_count = expected["rows"]
        timestamp = np.empty(row_count, dtype="<i8")
        arrays = [np.empty(row_count, dtype=dtype) for dtype in dtypes]
        seen_rows = 0
        for csv_row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise DatasetContractError(
                    f"row {csv_row_number} has {len(row)} fields, expected {len(header)}"
                )
            if seen_rows >= row_count:
                raise DatasetContractError(f"CSV has more than expected {row_count} data rows")
            timestamp[seen_rows] = _parse_timestamp(row[timestamp_index], timestamp_spec)
            for array, dtype, index, spec in zip(
                arrays, dtypes, column_indices, column_specs, strict=True
            ):
                array[seen_rows] = _parse_number(
                    row[index], dtype, row=csv_row_number, column=spec["name"]
                )
            seen_rows += 1
    if seen_rows != row_count:
        raise DatasetContractError(f"CSV has {seen_rows} rows, expected {row_count}")
    _validate_timestamp_semantics(timestamp, timestamp_spec)
    immutable(timestamp)

    value_buffers: list[ValueBuffer] = []
    for spec, array in zip(column_specs, arrays, strict=True):
        immutable(array)
        value_buffers.append(
            ValueBuffer(
                name=spec["name"],
                display_name=spec["display_name"],
                array=array,
                unit=spec["unit"],
                entity=spec["entity"],
                feature=spec["feature"],
            )
        )

    logical_descriptor = {
        "schema_version": "tscb.logical-view.v2",
        "topology": document["logical"]["topology"],
        "axes": document["logical"]["axes"],
        "n_rows": row_count,
        "timestamp": {
            "present": True,
            "origin": timestamp_spec["origin"],
            "dtype": timestamp.dtype.str,
            "unit": timestamp_spec["unit"],
            "epoch": timestamp_spec["epoch"],
            "order_policy": timestamp_spec["order_policy"],
        },
        "value_shape": [row_count, len(value_buffers)],
        "value_columns": [item.descriptor() for item in value_buffers],
        "validity_shape": document["logical"]["validity"]["shape"],
        "nan_is_null": document["logical"]["validity"]["nan_is_null"],
    }
    physical_descriptors = (
        {
            "view_id": "timestamp-le-i64",
            "layout": "ROW_MAJOR_CONTIG",
            "dtype": timestamp.dtype.str,
            "shape": [row_count],
            "strides": list(timestamp.strides),
            "endianness": "little",
        },
        {
            "view_id": "value-soa-columns",
            "layout": "SOA_COLUMNS",
            "dtype_vector": [item.array.dtype.str for item in value_buffers],
            "shape": [row_count, len(value_buffers)],
            "endianness": "little",
        },
    )
    return CanonicalDataset(
        manifest=manifest,
        timestamp=timestamp,
        values=tuple(value_buffers),
        validity=None,
        logical_descriptor=logical_descriptor,
        physical_descriptors=physical_descriptors,
        loader_provenance={
            "loader": "tscompbench.datasets.loaders._load_csv",
            "python": platform.python_version(),
            "csv_module": "python-stdlib",
            "numeric_parse": "python-int-or-float-to-declared-numpy-dtype",
            "source_sha256": document["file"]["sha256"],
            "hidden_transforms": [],
        },
    )


def _load_npz(manifest: DatasetManifest) -> CanonicalDataset:
    document = manifest.document
    parser = document["parser"]
    expected = document["expected"]
    array_key = parser["array_key"]
    with np.load(manifest.source_path, allow_pickle=False) as archive:
        if sorted(archive.files) != sorted(parser["expected_keys"]):
            raise DatasetContractError(
                f"NPZ keys {sorted(archive.files)} do not match {sorted(parser['expected_keys'])}"
            )
        source = archive[array_key]
        if list(source.shape) != expected["shape"]:
            raise DatasetContractError(
                f"NPZ shape {list(source.shape)} does not match {expected['shape']}"
            )
        expected_dtype = np.dtype(document["logical"]["value"]["array"]["dtype"])
        if source.dtype != expected_dtype:
            raise DatasetContractError(
                f"NPZ dtype {source.dtype.str} does not match declared {expected_dtype.str}"
            )
        if document["logical"]["value"]["array"]["required_layout"] == "ROW_MAJOR_CONTIG":
            if not source.flags.c_contiguous:
                raise DatasetContractError("NPZ value array is not declared C-contiguous layout")
        values = source.copy(order="C")
    immutable(values)
    value_spec = document["logical"]["value"]["array"]
    buffer = ValueBuffer(
        name=array_key,
        display_name=document["display_name"],
        array=values,
        unit=value_spec["unit"],
        entity=value_spec["entity"],
        feature=value_spec["feature"],
    )
    logical_descriptor = {
        "schema_version": "tscb.logical-view.v2",
        "topology": document["logical"]["topology"],
        "axes": document["logical"]["axes"],
        "n_rows": int(values.shape[0]),
        "timestamp": {
            "present": False,
            "origin": document["logical"]["timestamp"]["origin"],
        },
        "value_shape": list(values.shape),
        "value_columns": [buffer.descriptor()],
        "validity_shape": document["logical"]["validity"]["shape"],
        "nan_is_null": document["logical"]["validity"]["nan_is_null"],
    }
    physical_descriptors = (
        {
            "view_id": "value-native-nd-c-order",
            "layout": "ROW_MAJOR_CONTIG",
            "dtype": values.dtype.str,
            "shape": list(values.shape),
            "strides": list(values.strides),
            "endianness": "little",
        },
    )
    return CanonicalDataset(
        manifest=manifest,
        timestamp=None,
        values=(buffer,),
        validity=None,
        logical_descriptor=logical_descriptor,
        physical_descriptors=physical_descriptors,
        loader_provenance={
            "loader": "tscompbench.datasets.loaders._load_npz",
            "python": platform.python_version(),
            "numpy": np.__version__,
            "allow_pickle": False,
            "source_sha256": document["file"]["sha256"],
            "timestamp_synthesized": False,
            "reshape_performed": False,
            "hidden_transforms": [],
        },
    )


def load_dataset(manifest: DatasetManifest) -> CanonicalDataset:
    source_hash_before = sha256_file(manifest.source_path)
    file_format = manifest.document["file"]["format"]
    if file_format == "csv":
        dataset = _load_csv(manifest)
    elif file_format == "npz":
        dataset = _load_npz(manifest)
    else:
        raise DatasetContractError(f"unsupported source format: {file_format}")
    source_hash_after = sha256_file(manifest.source_path)
    if source_hash_before != source_hash_after:
        raise DatasetContractError("loader modified the source dataset")
    return dataset
