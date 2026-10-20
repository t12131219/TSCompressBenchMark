#!/usr/bin/env python3
"""Verify exact upstream and vendor identities, then replay diff in a temp copy."""
import hashlib,json,pathlib,shutil,subprocess,tempfile
p=pathlib.Path(__file__).resolve().parents[1]
up=p/'../../Source/alp-cwida/upstream'
index=json.loads((p/'patches/INDEX.json').read_text())
sha=lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(p/'patches'/index['patch'])==index['sha256']
with tempfile.TemporaryDirectory(prefix='alp-patch-') as tmp:
    q=pathlib.Path(tmp)
    for d in ['include','src']:shutil.copytree(up/d,q/d)
    for f,lock in index['files'].items():assert sha(q/f)==lock['pre']
    subprocess.run(['patch','-p1','-i',str(p/'patches'/index['patch'])],cwd=q,check=True)
    for f,lock in index['files'].items():assert sha(q/f)==lock['post']==sha(p/'vendor'/f)
    for f in (p/'vendor').rglob('*'):
        if f.is_file():assert sha(f)==sha(q/f.relative_to(p/'vendor'))
print('PASS exact pre/post patch replay and all vendor bytes')
