"""Recompute CORAD training input, model, solver and held-out evidence offline."""
import ast
import math
import re
import struct

from ..assets import ContractError, canonical_bytes, content_id, load_json, local_file, parse_json, require
from ..planner.corad_training import DIR, STAGED_BRIDGE, VECTORS, ref, retained_paths, source_argv
from .corad_wire import HEADER, interpret, quality


def exact(value, expected, msg):
    require(canonical_bytes(value)==canonical_bytes(expected),msg)


def npy_values(data, rows, cols):
    """Narrow little-endian NPY 1.0 transport; no pickle or NumPy backend needed."""
    require(len(data)>=10 and data[:8]==b'\x93NUMPY\x01\0','invalid CORAD training matrix header')
    stop = 10+int.from_bytes(data[8:10],'little')
    require(10<stop<=min(1024,len(data)) and data[stop-1:stop]==b'\n' and (len(data)-stop)==rows*cols*8,
            'invalid CORAD training matrix extent')
    try:
        meta = ast.literal_eval(data[10:stop].decode('ascii').strip())
    except (ValueError, SyntaxError, RecursionError) as exc:
        raise ContractError('invalid CORAD NPY metadata') from exc
    require(isinstance(meta,dict) and meta=={'descr':'<f8','fortran_order':False,'shape':(rows,cols)} and
            meta['fortran_order'] is False and all(type(n) is int for n in meta['shape']),
            'invalid CORAD NPY dtype, layout or shape')
    raw = struct.unpack_from(f'<{rows*cols}d',data,stop)
    require(all(map(math.isfinite,raw)),'CORAD training vectors contain nonfinite values')
    return raw


def _data(bundle, read):
    parts = {}
    for key in ('train','evaluation'):
        d = bundle['data'][key]
        ticks, raw = (read(d[k]['path']) for k in ('timestamps','values'))
        for label,body in (('timestamps',ticks),('values',raw)):
            exact(ref(d[label]['path'],body),d[label],'CORAD retained training/evaluation identity differs')
        times = [t for (t,) in struct.iter_unpack('<q',ticks)]
        require(times and (times[0],times[-1])==(d['first_timestamp'],d['last_timestamp']) and
                all(a<b for a,b in zip(times,times[1:])) and len(raw)==len(bundle['columns'])*len(ticks),
                'CORAD retained input time/column shape differs')
        parts[key] = [raw[i:i+len(ticks)] for i in range(0,len(raw),len(ticks))]
    require(bundle['data']['train']['last_timestamp'] < bundle['data']['evaluation']['first_timestamp'],
            'CORAD held-out training leakage')
    return parts['train'],parts['evaluation']


