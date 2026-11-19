"""Freeze CORAD inference probes and their shared, bounded retention plan."""
from hashlib import sha256
from pathlib import Path

from ..assets import content_id, load_json, local_file, require
from ..corad_quality import calibrate
from ..plugins import resolve
from .corad_deployment import load_deployment
from .corpus_windows import bind_training_window, bind_window, read_tv_window

CONFIG = 'configs/suites/dev_corad_v1/cases.json'
METHOD = 'corad-frozen'
TEST = 'tsbench.worker.corad-frozen.recovery'
ROUTES = ('c-lars', 'source-sklearn')
DATA = 'corad-input.f64le'
QUALITY_CONFIG = 'configs/suites/dev_corad_v1/quality-policy.json'
CALIBRATION = 'corad-quality-calibration.f64le'
REJECTIONS = {'encode-without-model':3, 'column-order':2, 'unequal-row-count':2, 'wrong-dtype':1,
              'nonfinite':2, 'encode-value-budget':7, 'wrong-expected-model':5, 'wrong-expected-schema':5,
              'decode-value-budget':7, 'bad-reference':5, 'truncated':5, 'trailing-byte':5}


def plan_corad_inference(root: Path):
    cfg = load_json(local_file(root,CONFIG))
    cols, width, n = cfg['columns'], cfg['tricklet'], cfg['evaluation']['count']
    require(cfg['schema'] == 'bmk.dev-corad-cases/1' and cfg['selection'] == 80 and
            cfg['train']['partition'] == 'train' and cfg['evaluation']['partition'] == 'test' and
            type(n) is int and type(width) is int and 1 < width < n and n % width and 0 < n*len(cols) <= 16384,
            'invalid CORAD inference case configuration')
    manifests = [f'assets/manifests/corad-weather-{route}-v1.json' for route in ROUTES]
    deployments = [load_deployment(root,path) for path in manifests]
    policy = load_json(local_file(root,QUALITY_CONFIG))
    train_windows = [bind_training_window(root,cfg['corpus'],cfg['corpus_id'],{'dataset':cfg['dataset'],'column':col,**cfg['train']})
                     for col in cols]
    train = [read_tv_window(root,win) for win in train_windows]
    train_rows = cfg['train']['count']
    require(all(t == train[0][0] and len(v) == train_rows*8 for t,v in train), 'CORAD quality training alignment differs')
    calibration_cols = [v for _,v in train]
    calibration = b''.join(calibration_cols)
    quality = {'definition':policy,'calibration':{'path':CALIBRATION,'bytes':len(calibration),
                'sha256':sha256(calibration).hexdigest(),'rows':train_rows,'windows':train_windows},
               'bounds':calibrate(cols,calibration_cols,policy)}
    quality['policy_id'] = content_id(quality)
    windows = [bind_window(root,cfg['corpus'],cfg['corpus_id'],{'dataset':cfg['dataset'],'column':col,**cfg['evaluation']})
               for col in cols]
    data = [read_tv_window(root,win) for win in windows]
    require(all(t == data[0][0] and len(v) == n*8 for t,v in data), 'CORAD held-out timestamp/row alignment differs')
    require(int.from_bytes(train[0][0][-8:],'little',signed=True) < int.from_bytes(data[0][0][:8],'little',signed=True),
            'CORAD quality training and held-out clocks overlap')
    raw = [v for _,v in data]
    common = b''.join(raw)
    frame_specs, model_records = [], []
    decode_id = resolve(root,METHOD,{})['configuration_id']
    for route, manifest, (d,schema,model,options) in zip(ROUTES,manifests,deployments,strict=True):
        p = d['training']
        require(d['ordered_columns'] == cols and (p['route'],p['dataset'],p['corpus_id'],p['partition'],p['offset'],p['rows']) ==
                (route,cfg['dataset'],cfg['corpus_id'],'train',cfg['train']['offset'],cfg['train']['count']),
                'CORAD deployment provenance does not match its ordered training contract')
        config_id = resolve(root,METHOD,options)['configuration_id']
        model_records.append({'manifest':manifest,'definition':d,'configuration_id':config_id})
        for tag,count in (('held-out',n),('short-tail-only',width-1),('empty',0)):
            # An allocation/retention limit derived from CRD1 worst-case record lengths, not an observed size.
            upper = 24 + len(schema) + len(model) + len(cols)*((count//width)*(2+10*cfg['nonzero']) + (count%width)*8)
            frame_specs.append({'path':f'corad-{route}-{tag}.bmk','case':tag,'route':route,'rows':count,'columns':cols,
                                'native_configuration':{'rows':count,'columns':len(cols),'tricklet':width,'atoms':cfg['atoms'],
                                                        'nonzero':cfg['nonzero'],'threshold':cfg['threshold']},
                                'model_sha256':d['model']['sha256'],'model_asset_bytes':len(model),
                                'deployment_id':d['deployment_id'],'schema_hex':schema.hex(),'max_frame_bytes':upper,
                                'source_sha256':sha256(b''.join(v[:count*8] for v in raw)).hexdigest(),
                                'encode_configuration_id':config_id,'decode_configuration_id':decode_id})
    checks = []
    frame_ids = {r['path']:content_id(r) for r in frame_specs}

    def add(name, check, frames, rejections=(), **criteria):
        body = {'selection':80,'route':'corad-inference','name':name,'check':check,
                'artifacts':frames,'frame_spec_ids':[frame_ids[p] for p in frames],
                'rejections':{k:REJECTIONS[k] for k in rejections},'original_sha256':sha256(common).hexdigest(),**criteria}
        checks.append({**body,'case_id':content_id(body)})

    held = [f['path'] for f in frame_specs if f['case'] == 'held-out']
    add('ordered-heldout-columns','ordered_finite_columns',held,('column-order','unequal-row-count','nonfinite','wrong-dtype'))
    for route in ROUTES:
        add(route+'-tail','model_identity_and_short_tail',[f'corad-{route}-short-tail-only.bmk'])
        add(route+'-restore','isolated_crd1_restore',[f['path'] for f in frame_specs if f['route'] == route])
        add(route+'-original-error','original_domain_max_error_and_rmse',[f'corad-{route}-held-out.bmk'])
    add('wrong-model-order-budget','wrong_model_order_and_budget_rejected',held,
        ('wrong-expected-model','wrong-expected-schema','column-order','encode-value-budget','decode-value-budget'))
    add('heldout-predeclared-quality','bound_predeclared_before_formal_run',held,quality_policy_id=quality['policy_id'])
    body = {'schema':'bmk.corad-inference-cases/1','test':TEST,'evidence_path':'corad-worker-control.json',
            'config_id':content_id(cfg),'window':windows,'models':model_records,'frames':frame_specs,'cases':checks,
            'input':{'path':DATA,'bytes':len(common),'sha256':sha256(common).hexdigest(),'rows':n,'columns':cols},
            'rejections':REJECTIONS,'quality_policy':quality}
    return {**body,'bundle_id':content_id(body)}, deployments, raw, calibration


def retained_paths(bundle):
    policy = bundle['quality_policy']
    return [bundle['input']['path'], *([policy['calibration']['path']] if isinstance(policy,dict) else []),
            *[r['path'] for r in bundle['frames']]]
