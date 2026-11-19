"""Actual fixed-route controls and native corruption rejections for one sealed TV run."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import run_worker
from tsbench.api import plan_tv, report_tv
from tsbench.application.tv import ENTRY, HEADER, _args, _fields
from tsbench.assets import ContractError, canonical_bytes, load_json, require
from tsbench.planner import tv
from tsbench.plugins import registrations


def rejected(fn, fragment):
    try:
        fn()
    except ContractError as exc:
        require(fragment in str(exc),f'different rejection: {exc}')
        return str(exc)
    raise AssertionError('unexpected acceptance')


def main(root, run, build_lock, cli_plan):
    plan = load_json(run/'plan.json')
    require(plan_tv(root,build_lock)==load_json(cli_plan)==plan,'CLI and Python plans differ')
    report = report_tv(run)
    require(report['statuses']=={'verified':15} and not report['qualification_granted'],'unexpected TV run coverage')
    rows = {(r['method'],r['case']):r for r in report['slots']}
    audits = []
    for group, divs in plan['comparisons'].items():
        g = plan['suite']['comparisons'][group]
        for case, comparison in divs.items():
            pair = [rows[n,case] for n in g['methods']]
            require(len({r['artifact']['sha256'] for r in pair})==2 and len({o['session_id'] for r in pair for o in r['operations']})==4,
                    'control reused another method artifact or runtime session')
            assert all(r['accounting']['bundle_bytes']==r['artifact']['bytes']==r['accounting']['stream_bytes']+
                       r['accounting']['schema_bytes']+r['accounting']['container_bytes'] for r in pair)
            control = g['control']
            if control is not None:
                timestamp = control=='fixed_timestamp_route'
                filtered = [[s['sha256'] for s in r['accounting']['streams'] if (s['first_column']==0)==timestamp] for r in pair]
                require(filtered[0] and filtered[0]==filtered[1],'fixed branch did not get identical codec frames')
            audits.append({'group':group,'case':case,'comparison_ids':{d:x['comparison_id'] for d,x in comparison.items()},
                           'sessions_distinct':True,'fixed_streams_match':True if control else None,
                           'serialized_bundle_bytes':{r['method']:r['artifact']['bytes'] for r in pair}})
    specimen = rows['gorilla-t-gorilla-v','traffic-multi-value-tail']
    directory = [(s['row'],s['rows'],s['first_column']) for s in specimen['accounting']['streams']]
    require(directory==[(row,n,col) for row,n in ((0,512),(512,3)) for col in range(3)], 'timestamp duplicated or tail misaligned')
    bad = {}
    real_load = tv.load_json
    def mutate(name, fun, reason):
        suite = deepcopy(plan['suite'])
        fun(suite)
        with patch.object(tv,'load_json',side_effect=lambda f:suite if f==root/plan['suite_path'] else real_load(f)):
            bad[name] = rejected(lambda:tv.compile_tv(root,plan['suite_path'],plan['build'],plan['recovery']),reason)
    mutate('wrong_plugin_role',lambda s:s['profiles']['gorilla-t'].update(role='value'),'plugin role')
    mutate('non_fixed_t',lambda s:s['comparisons']['fixed-t']['methods'].__setitem__(1,'raw-t-gorilla-v'),'hold one route fixed')
    mutate('paired_codec_given_two_values',lambda s:s['comparisons']['native-vs-composed']['cases'].append('traffic-multi-value-tail'),
           'exactly one value column')
    real_window = tv.read_tv_window
    def wrong_time_axis(base, ref):
        stamps, values = real_window(base,ref)
        if ref['column']=='channel_27':
            first = struct.unpack_from('<q',stamps)[0]
            stamps = struct.pack('<q',first+1)+stamps[8:]
        return stamps,values
    with patch.object(tv,'read_tv_window',side_effect=wrong_time_axis):
        bad['mismatched_value_time_axis'] = rejected(lambda:plan_tv(root,build_lock),'time axis')
    with tempfile.TemporaryDirectory(prefix='tv-controls-') as work:
        work = Path(work)
        (work/'catalog').mkdir()
        text = (root/'catalog/plugins.toml').read_text()
        old = '[plugins."raw-timestamp"]\nenabled = true'
        require(old in text,'test provider unavailable')
        (work/'catalog/plugins.toml').write_text(text.replace(old,old.replace('true','false')))
        with patch('tsbench.plugins.registrations',return_value=registrations(work)):
            bad['disabled_t_provider'] = rejected(lambda:plan_tv(root,build_lock),'disabled plugin')
        bad['non_exact_timestamp_unit'] = rejected(lambda:tv.exact_ticks(struct.pack('<q',1001),'ms','s'),'non-exact')
        bad['timestamp_overflow'] = rejected(lambda:tv.exact_ticks(struct.pack('<q',2**63-1),'s','ms'),'overflowing')
        payload = (run/specimen['artifact']['path']).read_bytes()
        worker = root/plan['build']['worker']['path']
        libs = {p:root/v['library']['path'] for p,v in plan['build']['plugins'].items()}
        artifact = work/'mutated.tvb'
        schema = work/'schema'; paths = [work/f'out-{i}' for i in range(3)]
        argv = _args(plan,specimen,'decode',artifact,schema,paths,worker,libs)
        def native_rejection(label, blob, reason):
            artifact.write_bytes(blob)
            p = run_worker(work,argv,check=False)
            text = p.stderr.decode().strip()
            require(p.returncode==3 and reason in text and not schema.exists() and not any(x.exists() for x in paths),
                    f'{label} did not refuse without output: {text}')
            bad[label] = {'returncode':p.returncode,'reason':text,'no_output':True}
        def edit(at, value):
            return payload[:at]+value+payload[at+len(value):]
        native_rejection('missing_t_entry',edit(HEADER.size+24,bytes(8)),'invalid/missing TV stream')
        native_rejection('wrong_column_index',edit(HEADER.size+ENTRY.size+8,struct.pack('<I',2)),'row/column index')
        native_rejection('wrong_tail_row',edit(HEADER.size+3*ENTRY.size,struct.pack('<I',511)),'row/column index')
        native_rejection('wrong_method_identity',edit(32,b'0'*64),'method, layout')
        native_rejection('damaged_stream_crc',edit(len(payload)-1,bytes([payload[-1]^1])),'CRC mismatch')
        native_rejection('trailing_data',payload+b'\0','trailing TV data')
        _,_,n_columns,_ = _fields(plan,specimen)
        assert n_columns==3
        for i,path in enumerate(paths):
            path.write_bytes(bytes((514 if i==2 else 515)*8))
        schema.write_bytes(canonical_bytes(plan['cases'][specimen['case']]['schema']))
        artifact.unlink()
        enc = _args(plan,specimen,'encode',artifact,schema,paths,worker,libs)
        p = run_worker(work,enc,check=False)
        require(p.returncode==3 and b'row mismatch' in p.stderr and not artifact.exists(),'misaligned input was not rejected')
        bad['misaligned_source_column'] = {'returncode':p.returncode,'reason':p.stderr.decode().strip(),'no_output':True}
    return {'schema':'bmk.dev-tv-controls/1','run_id':report['run_id'],'seal_id':report['seal_id'],
            'control_pairs':audits,'rejections':bad,'qualification_granted':False}


if __name__=='__main__':
    _, root, run, build_lock, cli_plan = sys.argv
    result = main(Path(root).resolve(strict=True),Path(run).resolve(strict=True),build_lock,Path(cli_plan))
    sys.stdout.buffer.write(canonical_bytes(result)+b'\n')
