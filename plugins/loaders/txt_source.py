"""Explicit delimited or fixed-width text; never guess from the suffix."""
from tsbench.assets import require
from tsbench.ingress import names, text_probe, text_rows


def probe_source(assets, spec, options):
    return text_probe(assets)


def resolve_schema(handle, spec, options):
    if options['mode']=='fixed_width':
        require(len(options['widths'])==len(names(spec)), 'fixed-width field count differs from schema')
    return spec


def read_batches(handle, spec, options, batch_rows):
    def fields(line):
        if options['mode']=='delimited':
            return line.split(options['delimiter'])
        require(line.isascii() and len(line)==sum(options['widths']), 'invalid fixed-width record')
        offset, result = 0, []
        for width in options['widths']:
            result.append(line[offset:offset+width].strip(' '))
            offset += width
        return result
    return text_rows(handle,spec,options,fields,batch_rows)


def close(handle):
    pass
