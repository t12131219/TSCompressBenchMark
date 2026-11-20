#!/usr/bin/env python3
"""Generate a new synthetic civil-second multivariate input, not a new real corpus source."""
from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.smoke import write_new
from tsbench.assets import digest
from tsbench.corpus_ingress import axis_contract, fingerprint, PARTITIONS

ROWS = 4099
BOUNDS = (0, 2048, 3072, ROWS)
ID = 'm3-switch-synthetic-civil-v1'
RAW = Path('datasets/fixtures/m3-input-switch-v1/civil-periodic.csv')
MANIFEST = Path('datasets/manifests/m3-input-switch-synthetic-v1.json')


def generate(root):
    path = root/RAW
    path.parent.mkdir(parents=True,exist_ok=True)
    columns = ['timestamp','triangular_a','triangular_b','band']
    origin = datetime(2001,2,3,4,5,6)
    with path.open('x',encoding='ascii',newline='\n') as f:
        f.write(','.join(columns)+'\n')
        for row in range(ROWS):
            t = (origin+timedelta(seconds=3*row+row//97)).isoformat(sep=' ')
            a, b = row%64, (row+11)%64
            f.write(f'{t},{2+min(a,64-a)/64},{3+min(b,64-b)/32},{4+(row//64%5)/16}\n')
    entry = {'id':ID, 'source_cluster':ID, 'file':{'path':RAW.as_posix(),'bytes':path.stat().st_size,'sha256':digest(path)},
             'parser':{'format':'utf8_delimited_physical_rows_v1','separator':',','decimal':'.','timestamp':'civil_iso_seconds',
                       'missing':'reject_empty_preserve_finite'},'columns':columns,'axis':axis_contract('civil_iso_seconds'),
             'values_dtype':'<f8','rows':ROWS,'value_count':3,
             'partitions':[{'name':n,'start':BOUNDS[i],'end':BOUNDS[i+1]} for i,n in enumerate(PARTITIONS)]}
    entry.update(fingerprint(root,entry))
    write_new(root/MANIFEST,{'schema':'bmk.full-corpus/1','scope':'same_entry_synthetic_switch_v1','datasets':[entry]})


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    p.parse_args()
    generate(ROOT)
