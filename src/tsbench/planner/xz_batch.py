"""Materialize the existing XZ baseline cases for product-level execution."""
from ..assets import canonical_bytes, content_id, require
from .gorilla import sha
from .lzbench import BASE_SIZES, plan_lzbench, sample

METHOD = 'xz-baseline'
TOOL = 'xz-baseline-direct'
TARGET = 'tsbench_xz_batch_control'
POLICY = 'configs/suites/m3_first_batch_native_v2/xz-batch-execution.json'
FRAME_PAYLOAD_CAP = 68000
SOURCES = ('plugins/codecs/zstd/xz_batch_control.cpp', 'src/tsbench/planner/xz_batch.py',
           'src/tsbench/qualification/xz_batch.py')


def xz_inputs(root):
    from .batch_execution import BatchInput

    plan = plan_lzbench(root)
    spec, guard = plan['xz_baseline'], plan['xz_guard']
    require((spec['preset'], spec['encoder_threads'], spec['check'], spec['dictionary_property'], spec['decoder_memlimit'])
            == (6, 1, 0, 22, 256 << 20) and
            (guard['dictionary_property'], guard['advertised_dictionary_bytes'], guard['output_bytes']) == (33, 384 << 20, 1),
            'XZ batch native parameters differ')
    schema = canonical_bytes({'column':'bytes','dtype':'u8'})
    products, slots = {}, {}
    for fixture in [*spec['frames'], {'frame':None, 'input':spec['oversize']}]:
        source = fixture['input']
        n = source['bytes']
        original = sample(n, source['salt'])
        require(len(original) == n and sha(original) == source['sha256'] and n not in slots,
                'XZ batch fixture source differs')
        oversized = fixture['frame'] is None
        negatives = [] if oversized else ['wrong_output_count','truncated_payload']
        if fixture['frame'] == guard['base_frame']:
            require(n == 1, 'XZ guard must originate from the one-byte fixture')
            negatives.append('oversize_dictionary')
        body = {'name': f'xz-legacy-{n}', 'method': METHOD, 'lineage':fixture,
                'expected_status':7 if oversized else 0, 'max_frame_bytes':0 if oversized else 32+len(schema)+FRAME_PAYLOAD_CAP,
                'original':{'columns':[{'dtype':2,'count':n}], 'column_bytes':[n], 'column_sha256':[sha(original)],
                            'schema_bytes':len(schema), 'schema_sha256':sha(schema)}, 'wire_checks':{},
                'reject_decodes':negatives, 'upstream_zstd':False}
        sid = slots[n] = content_id(body)
        products[sid] = {**body,'product_slot':sid}, BatchInput(schema,(original,))
    require(tuple(slots) == (*BASE_SIZES,65537), 'XZ baseline scope differs')
    covers = {'byte_block_boundary_triplet':(65535,65536,65537), 'empty_and_short':(0,1),
              'preset_threads_and_check':BASE_SIZES, 'correct_output_size':BASE_SIZES, 'memlimit_and_truncation':BASE_SIZES}
    binds = {c['case_id']:(plan['bundle_id'],[slots[n] for n in covers[c['check']]]) for c in plan['cases']
             if c['selection'] == 39 and c['route'] == METHOD}
    require(len(binds) == len(covers), 'XZ obligation definition differs')
    return products, binds
