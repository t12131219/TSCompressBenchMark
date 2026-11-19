"""Check the actual fixed-T pair, five-value limb shapes, and native rejections."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import run_worker
from tsbench.api import plan_tv, report_tv
from tsbench.application.tv import ENTRY, HEADER, _args, inspect_bundle
from tsbench.assets import load_json, require, canonical_bytes
from tsbench.planner import tv
from tsbench.qualification.sprintz import GROUP_HEADER
from integration.tv_composition import rejected


DIRECT = 'gorilla-t-alp-f64'
GROUPED = 'gorilla-t-fire-u16'


def main(root, run, build_lock, cli_plan):
    plan = load_json(run/'plan.json')
    require(plan_tv(root,build_lock,plan['suite_path'])==load_json(cli_plan)==plan,'CLI and Python plans differ')
    report = report_tv(run)
    require(report['statuses']=={'verified':4} and not report['qualification_granted'],'unexpected five-value run coverage')
    rows = {(r['method'],r['case']):r for r in report['slots']}
    audits = {}
    for case, fact in plan['cases'].items():
        direct, grouped = rows[DIRECT,case], rows[GROUPED,case]
        a, b = direct['accounting'], grouped['accounting']
        require(fact['logical_bytes']==48*515 and len(fact['column_sha256'])==6,'incorrect original-object denominator')
        require(len({o['session_id'] for r in (direct,grouped) for o in r['operations']})==4,'methods must not share sessions')
        require(direct['restored']==grouped['restored'],'the methods must restore the identical original object')
        for r,p in ((direct,a),(grouped,b)):
            require(p['bundle_bytes']==r['artifact']['bytes']==p['container_bytes']+p['schema_bytes']+p['stream_bytes'],
                    'serialized bytes not conserved')
        require(len(a['streams'])==12 and len(b['streams'])==4,'incorrect number of V streams')
        a_t, b_t = ([s['sha256'] for s in p['streams'] if s['first_column']==0] for p in (a,b))
        require(len(a_t)==2 and a_t==b_t,
                'independently encoded fixed T streams differ')
        require([(s['row'],s['rows'],s['first_column'],s['column_count']) for s in b['streams']]==
                [(0,512,0,1),(0,512,1,5),(512,3,0,1),(512,3,1,5)],'grouped directory differs')
        packed = [s['packed_value'] for s in b['streams'] if s['first_column']]
        require([(s['logical_value_columns'],s['encoded_channels'],s['raw_bytes']) for s in packed]==[(5,20,20480),(5,20,120)] and
                packed[0]['packed_blocks']>0 and packed[1]['packed_blocks']==0 and packed[1]['literal_values']==60,
                'did not exercise generic packing and a three-row literal tail')
        audits[case] = {'fixed_timestamp_frames_match':True,'distinct_sessions':True,
                        'raw_object_bytes':fact['logical_bytes'],'direct_bundle_bytes':a['bundle_bytes'],
                        'grouped_bundle_bytes':b['bundle_bytes'],'grouped_native_blocks':packed}
    bad = {}
    original_load = tv.load_json
    def edit_suite(label, change, reason):
        suite = deepcopy(plan['suite'])
        change(suite)
        with patch.object(tv,'load_json',side_effect=lambda f:suite if f==root/plan['suite_path'] else original_load(f)):
            bad[label] = rejected(lambda:tv.compile_tv(root,plan['suite_path'],plan['build'],plan['recovery']),reason)
    edit_suite('wrong_lanes',lambda s:s['profiles']['fire-u16-group']['options'].update(lanes=16),'four u16 lanes')
    edit_suite('missing_transform',lambda s:s['methods'][GROUPED].pop('value_transform'),'explicit compatible transform')
    edit_suite('direct_f64_codec_in_group',lambda s:s['methods'][GROUPED].update(value='alp-f64'),'four u16 lanes')
    edit_suite('value_columns_mismatch',lambda s:s['cases']['five-value-edge-bits'].update(fixture='edge-bits'),'column count differs')
    edit_suite('lanes_exceed_api_limit',lambda s:s['profiles']['fire-u16-group']['options'].update(lanes=129),'plugin option outside maximum: lanes')

    sample = rows[GROUPED,'five-value-edge-bits']
    case, method = plan['cases'][sample['case']], plan['methods'][GROUPED]
    data = (run/sample['artifact']['path']).read_bytes()
    child = sample['accounting']['streams'][1]
    wire = child['offset']+child['packed_value']['physical_envelope_bytes']
    with tempfile.TemporaryDirectory(prefix='tv-limb-controls-') as work:
        work = Path(work)
        artifact, schema = work/'mutated.tvb', work/'schema.json'
        paths = [work/f'column-{i}.bin' for i in range(6)]
        worker = root/plan['build']['worker']['path']
        libs = {p:root/v['library']['path'] for p,v in plan['build']['plugins'].items()}
        argv = _args(plan,sample,'decode',artifact,schema,paths,worker,libs)

        def native_error(label, data, args, expected):
            artifact.write_bytes(data)
            res = run_worker(work,args,check=False)
            error = res.stderr.decode().strip()
            require(res.returncode==3 and expected in error and not schema.exists() and not any(x.exists() for x in paths),
                    f'{label}: did not reject without output: {error}')
            bad[label] = error

        def edit_native_byte(field, val):
            edited = bytearray(data)
            edited[field] = val
            # Leave the outer CRC correct: this alteration must reach the codec.
            inner = edited[child['offset']:child['offset']+child['bytes']]
            struct.pack_into('<I',edited,HEADER.size+ENTRY.size+32,zlib.crc32(inner))
            return bytes(edited)

        edited = edit_native_byte(wire+8,16)
        bad['sfb1_wrong_lane_field_report'] = rejected(lambda:inspect_bundle(edited,case,method,512),'frame configuration')
        native_error('sfb1_wrong_lane_field_decoder',edited,argv,'invalid native SFB1')
        # Alter u16 count without touching the native frame; the envelope must reject incomplete rows.
        edited = edit_native_byte(child['offset']+12,(512*20+1)&255)
        native_error('partial_u16_row',edited,argv,'incomplete u16 lane row')
        assert GROUP_HEADER.size < child['packed_value']['physical_envelope_bytes']
        for name,opts in [('out_of_range','{"lanes":129}'),('non_integral','{"lanes":20.0}'),('duplicate','{"lanes":20,"lanes":20}')]:
            args = argv.copy()
            args[14] = opts
            native_error(name,data,args,'plugin status')
        edited = bytearray(data)
        struct.pack_into('<I',edited,HEADER.size+ENTRY.size+12,4)
        native_error('directory_short_value_group',edited,argv,'row/column index')
    return {'schema':'bmk.dev-tv-limb-controls/1','run_id':report['run_id'],'seal_id':report['seal_id'],
            'fixed_t_pairs':audits,'rejections':bad,'qualification_granted':False}


if __name__=='__main__':
    _, root, run, build_lock, cli_plan = sys.argv
    result = main(Path(root).resolve(strict=True),Path(run).resolve(strict=True),build_lock,Path(cli_plan))
    sys.stdout.buffer.write(canonical_bytes(result)+b'\n')
