"""Strict single-line CSV; options are validated before entry."""
import csv
from tsbench.assets import ContractError, require
from tsbench.ingress import text_probe, text_rows


def probe_source(assets, spec, options):
    return text_probe(assets)


def resolve_schema(handle, spec, options):
    return spec


def read_batches(handle, spec, options, batch_rows):
    def fields(line):
        require(len(line)<=4096,'oversized CSV record')
        try:
            return next(csv.reader([line], delimiter=options['delimiter'], quotechar=options['quote'], doublequote=True, strict=True))
        except csv.Error as exc:
            raise ContractError('invalid CSV quoting') from exc
    return text_rows(handle,spec,options,fields,batch_rows)


def close(handle):
    pass  # immutable in-memory snapshot; no open files
