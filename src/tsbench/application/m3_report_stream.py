"""Read the native corpus executor's indent-2 report one decision at a time."""
from contextlib import contextmanager

from ..assets import parse_json, require

# This is the executor's own on-disk representation, not a generic JSON
# reader. Escaped line breaks in string values cannot match these boundaries.
SECTION = b'  "rows": [\n'
OUTER_LIMIT = 128 << 20


def _line(stream):
    text = stream.readline(OUTER_LIMIT + 1)
    require(len(text) <= OUTER_LIMIT and text.endswith(b'\n'), 'incomplete M3 report line')
    return text


def _metadata(data):
    ending = b',\n' if data.endswith(b',\n') else b'\n'
    return parse_json(b'{\n'+data.removesuffix(ending)+b'\n}', 'M3 report metadata')


def _append(buf, text):
    require(len(buf)+len(text)<=OUTER_LIMIT, 'M3 report row or metadata exceeds streaming audit limit')
    buf.extend(text)


@contextmanager
def stream_report(path):
    """Yield metadata and an iterator of complete dicts; finish before publishing.

    Metadata written after the row array is added on iterator exhaustion. The
    caller still verifies the seal and the report-to-ledger equality itself.
    """
    with path.open('rb') as stream:
        require(_line(stream)==b'{\n','M3 report is not in the executor format')
        prefix = bytearray()
        while (line := _line(stream)) != SECTION:
            require(line!=b'}\n','M3 report has no decision array')
            _append(prefix,line)
        require(not prefix or prefix.endswith(b',\n'),'M3 report metadata lacks decision separator')
        metadata = _metadata(bytes(prefix))
        require('rows' not in metadata,'M3 report repeats its decision array')
        finished = False

        def rows():
            nonlocal finished
            while True:
                start = _line(stream)
                require(start==b'    {\n','M3 report has a missing or non-object decision')
                row = bytearray(start)
                while (end := _line(stream)) not in (b'    },\n',b'    }\n'):
                    _append(row,end)
                _append(row,b'    }\n')
                yield parse_json(bytes(row),'M3 report decision')
                if end==b'    }\n':
                    break
            delimiter = _line(stream)
            require(delimiter in (b'  ],\n',b'  ]\n'),'M3 report decision array did not close')
            tail = bytearray()
            while (line := _line(stream))!=b'}\n':
                _append(tail,line)
            require(bool(tail)==(delimiter==b'  ],\n') and not tail.endswith(b',\n') and not stream.read(1),
                    'M3 report has invalid trailing metadata')
            extra = _metadata(bytes(tail))
            require('rows' not in extra and not metadata.keys()&extra.keys(),'M3 report repeats a metadata field')
            metadata.update(extra)
            finished = True

        yield metadata, rows()
        require(finished,'M3 report decisions were not fully read')
