"""Static CPU length/rate-quality plots from a saved study summary only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def plot(summary_path, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    summary_path=Path(summary_path);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    raw=summary_path.read_bytes();report=json.loads(raw)
    cases=report['cases'];sources=sorted({p['source_id'] for p in cases})
    fig,axes=plt.subplots(len(sources),3,figsize=(15,3.6*len(sources)),squeeze=False,constrained_layout=True)
    labels=('Complete wire / original bytes','Encode MiB/s','Decode MiB/s')
    for row,source in enumerate(sources):
        chosen=[p for p in cases if p['source_id']==source and p['task']['fidelity']=='bitwise' and p['complete']]
        for method in sorted({p['method_id'] for p in chosen}):
            points=sorted((p for p in chosen if p['method_id']==method),key=lambda p:p['raw_bytes'])
            lengths=[p['raw_bytes']//8 for p in points]
            values=[[p['stored_fraction'] for p in points],
                    [p['raw_bytes']*1e9/p['encode_ns']['median']/2**20 for p in points],
                    [p['raw_bytes']*1e9/p['decode_ns']['median']/2**20 for p in points]]
            for col in range(3):axes[row,col].plot(lengths,values[col],marker='o',label=method)
        for col in range(3):
            ax=axes[row,col];ax.set(title=f'{source}: {labels[col]}',xlabel='Values per independent object',ylabel=labels[col])
            ax.set_xscale('log',base=2);ax.grid(alpha=.25)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Fixed CPU object boundary; three sessions × seven rounds per case\nNested lengths are dependent; method curves describe these selected sources')
    fig.savefig(output/'length_cost.png',dpi=160);fig.savefig(output/'length_cost.svg');plt.close(fig)
    fig,axes=plt.subplots(len(sources),2,figsize=(13,3.6*len(sources)),squeeze=False,constrained_layout=True)
    for row,source in enumerate(sources):
        for col,length in enumerate((128,512)):
            ax=axes[row,col]
            chosen=[p for p in cases if p['source_id']==source and p['raw_bytes']==length*8 and p['complete'] and p['task']['fidelity']!='bitwise']
            for codec in sorted({p['codec'] for p in chosen}):
                points=sorted((p for p in chosen if p['codec']==codec),key=lambda p:p['quality']['max_abs']['median'])
                x=[p['quality']['max_abs']['median'] for p in points]
                y=[p['stored_bytes']['median']*8/length for p in points]
                ax.plot(x,y,marker='o',label=codec)
            ax.set_xscale('symlog',linthresh=1e-5);ax.set(xlabel='Actual maximum absolute error (original units)',ylabel='Complete bits/value',title=f'{source}, n={length}')
            ax.grid(alpha=.25)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Prespecified quality grid: original-domain error and complete stored cost\nABBA/fABBA points are empirical; connecting points is descriptive, not a selector')
    fig.savefig(output/'rate_quality.png',dpi=160);fig.savefig(output/'rate_quality.svg');plt.close(fig)
    fig,axes=plt.subplots(len(sources),2,figsize=(13,3.6*len(sources)),squeeze=False,constrained_layout=True)
    for row,source in enumerate(sources):
        chosen=[p for p in cases if p['source_id']==source and p['raw_bytes']==512*8 and p['complete'] and p['task']['fidelity']!='bitwise']
        for col,metric in enumerate(('encode_ns','decode_ns')):
            ax=axes[row,col]
            for codec in sorted({p['codec'] for p in chosen}):
                points=sorted((p for p in chosen if p['codec']==codec),key=lambda p:p['quality']['max_abs']['median'])
                x=[p['quality']['max_abs']['median'] for p in points]
                y=[p['raw_bytes']*1e9/p[metric]['median']/2**20 for p in points]
                ax.plot(x,y,marker='o',label=codec)
            operation='Encode' if col==0 else 'Decode'
            ax.set_xscale('symlog',linthresh=1e-5)
            ax.set(xlabel='Actual maximum absolute error (original units)',ylabel=f'{operation} MiB/s',title=f'{source}, n=512: {operation.lower()}')
            ax.grid(alpha=.25)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Quality and completed object throughput, n=512\nThree sessions × seven rounds; descriptive median on these selected objects')
    fig.savefig(output/'quality_speed.png',dpi=160);fig.savefig(output/'quality_speed.svg');plt.close(fig)
    trace={'schema':'tsbench.study-figure-trace/1','source_summary':str(summary_path.resolve()),'source_sha256':hashlib.sha256(raw).hexdigest(),
           'analysis_id':report['analysis_id'],'plot_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.suffix in {'.png','.svg'}},
           'points':'summary.json contains exact case/session/round/attempt and observation_line identities and input manifest/raw hashes'}
    (output/'trace.json').write_text(json.dumps(trace,indent=2)+'\n')
    print(json.dumps({'output':str(output),'analysis_id':report['analysis_id']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();plot(args.summary,args.output)
