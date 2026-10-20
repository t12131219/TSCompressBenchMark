#!/usr/bin/env python3
"""Replay frozen original-source LZSS fixtures; not an lzbench comparator."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
from tsbench.bridges import create_bridge
from tsbench.registry import Registry

ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    target=a.output.resolve();target.mkdir(parents=True,exist_ok=False);shutil.copy2(__file__,target/'audit_script.py')
    reference=ROOT/'adapters/lzss_raw/tests/fixtures/reference_vectors.json'
    d=json.loads(reference.read_text());bridge=create_bridge(ROOT,'lzss-raw');params=Registry(ROOT).resolve_params('lzss-raw');rows=[]
    sha=lambda b:hashlib.sha256(b).hexdigest()
    for item in d['cases']:
        stream=base64.b64decode(item['stream_base64']);restored=bridge.decode(stream,np.dtype('u1'),(item['length'],),params)
        assert sha(stream)==item['stream_sha256'] and sha(restored.tobytes())==item['input_sha256'],item['name']
        encoded=bridge.encode(restored,params);assert encoded==stream,item['name']
        rows.append({'name':item['name'],'input_sha256':sha(restored.tobytes()),'stream_sha256':sha(stream),'decode_input_hash_passed':True,'encode_bytes_equal':True})
    result={'comparator':'FROZEN_ORIGINAL_ALEXKAZIK_VECTORS_NOT_LZBENCH','reference':d['reference'],'fixture_path':str(reference),'fixture_sha256':sha(reference.read_bytes()),'cases':rows,'passed':len(rows)}
    (target/'results.json').write_text(json.dumps(result,indent=2)+'\n');print(len(rows),'passed')

if __name__=='__main__':main()
