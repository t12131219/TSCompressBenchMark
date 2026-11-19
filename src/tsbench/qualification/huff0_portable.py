"""Recompute Huff0 same-run portable work and recovery evidence from the ledger."""
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..planner.huff0 import CONTROL, DECODE_API, ENVELOPE, ref
from ..planner.huff0_portable import BINARIES, DRIVER, RECIPE, REPORT, TEST
from .huff0 import _calls, _exact


def portable_cases(primary, source):
    """Yield native decoder inputs and expected recovery, never the original columns."""
    for row in primary['fec1_cases']:
        artifact = row['artifact']
        frame = local_file(source,artifact['path']).read_bytes()
        _exact(ref(artifact['path'],frame),artifact,'Huff0 primary frame has changed')
        payload = frame[ENVELOPE.size+row['schema_bytes']:]
        require(ref('',payload)['sha256']==row['fec_sha256'] and len(payload)==row['fec_bytes'], 'Huff0 FEC1 payload has changed')
        yield ('fec1',row['name'],0,[artifact],[payload],None,None,
               [row['direct_restored_sha256']],row['direct_backend'])
    for row in primary['etb1_profiles']:
        model = row['model']
        artifacts = [b['artifact'] for b in row['blocks']]
        data = [local_file(source,a['path']).read_bytes() for a in artifacts]
        model_bytes = local_file(source,model['path']).read_bytes()
        _exact([ref(a['path'],raw) for a,raw in zip([model,*artifacts],[model_bytes,*data],strict=True)],
               [model,*artifacts], 'Huff0 primary ETB1 blocks or model changed')
        yield ('etb1',f"{row['profile']}-{row['streams']}x",1 if row['streams']==1 else 2,
               artifacts,data,model,model_bytes,[b['restored_sha256'] for b in row['blocks']],row['direct_backend'])


def comparison_binding(document):
    bindings = document['bindings']
    control = bindings.get('huff0_portable_control')
    slots = document['slots']
    if control is None:
        require(not any(s.get('test')==TEST or 'requires_slot' in s for s in slots), 'unbound Huff0 portable control')
        return None
    require(control.get('control_id')==content_id({k:v for k,v in control.items() if k!='control_id'}) and
            control.get('schema')=='bmk.huff0-portable-control-plan/1' and control.get('test')==TEST and
            control.get('evidence_path')==REPORT and control.get('bundle_id')==bindings['huff0']['bundle_id'] and
            control.get('comparison')=='same_run_primary_fec1_payload_etb1_blocks_and_models' and
            set(control.get('normalized_build_recipe',{}))=={f'{d}/{f}' for d in RECIPE for f in ('flags.make','link.txt')},
            'invalid Huff0 portable control binding')
    inputs = bindings['command_inputs']
    assets = [f'project:{DRIVER}',*(f'huff0_portable:{p}' for p in BINARIES)]
    expected = [{'python':True},{'literal':'-I'},{'literal':'-B'},*({'asset':p} for p in assets),
                {'input_slot':control['primary_slot_id']},{'output':REPORT}]
    primary = [s for s in slots if s['test']==bindings['huff0']['test']]
    portable = [s for s in slots if s['test']==TEST]
    require(len(primary)==len(portable)==1 and slots.index(primary[0])<slots.index(portable[0]) and
            primary[0]['slot_id']==control['primary_slot_id'] and portable[0]['slot_id']==control['control_slot_id'] and
            [s for s in slots if 'requires_slot' in s]==portable and
            portable[0]['requires_slot']==primary[0]['slot_id'] and portable[0]['command']==expected and
            portable[0]['evidence']==[REPORT] and all(inputs[k]['root']==k.split(':',1)[0] and
            inputs[k]['path']==k.split(':',1)[1] for k in assets) and
            {g['archive_sha256'] for g in document['groups'] if g['selection']==29}=={control['archive_sha256']},
            'Huff0 portable control does not bind primary evidence and separate binary inputs')
    return control


def verify_portable_control(document, run, control):
    bindings = document['bindings']
    bundle = bindings['huff0']
    source = run/'slots'/control['primary_slot_id']
    primary_path = local_file(source,bundle['evidence_path'])
    primary = load_json(primary_path)
    out = local_file(run,f"slots/{control['control_slot_id']}/{REPORT}")
    report = load_json(out)
    inputs = bindings['command_inputs']
    binary = {Path(p).name:inputs[f'huff0_portable:{p}']['sha256'] for p in BINARIES}
    require(isinstance(report,dict) and isinstance(rows:=report.get('rows'),list) and
            len(rows)==len(bundle['fec1'])+len(bundle['etb1']), 'Huff0 portable result denominator differs')
    _exact({k:v for k,v in report.items() if k!='rows'},
           {'schema':'bmk.huff0-portable-decode/1','primary_report_sha256':digest(primary_path),'bundle_id':bundle['bundle_id'],
            'driver_sha256':inputs[f'project:{DRIVER}']['sha256'],'binaries':binary,
            'formal_qualification':False},'Huff0 portable decode is not bound to this primary report and build')
    baseline = primary['fec1_cases'][0]['direct_backend']
    require(baseline['dynamic_bmi2_compiled'] is True, 'Huff0 primary is not the dynamic build')
    dynamic, portable = dict.fromkeys(DECODE_API,0),dict.fromkeys(DECODE_API,0)
    for case,row in zip(portable_cases(primary,source),rows,strict=True):
        kind,name,api,artifacts,_,model,_,restored,original = case
        require(isinstance(row,dict) and isinstance(native:=row.get('native'),dict), 'missing Huff0 portable case')
        counts = original['completed_decode_calls'][api]
        _calls(native,(False,baseline['cpu_bmi2_available']),api,sum(counts),original['streams'],original['effective_table_log'])
        _exact(row,{'kind':kind,'case':name,'artifacts':artifacts,'model':model,'restored_sha256':restored,'native':native},
               'Huff0 portable used different frames/models or did not recover the same bits')
        entry = DECODE_API[api]
        dynamic[entry] += counts[1]
        portable[entry] += native['completed_decode_calls'][api][0]
    require(all(portable.values()) and (not baseline['cpu_bmi2_available'] or dynamic==portable),
            'Huff0 primary and portable did not observe matched native decode work')
    return {'path':out.relative_to(run).as_posix(),'sha256':digest(out),'control_id':control['control_id'],
            'binaries':binary,'same_run_decoded_cases':len(rows),'dynamic_bmi2_calls':dynamic,'portable_calls':portable}
