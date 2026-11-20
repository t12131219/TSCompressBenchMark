#!/usr/bin/env python3
"""Audit one Huff0 ETB1 corpus run and restore retained model/stream pairs."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_huff0_table import asset, binding, call, checked_identity, layout
from tsbench.application.m3_huff0_specialized import ledger_products
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest, read_batches
from tsbench.planner.m3_huff0_fec1 import KEY as FEC1_KEY
from tsbench.planner.m3_huff0_table import BLOCK, DRIVER, KEY, RETAIN_MAX, STREAMS, inputs
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.qualification.huff0 import _model


def training_prefix(root,entry,span):
    h=sha256(); consumed=0; width=8*entry['value_count']
    for batch in read_batches(root,entry):
        start=batch.start*width; end=start+len(batch.values)
        lo,hi=max(start,span[0]),min(end,span[1])
        if lo<hi:
            h.update(batch.values[lo-start:hi-start]); consumed+=hi-lo
    require(consumed==span[1]-span[0],'ETB1 original training prefix is incomplete')
    return {'bytes':consumed,'sha256':h.hexdigest()}


def lane(run,item,exe,key,proof,training,holdout):
    size=holdout['bytes']; blocks=proof['blocks']; streams=int(key)
    require(streams in STREAMS and proof['status']=='verified' and proof['recovered']==holdout and
            [b['original_bytes'] for b in blocks]==[min(BLOCK,size-at) for at in range(0,size,BLOCK)] and
            all((b['mode']=='raw' and b['body_bytes']==b['original_bytes']) or
                (b['mode']=='huffman' and 0<b['body_bytes']<b['original_bytes']) for b in blocks),'ETB1 audited block layout differs')
    table_ref,frame_ref,bind_ref=(proof[k] for k in ('model','frame','binding'))
    wire_cost=sum(9+b['body_bytes'] for b in blocks)
    sidecar=binding(streams,table_ref,frame_ref)
    require(9<=table_ref['bytes']<=1024 and frame_ref['bytes']==wire_cost and
            bind_ref=={'bytes':len(sidecar),'sha256':sha256(sidecar).hexdigest()} and
            proof['complete_bytes']==wire_cost+table_ref['bytes']+bind_ref['bytes'],'ETB1 complete resource charge differs')
    train=proof['train']; log=train['effective_table_log']
    require(9<=log<=12 and train=={'streams':streams,'effective_table_log':log,'blocks':0,'raw_bytes':training['bytes'],
            'wire_bytes':table_ref['bytes'],'context_count':1} and
            proof['encode']==proof['decode']=={**train,'blocks':len(blocks),'raw_bytes':size,'wire_bytes':wire_cost},
            'ETB1 table load and reuse evidence differs')
    retained=proof['retained']; replayed=None
    if wire_cost<=RETAIN_MAX:
        names={'model.etb1':table_ref,'test.blocks':frame_ref,'binding.json':bind_ref}
        paths={}
        for k,v in names.items():
            require(retained[k]=={'path':f"retained/{item['work_item_id']}/{key}x/{k}",**v},'ETB1 retained pair closure differs')
            paths[k]=verify_asset(run,retained[k])
        require(retained.keys()==names.keys() and _model(paths['model.etb1'].read_bytes(),streams)==log and
                layout(paths['test.blocks'],streams,size)==blocks,'ETB1 retained byte layout differs')
        checked_identity(paths['binding.json'].read_bytes(),streams,asset(paths['model.etb1']),asset(paths['test.blocks']))
        with TemporaryDirectory(prefix='tsbench-etb1-audit-') as tmp:
            work=Path(tmp); raw=work/'out'
            require(call(exe,'decode',paths['model.etb1'],paths['test.blocks'],raw,cwd=work)==proof['decode'] and
                    asset(raw)==holdout,'ETB1 retained pair did not restore')
        replayed={'dataset_id':item['dataset_id'],'streams':streams,'parts':retained,'restored':holdout}
    else:
        require(not retained,'ETB1 oversized retained pair')
    return replayed


def verify(root,plan_path,run):
    plan=load_json(plan_path); check_m3_real_corpus_plan(root,plan)
    f={n:local_file(run,n) for n in ('report.json','ledger.jsonl','completion.json')}
    r=load_json(f['report.json']); seal=load_json(f['completion.json'])
    load_contract(root,'m3-real-corpus-run').validate(r,'Huff0 shared table run')
    special=r['specialized']
    require(r['partial_preflight'] and r['route_filter'] in ([KEY[1]], sorted([KEY[1],FEC1_KEY[1]])) and special.keys()<={'huff0'} and
            r['run_id']==seal['run_id']==run.name and r['plan_content_id']==seal['plan_content_id']==plan['plan_content_id'] and
            seal['report_sha256']==digest(f['report.json']) and seal['ledger_sha256']==digest(f['ledger.jsonl']) and
            seal['seal_id']==content_id({k:v for k,v in seal.items() if k!='seal_id'}),'ETB1 scope or run seal differs')
    products=ledger_products(plan['specialized']['huff0'],special['huff0']) if 'huff0' in special else []
    with f['ledger.jsonl'].open(encoding='utf-8') as ledger:
        for line,record in zip(ledger,[*r['rows'],*products,*r['obligations']],strict=True):
            require(json.loads(line)==record,'ETB1 main ledger differs from report')
    obligations=[ob for ob in plan['obligations'] if (ob['selection'],ob['route'])==KEY]
    observed=[ob for ob in r['obligations'] if (ob['selection'],ob['route'])==KEY]
    wanted=[a for a in plan['work_items'] if (a['selection'],a['route'])==KEY]
    actual=[a for a in r['rows'] if (a['selection'],a['route'])==KEY]
    require(len(wanted)==len(actual)==23 and r['selected_work_items']==r['selected_corpus_decisions']==len(r['rows']) and
            r['obligation_statuses']==dict(Counter(o['status'] for o in r['obligations'])),'ETB1 denominator differs')
    for a,b in zip(obligations,observed,strict=True):
        require(all(a[k]==b[k] for k in ('obligation_id','selection','route','check','kind')) and
                ('huff0' in special or b['status']=='not_run' and b['evidence'] is None),'ETB1 named obligation differs')
    definition=load_json(verify_asset(root,plan['definition']['plan']))
    entries={e['id']:e for e in load_full_manifest(root,definition['bindings']['manifest'],parse=False)['datasets']}
    exe=local_file(root,plan['build']['huff0_table']['executable']['path'])
    totals={str(s):Counter() for s in STREAMS}; replayed=[]; failures=[]
    mismatch={'status':'expected_rejection','reason':'ETB1 SHA-256 model/block binding mismatch','native_decode_started':False}
    for item,row in zip(wanted,actual,strict=True):
        require(all(item[k]==row[k] for k in ('work_item_id','dataset_id','selection','route','operation','applicability')) and
                row['applicability']=='input_domain_matches' and row['status'] in ('failed','verified'),'ETB1 result identity differs')
        proof=row['evidence']; entry=entries[row['dataset_id']]
        if row['status']=='failed':
            require(row['reason'],'ETB1 failed without a reason')
            failures.append({k:row[k] for k in ('dataset_id','reason')})
            if proof is None: continue
        require(proof is not None,'verified ETB1 result has no evidence')
        train,test=inputs(item,entry)
        training=training_prefix(root,entry,train)
        holdout={'bytes':test[1]-test[0],'sha256':entry['partitions'][2]['canonical']['values_sha256']}
        require(proof['driver']==DRIVER and not proof['timing_admitted'] and proof['training']==training and
                proof['holdout']==holdout and proof['profiles'].keys()==totals.keys() and
                bool(proof['errors'])==(row['status']=='failed'),'ETB1 corpus binding or outcome differs')
        for k,v in proof['profiles'].items():
            totals[k][v['status']]+=1
            if v['status']=='failed':
                require(v['reason'] and row['status']=='failed','ETB1 lane nonpass disappeared')
                continue
            sample=lane(run,item,exe,k,v,training,holdout)
            if sample: replayed.append(sample)
            if row['status']=='verified':
                other=proof['profiles']['4' if k=='1' else '1']
                require(v['different_valid_model_binding_rejection']==mismatch and other['model']!=v['model'],
                        'ETB1 different-model rejection used no independent model')
            totals[k]['blocks']+=len(v['blocks'])
            totals[k]['huffman_blocks']+=sum(b['mode']=='huffman' for b in v['blocks'])
            totals[k]['complete_bytes']+=v['complete_bytes']
    require(r['statuses']==dict(Counter(row['status'] for row in r['rows'])),'ETB1 file status accounting differs')
    return {'schema':'bmk.m3-huff0-table-audit/1','run_id':run.name,'plan_content_id':plan['plan_content_id'],'run_seal_id':seal['seal_id'],
            'totals':totals,'replayed_samples':replayed,'failures':failures,'obligations':r['obligation_statuses'],
            'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True); p.add_argument('--run',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(verify(ROOT,a.plan,a.run.resolve(strict=True)),indent=2))
