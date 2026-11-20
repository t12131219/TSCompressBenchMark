#!/usr/bin/env python3
"""Attribute errors in the zero-reference CORAD guard frames without fitting a model."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from struct import Struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.corad_corpus_execution import _identity
from tsbench.application.m3_corad import prepare
from tsbench.application.m3_corad_guard_corpus import TRAINERS, _bind, _seal, check, ref
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, local_file, parse_json, require
from tsbench.planner.corad_deployment import NATIVE as HEADER
from tsbench.qualification.corad_wire import interpret

COUNT = Struct('<H')


def sparse_support(frame, rows, columns, width, atoms, maximum):
    """Read the already independently verified record counts in on-wire order."""
    cursor = HEADER.size + 8*(width*atoms + 2*columns)
    support = np.empty((rows//width, columns), dtype=np.uint16)
    for b in range(len(support)):
        for c in range(columns):
            n, = COUNT.unpack_from(frame,cursor)
            require(n<=maximum,'reference or invalid support count in a zero-reference frame')
            support[b,c] = n
            cursor += COUNT.size + 10*n
    require(cursor + 8*columns*(rows%width)==len(frame),'zero-reference record extent differs')
    return support


def above_bound(original, restored, bound):
    """Binary64 subtraction orders strict neighbors; resolve rounded ties exactly."""
    with np.errstate(over='ignore'):
        distance = np.abs(original-restored)
    rounded = float(bound)
    exceeds = distance > rounded
    for c,r in zip(*np.nonzero(distance==rounded),strict=True):
        exceeds[c,r] = abs(Fraction(float(original[c,r]))-Fraction(float(restored[c,r]))) > bound
    return exceeds


def inspect_frame(frame, original, training, binding, row):
    _, rows, cols, width, atoms, nzmax, _, _ = HEADER.unpack_from(frame)
    restored, parsed, _ = interpret(frame,max_values=131072)
    require(parsed['references']==0 and _identity(restored)==row['restore'] and cols==len(binding['ordered_columns']),
            'zero-reference independent restore identity differs')
    src, dst = (np.frombuffer(data,dtype='<f8').reshape(cols,rows) for data in (original,restored))
    train = np.frombuffer(training,dtype='<f8').reshape(cols,-1)
    lo, hi = np.min(train,axis=1), np.max(train,axis=1)
    inside = (src>=lo[:,None]) & (src<=hi[:,None])
    n = rows - rows%width
    supports = sparse_support(frame,rows,cols,width,atoms,nzmax).T
    require(original and src[:,n:].tobytes()==dst[:,n:].tobytes(),'raw tail was not restored bitwise')
    counts = Counter(expanded_values=src.size, expanded_tricklets=supports.size,
                     max_support_tricklets=int(np.count_nonzero(supports==nzmax)))
    for c,(limit,summary) in enumerate(zip(binding['train_only_quality_bounds'],row['original_domain_metrics'],strict=True)):
        bound = Fraction(limit['max_abs_error'])
        exceed = above_bound(src[c:c+1],dst[c:c+1],bound).ravel()
        require((not exceed.any()) is summary['max_abs_error_within_bound'] and not exceed[n:].any(),
                'pointwise sparse errors differ from guarded corpus terminal')
        blocks = exceed[:n].reshape(-1,width).any(axis=1)
        counts['abs_exceeding_values'] += int(np.count_nonzero(exceed))
        counts['abs_exceeding_values_in_train_range'] += int(np.count_nonzero(exceed & inside[c]))
        counts['abs_exceeding_values_outside_train_range'] += int(np.count_nonzero(exceed & ~inside[c]))
        counts['abs_exceeding_tricklets'] += int(np.count_nonzero(blocks))
        counts['abs_exceeding_tricklets_at_max_support'] += int(np.count_nonzero(blocks & (supports[c]==nzmax)))
        counts['abs_exceeding_tricklets_below_max_support'] += int(np.count_nonzero(blocks & (supports[c]<nzmax)))
        counts['mse_rejected_columns'] += int(not summary['mse_within_bound'])
    return counts


def audit(root, run, projection=None):
    plan = load_json(local_file(run,'plan.json'))
    require(plan['dataset_projection'] is None,'residual attribution requires a sealed full CORAD candidate source')
    seal = load_json(local_file(run,'completion.json'))
    require(seal==_seal(run,plan),'CORAD residual source seal differs')
    require(projection is None or projection in {c['dataset_id'] for c in plan['cases']}, 'unknown residual projection')
    _, entries, work_items = _bind(root,plan)
    summaries = defaultdict(lambda:defaultdict(Counter))
    count = 0
    with local_file(run,'trials.jsonl').open('rb') as ledger:
        for case in plan['cases']:
            dataset = case['dataset_id']
            selected = projection is None or dataset==projection
            if selected:
                material = prepare(root,entries[dataset],{r:work_items[w] for r,w in case['work_items'].items()})
                require(len(material)==len(case['members']),'residual attribution cohort population differs')
            for ix, member in enumerate(case['members']):
                saved = member['binding']
                if selected:
                    binding,training,tests = material[ix]
                    require(binding==saved and _identity(training)==binding['train']['values'],
                            'training range changed in residual attribution')
                for producer in TRAINERS:
                    for i,f in enumerate(saved['test_frames']):
                        row = parse_json(ledger.readline(),'CORAD guarded residual trial')
                        key = row['case']
                        require((key['dataset_id'],key['input_binding_id'],key['producer'],key['row_range'],key['source']) ==
                                (dataset,saved['input_binding_id'],producer,f['absolute_rows'],f['values']),
                                'guarded residual trial differs from frozen frame scope')
                        if not selected:
                            continue
                        count += 1
                        summary = summaries[dataset][producer]
                        summary['all_frames'] += 1
                        if row.get('reference_records') != 0:
                            summary['excluded_not_restored_or_contains_reference'] += 1
                            continue
                        require(row['status'] in {'verified','quality_rejected'}, 'invalid zero-reference candidate terminal')
                        payload = check(run,row['frame']).read_bytes()
                        require(_identity(tests[i])==key['source'],'residual analysis source value digest differs')
                        summary['zero_reference_frames:'+row['status']] += 1
                        summary.update(inspect_frame(payload,tests[i],training,binding,row))
            if selected:
                print(f'reconciled {dataset}',flush=True)
                del material
        require(not ledger.read(1),'unplanned CORAD residual attribution rows')
    require(projection is not None or count==plan['frame_count']==1174,'residual attribution omits frozen frames')
    totals = sum((c for ds in summaries.values() for c in ds.values()),Counter())
    body = {'schema':'bmk.m3-corad-sparse-residual-attribution/1','source_seal':ref(root,run/'completion.json'),
            'source_seal_id':seal['seal_id'],'dataset_projection':projection,'reviewed_frames':count,'counts':totals,
            'counts_by_file_and_producer':summaries,'scope':'original-domain extremes in reference-free CRD1 sparse records only',
            'model_or_quality_changes':False,'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}
    return {**body,'audit_id':content_id(body)}


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--dataset')
    o = p.add_mutually_exclusive_group(required=True)
    o.add_argument('--out',type=Path)
    o.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        report = audit(ROOT,a.run.resolve(strict=True),a.dataset)
        if a.out:
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,report)
        else:
            require(report==load_json(a.verify),'CORAD residual attribution did not recompute')
        print(dict(report['counts']))
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
