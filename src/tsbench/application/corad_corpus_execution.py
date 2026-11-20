"""Execute same-run CORAD model producers and their isolated held-out consumers."""
from collections import Counter
from fractions import Fraction
import math
from pathlib import Path
import struct
import tempfile

from ..assets import canonical_bytes, content_id, digest, load_json, require, verify_asset
from ..planner.corad_corpus import C, SOURCE, calibrate_quality
from ..planner.corad_training import STAGED_BRIDGE, VECTORS
from ..qualification.corad_training import _normalization
from ..qualification.corad_wire import HEADER, interpret, quality
from ..recovery import DIRECTORY
from ..supervisor.corad_source import invoke_source
from ..supervisor.isolated_worker import invoke_isolated_tool
from .corad_training_execution import _npy

TOOL = 'corad-corpus-control'
LIMITS = {'address_space_bytes':128 << 20, 'file_bytes':1 << 20, 'wall_seconds':10}
SOURCE_LIMITS = {**LIMITS, 'address_space_bytes':768 << 20, 'wall_seconds':25}


def _ref(root, path):
    return {'path':path.relative_to(root).as_posix(), 'sha256':digest(path), 'bytes':path.stat().st_size}


def _identity(data):
    from hashlib import sha256
    return {'bytes':len(data), 'sha256':sha256(data).hexdigest()}


def judge_quality(original, restored, names, bounds):
    require(names and original and len(original)==len(restored) and len(original)%(8*len(names))==0 and len(bounds)==len(names),
            'CORAD quality input extent differs')
    col_bytes = len(original)//len(names)
    src, dst = ([b[i:i+col_bytes] for i in range(0,len(b),col_bytes)] for b in (original,restored))
    out = quality(src,dst,names)
    for row, calibration, a, b in zip(out,bounds,src,dst,strict=True):
        errors = [abs(Fraction(y)-Fraction(x)) for (x,), (y,) in zip(struct.iter_unpack('<d',a),struct.iter_unpack('<d',b),strict=True)]
        maximum, mse = max(errors), sum((e*e for e in errors),Fraction(0))/len(errors)
        row.update(exact_max_abs_error=str(maximum), exact_mse=str(mse),
                   max_abs_error_within_bound=maximum <= Fraction(calibration['max_abs_error']),
                   mse_within_bound=mse <= Fraction(calibration['mse']))
    return out, all(r['max_abs_error_within_bound'] and r['mse_within_bound'] for r in out)


def _native(run, plan, work, logs, label, mounts, args, target, operations):
    step = work/label
    step.mkdir()
    out, op = invoke_isolated_tool(run/DIRECTORY, plan['decoder'], TOOL, LIMITS, step, logs, label, mounts, args,
                                   lambda:False, observe=True)
    operations[label] = op
    if op.get('status') != 'completed' or op.get('returncode') != 0:
        return None, None
    doc = load_json(logs/(label+'.stdout'))
    op['native'] = doc
    if doc['native_status'] != 0:
        require(not list(out.iterdir()) and doc['output_bytes']==0, 'CORAD native rejection produced output')
        return None, doc
    path = out/target
    require({p.name for p in out.iterdir()}=={target} and path.is_file() and not path.is_symlink() and
            path.stat().st_size==doc['output_bytes'], 'CORAD native output closure differs')
    return path.read_bytes(), doc


def _stage(path, data):
    with path.open('xb') as f:
        f.write(data)
    return path