def _normalization(columns, width, mask):
    arr = [struct.unpack(f'<{len(raw)//8}d',raw) for raw in columns]
    require(all(math.isfinite(v) for xs in arr for v in xs),'nonfinite CORAD training input')
    means = [math.fsum(xs)/len(xs) for xs in arr]
    scales = [math.sqrt(math.fsum((x-m)**2 for x in xs)/len(xs)) or 1.0 for xs,m in zip(arr,means,strict=True)]
    vectors = [(x-means[j])/scales[j] for j,xs in enumerate(arr) if (mask>>j)&1 for x in xs[:len(xs)//width*width]]
    return means, scales, vectors


def _close(actual, want, tolerance, message):
    require(len(actual)==len(want) and all(math.isclose(a,b,rel_tol=0,abs_tol=tolerance)
                                           for a,b in zip(actual,want,strict=True)),message)


def _c(record, bundle, read):
    opts, cap = bundle['c_options'],bundle['policy']['c']['seeded_repetitions']
    require(isinstance(record,dict) and record.keys()=={'options','fits','analytical_controls','rejections'},
            'CORAD C training record differs')
    exact(record['options'],opts,'CORAD effective C seed/mask/options differ')
    exact(record['rejections'],bundle['native_rejections'],'CORAD C sample/mask or sparse failure differs')
    # Solve the axis-aligned LASSO independently, including its objective and KKT condition.
    expected = [math.copysign(max(abs(y)-opts['alpha'],0),y) for y in (2.,-1.)]
    kkt = max(abs(x-y+math.copysign(opts['alpha'],x)) for x,y in zip(expected,(2.,-1.),strict=True))
    objective = math.fsum(0.5*(x-y)**2+opts['alpha']*abs(x) for x,y in zip(expected,(2.,-1.),strict=True))
    exact(record['analytical_controls'],[{'solver':solver,'coefficients':expected,'kkt':kkt,
          'fixed_dictionary':[1.,0.,0.,1.],'expected_objective':objective,'stats':{'training_samples':2,'resampled_atoms':0,
          'iterations':2,'converged':1,'objective':objective,'max_kkt_violation':kkt}} for solver in (0,1)],
          'CORAD LARS/CD analytical solution or inner/outer report differs')
    fits = record['fits']
    require(isinstance(fits,list) and len(fits)==cap and all(isinstance(r,dict) for r in fits),
            'CORAD C seeded repetition closure differs')
    model_id = ref('c-lars.model.crd1',read('c-lars.model.crd1'))
    stats = fits[0].get('stats')
    require(isinstance(stats,dict) and stats.keys()=={'training_samples','iterations','converged','objective','max_kkt_violation','resampled_atoms'}
            and type(stats['resampled_atoms']) is int and 0<=stats['resampled_atoms']<=opts['max_iter']*bundle['model']['atoms']
            and type(stats['objective']) in (int,float) and math.isfinite(stats['objective']) and stats['objective']>=0
            and type(stats['max_kkt_violation']) in (int,float) and 0<=stats['max_kkt_violation']<=opts['solver_tolerance']*10,
            'CORAD C training stats or KKT bound differs')
    exact([stats['training_samples'],stats['iterations'],stats['converged']],
          [opts['max_training_samples'],opts['max_iter'],0],'CORAD outer iteration limit is not convergence')
    exact(fits,[{'model':model_id,'stats':stats}]*cap,'CORAD C training model or seeded repeat differs')


def _source(record, bundle, read, python_sha256, vectors):
    opts, spec = bundle['c_options'],bundle['model']
    samples, width = opts['max_training_samples'],spec['tricklet']
    blob = read(VECTORS)
    _close(npy_values(blob,samples,width),vectors,bundle['policy']['statistics_absolute_tolerance'],
           'CORAD staged matrix is not the ordered train-only tricklets')
    bridge = ref(STAGED_BRIDGE,read(STAGED_BRIDGE))
    require(bridge['sha256']==bundle['bridge_sha256'],'CORAD shipped Source bridge changed')
    require(isinstance(record,dict),'CORAD Source training record missing')
    runs = record.get('runs')
    exact(record,{'policy':bundle['policy']['source'],'environment_lock_sha256':bundle['environment_lock_sha256'],
                  'python_sha256':python_sha256,'bridge':bridge,'train_vectors':ref(VECTORS,blob),'runs':runs},
          'CORAD Source environment, script or matrix identity differs')
    require(isinstance(runs,list) and len(runs)==bundle['policy']['source']['fresh_processes']==len(bundle['source_labels']),
            'CORAD Source repetition closure differs')
    dicts = {}
    for label,row in zip(bundle['source_labels'],runs,strict=True):
        require(isinstance(row,dict) and all(isinstance(row.get(k),str) for k in ('stdout','stderr')) and
                len(row['stdout'])+len(row['stderr'])<=bundle['policy']['capacity_bytes_per_artifact'],
                'CORAD Source process log is missing or exceeds bound')
        name = label+'.json'
        raw = read(name)
        try:
            dictionary = parse_json(raw.decode('utf-8'),name)
        except UnicodeError as exc:
            raise ContractError('invalid Source dictionary text') from exc
        parsed = dictionary.get('dictionary') if isinstance(dictionary,dict) else None
        require(isinstance(parsed,list) and len(parsed)==spec['atoms'] and
                all(isinstance(a,list) and len(a)==width and all(type(x) in (float,int) and math.isfinite(x) for x in a) for a in parsed),
                'CORAD Source dictionary shape or finiteness differs')
        exact(dictionary,{'backend':'upstream-CORAD-sklearn-DictionaryLearning','max_iter':bundle['policy']['source']['max_iter'],
                          'alpha':opts['alpha'],'rows':samples,'features':width,'dictionary':parsed},
              'CORAD Source dictionary options or rows differ')
        exact(row,{'origin':label,'argv':source_argv(bundle,label),'returncode':0,'dictionary':ref(name,raw),
                   'stdout':row['stdout'],'stderr':row['stderr']},'CORAD Source actual argv or output identity differs')
        dicts[label] = b''.join(struct.pack(f'<{width}d',*atom) for atom in parsed)
    return dicts


def _infer(label, reported, bundle, read, train_stats, held, expected_dictionary):
    exact(reported,inference_evidence(label,bundle,read,train_stats,held,expected_dictionary),
          'CORAD held-out accounting, metrics or rejection differs')


def inference_evidence(label, bundle, read, train_stats, held, expected_dictionary):
    spec = bundle['model']
    rows, width = len(held[0])//8,spec['tricklet']
    config = (spec['columns'],width,spec['atoms'],spec['nonzero'],spec['threshold'])
    model_path, frame_path, decoded_path = (label+s for s in ('.model.crd1','.heldout.crd1','.restored.f64le'))
    model, frame, decoded = (read(name) for name in (model_path,frame_path,decoded_path))
    native, stats, embedded = interpret(model)
    restored, counts, frame_embedded = interpret(frame)
    require(not native and HEADER.unpack_from(model)==(b'CRD1',0,*config,len(model)) and
            HEADER.unpack_from(frame)==(b'CRD1',rows,*config,len(frame)) and embedded==frame_embedded,
            'CORAD trained model is not the exact embedded held-out model')
    if expected_dictionary is not None:
        require(embedded[:len(expected_dictionary)]==expected_dictionary,'CORAD packed dictionary differs from Source output')
    means, scales = train_stats
    tolerance = bundle['policy']['statistics_absolute_tolerance']
    _close(stats['mean'],means,tolerance,'CORAD packed means are not train-only statistics')
    _close(stats['scale'],scales,tolerance,'CORAD packed scales are not train-only statistics')
    require(restored==decoded,'CORAD raw CRD1 differs from detached native restore')
    columns = [restored[i:i+rows*8] for i in range(0,len(restored),rows*8)]
    tail = rows%width*8
    require(tail>0 and all(a[-tail:]==b[-tail:] for a,b in zip(held,columns,strict=True)),
            'CORAD held-out original tail differs')
    requires = {'nan_atom':4,'trailing_byte':4,'truncated':4,'max_values':2,'model_load_data_frame':2}
    if counts['first_reference'] is not None:
        requires['self_reference'] = 4
    return {'origin':label,'model':ref(model_path,model),'frame':ref(frame_path,frame),'restored':ref(decoded_path,decoded),
            'sections':counts,'quality':quality(held,columns,bundle['columns']),'rejections':requires,
            'config':{'rows':rows,**spec}}


def verify_corad_training(bundle, build, driver, python_sha256, out, *, sealed_paths=None):
    require(bundle['bundle_id']==content_id({k:v for k,v in bundle.items() if k!='bundle_id'}),'CORAD training bundle identity differs')
    require(sealed_paths is None or retained_paths(bundle)|{bundle['evidence_path']}<=sealed_paths,'CORAD training evidence is not sealed')
    report = load_json(local_file(out,bundle['evidence_path']))
    require(isinstance(report,dict) and isinstance(report.get('diagnostic_id'),str) and
            re.fullmatch('[0-9a-f]{32}',report['diagnostic_id']) and build.keys()=={'libcorad_c.so','train.py'} and
            build['train.py']==bundle['bridge_sha256'],'CORAD training build/source closure differs')
    omit = {'diagnostic_id','c_training','source_training','inference'}
    exact({k:v for k,v in report.items() if k not in omit},
          {'schema':'bmk.corad-native-control/2','config_id':bundle['config_id'],'bundle_id':bundle['bundle_id'],
           'data':bundle['data'],'archive_sha256':bundle['archive_sha256'],'corad_library_sha256':build['libcorad_c.so'],
           'probe_sha256':driver,'formal_performance':False,'formal_qualification':False},'CORAD training evidence identity differs')

    def read(name):
        path = local_file(out,DIR+'/'+name)
        require(path.stat().st_size<=bundle['policy']['capacity_bytes_per_artifact'],'CORAD training artifact exceeds bound')
        return path.read_bytes()

    train, held = _data(bundle,read)
    means, scales, vectors = _normalization(train,bundle['model']['tricklet'],bundle['c_options']['training_columns'])
    _c(report.get('c_training'),bundle,read)
    dictionaries = _source(report.get('source_training'),bundle,read,python_sha256,vectors)
    inference = report.get('inference')
    require(isinstance(inference,list) and len(inference)==len(bundle['models']),'CORAD trained model evaluation closure differs')
    for label,row in zip(bundle['models'],inference,strict=True):
        _infer(label,row,bundle,read,(means,scales),held,dictionaries.get(label))
