#!/usr/bin/env python3
import hashlib,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def main():
    index=json.loads((ROOT/'reports/EVIDENCE_INDEX.json').read_text())
    for f,h in index['files'].items():
        p=ROOT/f
        if not p.is_file() or sha(p)!=h:raise SystemExit('FAIL '+f)
    lock=json.loads((ROOT/'docs/SOURCE_LOCK.json').read_text())
    upstream=ROOT/'../../Source/alp-cwida/upstream'
    for f,h in lock['files'].items():
        if sha(upstream/f)!=h:raise SystemExit('FAIL upstream '+f)
    print('PASS',len(index['files']),'evidence files plus',len(lock['files']),'frozen upstream files')
if __name__=='__main__':main()