def _source_train(run, plan, work, logs, train, bridge, width, rows, operations):
    means, scales, vectors = _normalization([train[i*rows*8:(i+1)*rows*8] for i in range(width)],4,(1<<width)-1)
    npy = _npy(vectors, len(vectors)//4, 4)
    bridge_path = _stage(work/STAGED_BRIDGE, bridge)
    vector_path = _stage(work/VECTORS, npy)
    source = work/'source-train'; source.mkdir()
    step = {'outputs':['trained.json'], 'argv':['-I','-B',STAGED_BRIDGE,'--input',VECTORS,'--output','trained.json',
                                              '--atoms','4','--alpha','0.25','--source-root','.']}
    out, op = invoke_source(plan, step, SOURCE_LIMITS, source, logs, 'source-train',
                            {STAGED_BRIDGE:bridge_path, VECTORS:vector_path}, lambda:False)
    operations['source-train'] = op
    if op.get('status') != 'completed' or op.get('returncode') != 0:
        return None, None, None
    require({p.name for p in out.iterdir()}=={'trained.json'}, 'CORAD Source output closure differs')
    raw = (out/'trained.json').read_bytes()
    model = load_json(out/'trained.json')['dictionary']
    require(isinstance(model,list) and len(model)==4 and all(isinstance(a,list) and len(a)==4 and
            all(type(v) in (int,float) and math.isfinite(v) for v in a) for a in model), 'invalid CORAD Source dictionary')
    atoms = [v for a in model for v in a]
    arr = _stage(work/'arrays',struct.pack(f'<{16+2*width}d',*atoms,*means,*scales))
    blob, native = _native(run,plan,work,logs,'source-pack',{'arrays':arr},['pack','/inputs/arrays',str(width)],'model',operations)
    if blob is not None:
        _, _, embedded = interpret(blob)
        require(embedded==struct.pack(f'<{16+2*width}d',*atoms,*(x for ms in zip(means,scales,strict=True) for x in ms)),
                'CORAD packed Source model arrays differ from train-only normalization or dictionary')
    return blob, native, {'dictionary_json':raw, 'train_vectors':npy}


def execute_cohort(run, plan, binding, train, tests, bridge):
    """Yield terminal train/deploy/frame evidence under one caller-owned ledger."""
    name = binding['input_binding_id']
    columns = binding['ordered_columns']
    width, rows = len(columns), binding['train']['absolute_rows'][1]-binding['train']['absolute_rows'][0]
    require(_identity(train)==binding['train']['values'] and len(tests)==len(binding['test_frames']) and
            binding['train_only_quality_bounds']==calibrate_quality(train,count=rows,width=width),
            'CORAD bound training bytes or quality gates differ')
    require(all(_identity(raw)==frame['values'] for raw,frame in zip(tests,binding['test_frames'],strict=True)),
            'CORAD bound test bytes differ')
    for trainer in (C,SOURCE):
        outputs, logs = run/'products'/name/trainer, run/'logs'/name/trainer
        outputs.mkdir(parents=True); logs.mkdir(parents=True)
        identity = {'dataset':binding['source'], 'producer':trainer, 'input_binding_id':name,
                    'producer_binding_id':binding['producer_binding_ids'][trainer]}
        operations = {}
        blob, native, training_assets = None, None, {}
        with tempfile.TemporaryDirectory(prefix='corad-corpus-train-') as td:
            temp = Path(td)
            if trainer==C:
                train_path = _stage(temp/'train',train)
                blob, native = _native(run,plan,temp,logs,'c-train',{'train':train_path},
                                       ['train','/inputs/train',str(width)],'model',operations)
                if blob is not None:
                    require(native['training_samples']==(rows//4)*width and 1<=native['iterations']<=6 and
                            native['converged'] in (0,1), 'CORAD C fit sample/iteration ledger differs')
            else:
                blob, native, source_assets = _source_train(run,plan,temp,logs,train,bridge,width,rows,operations)
                if source_assets is not None:
                    for key,data in source_assets.items():
                        training_assets[key] = _ref(run,_stage(outputs/key,data))
        if blob is None:
            yield {**identity,'operation':'train','status':'native_rejected' if native else 'training_process_failed',
                   'native':native,'processes':operations}
            for f in binding['test_frames']:
                yield {**identity,'operation':'heldout','status':'dependency_not_produced','frame_range':f['absolute_rows']}
            continue
        _, model_meta, model_values = interpret(blob)
        require(model_meta['rows']==0 and model_meta['columns']==width and 0<len(blob)<=16384, 'invalid CORAD trained model')
        model_file = _stage(outputs/'model.crd1',blob)
        model_ref = _ref(run,model_file)
        deployment = {**identity, 'train':binding['train'], 'ordered_columns':columns,'model':model_ref}
        deployment['deployment_id'] = content_id(deployment)
        dep_path = _stage(outputs/'deployment.json',canonical_bytes(deployment)+b'\n')
        yield {**identity,'operation':'train','status':'verified','deployment':deployment,
               'deployment_asset':_ref(run,dep_path),'training_assets':training_assets,'native':native,'processes':operations}
        for i,(test,frame) in enumerate(zip(tests,binding['test_frames'],strict=True)):
            count = frame['absolute_rows'][1]-frame['absolute_rows'][0]
            operations = {}
            with tempfile.TemporaryDirectory(prefix='corad-corpus-heldout-') as td:
                temp = Path(td)
                require(_ref(run,model_file)==model_ref,'CORAD deployment model changed before use')
                test_path = _stage(temp/'test',test)
                descriptor = [str(count),str(width)]
                encoded, enc = _native(run,plan,temp,logs,f'encode-{i}',{'model':model_file,'test':test_path},
                                       ['encode','/inputs/model','/inputs/test',*descriptor],'frame',operations)
                key = {**identity,'operation':'heldout','deployment_id':deployment['deployment_id'],
                       'frame_range':frame['absolute_rows'],'processes':operations}
                if encoded is None:
                    yield {**key,'status':'native_rejected' if enc else 'encode_process_failed','native':enc}
                    continue
                path = _stage(outputs/f'heldout-{i}.crd1',encoded)
            # Original values are not even staged under this restore workspace.
            with tempfile.TemporaryDirectory(prefix='corad-corpus-frame-only-') as td:
                restored, dec = _native(run,plan,Path(td),logs,f'restore-{i}',{'frame':path},
                                        ['decode','/inputs/frame',*descriptor],'values',operations)
            if restored is None:
                yield {**key,'status':'restore_failed','native':dec,'frame':_ref(run,path)}
                continue
            interpreted, meta, embedded = interpret(encoded,max_values=131072)
            require(restored==interpreted and embedded==model_values and (meta['rows'],meta['columns'])==(count,width) and
                    set(operations[f'restore-{i}']['input_mounts'])=={'frame'}, 'CORAD detached restore or model binding differs')
            metrics, accepted = judge_quality(test,restored,columns,binding['train_only_quality_bounds'])
            yield {**key,'status':'verified' if accepted else 'quality_rejected','original_domain_metrics':metrics,
                   'quality_gates':binding['train_only_quality_bounds'],'frame':_ref(run,path),'restore':_identity(restored),
                   'frame_accounting':{k:meta[k] for k in ('header_bytes','embedded_model_bytes','tricklet_record_bytes','tail_bytes')},
                   'logical_value_bytes':len(test)}


def summarize(rows):
    return {'training':dict(Counter(r['status'] for r in rows if r['operation']=='train')),
            'heldout':dict(Counter(r['status'] for r in rows if r['operation']=='heldout')),
            'detached_restored':sum('restore' in r for r in rows)}


def verify_cohort_ledger(run, binding, train, tests, rows):
    """Recompute pairing, detached byte identity and exact quality without native code."""
    names = binding['ordered_columns']
    width = len(names)
    bounds = calibrate_quality(train,count=len(train)//(8*width),width=width)
    require(bounds==binding['train_only_quality_bounds'] and len(tests)==len(binding['test_frames']) and
            len(rows)==2*(1+len(tests)), 'CORAD ledger denominator or calibration differs')
    stride = len(tests)+1
    for index, producer in enumerate((C,SOURCE)):
        fitted, *evaluations = rows[index*stride:(index+1)*stride]
        require(fitted['producer']==producer and fitted['operation']=='train' and all(
            r['input_binding_id']==binding['input_binding_id'] and r['dataset']==binding['source'] and
            r['producer']==producer and r['producer_binding_id']==binding['producer_binding_ids'][producer]
            for r in (fitted,*evaluations)), 'CORAD ledger producer binding differs')
        if fitted['status']!='verified':
            require(all(r['status']=='dependency_not_produced' for r in evaluations), 'CORAD failed train cannot deploy')
            continue
        deployment = fitted['deployment']
        ref = deployment['model']
        model = verify_asset(run,ref).read_bytes()
        require(len(model)==ref['bytes'] and load_json(verify_asset(run,fitted['deployment_asset']))==deployment and
                deployment['deployment_id']==content_id({k:v for k,v in deployment.items() if k!='deployment_id'}) and
                deployment['train']==binding['train'] and deployment['ordered_columns']==names,
                'CORAD deployment ledger differs')
        _, m, model_arrays = interpret(model)
        require(m['rows']==0 and m['columns']==width, 'CORAD stored model shape differs')
        mounted = fitted['processes']['c-train' if producer==C else 'source-train']['input_mounts']
        if producer==C:
            require(mounted=={'train':_identity(train)} and not fitted['training_assets'], 'CORAD C trainer received other inputs')
        else:
            assets = fitted['training_assets']
            vector = verify_asset(run,assets['train_vectors']).read_bytes()
            means, scales, v = _normalization([train[i:i+len(train)//width] for i in range(0,len(train),len(train)//width)],4,(1<<width)-1)
            dictionary = load_json(verify_asset(run,assets['dictionary_json']))['dictionary']
            arrays = [x for row in dictionary for x in row] + [x for pair in zip(means,scales,strict=True) for x in pair]
            require(set(mounted)=={STAGED_BRIDGE,VECTORS} and mounted[VECTORS]==_identity(vector) and
                    vector==_npy(v,len(v)//4,4) and struct.pack(f'<{len(arrays)}d',*arrays)==model_arrays,
                    'CORAD Source fit or deployment differs from train-only material')
        for i,(row,original,case) in enumerate(zip(evaluations,tests,binding['test_frames'],strict=True)):
            require(row['operation']=='heldout' and row['deployment_id']==deployment['deployment_id'] and
                    row['frame_range']==case['absolute_rows'] and _identity(original)==case['values'],
                    'CORAD held-out ledger range or dependency differs')
            if row['status'] not in {'verified','quality_rejected'}:
                continue
            frame = verify_asset(run,row['frame']).read_bytes()
            restored, meta, arrays = interpret(frame,max_values=131072)
            metrics, accepted = judge_quality(original,restored,names,bounds)
            require(len(frame)==row['frame']['bytes'] and arrays==model_arrays and
                    row['restore']==_identity(restored) and row['quality_gates']==bounds and
                    row['original_domain_metrics']==metrics and (row['status']=='verified')==accepted and
                    row['processes'][f'restore-{i}']['input_mounts']=={'frame':_identity(frame)},
                    'CORAD held-out frame, independent restore or quality decision differs')
