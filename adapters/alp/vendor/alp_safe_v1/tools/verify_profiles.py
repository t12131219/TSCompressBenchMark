#!/usr/bin/env python3
"""Replay frozen corpus artifacts through an additional compiled profile.
Both encode directions and both cold decode directions are checked. All
binary32/64 and methods; ARM may use frozen first-numeric-column real subset.
"""
import argparse,hashlib,json,pathlib,subprocess
from verify import run,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--artifacts',type=pathlib.Path,required=True)
    p.add_argument('--cli',type=pathlib.Path,required=True);p.add_argument('--base-cli',type=pathlib.Path,default=pathlib.Path('build/release/alp_cli'))
    p.add_argument('--first-real-column',action='store_true');p.add_argument('--out',type=pathlib.Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    source=json.loads((a.artifacts/'verification.json').read_text());rows=[];commands=[]
    for case in source['cases']:
        if a.first_real_column and case['kind']=='real' and case['column_index']!=1:continue
        d=case['dtype'];m=case['method'];directory=a.artifacts/case['case'];raw=directory/'input.raw';base=directory/(m+'.frame')
        out=a.out/(case['case']+'_'+m);out.mkdir(exist_ok=True);frame=out/'profile.frame';cross=out/'profile.decoded';back=out/'base.decoded'
        row={'case':case['case'],'method':m,'dtype':d,'input_sha256':case['input_sha256'],'count':case['count']};rows.append(row)
        run([a.cli,'encode',d,m,raw,frame,1],commands)
        run([a.cli,'decode',d,m,base,cross,1],commands)
        run([a.base_cli,'decode',d,m,frame,back,1],commands)
        row.update({'frame_sha256':sha(frame.read_bytes()),'byte_identical':frame.read_bytes()==base.read_bytes(),'profile_decodes_base':sha(cross.read_bytes())==case['input_sha256'],'base_decodes_profile':sha(back.read_bytes())==case['input_sha256']})
        if not row['profile_decodes_base'] or not row['base_decodes_profile']:raise RuntimeError(row)
        cross.unlink();back.unlink()
    report={'profile_cli':str(a.cli),'cli_sha256':sha(a.cli.read_bytes()),'selection':'all synthetic and first numeric column of each real file' if a.first_real_column else 'all frozen cases','source_verification_sha256':sha((a.artifacts/'verification.json').read_bytes()),'cases':rows,'totals':{'cases':len(rows),'pass':len(rows),'fail':0,'values':sum(x['count'] for x in rows),'byte_identical':sum(x['byte_identical'] for x in rows)}}
    (a.out/'profiles.json').write_text(json.dumps(report,indent=2)+'\n');(a.out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');print(json.dumps(report['totals']))

if __name__=='__main__':main()
