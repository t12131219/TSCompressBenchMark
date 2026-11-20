"""Bounded ingress and ZDG1 validation for the r40 Zstd dictionary work.

The controller sees the original to verify provenance. The trainer is a separate
process and must receive only the staged prefix, not the source or the holdout.
ZDG1 is harness framing, not native Zstd bytes; the dictionary is an external
recovery dependency counted once per complete held-out archive.
"""
from contextlib import ExitStack
from hashlib import sha256

from ..assets import require
from ..corpus_ingress import read_batches
from ..planner.m3_zstd_dictionary import LIMIT, extents
from ..qualification.lzbench import zstd_frame
from ..qualification.zstd_dictionary_grouped_wire import FRAME, HEAD, MAGIC, MAX_WIRE


def stage_inputs(root, item, entry, work, evidence, *, roles=('train', 'holdout')):
    """Stage requested immutable views, in one bounded parser pass in the controller."""
    require(roles and len(set(roles)) == len(roles) and set(roles) <= {'train', 'holdout'},
            'invalid dictionary staging roles')
    spans, _, _ = extents(item, entry)
    wanted = {
        'train': {'bytes': spans[0][1] - spans[0][0], 'sha256': evidence['train_prefix_sha256']},
        'holdout': evidence['holdout'],
    }
    require(wanted['holdout'] == {'bytes': spans[1][1] - spans[1][0],
                                   'sha256': entry['partitions'][2]['canonical']['values_sha256']},
            'dictionary held-out identity disagrees with the manifest')
    scope = dict(zip(('train', 'holdout'), spans, strict=True))
    width = entry['value_count'] * 8
    staged = {}
    try:
        with ExitStack() as stack:
            sinks, totals, digests = {}, dict.fromkeys(roles, 0), {k: sha256() for k in roles}
            for role in roles:
                path = work / f'{role}.bin'
                sinks[role] = stack.enter_context(path.open('xb'))
                staged[role] = path
            for batch in read_batches(root, entry):
                start = batch.start * width
                end = start + len(batch.values)
                for role, out in sinks.items():
                    lo, hi = scope[role]
                    if start < hi and lo < end:
                        portion = memoryview(batch.values)[max(lo, start)-start:min(hi, end)-start]
                        totals[role] += out.write(portion)
                        digests[role].update(portion)
        require(all({'bytes': totals[k], 'sha256': digests[k].hexdigest()} == wanted[k] for k in roles),
                'staged dictionary input differs from r40 evidence')
    except BaseException:
        for path in staged.values():
            path.unlink(missing_ok=True)
        raise
    return staged


def inspect_archive(path, evidence):
    """Require ordered single native frames, exact extents, and r40 per-frame identities."""
    frames, dictionary = evidence['frames'], evidence['dictionary']
    logical = evidence['holdout']['bytes']
    count = (logical + LIMIT - 1) // LIMIT
    require(logical > 0 and len(frames) == count, 'dictionary held-out denominator differs')
    wire_bytes, cursor = 0, 0
    archive_hash = sha256()
    with path.open('rb') as stream:
        def take(n):
            data = stream.read(n)
            require(len(data) == n, 'truncated ZDG1 archive')
            archive_hash.update(data)
            return data

        require(HEAD.unpack(take(HEAD.size)) == (MAGIC, count), 'ZDG1 header or frame count differs')
        for i, row in enumerate(frames):
            n, wire = FRAME.unpack(take(FRAME.size))
            require(n == min(LIMIT, logical - cursor) and 0 < wire <= MAX_WIRE and
                    row['index'] == i and row['holdout_byte_range'] == [cursor, cursor + n] and
                    row['logical_bytes'] == n and row['bytes'] == wire and row['status'] == 'verified',
                    'ZDG1 frame geometry differs from r40')
            data = take(wire)
            hdr = zstd_frame(data)
            require(sha256(data).hexdigest() == row['sha256'] and
                    hdr['dictionary_id'] == row['dictionary_id'] == dictionary['id'] and
                    hdr['content_size'] in (None, n) and not hdr['checksum'], 'ZDG1 native frame differs from r40')
            wire_bytes += wire
            cursor += n
        require(stream.read(1) == b'', 'trailing data after ZDG1 archive')
    wrapper = HEAD.size + FRAME.size * count
    require(cursor == logical and evidence['verified_frame_bytes'] == wire_bytes and
            evidence['verified_frame_bytes_plus_shared_dictionary_once'] == wire_bytes + dictionary['bytes'],
            'r40 dictionary artifact accounting differs')
    return {'bytes': wire_bytes + wrapper, 'sha256': archive_hash.hexdigest(), 'native_frames': count,
            'native_frame_bytes': wire_bytes, 'wrapper_bytes': wrapper, 'dictionary_bytes': dictionary['bytes'],
            'recovery_bytes': wire_bytes + wrapper + dictionary['bytes']}
