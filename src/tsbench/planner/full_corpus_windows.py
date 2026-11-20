"""Manifest-selected held-out projections for the reusable M1/M2 input path."""
from hashlib import sha256
from pathlib import Path

from ..assets import content_id, require
from ..corpus_ingress import load_full_manifest, read_batches

SCHEMA = 'bmk.full-corpus-heldout-column/1'
MAX_VALUES = 8192


def bind_full_column(root: Path, manifest: str, *, dataset: str, column: str, offset: int, count: int) -> tuple[dict, bytes]:
    """Freeze one value slice, verifying the complete source identity before returning bytes.

    This is a projection, not a claim that the complete file has been handed to
    the codec. T is never substituted for a V column, and no dtype conversion
    or implicit partition choice is made on behalf of the caller.
    """
    require(type(dataset) is str and type(column) is str, 'dataset and value column must be names')
    require(type(offset) is int and type(count) is int and 0 <= offset and 1 <= count <= MAX_VALUES,
            'invalid held-out value window extent')
    corpus = load_full_manifest(root, manifest)
    found = next((entry for entry in corpus['datasets'] if entry['id'] == dataset), None)
    require(found is not None, f'unknown full-corpus dataset: {dataset}')
    columns = found['columns'][1:]
    require(column in columns, f'not a declared binary64 value column: {column}')
    col = columns.index(column)
    heldout = next(partition for partition in found['partitions'] if partition['name'] == 'test')
    first, end = heldout['start'] + offset, heldout['start'] + offset + count
    require(end <= heldout['end'], 'value projection crosses the frozen test partition')
    raw = bytearray()
    stride = 8 * len(columns)
    for batch in read_batches(root, found):
        lo = max(first, batch.start) - batch.start
        hi = min(end, batch.start + batch.rows) - batch.start
        for index in range(lo, hi):
            at = index * stride + 8 * col
            raw.extend(batch.values[at:at + 8])
    require(len(raw) == 8 * count, 'incomplete held-out projection')
    binding = {'schema': SCHEMA, 'manifest': manifest, 'manifest_id': content_id(corpus), 'dataset': dataset,
               'source_cluster': found['source_cluster'], 'source_file': found['file'],
               'full_canonical_id': found['canonical']['object_id'], 'partition': 'test',
               'partition_canonical_id': heldout['canonical']['object_id'],
               'column': column, 'physical_column_index': col + 1, 'offset': offset, 'count': count,
               'absolute_row_range': [first, end], 'dtype': '<f8', 'bytes': len(raw), 'raw_sha256': sha256(raw).hexdigest(),
               'scope': 'one_value_column_slice_not_full_source'}
    return {**binding, 'input_id': content_id(binding)}, bytes(raw)


def read_full_column(root: Path, binding: dict) -> bytes:
    """Revalidate a frozen window; swapped columns, paths, bytes or bounds fail closed."""
    require(isinstance(binding, dict) and binding.get('schema') == SCHEMA, 'not a frozen held-out column binding')
    expected, raw = bind_full_column(root, binding['manifest'], dataset=binding['dataset'], column=binding['column'],
                                     offset=binding['offset'], count=binding['count'])
    require(expected == binding, 'held-out projection no longer matches the frozen binding')
    return raw
