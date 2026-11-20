#!/usr/bin/env python3
"""Attribute rejected development columns using exact CRD1 arithmetic, without selecting a model."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from struct import iter_unpack, unpack_from
from tempfile import TemporaryDirectory

from m3_corad_sparse_development import (ROOT, _identity, check, jobs, ref, seal, plan_for)
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, parse_json, require
from tsbench.qualification.corad_wire import HEADER, interpret

SCHEMA = 'bmk.m3-corad-development-rounding-attribution/1'


def compare_rejected(frame, raw, native, bad, names, gates):
    """Round the exact affine reconstruction once; keep the actual CRD1 record and coefficient bytes."""
    _,rows,cols,width,atoms,_,_,_ = HEADER.unpack_from(frame)
    require(len(raw)==len(native)==8*rows*cols and width==atoms==4 and bad,'CORAD audit extent differs')
    words = tuple(iter_unpack('<d',raw)); restored = tuple(iter_unpack('<d',native))
    d_size = width*atoms
    model = tuple(map(Fraction,unpack_from(f'<{d_size+2*cols}d',frame,HEADER.size)))
    offset = HEADER.size+8*len(model)
    results = {c:{'max':Fraction(0),'sse':Fraction(0),'counts':Counter()} for c in bad}
    for lo in range(0,rows-rows%width,width):
        records, refs = [], []
        for _ in range(cols):
            n, = unpack_from('<H',frame,offset); offset += 2
            if n == 65535:
                target, = unpack_from('<H',frame,offset); offset += 2
                refs.append(target); records.append(None)
            else:
                terms = []
                for _ in range(n):
                    atom, value = unpack_from('<Hd',frame,offset); offset += 10
                    terms.append((atom*width,value))
                records.append(terms); refs.append(None)
        dot = {}
        for c in bad:
            head = results[c]
            cap = Fraction(gates[c]['max_abs_error']); ref_col = refs[c]
            src = c if ref_col is None else ref_col
            if src not in dot:
                terms = [(at,Fraction(v)) for at,v in records[src]]
                dot[src] = tuple(sum((coeff*model[at+i] for at,coeff in terms),Fraction(0)) for i in range(width))
            mean, scale = model[d_size+2*c:d_size+2*c+2]
            for i,value in enumerate(dot[src]):
                k = c*rows+lo+i
                x,y = Fraction(words[k][0]),Fraction(restored[k][0])
                new = Fraction(float(value*scale+mean))
                before, after = abs(x-y), abs(x-new)
                head['max'] = max(head['max'],after); head['sse'] += after*after
                stats = head['counts']; stats['values'] += 1
                stats['actual_max_violations'] += before > cap
                stats['ideal_max_violations'] += after > cap
                stats['violations_removed_by_ideal_rounding'] += before > cap >= after
                stats['violations_introduced_by_ideal_rounding'] += after > cap >= before
                stats['actual_violations_using_reference'] += before > cap and ref_col is not None
                stats['ideal_violations_using_reference'] += after > cap and ref_col is not None
    require(all(words[c*rows+i]==restored[c*rows+i] for c in bad for i in range(rows-rows%width,rows)),
            'CORAD raw tail did not roundtrip')
    return [{ 'column':names[c], 'zero_training_gate':Fraction(gates[c]['max_abs_error'])==0,
              'ideal_max':str(h['max']), 'ideal_mse':str(h['sse']/rows),
              'ideal_passes':h['max']<=Fraction(gates[c]['max_abs_error']) and h['sse']/rows<=Fraction(gates[c]['mse']),
              'counts':h['counts']} for c,h in results.items()]


def audit(run, dataset):
    plan = load_json(local_file(run,'plan.json'))
    stamped = load_json(local_file(run,'completion.json'))
    require(plan['dataset_projection'] is None and stamped==seal(run,plan),'expected sealed full development trials')
    guard = check(ROOT,plan['source_guard']).parent
    build = check(ROOT,plan['build'])
    frozen,_ = plan_for(guard,build,None)
    require(frozen==plan and (dataset is None or dataset in plan['files']),'development plan differs')
    results, total = [], Counter(); split = defaultdict(Counter); written = 0
    with TemporaryDirectory(prefix='corad-rounding-',dir=run.parent) as work, local_file(run,'trials.jsonl').open('rb') as ledger:
        for n,(key,raw,gates) in enumerate(jobs(guard,build,None,Path(work))):
            row = parse_json(ledger.readline(),'CORAD development trial')
            require(row['key']==key,'development audit regenerated different slot')
            decision = row['decision']; ds = key['dataset_id']
            if key['nonzero']!=4 or (dataset is not None and dataset!=ds) or decision['terminal']!='quality_rejected':
                continue
            file = check(ROOT,row['frame'])
            require(file==run/'frames'/f'{n}.crd1','CORAD frame crossed development slots')
            wire = file.read_bytes(); reconstructed,info,_ = interpret(wire,max_values=131072)
            require(_identity(reconstructed)==row['restore'] and _identity(raw)==key['development_input'], 'restore or input identity differs')
            bad = [i for i,c in enumerate(decision['quality']) if not (c['max_abs_error_within_bound'] and c['mse_within_bound'])]
            columns = compare_rejected(wire,raw,reconstructed,bad,key['columns'],gates)
            total['quality_rejected_frames'] += 1
            total['all_rejected_columns_would_pass_ideal'] += all(c['ideal_passes'] for c in columns)
            for c in columns:
                for counter in (total,split[ds]):
                    counter['quality_rejected_columns'] += 1
                    counter['zero_training_gate_columns'] += c['zero_training_gate']
                    counter['ideal_rounding_pass_columns'] += c['ideal_passes']
                    counter.update(c['counts'])
            results.append({'key':key,'counts_reference_records':info['references'],'rejected_columns':columns})
            written += 1
        require(not ledger.read(1) and written>0,'CORAD rejected trial population did not close')
    if dataset is None:
        require(written==load_json(local_file(run,'report.json'))['totals']['4']['quality_rejected'],'missing rejected budget-4 frames')
    body = {'schema':SCHEMA,'source':ref(ROOT,run/'completion.json'),'source_seal_id':stamped['seal_id'],'dataset_projection':dataset,
            'scope':'development only; existing coefficients and references with ideal correctly-rounded affine reconstruction; no candidate chosen',
            'actual_quality_unchanged':True,'held_out_read':False,'totals':total,'datasets':split,'rejected_frames':results,
            'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    return {**body,'audit_id':content_id(body)}


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True); p.add_argument('--dataset')
    out=p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path); out.add_argument('--verify',type=Path)
    a=p.parse_args()
    try:
        result=audit(a.run.resolve(strict=True),a.dataset)
        if a.out:
            write_new(a.out,result)
        else:
            require(result==load_json(a.verify),'CORAD development rounding attribution differs')
        print(dict(result['totals']))
    except (OSError, ValueError) as exc:
        p.exit(1,f'{exc}\n')
