"""Independent train/holdout and sealed-frame audit for the M3 lzbench run."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from tsbench.application.m3_zstd_dictionary import _frame
from tsbench.assets import require, verify_asset
from tsbench.corpus_ingress import read_batches
from tsbench.planner.m3_zstd_dictionary import DRIVER, LIMIT, extents
from tsbench.qualification.lzbench import zstd_frame


def audit_dictionary(root,run,exe,item,row,entry):
    proof = row['evidence']; expected = item['input']['training']
    (train,test),_,_ = extents(item,entry)
    require(proof['driver']==DRIVER and proof['tier']==expected['extent_tier'] and
            proof['sample_geometry']==expected['sample_geometry'] and proof['train_bytes']==train[1]-train[0] and
            proof['holdout_object_id']==expected['evaluation']['partition_object_id'] and
            not proof['fallback_used'] and not proof['timing_admitted'],'Zstd dictionary contract differs')
    wanted = {'bytes':test[1]-test[0],'sha256':entry['partitions'][2]['canonical']['values_sha256']}
    require(proof['holdout']==wanted,'Zstd dictionary holdout differs from manifest')
    frame_rows=iter(proof['frames']); width=entry['value_count']*8
    train_hash,test_hash = sha256(),sha256()
    raw_sample = None; pos=0; checked=0; buffer=bytearray()
    sample = proof.get('retained_frame')
    for batch in read_batches(root,entry):
        start = batch.start*width; end = start+len(batch.values)
        if start<train[1] and train[0]<end:
            train_hash.update(batch.values[max(0,train[0]-start):min(end,train[1])-start])
        if start<test[1] and test[0]<end:
            portion=batch.values[max(0,test[0]-start):min(end,test[1])-start]
            test_hash.update(portion)
            if proof['test_attempted']:
                buffer.extend(portion); offset=0
                while len(buffer)-offset>=LIMIT or (end>=test[1] and len(buffer)>offset):
                    n=min(len(buffer)-offset,LIMIT); data=buffer[offset:offset+n]; offset+=n
                    part = next(frame_rows,None)
                    require(part is not None and (part['index'],part['holdout_byte_range'],part['logical_bytes'],part['input_sha256'])==
                            (checked,[pos,pos+n],n,sha256(data).hexdigest()),'Zstd dictionary held-out frame extent differs')
                    if sample and sample['index']==checked:
                        raw_sample = bytes(data)
                    checked+=1; pos+=n
                del buffer[:offset]
    require(test_hash.hexdigest()==wanted['sha256'] and train_hash.hexdigest()==proof['train_prefix_sha256'] and
            next(frame_rows,None) is None,'Zstd dictionary independently staged input differs')
    if not proof['test_attempted']:
        require(not checked and row['status']=='failed' and row['reason']==proof['failure_reason'] and
                proof['phase']=='native_training_failed','Zstd dictionary training failure terminal differs')
        return None
    successful = [f for f in proof['frames'] if f['status']=='verified']
    failed = [f for f in proof['frames'] if f['status']=='failed' and f['reason']]
    require(pos==wanted['bytes'] and len(successful)+len(failed)==checked==item['input']['size_estimate']['input_units']-1 and
            len(failed)==proof['failed_units'] and (not failed)==(row['status']=='verified'), 'Zstd dictionary status accounting differs')
    shared = proof['dictionary']; dictionary = verify_asset(run,shared); data = dictionary.read_bytes()
    require(8<=len(data)==shared['bytes']<=expected['dictionary_capacity_bytes'] and
            data[:4]==bytes.fromhex('37a430ec') and int.from_bytes(data[4:8],'little')==shared['id']>1 and
            all(f['dictionary_id']==shared['id'] and f['input_sha256']==f['restored_sha256'] for f in successful),
            'Zstd dictionary dependency or restore digest differs')
    wire_bytes = sum(f['bytes'] for f in successful)
    require(proof['verified_frame_bytes']==wire_bytes and proof['verified_frame_bytes_plus_shared_dictionary_once']==wire_bytes+len(data),
            'Zstd dictionary dependency was not billed exactly once')
    if not successful:
        require(sample is None,'unexpected Zstd dictionary sample for no verified frame')
        return None
    first = successful[0]; wire = verify_asset(run,sample)
    require(raw_sample is not None and all(sample[k]==first[k] for k in ('index','bytes','sha256')) and
            zstd_frame(wire.read_bytes())['dictionary_id']==shared['id'],'Zstd dictionary sample differs')
    negatives = {k:{'status':'expected_rejection','reason':'Dictionary mismatch','returncode':2} for k in ('missing','wrong_id')}
    require(proof['negative_controls']==negatives,'Zstd dictionary negative controls differ')
    with TemporaryDirectory(prefix='m3-zstd-dict-audit-') as tmp:
        work = Path(tmp); restored = work/'raw'; copied=work/'copied'
        _frame(exe,work,wire,copied,restored,len(raw_sample),dictionary)
        require(copied.read_bytes()==wire.read_bytes() and restored.read_bytes()==raw_sample,'Zstd dictionary sample replay differs')
        wrong = work/'wrong'
        wrong.write_bytes(data[:4]+(shared['id']^1).to_bytes(4,'little')+data[8:])
        for label, dependency in [('missing',None),('wrong_id',wrong)]:
            a,b=work/(label+'-copied'),work/(label+'-raw')
            require(_frame(exe,work,wire,a,b,len(raw_sample),dependency,reject='Dictionary mismatch')==negatives[label]
                    and not a.exists() and not b.exists(),'Zstd dictionary independent negative control differs')
    return {'dataset_id':item['dataset_id'],'tier':proof['tier'],'frame':sample,'dictionary':shared,'rejection_controls':negatives}
