#!/usr/bin/env python3
"""Development-only CRD1 reference candidate: exact basis on zero-gate columns."""
from argparse import ArgumentParser
from collections import Counter
from fractions import Fraction
import math
from pathlib import Path
from struct import Struct, iter_unpack, pack, unpack_from
from tempfile import TemporaryDirectory

from m3_corad_sparse_development import ROOT, check, ref, seal, train_dev_matrix, binding, judge_quality, _identity
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, parse_json, require
from tsbench.qualification.corad_wire import HEADER, interpret

RECORD_COUNT = Struct('<H')
TERM = Struct('<Hd')
REFERENCE = 65535
SCHEMA = 'bmk.m3-corad-exact-basis-development/1'


def zero_gate(gate):
    return Fraction(gate['max_abs_error']) == Fraction(gate['mse']) == 0


def candidate(frame, original, gates):
    """Generate a new CRD1 frame; this is not the unmodified native encoder.

    Positive-gate columns preserve their sparse reconstruction. A reference
    into a rewritten source column becomes the equivalent original sparse
    record to keep its meaning. The exact columns use added unit atoms with
    mean=0, scale=1. The decoder already supports these records; no new escape
    symbol, outer raw block or loss budget is used. Restoration is numerically
    exact, not necessarily bit-exact (a sparse -0.0 becomes +0.0).
    """
    require(len(frame) >= HEADER.size, 'missing candidate base CRD1 header')
    magic, rows, cols, width, atoms, nonzero, threshold, saved_size = HEADER.unpack_from(frame)
    require(magic == b'CRD1' and len(frame) == saved_size and width == nonzero == 4 and 1 <= atoms <= 508 and
            len(gates) == cols and len(original) == rows*cols*8, 'candidate requires a budget-4 valid CRD1 base shape')
    exact = {i for i,g in enumerate(gates) if zero_gate(g)}
    if not exact:
        return frame, {'exact_columns':0, 'basis_bytes':0, 'exact_sparse_records':0, 'retargeted_references':0}
    dict_end = HEADER.size+width*atoms*8
    model_end = dict_end+16*cols
    require(model_end <= len(frame), 'truncated base model')
    identity = pack('<16d', *(float(i == j) for i in range(width) for j in range(width)))
    stats = b''.join(pack('<dd',0.,1.) if c in exact else frame[dict_end+16*c:dict_end+16*(c+1)] for c in range(cols))
    records = bytearray()
    cursor = model_end
    retargeted = 0
    for start in range(0,rows-rows%width,width):
        base, targets = [], []
        for col in range(cols):
            require(cursor+2 <= len(frame), 'truncated base tricklet')
            count, = RECORD_COUNT.unpack_from(frame,cursor)
            size = 4 if count == REFERENCE else 2+TERM.size*count
            require((count == REFERENCE or count <= nonzero) and cursor+size <= len(frame), 'invalid base record extent')
            target = RECORD_COUNT.unpack_from(frame,cursor+2)[0] if count == REFERENCE else None
            require(target is None or target < cols and target != col, 'invalid base reference')
            targets.append(target)
            base.append(frame[cursor:cursor+size]); cursor += size
        require(all(t is None or targets[t] is None for t in targets), 'chained base reference')
        for col in range(cols):
            if col in exact:
                values = unpack_from('<4d',original,(col*rows+start)*8)
                require(all(map(math.isfinite,values)), 'nonfinite exact-basis input')
                terms = [TERM.pack(atoms+i,v) for i,v in enumerate(values) if v != 0.]
                records.extend(RECORD_COUNT.pack(len(terms)))
                for term in terms:
                    records.extend(term)
            elif targets[col] in exact:
                records.extend(base[targets[col]])
                retargeted += 1
            else:
                records.extend(base[col])
    tail = frame[cursor:]
    require(len(tail) == 8*cols*(rows%width), 'base payload has wrong raw-tail extent')
    payload = frame[HEADER.size:dict_end]+identity+stats+records+tail
    out = HEADER.pack(magic,rows,cols,width,atoms+width,nonzero,threshold,HEADER.size+len(payload))+payload
    return out, {'exact_columns':len(exact), 'basis_bytes':len(identity), 'exact_sparse_records':len(exact)*(rows//width),
                 'retargeted_references':retargeted}


def evaluate(frame, raw, columns, gates, restored_identity):
    old, old_meta, _ = interpret(frame,max_values=131072)
    require(_identity(old) == restored_identity, 'base CRD1 recovery identity differs')
    out, stats = candidate(frame,raw,gates)
    new, meta, _ = interpret(out,max_values=131072)
    values_per_col = meta['rows']*8
    zero_gate_values = zero_gate_different_bits = zero_gate_signed_zero_changes = 0
    for i,g in enumerate(gates):
        sub = slice(i*values_per_col,(i+1)*values_per_col)
        if not zero_gate(g):
            require(old[sub] == new[sub], 'non-zero-gate column changed reconstruction')
            continue
        zero_gate_values += meta['rows']
        for (a,), (b,) in zip(iter_unpack('<Q',raw[sub]),iter_unpack('<Q',new[sub]),strict=True):
            if a != b:
                zero_gate_different_bits += 1
                zero_gate_signed_zero_changes += {a,b} == {0,1 << 63}
    metrics, ok = judge_quality(raw,new,columns,gates)
    numeric = ('header_bytes','embedded_model_bytes','tricklet_record_bytes','tail_bytes')
    before, after = ({k:m[k] for k in numeric} for m in (old_meta,meta))
    require(sum(before.values()) == len(frame) and sum(after.values()) == len(out), 'candidate byte accounting does not close')
    return {'verified':ok, 'quality':metrics, 'base_bytes':len(frame),'candidate_bytes':len(out),
            'zero_gate_values':zero_gate_values,'zero_gate_different_bits':zero_gate_different_bits,
            'zero_gate_signed_zero_changes':zero_gate_signed_zero_changes,
            'base_accounting':before,'candidate_accounting':after,'candidate_frame':_identity(out),**stats}


def audit(run, datasets):
    plan = load_json(local_file(run,'plan.json')); signed = load_json(local_file(run,'completion.json'))
    require(plan['dataset_projection'] is None and signed == seal(run,plan), 'expected sealed full CORAD development source')
    require(datasets and datasets <= plan['files'].keys(), 'unknown or missing development datasets')
    source = check(ROOT,plan['source_guard']).parent; build = check(ROOT,plan['build'])
    baseline = load_json(local_file(run,'report.json'))
    require(baseline['held_out_run'] is False and baseline['selected_nonzero_on_full_development'] is None,
            'candidate source used held-out data or selected budget')
    picked = {ds:[] for ds in datasets}
    with local_file(run,'trials.jsonl').open('rb') as f:
        for line in f:
            r = parse_json(line); k = r['key']
            if k['nonzero'] == 4 and k['dataset_id'] in datasets:
                picked[k['dataset_id']].append(r)
    checks, totals = [], Counter()
    with TemporaryDirectory(prefix='corad-basis-dev-') as tmp:
        for ds in sorted(datasets):
            require(len(picked[ds]) == baseline['stratified'][ds]['4']['frames'], 'candidate development denominator changed')
            (entry, groups, _), = binding(source,build,ds)
            require(entry['partitions'][1] == plan['files'][ds]['development'], 'candidate development partition changed')
            directory = Path(tmp)/ds; directory.mkdir()
            matrix = train_dev_matrix(ROOT,entry,directory)
            idx = {g['id']:g for g in groups}
            for r in picked[ds]:
                require(r['status'] == 'native_restored', 'candidate source has missing native restoration')
                k = r['key']; g = idx[k['input_binding_id']]
                lo, hi = k['development_rows']
                require(entry['partitions'][1]['start'] <= lo < hi <= entry['partitions'][1]['end'] and
                        k['model'] == g['models'][k['producer']] and k['columns'] == g['column_names'], 'foreign development trial')
                raw = matrix[lo:hi,g['columns']].T.tobytes()
                a,z = g['train']['absolute_rows']
                require(_identity(matrix[a:z,g['columns']].T.tobytes()) == g['train']['values'] and
                        _identity(raw) == k['development_input'], 'frozen train/development bytes differ')
                out = evaluate(check(ROOT,r['frame']).read_bytes(),raw,k['columns'],g['gates'],r['restore'])
                prior = r['decision']['terminal']
                totals[f"{prior}_to_{'verified' if out['verified'] else 'quality_rejected'}"] += 1
                for name in ('base_bytes','candidate_bytes','retargeted_references','exact_sparse_records',
                             'zero_gate_values','zero_gate_different_bits','zero_gate_signed_zero_changes'):
                    totals[name] += out[name]
                checks.append({'key':k,'base_terminal':prior, **out})
    body = {'schema':SCHEMA, 'scope':'projected_development_only_reference_encoder_and_independent_crd1_reader',
            'source':ref(ROOT,run/'completion.json'),'dataset_projection':sorted(datasets),'totals':dict(totals),'rows':checks,
            'native_candidate_run':False,'held_out_read':False,'budget_selected':False,'all_development_covered':datasets == plan['files'].keys(),
            'timing_admitted':False,'qualification_granted':False,'stage_accepted':False}
    return {**body,'audit_id':content_id(body)}


def main():
    p = ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--dataset',action='append',required=True)
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path); out.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        result = audit(a.run.resolve(strict=True),set(a.dataset))
        if a.out:
            write_new(a.out,result)
        else:
            require(result == load_json(a.verify),'CORAD exact basis proof differs on recomputation')
        print(result['audit_id'],result['totals'])
    except (KeyError, OSError, ValueError) as exc:
        p.exit(1,f'{exc}\n')


if __name__ == '__main__':
    main()
