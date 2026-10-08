"""Bounded parallel Archify CLI validation; preserve every receipt."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys

OUT=Path(__file__).resolve().parent
CLI='/home/fzg/.codex/skills/archify/bin/archify.mjs'
NODE='/home/fzg/.nvm/versions/node/v24.19.0/bin/node'
mode=sys.argv[1] if len(sys.argv)>1 else 'validate'
def check(path):
    args=([NODE,CLI,mode,str(path.with_suffix('.html')),'--json'] if mode=='visual-check' else [NODE,CLI,mode,'architecture',str(path)])
    if mode=='deliver':args.append(str(path.with_suffix('.html')))
    if mode!='visual-check':args+=['--quality','showcase','--json']
    call=subprocess.run(args,capture_output=True,text=True)
    try:receipt=json.loads(call.stdout)
    except ValueError:receipt=dict(error=call.stderr or call.stdout)
    (OUT/(path.stem+'.'+mode+'-receipt.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return dict(page=path.stem,exit=call.returncode,receipt=receipt)
paths=sorted(OUT.glob('[0-9][0-9]-*.json'))
paths=[p for p in paths if '.' not in p.stem]
with ThreadPoolExecutor(max_workers=4) as pool:
    results=list(pool.map(check,paths))
for x in results:
    r=x['receipt']
    print(json.dumps(dict(page=x['page'],exit=x['exit'],diagnostics=[d['message'] for d in r.get('diagnostics',[])][:4],artifact=r.get('artifact')),ensure_ascii=False))
sys.exit(1 if any(x['exit'] for x in results) else 0)
