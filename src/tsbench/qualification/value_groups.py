"""Additional archived-payload diagnostics, keyed by codec format, not routing."""
from . import sprintz

_AUDITORS = {'sprintz-fire.u16-group-envelope.v1': (sprintz.inspect_u16_group,sprintz.check_group_execution)}


def inspect_group(format_id, payload, rows, dims, schema, expected_crc):
    auditor = _AUDITORS.get(format_id)
    return auditor[0](payload,rows,dims,schema,expected_crc) if auditor else {}


def check_execution(format_id, facts, direction, dims):
    if auditor := _AUDITORS.get(format_id):
        auditor[1](facts,direction,dims)
